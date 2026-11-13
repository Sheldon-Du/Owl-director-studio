"""Automatically run independent AI jobs within the shared call budget."""
import threading
import time
import copy
from . import store,task_details,queue_control

AI_LIMIT=5
ASSET_TARGETS={'asset_enrich','asset_prompt','asset_profile','character_profile','preview','character_card'}
SHOT_TARGETS={'performance_plan','tail','frame_layout','frame_plan','h3','frame','keyframe','frame_assets','schedule','stage3d_plan'}

def ai_task(task):
    return task.get('phase')=='ai_prepare' or task.get('queue_group')=='ai' or task.get('queue_lane') in ('production','continuation','agent')

def cost(task):
    # Asset extraction has at most two simultaneous model requests internally.
    return 2 if task.get('kind')=='script_assets' else 1

def resource(task):
    if task.get('kind')=='agent':return None
    target=task.get('target')
    if task.get('kind')=='h3' and target:
        from . import shot_merge
        if shot_merge.group_for(task.get('snapshot',{}),target):return ('project',None)
    if target and task['kind'] in ASSET_TARGETS:return ('asset',target)
    if target and task['kind'] in SHOT_TARGETS:return ('shot',target)
    return ('project',None)

def active_tasks(rows):
    return [t for t in rows if t['status'] in ('running','cancelling') and ai_task(t)]


def independent_reviewed_shot(task,other):
    """Timing, H3 and first-frame work may continue on already saved shots."""
    if task.get('kind') not in ('h3','schedule','frame','frame_plan','keyframe','tail','frame_layout') or not task.get('target') or other.get('kind')!='storyboard':return False
    if other.get('options',{}).get('force') or other.get('options',{}).get('regenerate'):return False
    snapshot=task.get('snapshot',{});batch=other.get('snapshot',{})
    shot=next((s for s in snapshot.get('shots',[]) if s.get('id')==task['target']),None)
    same=next((s for s in batch.get('shots',[]) if s.get('id')==task['target']),None)
    if not shot or not shot.get('native'):return False
    if task.get('kind')=='h3' and (not same or shot!=same):return False
    if task.get('kind')=='schedule':
        if same and shot!=same:return False
        if not same and shot.get('generation_source_hash')!=batch.get('storyboard_generation',{}).get('source_hash'):return False
    if task.get('kind') in ('frame','frame_plan','keyframe','tail','frame_layout'):
        keys=('id','description','duration','prompt','actions','native','generation_source_hash')
        if same and any(shot.get(k)!=same.get(k) for k in keys):return False
        if not same and shot.get('generation_source_hash')!=batch.get('storyboard_generation',{}).get('source_hash'):return False
    return bool(snapshot.get('storyboard_generation',{}).get('source_hash')) and snapshot.get('storyboard_generation',{}).get('source_hash')==batch.get('storyboard_generation',{}).get('source_hash')

def blocked(task,active):
    if sum(cost(t) for t in active)+cost(task)>AI_LIMIT:
        return f'AI并发额度已占满，最多{AI_LIMIT}个调用名额；等待执行任务完成后可并发启动'
    scope=resource(task)
    for other in active:
        pair={task.get('kind'),other.get('kind')}
        if task['project_id']==other['project_id'] and readonly_shot_preparation(task) and readonly_shot_preparation(other) and (scope!=resource(other) or task.get('kind')!=other.get('kind') or task.get('kind') in ('frame','keyframe')):continue
        if task['project_id']==other['project_id'] and 'asset_prompt' in pair and pair.intersection({'storyboard','storyboard_outline'}):
            prompt_task=task if task.get('kind')=='asset_prompt' else other
            if independent_asset_prompt(prompt_task):continue
        if task['project_id']==other['project_id'] and 'asset_enrich' in pair and pair.intersection({'storyboard','storyboard_outline'}) and task.get('options',{}).get('auto_parallel') and other.get('options',{}).get('auto_parallel'):
            enrich_task=task if task.get('kind')=='asset_enrich' else other
            a=next((a for a in enrich_task.get('snapshot',{}).get('assets',[]) if a.get('id')==enrich_task.get('target')), {})
            if a.get('visual_description_source') in ('script','analysis') and a.get('visual_profile_source')!='user' and '"source": "user"' not in __import__('json').dumps(a.get('visual_profile',{}),ensure_ascii=False):continue
        if task['project_id']==other['project_id'] and 'script_assets' in pair and pair.intersection({'storyboard','storyboard_outline'}):continue
        if independent_reviewed_shot(task,other) or independent_reviewed_shot(other,task):continue
        other_scope=resource(other)
        if task['project_id']==other['project_id'] and scope and other_scope and (scope[0]=='project' or other_scope[0]=='project' or scope==other_scope):
            if 'asset_enrich' in pair and pair.intersection({'storyboard','storyboard_outline'}):
                return '同项目分镜与补充描述共用造型依据，请先完成补充描述再生成分镜；不同元素的补充描述可并发'
            return '同项目有依赖或相同目标正在执行，请等待完成；不同项目或独立元素可并发'
    return ''


def readonly_shot_preparation(task):
    """These write independent candidates/plans, never the shot's source fields."""
    if task.get('kind')=='h3':
        from . import shot_merge
        if shot_merge.group_for(task.get('snapshot',{}),task.get('target')):return False
        shot=next((s for s in task.get('snapshot',{}).get('shots',[]) if s.get('id')==task.get('target')),{})
        return bool(shot.get('asset_ids')) or shot.get('h3_reference_mode') in ('text','first_frame','previous_tail')
    return bool(task.get('target')) and (task.get('kind') in ('keyframe','frame_plan','tail','frame_layout') or
        (task.get('kind')=='frame' and bool(task.get('options',{}).get('image_plan'))))

def independent_asset_prompt(task):
    """Allow prompt writing only when profile preparation leaves shot inputs intact."""
    from . import asset_profiles,character_profiles,storyboard_generation
    project=task.get('snapshot',{})
    asset=next((a for a in project.get('assets',[]) if a.get('id')==task.get('target')),None)
    if not asset or not asset.get('visual_profile') or asset.get('profile_stale'):return False
    if asset.get('profile_source_type')!='script' or asset.get('profile_source_hash')!=character_profiles.source_hash(project,asset):return False
    try:
        updated=copy.deepcopy(project)
        target=next(a for a in updated['assets'] if a['id']==asset['id'])
        target.update(asset_profiles.prepare(updated,target))
        return storyboard_generation.fingerprint(updated)==storyboard_generation.fingerprint(project)
    except (ValueError,TypeError,KeyError):return False

def eligible(task,manual=False):
    return task['status']=='queued' and bool(task.get('snapshot')) and ai_task(task) and (manual or task['kind']!='agent') and not task.get('cancel_requested')

def public_rows(rows=None):
    from . import jobs
    with jobs.TASK_LOCK:
        rows=store.task_list() if rows is None else rows
        active=active_tasks(rows);used=sum(cost(t) for t in active);paused=queue_control.is_paused();positions={t['id']:i+1 for i,t in enumerate(queue_control.comfy_order(rows))}
        result=[]
        for task in sorted(rows,key=lambda t:t['created'],reverse=True):
            normalized=copy.deepcopy(task)
            if task['status'] in ('queued','running','cancelling'):jobs.set_queue_lane(normalized)
            row=task_details.public(normalized);candidate=eligible(normalized,manual=True)
            reason='队列已暂停，点击开始后可手动并发' if paused and candidate else ''
            row.update(queue_position=positions.get(task['id']),queue_batch=queue_control.media_batch(task) if task['id'] in positions else None,queue_paused=paused,parallel_eligible=candidate,can_parallel=candidate and not reason,parallel_blocker=reason,
                       ai_parallel_limit=AI_LIMIT,ai_slots_used=used,ai_slot_cost=cost(task))
            result.append(row)
        return result

def claim(identity,wait=False,manual=False,expected_lane=None):
    from . import jobs
    with jobs.TASK_CONDITION:
        while True:
            task=store.task_get(identity)
            if expected_lane is not None and jobs.task_queue(task) is not expected_lane:return None
            if task['status']!='queued' or task.get('cancel_requested') or identity in jobs.CANCEL:
                if manual:raise ValueError('任务已开始、结束或取消，请刷新队列')
                return None
            if queue_control.is_paused():
                if not wait:raise ValueError('队列已暂停，请先点击开始')
                jobs.TASK_CONDITION.wait(.25);continue
            if manual and not eligible(task,manual=True):raise ValueError('仅排队中的AI制作任务支持手动并发')
            reason=blocked(task,active_tasks(store.task_list())) if ai_task(task) and not manual else ''
            if not reason:break
            if not wait:raise ValueError(reason)
            jobs.TASK_CONDITION.wait(.25)
        # Persist the claim before launching. Old queue entries will see this
        # status and skip it, even if the manual thread has already completed.
        now=time.time()
        task.update(status='running',execution_mode='manual_parallel' if manual else 'auto_parallel' if ai_task(task) else 'queue',execution_started=now)
        task.setdefault('started',now)
        task['message']='手动并发启动，正在执行' if manual else '正在执行'
        store.task_save(task)
        return task

def claim_comfy():
    from . import jobs
    with jobs.TASK_CONDITION:
        if queue_control.is_paused():return None
        rows=store.task_list()
        if any(t['status'] in ('running','cancelling') and jobs.task_queue(t) is jobs.COMFY_QUEUE for t in rows):return None
        ordered=queue_control.comfy_order(rows)
        if not ordered:return None
        task=claim(ordered[0]['id'],expected_lane=jobs.COMFY_QUEUE)
        if task:queue_control.update(affinity=queue_control.media_batch(task))
        return task


def execute_claimed(task):
    from . import jobs
    try:
        if jobs.needs_media_preparation(task):jobs.process_task(task,prepare_only=True)
        else:jobs.process_task(task)
    finally:
        with jobs.TASK_CONDITION:jobs.TASK_CONDITION.notify_all()

def run_parallel(identity):
    from . import jobs
    task=claim(identity,manual=True)
    try:threading.Thread(target=execute_claimed,args=(task,),daemon=True).start()
    except Exception:
        with jobs.TASK_CONDITION:
            task.update(status='queued',execution_mode='queue',message='并发启动失败，仍保留在原队列')
            store.task_save(task);jobs.TASK_CONDITION.notify_all()
        raise
    return next(t for t in public_rows() if t['id']==identity)


def dispatch_ready():
    """Claim atomically so ordinary workers and the dispatcher cannot double-run."""
    from . import jobs
    launched=[]
    with jobs.TASK_CONDITION:
        if queue_control.is_paused():return launched
        from . import ai_context
        ai_context.sweep()
        from . import timing
        for pid in {t['project_id'] for t in store.task_list() if t.get('kind')=='schedule'}:
            try:timing.apply_automatic_pending(pid)
            except KeyError:pass
        for row in sorted(store.task_list(),key=lambda t:t['created']):
            task=store.task_get(row['id'])
            if not eligible(task) or blocked(task,active_tasks(store.task_list())):continue
            claimed=claim(task['id'])
            if not claimed:continue
            try:threading.Thread(target=execute_claimed,args=(claimed,),daemon=True).start()
            except Exception:
                claimed.update(status='queued',execution_mode='queue',message='启动失败，等待自动重试')
                store.task_save(claimed);jobs.TASK_CONDITION.notify_all()
                continue
            launched.append(task['id'])
    return launched


def automatic_dispatcher():
    import logging
    from . import jobs
    while True:
        try:dispatch_ready()
        except Exception:logging.getLogger(__name__).exception('AI queue dispatch failed')
        with jobs.TASK_CONDITION:jobs.TASK_CONDITION.wait(.5)
