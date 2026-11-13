"""Independent candidate storage for first, key and last frames."""
from . import store,shot_frames
FIELDS={'frame':('frames','first_frame','frame_trash'),'keyframe':('keyframes','adopted_keyframe','keyframe_trash'),'tail':('tailframes','adopted_tailframe','tailframe_trash')}

def change(project,sid,mode,action,media):
    if mode not in FIELDS:raise ValueError('帧类型无效')
    if mode=='frame':return shot_frames.change(project,sid,action,media)
    shot=next((s for s in project['shots'] if s['id']==sid),None)
    if not shot:raise ValueError('镜头不存在')
    rows,adopted,trash=FIELDS[mode]
    items=shot.setdefault(rows,[]);removed=shot.setdefault(trash,[])
    pool=removed if action=='restore' else items
    item=next((r for r in pool if r['media']==media),None)
    if not item:raise ValueError('请从本阶段候选中选择图片')
    if action=='adopt':shot[adopted]=media
    elif action=='remove':
        items.remove(item);removed.append(item)
        if shot.get(adopted)==media:shot.pop(adopted,None)
    elif action=='restore':removed.remove(item);items.append(item)
    else:raise ValueError('候选操作无效')
    if mode=='tail':
        from . import visual_reference
        # The first adoption initializes a planned link. Later changes only flag it.
        for next_shot in project['shots']:
            link=next_shot.get('first_frame_link',{})
            if action=='adopt' and link.get('source_id')==sid and link.get('mode')=='previous_tail' and not link.get('media'):
                visual_reference.pin(project,next_shot)
        visual_reference.tail_changed(project,shot)

def install(app):
    @app.post('/api/projects/{pid}/shots/{sid}/frame-images/{mode}/{action}')
    def action(pid:str,sid:str,mode:str,action:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            p=store.get_project(pid)
            if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请刷新后重试')
            change(p,sid,mode,action,body.get('media'))
            return store.save_project(p,p['revision'])
