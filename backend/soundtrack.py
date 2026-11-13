"""Storyboard-driven instrumental scoring through the saved MiniMax Music 3 graph."""
import copy, hashlib, json, os, re, secrets, time
from pathlib import Path
from . import ai, comfy, store, storyboard_prose, h3_workflow,workflow_files
SOURCE=workflow_files.ROOT/'audio_minimax_music_3.json'
RULE='你是一位AI配乐大师,擅长制作各种类型的音乐,现在需要根据上传的文本创作一个与故事内容、时代、氛围契合的纯音乐。请仔细阅读故事文本,为我生成用于AI音乐生成的提示词,提示词中音乐风格并空格隔开,例如:流行音乐 钢琴吉他,请勿输入歌星名字或非风格描述,否则会生成失败。'
def caption(track,duration):
    return styles(track.get('prompt'))

def rows(p,target=None):
    result=[{'id':s['id'],'index':i+1,'duration':s.get('duration',0),'script':storyboard_prose.shot_text(p,s,i+1)} for i,s in enumerate(p.get('shots',[])) if not target or s['id']==target]
    if not result:raise ValueError('请先生成具体分镜')
    return result
def fingerprint(p,target=None):
    data={'rows':rows(p,target),'parameters':p.get('parameters',{})}
    if target:data['global_music']={k:p.get('soundtrack',{}).get('all',{}).get(k) for k in ('prompt',)}
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def styles(value):
    if not isinstance(value,str):raise ValueError('音乐风格必须是文字')
    value=' '.join(value.split())
    if not value or len(value)>400 or re.search(r'[\n:：。；;{}<>]',value):raise ValueError('请输入空格分隔的音乐风格及乐器，不含解释、歌星或歌词')
    if any(v in value.lower() for v in ('lyrics','vocals','歌手','歌星','人声','演唱','歌词')):raise ValueError('配乐只允许纯音乐风格及乐器，不填写歌词或人声')
    return value
def generate(p,target,report):
    global_track=p.get('soundtrack',{}).get('all',{})
    report('正在根据分镜分析适合故事时代与氛围的音乐风格标签')
    selected=rows(p,target);duration=sum(s['duration'] for s in selected)
    def check(v):return {'prompt':styles(v.get('prompt')),'duration':duration,'source_hash':fingerprint(p,target),'created':time.time()}
    system=RULE+' 只输出JSON {prompt:空格分隔的音乐风格与乐器标签}。不得返回音乐说明、分段计划、歌词或歌星名字；只保留适合故事时代、氛围和画面风格的标签。若有global_music可参考其风格，保持整体协调。'
    with ai.asset_call_policy('soundtrack_prompt',limit=2,max_tokens=1200,timeout=180):
        return ai.validated_image_response(system,{'storyboard':selected,'duration':duration,'creative_settings':p.get('parameters',{}),'global_music':global_track.get('prompt') if target else None},check)

def graph(prompt,duration,seed,metadata=None):
    metadata=metadata or comfy.info()
    if not SOURCE.is_file():raise ValueError('MiniMax Music 3 工作流不存在，请配置 DIRECTOR_MUSIC_WORKFLOW')
    workflow=json.loads(SOURCE.read_text(encoding='utf-8-sig'));links={x[0]:x for x in workflow['links']};g={}
    for n in workflow['nodes']:
        t=n['type']
        if t not in metadata:raise ValueError('ComfyUI 缺少节点：'+t)
        inputs=copy.deepcopy(n.get('widgets_values_named',{}))
        fields=metadata[t]['input'];allowed={**fields.get('required',{}),**fields.get('optional',{})}
        inputs={k:v for k,v in inputs.items() if k in allowed}
        for slot in n.get('inputs',[]):
            if slot.get('link') in links:
                link=links[slot['link']];inputs[slot['name']]=[str(link[1]),link[2]]
        if t=='SeedNode':inputs['seed']=seed
        if t=='MiniMaxMusic3TextEncode':
            bound=allowed['max_duration'][1]
            if not bound.get('min',1)<=duration<=bound.get('max',600):raise ValueError(f'配乐时长需在 {bound.get("min",1)}–{bound.get("max",600)} 秒内，请分段生成')
            if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>12000:raise ValueError('音乐生成描述需为1至12000字符')
            inputs.update(caption=prompt,lyrics='[Instrumental]',seed=seed,max_duration=duration)
        if t=='KSampler':inputs['seed']=seed
        if t=='SaveAudioAdvanced':inputs.update(filename_prefix='owl/soundtrack',format='flac')
        g[str(n['id'])]=comfy.node(t,**inputs)
    outputs=[k for k,n in g.items() if n['class_type']=='SaveAudioAdvanced']
    g=h3_workflow.prune(g,outputs);h3_workflow.validate_graph(g,metadata)
    return g
def install_routes(app):
    @app.get('/api/projects/{pid}/soundtrack')
    def read(pid:str):
        p=store.get_project(pid);result=copy.deepcopy(p.get('soundtrack',{}))
        for key,value in result.items():
            try:value['stale']=value.get('source_hash')!=fingerprint(p,None if key=='all' else key)
            except ValueError:value['stale']=True
        return {'rows':rows(p) if p.get('shots') else [],'tracks':result}
    @app.post('/api/projects/{pid}/soundtrack/{action}')
    def act(pid:str,action:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            p=store.get_project(pid)
            if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请刷新后重试')
            target=body.get('target') or None;source=fingerprint(p,target);key=target or 'all'
            if action=='prompt':
                return jobs.enqueue('music_prompt',p,target)
            if action=='save':
                duration=float(body.get('duration',sum(x['duration'] for x in rows(p,target))))
                if not 1<=duration<=360:raise ValueError('配乐时长需在1–360秒内')
                def apply(current):
                    track=current.setdefault('soundtrack',{}).setdefault(key,{})
                    track.update(prompt=styles(body.get('prompt')),duration=duration,source_hash=source)
                    track.pop('brief',None);track.pop('segments',None)
                return store.mutate(pid,apply)
            if action=='generate':
                track=p.get('soundtrack',{}).get(key,{})
                if track.get('source_hash')!=source:raise ValueError('分镜依据已变化，请重新生成或复核保存配乐提示词')
                duration=float(body.get('duration',sum(x['duration'] for x in rows(p,target))))
                prompt=caption(track,duration)
                if not 1<=duration<=360:raise ValueError('配乐时长需在1–360秒内，超出请按分镜分段生成')
                return jobs.enqueue('music_generate',p,target,{'prompt':prompt,'duration':duration,'seed':secrets.randbelow(2147483648),'media_kind':'audio','source_hash':source})
            raise ValueError('未知配乐操作')
