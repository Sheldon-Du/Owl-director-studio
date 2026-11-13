def bind_adopted(project,plan):
    """Bind one explicitly adopted asset image in required-assets order."""
    import copy
    from . import store
    out=copy.deepcopy(plan);assets={a['id']:a for a in project.get('assets',[])}
    references=[];details=[];choices={};missing=[];used=set()
    for index,row in enumerate(out.get('required_assets',[])):
        asset=assets.get(row['asset_id'],{});media=asset.get('adopted')
        reason='尚未采用图片'
        if media and media in used:reason='采用图片与另一资产重复'
        elif media:
            try:
                if not store.media_path(media).is_file():raise FileNotFoundError(media)
            except (ValueError,FileNotFoundError):reason='已采用图片文件不可用'
            else:
                role={'character':'identity','scene':'environment','prop':'prop'}.get(asset.get('kind'),'identity')
                references.append({'asset_id':row['asset_id'],'media':media,'role':role,'note':'资产卡已采用图片','source':'adopted'})
                details.append({**row,'media':media});choices[str(index)]=media;used.add(media)
                continue
        missing.append({'asset_id':row['asset_id'],'name':asset.get('name',row['asset_id']),'reason':reason})
    out.update(references=references,reference_details=details,reference_choices=choices,missing_adopted_assets=missing,auto_reference_binding=True)
    return out
