import copy
import json
import hashlib
import queue
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from . import store, director, comfy, ai, timing, exporter, h3, image_prompts, h3_workflow,card_layout,character_profiles,asset_profiles,script_source,scene_identity,storyboard_generation,asset_references
from . import video_versions, shot_frames, shot_asset_binding, production_canvas, stage3d
from . import task_details,asset_card_render,image_composition,image_text,workflow_files

QUEUE=queue.Queue()
CONTINUATION_QUEUE=queue.Queue()
COMFY_QUEUE=queue.Queue()
EXPORT_QUEUE=queue.Queue()
AGENT_QUEUE=queue.Queue()
COMFY_KINDS={'tail','music_generate','preview','asset_upscale','character_mod','frame','keyframe','generate','audio','character_card','h3_generate','h3_upscale'}
CANCEL=set()
TASK_LOCK=threading.RLock()
TASK_CONDITION=threading.Condition(TASK_LOCK)
STORYBOARD_STAGE_TIMEOUT=330


def check_cancelled(task):
    if task['id'] in CANCEL or task.get('cancel_requested'):
        raise InterruptedError('已取消，停止后续执行和结果回填')


def mutate_task(task,operation):
    with TASK_LOCK:
        check_cancelled(task)
        return store.mutate(task['project_id'],operation)


def progress(task,message):
    with TASK_LOCK:
        check_cancelled(task)
        task['message']=message
        now=time.time();stage=message.split(' · 本阶段已等待 ')[0]
        if task.get('stage_message')!=stage:
            task['stage_message']=stage;task['stage_started']=now
            task['stage_history']=[*task.get('stage_history',[]),{'time':now,'message':stage}][-18:]
        task['updated']=now
        store.task_save(task)


def cancel(task_id):
    with TASK_LOCK:
        task=store.task_get(task_id)
        if task['status'] in ('queued','running','cancelling'):
            CANCEL.add(task_id)
            task['cancel_requested']=True
            task['status']='cancelled' if task['status']=='queued' else 'cancelling'
            task['message']='已取消排队任务' if task['status']=='cancelled' else '正在取消，停止当前执行…'
            if task['status']=='cancelled':
                task['finished']=time.time()
                task.pop('snapshot',None)
            store.task_save(task)
            TASK_CONDITION.notify_all()
        return {k:v for k,v in task.items() if k not in ('snapshot','options')}


def cancel_all():
    """Cancel the current global queue, retaining all completed work."""
    with TASK_LOCK:
        active=[t for t in store.task_list() if t['status'] in ('queued','running','cancelling')]
        active.sort(key=lambda t:t['status']!='queued')
        rows=[cancel(t['id']) for t in active]
        return {'cancelled':sum(t['status']=='cancelled' for t in rows),
                'cancelling':sum(t['status']=='cancelling' for t in rows),
                'task_ids':[t['id'] for t in rows]}


def text_result(task,report=None,on_asset=None,metrics=None):
    if task['kind']=='medical_ocr':
        from . import local_ocr
        return local_ocr.generate(task, report or (lambda message: None))
    if task['kind']=='medical_director':
        from . import medical_director
        return medical_director.generate(task, report or (lambda message: None))
    if task['kind']=='authoring_step':
        from . import authoring
        return authoring.generated(task,report)
    report=report or (lambda message:None)
    p=task['snapshot']
    from . import seedance_integration as seedance
    if task['kind'] in seedance.KINDS:return seedance.generate(task,report)
    if task['kind']=='frame_layout':
        from . import frame_layout
        return frame_layout.generate(p,next(s for s in p['shots'] if s['id']==task['target']),task['options'],report)
    if task['kind'] in ('story_promo','asset_prompt','frame_plan','keyframe_prepare','asset_enrich','script_assets'):
        p=seedance.filtered_project(p)
    if task['kind']=='frame_plan':
        from . import frame_plans
        return frame_plans.generate(p,next(s for s in p['shots'] if s['id']==task['target']),task['options'],report)
    if task['kind']=='asset_enrich':
        from . import asset_enrichment
        return (asset_enrichment.redo_card if task.get('options',{}).get('rebuild_card') else asset_enrichment.generate)(p,next(a for a in p['assets'] if a['id']==task['target']),report)
    if task['kind']=='asset_explore':
        from . import asset_exploration
        return asset_exploration.generate(p,report)
    if task['kind']=='music_prompt':
        from . import soundtrack
        return soundtrack.generate(p,task.get('target'),report)
    if task['kind']=='keyframe_prepare':
        from . import keyframes
        return keyframes.generate(p,next(s for s in p['shots'] if s['id']==task['target']),report)
    if task['kind']=='story_promo':
        from . import story_promo
        return story_promo.generate(p,task['options']['stage'],report)
    if task['kind']=='skill_plan':
        from . import skill_workflows
        return skill_workflows.generate(p,task['options'],report)
    if task['kind']=='agent_decide':
        from . import agent
        report('正在理解当前项目与对话')
        return agent.decide(task)
    if task['kind']=='stage3d_plan':
        return stage3d.recommend(p,task['target'],report,task.get('options',{}).get('description',''))
    if task['kind']=='plan':
        return director.plan(p,store.settings(),progress=report)
    if task['kind']=='script':
        return director.script(p,store.settings(),progress=report,plan_only=bool(task.get('options',{}).get('plan_only')),approved_plan=task.get('options',{}).get('approved_plan'),on_event=on_asset,metrics=metrics,force=bool(task.get('options',{}).get('force')))
    if task['kind']=='recommend':
        report('正在按原生规则预读已确认剧本，推荐镜头与美术方案')
        return ai.recommend(p)
    if task['kind'] in ('storyboard','storyboard_outline'):
        return storyboard_generation.generate(p,store.settings(),progress=report,on_event=on_asset,metrics=metrics,force=bool(task.get('options',{}).get('force')),
            plan_only=task['kind']=='storyboard_outline', require_outline=bool(task.get('options',{}).get('require_outline')),
            target_outline=task.get('target'),regenerate=bool(task.get('options',{}).get('regenerate')))
    if task['kind']=='canvas_links':
        return production_canvas.associate(p,report,on_asset,metrics)
    if task['kind']=='frame_assets':
        return shot_asset_binding.associate(p,next(s for s in p['shots'] if s['id']==task['target']),report,metrics)
    if task['kind']=='creative_refine':
        from . import creative_revision
        return creative_revision.generate(task,report)
    if task['kind']=='h3':
        return h3.rewrite(p,progress=report,shot_id=task.get('target'))
    if task['kind']=='analyze':
        report('正在阅读故事并预填导演参数')
        return ai.analyze(p,progress=report)
    if task['kind']=='script_assets':
        return ai.script_assets(p,progress=report,on_asset=on_asset,metrics=metrics,force=task.get('options',{}).get('force',False))
    if task['kind']=='schedule':
        report('正在按完整动作修正自然时长' if task.get('options',{}).get('revise_time') else '正在拆解和审查自然动作时序')
        with ai.asset_call_policy('storyboard_timing',metrics,limit=2,max_tokens=8192,timeout=300):
            return ai.schedule(p,next(s for s in p['shots'] if s['id']==task['target']),revise_time=bool(task.get('options',{}).get('revise_time')))
    if task['kind'] in ('character_profile','asset_profile'):
        asset=next(a for a in p['assets'] if a['id']==task['target'])
        report('正在分离 '+asset['name']+' 的外貌、衣着、性格与剧情经历')
        return asset_profiles.extract(p,asset)
    if task['kind']=='asset_prompt':
        return asset_prompt_result(p,task,report,metrics)
    raise ValueError('不支持的文本任务')


def asset_prompt_result(p,task,report,metrics=None):
    from . import seedance_integration as seedance
    asset=next(a for a in p['assets'] if a['id']==task['target'])
    if asset_card_render.uses_card(asset):
        direct=asset_card_render.prompt(asset)
        return {'prompt':direct,'prompt_zh':direct,'prompt_rules':'5S 资产卡直接生图','prompt_mode':'five_s_card','prompt_notes_used':str(asset.get('prompt_notes','')).strip()}
    # Preview preparation and the standalone prompt button share this path.
    # Keep upstream partial responses instead of throwing away and resending.
    with ai.asset_call_policy('asset_image_prompt',metrics,limit=3,max_tokens=16384,timeout=240,preserve_context=True,report=report,reasoning_effort='low'):
        asset=next(a for a in p['assets'] if a['id']==task['target'])
        if asset.get('variant'):
            from . import asset_variants
            return asset_variants.generate(p,asset,report)
        profile=asset_profiles.prepare(p,asset)
        asset={**asset,**profile}
        report('正在生成 '+asset['name']+' 的原生提示词')
        prompt,native=director.asset_prompt(p,asset)
        report('正在按 NeoImage 规则适配 '+asset['name']+' 的图片提示词')
        return {**profile,**image_prompts.generate(p,asset,prompt,native)}
def run_text(task,kind=None):
    check_cancelled(task)
    work=store.DATA/'task-work'/task['id']/store.uid()
    work.mkdir(parents=True,exist_ok=True)
    request_path=work/'request.json';result_path=work/'result.json';progress_path=work/'progress.json'
    request_path.write_text(json.dumps({**task,'kind':kind or task['kind']},ensure_ascii=False),encoding='utf-8')
    env=os.environ.copy();env['DIRECTOR_STUDIO_DATA']=str(store.DATA);env['PYTHONIOENCODING']='utf-8'
    strategy=task.get('options',{}).get('recovery_strategy')
    from .creation_recovery import INSTRUCTIONS
    if strategy in INSTRUCTIONS:env['DIRECTOR_AI_RECOVERY_STRATEGY']=strategy
    child=None
    applied=set();seen=set()
    def drain_events():
        if (kind or task['kind']) not in ('script','script_assets','storyboard','storyboard_outline','canvas_links'):return
        for path in sorted((work/'events').glob('*.json')):
            if path.name in seen:continue
            event=json.loads(path.read_text(encoding='utf-8'))
            if event['type']=='script_checkpoint':apply_script_event(task,event)
            elif event['type']=='canvas_binding':apply_canvas_event(task,event);applied.add(event['shot_id'])
            elif event['type'].startswith('storyboard_'):apply_storyboard_event(task,event)
            else:apply_asset_event(task,event)
            if event['type']=='asset':applied.add((event['item']['kind'],event['item']['name']))
            seen.add(path.name)
    try:
        with (work/'execution.log').open('w',encoding='utf-8') as log:
            child=subprocess.Popen([sys.executable,'-X','utf8',str(Path(__file__).with_name('job_process.py')),str(request_path),str(result_path),str(progress_path),str(os.getpid())],cwd=str(store.ROOT),env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            stage_message='';stage_started=time.monotonic();heartbeat=0
            while child.poll() is None:
                check_cancelled(task)
                drain_events()
                if progress_path.exists():
                    try:
                        message=json.loads(progress_path.read_text(encoding='utf-8'))['message']
                        if message!=stage_message:
                            stage_message=message;stage_started=time.monotonic();heartbeat=0
                            progress(task,message)
                    except (OSError,json.JSONDecodeError,KeyError):
                        pass
                if ((kind or task['kind']) in ('script','storyboard','storyboard_outline') or task['kind']=='storyboard_timing') and stage_message:
                    elapsed=time.monotonic()-stage_started
                    if elapsed>STORYBOARD_STAGE_TIMEOUT:
                        if (kind or task['kind'])=='script':raise TimeoutError('本批剧本等待超过330秒，已保存草稿保留；回剧本页继续编写')
                        raise TimeoutError('时间修正等待超过330秒；已审查动作保留，请点击时间修正继续' if task['kind']=='storyboard_timing' else '分镜汇总等待超过330秒；旧分镜保留，请点击生成分镜汇总重试' if (kind or task['kind'])=='storyboard_outline' else '当前分镜阶段等待超过330秒，已完成镜头保留；点击继续生成未完成分镜重试')
                    if elapsed>=15 and elapsed-heartbeat>=15:
                        heartbeat=elapsed;progress(task,f'{stage_message} · 本阶段已等待 {int(elapsed)} 秒（上限330秒）')
                time.sleep(.1)
            check_cancelled(task)
            drain_events()
        if child.returncode or not result_path.exists():
            raise ValueError('导演执行进程异常结束，请重试并检查任务日志')
        body=json.loads(result_path.read_text(encoding='utf-8'))
        if not body.get('ok'):
            raise ValueError(body.get('error','导演执行失败'))
        result=body['result']
        if (kind or task['kind'])=='script_assets':result['_applied_asset_keys']=[list(key) for key in applied]
        if (kind or task['kind'])=='canvas_links':result['_applied_canvas_ids']=list(applied)
        return result
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill();child.wait(timeout=3)
        # Request snapshots and generated text are stored in the project only.
        request_path.unlink(missing_ok=True);result_path.unlink(missing_ok=True)
        for path in (work/'events').glob('*'):path.unlink(missing_ok=True)


def apply_script_event(task,event):
    from . import screenplay_batches
    expected=screenplay_batches.fingerprint(task['snapshot'])
    def apply(current):
        if event['state'].get('fingerprint')!=expected or screenplay_batches.fingerprint(current)!=expected:
            raise store.Conflict('剧本编写期间故事、导演设定、规则或正文已修改，草稿未覆盖；请按当前版本重新编写')
        current['script_generation']={**copy.deepcopy(event['state']),'task_id':task['id']}
    mutate_task(task,apply)


def apply_canvas_event(task,event):
    saved=mutate_task(task,lambda current:production_canvas.apply(current,event['shot_id'],event['result']))
    task['project_revision']=saved['revision'];task['progress']={k:event.get(k,0) for k in ('completed','total','reused')}
    store.task_save(task)


def apply_storyboard_event(task,event):
    def apply(current):
        if storyboard_generation.fingerprint(current)!=event['source_hash']:raise store.Conflict('分镜生成期间剧本、方案或元素外观已修改；已完成镜头保留，请按新方案重新生成')
        state=current.get('storyboard_generation',{})
        if event['type']=='storyboard_outline_checkpoint':
            if current['shots']!=task['snapshot'].get('shots',[]):raise store.Conflict('汇总期间镜头已编辑，未覆盖当前分镜')
            draft=copy.deepcopy(event['draft'])
            state.update(version=storyboard_generation.VERSION,source_hash=event['source_hash'],outline_draft=draft,
                outline_task_id=task['id'],task_id=task['id'],status='running',outline_confirmed=False,
                message=f'汇总草稿已保存：全片 {len(draft["outlines"])} 镜；旁白画面 {draft["completed"]}/{draft["total"]} 套，可中断后继续')
            current['storyboard_generation']=state
            current['native_storyboard_current']=False;current['confirmed']=False
            return
        if event['type']=='storyboard_plan':
            if current['shots']!=task['snapshot'].get('shots',[]):raise store.Conflict('镜头提纲生成期间镜头已编辑，未覆盖当前分镜')
            if current['shots']:
                current.setdefault('storyboard_archive',[]).append({'created':time.time(),'shots':copy.deepcopy(current['shots']),'state':copy.deepcopy(state),'documents':{k:copy.deepcopy(current['documents'][k]) for k in ('storyboard_native','art','review','h3') if k in current['documents']}})
            state=copy.deepcopy(event['state']);state['outline_task_id']=task['id'];current['storyboard_generation']=state;current['shots']=[]
            current.pop('timing_revision',None)
            current['documents']['art']=state['preparation']['art']
        elif event['type']=='storyboard_shot':
            if state.get('source_hash')!=event['source_hash']:raise store.Conflict('分镜缓存已改变，停止旧镜头回填')
            if event.get('prefix_hash') is not None:
                prior=[storyboard_generation.current_row(s,i+1) for i,s in enumerate(current['shots'][:event['index']-1])]
                if storyboard_generation.prefix_hash(prior)!=event['prefix_hash']:raise store.Conflict('生成本镜期间前面的镜头已编辑，停止旧连续性结果回填；已保存镜头保留，点击继续按新内容衔接')
            outline=next((o for o in state['outlines'] if o['id']==event['outline_id'] and o['index']==event['index']),None)
            if not outline:raise ValueError('未知分镜提纲编号')
            old=next((s for s in current['shots'] if s.get('generation_outline_id')==outline['id']),None)
            if not old or event.get('replace'):
                if event.get('replace') and (not old or timing.shot_signature(old)!=event.get('expected_shot_hash')):
                    raise store.Conflict('重新生成期间本镜已编辑，保留当前镜头；请按新内容重新生成')
                row=event['row']
                replacement={'id':outline['id'],'generation_outline_id':outline['id'],'generation_source_hash':event['source_hash'],'generation_index':event['index'],
                    'duration':storyboard_generation.seconds(row['时长']),'description':row['画面焦点'],'prompt':row.get('AIGC适配提示词') or row['AIGC提示词'],
                    'native':row,'actions':copy.deepcopy(row.get('动作预案',[])),'natural_status':'unverified','asset_ids':[],'outputs':[],
                    'generation_preflight':copy.deepcopy(row.get('生成预检',{}))}
                from . import shot_continuity
                if row.get('连续性接口'):replacement['continuity_source_hash']=shot_continuity.digest(replacement)
                if old:
                    current.setdefault('shot_history',[]).append({'created':time.time(),'index':event['index'],'shot':copy.deepcopy(old)})
                    # Keep bound references and video outputs, including their seeds.
                    replacement['id']=old['id'];replacement.pop('asset_ids');replacement.pop('outputs')
                    old.update(replacement);old.pop('timing_suggestion',None)
                else:
                    production_canvas.inherit(current,replacement)
                    current['shots'].append(replacement)
                current['shots'].sort(key=lambda s:s.get('generation_index',0))
                from . import shot_continuity
                if current.get('storyboard_method')=='source_units':
                    if old:
                        for output in old.get('outputs',[]):output.update(stale=True,stale_reason='本镜提示词已重做；文件、采用和种子保留，请复核')
                        old['first_frame_needs_review']=bool(old.get('first_frame'))
                    shot_continuity.refresh(current)
                if current.get('timing_revision'):current['timing_revision'].update(status='stale',message='具体分镜已更新，请完成后重新执行时间修正')
                for shot in current['shots']:
                    shot.pop('start_s',None);shot.pop('end_s',None)
        state.update(status='running',task_id=task['id'],completed=len(current['shots']),message=f'已保存 {len(current["shots"])}/{state["total"]} 镜；中断后可继续')
        current['documents']['storyboard_native']=storyboard_generation.assemble(state['preparation'],[storyboard_generation.current_row(s,i+1) for i,s in enumerate(current['shots'])])
        current['documents'].pop('h3',None);current['documents'].pop('review',None)
        current['native_storyboard_current']=False;current['confirmed']=False
    saved=mutate_task(task,apply)
    with TASK_LOCK:
        check_cancelled(task);task['project_revision']=saved['revision']
        if event['type']=='storyboard_outline_checkpoint':
            draft=saved['storyboard_generation']['outline_draft']
            task['progress']={'phase':'outline_visuals','completed':draft['completed'],'total':draft['total'],'reused':0}
        else:task['progress']={k:saved['storyboard_generation'].get(k,0) for k in ('completed','total','reused')}
        store.task_save(task)


def discard_current_outline(current):
    """A requested rebuild starts empty; previous production is history only."""
    state=current.get('storyboard_generation',{})
    documents=current.setdefault('documents',{})
    if current.get('shots') or state.get('outlines') or state.get('outline_draft') or documents.get('storyboard_native'):
        current.setdefault('storyboard_archive',[]).append({'created':time.time(),'reason':'重新创建分镜汇总',
            'shots':copy.deepcopy(current.get('shots',[])),'state':copy.deepcopy(state),
            'documents':{k:copy.deepcopy(documents[k]) for k in ('storyboard_native','art','review','h3') if k in documents}})
    current['shots']=[]
    current['storyboard_generation']={'version':storyboard_generation.VERSION,'source_hash':storyboard_generation.fingerprint(current),
        'outlines':[],'total':0,'completed':0,'outline_confirmed':False}
    for key in ('storyboard_native','art','review','h3'):documents.pop(key,None)
    current.pop('timing_revision',None)
    current['native_storyboard_current']=False;current['confirmed']=False


def enqueue_storyboard(project,force=False,plan_only=False,require_outline=False,target_outline=None,regenerate=False,recovery_strategy=None):
    with TASK_LOCK:
        if require_outline:storyboard_generation.require_confirmed_outline(project,force)
        outline=None
        if target_outline:
            if force or plan_only:raise ValueError('单镜生成不能同时重建分镜汇总')
            outline=storyboard_generation.single_target(project,target_outline)
        source=storyboard_generation.fingerprint(project)
        active=next((t for t in store.task_list() if t['project_id']==project['id'] and t['kind'] in ('storyboard','storyboard_outline','storyboard_timing') and t['status'] in ('queued','running','cancelling')),None)
        if active:
            if target_outline and (active.get('target')!=target_outline or bool(active.get('options',{}).get('regenerate'))!=regenerate):raise ValueError('当前项目正在执行分镜任务，请完成或取消后再生成此镜')
            return {k:v for k,v in active.items() if k not in ('snapshot','options')}
        if force and plan_only:
            def discard(current):
                if current['revision']!=project['revision']:raise store.Conflict('项目已修改，请刷新后重新创建分镜汇总')
                discard_current_outline(current)
            project=store.mutate(project['id'],discard)
        task=enqueue('storyboard_outline' if plan_only else 'storyboard',project,target=target_outline,options={'force':force,'require_outline':require_outline,'regenerate':regenerate,'recovery_strategy':recovery_strategy})
        def mark(current):
            # Ordinary continuation keeps its cache. A forced overview rebuild
            # already archived and discarded the old current plan above.
            state=copy.deepcopy(current.get('storyboard_generation') or {'version':storyboard_generation.VERSION,'source_hash':source,'total':0,'completed':0})
            state.update(status='queued',task_id=task['id'],reused=0 if force else len([s for s in current['shots'] if s.get('generation_source_hash')==source]),message='重新创建分镜汇总已排队；旧汇总已移入历史，按当前剧本重新规划' if force and plan_only else '分镜汇总已排队；先匹配剧本，确认后再逐镜生成' if plan_only else '分镜已排队；完成一镜即保存一镜')
            if outline:state['message']=f'第{outline["index"]}镜已排队；本次只{"重新" if regenerate else ""}生成此镜'
            current['storyboard_generation']=state
            current['native_storyboard_current']=False;current['confirmed']=False
        saved=store.mutate(project['id'],mark)
        task['project_revision']=saved['revision'];store.task_save(task)
        return {k:v for k,v in task.items() if k not in ('snapshot','options')}


def enqueue_timing(project):
    with TASK_LOCK:
        if not project.get('native_storyboard_current') or not project.get('shots'):raise ValueError('请先按分镜汇总完成全部具体分镜，再修正时间')
        active=next((t for t in store.task_list() if t['project_id']==project['id'] and t['kind'] in ('storyboard','storyboard_outline','storyboard_timing') and t['status'] in ('queued','running','cancelling')),None)
        if active:return {k:v for k,v in active.items() if k not in ('snapshot','options')}
        task=enqueue('storyboard_timing',project,options={'revise_time':True})
        def mark(current):
            previous=current.get('timing_revision',{})
            current['timing_revision']={'task_id':task['id'],'status':'queued','completed':0,'total':len(current['shots']),'reused':0,
                'initial_target_duration':current['duration'] if previous.get('status')=='stale' else previous.get('initial_target_duration',current['duration']),
                'changes':[] if previous.get('status')=='stale' else copy.deepcopy(previous.get('changes',[])),
                'message':'时间修正已排队；先审查动作自然时长，再累计正式时间标签'}
            current['confirmed']=False
        saved=store.mutate(project['id'],mark);task['project_revision']=saved['revision'];store.task_save(task)
        return {k:v for k,v in task.items() if k not in ('snapshot','options')}


def apply_asset_event(task,event):
    def apply(current):
        if script_source.fingerprint(current)!=event['source_hash']:raise store.Conflict('元素提取期间剧本已修改，停止旧结果回填；请手动提取当前剧本')
        analysis=current.setdefault('asset_analysis',{})
        analysis.update(source_type='script',source_hash=event['source_hash'],status='running',task_id=task['id'])
        if event['type']=='inventory':
            analysis.update(inventory=event['inventory'],total=event['total'],completed=0,reused=0,failed=0,failures=[],strategy=event.get('strategy','single_pass'),scene_rules=event.get('scene_rules'),omitted_scenes=event.get('omitted_scenes',[]))
            analysis['omitted_scenes']=scene_identity.apply_omissions(current,analysis['omitted_scenes'])
        else:
            if event['type']=='asset':
                apply_analyzed_assets(current,[event['item']],task['snapshot'].get('assets',[]))
                current['confirmed']=False
            if event['type']=='failure':analysis.setdefault('failures',[]).append(event['failure'])
            analysis.update({k:event[k] for k in ('completed','total','reused','failed')})
        analysis['message']=f"已完成 {analysis.get('completed',0)}/{analysis.get('total',0)} 个元素（复用 {analysis.get('reused',0)}，失败 {analysis.get('failed',0)}）；完成项已保存"
    saved=mutate_task(task,apply)
    with TASK_LOCK:
        check_cancelled(task)
        task['project_revision']=saved['revision']
        task['progress']={k:saved['asset_analysis'].get(k,0) for k in ('completed','total','reused','failed')}
        store.task_save(task)


def apply_asset_prompt(task,result):
    original=next(a for a in task['snapshot']['assets'] if a['id']==task['target'])
    def apply(current):
        live=next((a for a in current['assets'] if a['id']==task['target']),None)
        if live!=original:
            raise store.Conflict('生成提示词期间资产被修改，未覆盖')
        if script_source.text(current,False)!=script_source.text(task['snapshot'],False):raise store.Conflict('生成期间剧本已修改，未覆盖元素设定')
        if current.get('production_scheme',{})!=task['snapshot'].get('production_scheme',{}):raise store.Conflict('镜头与美术方案已修改，保留原提示词；请按当前方案重新生成')
        if result.get('description') and result['description']!=live.get('description'):
            if live.get('prompt'):live.setdefault('prompt_history',[]).append({'prompt':live['prompt'],'prompt_zh':live.get('prompt_zh',''),'reason':'角色造型档案更新','created':time.time()})
            for preview in live.get('previews',[]):preview['stale']=True
            if task['kind'] in ('character_profile','asset_profile'):live['prompt']='';live['prompt_zh']=''
        live.update(result);current['confirmed']=False
        if task['kind']=='asset_prompt':live['style_needs_refresh']=False
        if result.get('visual_profile'):live['profile_result_hash']=character_profiles.design_hash(live)
    mutate_task(task,apply)


def apply_analyzed_assets(project,items,original_assets=None):
    """Merge screenplay-derived identities into live edits and retain media IDs."""
    for item in items:
        original=next((a for a in (original_assets or []) if a['kind']==item['kind'] and a['name']==item['name']),None)
        if original and not any(a['id']==original['id'] and a['name']==item['name'] and a['kind']==item['kind'] for a in project['assets']):continue
        asset=next((a for a in project['assets'] if a['kind']==item['kind'] and a['name']==item['name']),None)
        if asset is None:
            asset={'id':store.uid(),'name':item['name'],'kind':item['kind'],'description':'','model':'qwen-image-2.1','model_source':'default','prompt':'','references':[],'previews':[],'adopted':None}
            project['assets'].append(asset)
        if asset['kind']=='character' and 'is_protagonist' not in asset:asset['is_protagonist']=item.get('is_protagonist') is True
        profile=asset_profiles.normalize(asset_profiles.preserve_user_fields(item.get('visual_profile'),asset),project,asset,project['assets']+items)
        update=asset_profiles.update_fields(asset,profile,item.get('narrative_context',asset.get('narrative_context','')),character_profiles.source_hash(project,asset))
        if update['description']!=asset.get('description',''):
            if asset.get('prompt'):asset.setdefault('prompt_history',[]).append({'prompt':asset['prompt'],'prompt_zh':asset.get('prompt_zh',''),'reason':'剧本提取更新元素外观','created':time.time()})
            asset['prompt']='';asset['prompt_zh']=''
            for preview in asset.get('previews',[]):preview['stale']=True
        asset.update(update)
        for key in ('profile_context_hash','extraction_seconds','source_cache'):
            if key in item:asset[key]=item[key]
        if asset.get('visual_description_source')!='user':asset['visual_description_source']='script'
        asset.pop('needs_scene_extraction',None)
        asset['profile_result_hash']=character_profiles.design_hash(asset)


def needs_media_preparation(task):
    if task.get('prompt_id') or task.get('media_prepared'):return False
    if task['kind']=='frame':return True
    if task['kind'] in ('keyframe','tail'):return bool(task.get('snapshot'))
    if task['kind']!='preview' or not task.get('options',{}).get('ensure_prompt'):return False
    asset=next((a for a in task.get('snapshot',{}).get('assets',[]) if a['id']==task.get('target')),None)
    return asset is None or preview_needs_prompt(asset)


def preview_needs_prompt(asset):
    if asset_card_render.uses_card(asset):return False
    return bool(asset.get('style_needs_refresh')) or not str(asset.get('prompt') or '').strip() or str(asset.get('prompt_notes') or '').strip()!=str(asset.get('prompt_notes_used') or '').strip()


def task_queue(task):
    if task.get('options',{}).get('tts_engine')=='yovoice' or task.get('options',{}).get('yovoice_timing'):return COMFY_QUEUE
    if task['kind']=='agent':return AGENT_QUEUE
    if task['kind'] in ('medical_ocr','export','stage3d_render','subtitle_recognize'):return EXPORT_QUEUE
    if task['kind'] in COMFY_KINDS and not needs_media_preparation(task):return COMFY_QUEUE
    options=task.get('options',{})
    continuation=task['kind']=='stage3d_plan' or (task['kind']=='h3' and task.get('target')) or (task['kind'] in ('frame','schedule') and options.get('single_shot'))
    return CONTINUATION_QUEUE if continuation else QUEUE


def set_queue_lane(task):
    lane=task_queue(task)
    task['queue_lane']='agent' if lane is AGENT_QUEUE else 'comfy' if lane is COMFY_QUEUE else 'export' if lane is EXPORT_QUEUE else 'continuation' if lane is CONTINUATION_QUEUE else 'production'
    task['queue_group']='comfy' if lane is COMFY_QUEUE or task['kind']=='preview' else 'local' if lane is EXPORT_QUEUE else 'ai'
    task['phase']='ai_prepare' if needs_media_preparation(task) else task['queue_group']
    return lane


def enqueue(kind,project,target=None,options=None):
    """Repeated clicks join an identical active operation; explicit reruns remain fresh."""
    import hashlib
    options=dict(options or {})
    if kind in ('h3','h3_generate'):
        from . import shot_merge
        if kind=='h3' and target:target=shot_merge.leader(project,target)
        if kind=='h3_generate' and options.get('scope_shot'):options['scope_shot']=shot_merge.leader(project,options['scope_shot'])
    inputs={k:v for k,v in options.items() if k not in ('_request_digest','seed') or k=='seed' and options.get('seed_explicit')}
    basis=project.get('revision')
    if kind in ('h3','h3_generate'):
        try:basis=h3.source_hash(project,target if kind=='h3' else options.get('scope_shot'))
        except (ValueError,KeyError):pass
    digest=hashlib.sha256(json.dumps([project['id'],kind,target,basis,inputs],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    with TASK_LOCK:
        prior=next((row for row in store.task_list() if row['project_id']==project['id'] and row['kind']==kind and row.get('options',{}).get('_request_digest')==digest and row['status'] in ('queued','running','cancelling')),None)
        if prior:return prior
        options['_request_digest']=digest
        return _enqueue_unchecked(kind,project,target,options)


def _enqueue_unchecked(kind, project, target=None, options=None):
    from . import shot_merge
    if kind=='h3' and target:target=shot_merge.leader(project,target)
    if kind=='h3_generate' and (options or {}).get('scope_shot'):
        options={**options,'scope_shot':shot_merge.leader(project,options['scope_shot'])}
    task={'id':store.uid(),'kind':kind,'project_id':project['id'],'target':target,'options':options or {},'revision':project['revision'],'snapshot':copy.deepcopy(project),'status':'queued','message':'等待执行','created':time.time()}
    if kind in ('script','storyboard_outline','storyboard'):
        from . import creative_rules
        stages=('script_plan','script') if kind=='script' else ('storyboard_outline','storyboard')
        task['snapshot']['_creative_rule_bundles']=creative_rules.freeze(project,stages)
        stage='script_plan' if kind=='script' and task['options'].get('plan_only') else 'script' if kind=='script' else 'storyboard_outline' if kind=='storyboard_outline' else 'storyboard'
        task['rule_application']=creative_rules.audit(task['snapshot'],stage)
    task.update(task_details.describe(task,store.settings()));task['queued_at']=task['created']
    lane=set_queue_lane(task)
    if kind=='preview' and not needs_media_preparation(task):
        asset=next((a for a in task['snapshot'].get('assets',[]) if a['id']==target),None)
        if asset:task['options']['preview_render_inputs']=preview_inputs(asset)
    if needs_media_preparation(task):task['message']='等待 AI 准备，完成后自动转入 ComfyUI'
    store.task_save(task)
    lane.put(task)
    return task


def enqueue_script_assets(project,force=False):
    """Separate task: an extraction failure cannot discard a completed script."""
    source=script_source.fingerprint(project)
    with TASK_LOCK:
        active=next((t for t in store.task_list() if t['project_id']==project['id'] and t['kind']=='script_assets' and t['status'] in ('queued','running') and script_source.text(t.get('snapshot',{}),False)==script_source.text(project)),None)
        if active:return active
        configured=bool(store.settings().get('ai_url') and store.settings().get('ai_model'))
        task=enqueue('script_assets',project,options={'force':force}) if configured else None
        def apply(current):
            prior=current.get('asset_analysis',{})
            current['asset_analysis']={**(prior if prior.get('source_hash')==source else {}),'source_type':'script','source_hash':source,'status':'queued' if task else 'pending','task_id':task['id'] if task else None,'message':'手动提取已排队，完成一个元素即保存一个' if task else '配置文本AI后，手动点击提取元素'}
        store.mutate(project['id'],apply)
        return task


def finish(task,media,output=None):
    def apply(p):
        m={'id':store.uid(),'media':media,'kind':task['options'].get('media_kind','image' if task['kind'] in ('preview','frame','character_card') else 'video'),'task_id':task['id'],'created':time.time()}
        if m['kind']=='audio':
            m['generation_seconds']=max(0,time.time()-task.get('started',time.time()))
            m['prompt']=task['options'].get('prompt','')
            try:
                import soundfile
                m['duration']=soundfile.info(str(store.media_path(media))).duration
            except Exception:pass
            if task['options'].get('tts_engine')=='owl-speech-timing':
                from . import speech_audio
                opts=task['options'];m.update(model='qwen3-tts',seed=opts['seed'],scope_shot=opts['speech_timing_shot'],name='分镜人声实测')
                m['stale']=not speech_audio.save_result(p,opts,(output or {}).get('node_id'),media,m.get('duration'))
                line=next((s for s in opts['speech_lines'] if s['output_node']==str((output or {}).get('node_id'))),None)
                if line:m.update(name=speech_audio.role(line)+' · '+line['text'][:35],voice_role=speech_audio.role(line),speech_id=line['id'],speech_text=line['text'],seed=line.get('seed',opts['seed']))
            if task['options'].get('tts_engine')=='owl-qwen3':
                from . import tts_workflow
                opts=task['options'];tts_workflow.register_voice(opts)
                m.update(model='qwen3-tts',seed=opts['seed'],voice_mode=opts['voice_mode'],voice_role=opts['voice_role'],voice_speaker=opts.get('voice_speaker'),voice_filename=opts.get('voice_filename'),voice_description=opts.get('voice_description'),voice_delivery=opts.get('voice_delivery'),workflow_snapshot=opts.get('workflow_snapshot'),name=opts['voice_role']+' · '+('新建音色试配' if opts['voice_mode']=='design' else '配音'))
        if task['options'].get('tts_engine')=='yovoice' or task['options'].get('yovoice_timing'):
            opts=task['options'];m['tts_engine']='yovoice'
            if not opts.get('yovoice_timing'):
                m.update(model=opts['yovoice_model'],seed=opts.get('seed'),voice_role=opts['voice_role'],voice_mode=opts['voice_mode'],voice_description=opts.get('voice_description',''),voice_delivery=opts.get('voice_delivery',''),voice_filename=opts.get('saved_yovoice_voice') or opts.get('voice_filename'),name=opts['voice_role']+' · 配音')
            else:
                line=next((s for s in opts['speech_lines'] if s['output_node']==str((output or {}).get('node_id'))),None)
                if line:m['model']=line['voice'].get('yovoice_model')
        p['media'].append(m)
        if task['kind']=='music_generate':
            from . import soundtrack
            import soundfile
            actual_duration=soundfile.info(str(store.media_path(media))).duration
            m.update(kind='audio',model='minimax-music-3',seed=task['options']['seed'],prompt=task['options']['prompt'],duration=actual_duration,requested_duration=task['options']['duration'],source_hash=task['options']['source_hash'])
            p.setdefault('soundtrack',{}).setdefault(task.get('target') or 'all',{}).setdefault('outputs',[]).append(copy.deepcopy(m))
        if task['kind'] in ('keyframe','tail'):
            from . import keyframes
            shot=next((s for s in p['shots'] if s['id']==task['target']),None)
            plan=task['options']['keyframe_plan']
            m.update(kind='image',model='qwen-image-2.1',seed=task['options']['seed'],prompt=plan['prompt'],relationship=plan['relationship'],asset_ids=plan['asset_ids'],reference_bindings=plan['references'],source_hash=plan['source_hash'],stale=not shot or keyframes.fingerprint(p,shot)!=plan['source_hash'])
            if shot:shot.setdefault('tailframes' if task['kind']=='tail' else 'keyframes',[]).append(m)
        if task['kind']=='asset_upscale':
            asset=next((a for a in p['assets'] if a['id']==task['target']),None)
            m.update(source_media=task['options']['source_media'],upscaled=True,upscale_model=task['options'].get('upscale_model'),stale=not asset or asset.get('adopted')!=task['options']['source_media'])
            if asset:asset.setdefault('previews',[]).append(m)
        if task['kind'] in ('h3_generate','h3_upscale'):
            step=task['options']['h3_step'];scope_shot=task['options'].get('scope_shot');package=h3.package(p,scope_shot) or {}
            stale=package.get('source_hash')!=(h3.package(task['snapshot'],scope_shot) or {}).get('source_hash') or not h3.is_current(p,package,scope_shot)
            if task['kind']=='h3_upscale':
                owner=next((s for s in p['shots'] if s['id']==scope_shot),None)
                stale=not owner or task['options']['source_output_id'] not in owner.get('adopted_video_ids',[])
            m.update({'h3_step':step['index'],'duration':(output or {}).get('observed_duration',step['duration']),'planned_duration':step['duration'],'source_shot_ids':step['source_shot_ids'],'workflow':h3_workflow.SOURCE.stem,'quality':'second' if (output or {}).get('node_id')=='406' else 'first','seed':task['options']['seed'],'resolution':task['options'].get('resolution','540P'),'workflow_snapshot':task['options'].get('workflow_snapshot'),'stale':stale})
            m.update({k:v for k,v in (output or {}).items() if k in ('source_media','raw_duration','observed_duration','planned_duration','delivery_duration','timing_adjustment')})
            if scope_shot:m['scope_shot']=scope_shot
            if task['kind']=='h3_upscale':m.update({k:task['options'][k] for k in ('source_output_id','source_video','source_workflow_snapshot','upscale_factor','temporal_chunks','spatial_chunks','output_width','output_height')})
            if not stale and task['kind']=='h3_generate':
                live_step=next(s for s in package['steps'] if s['index']==step['index'])
                live_step.setdefault('outputs',[]).append(m)
            clips=task['options'].get('h3_clips')
            if clips is None:clips=next(s for s in h3.groups(h3.scope(task['snapshot'],scope_shot)) if s['index']==step['index'])['clips']
            for clip in clips:
                shot=next((s for s in p['shots'] if s['id']==clip['source_id']),None)
                if shot:shot.setdefault('outputs',[]).append({**m,'in':clip['start'],'source_offset':clip['source_offset'],'duration':clip['end']-clip['start']})
        if task['kind'] in ('preview','character_card'):
            asset=next((a for a in p['assets'] if a['id']==task['target']),None)
            if asset:
                original=next(a for a in task['snapshot']['assets'] if a['id']==task['target'])
                m.update({'prompt':task['options'].get('rendered_asset_prompt',original['prompt']),'model':task['options'].get('effective_image_model',original['model']),'seed':task['options']['seed'],'source_revision':task['revision'],'stale':preview_inputs(asset)!=preview_inputs(original)})
                if task['kind']=='character_card' or task['options'].get('character_reference_card'):
                    card_stale=preview_inputs(asset)!=preview_inputs(original) if task['kind']=='preview' else asset['references']!=original['references'] or asset.get('adopted')!=original.get('adopted')
                    m.update({'prompt':task['options']['card']['prompt'],'model':task['options'].get('effective_image_model',task['options']['card'].get('model','qwen-image-2.1')),'character_card':True,'layout_normalized':bool((output or {}).get('layout_normalized')),'layout':(output or {}).get('layout'),'stale':card_stale})
                    source=(output or {}).get('source_media')
                    if source and source!=media:
                        m['source_media']=source
                        # Keep the unmodified download in the project archive,
                        # but publish one gallery candidate per generated image.
                        p['media'].append({**m,'id':store.uid(),'media':source,'layout_normalized':False,'layout':None,'source_media':None,'archive_only':True,'derived_media':media})
                    if (output or {}).get('layout_error'): m['layout_error']=output['layout_error']
                asset['previews'].append(m)
        if task['kind']=='generate':
            shot=next((s for s in p['shots'] if s['id']==task['target']),None)
            if shot:
                shot.setdefault('outputs',[]).append(m)
        if task['kind']=='frame':
            shot=next((s for s in p['shots'] if s['id']==task['target']),None)
            m.update(seed=task['options']['seed'],model='qwen-image-2.1',prompt=task['options'].get('frame_prompt'),
                     reference_bindings=copy.deepcopy(task['options'].get('reference_bindings',[])),
                     asset_ids=copy.deepcopy(task['options'].get('frame_asset_ids',[])),
                     source_hash=task['options'].get('frame_source_hash'),
                     composition_reference=task['options'].get('composition_reference'),
                     stale=not shot or shot_asset_binding.render_inputs(p,shot)!=task['options'].get('frame_render_inputs'))
            if shot:
                # Every generated candidate is retained; adoption is explicit.
                shot.setdefault('frames',[]).append(m)
    mutate_task(task,apply)


def preview_inputs(asset):
    if asset_card_render.uses_card(asset):return {k:asset.get(k) for k in ('id','kind','name','card','model','prompt_notes','references','wh_ratio','ratio_follow','image_composition','image_text')}
    return {k:asset.get(k) for k in ('id','kind','name','description','model','prompt','prompt_notes','references','wh_ratio','ratio_follow','image_composition','image_text')}


def prepare_media(task):
    """Resolve text dependencies before this task occupies the GPU queue."""
    check_cancelled(task)
    if not needs_media_preparation(task):return
    p=task['snapshot']
    if task['kind'] in ('frame','keyframe','tail') and task['options'].get('image_plan'):
        from . import keyframes
        plan=task['options']['image_plan'];shot=next(s for s in p['shots'] if s['id']==task['target'])
        if plan['source_hash']!=keyframes.fingerprint(p,shot):raise store.Conflict('画面规划依据已变化，请重新预填')
        task['options']['keyframe_plan']=plan
        task['options'].update(frame_prompt=plan['prompt'],reference_bindings=plan['references'],frame_asset_ids=plan['asset_ids'],frame_source_hash=plan['source_hash'],frame_render_inputs=shot_asset_binding.render_inputs(p,shot))
        task['media_prepared']=True
        return
    if task['kind']=='keyframe':
        from . import keyframes
        result=run_text(task,'keyframe_prepare')
        live=store.get_project(p['id']);shot=next((s for s in live['shots'] if s['id']==task['target']),None)
        if not shot or keyframes.fingerprint(live,shot)!=result['source_hash']:raise store.Conflict('关键帧准备期间本镜或参考元素已修改，未提交图片任务')
        task['options']['keyframe_plan']=result
    if task['kind']=='preview':
        asset=next(a for a in p['assets'] if a['id']==task['target'])
        live=store.get_project(p['id'])
        current_asset=next((a for a in live['assets'] if a['id']==task['target']),None)
        allowed_changes={'prompt','prompt_zh','prompt_rules','prompt_rule_source','prompt_notes_used','native','previews','adopted','wh_ratio','ratio_follow','prompt_mode','source_cache','profile_context_hash','extraction_seconds'}
        if current_asset and current_asset.get('profile_result_hash')==character_profiles.design_hash(current_asset):
            allowed_changes.update({'description','age','gender','costume','personality','visual_profile','narrative_context','profile_source_hash','profile_source_type','profile_stale','profile_result_hash','prompt_history'})
        if current_asset is None or {k:v for k,v in current_asset.items() if k not in allowed_changes}!={k:v for k,v in asset.items() if k not in allowed_changes}:
            raise store.Conflict('排队期间元素设定被修改，请重新生成预览')
        p['assets']=[copy.deepcopy(current_asset) if a['id']==task['target'] else a for a in p['assets']]
        task['snapshot']=copy.deepcopy(p)
        asset=next(a for a in p['assets'] if a['id']==task['target'])
        if preview_needs_prompt(asset):
            progress(task,'AI 正在准备元素提示词，完成后提交 ComfyUI')
            result=run_text(task,'asset_prompt')
            apply_asset_prompt(task,result)
            asset.update(result)
        task['snapshot']=copy.deepcopy(p)
        task['options']['preview_render_inputs']=preview_inputs(asset)
    elif task['kind']=='frame':
        shot=next(s for s in p['shots'] if s['id']==task['target'])
        source=shot_asset_binding.fingerprint(p,shot)
        live=store.get_project(p['id'])
        live_shot=next((s for s in live['shots'] if s['id']==task['target']),None)
        if not live_shot or shot_asset_binding.fingerprint(live,live_shot)!=source:
            raise store.Conflict('排队期间本镜或资产设定已修改，请重新生成首帧')
        prompt=live_shot.get('native',{}).get('首帧提示词') or live_shot.get('native',{}).get('首帧描述')
        if not prompt:raise ValueError('缺少 DirectorMaster 首帧提示词，请重新生成分镜')
        stage={**task,'snapshot':live}
        association=shot_asset_binding.cached(live,live_shot)
        if association:progress(task,'复用本镜 AI 资产关联，使用各元素当前参考图')
        else:association=run_text(stage,'frame_assets')
        saved=mutate_task(task,lambda current:shot_asset_binding.apply(current,task['target'],association))
        task['project_revision']=saved['revision'];p=saved;task['snapshot']=copy.deepcopy(p)
        shot=next(s for s in p['shots'] if s['id']==task['target'])
        refs=shot_asset_binding.references(p,shot)
        if task['options'].get('composition_reference'):
            refs=[stage3d.reference(p,shot['id'],task['options']['composition_reference']),*refs]
            prompt+='\n将第一张3D预演图仅作为构图和站位参考。把几何人偶替换为后续资产参考中的真实角色，保持身份、服饰和场景质感；不生成网格、辅助线或人偶外观。'
        if len(refs)>16:raise ValueError('本镜资产参考图超过 Qwen 的16张上限，请减少绑定元素的参考图')
        prompt+='\n本镜元素约束（各自特征不得串给其他元素；保持上述首帧构图与动作起点）：\n'+shot_asset_binding.visual_constraints(p,shot)
        from . import skill_workflows
        adopted_rules=skill_workflows.prompt_rules(p,'image')
        if adopted_rules:prompt+='\n专项画面规则（不改变上述人物身份、构图与动作起点）：\n'+adopted_rules['rules']
        prompt+='\n'+'\n'.join(f"参考图片{i+1}用于{r.get('role','identity')}：{r.get('note','')}" for i,r in enumerate(refs))
        task['options'].update(frame_prompt=prompt,frame_source_hash=association['source_hash'],
            frame_asset_ids=list(shot.get('asset_ids',[])),reference_bindings=refs,
            frame_render_inputs=shot_asset_binding.render_inputs(p,shot))
        progress(task,f'已关联 {len(shot.get("asset_ids",[]))} 个元素，使用 {len(refs)} 张参考图生成首帧')
    check_cancelled(task)
    task['media_prepared']=True


def prepare_h3_references(task, sid=None):
    """Bind shot assets before H3 writing, even when first-frame creation is skipped."""
    if sid is None:
        if not task.get('target'):return
        from . import shot_merge
        for member in shot_merge.members(task['snapshot'],task['target']):prepare_h3_references(task,member)
        return
    snapshot=task['snapshot'];shot=next(s for s in snapshot['shots'] if s['id']==sid)
    if shot.get('h3_reference_mode','auto') in ('text','first_frame','previous_tail'):return
    from . import frame_reference_sets
    if frame_reference_sets.asset_ids(snapshot,shot):return
    live=store.get_project(task['project_id'])
    before=h3.source_manifest(h3.scope(snapshot,sid,allow_reference_prepare=True))
    after=h3.source_manifest(h3.scope(live,sid,allow_reference_prepare=True))
    if before!=after:raise store.Conflict('H3 资产关联前本镜生成依据已修改，请按当前内容重试')
    live_shot=next(s for s in live['shots'] if s['id']==sid)
    if not live.get('assets'):raise ValueError('尚无资产元素，请先提取并生成参考图，或明确选择纯文字模式')
    progress(task,'正在根据本镜画面关联角色、场景与道具，随后转写带参考图的 H3')
    association=shot_asset_binding.cached(live,live_shot)
    if not association:association=run_text({**task,'snapshot':live,'target':sid},'frame_assets')
    saved=mutate_task(task,lambda current:shot_asset_binding.apply(current,sid,association))
    task['project_revision']=saved['revision'];task['snapshot']=copy.deepcopy(saved)
    refs=asset_references.for_shot(saved,next(s for s in saved['shots'] if s['id']==sid))
    progress(task,f'H3 本镜已关联 {len(association["asset_ids"])} 个资产，找到 {len(refs)} 张参考图')


def execute(task,on_submitted=None):
    if task['kind']=='medical_ocr':
        from . import local_ocr
        return local_ocr.execute(task)
    if task['kind']=='medical_director':
        from . import medical_director
        return medical_director.execute(task)
    if task['kind']=='subtitle_recognize':
        from . import local_subtitles
        return local_subtitles.execute(task)
    if task['kind']=='performance_plan':
        from . import performance
        return performance.execute(task)
    if task.get('options',{}).get('tts_engine')=='yovoice' or task.get('options',{}).get('yovoice_timing'):
        from . import yovoice_cli
        return yovoice_cli.execute(task)
    if task['kind']=='authoring_shot':
        from . import authoring
        return authoring.execute_shot(task)
    if task['kind']=='creative_refine':
        from . import creative_revision
        return creative_revision.execute(task)
    if task['kind']=='authoring_run':
        from . import authoring
        return authoring.execute(task)
    from . import seedance_integration as seedance
    if task['kind'] in seedance.KINDS:
        result=run_text(task);task['seedance_result']=result
        mutate_task(task,lambda p:seedance.apply(p,result))
        task['completion_message']='Seedance 创作结果已保存，原始故事未修改'
        return
    check_cancelled(task)
    p=task['snapshot']
    kind=task['kind']
    if kind=='frame_layout':
        from . import frame_layout
        result=run_text(task)
        task['layout_result']=result
        saved=mutate_task(task,lambda current:frame_layout.apply(current,task['target'],result))
        task['project_revision']=saved['revision'];task['completion_message']='白模SVG与PNG已保存并绑定本阶段构图参考'
        return
    if kind=='agent':
        from . import agent
        from . import ai_context
        with ai_context.session(task['project_id']):return agent.run(task)
    if kind=='frame_plan':
        from . import keyframes, frame_plans
        result=run_text(task)
        # Retain a completed response even if a genuine edit prevents applying it.
        task['frame_plan_result']=result
        def apply(current):
            shot=next(s for s in current['shots'] if s['id']==task['target'])
            planning_hash=result.get('planning_source_hash')
            if planning_hash:
                if frame_plans.planning_fingerprint(current,shot,task.get('options',{}))!=planning_hash:
                    raise store.Conflict('画面规划期间本帧依据或所选资产描述已修改；生成结果已保留在任务记录，未覆盖当前编辑')
                result['source_hash']=keyframes.fingerprint(current,shot)
            elif keyframes.fingerprint(current,shot)!=result['source_hash']:raise store.Conflict('画面规划期间分镜或资产已修改；生成结果已保留在任务记录，未覆盖')
            if task.get('options',{}).get('layout_only'):
                mode=result['mode'];plan=shot.setdefault('image_plans',{}).get(mode)
                before=next(s for s in p['shots'] if s['id']==task['target']).get('image_plans',{}).get(mode,{})
                if not plan or any(plan.get(k)!=before.get(k) for k in ('relationship','prompt','layout_scene')):raise store.Conflict('布局调整期间画面方案已修改，未覆盖')
                plan.update({k:result[k] for k in ('layout_scene','layout_explanation','source_hash')})
                plan.pop('composition_reference',None)
            else:
                before=next(s for s in p['shots'] if s['id']==task['target']).get('image_plans',{}).get(result['mode'],{})
                current_plan=shot.get('image_plans',{}).get(result['mode'],{})
                if any(current_plan.get(k)!=before.get(k) for k in ('prompt','relationship','references','selected_asset_ids')):raise store.Conflict('提示词生成期间本帧方案或资产选择已编辑，旧结果未覆盖')
                update=result.get('frame_card_update')
                if update:
                    phase=update['phase']
                    shot.setdefault('frame_card_history',[]).append({'phase':phase,'card':__import__('copy').deepcopy(shot.get('frame_cards',{}).get(phase)),'created':time.time()})
                    shot.setdefault('frame_cards',{})[phase]=update['card']
                    shot.setdefault('frame_card_sources',{})[phase]=update['basis']
                    result['source_hash']=keyframes.fingerprint(current,shot)
                    result['planning_source_hash']=frame_plans.planning_fingerprint(current,shot,task.get('options',{}))
                if result.get('card_only'):
                    if result['mode'] in shot.get('image_plans',{}):shot['image_plans'][result['mode']]['stale']=True
                else:shot.setdefault('image_plans',{})[result['mode']]=result
        saved=mutate_task(task,apply);task['project_revision']=saved['revision']
        if task.get('options',{}).get('layout_only') or task.get('options',{}).get('render_layout'):
            check_cancelled(task)
            if task.get('options',{}).get('layout_svg'):
                enqueue('frame_layout',saved,task['target'],{'mode':result['mode']})
            else:enqueue('stage3d_render',saved,task['target'],{'mode':result['mode'],'time':0})
    elif kind=='asset_enrich':
        from . import asset_enrichment
        result=run_text(task)
        saved=mutate_task(task,lambda current:asset_enrichment.apply_result(current,task['target'],result))
        task['project_revision']=saved['revision']
        task['completion_message']='描述与图片提示词已一并生成，已有特征保留；可直接生成预览'
    elif kind=='asset_explore':
        from . import asset_exploration
        result=run_text(task)
        saved=mutate_task(task,lambda current:asset_exploration.apply_result(current,result))
        task['project_revision']=saved['revision']
        task['completion_message']='额外元素候选已保存，请在资产页选择采用'
    elif kind=='music_prompt':
        from . import soundtrack
        result=run_text(task)
        def apply(current):
            if soundtrack.fingerprint(current,task.get('target'))!=result['source_hash']:raise store.Conflict('配乐规划期间分镜已修改，旧结果未覆盖')
            track=current.setdefault('soundtrack',{}).setdefault(task.get('target') or 'all',{})
            track.update(result);track.pop('brief',None);track.pop('segments',None)
        mutate_task(task,apply)
    elif kind=='story_promo':
        from . import story_promo
        both=task['options'].get('stage')=='both'
        if both:task['options']['stage']='novel'
        result=run_text(task)
        saved=mutate_task(task,lambda current:story_promo.apply_result(current,result))
        if both:
            check_cancelled(task)
            task['snapshot']=saved;task['revision']=saved['revision'];task['options']['stage']='video'
            progress(task,'小说推文已保存，正在继续优化视频推文；取消时保留第一步')
            result=run_text(task)
            saved=mutate_task(task,lambda current:story_promo.apply_result(current,result))
        task['project_revision']=saved['revision']
        task['completion_message']='两步通用编辑规则已保存，可查看修改后开始改写' if result['stage']=='rules' else '视频推文已保存，请确认后进入剧本' if result['stage']=='video' else '第一步文案已保存，可继续第二步视频优化'
    elif kind=='skill_plan':
        from . import skill_workflows
        result=run_text(task)
        saved=mutate_task(task,lambda current:skill_workflows.apply_result(current,result))
        task['project_revision']=saved['revision']
        task['completion_message']='技能制作方案已保存，请在技能工作台核对与采用；未自动启动媒体生成'
    elif kind=='stage3d_plan':
        result=run_text(task)
        def apply(current):
            stage3d.check(current,task['target'],result['stage_hash'],result['source_hash'])
            stage3d.shot(current,task['target'])['stage3d_suggestion']=result
        saved=mutate_task(task,apply);task['project_revision']=saved['revision']
        task['completion_message']='3D布置建议已返回，请在本镜3D预演中查看并应用'
    elif kind=='canvas_links':
        result=run_text(task)
        for row in result['rows']:
            if row['shot_id'] not in result.get('_applied_canvas_ids',[]):
                apply_canvas_event(task,{'type':'canvas_binding',**row,'completed':result['total'],'total':result['total'],'reused':result['reused']})
        task['completion_message']=f'画布已关联 {result["total"]} 镜，复用 {result["reused"]} 镜；可拖动连线调整'
    elif kind=='storyboard_timing':
        source=storyboard_generation.fingerprint(p);ids=[s['id'] for s in p['shots']];reused=0
        relevant=('id','description','prompt','duration','actions','natural_status')
        def check_source(current):
            if storyboard_generation.fingerprint(current)!=source or [s['id'] for s in current['shots']]!=ids:raise store.Conflict('时间修正期间剧本、方案或镜头清单已修改；已审查动作保留')
        for index,sid in enumerate(ids):
            check_cancelled(task);live_project=store.get_project(p['id']);check_source(live_project)
            original=copy.deepcopy(next(s for s in live_project['shots'] if s['id']==sid))
            if timing.validate(original)['ok']:
                revised=original;reused+=1
            else:
                progress(task,f'正在修正第{index+1}/{len(ids)}镜自然时长；前面已审查的动作已保存')
                stage={**task,'target':sid,'snapshot':live_project}
                revised=run_text(stage,'schedule')
            def apply(current):
                check_source(current);live=next(s for s in current['shots'] if s['id']==sid)
                if any(live.get(k)!=original.get(k) for k in relevant):raise store.Conflict('时间修正期间本镜动作或提示词已编辑；未覆盖当前内容')
                checked=timing.validate(revised)
                if not checked['ok']:raise ValueError('时间修正未通过校验：'+'；'.join(checked['errors']))
                live.update({k:copy.deepcopy(revised[k]) for k in ('duration','actions','prompt','natural_status')})
                live.pop('timing_suggestion',None)
                live['native'].update(时长=live['duration'],AIGC提示词=live['prompt'],AIGC适配提示词=live['prompt'])
                current['confirmed']=False;current['documents'].pop('h3',None);current['documents'].pop('review',None)
                changes=current['timing_revision'].setdefault('changes',[])
                if not any(c['shot_id']==sid for c in changes):
                    change=timing.change_summary(original,revised,current.get('h3_settings',{}).get('max_step_seconds',30));change['index']=index+1;changes.append(change)
                current['timing_revision'].update(status='running',completed=index+1,reused=reused,message=f'已审查{index+1}/{len(ids)}镜；全部动作完成后累计正式时间标签')
            saved=mutate_task(task,apply);task['project_revision']=saved['revision']
            task['progress']={k:saved['timing_revision'][k] for k in ('completed','total','reused')};store.task_save(task)
        def finish_timing(current):
            check_source(current);labels=timing.clock(current)
            for shot,row in zip(current['shots'],labels['rows']):shot.update(start_s=row['start'],end_s=row['end'])
            script_source.set_derived_duration(current,labels['total_seconds']);current['confirmed']=False
            from . import script_workflows
            if current['documents'].get('video_spec'):
                current['documents']['video_spec']=script_workflows.spec(current)
                current['documents']['video_spec_markdown']=script_workflows.markdown(current)
            # A timing correction is allowed to update the derived film length
            # without regenerating the approved script or saved visual shots.
            state=current.get('storyboard_generation')
            new_source=storyboard_generation.fingerprint(current)
            if state:
                state['source_hash']=new_source
                for shot in current['shots']:shot['generation_source_hash']=new_source
            director.validate_project_shots(current)
            if state and state.get('preparation'):
                current['documents']['storyboard_native']=storyboard_generation.assemble(state['preparation'],[storyboard_generation.current_row(s,i+1) for i,s in enumerate(current['shots'])])
            current['timing_revision'].update(status='completed',rows=labels['rows'],total_seconds=labels['total_seconds'],message=f'时间已修正：{len(ids)}镜，共{labels["total_seconds"]:g}秒；时间标签按自然动作累计，未按目标片长压缩')
            task['completion_message']=current['timing_revision']['message']
        saved=mutate_task(task,finish_timing);task['project_revision']=saved['revision']
    elif kind in ('storyboard','storyboard_outline'):
        result=run_text(task)
        def apply(current):
            if storyboard_generation.fingerprint(current)!=result['source_hash']:raise store.Conflict('分镜期间生成依据已改变；已完成镜头保留')
            state=current.get('storyboard_generation',{})
            if result.get('plan_only'):
                if not storyboard_generation.valid_state(current) or len(state.get('outlines',[]))!=result['total']:raise store.Conflict('分镜汇总已改变，请重新核对')
                state.update(status='planned',message=f'分镜汇总已生成：{result["total"]}条，已核对剧本覆盖与银幕顺序；请查看并确认，再生成具体分镜')
                if result.get('estimate_adjusted'):
                    state['message']+=f'；{result["estimate_adjusted"]}条初估已按原文朗读下限校正，具体动作与停顿待审定'
                task['completion_message']=state['message']
                return
            if result.get('single_shot') and not result.get('complete'):
                state.update(status='partial',completed=len(current['shots']),reused=result['reused'],message=f'第{result["generated_index"]}镜已完成；已保存 {len(current["shots"])}/{result["total"]} 镜，可继续生成下一镜或批量续做')
                current['native_storyboard_current']=False;current['confirmed']=False
                task['completion_message']=state['message']
                return
            if len(current['shots'])!=result['total']:raise store.Conflict('分镜生成期间镜头数量改变，请继续生成未完成镜头')
            # Use live shots so edits, references, previews and timing reviews
            # made after an incremental save never get overwritten.
            rows=[storyboard_generation.current_row(s,i+1) for i,s in enumerate(current['shots'])]
            board=storyboard_generation.assemble(state['preparation'],rows)
            checked=director.validate_native(board)
            if not checked['ok']:raise ValueError('当前分镜契约校验失败，请核对镜头后继续')
            current['documents'].update(result['documents']);current['documents']['storyboard_native']=board
            from aggregator.review_engine import review_artifacts
            reviewed=review_artifacts(artifact_text=json.dumps(board,ensure_ascii=False),brief=json.loads(state['preparation']['core_pack']),mode='全量审查',checkpoint_dir=str(store.DATA/'director-checkpoints'))
            current['documents']['review']={'审查报告':reviewed['report'],'审查JSON':json.dumps(reviewed,ensure_ascii=False)}
            current['native_storyboard_current']=not any(s.get('continuity_review',{}).get('status')=='needs_review' for s in current['shots']);current['confirmed']=False
            state.update(status='completed',completed=result['total'],reused=result['reused'],message=f'已完成 {result["total"]}/{result["total"]} 镜；全部镜头已保存并通过原生契约校验')
            if not current['native_storyboard_current']:state['message']+='；部分镜头接续待复核，历史媒体与采用记录保留'
            task['completion_message']=state['message']
        saved=mutate_task(task,apply);task['project_revision']=saved['revision']
        task['progress']={'phase':'outline','completed':result['total'],'total':result['total'],'reused':0} if result.get('plan_only') else {k:saved['storyboard_generation'].get(k,0) for k in ('completed','total','reused')}
    elif kind=='plan':
        docs=run_text(task)
        shots=[]
        for s in docs['storyboard_native']['分镜表']:
            duration=float(str(s['时长']).replace('s',''))
            shots.append({'id':store.uid(),'duration':duration,'description':s['画面焦点'],'prompt':s.get('AIGC适配提示词') or s['AIGC提示词'],'native':s,'actions':[],'natural_status':'unverified','asset_ids':[],'outputs':[]})
        def apply(current):
            if current['revision']!=task['revision']:
                raise store.Conflict('规划期间项目被修改；结果未覆盖当前内容，请重新生成')
            current['documents']={**current.get('documents',{}),**docs};current['shots']=shots;current['confirmed']=False
            current['native_storyboard_current']=True
            if kind=='plan':
                current['script_confirmed']=False;script_source.accept(current);script_source.mark_assets_stale(current);script_source.mark_extraction_pending(current)
        mutate_task(task,apply)
    elif kind=='script':
        docs=run_text(task)
        generation=docs.pop('_script_generation',None)
        def apply(current):
            if generation:
                from . import screenplay_batches
                if screenplay_batches.fingerprint(current)!=generation['fingerprint']:raise store.Conflict('剧本生成期间故事、导演设定、规则或正文已修改，未覆盖')
            elif current['revision']!=task['revision']:raise store.Conflict('剧本生成期间项目已修改，未覆盖')
            from . import creative_rules
            if creative_rules.signature(current,('script_plan','script'))!=creative_rules.signature(p,('script_plan','script')):raise store.Conflict('生成期间创作技能版本已变化，旧结果未覆盖；请核对选择后重新执行')
            if task.get('options',{}).get('plan_only'):
                current['documents']['script_task_plan']=docs['script_task_plan']
                if docs.get('creative_rule_application'):current['documents']['creative_rule_application']=docs['creative_rule_application']
                task['completion_message']='改编提纲已生成；请核对后采用并编写正文'
                return
            old_docs=current['documents']
            if old_docs.get('script_source_view'):
                docs['script_source_history']=copy.deepcopy(old_docs.get('script_source_history',[]))+[{k:copy.deepcopy(old_docs[k]) for k in ('script','script_source_view','script_adaptation_map','script_production_settings','script_expression_review') if k in old_docs}]
            current['documents']={**old_docs,**docs};current['script_confirmed']=False;current['native_storyboard_current']=False;current['confirmed']=False
            if generation:current['script_generation']={**generation,'task_id':task['id']}
            else:current.pop('script_generation',None)
            script_source.accept(current);script_source.mark_assets_stale(current);script_source.mark_extraction_pending(current)
        mutate_task(task,apply)
    elif kind=='recommend':
        result=run_text(task)
        def apply(current):
            if ai.recommendation_fingerprint(current)!=ai.recommendation_fingerprint(p):raise store.Conflict('方案推荐期间剧本、导演设定或镜头与美术参数已修改，保留当前方案；请核对后重新推荐')
            if current.get('production_scheme',{})!=result['scheme']:
                for asset in current.get('assets',[]):
                    asset['style_needs_refresh']=True
                    for preview in asset.get('previews',[]):preview['stale']=True
            current['production_scheme']=result['scheme'];current['scheme_recommendation']=result
            current['native_storyboard_current']=False;current['confirmed']=False
            current['documents'].pop('h3',None)
        mutate_task(task,apply)
    elif kind=='h3':
        prepare_h3_references(task)
        p=task['snapshot']
        result=run_text(task);conflict=[]
        def apply(current):
            if not h3.is_current(current,result,task.get('target')):
                try:
                    before=h3.source_manifest(h3.scope(p,task.get('target')))
                    after=h3.source_manifest(h3.scope(current,task.get('target')))
                    labels={'script':'剧本','art':'美术正文','assets':'绑定资产描述或实际参考图','shots':'本镜动作、提示词、时长或采用首尾帧','production_scheme':'镜头与美术方案','h3_settings':'H3设置','parameters':'创作设定','adopted_skill_rules':'视频或声音技能','duration':'时长'}
                    changed=[labels.get(k,k) for k in before if before.get(k)!=after.get(k)]
                    reason='、'.join(changed) or '生成依据校验不一致'
                except ValueError as error:reason=str(error)
                current['documents'].setdefault('h3_conflict_drafts',[]).append({'task_id':task['id'],'scope_shot':task.get('target'),'reason':reason,'created':time.time(),'result':result})
                conflict.append(reason);return
            if task.get('target'):current['documents'].setdefault('h3_shots',{})[task['target']]=result
            else:current['documents']['h3']=result
        mutate_task(task,apply)
        if conflict:raise store.Conflict('H3 转写期间生成依据变化：'+conflict[0]+'；完整转写已保存到冲突草稿，原提示词未覆盖')
    elif kind=='analyze':
        result=run_text(task)
        def apply(current):
            if current['revision']!=task['revision']:
                raise store.Conflict('分析期间项目被修改；请重新分析')
            for key,value in result['parameters'].items():
                if current['parameters'].get(key)!=value['value']:
                    current['script_confirmed']=False;current['native_storyboard_current']=False;current['script_needs_rewrite']=True
                current['parameters'][key]=value['value'];current['parameter_sources'][key]=value
            current['questions']=result.get('questions',[]);current['summary']=result.get('summary','')
            current['analysis_source_hash']=hashlib.sha256(current.get('story','').encode()).hexdigest()
            current['confirmed']=False
        mutate_task(task,apply)
    elif kind=='script_assets':
        result=run_text(task)
        def apply(current):
            if script_source.fingerprint(current)!=result['source_hash']:raise store.Conflict('元素提取期间剧本已修改，结果未覆盖；请按当前剧本重新提取')
            applied={tuple(key) for key in result.get('_applied_asset_keys',[])}
            apply_analyzed_assets(current,[a for a in result['assets'] if (a['kind'],a['name']) not in applied],p.get('assets',[]))
            current['confirmed']=False
            failures=result.get('failures',[]);total=result.get('total',len(result['assets']));reused=result.get('reused',0)
            message=f"已完成 {len(result['assets'])}/{total} 个元素（复用 {reused}）"+('；失败项可再次点击提取重试，已完成项保留' if failures else '；外观与性格已保存')
            current['asset_analysis']={'source_type':'script','source_hash':result['source_hash'],'status':'partial' if failures else 'completed','task_id':task['id'],'message':message,'inventory':result.get('inventory',[]),'failures':failures,'total':total,'completed':len(result['assets']),'reused':reused,'failed':len(failures),'strategy':result.get('strategy','single_pass'),'scene_rules':result.get('scene_rules'),'omitted_scenes':result.get('omitted_scenes',[])}
            current['asset_analysis']['omitted_scenes']=scene_identity.apply_omissions(current,current['asset_analysis']['omitted_scenes'])
            task['completion_message']=message
        mutate_task(task,apply)
    elif kind=='schedule':
        shot=next(s for s in p['shots'] if s['id']==task['target'])
        scheduled=run_text(task)
        def apply(current):
            live=next(s for s in current['shots'] if s['id']==task['target'])
            if timing.audit_signature(current,live)!=timing.audit_signature(p,shot):
                raise store.Conflict('时序审查期间镜头被修改，未覆盖')
            proposal=scheduled.get('timing_suggestion',{})
            concurrent_generation=any(t['project_id']==current['id'] and t['kind']=='storyboard' and t['status'] in ('running','queued','cancelling') for t in store.task_list())
            draft={**scheduled,**proposal['draft']} if proposal.get('status')=='pending' else copy.deepcopy(scheduled)
            draft.pop('timing_suggestion',None)
            summary=timing.change_summary(live,draft,current.get('h3_settings',{}).get('max_step_seconds',30))
            if concurrent_generation:
                pending=timing.suggest(current,live,draft)['timing_suggestion'];pending['auto_apply']=True
                if task['options'].get('use_measured_speech'):pending['tts_track']=True
                live['timing_suggestion']=pending;live['natural_status']='unverified';current['confirmed']=False
                task['completion_message']='时序审查通过，后续分镜结束后将自动更新本镜时间，无需人工采用'
            else:
                timing.apply_review(current,live,draft);live['timing_review_summary']=summary
                if task['options'].get('use_measured_speech'):
                    from . import speech_audio
                    speech_audio.track(current,live)
                task['completion_message']=f'时序已自动更新：{summary["before_seconds"]:g} → {live["duration"]:g}秒；编辑分镜内容后需重新审查'
                if live['duration']>summary['task_limit_seconds']:task['completion_message']+=f'；超过H3单任务{summary["task_limit_seconds"]:g}秒，转写时按动作边界分任务'
        saved=mutate_task(task,apply);task['project_revision']=saved['revision']
    elif kind in ('asset_prompt','character_profile','asset_profile'):
        apply_asset_prompt(task,run_text(task))
    elif kind=='character_mod':
        from . import character_mod
        character_mod.execute(task,lambda:task['id'] in CANCEL,on_submitted)
    elif kind in ('tail','music_generate','preview','asset_upscale','frame','keyframe','generate','audio','character_card','h3_generate','h3_upscale'):
        if needs_media_preparation(task):
            prepare_media(task)
            p=task['snapshot']
        if not task.get('prompt_id'):
            if kind in ('h3_generate','h3_upscale'):
                if kind=='h3_upscale':
                    live=store.get_project(p['id'])
                    bound=h3_workflow.upscaled(live,task['options']['scope_shot'],task['options']['source_output_id'])
                    task['options'].update({k:bound[k] for k in ('source_output_id','source_video','source_workflow_snapshot','upscale_factor','temporal_chunks','spatial_chunks','output_width','output_height')})
                    task['options']['seed']=bound['seed']
                else:bound=h3_workflow.filled(p,task['target'],task['options'])
                task['options']['resolution']=bound['resolution']
                task['options']['h3_step']=bound['step'];task['options']['reference_bindings']=bound['references']
                task['options']['h3_clips']=bound['clips']
                snapshot_name=store.uid()+'.json'
                store.media_path(snapshot_name).write_text(json.dumps(bound,ensure_ascii=False,indent=2),encoding='utf-8')
                task['options']['workflow_snapshot']=snapshot_name
                graph=bound['graph']
            elif kind=='music_generate':
                from . import soundtrack
                live=store.get_project(p['id'])
                if soundtrack.fingerprint(live,task.get('target'))!=task['options']['source_hash']:raise store.Conflict('等待期间分镜已修改，未提交旧配乐任务')
                graph=soundtrack.graph(task['options']['prompt'],task['options']['duration'],task['options']['seed'])
            elif kind in ('keyframe','tail'):
                from . import keyframes,qwen_prompts
                plan=task['options']['keyframe_plan'];latest=store.get_project(p['id']);shot=next((s for s in latest['shots'] if s['id']==task['target']),None)
                if not shot or keyframes.fingerprint(latest,shot)!=plan['source_hash']:raise store.Conflict('等待期间本镜或参考元素已修改，未提交关键帧任务')
                from . import frame_continuity
                frame_continuity.check(latest,shot,kind,plan)
                width,height=qwen_prompts.dimensions({'wh_ratio':plan['wh_ratio'],'ratio_follow':plan['ratio_follow'],'references':plan['references']})
                graph=comfy.image_workflow('qwen-image-2.1',plan['prompt'],task['options']['seed'],plan['references'],width,height)
            elif kind=='asset_upscale':
                latest=store.get_project(p['id'])
                asset=next((a for a in latest['assets'] if a['id']==task['target']),None)
                if not asset or asset.get('adopted')!=task['options']['source_media']:raise store.Conflict('采用图片已变化，未提交二次放大')
                graph,model=comfy.asset_upscale_workflow(task['options']['source_media'])
                task['options']['upscale_model']=model
            elif kind=='character_card':
                asset=next(a for a in p['assets'] if a['id']==task['target'])
                card=image_prompts.character_card(p,asset)
                task['options']['card']=card
                graph=comfy.image_workflow(card['model'],card['prompt'],task['options']['seed'],card['references'],width=card['width'],height=card['height'])
            elif kind=='preview':
                asset=next(a for a in p['assets'] if a['id']==task['target'])
                refs=[] if task['options'].get('text_only') else asset['references']
                task['snapshot']=copy.deepcopy(p)
                from . import qwen_prompts
                direct=asset_card_render.uses_card(asset)
                width,height=(asset_card_render.dimensions(asset) if direct else qwen_prompts.dimensions(asset)) if asset['model']=='qwen-image-2.1' else (768,768)
                render_prompt=asset_card_render.prompt(asset,task['options'].get('text_only',False)) if direct else asset['prompt']
                if asset['kind']=='prop' and not direct:
                    from . import prop_image_rules
                    render_prompt+=' '+(prop_image_rules.ZH if refs and asset['model']=='qwen-image-2.1' else prop_image_rules.EN)
                    prop_image_rules.validate(render_prompt)
                if asset['kind']=='character':
                    card=image_prompts.initial_character_card(asset,task['options'].get('text_only',False))
                    refs=card['references'];width,height=card['width'],card['height'];render_prompt=card['prompt']
                    task['options']['card']=card;task['options']['character_reference_card']=True
                else:
                    render_prompt=image_composition.constrain(asset,render_prompt)
                    render_prompt=image_text.apply(asset,render_prompt)
                task['options']['rendered_asset_prompt']=render_prompt
                if direct:task['options']['asset_prompt_source']='five_s_card'
                graph=comfy.image_workflow(asset['model'],render_prompt,task['options']['seed'],refs,width=width,height=height)
            elif kind in ('generate','frame'):
                shot=next(s for s in p['shots'] if s['id']==task['target'])
                if kind=='frame':
                    prompt=task['options']['frame_prompt']
                    refs=task['options']['reference_bindings']
                    width=height=768
                    if task['options'].get('image_plan'):
                        from . import keyframes,qwen_prompts
                        plan=task['options']['image_plan'];live=store.get_project(p['id']);current=next(s for s in live['shots'] if s['id']==task['target'])
                        if keyframes.fingerprint(live,current)!=plan['source_hash']:raise store.Conflict('等待期间画面依据已修改，请重新预填')
                        from . import frame_continuity
                        frame_continuity.check(live,current,kind,plan)
                        width,height=qwen_prompts.dimensions(plan)
                    if task['options'].get('composition_reference'):
                        m=next(m for m in shot['stage3d_captures'] if m['media']==task['options']['composition_reference'])
                        ratio=m['width']/m['height'];width=1024 if ratio>=1 else max(64,round(1024*ratio/64)*64);height=max(64,round(width/ratio/64)*64)
                    graph=comfy.image_workflow('qwen-image-2.1',prompt,task['options']['seed'],refs,width,height)
                else:
                    refs=asset_references.for_shot(p,shot)
                    if not (workflow_files.IMPORTED/'video.json').exists():
                        if not shot.get('first_frame'):
                            raise ValueError('请生成并采用首帧，或从现有图片中选择首帧')
                        refs=[{'media':shot['first_frame'],'role':'first_frame'}]
                    graph=comfy.custom_workflow('video',{'prompt':timing.render(shot),'duration':shot['duration'],'seed':task['options']['seed']},refs)
            else:
                if task['options'].get('tts_engine')=='owl-speech-timing':
                    from . import speech_audio
                    graph=speech_audio.graph(task['options'])
                elif task['options'].get('tts_engine')=='owl-qwen3':
                    from . import tts_workflow
                    graph=tts_workflow.graph(task['options'])
                    snapshot_name=store.uid()+'.json'
                    store.media_path(snapshot_name).write_text(json.dumps({'graph':graph,'options':task['options']},ensure_ascii=False,indent=2),encoding='utf-8')
                    task['options']['workflow_snapshot']=snapshot_name
                else:graph=comfy.custom_workflow(task['options']['profile'],{'prompt':task['options']['prompt'],'duration':p['duration'],'seed':task['options']['seed']},[])
            if graph.get('4',{}).get('inputs',{}).get('unet_name','').replace('\\','/').endswith('krea2_turbo_fp8.safetensors'):
                task['options']['effective_image_model']='krea2'
                task['options']['final_output_nodes']=['42']
                task['options']['image_workflow']='全能角色资产制作【krea2】'
            with TASK_LOCK:
                check_cancelled(task)
                if kind=='preview' and task['options'].get('preview_render_inputs'):
                    latest=store.get_project(p['id']);current_asset=next((a for a in latest['assets'] if a['id']==task['target']),None)
                    if not current_asset or preview_inputs(current_asset)!=task['options']['preview_render_inputs']:
                        raise store.Conflict('等待 ComfyUI 期间元素或提示词已修改，请重新生成预览；未提交 GPU 任务')
                if kind=='frame':
                    latest=store.get_project(p['id']);current_shot=next((s for s in latest['shots'] if s['id']==task['target']),None)
                    if not current_shot or shot_asset_binding.render_inputs(latest,current_shot)!=task['options']['frame_render_inputs']:
                        raise store.Conflict('提交首帧前本镜或参考图已修改，请重新生成；未提交 GPU 任务')
                if kind=='music_generate':
                    from . import soundtrack
                    if soundtrack.fingerprint(store.get_project(p['id']),task.get('target'))!=task['options']['source_hash']:raise store.Conflict('提交前分镜已修改，请重新规划配乐')
                if kind=='h3_upscale':video_versions.adopted(store.get_project(p['id']),task['options']['scope_shot'],task['options']['source_output_id'])
                if kind=='h3_generate' and p.get('workflow_schema_version',1)>=2:
                    from . import workbench
                    live=store.get_project(p['id'])
                    if not workbench.current_review(live,'animatic') or (live.get('assets') and not workbench.current_review(live,'assets')):raise ValueError('预演或资产审核依据已变化，请重新审核后生成')
                if kind=='h3_generate':
                    try:
                        stats=comfy.request('GET','/system_stats',timeout=3)
                        task['options']['runtime_hardware']=[{'name':d.get('name'),'type':d.get('type'),'vram_total':d.get('vram_total')} for d in stats.get('devices',[])]
                        task['options']['runtime_workflow_stamp']=h3_workflow.SOURCE.stat().st_mtime_ns
                    except Exception:pass
                set_queue_lane(task)
                task['prompt_id']=comfy.submit(graph,task['id'])
                progress(task,'已提交 ComfyUI，等待生成结果')
        if on_submitted:on_submitted()
        outputs=comfy.wait_result(task,lambda:task['id'] in CANCEL)
        for output in outputs:
            check_cancelled(task)
            media=comfy.download(output)
            if kind in ('h3_generate','h3_upscale'):
                media,delivery=exporter.h3_delivery(media,task['options']['h3_step']['duration'],preserve_generated=p.get('workflow_schema_version',1)>=2 and not task['options']['h3_step'].get('audio_binding'))
                output.update(delivery)
            if kind=='character_card' or task['options'].get('character_reference_card'):
                check_cancelled(task)
                try:
                    normalized,layout=card_layout.normalize(media)
                except (OSError,ValueError) as error:
                    finish(task,media,{**output,'layout_error':str(error)})
                    task['completion_message']='角色卡已生成；等格排版未完成，保留原图供选择'
                else:
                    finish(task,normalized,{**output,'layout_normalized':True,'layout':layout,'source_media':media})
            else:
                finish(task,media,output)
        if task['options'].get('tts_engine')=='owl-speech-timing':
            from . import speech_audio
            speech_audio.continue_review(task)
    elif kind=='stage3d_render':
        from . import blender_render
        result=blender_render.render(p,task['target'],task['options'],lambda message:progress(task,message),lambda:check_cancelled(task))
        saved=mutate_task(task,lambda current:blender_render.apply(current,task['target'],result))
        task['project_revision']=saved['revision'];task['download']='/media/'+result['media']
    elif kind=='export':
        formats={'animatic':lambda:exporter.animatic(p,task['id']),'mp4':lambda:exporter.movie(p,task['id']),'zip':lambda:exporter.archive(p),'edl':lambda:exporter.edl(p),'prompts':lambda:exporter.export_prompts(p),'h3':lambda:exporter.export_h3(p,task['options'].get('scope_shot')),'h3_workflow':lambda:h3_workflow.export(p,task['target'],task['options'])}
        media=formats[task['options']['format']]()
        task['download']='/media/'+media


def process_task(task,prepare_only=False,on_submitted=None):
    deferred=False
    try:
        with TASK_LOCK:
            check_cancelled(task)
            linkage=store.task_get(task['id']).get('agent_run_id')
            if linkage:task['agent_run_id']=linkage
            now=time.time();task.setdefault('started',now);task['execution_started']=now
            task['status']='running'
            progress(task,'正在进行 AI 准备' if prepare_only else '正在执行')
        if prepare_only:
            prepare_media(task)
            with TASK_LOCK:
                check_cancelled(task)
                set_queue_lane(task)
                task['status']='queued';task['queued_at']=time.time()
                progress(task,'AI 准备已完成，等待 ComfyUI 生成')
                deferred=True
                COMFY_QUEUE.put(task)
            return
        if on_submitted:execute(task,on_submitted=on_submitted)
        else:execute(task)
        with TASK_LOCK:
            check_cancelled(task)
            task['status']='completed';task['message']=task.pop('completion_message','已完成')
    except InterruptedError as e:
        task['status']='cancelled';task['message']=str(e)
    except Exception as e:
        if task['id'] in CANCEL:
            task['status']='cancelled';task['message']='已取消，停止后续执行和结果回填'
        else:
            task['status']='failed';task['message']=str(e)
    finally:
        if not deferred:
            with TASK_LOCK:
                if task['id'] in CANCEL:
                    task['status']='cancelled';task['cancel_requested']=True
                    task.pop('download',None)
                task.pop('snapshot',None)
                task['finished']=time.time();store.task_save(task)
        if not deferred and task['kind']=='authoring_run' and task['status'] in ('failed','cancelled'):
            def authoring_note(current):
                run=current.get('authoring_run',{})
                if run.get('id')==task.get('options',{}).get('run_id'):run.update(status=task['status'],message=task['message'])
            try:store.mutate(task['project_id'],authoring_note)
            except KeyError:pass
        if not deferred and task['kind'] in ('script','script_assets','storyboard','storyboard_outline','storyboard_timing') and task['status'] in ('failed','cancelled'):
            def note(current):
                key='script_generation' if task['kind']=='script' else 'asset_analysis' if task['kind']=='script_assets' else 'timing_revision' if task['kind']=='storyboard_timing' else 'storyboard_generation'
                if current.get(key,{}).get('task_id')==task['id']:
                    current[key].update(status=task['status'],message=task['message'])
            try:store.mutate(task['project_id'],note)
            except KeyError:pass


def worker(task_queue=None):
    from . import task_scheduler
    task_queue=task_queue if task_queue is not None else QUEUE
    if task_queue is COMFY_QUEUE:
        while True:
            # SQLite owns order; discard queue notifications and pick by model.
            while True:
                try:COMFY_QUEUE.get_nowait();COMFY_QUEUE.task_done()
                except queue.Empty:break
            claimed=task_scheduler.claim_comfy()
            if claimed:submit_comfy_and_monitor(claimed)
            else:
                with TASK_CONDITION:TASK_CONDITION.wait(.5)
    while True:
        task=task_queue.get()
        try:
            claimed=task_scheduler.claim(task['id'],wait=True,expected_lane=task_queue)
            if claimed:
                if task_queue is COMFY_QUEUE:
                    submit_comfy_and_monitor(claimed)
                else:task_scheduler.execute_claimed(claimed)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Task queue worker recovered from an error')
        finally:
            task_queue.task_done()


def submit_comfy_and_monitor(task):
    """Hold the single Comfy lane through generation and result persistence."""
    try:process_task(task)
    finally:
        with TASK_CONDITION:TASK_CONDITION.notify_all()


def start():
    for task in sorted(store.task_list(),key=lambda t:t.get('queued_at',t['created'])):
        if task['kind']=='authoring_run' and task['status'] in ('queued','running','cancelling'):
            task.update(status='cancelled',message='服务重启中断创作；已完成阶段保留，请点击继续未完成步骤',finished=time.time())
            task.pop('snapshot',None);store.task_save(task)
            continue
        if task['kind']=='agent' and task['status'] in ('queued','running','cancelling'):
            # Never replay a conversational mutation after restart. Its child
            # production tasks resume through the ordinary queue below.
            from . import agent_store
            task.update(status='cancelled' if task.get('cancel_requested') else 'failed',message='服务重启中断对话；已提交制作任务和结果保留，可发送“继续”查看进度',finished=time.time())
            task.pop('snapshot',None);store.task_save(task)
            agent_store.append(task['project_id'],task['id'],'assistant',task['message'])
            continue
        if task.get('cancel_requested') or task['status']=='cancelling':
            task['status']='cancelled';task['message']='已取消，未恢复执行';task['finished']=time.time();task.pop('snapshot',None);store.task_save(task)
            continue
        if task['status'] in ('queued','running'):
            if task.get('snapshot'):
                if task['kind']=='script' and (task['snapshot'].get('story_policy')=='screenplay' or task['snapshot'].get('script_task','auto') not in ('auto','adapt')) and not task.get('options',{}).get('plan_only'):
                    from . import screenplay_batches
                    current=store.get_project(task['project_id'])
                    if screenplay_batches.fingerprint(current)!=screenplay_batches.fingerprint(task['snapshot']):
                        task.update(status='failed',message='重启前剧本依据已改变；旧正文与草稿保留，请按当前设定重新编写',finished=time.time())
                        task.pop('snapshot',None);store.task_save(task);continue
                    task['snapshot']=copy.deepcopy(current);task['revision']=current['revision']
                    if current.get('script_generation',{}).get('task_id')==task['id']:task.setdefault('options',{})['force']=False
                if task['kind'] in ('storyboard','storyboard_outline','storyboard_timing'):
                    current=store.get_project(task['project_id'])
                    if storyboard_generation.fingerprint(current)!=storyboard_generation.fingerprint(task['snapshot']):
                        task.update(status='failed',message='重启前分镜依据已改变；已完成镜头保留，请按当前方案重新生成',finished=time.time())
                        task.pop('snapshot',None);store.task_save(task);continue
                    task['snapshot']=copy.deepcopy(current);task['revision']=current['revision']
                    if storyboard_generation.valid_state(current) and current['storyboard_generation'].get('outline_task_id')==task['id']:
                        task.setdefault('options',{})['force']=False
                task['status']='queued';task['execution_mode']='queue';lane=set_queue_lane(task);store.task_save(task);lane.put(task)
            else:
                task['status']='failed';task['message']='中断任务缺少快照，请重新提交';store.task_save(task)
    from . import task_scheduler
    threading.Thread(target=task_scheduler.automatic_dispatcher,daemon=True).start()
    threading.Thread(target=worker,daemon=True).start()
    threading.Thread(target=worker,args=(CONTINUATION_QUEUE,),daemon=True).start()
    threading.Thread(target=worker,args=(COMFY_QUEUE,),daemon=True).start()
    threading.Thread(target=worker,args=(EXPORT_QUEUE,),daemon=True).start()
    for _ in range(2):threading.Thread(target=worker,args=(AGENT_QUEUE,),daemon=True).start()
