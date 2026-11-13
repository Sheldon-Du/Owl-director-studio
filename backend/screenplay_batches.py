"""Bounded faithful screenplay output with full context and durable checkpoints."""
import copy
import hashlib
import json
from . import ai, creative_rules, script_source, script_workflows, screenplay_expression

VERSION = 1
MAX_UNITS = 8
MAX_PARTS = 12
MAX_CHARS = 700


def fingerprint(project):
    from . import story_promo
    project = script_workflows.director_only(story_promo.for_writing(project))
    values = [VERSION, script_source.input_hash(project),
              creative_rules.signature(project, ('script_plan', 'script')),
              project.get('documents', {}).get('script', ''),project.get('documents',{}).get('script_task_plan') if project.get('script_task','auto') not in ('auto','adapt') else None]
    return hashlib.sha256(json.dumps(values, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def groups(units):
    from . import story_writing as sw
    result = []; batch = []; size = count = 0
    for unit in units:
        n = len(sw.source_parts([unit])); chars = len(unit['text'])
        if batch and (len(batch) >= MAX_UNITS or count+n > MAX_PARTS or size+chars > MAX_CHARS):
            result.append([u['id'] for u in batch]); batch = []; size = count = 0
        batch.append(unit); count += n; size += chars
    if batch: result.append([u['id'] for u in batch])
    return result


def current(project):
    state = project.get('script_generation')
    return state if isinstance(state, dict) and state.get('fingerprint') == fingerprint(project) else None


def combined(batches):
    value = {'scenes': [], 'questions': []}
    for batch in batches:
        scenes=copy.deepcopy(batch['value']['scenes'])
        if scenes and value['scenes'] and scenes[0].get('continues_previous_scene') is True:
            previous=value['scenes'][-1];first=scenes[0]
            if (previous.get('location'),previous.get('time'))!=(first.get('location'),first.get('time')):
                raise ValueError('续接上一场的地点和故事时间必须一致，不能因批次合并不同场景')
            previous['units'].extend(first['units'])
            previous['director_note']='\n'.join(n for n in (previous.get('director_note',''),first.get('director_note','')) if n)
            scenes=scenes[1:]
        value['scenes'].extend(scenes)
        value['questions'].extend(copy.deepcopy(batch['value'].get('questions', [])))
    return value


def normalize_continuation(value, completed):
    """A merge flag cannot override the scene's own location/time or prose."""
    value=copy.deepcopy(value)
    scenes=value.get('scenes')
    previous=(completed or {}).get('scenes',[])
    if isinstance(scenes,list) and scenes and isinstance(scenes[0],dict):
        first=scenes[0]
        if first.get('continues_previous_scene') is True and (not previous or
                (first.get('location'),first.get('time'))!=(previous[-1].get('location'),previous[-1].get('time'))):
            first['continues_previous_scene']=False
    return value


def generate(project, core, structure, progress=None, on_event=None, metrics=None, force=False):
    from . import story_writing as sw, story_world
    units = sw.source_units(project['story']); by_id = {u['id']: u for u in units}
    if not units: raise ValueError('请先填写故事')
    prior = current(project) if not force else None
    state = copy.deepcopy(prior) if prior and prior.get('status') != 'completed' else {
        'version': VERSION, 'fingerprint': fingerprint(project), 'batches': [],
        'pending': groups(units), 'total_units': len(units), 'completed_units': 0}
    # A draft is only reusable if its validated prefix and pending tail still
    # account for the exact source ledger. Never trust counters alone.
    assigned = [s for b in state['batches'] for s in b['source_ids']] + [s for b in state['pending'] for s in b]
    if assigned != [u['id'] for u in units]: raise ValueError('剧本草稿来源记录不完整，请舍弃草稿后重新编写')
    for batch in state['batches']:
        screenplay_expression.render(batch['value'], [by_id[s] for s in batch['source_ids']])
    # Repartition only the uncompleted tail of old, oversized drafts.
    state['pending']=[group for batch in state['pending'] for group in groups([by_id[s] for s in batch])]
    consecutive_timeouts=0
    report = progress or (lambda message: None)
    def save(message):
        if state['batches']:
            prefix=[by_id[s] for b in state['batches'] for s in b['source_ids']]
            state['draft_script']=screenplay_expression.render(combined(state['batches']),prefix)['script']
        state.update(status='running', message=message,
                     completed_units=sum(len(b['source_ids']) for b in state['batches']),
                     completed_batches=len(state['batches']),
                     total_batches=len(state['batches'])+len(state['pending']))
        if on_event: on_event({'type': 'script_checkpoint', 'state': copy.deepcopy(state)})
        report(message)
    save(f"剧本分批编写 · 已保存 {sum(len(b['source_ids']) for b in state['batches'])}/{len(units)} 段原文；每批保留完整故事上下文")
    while state['pending']:
        ids = state['pending'][0]; selected = [by_id[s] for s in ids]
        label = f"剧本第 {len(state['batches'])+1}/{len(state['batches'])+len(state['pending'])} 批 · {ids[0]}—{ids[-1]}"
        report(label+' · 正在编写与核对来源、对白和自然时序')
        try:
            with ai.asset_call_policy('screenplay_batch', metrics, limit=3, max_tokens=12288,
                                      timeout=180, preserve_context=True):
                value = sw.adapt(project, core, structure,
                    progress=lambda message: report(label+' · '+message),
                    target_units=selected, raw=True,
                    completed_context=combined(state['batches']))
            # Continuation is checked before making a result durable.
            combined([*state['batches'],{'value':value}])
        except ValueError as error:
            timeout='请求超时' in str(error)
            if ('finish_reason=length' in str(error) or timeout) and len(ids) > 1:
                middle = len(ids)//2
                state['pending'][:1] = [ids[:middle], ids[middle:]]
                save(label+(' · 请求超时' if timeout else ' · 上游截断')+'，已缩小本批输出范围；已完成内容保留')
                if not timeout or consecutive_timeouts<2:
                    consecutive_timeouts+=int(timeout)
                    continue
            raise ValueError(str(error)+f"；剧本草稿已保存 {state['completed_units']}/{len(units)} 段，回剧本页继续编写") from error
        consecutive_timeouts=0
        state['batches'].append({'source_ids': ids, 'value': value})
        state['pending'].pop(0)
        save(label+f" · 核对通过并保存（{sum(len(b['source_ids']) for b in state['batches'])}/{len(units)} 段）")
    report('所有剧本批次已保存，正在核对全片来源覆盖、顺序与世界观')
    value = combined(state['batches'])
    out = screenplay_expression.render(value, units, source_text=project['story'])
    setting_text = '\n'.join(r['script_excerpt'] for r in out['script_production_settings'])
    out['script_consistency'] = story_world.validate(project, out['script']+'\n'+setting_text)
    # Legacy reference modes are retired by director_only before this path.
    state.update(status='completed', message='剧本已完整核对；请复核表达后确认正文')
    out['_script_generation'] = state
    return out
