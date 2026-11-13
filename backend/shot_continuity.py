"""Explicit continuity records; compatible labels are not a visual inspection."""
import copy
import hashlib
import json


def digest(shot):
    return hashlib.sha256(json.dumps([shot.get('description'),shot.get('prompt'),shot.get('duration'),shot.get('native',{}).get('连续性接口')],ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def validate(value,outline,project):
    if not isinstance(value,dict):raise ValueError('剧情单元分镜需要continuity起止接口')
    asset_index={a['id']:a for a in project.get('assets',[])};errors=[]
    for state in ('start','end'):
        row=value.get(state)
        if not isinstance(row,dict):errors.append('连续性接口缺少'+state+'状态');continue
        for key in ('location','story_time','lighting','sound'):
            if not isinstance(row.get(key),str) or not row[key].strip():errors.append('连续性接口缺少非空字段：'+state+'.'+key)
        if row.get('location')!=outline['location']:errors.append('连续性接口地点必须与确认汇总的单一地点一致：'+state+'.location需为'+outline['location'])
        for category,kind,fields in (('characters','character',('name','position','facing','costume')),('props','prop',('name','holder','state'))):
            items=row.get(category)
            if not isinstance(items,list) or len(items)>80:errors.append('连续性人物/道具必须为列表：'+state+'.'+category);continue
            seen=set()
            for number,item in enumerate(items):
                path=f'{state}.{category}[{number}]'
                if not isinstance(item,dict):errors.append('连续性人物/道具必须为对象：'+path);continue
                missing=[k for k in fields if not isinstance(item.get(k),str) or not item[k].strip()]
                if missing:errors.append('连续性人物/道具缺少明确状态：'+ '、'.join(path+'.'+k for k in missing)+'。未知状态写未明确；无人持有的固定物需说明固定位置')
                identity=item.get('asset_id','')
                if not isinstance(identity,str) or (identity and (identity not in asset_index or asset_index[identity]['kind']!=kind)):
                    allowed=[a['id'] for a in asset_index.values() if a['kind']==kind]
                    errors.append('连续性接口引用了未知或错误类型资产ID：'+path+'.asset_id='+str(identity)+'；'+kind+'可用ID为'+json.dumps(allowed,ensure_ascii=False)+'。未建立对应资产时asset_id必须是空字符串""，不得创建新编号；name保留对应人物或道具名')
                    continue
                matches=[a for a in asset_index.values() if a['kind']==kind and a['name']==item.get('name')]
                if matches and identity not in [a['id'] for a in matches]:errors.append('连续性接口必须关联对应人物/道具的真实资产ID：'+path)
                key=identity or item.get('name')
                if not isinstance(key,str):continue
                if key in seen:errors.append('连续性接口人物/道具重复：'+path)
                seen.add(key)
    transition=value.get('transition')
    if not isinstance(transition,dict) or transition.get('type') not in ('continuous','cut','time_change','location_change') or not isinstance(transition.get('reason'),str) or not transition['reason'].strip():errors.append('连续性接口需说明衔接类型与理由：transition.type、transition.reason')
    if errors:raise ValueError('；'.join(errors))
    return copy.deepcopy(value)


def compare(previous,current):
    before=previous.get('native',{}).get('连续性接口',{}).get('end') if previous else None
    value=current.get('native',{}).get('连续性接口',{});after=value.get('start')
    if not before or not after:return {'status':'unrecorded','issues':[],'shot_hash':digest(current)}
    transition=value.get('transition',{});issues=[]
    changed=transition.get('type') in ('time_change','location_change')
    if not changed:
        for key in ('location','story_time','lighting'):
            if before.get(key)!=after.get(key) and '未明确' not in str(before.get(key))+str(after.get(key)):issues.append({'field':key,'previous':before.get(key),'next':after.get(key)})
        for category,fields in (('characters',('costume',)),('props',('holder','state'))):
            old={r.get('asset_id') or r['name']:r for r in before.get(category,[])}
            for row in after.get(category,[]):
                identity=row.get('asset_id') or row['name'];earlier=old.get(identity)
                if not earlier:continue
                for field in fields:
                    if earlier.get(field)!=row.get(field) and '未明确' not in str(earlier.get(field))+str(row.get(field)):issues.append({'field':row['name']+'.'+field,'previous':earlier.get(field),'next':row.get(field)})
    return {'status':'needs_review' if issues else 'compatible_recorded','issues':issues,
            'shot_hash':digest(current),
            'previous_id':previous['id'],'previous_hash':digest(previous),
            'note':'这里只比较已记录的地点、时间、服装和道具状态；位置朝向、轴线、实际光线和声音仍需查看复核'}


def refresh(project):
    if project.get('storyboard_method')!='source_units':return
    rows=sorted(project.get('shots',[]),key=lambda s:s.get('generation_index',0))
    for i,shot in enumerate(rows):
        report=compare(rows[i-1] if i else None,shot)
        if shot.get('continuity_source_hash') and shot['continuity_source_hash']!=digest(shot):report.update(status='needs_review',issues=[*report['issues'],{'field':'本镜内容','previous':'生成时记录的状态','next':'正文/动作/时长已编辑，需复核状态接口'}])
        prior=shot.get('continuity_review',{})
        accepted=prior.get('status')=='human_reviewed' and prior.get('previous_hash')==report.get('previous_hash') and prior.get('shot_hash')==digest(shot)
        if not accepted:shot['continuity_review']=report


def gate(project,sid):
    if project.get('storyboard_method')!='source_units':return
    rows=sorted(project.get('shots',[]),key=lambda s:s.get('generation_index',0))
    for index,shot in enumerate(rows):
        if shot['id']!=sid:continue
        if shot.get('continuity_source_hash') and shot['continuity_source_hash']!=digest(shot):raise ValueError('本镜内容已修改，请在分镜汇总人工复核状态接口后继续')
        if index:
            current=compare(rows[index-1],shot);review=shot.get('continuity_review',{})
            if current['status']=='needs_review' and not (review.get('status')=='human_reviewed' and review.get('previous_hash')==current['previous_hash'] and review.get('shot_hash')==digest(shot)):
                raise ValueError('本镜与前镜状态有冲突，请修复或在分镜汇总中人工复核衔接后继续')
        return


def accept(project,sid,note,expected_hash):
    if not isinstance(note,str) or len(note.strip())<4:raise ValueError('请说明实际声画如何衔接，再确认保留本镜')
    rows=sorted(project.get('shots',[]),key=lambda s:s.get('generation_index',0))
    index=next((i for i,s in enumerate(rows) if s['id']==sid),None)
    if index is None:raise ValueError('没有可复核的镜头')
    shot=rows[index]
    if digest(shot)!=expected_hash:raise ValueError('本镜已修改，请刷新后重新复核')
    report=compare(rows[index-1] if index else None,shot)
    shot['continuity_review']={**report,'status':'human_reviewed','shot_hash':digest(shot),'note':note.strip()}
    shot['continuity_source_hash']=digest(shot)
    return shot['continuity_review']
