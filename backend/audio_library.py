"""Remove an audio candidate from a project without deleting its file."""
import copy,time
from . import store

def remove(project,media_id):
    item=next((m for m in project.get('media',[]) if m.get('id')==media_id and m.get('kind')=='audio'),None)
    if not item:raise ValueError('音频不存在或已经删除')
    name=item['media']
    project.setdefault('audio_trash',[]).append({**copy.deepcopy(item),'removed_at':time.time()})
    project['media']=[m for m in project['media'] if m.get('media')!=name]
    project['timeline']=[c for c in project.get('timeline',[]) if c.get('media')!=name]
    for track in project.get('soundtrack',{}).values():
        track['outputs']=[m for m in track.get('outputs',[]) if m.get('media')!=name]

def install_routes(app):
    @app.post('/api/projects/{pid}/audio/{mid}/remove')
    def delete(pid:str,mid:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            p=store.get_project(pid)
            if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请加载最新内容后重试')
            if body.get('purge_file'):
                from . import audio_delete
                audio_delete.purge(p,mid)
            else:remove(p,mid)
            return store.save_project(p,p['revision'])
