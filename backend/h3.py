"""Adapt reviewed native storyboards to timed, English MiniMax H3 prompts."""
import hashlib
import copy
import json
import math
import os
import re
from pathlib import Path
from . import ai,director,timing,asset_references,frame_reference_sets,script_source,seedance_integration,character_mod,visual_reference,h3_voice,shot_references

MAX_SECONDS=30
OFFICIAL_MAX_SECONDS=15
MIN_SECONDS=4
REWRITE_ATTEMPTS=3
GUIDE=Path(os.environ.get('H3_PROMPT_GUIDE',r'C:\Users\40883\.codex\skills\h3-prompt-writing\references'))


def scope(project, shot_id=None,allow_reference_prepare=False):
    """A reviewed shot can proceed independently of the remaining film."""
    if not shot_id:
        from . import performance
        for row in project.get('shots',[]):performance.gate(project,row)
        return project
    from . import shot_merge
    group=None if project.get('_ignore_h3_group') else shot_merge.group_for(project,shot_id)
    if group:
        parts=[scope({**project,'_ignore_h3_group':True},sid,allow_reference_prepare) for sid in group['shot_ids']]
        scoped=copy.deepcopy(parts[0]);scoped.pop('_ignore_h3_group',None)
        scoped['shots']=[s for part in parts for s in part['shots']]
        scoped['duration']=sum(s['duration'] for s in scoped['shots'])
        ids={a['id'] for part in parts for a in part.get('assets',[])}
        scoped['assets']=[copy.deepcopy(a) for a in project.get('assets',[]) if a['id'] in ids]
        scoped['_h3_reference_assignments']=[r for part in parts for r in part.get('_h3_reference_assignments',[])]
        scoped['h3_scope_shot']=group['shot_ids'][0]
        return scoped
    if not script_source.ready(project):raise ValueError('请先填写故事或有效剧本')
    shot=next((s for s in project.get('shots',[]) if s['id']==shot_id),None)
    if not shot or not shot.get('native'):raise ValueError('请先生成本镜的原生分镜')
    from . import shot_continuity,performance
    performance.gate(project,shot)
    shot_continuity.gate(project,shot_id)
    from . import storyboard_generation as sg
    state=project.get('storyboard_generation')
    if state:
        if not sg.valid_state(project) or shot.get('generation_source_hash')!=state.get('source_hash'):
            raise ValueError('本镜的剧本或镜头与美术方案已变更，请重新生成本镜')
    elif not project.get('native_storyboard_current'):
        raise ValueError('镜头与美术方案已变更，请重新生成原生分镜')
    checked=timing.validate(shot)
    if not checked['ok']:raise ValueError('请先审定本镜自然动作时序：'+'；'.join(checked['errors']))
    mode=shot.get('h3_reference_mode','auto')
    if mode not in ('auto','assets','first_frame','previous_tail','text'):raise ValueError('不支持的 H3 参考来源')
    if mode=='assets' and not allow_reference_prepare and not frame_reference_sets.assignments(project,shot):raise ValueError('本镜没有可用资产参考图，请绑定元素并采用图片，或选择首帧')
    if mode in ('first_frame','previous_tail') and not shot.get('first_frame'):raise ValueError('请先采用本镜首帧，或提取并采用上一镜尾帧')
    if mode=='previous_tail' and shot.get('previous_tail_reference',{}).get('media')!=shot.get('first_frame'):
        raise ValueError('请重新提取并采用上一镜尾帧')
    scoped=copy.deepcopy(project)
    scoped['_full_script']=script_source.text(project,False)
    scoped['_production_source_kind']=script_source.kind(project)
    scoped['_speech_speaker_ids']=speaker_ids(project)
    from . import skill_workflows
    scoped['_skill_prompt_rules']={purpose:skill_workflows.prompt_rules(project,purpose) for purpose in ('image','video','audio')}
    scoped.update(shots=[copy.deepcopy(shot)],duration=shot['duration'],confirmed=True,native_storyboard_current=True,h3_scope_shot=shot_id)
    ids=frame_reference_sets.asset_ids(project,shot)
    scoped['shots'][0]['asset_ids']=ids
    scoped['shots'][0]['reference_stages']=frame_reference_sets.stages(project,shot)
    scoped['_h3_reference_assignments']=frame_reference_sets.assignments(project,shot)
    if mode in ('auto','assets'):
        referenced={r['asset_id'] for r in scoped['_h3_reference_assignments']}
        missing=[a['name'] for a in project.get('assets',[]) if a['id'] in frame_reference_sets.character_ids(project,shot) and a['id'] not in referenced]
        if missing:raise ValueError('本镜角色缺少可用参考：'+'、'.join(missing)+'；请先采用角色图片并制作角色mod，不能仅凭道具参考生成角色')
    scoped['assets']=[a for a in scoped.get('assets',[]) if a['id'] in ids]
    if state and state.get('preparation'):
        scoped['documents']['storyboard_native']=sg.assemble(state['preparation'],[sg.current_row(shot,1)])
    return scoped


def package(project, shot_id=None):
    documents=project.get('documents',{})
    from . import shot_merge
    return documents.get('h3_shots',{}).get(shot_merge.leader(project,shot_id)) if shot_id else documents.get('h3')


def source_hash(project, shot_id=None):
    return fingerprint(scope(project,shot_id))


def is_current(project, saved, shot_id=None):
    try:
        if saved and any(s.get('mode')=='T2VA' for s in saved.get('steps',[])):
            selected=[s for s in project.get('shots',[]) if not shot_id or s['id']==shot_id]
            if any(s.get('h3_reference_mode','auto')!='text' for s in selected):return False
        return bool(saved) and saved.get('source_hash')==source_hash(project,shot_id)
    except ValueError:return False


def rewrite_complete(project, shot_id):
    """Only a complete, current shot package can be reused by batch rewrite."""
    saved=package(project,shot_id)
    if not is_current(project,saved,shot_id):return False
    steps=saved.get('steps')
    return bool(isinstance(steps,list) and steps and all(
        isinstance(step,dict) and str(step.get('prompt') or '').strip() and
        str(step.get('prompt_zh') or '').strip() for step in steps))


def fingerprint(project):
    data=source_manifest(project)
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def source_manifest(project):
    """Compare only inputs actually supplied to the H3 writer and renderer."""
    from . import character_profiles
    assets=[{'id':a['id'],'name':a.get('name'),'description':a.get('description'),
             'references':asset_references.effective(a),'character_mod':character_mod.current(a),
             'voice':a.get('voice'), 'personality':character_profiles.personality_notes(a) if a.get('kind')=='character' else None} for a in project.get('assets',[])]
    data={k:project.get(k) for k in ('duration','production_scheme','h3_settings')}
    data['reference_contract']='voice-timbre-three-frames-v2'
    if project.get('h3_shot_groups'):data['h3_shot_groups']=project['h3_shot_groups']
    names={line.get('speaker') for s in project.get('shots',[]) for line in s.get('sound_script',{}).get('lines',[])}
    data['voice_roles']={k:v for k,v in project.get('tts_voice_roles',{}).items() if not project.get('h3_scope_shot') or k in names}
    data.update(script=([{'id':s['id'],'creative':s.get('creative_storyboard_prompt') or s.get('description'),'lines':s.get('sound_script')} for s in project.get('shots',[])] if project.get('h3_scope_shot') else script_source.text(project,False)),art=project.get('documents',{}).get('art'),assets=assets)
    data['applied_art_style']=visual_reference.art(project)
    data['shot_cameras']=[{'id':s['id'],'settings':visual_reference.active_camera(s),'fragments':[{'id':f['id'],'duration':f['duration'],'prompt':f['prompt'],'camera':visual_reference.active_camera(f),'frame_cards':f.get('frame_cards'),'first_frame':f.get('first_frame'),'tail_frame':f.get('adopted_tailframe')} for f in s.get('merged_from',[])]} for s in project.get('shots',[])]
    from . import skill_workflows
    data['adopted_skill_rules']={purpose:skill_workflows.prompt_rules(project,purpose) for purpose in ('video','audio')}
    if project.get('h3_scope_shot'):data.update(scope_shot=project['h3_scope_shot'],parameters=project.get('parameters'))
    shot_fields=('seedance_sections','creative_storyboard_prompt','performance','camera_override','id','duration','description','prompt','native','actions','asset_ids','h3_reference_mode','first_frame','last_frame')
    shot_fields+=('frame_cards','adopted_keyframe','adopted_tailframe','h3_frame_roles')
    data['shots']=[{k:s.get(k) for k in shot_fields} for s in project.get('shots',[])]
    for row,shot in zip(data['shots'],project.get('shots',[])):
        if examples:=shot_references.guidance(shot):row['shot_examples']=examples
    if any(s.get('speech_track') or s.get('h3_audio_mode') for s in project.get('shots',[])):
        data['speech_tracks']=[{'shot_id':s['id'],'audio_mode':s.get('h3_audio_mode','auto'),'track':s.get('speech_track')} for s in project['shots']]
        used={p['speaker'] for s in project['shots'] for p in s.get('speech_track',{}).get('placements',[])}
        data['speaker_ids']={k:v for k,v in speaker_ids(project).items() if k in used}
    data['reference_stages']=[{'shot_id':s['id'],'stages':frame_reference_sets.stages(project,s)} for s in project.get('shots',[]) if s.get('image_plans') or s.get('adopted_keyframe')]
    data['reference_assignments']=project.get('_h3_reference_assignments',[])
    from . import stage3d
    data['stage3d']=[{'shot_id':s['id'],'previs':stage3d.h3_reference(project,s)} for s in project.get('shots',[]) if s.get('stage3d')]
    return data

def speaker_ids(project):
    if project.get('_speech_speaker_ids'):return project['_speech_speaker_ids']
    from . import speech_audio,timing_speech
    result={}
    for shot in project.get('shots',[]):
        rows=sorted(shot.get('speech_track',{}).get('placements',[]),key=lambda p:p['start'])
        names=[p['speaker'] for p in rows if p.get('gain',1)>0] if rows else [speech_audio.role(s) for s in timing_speech.raw_catalogue(project,shot)]
        for name in names:
            if name not in result:result[name]='S'+str(len(result)+1)
    return result


def groups(project):
    from . import stage3d,performance
    from . import speech_audio
    if not script_source.ready(project):raise ValueError('请先填写故事或有效剧本')
    if not project.get('native_storyboard_current'):raise ValueError('镜头与美术方案已变更，请重新生成原生分镜')
    if not project.get('confirmed'):raise ValueError('请审定自然动作时序并确认分镜后转写 H3')
    shots=project.get('shots',[])
    if not shots:raise ValueError('请先生成原生分镜')
    director.validate_project_shots(project)
    cursor=0;timeline=[];safe=[];spoken_intervals=[]
    for shot in shots:
        timing.render(shot)
        if h3_voice.locked(shot) and not speech_audio.current(project,shot):raise ValueError('锁定原配音轨前，请先更新本镜最终配音轨')
        duration=timing.number(shot['duration'])
        timeline.append((cursor,cursor+duration,shot))
        safe.extend(cursor+timing.number(a['end']) for a in shot['actions'])
        if speech_audio.current(project,shot):
            for p in shot['speech_track']['placements']:
                if p.get('gain',1)<=0:continue
                spoken_intervals.append((cursor+p['start'],cursor+p['end']))
                safe.extend([cursor+p['start'],cursor+p['end']])
        if not h3_voice.locked(shot) and shot.get('performance'):
            cat={r['speech_id']:r for r in performance.rows(project,shot)}
            for row in shot['performance'].get('speech',[]):
                if row.get('gain',1)>0:
                    left=cursor+row['start'];right=left+cat[row['speech_id']]['duration']
                    spoken_intervals.append((left,right));safe.extend([left,right])
        cursor+=duration
    safe=[v for v in safe if not any(left+1e-7<v<right-1e-7 for left,right in spoken_intervals)]
    if abs(cursor-timing.number(project['duration']))>.02:raise ValueError('分镜总时长与项目时长不一致')
    if cursor<=0:raise ValueError('镜头时长必须大于零')
    maximum=timing.number(project.get('h3_settings',{}).get('max_step_seconds',MAX_SECONDS))
    if maximum not in (15,30):raise ValueError('H3 提示词任务上限请选择15或30秒')
    from . import shot_merge
    # Explicit pairs are production groups only; original shot boundaries,
    # durations, frame cards and audio remain untouched.
    units=[]
    if project.get('h3_shot_groups'):
        i=0
        while i<len(timeline):
            left,_,shot=timeline[i];group=shot_merge.group_for(project,shot['id'])
            end_index=i+len(group['shot_ids'])-1 if group else i
            if end_index>=len(timeline):raise ValueError('H3分组缺少第二片段')
            units.append((left,timeline[end_index][1]));i=end_index+1
    else:units=[(0.0,cursor)]
    bounds=[0.0]
    for unit_start,unit_end in units:
        count=math.ceil(round(unit_end-unit_start,8)/maximum)
        for i in range(1,count):
            remaining=count-i
            lower=max(bounds[-1]+MIN_SECONDS,unit_end-remaining*maximum)
            upper=min(bounds[-1]+maximum,unit_end-remaining*MIN_SECONDS)
            target=bounds[-1]+(unit_end-bounds[-1])/(remaining+1)
            candidates=[v for v in safe if lower-1e-7<=v<=upper+1e-7]
            boundary=min(candidates,key=lambda v:abs(v-target)) if candidates else target
            if any(left+1e-7<boundary<right-1e-7 for left,right in spoken_intervals):
                raise ValueError('H3分段会切断实测配音或重叠对白，请调整分镜/配音落点，或先将长原句拆段，不截断或变速')
            bounds.append(boundary)
        bounds.append(unit_end)
    # Round shared boundaries once, so adjacent segment durations telescope to
    # the exact source duration rather than independently losing microseconds.
    bounds=[round(v,6) for v in bounds]
    result=[]
    for index,(start,end) in enumerate(zip(bounds,bounds[1:]),1):
        clips=[]
        selected=[shot for ss,se,shot in timeline if min(end,se)-max(start,ss)>1e-7]
        if any(h3_voice.locked(s) for s in selected) and not all(h3_voice.locked(s) for s in selected):raise ValueError('同一H3任务不能混用锁定音轨与声音参考，请统一本组声音来源或拆开任务')
        step_bound=all(h3_voice.locked(shot) and speech_audio.current(project,shot) for ss,se,shot in timeline if min(end,se)-max(start,ss)>1e-7)
        for ss,se,shot in timeline:
            left=max(start,ss);right=min(end,se)
            if right-left<1e-7:continue
            bound=step_bound
            actions=[]
            for number,a in enumerate(shot['actions']):
                a_start=ss+timing.number(a['start']);a_end=ss+timing.number(a['end'])
                al=max(left,a_start);ar=min(right,a_end)
                if ar-al<1e-7:continue
                partial=al>a_start+1e-7 or ar<a_end-1e-7
                if partial and not bound and (a.get('dialogue') or a.get('voiceover')):
                    raise ValueError(f'分段边界穿过整段对白或旁白，请在“编辑与时序”按原文句段拆开说话动作，每段不超过{maximum:g}秒，再确认分镜并转写H3；不删台词、不加速')
                actions.append({**a,'key':shot['id']+':'+str(number),'start':round(al-start,6),'end':round(ar-start,6),'natural_seconds':round(ar-al,6),'source_natural_seconds':timing.number(a['end'])-timing.number(a['start']),'source_action_offset':round(al-a_start,6),'continuation':partial})
                if bound:
                    # Soundtrack time is independent of the physical action slots.
                    actions[-1].update(dialogue='',voiceover='')
            clips.append({'source_id':shot['id'],'source_offset':round(left-ss,6),'start':round(left-start,6),'end':round(right-start,6),'description':shot['description'],'creative_storyboard_prompt':performance.creative_prompt(shot),'finalized_storyboard_prompt':performance.finalized_prompt(project,shot),'native_prompt':shot['prompt'] if shot.get('camera_override',{}).get('enabled') else None,'performance_timeline':copy.deepcopy(shot.get('performance')),'camera_override':visual_reference.active_camera(shot),'merged_fragments':visual_reference.fragments(shot,left-ss,right-left),'native':{} if shot.get('performance') else shot.get('native',{}),'asset_ids':frame_reference_sets.asset_ids(project,shot),'reference_stages':frame_reference_sets.stages(project,shot),'previs':stage3d.h3_reference(project,shot),'reference_mode':shot.get('h3_reference_mode','auto'),'first_frame':shot.get('first_frame') if abs(left-ss)<1e-7 else None,'last_frame':shot.get('last_frame') if abs(right-se)<1e-7 else None,'continues_from_previous':left>ss+1e-7,'continues_to_next':right<se-1e-7,'actions':actions})
            if examples:=shot_references.guidance(shot):clips[-1]['shot_examples']=examples
            group=shot_merge.group_for(project,shot['id'])
            clips[-1].update(frame_cards=copy.deepcopy(shot.get('frame_cards',{})),adopted_keyframe=shot.get('adopted_keyframe'),adopted_tailframe=shot.get('adopted_tailframe'),segment=group['shot_ids'].index(shot['id'])+1 if group else None,h3_frame_roles=copy.deepcopy(shot.get('h3_frame_roles')))
            if bound or shot.get("performance"):
                from . import timing_speech
                original={s['id']:s for s in timing_speech.raw_catalogue(project,shot)}
                if not bound:
                    catalogue={r['speech_id']:r for r in performance.rows(project,shot)}
                    placements=[{**catalogue[r['speech_id']],**r,'end':r['start']+catalogue[r['speech_id']]['duration']} for r in shot.get('performance',{}).get('speech',[])]
                else:placements=shot['speech_track']['placements']
                clips[-1]['speech_timeline']=[{**original.get(p['speech_id'],{}),**p,'start':round(ss+p['start']-start,6),'end':round(ss+p['end']-start,6)} for p in placements if p['start']>=left-ss-1e-7 and p['end']<=right-ss+1e-7 and p.get('gain',1)>0]
        result.append({'index':index,'start':round(start,6),'end':round(end,6),'duration':round(end-start,6),'clips':clips})
    return result


def reference_catalog(project):
    pictures=[];subjects=[];by_media={};by_subject={};image_count=0;video_count=0
    assignments=project.get('_h3_reference_assignments')
    if assignments is None:assignments=[r for shot in project.get('shots',[]) for r in frame_reference_sets.assignments(project,shot)]
    for ref in assignments:
        asset=next((a for a in project['assets'] if a['id']==ref['asset_id']),None)
        if not asset:continue
        mod=character_mod.current(asset)
        media=ref['media'];identity=('mod',mod['name']) if mod else ('image',media)
        if identity not in by_media:
            by_media[identity]=len(pictures)
            if mod:
                video_count+=1;label=f'<Video {video_count}>'
            else:
                image_count+=1;label=f'<Picture {image_count}>'
            pictures.append({'label':label,'media':media,'bindings':[],**({'refmod':copy.deepcopy(mod),'media_type':'video'} if mod else {})})
        picture=pictures[by_media[identity]]
        variant=asset.get('variant',{});root=variant.get('parent_id') or asset['id']
        binding={'asset_id':asset['id'],'role':ref.get('role','identity'),'note':ref.get('note',''),'usage':ref.get('usage',''),'stage':ref.get('stage','shared'),'relationship':ref.get('relationship',''),'same_subject_id':root,'state':ref.get('state') or variant.get('intent','')}
        if binding not in picture['bindings']:picture['bindings'].append(binding)
        if root not in by_subject:
            subject={'label':f'<Subject {len(subjects)+1}>','asset_id':asset['id'],'asset_ids':[],'same_subject_id':root,'name':variant.get('parent_name') or asset['name'],'description':asset['description'],'pictures':[],'states':[]}
            by_subject[root]=subject;subjects.append(subject)
        subject=by_subject[root]
        if asset['id'] not in subject['asset_ids']:subject['asset_ids'].append(asset['id'])
        if picture['label'] not in subject['pictures']:subject['pictures'].append(picture['label'])
        state={'asset_id':asset['id'],'stage':ref.get('stage','shared'),'picture':picture['label'],'description':asset['description'],'change':variant.get('intent','')}
        if state not in subject['states']:subject['states'].append(state)
    return pictures,subjects


def mode_for(step,pictures,subjects):
    selection=step['clips'][0].get('reference_mode','auto')
    if all(c.get('reference_mode','auto')=='text' for c in step['clips']):return 'T2VA',[],[]
    from . import h3_segment_references
    return h3_segment_references.mode_for(step,pictures,subjects)


def english(value,allow_shot_labels=False,language="en"):
    if not isinstance(value,str) or not value.strip():raise ValueError('H3 转写缺少英文描述')
    # Original spoken words and visible written text remain in their language.
    prose=re.sub(r'<d>.*?</d>|"[^"]*"','',value,flags=re.S)
    if language!='zh' and re.search(r'[\u3400-\u9fff]',prose):raise ValueError('H3 描述需为英文；原文对白和画面文字可保留原语言')
    if re.search(r'\b(?:slow[- ]motion|fast[- ]forward|teleport|speed up|speeding up)\b',prose,re.I):raise ValueError('H3 转写试图改变自然动作速度，请重试')
    if not allow_shot_labels and re.search(r'\[Shot\s+\d+\]|\bAt\s+\d\d:\d\d',value):raise ValueError('H3 镜头编号与切点由已审定时间表生成，请重试')
    return value.strip()


def cut_time(seconds):
    ms=round(seconds*1000)
    return f'{ms//60000:02}:{ms//1000%60:02}.{ms%1000:03}'


def rewrite_contract(step,mode):
    """Expose short per-request identities; persisted IDs and timing stay local."""
    request=copy.deepcopy(step)
    reserved={c['source_id'] for c in step['clips']}|{a['key'] for c in step['clips'] for a in c['actions']}
    prefix=''
    while any(prefix+f'clip_{i}' in reserved or any(prefix+f'action_{i}_{j}' in reserved for j in range(1,len(c['actions'])+1)) for i,c in enumerate(step['clips'],1)):
        prefix+='local_'
    for i,clip in enumerate(request['clips'],1):
        clip['source_id']=prefix+f'clip_{i}'
        for j,action in enumerate(clip['actions'],1):action['key']=prefix+f'action_{i}_{j}'
    template={'shots':[{'source_id':c['source_id'],'description':'','actions':[{'key':a['key'],'text':''} for a in c['actions']]} for c in request['clips']],
              'overall_soundscape':'','non_diegetic_music':'N/A','continuity_in':'','continuity_out':''}
    if mode=='Ref2VA':template.update(subject_definitions='',summary='',retention_analysis='')
    return request,template


def match_records(records,identities,field,label):
    """Reorder only explicitly identified rows. Never guess a missing identity."""
    if not isinstance(records,list):raise ValueError(label+'需为数组')
    aliases={identity:index for index,pair in enumerate(identities) for identity in pair}
    matched={}
    for record in records:
        if not isinstance(record,dict):raise ValueError(label+'条目需为对象')
        identity=record.get(field)
        if not isinstance(identity,str) or identity not in aliases:
            raise ValueError(label+'标识缺失或无效；'+field+'必须逐字使用：'+', '.join(pair[0] for pair in identities))
        index=aliases[identity]
        if index in matched:raise ValueError(label+'标识重复：'+identities[index][0])
        matched[index]=copy.deepcopy(record)
    missing=[pair[0] for index,pair in enumerate(identities) if index not in matched]
    if missing:raise ValueError(label+'遗漏：'+', '.join(missing))
    return [matched[index] for index in range(len(identities))]


def normalize_rewrite(step,request,answer):
    if not isinstance(answer,dict):raise ValueError('H3 转写需返回 JSON 对象')
    result=copy.deepcopy(answer)
    descriptions=match_records(result.get('shots'),[(wire['source_id'],native['source_id']) for native,wire in zip(step['clips'],request['clips'])],'source_id','H3 镜头')
    for i,(native,wire,written) in enumerate(zip(step['clips'],request['clips'],descriptions),1):
        written['source_id']=native['source_id']
        actions=match_records(written.get('actions'),[(w['key'],a['key']) for a,w in zip(native['actions'],wire['actions'])],'key',f'H3 第{i}镜动作')
        for original,action in zip(native['actions'],actions):action['key']=original['key']
        written['actions']=actions
    result['shots']=descriptions
    return result


def rewrite_step(step,mode,refs,subjects,system,payload,report):
    from . import h3_reference_limits,store
    request,template=rewrite_contract(step,mode)
    source={**payload,'step':request,'output_template':template,'writing_stage':'complete_prompt_first'}
    if len(request['clips'])>1:
        from . import h3_segment_references
        source['per_shot_reference_scope']=h3_segment_references.scope_contract(request,refs,subjects)
        for clip,scope in zip(request['clips'],source['per_shot_reference_scope']):clip['reference_scope']=scope
    system+='\n对白原句、说话时间、发声角色和参考编号由程序固定。你只输出英文画面、摄影和非对白声音描述，严禁输出<d>台词；不要重写对白或自行添加发声时间。原始对白仅供理解表演语境。\n本次采用两步流程：第一步先生成完整英文提示词，本步最终组装目标不超过6000字符，提前精简重复描述，但不删动作或参考；程序会在完整渲染后计数，超长保留原稿并进行独立精简，保存每轮修改记录。遵守output_template结构，逐字保留全部source_id/action key，全部分镜动作对白时间与引用范围不能增删或串镜。只输出完整JSON，不输出推理或规则说明。每镜reference_scope限定本镜Subject和媒体标签，required_frames在对应镜头正文落实。'
    if payload.get('_five_source_input'):
        from . import h3_input
        source=h3_input.build(step,request,template,mode,refs,subjects,payload)
        system=h3_input.SYSTEM
    chinese=bool(payload.get('_direct_chinese'))
    history=[];history_file=None
    if chinese:
        folder=store.DATA/'h3-full-prompt-drafts';folder.mkdir(exist_ok=True)
        history_file=folder/(store.uid()+'.json')
    def save_history():
        if history_file:history_file.write_text(json.dumps({'language':'zh','step':step,'attempts':history},ensure_ascii=False,indent=2),encoding='utf-8')
    previous=None;error=None;complete=None;adapted=None
    for attempt in range(REWRITE_ATTEMPTS):
        data=source if not attempt else {**source,'validation_error':error,'previous_response':previous,'repair_instruction':'只修正结构、身份、原文对白或引用范围校验问题，保留其他完整内容。同时保持6000字符最终预算。'}
        if attempt:report(f'第 {step["index"]} 步完整 H3 校验纠正 {attempt}/{REWRITE_ATTEMPTS-1}：{error[:220]}')
        record={'attempt':attempt+1,'request':data,'status':'pending'}
        history.append(record);save_history()
        try:
            with ai.asset_call_policy('h3_rewrite',limit=1,max_tokens=32768,timeout=300,preserve_context=True,report=report,reasoning_effort='low'):
                previous=ai.ask(system,json.dumps(data,ensure_ascii=False))
        except ValueError as failure:
            if not str(failure).startswith('AI 未返回有效 JSON'):raise
            error=str(failure)
        else:
            try:
                from . import h3_edit
                record['response']=previous;save_history()
                adapted=h3_edit.canonical_visual(step,normalize_rewrite(step,request,previous))
                if chinese:adapted['_language']='zh'
                complete=render_step(step,adapted,mode,refs,subjects,enforce_length=chinese)
                if chinese:
                    complete.update(language='zh',prompt_zh=complete['prompt'],generation_history=history_file.name)
                record.update(status='completed',output=complete);save_history()
                break
            except ValueError as failure:
                complete=None;error=str(failure)
        record.update(status='failed',error=error);save_history()
    if complete is None:raise ValueError(f'H3 第{step["index"]}步完整提示词校验失败：{error}；原分镜及已有提示词保留'+(f'；修改记录：{history_file.name}' if history_file else ''))
    count=h3_reference_limits.prompt_length(complete['prompt'])
    if count<=5992:return complete
    folder=store.DATA/'h3-full-prompt-drafts';folder.mkdir(exist_ok=True)
    draft=folder/(store.uid()+'.json')
    draft.write_text(json.dumps({'step':step,'mode':mode,'full_output':complete,'adapted':adapted,'original_characters':count},ensure_ascii=False,indent=2),encoding='utf-8')
    report(f'英文 H3 共{count}字符，超过6000字符预算；改写为中文，保留英文原稿和修改记录')
    history=[]
    body=json.loads(draft.read_text(encoding='utf-8'))
    def checkpoint():
        body['chinese_fallback']={'status':'running','attempts':history}
        draft.write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        chinese=translate_prompt(complete['prompt'],step['index'],report,history=history,checkpoint=checkpoint)
        from . import h3_reference_limits
        final_count=h3_reference_limits.prompt_length(chinese)+8
        if final_count>6000:raise ValueError(f'中文改写后仍超6000字符预算（含预留共{final_count}字符），请拆分分组；不会截断对白或动作')
        output={**complete,'prompt':chinese,'prompt_zh':chinese,'prompt_english':complete['prompt'],'language':'zh'}
        output['language_fallback']={'reason':'english_over_budget','english_characters':count,'chinese_characters':final_count-8,'full_draft':draft.name}
        body['chinese_fallback']={'status':'completed','attempts':history,'output':output}
        report(f'中文改写通过：英文{count}字符 → 中文{final_count-8}字符，作为实际视频生成提示词')
        return output
    except ValueError as error:
        body['chinese_fallback']={'status':'failed','attempts':history,'error':str(error)}
        raise ValueError(f'H3超长英文稿转中文未通过：{error}；英文原稿及修改记录已保留：{draft.name}') from error
    finally:
        draft.write_text(json.dumps(body,ensure_ascii=False,indent=2),encoding='utf-8')



def rewrite_lengths(answer):
    if not isinstance(answer,dict):return {}
    fields={k:len(str(answer.get(k,''))) for k in ('subject_definitions','summary','retention_analysis','overall_soundscape','non_diegetic_music')}
    fields['shots']=[{'source_id':s.get('source_id'),'description':len(str(s.get('description',''))),'actions':[{'key':a.get('key'),'text':len(str(a.get('text','')))} for a in s.get('actions',[]) if isinstance(a,dict)]} for s in answer.get('shots',[]) if isinstance(s,dict)] if isinstance(answer.get('shots'),list) else []
    return fields


def rewrite_budget(step,mode,refs,subjects):
    """Reserve rendering syntax, then allocate prose by actual clips/actions."""
    action_count=sum(len(c['actions']) for c in step['clips'])
    # Spoken originals and fixed timeline syntax cannot be compressed away.
    speech=sum(len(str(a.get('dialogue','')))+50 if a.get('dialogue') else 0 for c in step['clips'] for a in c['actions'])
    speech+=sum(len(p['text'])+250 for c in step['clips'] for p in c.get('speech_timeline',[]))
    from . import h3_segment_references
    mapping_size=len(h3_segment_references.mapping(refs)) if len(step['clips'])>1 else 0
    overhead=mapping_size+450+len(step['clips'])*75+action_count*65+len(frame_reference_sets.rules(refs))
    available=max(0,6000-overhead-speech)
    target=min(available,2600+int(step['duration'])*80)
    analysis=int(target*.30) if mode=='Ref2VA' else 0
    sound=min(300,int(target*.10));music=80
    visual=max(0,target-analysis-sound-music)
    per_clip=int(visual*.35/max(1,len(step['clips'])))
    per_action=int(visual*.65/max(1,action_count))
    return {'final_render_max_characters':6000,'preferred_render_max_characters':6000,'prose_target_characters':target+speech,
            'subject_definitions':int(analysis*.55),'summary':int(analysis*.15),'retention_analysis':int(analysis*.30),
            'overall_soundscape':sound,'non_diegetic_music':music,'continuity_in':240,'continuity_out':240,
            'shots':[{'source_id':c['source_id'],'description':per_clip,'actions':[{'key':a['key'],'text':per_action+(len(str(a.get('dialogue','')))+50 if a.get('dialogue') else 0)} for a in c['actions']]} for c in step['clips']],
            'rule':'字符预算不是最低篇幅；仅转写本步实际内容。原始对白及所有动作优先保留，禁止硬截断文本。'}


def render_step(step,adapted,mode,refs,subjects,enforce_length=True):
    from . import h3_edit
    validate_prose=lambda value,allow_shot_labels=False:english(value,allow_shot_labels,language=adapted.get('_language','en'))
    adapted=h3_edit.canonical_visual(step,adapted)
    if mode=='Ref2VA':
        from . import h3_segment_references
        h3_segment_references.validate_scopes(step,adapted,refs,subjects)
        adapted={**adapted,'retention_analysis':str(adapted.get('retention_analysis',''))+'\n'+h3_segment_references.mapping(refs)}
    descriptions=adapted.get('shots',[])
    if [s.get('source_id') for s in descriptions]!=[s['source_id'] for s in step['clips']]:raise ValueError('H3 转写遗漏或重排原生镜头')
    blocks=[];allowed_labels={p['label'] for p in refs}|{s['label'] for s in subjects}
    for index,(clip,written) in enumerate(zip(step['clips'],descriptions),1):
        text=validate_prose(written.get('description'))
        source=clip['actions'];actions=written.get('actions',[])
        if [a.get('key') for a in actions]!=[a['key'] for a in source]:raise ValueError('H3 转写遗漏或重排自然动作')
        for action,words in zip(source,actions):
            description=validate_prose(words.get('text'))
            spoken=re.findall(r'<d>\[([^]]+)\]\s*(.*?)</d>',description,re.S)
            dialogue=str(action.get('dialogue','')).strip()
            if spoken:raise ValueError('画面描述中不应重复对白；对白由程序按审定时间统一写入')
            if dialogue and not step.get('audio_binding'):
                language='Chinese' if re.search(r'[\u4e00-\u9fff]',dialogue) else 'English'
                description+=f' <d>[{language}] {dialogue}</d>'
            text+=f" From {action['start']:.2f} to {action['end']:.2f} seconds: {description}"
        if clip.get('speech_timeline'):
            bindings={b['speaker']:b for b in step.get('speaker_bindings',[])}
            for p in sorted(clip.get('speech_timeline',[]),key=lambda r:r['start']):
                binding=bindings.get(p['speaker'],{'speaker_id':p['speaker']});identity='('+binding['speaker_id']+')'
                language='Chinese' if re.search(r'[\u4e00-\u9fff]',p['text']) else 'English'
                if p['kind']=='voiceover':
                    who='The off-screen voice '+identity;sync='Off-screen; no visible lip-sync.'
                else:
                    who=(binding.get('subject_label') or 'The visible character assigned to this speaker')+' '+identity
                    sync='Only this speaker lip-syncs.'
                audio = 'speaks from <Audio 1>' if step.get('audio_binding') else 'speaks with newly generated voice'
                text+=f" From {p['start']:.3f} to {p['end']:.3f} seconds: {who} {audio} <d>[{language}] {p['text']}</d>. {sync}"
        lead='[Shot 1] ' if index==1 else f'[Shot {index}] At {cut_time(clip["start"])}, the camera cuts to '
        blocks.append(lead+text)
    main='\n'.join(blocks)
    if step.get('audio_binding'):main+='\nThe listed audio intervals govern mouth movement, independently of physical action segments. Outside their own speaking intervals, visible characters keep their mouths closed. Overlapping speaking intervals mean simultaneous voices. Preserve every supplied silence.'
    sound=validate_prose(adapted.get('overall_soundscape'))
    music=validate_prose(adapted.get('non_diegetic_music'))
    if mode=='Ref2VA':
        fields=[(k,validate_prose(adapted.get(k),allow_shot_labels=True)) for k in ('subject_definitions','summary','retention_analysis')]
        fields.append(('detailed_description',main))
    else:
        fields=[('integrated_multimodal_description',main)]
    voice_rules=h3_voice.instructions(refs)
    if voice_rules:
        fields=[(k,v+'\n'+voice_rules if k=='subject_definitions' else v) for k,v in fields]
        sound+=' Generate new dialogue in the referenced voices; synchronize visible mouths. Do not reuse the reference soundtrack.'
    fields.extend([('overall_soundscape',sound),('non_diegetic_music',music)])
    prompt='\n\n'.join(k+': '+v for k,v in fields)
    if mode=='I2VA':prompt='For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.\n\n'+prompt
    elif mode=='FL2VA':prompt=f'How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot {len(blocks)}) aligns with the {step["duration"]:.2f}-second mark of the target video.\n\n'+prompt
    elif mode=='L2VA':prompt=f'How the reference pictures align with the target video — <Picture 1> (from [Shot {len(blocks)}]) aligns with the {step["duration"]:.2f}-second mark of the target video.\n\n'+prompt
    stage_rules=frame_reference_sets.rules(refs) if len(step['clips'])==1 else ''
    if stage_rules:prompt+='\n\n'+stage_rules
    if step.get('audio_binding'):
        prompt=audio_prompt(prompt,step['duration']);allowed_labels.add('<Audio 1>')
    if any(r.get('refmod') for r in refs):
        prompt+='\n\nCharacter video references are saved multi-view identity assets. Preserve their face, hairstyle, body proportions and outfit. Use them for appearance only; generate the scripted actions anew. Never copy their view changes, transitions or montage layout.'
    actual=set(re.findall(r'<(?:Subject|Picture|Video|Audio) \d+>',prompt))
    if not actual.issubset(allowed_labels):raise ValueError('H3 转写引用了不存在的参考标签')
    if mode=='Ref2VA' and not allowed_labels.issubset(actual):raise ValueError('H3 转写遗漏已绑定的参考标签')
    if '<<<' in prompt or '>>>' in prompt:raise ValueError('H3 转写不得混入 Seedance 引用标签，请使用当前H3参考清单的Picture/Subject/Audio格式')
    from . import h3_reference_limits
    if enforce_length and h3_reference_limits.prompt_length('r34l1sm\n'+prompt)>6000:raise ValueError('H3生成预算超过6000字符，请精简重复描述；保留动作、对白和引用')
    continuity_in=validate_prose(adapted.get('continuity_in','None.'))
    continuity_out=validate_prose(adapted.get('continuity_out','None.'))
    return {'index':step['index'],'start':step['start'],'end':step['end'],'duration':step['duration'],'mode':mode,'references':refs,'prompt':prompt,'audio_binding':step.get('audio_binding',False),'continuity_in':continuity_in,'continuity_out':continuity_out,'source_shot_ids':[c['source_id'] for c in step['clips']],'timing':[{k:a[k] for k in ('key','start','end','natural_seconds','source_natural_seconds','source_action_offset','continuation')} for c in step['clips'] for a in c['actions']]}

def audio_prompt(prompt,duration):
    """Bind exact audio with the official six-section reference structure."""
    sections=re.split(r'(?m)(?:^|\n\n)(subject_definitions|summary|retention_analysis|detailed_description|integrated_multimodal_description|overall_soundscape|non_diegetic_music):\s*',prompt)
    fields={sections[i]:sections[i+1].strip() for i in range(1,len(sections)-1,2)}
    definition=f'<Audio 1> is the complete supplied {duration:.3f}-second dialogue and off-screen narration track, including silent motion intervals. Preserve the original voices, syllables, timing and playback speed.'
    fields['subject_definitions']=(fields.get('subject_definitions','')+'\n'+definition).strip()
    fields['summary']=(fields.get('summary','')+' Use <Audio 1> as the exact soundtrack; synchronize visible speaking characters, while narration remains off-screen.').strip()
    fields['retention_analysis']=(fields.get('retention_analysis','')+'\n<Audio 1>: fully_copy. Preserve silent intervals; do not invent speech or music.').strip()
    fields['detailed_description']=fields.get('detailed_description') or fields.get('integrated_multimodal_description','')
    fields['overall_soundscape']='Use only <Audio 1> at its original timing. Silent motion intervals remain silent. Do not generate replacement voices or additional sound.'
    fields['non_diegetic_music']='N/A. Add no music; the score is prepared separately.'
    return '\n\n'.join(k+': '+fields[k] for k in ('subject_definitions','summary','retention_analysis','detailed_description','overall_soundscape','non_diegetic_music'))


def rewrite(project,progress=None,shot_id=None,feedback=None):
    original_package=package(project,shot_id)
    project=scope(project,shot_id)
    steps=groups(project);pictures,subjects=reference_catalog(project)
    report=progress or (lambda message:None)
    outputs=[]
    for step in steps:
        report(f'正在编写中文 H3：第 {step["index"]}/{len(steps)} 步')
        mode,refs,used_subjects=mode_for(step,pictures,subjects)
        from . import speech_audio
        clip_shots=[next(s for s in project['shots'] if s['id']==c['source_id']) for c in step['clips']]
        if all(h3_voice.locked(s) and speech_audio.current(project,s) for s in clip_shots):
            step['audio_binding']=True;mode='Ref2VA'
            names={p['speaker'] for c in step['clips'] for p in c.get('speech_timeline',[])}
            ids=speaker_ids(project)
            step['speaker_bindings']=[{'speaker':name,'speaker_id':ids[name],
                'subject_label':next((s['label'] for s in used_subjects if s['name']==name),None)} for name in sorted(names,key=lambda n:int(ids[n][1:]))]
        if not step.get('audio_binding'):
            refs=refs+h3_voice.references(project,step,used_subjects,prepare=True)
            if any(r.get('media_type')=='audio' for r in refs):mode='Ref2VA'
            ids=speaker_ids(project)
            step['speaker_bindings']=[{'speaker':name,'speaker_id':ids[name],'subject_label':next((s['label'] for s in used_subjects if s['name']==name),None)} for name in ids]
        from . import h3_reference_limits
        h3_reference_limits.validate_media(refs,extra_audio=int(bool(step.get('audio_binding'))))
        from . import h3_input
        payload={'_five_source_input':True,'_direct_chinese':True,
                 '_asset_cards':{a['id']:a.get('card',{}) for a in project.get('assets',[])},
                 'previous_handoff':outputs[-1]['continuity_out'] if outputs else None,
                 'next_source':steps[step['index']]['clips'][0] if step['index']<len(steps) else None,
                 'applied_art_style':visual_reference.art(project)}
        if feedback:
            previous=(original_package or {}).get('steps',[])
            payload['existing_prompt']=next((row.get('prompt') for row in previous if row['index']==step['index']),None)
            payload['user_revision_feedback']=feedback
        output=rewrite_step(step,mode,refs,used_subjects,h3_input.SYSTEM+(' 基于existing_prompt按照user_revision_feedback修改，未提及部分保留；引用标签、对白原句、时序和输出协议仍按输入约束校验。' if feedback else ''),payload,report)
        output['input_contract']='h3-five-source-v1'
        output['skill_rule_application']={'source':'approved_storyboards','extra_skill_rules_injected':False}
        if output.get('language')!='zh':
            report(f'正在逐句生成中文核对版：第 {step["index"]}/{len(steps)} 步')
            output['prompt_zh']=translate_prompt(output['prompt'],step['index'],report)
        outputs.append(output)
    return {'steps':outputs,'scope_shot':shot_id,'total_duration':sum(s['duration'] for s in outputs),'max_step_seconds':project.get('h3_settings',{}).get('max_step_seconds',MAX_SECONDS),'official_max_seconds':OFFICIAL_MAX_SECONDS,'language':('zh' if all(o.get('language')=='zh' for o in outputs) else 'mixed' if any(o.get('language')=='zh' for o in outputs) else 'en'),'source_hash':fingerprint(project),'engine_version':project['documents'].get('engine_version'),'guide':'h3-prompt-writing; 任务分组上限采用用户设定','official_source':'https://www.minimax.io/news/minimax-h3-open-source'}


def protect_translation(prompt):
    # Whole dialogue/visible text is matched before its nested labels or digits.
    pattern=re.compile(r'<d>.*?</d>|"[^"\n]*"|(?m:^(?:integrated_multimodal_description|subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music):)|\[Shot \d+\]|<(?:Subject|Picture|Video|Audio) \d+>|\(S\d+(?:,S\d+)*\)|fully_preserved|partially_preserved|attribute_transfer|weak_reference|fully_copy|partially_copy|N/A|<scenetrans>|<cutoff>|\d+(?:\.\d+)?',re.S)
    protected={}
    def replace(match):
        token=f'__H3_KEEP_{len(protected)+1:03d}__';protected[token]=match.group(0)
        return token
    return pattern.sub(replace,prompt),protected


def restore_translation(translation,protected):
    if not isinstance(translation,str):raise ValueError('H3 中文核对版需为字符串')
    tokens=re.findall(r'__H3_KEEP_\d+__',translation)
    if tokens!=list(protected):raise ValueError('H3 中文核对版遗漏、重复或重排保护标签；所有 __H3_KEEP_...__ 必须原样、按原顺序保留')
    return re.sub(r'__H3_KEEP_\d+__',lambda match:protected[match.group(0)],translation).strip()


def translation_slots(prompt):
    masked,protected=protect_translation(prompt)
    pieces=re.split(r'(__H3_KEEP_\d+__)',masked)
    fields=[]
    for index,text in enumerate(pieces):
        if text in protected or not re.search(r'[A-Za-z]',text):continue
        fields.append({'id':f't{index}','text':text,
                       'left':protected.get(pieces[index-1],'') if index else '',
                       'right':protected.get(pieces[index+1],'') if index+1<len(pieces) else ''})
    return pieces,protected,fields


def assemble_translation(pieces,protected,fields,response):
    rows=response.get('translations') if isinstance(response,dict) else None
    if not isinstance(rows,list):raise ValueError('中文翻译需返回 translations 数组')
    expected={f['id'] for f in fields};translated={}
    for row in rows:
        if not isinstance(row,dict):raise ValueError('中文翻译条目需为对象')
        identity=row.get('id');text=row.get('text')
        if identity not in expected or identity in translated or not isinstance(text,str) or not text.strip():raise ValueError('中文翻译片段编号缺失、重复、未知或正文为空')
        # Immutable labels, quoted text, numbers and utterances stay in code.
        if '__H3_KEEP_' in text or re.search(r'<(?:Subject|Picture|Video|Audio) \d+>|<d>|\[Shot \d+\]|\d',text):raise ValueError('中文翻译片段新增了固定标签或数字：'+identity)
        translated[identity]=text
    if set(translated)!=expected:raise ValueError('中文翻译遗漏片段：'+','.join(sorted(expected-set(translated))))
    output=[]
    for index,piece in enumerate(pieces):
        identity=f't{index}'
        if piece in protected:output.append(protected[piece])
        elif identity in translated:
            leading=re.match(r'^\s*',piece)[0];trailing=re.search(r'\s*$',piece)[0]
            output.append(leading+translated[identity].strip()+trailing)
        else:output.append(piece)
    return ''.join(output).strip()


def translate_prompt(prompt,index,report,history=None,checkpoint=None):
    pieces,protected,fields=translation_slots(prompt)
    system=('你是技术翻译员。只返回JSON {"translations":[{"id":"原编号","text":"中文译文"}]}。逐项将text等量译为中文，保留全部含义，不概括、不新增事件。'
            'left/right仅为理解上下文的固定内容，由程序保管；不得在译文中复述它们，不返回任何占位符、引用标签、对白或阿拉伯数字。'
            '每个片段单独翻译，片段之间的标签、时间和对白由程序按原位置组装，禁止跨片段移动语义。所有编号恰好一次；编号可乱序，程序按编号恢复。保留段落换行；不要说明、Markdown或推理。')
    previous=None;error=None
    for attempt in range(REWRITE_ATTEMPTS):
        payload={'fields':fields}
        if attempt:payload.update(error=error,previous_response=previous,repair_instruction='修正出错内容，返回全部片段；只翻译text，不搬运left/right中的固定内容。')
        if attempt:report(f'第 {index} 步中文片段翻译未通过，正在纠正 {attempt}/{REWRITE_ATTEMPTS-1}：{error[:220]}')
        record={'attempt':attempt+1,'request':payload,'status':'pending','method':'program_owned_fixed_slots'}
        if history is not None:history.append(record)
        if checkpoint:checkpoint()
        try:
            with ai.asset_call_policy('h3_translation',limit=1,max_tokens=32768,timeout=300,preserve_context=True,report=report,reasoning_effort='low'):
                previous=ai.ask(system,json.dumps(payload,ensure_ascii=False))
            record.update(response=previous,status='validating')
            if checkpoint:checkpoint()
            result=assemble_translation(pieces,protected,fields,previous)
            validate_translation(prompt,result)
            record['status']='completed'
            if checkpoint:checkpoint()
            return result
        except ValueError as failure:
            if isinstance(failure,ai.InvalidJSONResponse):record['raw_response']=failure.raw_response
            error=str(failure)
            record.update(status='failed',error=error)
            if checkpoint:checkpoint()
    raise ValueError(f'H3 第{index}步中文片段翻译自动纠正{REWRITE_ATTEMPTS-1}次后仍未通过：{error}；原稿和修改记录保留')


def validate_translation(prompt,translation):
    if not translation or not re.search(r'[\u3400-\u9fff]',translation):raise ValueError('H3 中文核对版缺失')
    patterns=(r'(?m)^(?:integrated_multimodal_description|subject_definitions|summary|retention_analysis|detailed_description|overall_soundscape|non_diegetic_music):',r'\[Shot \d+\]',r'<(?:Subject|Picture|Video|Audio) \d+>',r'\(S\d+(?:,S\d+)*\)',r'<d>.*?</d>',r'\d+(?:\.\d+)?',r'fully_preserved|partially_preserved|attribute_transfer|weak_reference|fully_copy|partially_copy|N/A|<scenetrans>|<cutoff>',r'"[^"\n]*"')
    for pattern in patterns:
        expected=re.findall(pattern,prompt,re.S);actual=re.findall(pattern,translation,re.S)
        if expected!=actual:raise ValueError('H3 中文核对版改变了字段、时间、参考标签或原文。必须保留：'+str(expected)[:1000]+'；当前：'+str(actual)[:1000])


def markdown(package):
    lines=['# MiniMax H3 · 多步提示词',f'\n总时长：{package["total_duration"]:.2f} 秒；共 {len(package["steps"])} 步；提示词任务上限 {package["max_step_seconds"]} 秒。','\n指定本地 H3 节点支持最长30秒，导演台仅生成540P一采预览。官方 API 单次为4–15秒，可在网页选择15秒兼容模式。']
    for s in package['steps']:
        lines.extend([f'\n## 【分组{s["index"]}｜{s["start"]:.2f}–{s["end"]:.2f}秒｜{s["duration"]:.2f}秒】',f'\n模式：{s["mode"]}',*[f'\n{r["label"]} → media/{r["media"]}' for r in s['references']],'\n-----\n',('### 中文生成版\n' if s.get('language')=='zh' else '### 英文生成版\n'),s['prompt'],'\n### 中文核对版（不与英文拼接输入）\n',s['prompt_zh']])
        for m in s.get('outputs',[]):
            if m.get('seed') is not None:lines.append(f'\n生成记录：{m["media"]}；种子 {m["seed"]}；{m.get("resolution","540P")}；{m.get("quality","first")}。')
        if s['index']<len(package['steps']):lines.extend(['\n## 【段间引导：需要】','理由：'+s['continuity_out'],'下一步起始状态：'+package['steps'][s['index']]['continuity_in']])
    return '\n'.join(lines)


def reference_preview(project,shot_id):
    """Compute the exact reference plan before any text AI call."""
    scoped=scope(project,shot_id);pictures,subjects=reference_catalog(scoped)
    result={}
    from . import h3_segment_references,speech_audio,h3_reference_limits
    for step in groups(scoped):
        mode,refs,used=mode_for(step,pictures,subjects)
        audio=all(h3_voice.locked(next(s for s in scoped['shots'] if s['id']==c['source_id'])) and speech_audio.current(scoped,next(s for s in scoped['shots'] if s['id']==c['source_id'])) for c in step['clips'])
        if not audio:refs=refs+h3_voice.references(scoped,step,used)
        counts=h3_reference_limits.validate_media(refs,extra_audio=int(audio))
        for index,clip in enumerate(step['clips'],1):
            visible=h3_segment_references.allowed_subjects(clip,used)
            ids={identity for subject in visible for identity in subject.get('asset_ids',[subject.get('asset_id')])}
            assets=[{'id':a['id'],'name':a['name'],'kind':a['kind'],'references':[{'label':ref['label'],'kind':'角色 mod' if ref.get('refmod') else '图片'} for ref in refs if any(b['asset_id']==a['id'] for b in ref.get('bindings',[]))]} for a in scoped['assets'] if a['id'] in ids]
            frames=[{'label':ref['label'],'role':binding['role']} for ref in refs for binding in ref.get('frame_bindings',[]) if binding['source_id']==clip['source_id']]
            result[clip['source_id']]={'assets':assets,'frames':frames,'mode':mode,'audio':audio,'voice_references':[{'label':r['label'],'speaker':r['speaker']} for r in refs if r.get('role')=='voice_timbre'],'counts':counts}
    return {'shots':result,'revision':project['revision']}
