"""Read-only ComfyUI websocket progress attached to a persisted Owl task."""
import asyncio,json,threading,time
from contextlib import contextmanager

def stage_name(task,node,kind):
    lower=kind.lower()
    if 'sampler' in lower:
        if task.get('kind')=='h3_upscale':
            return '高清采样' if 'tiled' in lower or str(node)=='346' else '一采重放'
        return '视频采样' if task.get('kind')=='h3_generate' else '采样生成'
    if 'upscal' in lower:return '高清放大'
    if 'decode' in lower:return '画面解码'
    if 'encode' in lower or 'clip' in lower:return '参考与音频编码'
    if 'combine' in lower or 'save' in lower:return '保存输出'
    if 'loader' in lower:return '加载模型'
    return '准备生成'

def consume(task,event,graph):
    """Update only this prompt; percentages describe a node, never the whole job."""
    data=event.get('data') or {};kind=event.get('type')
    if data.get('prompt_id') and str(data['prompt_id'])!=str(task.get('prompt_id')):return False
    state=task.setdefault('comfy_progress',{'stages':[]})
    if kind=='progress_state':
        changed=False
        for node,entry in (data.get('nodes') or {}).items():
            if entry.get('state') in ('finished','completed'):
                old=next((r for r in state.get('stages',[]) if r['node_id']==str(node)),None)
                if old:old.update(current=old['total'],percent=100)
                continue
            if entry.get('state')!='running':continue
            changed=consume(task,{'type':'progress','data':{'node':node,'value':entry.get('value',0),'max':entry.get('max',0)}},graph) or changed
        return changed
    if kind=='executing':
        node=data.get('node')
        if node is None:state.update(status='finishing',phase='保存输出');return True
        node=str(node);spec=graph.get(node,{})
        if state.get('node_id')==node:return False
        state.update(node_id=node,node_type=spec.get('class_type',''),phase=stage_name(task,node,spec.get('class_type','')),status='running',current=None,total=None,percent=None)
    elif kind=='progress':
        node=str(data.get('node') or state.get('node_id') or '')
        try:total=float(data.get('max',0));value=float(data.get('value',0))
        except (ValueError,TypeError):return False
        if total<=0:return False
        value=max(0,min(total,value));spec=graph.get(node,{})
        row={'node_id':node,'node_type':spec.get('class_type',''),'phase':stage_name(task,node,spec.get('class_type','')),'current':value,'total':total,'percent':round(value/total*100,1)}
        stages=state.setdefault('stages',[]);old=next((r for r in stages if r['node_id']==node),None)
        if old:old.update(row)
        else:stages.append(row)
        state.update(row,status='running');state['stages']=stages[-8:]
    elif kind in ('execution_success','execution_error','execution_interrupted'):
        state['status']={'execution_success':'completed','execution_error':'failed','execution_interrupted':'cancelled'}[kind]
    else:return False
    state['updated']=time.time();return True

@contextmanager
def monitor(task):
    from . import comfy,store
    stop=threading.Event()
    async def listen():
        import aiohttp
        graph={}
        try:
            queue=comfy.request('GET','/queue')
            row=next((r for r in queue.get('queue_running',[])+queue.get('queue_pending',[]) if str(r[1])==str(task['prompt_id'])),None)
            if row:graph=row[2]
        except Exception:pass
        last_save=0
        while not stop.is_set():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(comfy.url().replace('https:','wss:').replace('http:','ws:')+'/ws',params={'clientId':'director-studio-'+task['id']},heartbeat=20) as ws:
                        while not stop.is_set():
                            try:message=await ws.receive(timeout=1)
                            except asyncio.TimeoutError:continue
                            if message.type!=aiohttp.WSMsgType.TEXT:
                                if message.type in (aiohttp.WSMsgType.CLOSED,aiohttp.WSMsgType.ERROR):break
                                continue
                            event=json.loads(message.data)
                            from .jobs import TASK_LOCK
                            with TASK_LOCK:
                                if task.get('status') not in ('running','cancelling'):return
                                if consume(task,event,graph):
                                    now=time.monotonic()
                                    if now-last_save>=.5 or event.get('type')!='progress':
                                        store.task_save(task);last_save=now
            except Exception:
                # Progress is best effort; never fail or duplicate a generation.
                pass
            await asyncio.sleep(1)
    def run():
        try:asyncio.run(listen())
        except Exception:pass
    worker=threading.Thread(target=run,name='comfy-progress-'+task['id'],daemon=True);worker.start()
    try:yield
    finally:stop.set();worker.join(timeout=2)
