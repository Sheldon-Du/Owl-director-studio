"""Bind immutable spoken lines to AI timing segments, without retyping them."""
import copy
from . import shot_preflight

def raw_catalogue(project,shot):
    if 'sound_script' in shot:
        from . import narration_visuals
        return [{**s,'source_id':s.get('source_id',s['id']),'minimum_seconds':narration_visuals.speech_seconds([s])} for s in shot['sound_script'].get('lines',[]) if s.get('kind') in ('dialogue','voiceover') and s.get('text','').strip()]
    outline=next((o for o in project.get('storyboard_generation',{}).get('outlines',[]) if o.get('id')==shot.get('generation_outline_id')),None)
    sources=shot_preflight.speech_sources(outline) if outline else []
    selected=[s for s in sources if s['kind'] in ('dialogue','voiceover')]
    # Legacy shots without an outline still have exact accepted action lines.
    if not outline:
        for action in shot.get('actions',[]):
            for kind in ('dialogue','voiceover'):
                text=action.get(kind)
                measured=[s for s in action.get('measured_speech',[]) if s['kind']==kind]
                if measured and text=='；'.join(s['text'] for s in measured):
                    for s in measured:
                        if not any(r['kind']==kind and r['text']==s['text'] for r in selected):selected.append({'kind':kind,'text':s['text'],'speaker':s.get('speaker','')})
                    continue
                if text and not any(s['kind']==kind and s['text']==text for s in selected):selected.append({'kind':kind,'text':text,'speaker':''})
    from . import narration_visuals
    return [{**s,'source_id':s.get('id'),'id':f'speech_{i+1}','minimum_seconds':narration_visuals.speech_seconds([s])} for i,s in enumerate(selected)]

def catalogue(project,shot):
    from . import speech_audio
    result=raw_catalogue(project,shot)
    for source in result:
        measured=speech_audio.measurement(project,shot,source)
        if measured:source.update(minimum_seconds=measured['duration'],measured_seconds=measured['duration'],audio_media=measured['media'],timing_basis='TTS实际音频，不变速')
    return result

def bind(actions,sources):
    if not isinstance(actions,list) or not actions or any(not isinstance(a,dict) for a in actions):raise ValueError('时序需返回非空动作对象列表')
    result=copy.deepcopy(actions);index={s['id']:s for s in sources};carried=[]
    for action in result:
        ids=action.get('speech_ids')
        if ids is None:
            ids=[]
            for kind in ('dialogue','voiceover'):
                text=action.get(kind,'')
                if text in ('','无','无对白','无台词','无旁白','N/A','None','none',None):continue
                matches=[s['id'] for s in sources if s['kind']==kind and s['text']==text]
                if len(matches)!=1:raise ValueError('时序台词必须选择本镜原句编号，不可改写或添加')
                ids.extend(matches)
        if not isinstance(ids,list) or any(not isinstance(i,str) or i not in index for i in ids):raise ValueError('动作speech_ids需引用本镜speech_sources原句编号')
        carried.extend(ids);action['speech_ids']=ids
        action['speech_source_ids']=[index[i]['source_id'] for i in ids if index[i].get('source_id')]
        for kind in ('dialogue','voiceover'):action[kind]='；'.join(index[i]['text'] for i in ids if index[i]['kind']==kind)
        if ids and all(index[i].get('measured_seconds') for i in ids):
            duration=sum(index[i]['measured_seconds'] for i in ids)
            action['measured_speech_seconds']=duration
            action['measured_speech']=[{'id':i,'kind':index[i]['kind'],'text':index[i]['text'],'speaker':index[i].get('speaker',''),'media':index[i]['audio_media'],'duration':index[i]['measured_seconds']} for i in ids]
            for field in ('natural_seconds','minimum_seconds','maximum_seconds'):
                action[field]=max(float(action.get(field) or 0),duration)
            action['rationale']=str(action.get('rationale',''))+f'；人声采用TTS实测{duration:.3f}秒，和动作同时发生时取较长者，不压缩音频。'
    if len(carried)!=len(set(carried)):raise ValueError('本镜原句只能播放一次，不能重复分配到动作段')
    missing=set(index)-set(carried)
    if missing:raise ValueError('时序拆解遗漏本镜原句编号：'+ '、'.join(sorted(missing)))
    return result
