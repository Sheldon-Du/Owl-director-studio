"""Measure exact spoken lines in ComfyUI, then reserve motion-only audio gaps."""
import copy,hashlib,json,time
from . import store,tts_workflow,timing,script_source

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def role(source):return source.get('speaker') or ('旁白' if source['kind']=='voiceover' else '对白')

def voice(project,source):
    name=role(source);roles=project.get('tts_voice_roles',{})
    config=roles.get(name,{}) or roles.get(source.get('speaker_id'),{})
    if config.get('tts_engine')=='yovoice':return {**config,'voice_role':name}
    return {'voice_role':name,'voice_mode':config.get('voice_mode','preset'),'voice_speaker':config.get('voice_speaker','Vivian'),'voice_filename':config.get('voice_filename'),'voice_delivery':config.get('voice_delivery',''),'voice_language':config.get('voice_language','Chinese')}

def key(source,profile):return digest({k:source.get(k) for k in ('id','source_id','kind','text','speaker')}|{'voice':profile})

def measurement(project,shot,source):
    profile=voice(project,source);cache=shot.get('speech_audio',{}).get(key(source,profile))
    if not cache or not store.media_path(cache['media']).is_file():return None
    return cache

def signature(project,shot):
    from .timing_speech import raw_catalogue
    return digest({'shot':timing.shot_signature(shot),'script':script_source.text(project,False),'lines':[{**s,'voice':voice(project,s)} for s in raw_catalogue(project,shot)]})

def prepare(project,sid,seed):
    from .timing_speech import raw_catalogue
    shot=next(s for s in project['shots'] if s['id']==sid);lines=[]
    for i,source in enumerate(raw_catalogue(project,shot)):
        profile=voice(project,source);cached=measurement(project,shot,source)
        lines.append({**source,'voice':profile,'cache_key':key(source,profile),'output_node':str(10000*(i+1)+10),'cached':bool(cached),'seed':(seed+i)%2147483647})
    uses_yovoice=any(s['voice'].get('tts_engine')=='yovoice' for s in lines)
    if any(s['voice'].get('tts_engine')!='yovoice' for s in lines):raise ValueError('本镜还有未绑定 yovoice 音色的角色，请先在声音工作台完成全部角色绑定')
    return {'yovoice_timing':uses_yovoice,'profile':'tts','media_kind':'audio','tts_engine':'owl-speech-timing','speech_timing_shot':sid,'speech_source_hash':signature(project,shot),'speech_lines':lines,'seed':seed,'prompt':'\n'.join(s['text'] for s in lines),'voice_role':'分镜对白与画外音'}

def enqueue(project,sid,seed):
    from . import jobs
    options=prepare(project,sid,seed)
    active=next((t for t in store.task_list() if t['project_id']==project['id'] and (t.get('options',{}).get('speech_timing_shot')==sid or (t['kind']=='schedule' and t.get('target')==sid)) and t['status'] in ('queued','running','cancelling')),None)
    if active:return active
    if any(not s['cached'] for s in options['speech_lines']):return jobs.enqueue('audio',project,options=options)
    raise ValueError('本镜对白已经齐全，请先声音定稿，再调用一次 AI 编排')

def enqueue_line(project,sid,identity,seed,regenerate=False):
    from . import jobs
    options=prepare(project,sid,seed)
    line=next((s for s in options['speech_lines'] if s['id']==identity),None)
    if not line:raise ValueError('本镜不存在这句对白或旁白')
    active=next((t for t in store.task_list() if t['project_id']==project['id'] and t['status'] in ('queued','running','cancelling') and
                 (t.get('options',{}).get('speech_timing_shot')==sid and any(s['id']==identity for s in t['options'].get('speech_lines',[]) if not s.get('cached')) or
                  t['kind']=='schedule' and t.get('target')==sid)),None)
    if active:return active
    if line['cached'] and not regenerate:raise ValueError('本句已有配音，可试听或选择重新生成')
    line['cached']=False
    options.update(speech_lines=[line],speech_line_only=True,prompt=line['text'],voice_role=role(line))
    return jobs.enqueue('audio',project,options=options)

def graph(options):
    metadata=tts_workflow.comfy.info();result={}
    for i,line in enumerate(options['speech_lines']):
        if line['cached']:continue
        config=tts_workflow.prepare({**line['voice'],'prompt':line['text'],'seed':line.get('seed',(options['seed']+i)%2147483647)})
        branch=tts_workflow.graph(config,metadata);namespace=int(line['output_node'])-10
        mapping={k:str(namespace+int(k)) for k in branch}
        for k,node in branch.items():
            node=copy.deepcopy(node)
            for name,value in node['inputs'].items():
                if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and value[0] in mapping:node['inputs'][name]=[mapping[value[0]],value[1]]
            result[mapping[k]]=node
    return result

def save_result(project,options,node_id,media,duration):
    shot=next((s for s in project['shots'] if s['id']==options['speech_timing_shot']),None)
    line=next((s for s in options['speech_lines'] if s['output_node']==str(node_id)),None)
    if not shot or not line or signature(project,shot)!=options['speech_source_hash']:return False
    if not duration or duration<=0:raise ValueError('配音文件没有有效实测时长')
    shot.setdefault('speech_audio',{})[line['cache_key']]={k:copy.deepcopy(line[k]) for k in ('id','source_id','kind','text','speaker','voice')}
    shot['speech_audio'][line['cache_key']].update(media=media,duration=duration,seed=line.get('seed',options['seed']),created=time.time())
    return True

def continue_review(task):
    from . import jobs
    p=store.get_project(task['project_id']);opts=task['options'];shot=next(s for s in p['shots'] if s['id']==opts['speech_timing_shot'])
    if signature(p,shot)!=opts['speech_source_hash']:raise store.Conflict('配音期间本镜或音色已修改，音频已保留，请重新测时')
    if opts.get('speech_line_only'):
        task['completion_message']='本句独立配音已保存，可试听；完成全部原句后测时并生成最终混合音轨'
        return
    from .timing_speech import raw_catalogue
    if any(not measurement(p,shot,s) for s in raw_catalogue(p,shot)):raise ValueError('部分原句未获得音频，已完成配音保留，可再次点击继续')
    task['completion_message']='本镜对白已生成并实测；请试听并确认声音定稿，再调用一次 AI 编排动作与镜头'

def track(project,shot):
    from . import speech_mix
    return speech_mix.render(project,shot)

def current(project,shot):
    saved=shot.get('speech_track',{})
    if not saved:return False
    from . import speech_mix
    expected=speech_mix.source_hash(project,shot) if saved.get('engine')=='role-mix-v1' else signature(project,shot)
    if saved.get('engine')!='role-mix-v1':
        from .timing_speech import raw_catalogue
        catalogue={s['id']:s for s in raw_catalogue(project,shot)}
        for p in saved.get('placements',[]):
            measured=measurement(project,shot,catalogue[p['speech_id']]) if p.get('speech_id') in catalogue else None
            if not measured or measured['media']!=p['media']:return False
    if not (saved.get('source_hash')==expected and store.media_path(saved['media']).is_file() and shot.get('natural_status') in ('ai_reviewed','human_reviewed')):return False
    # A matching signature cannot prove that an externally replaced file still
    # retains the complete shot, including its leading and trailing silence.
    import soundfile as sf
    try:
        info=sf.info(str(store.media_path(saved['media'])))
        return abs(info.frames-round(timing.number(shot['duration'])*info.samplerate))<=1
    except (OSError,RuntimeError,ValueError):return False

def step_audio(project,clips,duration,sampling_seconds):
    """Assemble matching shot slices without stretching, then pad frame-grid tail."""
    import numpy as np,soundfile as sf
    sr=24000;wave=np.zeros(round(sampling_seconds*sr),dtype='float32');placed=[]
    for clip in clips:
        shot=next(s for s in project['shots'] if s['id']==clip['source_id'])
        if not current(project,shot):raise ValueError('本镜配音轨缺失或已失效，请先完成 TTS 实测与动作时序')
        audio,rate=sf.read(str(store.media_path(shot['speech_track']['media'])),dtype='float32',always_2d=True)
        audio=audio.mean(axis=1)
        if rate!=sr:audio=np.interp(np.arange(round(len(audio)*sr/rate))*rate/sr,np.arange(len(audio)),audio).astype('float32')
        offset=round(clip.get('source_offset',0)*sr);length=round((clip['end']-clip['start'])*sr);start=round(clip['start']*sr)
        if offset+length>len(audio)+1 or start+length>round(duration*sr)+1:raise ValueError('H3 音轨片段与分镜时长不一致')
        chunk=audio[offset:offset+length];wave[start:start+len(chunk)]=chunk
        placed.append({'shot_id':shot['id'],'media':shot['speech_track']['media'],'start':clip['start'],'end':clip['end'],'source_offset':clip.get('source_offset',0)})
    name=store.uid()+'.wav';sf.write(str(store.media_path(name)),wave,sr,subtype='PCM_16')
    return {'media':name,'duration':duration,'sampling_seconds':sampling_seconds,'placements':placed}
