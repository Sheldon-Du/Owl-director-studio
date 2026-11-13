"""Persist approved creative-task scenes without repeating full output ledgers."""
import copy
from . import ai,store,screenplay_batches

def generate(project,record,system,data,finish,progress,on_event,metrics,force=False):
    from . import script_tasks
    fingerprint=screenplay_batches.fingerprint(project)
    prior=project.get('script_generation',{})
    expected=[s['id'] for s in record['plan']['scenes']]
    state=copy.deepcopy(prior) if not force and prior.get('mode')=='task' and prior.get('fingerprint')==fingerprint else {'mode':'task','fingerprint':fingerprint,'batches':[],'pending':expected,'total_units':len(expected)}
    if [b['scene']['id'] for b in state['batches']]+state['pending']!=expected:raise ValueError('重编草稿与采用提纲不匹配，请舍弃草稿重新编写')
    report=progress or (lambda _:None)
    def save(message):
        state.update(status='running',completed_units=len(state['batches']),completed_batches=len(state['batches']),total_batches=len(expected),message=message,draft_script='\n\n'.join(b['scene']['text'] for b in state['batches']))
        on_event({'type':'script_checkpoint','state':copy.deepcopy(state)});report(message)
    save('按采用提纲分场编写 · 已保存 '+str(len(state['batches']))+'/'+str(len(expected))+' 场')
    for sid in list(state['pending']):
        planned=next(s for s in record['plan']['scenes'] if s['id']==sid)
        source_ids=set(planned['source_ids'])
        planned_rows={x['source_id']:x for x in record['plan']['source_map']}
        source_ids={x for x in source_ids if planned_rows[x]['status']!='omit'}
        instruction=system+'\n这是一个单场输出任务。完整故事与approved_plan用于理解全片，不改变提纲。只输出target_scene_id这一场，source_map只输出target_source_ids；其他场次禁止重复输出。沿用completed_scenes的角色状态和道具位置，真实转场遵循提纲。changes仅写本场实际改动，duration_advice可简短填写。'
        payload={**data,'target_scene_id':sid,'target_source_ids':sorted(source_ids),'completed_scenes':[b['scene'] for b in state['batches']]}
        def validate(value):
            scenes=value.get('scenes')
            if not isinstance(scenes,list) or len(scenes)!=1 or scenes[0].get('id')!=sid or not isinstance(scenes[0].get('text'),str) or not scenes[0]['text'].strip():raise ValueError('只返回目标场次的完整非空正文')
            mapping=script_tasks.ledger(value.get('source_map'),[u for u in data['source_units'] if u['id'] in source_ids])
            for row in mapping.values():
                if row['status']!=planned_rows[row['source_id']]['status']:raise ValueError('不得改变提纲中的来源处理方式')
                excerpt=row.get('script_excerpt')
                if not isinstance(excerpt,str) or not excerpt.strip() or excerpt not in scenes[0]['text']:raise ValueError('本场来源片段必须逐字出现在本场正文')
            changes=value.get('changes',[])
            if not isinstance(changes,list) or any(not isinstance(c,dict) or c.get('type') not in ('新增','合并','删减','重排','改写') or not isinstance(c.get('description'),str) or not c['description'].strip() for c in changes):raise ValueError('本场改动说明无效')
            return {'scene':scenes[0],'source_map':list(mapping.values()),'changes':changes,'review_notes':value.get('review_notes',[]),'duration_advice':value.get('duration_advice','')}
        report(f'正在编写第 {len(state["batches"])+1}/{len(expected)} 场 · {sid}')
        with ai.asset_call_policy('task_script_scene',metrics,limit=3,max_tokens=16384,timeout=300,preserve_context=True):
            value=script_tasks.ask_checked(instruction,payload,validate,report)
        state['batches'].append(value);state['pending'].remove(sid);save(f'已核对并保存 {len(state["batches"])}/{len(expected)} 场')
    rows={}
    for b in state['batches']:
        for row in b['source_map']:rows.setdefault(row['source_id'],row)
    for row in record['plan']['source_map']:
        if row['status']=='omit':rows[row['source_id']]={**row,'script_excerpt':''}
    value={'scenes':[b['scene'] for b in state['batches']],'source_map':list(rows.values()),'changes':[c for b in state['batches'] for c in b['changes']],'review_notes':[n for b in state['batches'] for n in b['review_notes']],'duration_advice':'\n'.join(dict.fromkeys(b['duration_advice'] for b in state['batches'] if b['duration_advice']))}
    report('所有场次已保存，正在统一核对对白、来源、银幕顺序和世界观')
    out=finish(value);state.update(status='completed',message='全片核对通过，请复核并确认正文');out['_script_generation']=state
    return out
