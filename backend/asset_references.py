"""Shared reference selection for shot frames and H3, without changing assets."""
import copy

def effective(asset):
    role={'character':'identity','scene':'environment','prop':'prop'}.get(asset.get('kind'),'identity')
    result=[];seen=set()
    def add(ref):
        media=ref.get('media')
        if media and media not in seen:
            result.append(copy.deepcopy(ref));seen.add(media)
    if asset.get('variant'):
        media=asset.get('adopted') or next((p['media'] for p in reversed(asset.get('previews',[])) if p.get('media') and not p.get('stale')),None)
        if media:add({'media':media,'role':role,'note':'状态变体生成结果','source':'variant_output'})
        return result
    for ref in asset.get('references',[]):add(ref)
    if asset.get('adopted'):add({'media':asset['adopted'],'role':role,'note':'用户采用的元素图片','source':'adopted'})
    if not result:
        preview=next((p for p in reversed(asset.get('previews',[])) if p.get('media') and not p.get('stale')),None)
        if preview:add({'media':preview['media'],'role':role,'note':'最新有效的元素预览','source':'latest_preview'})
    return result

def for_shot(project,shot):
    result=[];by_media={}
    for identity in shot.get('asset_ids',[]):
        asset=next(a for a in project['assets'] if a['id']==identity)
        for ref in effective(asset):
            ref={**ref,'note':asset['name']+'：'+ref.get('note','')}
            if ref['media'] not in by_media:
                by_media[ref['media']]=ref;result.append(ref)
            elif ref['note'] not in by_media[ref['media']]['note']:by_media[ref['media']]['note']+='；'+ref['note']
    return result
