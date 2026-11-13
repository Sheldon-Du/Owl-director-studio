"""Independent start/key-moment references, combined only for video planning."""
import copy
from . import asset_references

def image_pool(asset):
    return {r['media'] for r in [*asset.get('references',[]),*asset.get('previews',[]),*([{'media':asset['adopted']}] if asset.get('adopted') else [])] if r.get('media')}

def owners(project,refs):
    result=[]
    for ref in refs:
        explicit=ref.get('asset_id')
        matches=[a for a in project.get('assets',[]) if ref.get('media') in image_pool(a) and (not explicit or a['id']==explicit)]
        if not matches:raise ValueError('参考图片与所选资产不对应，请重新选择')
        if not explicit and len(matches)>1:
            generated=[a for a in matches if ref['media']==a.get('adopted') or any(r.get('media')==ref['media'] for r in a.get('previews',[]))]
            if len(generated)==1:matches=generated
            else:raise ValueError('同一图片属于多个资产，请重新选择明确所属的资产')
        result.append({**copy.deepcopy(ref),'asset_id':matches[0]['id']})
    return result

def stages(project,shot):
    result=[]
    for mode in ('frame','keyframe'):
        plan=shot.get('image_plans',{}).get(mode)
        if not plan:
            media=shot.get('first_frame') if mode=='frame' else shot.get('adopted_keyframe')
            pool=shot.get('frames',[]) if mode=='frame' else shot.get('keyframes',[])
            candidate=next((r for r in pool if r.get('media')==media),None)
            if candidate:plan={'references':candidate.get('reference_bindings',[]),'relationship':candidate.get('relationship',''),'asset_ids':candidate.get('asset_ids',[])}
        if not plan or not plan.get('references'):continue
        refs=owners(project,plan['references'])
        result.append({'stage':mode,'relationship':plan.get('relationship',''),'reference_details':plan.get('reference_details',[]),'references':refs,'asset_ids':list(dict.fromkeys(r['asset_id'] for r in refs))})
    return result

def character_ids(project,shot):
    from . import timing_speech
    characters=[a for a in project.get('assets',[]) if a.get('kind')=='character']
    ids=[a['id'] for a in characters if a['id'] in shot.get('asset_ids',[])]
    for line in timing_speech.raw_catalogue(project,shot):
        if line.get('kind')!='dialogue':continue
        matches=[a for a in characters if a['id']==line.get('speaker_id')]
        if not matches:matches=[a for a in characters if a['name']==line.get('speaker')]
        if len(matches)==1 and matches[0]['id'] not in ids:ids.append(matches[0]['id'])
    return ids

def asset_ids(project,shot):
    selected=stages(project,shot)
    ids=list(dict.fromkeys(a for group in selected for a in group['asset_ids'])) if selected else list(shot.get('asset_ids',[]))
    return list(dict.fromkeys(ids+shot.get('performance',{}).get('asset_ids',shot.get('asset_ids',[]))+character_ids(project,shot)))

def assignments(project,shot):
    selected=stages(project,shot)
    if selected:
        refs=[{**r,**next((d for d in group['reference_details'] if d.get('media')==r['media'] and d.get('asset_id')==r['asset_id']),{}),'stage':group['stage'],'relationship':group['relationship']} for group in selected for r in group['references']]
        bound={r['asset_id'] for r in refs}
        refs.extend({**r,'asset_id':a['id'],'stage':'shared'} for a in project.get('assets',[]) if a['id'] in asset_ids(project,shot) and a['id'] not in bound for r in asset_references.effective(a))
        return refs
    return [{**r,'asset_id':a['id'],'stage':'shared'} for a in project.get('assets',[]) if a['id'] in asset_ids(project,shot) for r in asset_references.effective(a)]


def rules(refs):
    groups={stage:list(dict.fromkeys(r['label'] for r in refs if any(b.get('stage')==stage for b in r.get('bindings',[])))) for stage in ('frame','keyframe')}
    if not any(groups.values()):return ''
    return ('Stage-specific references: start-state assets '+(', '.join(groups['frame']) or 'none specified')+'; key-moment assets '+(', '.join(groups['keyframe']) or 'none specified')+
        '. Use start-state appearances before the scripted change, and key-moment states only when the corresponding action reaches that state. Different states of the same asset are one continuous subject, never duplicate objects or averaged appearances. Change only the scripted attribute; preserve identity, shape, material and spatial continuity. Never apply a later state prematurely or reset an earlier state.')
