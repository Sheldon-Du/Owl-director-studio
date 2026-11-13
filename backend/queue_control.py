"""Durable queue pause and model affinity; running tasks are never interrupted."""
import json,time
from . import store

def settings():
    path=store.DATA/'queue-control.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'paused':False,'affinity':''}

def update(**values):
    state={**settings(),**values,'updated':time.time()}
    path=store.DATA/'queue-control.json';temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state,ensure_ascii=False),encoding='utf-8');temporary.replace(path)
    return state

def is_paused():return bool(settings().get('paused'))

def media_batch(task):
    opts=task.get('options',{});kind=task['kind'];snapshot=task.get('snapshot',{})
    if opts.get('tts_engine')=='yovoice' or opts.get('yovoice_timing'):
        models=sorted({line.get('voice',{}).get('yovoice_model','') for line in opts.get('speech_lines',[])})
        return 'yovoice:'+str(opts.get('yovoice_model') or ','.join(models))
    if kind in ('frame','keyframe','tail'):return 'image:qwen-image-2.1'
    if kind in ('preview','character_card'):
        asset=next((a for a in snapshot.get('assets',[]) if a.get('id')==task.get('target')), {})
        return 'image:'+str(asset.get('model','qwen-image-2.1'))
    if kind in ('h3_generate','h3_upscale'):return 'video:minimax-h3'
    return 'media:'+kind

def comfy_order(rows):
    from . import jobs
    affinity=settings().get('affinity','')
    queued=[t for t in rows if t['status']=='queued' and jobs.task_queue(t) is jobs.COMFY_QUEUE and not t.get('cancel_requested')]
    oldest=sorted(queued,key=lambda t:(t.get('queued_at',t['created']),t['created'],t['id']))
    if not oldest:return []
    batch=affinity if any(media_batch(t)==affinity for t in oldest) else media_batch(oldest[0])
    keys=[batch]+list(dict.fromkeys(media_batch(t) for t in oldest if media_batch(t)!=batch))
    return [t for key in keys for t in oldest if media_batch(t)==key]

def state():
    rows=store.task_list();active=sum(t['status'] in ('running','cancelling') for t in rows);paused=is_paused()
    return {'paused':paused,'draining':paused and active>0,'active':active,'queued':sum(t['status']=='queued' for t in rows)}

def install(app):
    @app.get('/api/queue/control')
    def view():return state()
    @app.post('/api/queue/control')
    def change(body:dict):
        from . import jobs
        if type(body.get('paused')) is not bool:raise ValueError('paused 需要布尔值')
        with jobs.TASK_CONDITION:
            update(paused=body['paused']);jobs.TASK_CONDITION.notify_all();return state()
