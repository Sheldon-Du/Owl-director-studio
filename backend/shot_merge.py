"""Reversible manual composition of adjacent shots; preserve source media."""
import copy,re,time,math
from . import store,authoring

def group_for(p,sid):
    group=next((g for g in p.get('h3_shot_groups',[]) if sid in g.get('shot_ids',[])),None)
    if group:
        ids=group['shot_ids'];positions=[i for i,s in enumerate(p['shots']) if s['id'] in ids]
        if len(ids)<2 or len(ids)!=len(set(ids)) or len(positions)!=len(ids) or positions!=list(range(positions[0],positions[-1]+1)) or [p['shots'][i]['id'] for i in positions]!=ids:
            raise ValueError('H3分组对应的相邻分镜已改变，请取消分组后重新选择')
    return group

def members(p,sid):
    group=group_for(p,sid)
    return group['shot_ids'] if group else [sid]

def leader(p,sid):
    return members(p,sid)[0]

def merge(p,ids):
    if not isinstance(ids,list) or len(ids)<2 or len(set(ids))!=len(ids):raise ValueError('请选择至少两个不同的连续分镜建立H3分段')
    positions=[i for i,s in enumerate(p['shots']) if s['id'] in ids]
    if len(positions)!=len(ids) or positions!=list(range(positions[0],positions[-1]+1)):raise ValueError('只能将连续相邻分镜合并为H3分段，不能跨镜')
    shots=[p['shots'][i] for i in positions]
    if any(s.get('merged_from') or group_for(p,s['id']) for s in shots):raise ValueError('已合并或已分组的分镜不能再次合并，请先取消原分组')
    if any(type(s.get('duration')) not in (int,float) or not math.isfinite(s['duration']) or s['duration']<=0 for s in shots):raise ValueError('镜头时长必须大于零')
    maximum=p.get('h3_settings',{}).get('max_step_seconds',30)
    if sum(s['duration'] for s in shots)>maximum+.001:raise ValueError(f'所选分镜总时长超过当前H3单次{maximum}秒上限，请减少所选分镜或调整H3时长上限')
    group={'id':store.uid(),'shot_ids':[s['id'] for s in shots],'created':time.time()}
    p.setdefault('h3_shot_groups',[]).append(group)
    p.setdefault('shot_merge_history',[]).append({'id':store.uid(),'kind':'h3_group','group_id':group['id'],'created':time.time()})
    p['shot_merge_history']=p['shot_merge_history'][-10:]
    return shots[0]['id']

def ungroup(p,group_id=None):
    groups=p.get('h3_shot_groups',[])
    if group_id is not None and not any(g['id']==group_id for g in groups):raise ValueError('H3分段不存在，请刷新')
    removed={g['id'] for g in groups if group_id is None or g['id']==group_id}
    p['h3_shot_groups']=[g for g in groups if g['id'] not in removed]
    p['shot_merge_history']=[r for r in p.get('shot_merge_history',[]) if r.get('group_id') not in removed]

def legacy_merge(p,ids):
    if not isinstance(ids,list) or len(ids)<2 or len(ids)!=len(set(ids)):raise ValueError('请勾选至少两个不同的相邻分镜')
    positions=[i for i,s in enumerate(p['shots']) if s['id'] in ids]
    if len(positions)!=len(ids) or positions!=list(range(min(positions),max(positions)+1)):raise ValueError('只能合并相邻分镜，不能跨过中间镜头')
    sources=[copy.deepcopy(p['shots'][i]) for i in positions]
    if any(type(s.get('duration')) not in (int,float) or not math.isfinite(s['duration']) or s['duration']<=0 for s in sources):raise ValueError('镜头时长必须大于零')
    before={'shots':copy.deepcopy(p['shots']),'documents':copy.deepcopy(p.get('documents',{})),'storyboard_generation':copy.deepcopy(p.get('storyboard_generation')),'storyboard_method':p.get('storyboard_method'),'native_storyboard_current':p.get('native_storyboard_current')}
    merged=copy.deepcopy(sources[0]);merged['id']=store.uid();merged['description']=' → '.join(s['description'] for s in sources)
    merged['duration']=round(sum(s['duration'] for s in sources),6)
    merged['merged_from']=sources;merged['merged_at']=time.time()
    merged['camera_override']={'enabled':False,'selected':[],'options':{}}
    merged.pop('camera_baseline',None);merged.pop('camera_history',None)
    mapping=p.get('authoring_run',{}).get('published_shot_ids',[])
    merged['overview_indices']=list(dict.fromkeys(i for s in sources for i in (s.get('overview_indices') or ([mapping.index(s['id'])] if s['id'] in mapping else []))))
    merged['asset_ids']=list(dict.fromkeys(a for s in sources for a in s.get('asset_ids',[])))
    merged['asset_names']=list(dict.fromkeys(a for s in sources for a in s.get('asset_names',[])))
    actions=[];cursor=0
    for s in sources:
        for raw in s.get('actions',[]):
            a=copy.deepcopy(raw);a.update(id=store.uid(),start=round(cursor+float(raw.get('start',0)),6),end=round(cursor+float(raw.get('end',s['duration'])),6));a.pop('depends_on',None);actions.append(a)
        cursor+=s['duration']
    merged['actions']=actions
    # Each source's reference tags are local. Remap all tags in one pass.
    refs=[];known={};counters={};chunks=[]
    for s in sources:
        tags={}
        for raw in s.get('seedance_references',[]):
            key=(raw['kind'],raw['media'])
            if key not in known:
                kind=raw['kind'];counters[kind]=counters.get(kind,0)+1
                tag=f'<<<{kind}_{counters[kind]}>>>';known[key]=tag;refs.append({**copy.deepcopy(raw),'tag':tag})
            if raw.get('tag'):tags[raw['tag']]=known[key]
        text=s.get('prompt','')
        if tags:text=re.sub('|'.join(re.escape(t) for t in sorted(tags,key=len,reverse=True)),lambda m:tags[m.group()],text)
        chunks.append(text)
    merged['prompt']='\n\n'.join('连续片段 '+str(i+1)+'\n'+text for i,text in enumerate(chunks))
    merged['seedance_sections']={'首帧与空间调度':sources[0].get('seedance_sections',{}).get('首帧与空间调度',sources[0]['description']),'动作时间轴':merged['prompt'],'正向约束':'按片段先后顺序完整呈现，保持角色身份与动作因果。无字幕。'}
    merged['seedance_references']=refs;merged['seedance_reference_confirmation']=None
    merged['sound_script']={'lines':[copy.deepcopy(l) for s in sources for l in s.get('sound_script',{}).get('lines',[])],'environment':[v for s in sources for v in (s.get('sound_script',{}).get('environment',[]) if isinstance(s.get('sound_script',{}).get('environment',[]),list) else [s.get('sound_script',{}).get('environment','')]) if v]}
    for key in ('dialogue','voiceover'):merged[key]='\n'.join(s.get(key,'') for s in sources if s.get(key))
    middle=sources[len(sources)//2]
    merged['frame_cards']={'first':copy.deepcopy(sources[0].get('frame_cards',{}).get('first',{})),'middle':copy.deepcopy(middle.get('frame_cards',{}).get('middle',{})),'last':copy.deepcopy(sources[-1].get('frame_cards',{}).get('last',{}))}
    for key in ('tailframes','adopted_tailframe'):merged[key]=copy.deepcopy(sources[-1].get(key,[] if key=='tailframes' else None))
    for key in ('keyframes','adopted_keyframe'):merged[key]=copy.deepcopy(middle.get(key,[] if key=='keyframes' else None))
    merged['outputs']=[]  # Source clips stay in merged_from, not a fake full merged video.
    for key in ('h3','h3_prompt','seedance_candidate','image_plans','speech_audio','speech_mix','timing_suggestion','timing_audit','continuity_review','continuity_source_hash'):merged.pop(key,None)
    merged['natural_status']='human_reviewed' if all(s.get('natural_status') in ('ai_reviewed','human_reviewed') for s in sources) else 'unverified'
    merged['timing_status']='unverified'
    merged['native']={'画面焦点':merged['description'],'AIGC提示词':merged['prompt'],'时长':merged['duration'],'动作预案':actions,'台词':merged['dialogue'],'旁白':merged['voiceover']}
    p['shots'][positions[0]:positions[-1]+1]=[merged]
    for following in p['shots']:
        link=following.get('first_frame_link',{})
        if link.get('source_id')==sources[-1]['id']:link['source_id']=merged['id']
    p.setdefault('shot_merge_history',[]).append({'id':store.uid(),'merged_id':merged['id'],'created':time.time(),'before':before})
    p['shot_merge_history']=p['shot_merge_history'][-10:]
    p.pop('storyboard_generation',None);p['storyboard_method']='legacy';p['native_storyboard_current']=True;p['confirmed']=False
    refresh(p)
    return merged['id']

def refresh(p):
    p['documents']['storyboard_native']={'contract_version':2,'分镜表':[s.get('native',{}) for s in p['shots']]}
    if p.get('authoring_run'):p['authoring_run']['input_hash']=authoring.fingerprint(p)

def undo(p):
    history=p.get('shot_merge_history',[])
    if not history:raise ValueError('没有可撤销的合并')
    row=history[-1]
    if row.get('kind')=='h3_group':
        p['h3_shot_groups']=[g for g in p.get('h3_shot_groups',[]) if g['id']!=row['group_id']]
        history.pop()
        return
    before=row['before']
    index=next((i for i,s in enumerate(p['shots']) if s['id']==row['merged_id']),None)
    if index is None:raise ValueError('最近合并镜头已被其他操作替换，请先恢复当前分镜版本')
    original=copy.deepcopy(p['shots'][index].get('merged_from',[]))
    if not original:raise ValueError('缺少合并前镜头备份')
    history.pop()
    # Save the current merged version so later media and edits remain recoverable.
    p.setdefault('shot_merge_undo_history',[]).append({'shots':copy.deepcopy(p['shots']),'created':time.time()})
    p['shots'][index:index+1]=original
    for following in p['shots']:
        link=following.get('first_frame_link',{})
        if link.get('source_id')==row['merged_id']:link['source_id']=original[-1]['id']
    for key in ('storyboard_generation','storyboard_method','native_storyboard_current'):
        if before.get(key) is not None:p[key]=before[key]
        else:p.pop(key,None)
    p['confirmed']=False;refresh(p)
