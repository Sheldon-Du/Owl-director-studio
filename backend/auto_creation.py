"""Durable orchestration of existing production jobs; no monolithic AI output."""
import copy
import hashlib
import json
import threading
import time
from . import store, jobs, script_source, script_workflows, story_promo, storyboard_generation, ai, keyframes

LEGACY_STEPS = [('analyze','故事分析与参数预填'),('script','忠于故事剧本化'),
         ('script_adopt','自动采用剧本'),('novel','第一步 · 推文体整理'),
         ('video','第二步 · 画面化推文'),('promo_adopt','自动采用视频推文'),
         ('recommend','镜头与美术推荐'),('script_assets','提取资产元素'),
         ('enrich','补全描述与图片提示词'),('prompts','补齐资产图片提示词'),
         ('previews','ComfyUI 生成资产图'),('outline','生成分镜汇总'),
         ('outline_adopt','自动采用分镜汇总'),('shots','生成具体分镜描写'),
         ('frame_plans','编写首帧与关键帧提示词'),('layouts','Blender 生成布局图')]
STEPS=[row for row in LEGACY_STEPS if row[0] not in ('script','script_adopt')]
LOCK=threading.RLock()
STOP=threading.Event()
LAUNCH=None

def table(c):
    c.execute('CREATE TABLE IF NOT EXISTS auto_creation (project_id TEXT PRIMARY KEY, body TEXT)')

def read(pid):
    with store.connect() as c:
        table(c);row=c.execute('SELECT body FROM auto_creation WHERE project_id=?',(pid,)).fetchone()
    run=json.loads(row[0]) if row else None
    if run and run.get('flow_version',1)<2:
        stage=LEGACY_STEPS[min(run['step'],len(LEGACY_STEPS)-1)][0] if run['step']<len(LEGACY_STEPS) else None
        run['step']=next((i for i,row in enumerate(STEPS) if row[0]==stage),len(STEPS) if stage is None else 1)
        run['flow_version']=2
    return run

def write(run):
    run['updated']=time.time()
    with store.connect() as c:
        table(c);c.execute('INSERT OR REPLACE INTO auto_creation VALUES (?,?)',(run['project_id'],json.dumps(run,ensure_ascii=False)))

def describe(run):
    return {**(run or {}),'steps':[{'id':key,'name':name,'done':key in (run or {}).get('done_stages',[])} for key,name in STEPS]}

def control(pid,action,revision=None):
    with LOCK,jobs.TASK_LOCK:
        p=store.get_project(pid);run=read(pid)
        if action=='start':
            if revision!=p['revision']:raise store.Conflict('项目已更新，请保存最新故事后再启动')
            if run and run['status'] in ('running','paused','failed'):raise ValueError('已有自动流程，请继续或结束本次流程')
            if not p.get('story','').strip():raise ValueError('请先粘贴完整故事')
            if any(t['status'] in ('queued','running','cancelling','reload_wait') for t in current_tasks(pid)):
                raise ValueError('本项目仍有任务执行，请等这些任务完成后启动自动流程，避免覆盖正在使用的设定')
            cfg=store.settings()
            if not cfg.get('ai_url') or not cfg.get('ai_model'):raise ValueError('请先配置文本 AI')
            from . import blender_render,creative_rules
            blender_render.executable()
            p=store.save_project(p,p['revision'])
            run={'id':store.uid(),'project_id':pid,'status':'running','step':0,'started':time.time(),
                 'flow_version':2,'story_hash':hashlib.sha256(p['story'].encode()).hexdigest(),'records':{},'message':'已启动，准备分析故事',
                 'adoption_policy':'用户授权自动推进；自动采用不代表人工语义审查'}
        elif not run:raise ValueError('尚未启动自动流程')
        elif action=='pause':
            run.update(status='paused',message='已暂停后续步骤；已提交的任务继续完成并保存')
        elif action=='resume':
            if run['status'] not in ('paused','failed'):raise ValueError('当前流程无需继续')
            if run.get('restart_required'):raise ValueError('生成依据已手动修改，请结束旧流程后重新启动；有效结果仍会复用')
            if hashlib.sha256(p.get('story','').encode()).hexdigest()!=run['story_hash']:raise ValueError('故事已修改，请结束旧流程后重新启动')
            run.update(status='running',message='继续未完成步骤',error='')
        elif action=='stop':run.update(status='stopped',message='已结束自动流程，已有结果保留；已提交的任务继续保存')
        elif action!='start':raise ValueError('不支持的自动流程操作')
        write(run);return describe(run)

def pause_for_edit(pid):
    with LOCK:
        run=read(pid)
        if run and run['status']=='running':
            run.update(status='paused',restart_required=True,message='生成依据已手动修改，自动流程暂停；请结束旧流程后重新启动，有效结果会复用');write(run)

def current_tasks(pid):
    return [t for t in store.task_list() if t['project_id']==pid]

def submit(p,run,key,kind,target=None,options=None):
    options={**(options or {}),'auto_parallel':True}
    matching=[t for t in current_tasks(p['id']) if t['kind']==kind and t.get('target')==target and t['status'] in ('queued','running','cancelling','reload_wait')
              and all(t.get('options',{}).get(k)==v for k,v in options.items() if k in ('stage','mode'))]
    if matching:task=matching[0]
    elif kind=='story_promo':task=jobs.enqueue(kind,p,target,options)
    else:task=LAUNCH(p['id'],kind,{'revision':p['revision'],'target':target,'options':options})
    saved_task=store.task_get(task['id'])
    saved_task.setdefault('options',{})['auto_parallel']=True;store.task_save(saved_task)
    run['records'][key]={'task_id':task['id'],'status':'submitted','kind':kind,'target':target,'options':options}
    write(run)

def adopt_script(p):
    docs=p.get('documents',{})
    if not script_source.text(p):raise ValueError('没有有效剧本正文')
    if '【对白 · 待确认】' in docs['script']:raise ValueError('剧本仍有说话人待确认，请先修改后继续')
    review=docs.get('script_expression_review')
    if isinstance(review,dict):review.update(semantic_fidelity='automation_adopted_pending_review',audience_delivery='automation_adopted_pending_review',
                            confirmed_script_hash=hashlib.sha256(docs['script'].encode()).hexdigest(),adoption_method='auto_creation')
    p['script_confirmed']=True;script_source.accept(p);script_workflows.refresh(p);script_source.mark_extraction_pending(p)
    return store.save_project(p,p['revision'])

def work(p,stage):
    """Return keyed units; empty means valid saved output is reused."""
    if stage=='analyze':return [] if script_source.screenplay(p,False) or (p.get('summary') and any(t['kind']=='analyze' and t['status']=='completed' and t.get('snapshot',{}).get('story')==p.get('story') for t in current_tasks(p['id']))) or p.get('analysis_source_hash')==hashlib.sha256(p.get('story','').encode()).hexdigest() else [('analyze','analyze',None,{})]
    if stage=='script':return [] if script_source.text(p,False) and p.get('documents',{}).get('script_policy')=='screenplay' else [('script','script',None,{})]
    if stage in ('novel','video'):
        try:story_promo.current(p,stage);return []
        except ValueError:return [(stage,'story_promo',None,{'stage':stage})]
    if stage=='recommend':return [] if p.get('scheme_recommendation',{}).get('source_hash')==ai.recommendation_fingerprint(p) else [('recommend','recommend',None,{})]
    if stage=='script_assets':
        a=p.get('asset_analysis',{})
        return [] if a.get('status')=='completed' and a.get('source_hash')==script_source.fingerprint(p) else [('script_assets','script_assets',None,{})]
    if stage in ('enrich','prompts','previews'):
        assets=p.get('assets',[])
        if not assets:raise ValueError('未提取到资产元素，请检查剧本或提取记录')
        kind={'enrich':'asset_enrich','prompts':'asset_prompt','previews':'preview'}[stage]
        units=[]
        for a in assets:
            if stage=='enrich':
                from . import asset_enrichment
                if a.get('variant') or a.get('enrichment_source_hash')==asset_enrichment.fingerprint(p,a):continue
                if a.get('visual_profile') and not a.get('style_needs_refresh') and not a.get('profile_stale') and not jobs.preview_needs_prompt(a):continue
            if stage=='prompts' and not jobs.preview_needs_prompt(a):continue
            if stage=='previews' and any(m.get('media') and not m.get('stale') for m in a.get('previews',[])):continue
            units.append((stage+':'+a['id'],kind,a['id'],{'ensure_prompt':True} if stage=='previews' else {}))
        return units
    if stage=='outline':
        state=storyboard_generation.valid_state(p)
        return [] if state and state.get('outlines') and not state.get('outline_draft') else [('outline','storyboard_outline',None,{})]
    if stage=='shots':
        state=storyboard_generation.valid_state(p)
        return [] if state and state.get('status')=='completed' and state.get('completed')==state.get('total') and p.get('shots') else [('shots','storyboard',None,{})]
    if stage in ('frame_plans','layouts'):
        units=[]
        if not p.get('shots'):raise ValueError('尚无分镜描写')
        for s in p['shots']:
            if not s.get('native'):raise ValueError('分镜描写未完成')
            for mode in ('frame','keyframe'):
                plan=s.get('image_plans',{}).get(mode,{})
                if stage=='frame_plans':
                    if plan.get('prompt') and plan.get('layout_scene') and plan.get('source_hash')==keyframes.fingerprint(p,s):continue
                    units.append((stage+':'+s['id']+':'+mode,'frame_plan',s['id'],{'mode':mode,'propose_assets':True,'render_layout':False}))
                else:
                    if not plan.get('layout_scene'):raise ValueError('请先完成首帧与关键帧布局指令')
                    from . import stage3d
                    capture=next((m for m in s.get('stage3d_captures',[]) if m.get('media')==plan.get('composition_reference') and not m.get('stale') and m.get('layout_hash')==stage3d.digest(plan['layout_scene'])),None)
                    if capture:continue
                    units.append((stage+':'+s['id']+':'+mode,'stage3d_render',s['id'],{'mode':mode,'time':0}))
        return units
    return []

DEPENDENCIES={
 'analyze':[], 'novel':['analyze'], 'video':['novel'], 'promo_adopt':['video'],
 'recommend':['promo_adopt'], 'script_assets':['recommend'], 'enrich':['script_assets'],
 'prompts':['enrich'], 'previews':['prompts'], 'outline':['recommend'],
 'outline_adopt':['outline'], 'shots':['outline_adopt'],
 'frame_plans':['shots','enrich','prompts','previews'], 'layouts':['frame_plans']}


def advance_stage(pid,run,p,stage,name):
    prefix=stage+':'
    records={k:r for k,r in run['records'].items() if k==stage or k.startswith(prefix)}
    tasks={t['id']:t for t in current_tasks(pid)}
    active=False
    for k,r in records.items():
        if r.get('status') in ('completed','failed'):continue
        task=tasks.get(r['task_id'])
        if not task:raise ValueError('流程任务记录缺失，请检查任务队列')
        if task['status']=='completed':r['status']='completed'
        elif task['status'] in ('failed','cancelled'):
            message=task.get('error') or task.get('message') or '任务未完成'
            from .creation_recovery import decide
            decision=decide(r['kind'],message,task['status']=='cancelled')
            if decision['action']=='retry' and r.get('retries',0)<2:
                if decision.get('delay'):
                    r.setdefault('retry_at',time.time()+decision['delay'])
                    if time.time()<r['retry_at']:
                        run['message']=name+' · '+decision['reason'];write(run);return
                retries=r.get('retries',0)+1
                options={**r['options'],'recovery_strategy':decision['strategy']}
                run.setdefault('recovery_history',[]).append({'created':time.time(),'step':name,'unit':k,'attempt':retries,
                    'error':message[:1500],'decision':decision['reason'],'strategy':decision['strategy']})
                submit(store.get_project(pid),run,k,r['kind'],r['target'],options)
                run['records'][k]['retries']=retries
                run['message']=f'{name} · 自动恢复 {retries}/2：'+decision['reason']
                write(run);return
            if r.get('status')=='failed':continue  # Explicit resume may retry this unit.
            r['status']='failed';write(run)
            raise ValueError(message)
        else:active=True
    if active:
        run['message']=f'{name} · 已完成 {sum(r.get("status")=="completed" for r in records.values())}/{len(records)} 项';write(run);return
    if stage=='script_assets' and records and p.get('asset_analysis',{}).get('status')=='partial':
        r=run['records'][stage]
        if r.get('status')!='failed':r['status']='failed';write(run);raise ValueError('资产提取部分失败，已完成元素保留，点击继续补齐失败项')
    if stage=='script_adopt':adopt_script(p)
    elif stage=='promo_adopt':
        row=story_promo.current(p,'video')
        adopted=story_promo.input_values(p)
        if not adopted or adopted['stale'] or adopted['id']!=row['id']:
            p.setdefault('story_promo',{})['adopted']={k:copy.deepcopy(row[k]) for k in ('id','text','source_hash')}
            p['story_promo']['adopted']['adoption_method']='auto_creation';story_promo.mark_script(p);store.save_project(p,p['revision'])
    elif stage=='outline_adopt':
        state=storyboard_generation.valid_state(p)
        if not state or not state.get('outlines') or state.get('outline_draft'):raise ValueError('没有完整有效的分镜汇总')
        state['outline_confirmed']=True;state.setdefault('outline_review',{}).update(semantic_fidelity='automation_adopted_pending_review',atomic_granularity='automation_adopted_pending_review',review_basis='自动流程采用，未进行人工语义审查')
        store.save_project(p,p['revision'])
    else:
        units=work(p,stage)
        # Remember failed work even if a partial result would otherwise look reusable.
        for k,r in records.items():
            if r.get('status')=='failed' and not any(u[0]==k for u in units):units.append((k,r['kind'],r['target'],r['options']))
        pending=[u for u in units if run['records'].get(u[0],{}).get('status')!='completed']
        if pending:
            for k,kind,target,options in pending:submit(store.get_project(pid),run,k,kind,target,options)
            run['message']=name+' · 任务已提交';write(run);return
    return True


def tick(pid):
    with LOCK,jobs.TASK_LOCK:
        run=read(pid)
        if not run or run['status']!='running':return
        p=store.get_project(pid)
        if hashlib.sha256(p.get('story','').encode()).hexdigest()!=run['story_hash']:raise ValueError('故事已修改，请结束旧流程并重新启动')
        done=set(run.setdefault('done_stages',[key for key,_ in STEPS[:run['step']]]))
        active=[]
        for stage,name in STEPS:
            if stage in done or not set(DEPENDENCIES[stage]).issubset(done):continue
            if stage in ('outline','shots') and 'enrich' not in done and any(a.get('visual_profile_source')=='user' or '"source": "user"' in json.dumps(a.get('visual_profile',{}),ensure_ascii=False) for a in store.get_project(pid).get('assets',[])):continue
            if advance_stage(pid,run,store.get_project(pid),stage,name):
                done.add(stage);run['done_stages']=list(done)
            else:active.append(name)
        run['step']=next((i for i,(stage,_) in enumerate(STEPS) if stage not in done),len(STEPS))
        run['completed_steps']=len(done)
        if len(done)==len(STEPS):
            run.update(status='completed',finished=time.time(),message='资产图、分镜描写、首帧／关键帧提示词及布局图已完成；可选择参考图片继续生图')
        else:run['message']='并行处理中：'+' ｜ '.join(active)
        write(run)


def loop():
    while not STOP.wait(2):
        with store.connect() as c:
            table(c);ids=[r[0] for r in c.execute('SELECT project_id FROM auto_creation')]
        for pid in ids:
            try:tick(pid)
            except Exception as error:
                with LOCK:
                    run=read(pid)
                    if run and run['status']=='running':run.update(status='failed',error=str(error),message='流程已停止，已完成内容保留：'+str(error));write(run)

def start(launch):
    global LAUNCH
    LAUNCH=launch;STOP.clear();threading.Thread(target=loop,daemon=True,name='auto-creation').start()

def install_routes(app):
    @app.get('/api/projects/{pid}/auto-creation')
    def state(pid:str):store.get_project(pid);return describe(read(pid))
    @app.post('/api/projects/{pid}/auto-creation/{action}')
    def action(pid:str,action:str,body:dict):return control(pid,action,body.get('revision'))
