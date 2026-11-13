"""Copy adopted overview descriptions into production cards without replacing media."""
import copy,time
from . import store,seedance_integration as seedance

def update(p,scope,target=None):
    from . import authoring
    run=p.get('authoring_run',{})
    stage=3 if scope=='assets' else 4 if scope=='shots' else 5
    if not run.get('adopted') or run.get('status')!='completed':
        raise ValueError('请先在创作概览完成并采用创作成果，再更新卡片')
    if run.get('stale_from',7)<=stage:raise ValueError('创作概览的依据已修改，请先重新生成并采用对应阶段')
    records=[]
    if scope=='assets':
        rows=authoring.result(p,'assets')
        if not rows or not rows.get('assets'):raise ValueError('创作概览还没有资产设计信息')
        targets=[a for a in p['assets'] if not target or a['id']==target]
        if target and not targets:raise ValueError('资产卡片不存在')
        for raw in rows['assets']:
            matches=[a for a in targets if a['id']==raw.get('id')]
            if not matches:matches=[a for a in targets if a['kind']==raw['kind'] and a['name']==raw['name']]
            if len(matches)>1:raise ValueError('同名资产无法确定对应关系，请先区分名称')
            asset=matches[0] if matches else None
            if asset is None:
                if target:continue
                asset={'id':raw.get('id') or store.uid(),'name':raw['name'],'kind':raw['kind'],'references':[],'previews':[],'adopted':None,'model':'qwen-image-2.1','prompt':''}
                p['assets'].append(asset)
            before={k:copy.deepcopy(asset.get(k)) for k in ('card','description','voice')}
            card=seedance.card(raw['card']);asset.update(card=card,description=seedance.card_text(card))
            if asset['kind']=='character':asset.setdefault('voice',{})['description']=raw.get('voice_description','')
            if before['card']!=card:
                asset['style_needs_refresh']=True
            records.append({'id':asset['id'],'before':before})
    elif scope=='shots':
        if any(s.get('merged_from') for s in p['shots'] if not target or s['id']==target):raise ValueError('分镜包含手动合并版本，请先撤销合并再从概览更新，避免丢失人工合并')
        rows=authoring.result(p,'outline')
        if not rows:raise ValueError('创作概览还没有分镜信息')
        mapping=list(run.get('published_shot_ids',[]))
        if target and not any(s['id']==target for s in p['shots']):raise ValueError('分镜不存在')
        new_mapping=[]
        for index,outline in enumerate(rows['shots']):
            shot=next((s for s in p['shots'] if index<len(mapping) and s['id']==mapping[index]),None)
            if not shot:
                matches=[s for s in p['shots'] if outline['description'] in (s.get('description'),s.get('native',{}).get('画面焦点'))]
                if len(matches)>1:raise ValueError('同内容分镜无法确定对应关系，请先采用最新概览')
                shot=matches[0] if matches else None
            if target and (not shot or shot['id']!=target):
                new_mapping.append(shot['id'] if shot else None);continue
            if not shot:
                shot={'id':store.uid(),'frames':[],'keyframes':[],'tailframes':[],'outputs':[],'seedance_references':[]}
                p['shots'].append(shot)
            detail=authoring.result(p,f'shot:{index}');audio=authoring.result(p,'sound')
            if not detail or not audio:raise ValueError(f'创作概览尚未完成第 {index+1} 镜的提示词与声音脚本')
            audio=audio['shots'][index]
            fields=('description','duration','asset_ids','asset_names','speech_ids','prompt','seedance_sections','actions','sound_script','dialogue','voiceover','native')
            before={k:copy.deepcopy(shot.get(k)) for k in fields}
            actions=copy.deepcopy(detail['actions']);cursor=0
            for action in actions:
                action.update(id=store.uid(),start=cursor,end=cursor+action['natural_seconds'],minimum_seconds=action['natural_seconds'],rationale='自然动作规划，最终以实测复核');cursor=action['end']
            lines=[{**copy.deepcopy(line),'source_id':line['id'],'speaker_id':next((a['id'] for a in p['assets'] if a['kind']=='character' and a['name']==line.get('speaker')),None),'independent_track':line['kind']=='voiceover'} for line in audio['dialogue']+audio['voiceover']]
            shot.update(**copy.deepcopy(outline),asset_ids=[a['id'] for a in p['assets'] if a['name'] in outline['asset_names']],prompt=detail['prompt'],seedance_sections=copy.deepcopy(detail['sections']),seedance_model=authoring.settings(p)['seedance_model'],seedance_quality=detail.get('quality_notes',[]),actions=actions,sound_script={'lines':lines,'environment':audio['environment']},dialogue='\n'.join(l['text'] for l in audio['dialogue']),voiceover='\n'.join(l['text'] for l in audio['voiceover']),natural_status='unverified',timing_status='unverified',seedance_reference_confirmation=None)
            shot.setdefault('native',{}).update(画面焦点=shot['description'],AIGC提示词=shot['prompt'],时长=shot['duration'],台词=[l['text'] for l in audio['dialogue']],旁白=shot['voiceover'],动作预案=actions)
            shot.pop('seedance_candidate',None)
            if not shot.get('frame_cards') and authoring.result(p,f'frame:{index}'):shot['frame_cards']=copy.deepcopy(authoring.result(p,f'frame:{index}')['frame_cards'])
            for key in ('frames','keyframes','tailframes','outputs'):
                for media in shot.get(key,[]):media['stale']=True
            records.append({'id':shot['id'],'before':before});new_mapping.append(shot['id'])
        if not target:run['published_shot_ids']=new_mapping
        p['confirmed']=False
        p['documents']['storyboard_native']={'contract_version':2,'分镜表':[s.get('native',{}) for s in p['shots']]}
        p['documents']['sound_script']=copy.deepcopy(authoring.result(p,'sound'))
    elif scope=='frames':
        outline=authoring.result(p,'outline')
        if not outline:raise ValueError('创作概览还没有分镜与三帧信息')
        targets=[s for s in p['shots'] if not target or s['id']==target]
        if not targets:raise ValueError('请先采用创作概览中的分镜')
        mapping=run.get('published_shot_ids',[])
        for shot in targets:
            if shot.get('overview_indices'):
                indices=shot['overview_indices'];first=authoring.result(p,f'frame:{indices[0]}');middle=authoring.result(p,f'frame:{indices[len(indices)//2]}');last=authoring.result(p,f'frame:{indices[-1]}')
                if not all((first,middle,last)):raise ValueError('合并镜头的原始三帧信息尚未完成')
                before=copy.deepcopy(shot.get('frame_cards',{}));shot['frame_cards']={'first':copy.deepcopy(first['frame_cards']['first']),'middle':copy.deepcopy(middle['frame_cards']['middle']),'last':copy.deepcopy(last['frame_cards']['last'])}
                for plan in shot.get('image_plans',{}).values():plan['stale']=True
                records.append({'id':shot['id'],'before':before});continue
            if shot['id'] in mapping:index=mapping.index(shot['id'])
            else:
                matches=[i for i,row in enumerate(outline['shots']) if row['description'] in (shot.get('description'),shot.get('native',{}).get('画面焦点'))]
                if len(matches)!=1:raise ValueError('无法确定分镜与创作概览的对应关系，请先在概览采用分镜成果')
                index=matches[0]
            value=authoring.result(p,f'frame:{index}')
            if not value:raise ValueError(f'创作概览尚未生成第 {index+1} 镜的三帧描述')
            cards={key:seedance.card(value['frame_cards'][key]) for key in ('first','middle','last')}
            before=copy.deepcopy(shot.get('frame_cards',{}))
            shot['frame_cards']=cards
            if before!=cards:
                for plan in shot.get('image_plans',{}).values():plan['stale']=True
                for key in ('frames','keyframes','tailframes'):
                    for media in shot.get(key,[]):media['stale']=True
            records.append({'id':shot['id'],'before':before})
    else:raise ValueError('请选择资产或三帧更新')
    if not records:raise ValueError('创作概览中没有这张卡片的对应信息')
    from . import visual_reference
    for shot in p['shots']:
        link=shot.get('first_frame_link',{})
        if link.get('mode')=='previous_tail' and link.get('media'):shot.setdefault('frame_cards',{})['first']=copy.deepcopy(link['card'])
        visual_reference.tail_changed(p,shot)
    p.setdefault('overview_sync_history',[]).append({'scope':scope,'run_id':run['id'],'created':time.time(),'records':records})
    p['overview_sync_history']=p['overview_sync_history'][-20:]
    run['input_hash']=authoring.fingerprint(p)
    return len(records)
