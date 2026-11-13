"""Explicit per-shot frame/asset roles for a multi-shot H3 segment."""
import copy,re
from . import store

RULES='''分段多参考规范：按原分镜播放顺序输出，原时长不变。资产参考通过Subject定义角色、场景、道具身份；帧图通过Picture单独定义某个Shot的首帧、关键瞬间或尾帧构图与状态。asset_shots和frame_bindings给出准确作用范围，禁止跨镜套用状态。首帧对齐本镜start，尾帧对齐end，关键帧在本镜范围内对应剧本关键动作，不擅自固定为时间中点。每个已绑定帧标签必须在对应镜头description或actions.text明确出现，不能只列在分析字段。每张图在subject_definitions解释用途，在retention_analysis解释保留哪些信息、作用于哪个Shot，在detailed_description落实动作因果、机位、光线与参考状态。相同角色/道具的不同时态保持同一身份，不克隆、不叠加、不提前出现后续状态。参考图身份优先，画面布局参考只约束站位、构图和状态，不移植无关人物、白底和拼图。只使用references中真实媒体标签，图片与视频分开编号；共享同一文件复用同一标签。关键帧及中途首尾帧为Ref2VA时序参考，不声称是节点强制锁帧。对白逐字保留，旁白不驱动口型；每镜专业镜头设置仅在本镜生效。'''

def mode_for(step,pictures,subjects):
    clips=step['clips'];selected={};asset_shots={}
    for index,clip in enumerate(clips,1):
        if clip.get('reference_mode') in ('text','first_frame','previous_tail'):continue
        ids=set(clip.get('asset_ids',[]));stages=clip.get('reference_stages',[])
        media={r['media'] for g in stages for r in g.get('references',[])}
        for picture in pictures:
            bindings=[b for b in picture.get('bindings',[]) if b['asset_id'] in ids]
            if not bindings or stages and not picture.get('refmod') and picture['media'] not in media and not any(b.get('stage')=='shared' for b in bindings):continue
            selected[picture['label']]=copy.deepcopy(picture)
            asset_shots.setdefault(picture['label'],[]).append(index)
    refs=list(selected.values())
    for ref in refs:ref['asset_shots']=asset_shots[ref['label']]
    by_media={r['media']:r for r in refs if not r.get('refmod')}
    next_number=max([int(re.search(r'\d+',r['label'])[0]) for r in pictures if r['label'].startswith('<Picture ')]+[0])+1
    roles={'first':('first_frame','start','first'),'keyframe':('adopted_keyframe',None,'middle'),'tail':('adopted_tailframe','end','last')}
    for index,clip in enumerate(clips,1):
        if clip.get('reference_mode') in ('text','assets'):continue
        chosen=clip.get('h3_frame_roles')
        if chosen is None:chosen=['first'] if clip.get('reference_mode') in ('first_frame','previous_tail') else ['first','keyframe','tail']
        if not isinstance(chosen,list) or any(r not in roles for r in chosen):raise ValueError('H3帧引用选项无效')
        for role in dict.fromkeys(chosen):
            field,point,card=roles[role];media=clip.get(field)
            if not media:continue
            if role=='first' and clip.get('continues_from_previous') or role=='tail' and clip.get('continues_to_next') or role=='keyframe' and (clip.get('continues_from_previous') or clip.get('continues_to_next')):continue
            if not store.media_path(media).is_file():raise ValueError(f'原分镜{index}的{role}参考图片缺失，请重新采用')
            ref=by_media.get(media)
            if ref is None:
                ref={'label':f'<Picture {next_number}>','media':media,'bindings':[],'asset_shots':[]};next_number+=1;refs.append(ref);by_media[media]=ref
            binding={'source_id':clip['source_id'],'shot':index,'role':role,'start':clip['start'],'end':clip['end'],'description':copy.deepcopy(clip.get('frame_cards',{}).get(card,{}))}
            if point:binding['at']=clip[point]
            ref.setdefault('frame_bindings',[]).append(binding)
    from . import h3_reference_limits
    h3_reference_limits.validate_media(refs)
    if not refs:raise ValueError('本分段没有可用的已采用帧或资产图片，请补充参考；纯文字需在各原分镜明确选择')
    labels={r['label'] for r in refs}
    used=[]
    for subject in subjects:
        chosen=[p for p in subject['pictures'] if p in labels]
        if chosen:used.append({**copy.deepcopy(subject),'pictures':chosen,'states':[s for s in subject.get('states',[]) if s['picture'] in labels]})
    return 'Ref2VA',refs,used

def mapping(refs):
    rows=[]
    for ref in refs:
        label=ref['label']
        for b in ref.get('frame_bindings',[]):
            target=f'[Shot {b["shot"]}]'
            if b['role']=='keyframe':rows.append(f'{label}: key-moment composition/state for {target} within {b["start"]:.2f}-{b["end"]:.2f}s; reach it at the scripted action, not an invented midpoint.')
            else:rows.append(f'{label}: {"start" if b["role"]=="first" else "end"}-frame composition/state for {target} at {b["at"]:.2f}s.')
        if ref.get('asset_shots'):rows.append(f'{label}: identity/material reference for shots '+','.join(str(i) for i in ref['asset_shots'])+'; do not copy its background, pose sequence or layout.')
    return '\n'.join(rows)

def allowed_subjects(clip,subjects):
    ids=set(clip.get('asset_ids',[]))
    return [s for s in subjects if ids.intersection(s.get('asset_ids') or [s.get('asset_id')])]

def scope_contract(step,refs,subjects):
    return [{'source_id':clip['source_id'],'allowed_subjects':[{'label':s['label'],'name':s.get('name','')} for s in allowed_subjects(clip,subjects)],'allowed_media':[r['label'] for r in refs if index in r.get('asset_shots',[]) or any(b['shot']==index for b in r.get('frame_bindings',[]))],'required_frames':[r['label'] for r in refs if any(b['shot']==index for b in r.get('frame_bindings',[]))]} for index,clip in enumerate(step['clips'],1)]

def validate_scopes(step,adapted,refs,subjects):
    for index,(clip,written) in enumerate(zip(step['clips'],adapted.get('shots',[])),1):
        text=str(written.get('description',''))+' '+ ' '.join(str(a.get('text','')) for a in written.get('actions',[]))
        allowed={r['label'] for r in refs if index in r.get('asset_shots',[]) or any(b['shot']==index for b in r.get('frame_bindings',[]))}
        used=set(re.findall(r'<(?:Picture|Video) \d+>',text))
        if not used.issubset(allowed):raise ValueError(f'H3原分镜{index}引用了其他分镜专用的图片或视频')
        permitted={s['label'] for s in allowed_subjects(clip,subjects)}
        invalid=set(re.findall(r'<Subject \d+>',text))-permitted
        if invalid:
            names={s['label']:s.get('name','未知资产') for s in subjects}
            bad='、'.join(label+'（'+names.get(label,'不存在')+'）' for label in sorted(invalid))
            good='、'.join(label+'（'+names[label]+'）' for label in sorted(permitted)) or '无Subject'
            raise ValueError(f'H3原分镜{index}引用越界：{bad}；本镜仅允许：{good}。只修正该镜description/actions.text中的越界引用；无关资产应移除，不能改用错误资产标签代替。')
        required={r['label'] for r in refs if any(b['shot']==index for b in r.get('frame_bindings',[]))}
        if not required.issubset(used):raise ValueError(f'H3原分镜{index}未在画面动作正文中落实全部已选帧引用')
