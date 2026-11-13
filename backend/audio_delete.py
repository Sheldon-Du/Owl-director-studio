"""Delete only validated project audio paths after checking live references."""
import copy
from . import store

def contains(value,name):
    if isinstance(value,dict):return any(contains(v,name) for v in value.values())
    if isinstance(value,list):return any(contains(v,name) for v in value)
    return value==name

def purge(project,identity):
    from . import yovoice_cli as y,audio_library
    item=next((m for m in project.get('media',[]) if m.get('id')==identity and m.get('kind')=='audio'),None)
    if not item:raise ValueError('音频不存在或已删除')
    name=item['media'];path=store.media_path(name)
    # media_path resolves symlinks and verifies the workspace media boundary.
    candidates=[v for v in y.own_voices() if v.get('media')==name]
    ids={v['filename'] for v in candidates}
    projects=store.list_projects(include_deleted=True)
    for p in projects:
        if p['id']!=project['id'] and contains(p,name):raise ValueError('音频仍被其他项目引用：'+p['name']+'；请先移除该引用')
        for role,binding in p.get('tts_voice_roles',{}).items():
            if binding.get('voice_filename') in ids:raise ValueError('此声音仍绑定角色 '+p['name']+' / '+role+'，请先改绑其他音色')
    for task in store.task_list():
        if task['status'] in ('queued','running','cancelling') and (task['project_id']==project['id'] or contains(task.get('options',{}),name)):
            raise ValueError('相关项目正在执行任务，请任务结束后删除')
    # Do not remove imported samples also attached to another candidate.
    for v in y.own_voices():
        if v.get('media')==name and v['filename'] not in ids:raise ValueError('文件仍被其他音色引用')
    # Reject uses as another input/reference in this project, outside generated speech caches.
    probe=copy.deepcopy(project)
    for field in ('media','timeline','audio_trash','shots','soundtrack'):probe.pop(field,None)
    if contains(probe,name):raise ValueError('文件仍被项目中的参考设置使用，请先更换参考')
    for shot in project.get('shots',[]):
        other={k:v for k,v in shot.items() if k not in ('speech_audio','speech_track','speech_mix','actions')}
        if contains(other,name):raise ValueError('文件仍被分镜参考使用，请先更换参考')
    # Unlink first: a permissions failure must leave project entries intact.
    path.unlink(missing_ok=True)
    for v in candidates:
        record=store.DATA/'yovoice-voices'/(v['filename'][4:]+'.json')
        record.unlink(missing_ok=True)
    trash=store.DATA/'yovoice-voice-trash.json'
    if trash.exists():
        import json
        rows=[v for v in y.voice_trash() if v.get('media')!=name]
        trash.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    audio_library.remove(project,identity)
    project['audio_trash']=[m for m in project.get('audio_trash',[]) if m.get('media')!=name]
    for shot in project.get('shots',[]):
        cache=shot.get('speech_audio',{})
        removed=[k for k,v in cache.items() if v.get('media')==name]
        for key in removed:cache.pop(key)
        if removed or contains(shot.get('speech_track',{}),name):
            shot['natural_status']='unverified'
            shot.pop('speech_track',None);shot.pop('speech_mix',None)
        for action in shot.get('actions',[]):
            rows=action.get('measured_speech',[])
            if any(r.get('media')==name for r in rows):
                action['measured_speech']=[r for r in rows if r.get('media')!=name]
                action.pop('measured_speech_seconds',None)
    return name
