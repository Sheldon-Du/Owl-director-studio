"""Resolve a valid screenplay or original story without publishing synthetic documents."""
import hashlib
import json


def input_hash(project):
    values={key:project.get(key) for key in ('story','parameters','duration','script_mode','story_policy')}
    if '_story_original' in project:values['story']=project['_story_original']
    from . import script_workflows
    extra=script_workflows.input_values(project)
    if extra is not None:values['writing_workflow']=extra
    from . import script_tasks
    task_inputs=script_tasks.input_values(project)
    if task_inputs is not None:values['writing_task']=task_inputs
    if 'creative_skills' in project:
        from . import creative_rules
        values['creative_skills']=creative_rules.signature(project,('script_plan','script'))
    return hashlib.sha256(json.dumps(values,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def screenplay(project,required=True):
    docs=project.get('documents',{})
    body=str(docs.get('script',''))
    error='请先编写或填写完成剧本，再按剧本提取元素外观'
    if body.strip():
        if not project.get('script_needs_rewrite') and docs.get('script_input_hash',input_hash(project))==input_hash(project):return body
        error='故事或导演设定已修改，请重新编写剧本，或确认当前正文后再提取元素'
    if required:raise ValueError(error)
    return ''


def kind(project):
    if '_production_source_kind' in project:return project['_production_source_kind']
    return 'script' if screenplay(project,False).strip() else 'story'


def text(project,required=True):
    if '_full_script' in project:return project['_full_script']
    body=screenplay(project,False) or str(project.get('_story_original',project.get('story','')))
    if required and not body.strip():raise ValueError('请先填写故事或有效剧本')
    return body


def ready(project):return bool(text(project,False).strip())


def fingerprint(project):
    return hashlib.sha256((('screenplay-v1' if kind(project)=='script' else 'story-v1')+'\n'+asset_text(project)).encode()).hexdigest()


def asset_hash(project,asset):
    return hashlib.sha256(json.dumps(['screenplay-v1' if kind(project)=='script' else 'story-v1',asset_text(project,False),asset['kind'],asset['name']],ensure_ascii=False).encode()).hexdigest()


def asset_text(project,required=True):
    body=text(project,required)
    docs=project.get('documents',{})
    if kind(project)!='script' or not body or docs.get('script_expression_review',{}).get('settings_stale'):return body
    settings=docs.get('script_production_settings',[])
    if settings:
        body+='\n\n【剧本制作设定 · 来源为已编写剧本的设定表】\n'+'\n'.join(f'第{r["scene"]}场 · {r["location"]} · {r["script_excerpt"]}（适用：{r["reason"]}）' for r in settings)
    return body


def accept(project):
    project.setdefault('documents',{})['script_input_hash']=input_hash(project)
    project['script_needs_rewrite']=False


def set_derived_duration(project,seconds):
    """A natural-action clock changes film length, not screenplay inputs."""
    was_current=bool(screenplay(project,False))
    project['duration']=seconds
    if was_current:accept(project)


def mark_assets_stale(project):
    for asset in project.get('assets',[]):
        if asset.get('profile_source_type')=='script' and asset.get('profile_source_hash')==asset_hash(project,asset):continue
        if asset.get('visual_profile'):asset['profile_stale']=True
        for preview in asset.get('previews',[]):preview['stale']=True


def mark_extraction_pending(project):
    body=text(project,False)
    source=fingerprint(project) if body.strip() else None
    analysis=project.get('asset_analysis',{})
    if source and analysis.get('source_hash')==source and analysis.get('status') in ('completed','queued','running'):return
    project['asset_analysis']={'source_type':kind(project),'source_hash':source,'status':'pending','task_id':None,'message':'剧本已准备好，请手动点击“提取元素外观与性格”' if source else '请先完成剧本，再手动提取元素'}
