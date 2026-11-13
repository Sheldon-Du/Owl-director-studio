"""Scene assets represent one physical set, not a montage of locations."""
import copy
import re
import time
from . import store,script_source

RULE_VERSION='physical-scene-v2-inventory-coverage'
ROOMS=('客厅','玄关','诊室','走廊','病房','厨房','卧室','教室','大厅','办公室','楼梯间','洗手间','卫生间')


def locations(name):
    parts=[s.strip(' ·，,;；') for s in re.split(r'[/／|｜;；]+',str(name)) if s.strip()]
    if len(parts)<2:return [str(name).strip()]
    prefix=''
    out=[]
    for part in parts:
        if part in ROOMS and prefix:part=prefix+part
        prefix=''
        for room in ROOMS:
            if part.endswith(room) and len(part)>len(room):prefix=part[:-len(room)];break
        if not prefix and part.endswith(('医院','学校','小学','中学','住宅')):prefix=part
        if part not in out:out.append(part)
    return out


def single_name(name):
    if len(locations(name))!=1:raise ValueError('一个场景资产只能对应一个拍摄地点，不能合并：'+name)


def known_assets(assets):
    result=[]
    for asset in assets:
        names=locations(asset['name']) if asset['kind']=='scene' else [asset['name']]
        for name in names:result.append({**asset,'name':name})
    return result


def normalize_inventory(items):
    result=[];omitted=[]
    for item in items:
        if not isinstance(item,dict) or item.get('kind') not in ('character','scene','prop') or not isinstance(item.get('name'),str):continue
        if item['kind']!='scene':result.append(item);continue
        names=locations(item['name'])
        if (item.get('visible') is False or item.get('asset_need')=='omit') and item.get('omit_reason'):
            omitted.extend({'name':name,'reason':str(item['omit_reason']),'script_block_ids':item.get('script_block_ids',[])} for name in names)
            continue
        if len(names)==1:result.append(item);continue
        # Mixed profiles cannot be copied to each child: that would reproduce
        # all locations in every image. Reassess each child from source blocks.
        for name in names:
            child={k:copy.deepcopy(v) for k,v in item.items() if k not in ('description','narrative_context','aliases','source_quotes','fields','visual_profile')}
            child['name']=name;result.append(child)
    return result,omitted


def split_project(project):
    assets=project.get('assets',[]);replacements={};changed=[]
    mixed={a['id'] for a in assets if a['kind']=='scene' and len(locations(a['name']))>1}
    if any(mixed.intersection(s.get('asset_ids',[])) for s in project.get('shots',[])):
        raise ValueError('合并场景已有分镜绑定，请先核对并解除这些绑定后再拆分，避免错误分配地点')
    for parent in list(assets):
        if parent['kind']!='scene':continue
        names=locations(parent['name'])
        if len(names)<2:continue
        children=[]
        for name in names:
            child=next((a for a in assets if a['kind']=='scene' and a['name']==name and a['id']!=parent['id']),None)
            if child is None:
                child={'id':store.uid(),'kind':'scene','name':name,'description':'','visual_description_source':'script','model':parent.get('model','qwen-image-2.1'),'model_source':parent.get('model_source','default'),'prompt':'','references':[],'previews':[],'adopted':None,'split_from':parent['id'],'needs_scene_extraction':True}
                assets.append(child)
            children.append(child['id'])
        # Preserve the entire old asset, including user fields, prompts, refs
        # and generated media. No ambiguous media is automatically reassigned.
        project.setdefault('scene_asset_archive',[]).append({'asset':copy.deepcopy(parent),'replacement_ids':children,'reason':'旧场景合并了多个拍摄地点，已拆分；原资料保留待核对','created':time.time()})
        replacements[parent['id']]=children;assets.remove(parent)
        changed.append({'old':parent['name'],'new':names})
    if not changed:return []
    project['native_storyboard_current']=False;project['confirmed']=False
    script_source.mark_extraction_pending(project)
    # The rule change requires a fresh inventory even for an unchanged script.
    project['asset_analysis'].update(status='pending',inventory=[],total=0,completed=0,reused=0,failed=0,failures=[],task_id=None,scene_rules=None,omitted_scenes=[],message='旧合并场景已拆开，请手动提取各地点外观；原场景资料保留在旧记录中')
    return changed


def apply_omissions(project,omitted):
    records=copy.deepcopy(omitted)
    for record in records:
        asset=next((a for a in project.get('assets',[]) if a['kind']=='scene' and a['name']==record['name']),None)
        if asset is None:continue
        disposable=asset.get('needs_scene_extraction') and not any(asset.get(k) for k in ('description','visual_profile','references','previews','adopted','prompt'))
        bound=any(asset['id'] in s.get('asset_ids',[]) for s in project.get('shots',[]))
        if not disposable or bound:record['kept_existing']=True;continue
        project.setdefault('scene_asset_archive',[]).append({'asset':copy.deepcopy(asset),'replacement_ids':[],'reason':'省略独立场景资产：'+record['reason'],'created':time.time()})
        project['assets'].remove(asset)
    return records
