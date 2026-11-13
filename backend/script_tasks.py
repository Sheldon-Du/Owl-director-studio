"""Task-specific screenplay instructions, source ledgers and reviewed outlines."""
import hashlib
import json
import math
from . import creative_rules
from pathlib import Path

RULES_PATH = Path(__file__).resolve().parents[1] / 'rules' / 'story-screenplay-methods.md'
TASKS = {
    'adapt': {'name': '忠实剧本化', 'policy': 'screenplay', 'rules': [
        '完整覆盖原文，保持原文的银幕顺序、人物、因果、结局及全部引文。内心信息用画外音，不凭空增加行动或对白。']},
    'continue': {'name': '续写 · 保留开头补全后续', 'policy': 'creative', 'rules': [
        '先提取开头结束时人物所知、目标、关系、道具和未解决伏笔；新场次从这些状态承接。',
        '原开头只作技术性剧本化，完整覆盖并保持顺序；其场次全部在新增场次之前，原引文锁定。',
        '后续新人物、冲突和结局服务既有主线，不能用追认式设定推翻开头事实；修订只改新增部分和必要衔接。']},
    'expand': {'name': '扩写 · 从创意发展完整故事', 'policy': 'creative', 'rules': [
        '锁定给出的创意核心与限制，建立主角目标、阻碍、代价、选择和变化，再扩成必要场次。',
        '新增人物、事件和世界规则标为授权新增；每条支线说明推动主线或改变人物选择的作用，不填充无关内容。']},
    'condense': {'name': '缩编 · 保留主线压缩内容', 'policy': 'creative', 'rules': [
        '先区分必需因果、必要动机、情感转折与可省略重复，再提出合并和删减的短版提纲。',
        '主线因果、必要线索、人物动机及用户保护项不得删掉；每项省略写理由及其原功能如何承担。',
        '合并场次不合并不同物理地点，不让人物出现在不兼容的时空；仍放不下时建议延长或分集，不加速对白。']},
    'restructure': {'name': '重编 · 重组结构与信息揭示', 'policy': 'creative', 'rules': [
        '建立保留锚点和拟改动点，分别记录故事时间与新版银幕顺序，说明重排/改写的依据。',
        '设计每场观众与人物的知情范围、伏笔与回收；揭示必须有铺垫，不在结尾凭空加入解决问题的规则。',
        '事实、关键事件及结局只在用户许可范围内改变，不为钩子让人物隐瞒其理应表达的信息。']},
    'perspective': {'name': '视角改编 · 从指定人物讲述', 'policy': 'creative', 'rules': [
        '以viewpoint指定人物为叙述视角，逐场注明目击、听闻、推断或未知及依据。',
        '默认保留客观事件、时间与人物关系；只调整关注重点和揭示方式，不把换视角当成改事实。',
        '人物不能回忆未经历/未听说的对话，不能提前知道后来才出现的线索；主观理解不能冒充客观事实。']},
}
SETTINGS = {'requirements', 'must_keep', 'viewpoint', 'preserve_dialogue', 'preserve_ending'}
PLAN_SCHEMA = '''只输出JSON {summary:string, scenes:[{id:唯一场次编号,source_ids:[原文S编号],origin:source|authorized,location:string,time:string,goal:string,obstacle:string,action:string,result:string,story_time:string,knowledge:string,estimated_seconds:number,seconds_basis:string}],source_map:[{source_id:S编号,status:retain|merge|omit,reason:string}],pending_questions:[string],review_notes:[string],duration_advice:string}。
最多40个叙事场次。source_map恰好覆盖所有原文编号，retain/merge的来源必须绑定到source场次；authorized场次source_ids为空，来源是任务授权。omit仅限缩编或重编，并写明原因，不在其他场次隐性恢复。每场填写目标、阻碍、行动、结果、故事时间及自然估时依据；unknown填“原文未明确”，不捏造事实。续写的全部source场次在authorized场次之前，source_ids完整覆盖开头且保持顺序。pending_questions仅放阻碍正式写作的重大待决问题；非阻碍建议放review_notes。时长合计超出duration_seconds，duration_advice说明差额及延长/分集/经允许删减方案，不加速。'''


def task(project):
    return project.get('script_task', 'auto')


def validate(project):
    selected = task(project)
    if selected not in ('auto', *TASKS):
        raise ValueError('请选择有效的剧本编写任务')
    settings = project.get('script_task_settings', {})
    if not isinstance(settings, dict) or set(settings) - SETTINGS:
        raise ValueError('剧本任务设置包含不支持的字段')
    for key in ('requirements', 'must_keep', 'viewpoint'):
        if key in settings and (not isinstance(settings[key], str) or len(settings[key]) > 4000):
            raise ValueError('剧本任务要求需为4000字以内的文本')
    for key in ('preserve_dialogue', 'preserve_ending'):
        if key in settings and not isinstance(settings[key], bool):
            raise ValueError('剧本保留选项需为布尔值')
    if selected != 'auto' and project.get('story_policy', 'faithful') != TASKS[selected]['policy']:
        raise ValueError('此任务需要选择' + ('忠于故事剧本化' if selected == 'adapt' else 'AI编排') + '；原文直用不执行改写')


def input_values(project):
    if task(project) == 'auto':
        return None
    return {'task': task(project), 'settings': project.get('script_task_settings', {})}


def settings(project):
    selected = task(project)
    return {'preserve_dialogue': True, 'preserve_ending': selected in ('adapt', 'continue', 'condense', 'perspective'),
            **project.get('script_task_settings', {})}


def instruction(project):
    text = RULES_PATH.read_text(encoding='utf-8')
    selected = task(project)
    if selected != 'auto':
        text += '\n本次任务：' + TASKS[selected]['name'] + '\n' + '\n'.join(TASKS[selected]['rules'])
        text += '\n用户任务设置：' + json.dumps(settings(project), ensure_ascii=False)
        text += '\npreserve_ending=true时原结局属于禁改项；must_keep是必须保留的情节与设定，不因缩编或叙事模板删除。'
    return text


def source_hash(project):
    from . import script_source
    return script_source.input_hash(project)


def plan_hash(record):
    value = {k: v for k, v in record.items() if k != 'approval_token'}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def current_plan(project):
    record = project.get('documents', {}).get('script_task_plan')
    return record if isinstance(record, dict) and record.get('source_hash') == source_hash(project) and record.get('task') == task(project) and record.get('rule_signature') == creative_rules.signature(project,('script_plan','script')) else None


def ledger(value, units):
    if not isinstance(value, list) or len(value) != len(units):
        raise ValueError('来源对应表必须逐段完整覆盖原文')
    expected = {u['id'] for u in units}
    found = set()
    for row in value:
        if not isinstance(row, dict) or row.get('source_id') not in expected or row['source_id'] in found:
            raise ValueError('来源对应表含未知或重复原文编号')
        if row.get('status') not in ('retain', 'merge', 'omit') or not str(row.get('reason', '')).strip():
            raise ValueError('每段来源需填写有效处理方式与理由')
        found.add(row['source_id'])
    return {r['source_id']: r for r in value}


def validate_plan(value, project, units):
    if not isinstance(value, dict) or not isinstance(value.get('summary'), str) or not value['summary'].strip():
        raise ValueError('改编提纲缺少概述')
    sources = ledger(value.get('source_map'), units)
    if task(project) not in ('condense', 'restructure') and any(r['status'] == 'omit' for r in sources.values()):
        raise ValueError('此任务不允许省略原文段落')
    scenes = value.get('scenes')
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 40:
        raise ValueError('改编提纲需包含1至40个场次')
    ids = set(); seen = []; added = False; total = 0
    for scene in scenes:
        if not isinstance(scene, dict):
            raise ValueError('提纲场次必须为对象')
        for key in ('id', 'location', 'time', 'goal', 'obstacle', 'action', 'result', 'story_time', 'seconds_basis'):
            if not isinstance(scene.get(key), str) or not scene[key].strip():
                raise ValueError('提纲场次缺少非空字段：' + key)
        if scene['id'] in ids:
            raise ValueError('提纲场次编号重复')
        ids.add(scene['id'])
        refs = scene.get('source_ids')
        if not isinstance(refs, list) or any(not isinstance(s, str) or s not in sources or sources[s]['status'] == 'omit' for s in refs) or len(set(refs))!=len(refs):
            raise ValueError('提纲场次引用了不存在或已省略的原文')
        if scene.get('origin') not in ('source', 'authorized') or (scene['origin'] == 'source' and not refs) or (scene['origin'] == 'authorized' and refs):
            raise ValueError('原文场次需有来源，授权新增场次不得伪造原文编号')
        if task(project) == 'continue':
            if scene['origin'] == 'authorized': added = True
            elif added: raise ValueError('续写新增内容必须在已有开头场次之后')
        if task(project) == 'adapt' and scene['origin'] == 'authorized':
            raise ValueError('忠实剧本化不允许新增情节场次')
        if task(project) == 'perspective' and (not isinstance(scene.get('knowledge'), str) or not scene['knowledge'].strip()):
            raise ValueError('视角改编需逐场说明角色的知识来源')
        seconds = scene.get('estimated_seconds')
        if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError('场次自然估计时长必须为正数')
        total += seconds; seen.extend(refs)
    kept = {s for s, row in sources.items() if row['status'] != 'omit'}
    if set(seen) != kept:
        raise ValueError('提纲场次未覆盖所有保留或合并的原文')
    if task(project) in ('continue', 'adapt'):
        order = [s for i, s in enumerate(seen) if i == 0 or seen[i-1] != s]
        if order != [u['id'] for u in units]:
            raise ValueError('已有开头/忠实提纲必须保持原文完整覆盖和顺序')
    for key in ('pending_questions', 'review_notes'):
        if not isinstance(value.get(key, []), list) or any(not isinstance(x, str) for x in value.get(key, [])):
            raise ValueError('提纲待决事项与审查建议必须为文字列表')
    if total > float(project['duration']) and not str(value.get('duration_advice', '')).strip():
        raise ValueError('提纲超出目标时长，需说明延长、分集或允许的压缩建议')
    value['estimated_seconds'] = round(total, 2)
    return value


def ask_checked(system, payload, finish, progress=None):
    from . import ai
    previous = None; error = None
    for attempt in range(3):
        if attempt and progress: progress(f'正在纠正剧本任务 {attempt}/2：{error[:150]}')
        data = payload if not attempt else {**payload, 'validation_error': error, 'previous': previous}
        try: previous = ai.ask(system + ('\n只修复校验失败字段及受影响场次，保留其他内容、采用的提纲与禁改项；不得删来源记录或锁定台词过关。返回完整JSON。' if attempt else ''), json.dumps(data, ensure_ascii=False))
        except ValueError as failure:
            if not str(failure).startswith('AI 未返回有效 JSON'): raise
            error = str(failure); previous = None
        else:
            try: return finish(previous)
            except ValueError as failure: error = str(failure)
    raise ValueError('剧本任务纠正2次后仍未通过：' + error + '；原有正文保留')


def payload(project, core, structure):
    from . import story_writing, story_world, character_profiles
    return {'source_units': story_writing.source_units(project['story']), 'duration_seconds': project['duration'],
            'script_mode': project.get('script_mode'), 'director_parameters': project.get('parameters', {}),
            'director_rules': core['统一电影提示词'], 'native_structure': structure,
            'story_world_contract': story_world.contract(project), 'task': task(project),
            'task_settings': settings(project),
            'character_personalities':[{'name':a['name'],'features':character_profiles.personality_notes(a)} for a in project.get('assets',[]) if a.get('kind')=='character']}


def generate_plan(project, core, structure, progress=None):
    validate(project)
    if task(project) == 'auto': raise ValueError('请先选择具体剧本任务，再生成改编提纲')
    if task(project) == 'perspective' and not project.get('script_task_settings', {}).get('viewpoint', '').strip():
        raise ValueError('请填写视角人物或叙述立场')
    data = payload(project, core, structure)
    if progress: progress('正在生成' + TASKS[task(project)]['name'] + '提纲与来源对应')
    def finish(value):
        plan = validate_plan(value, project, data['source_units'])
        record = {'source_hash': source_hash(project), 'task': task(project), 'plan': plan,'rule_signature':creative_rules.signature(project,('script_plan','script'))}
        record['approval_token'] = plan_hash(record)
        return {'script_task_plan': record}
    return ask_checked('你是DirectorMaster剧本规划助手。只规划，不写正文、不生成媒体。\n' + instruction(project) + creative_rules.instruction(project,'script_plan') + '\n' + PLAN_SCHEMA, data, finish, progress)


def write_task(project, core, structure, approved_plan, progress=None,on_event=None,metrics=None,force=False):
    from . import story_writing, story_world
    record = current_plan(project)
    if not record or approved_plan != plan_hash(record):
        raise ValueError('请先生成当前任务的提纲，再点击“采用提纲并编写剧本”')
    if record['plan'].get('pending_questions'):
        raise ValueError('提纲有重大待决问题，请补充任务要求并重新生成提纲后再编写')
    data = payload(project, core, structure); data['approved_plan'] = record['plan']
    data['dialogue_contract'] = story_writing.dialogue_contract(data['source_units'])
    system = '''你是遵循DirectorMaster的编剧。按approved_plan写正文，只输出JSON：
{scenes:[{id:采用提纲中的编号,text:本场正文字符串，区分【动作】【对白 · 人名】【画外音】}],changes:[{type:新增|合并|删减|重排|改写,description:string}],source_map:[{source_id:S编号,status:retain|merge|omit,script_excerpt:最终本场正文中能逐字定位的片段，省略项为空字符串,reason:string}],review_notes:[string],duration_advice:string}。
scenes严格采用提纲的全部场次编号与银幕顺序，不新增、删除或重排场次；地点时间由程序回填。source_map完整覆盖原文，处理状态与采用提纲一致。保留对白时每条对应来源的引文完整保留，可分布在对应场次，不冒用说话人。续写对开头只技术性剧本化，不改事实或原引文，新增内容在其后。来源片段要覆盖该原文事件，不用无关公共词作为依据。
逐项列出相对用户原文的实际改动，不把未采用规则范例列为删改。只输出可表演的正文，审查意见与待决事项不混入剧情。自查人物动机、时代、因果、时空、道具连续性和视角所知；未经验证不要宣称准确时长或百分百忠实。'''
    system += '\n' + instruction(project)+creative_rules.instruction(project,'script')
    def finish(value):
        if not isinstance(value, dict) or not isinstance(value.get('scenes'), list): raise ValueError('任务剧本缺少场次正文')
        plan_scenes = record['plan']['scenes']
        if [s.get('id') if isinstance(s, dict) else None for s in value['scenes']] != [s['id'] for s in plan_scenes]:
            raise ValueError('正文场次必须与采用提纲的编号和银幕顺序一致')
        body = []; texts = {}
        for i, (scene, planned) in enumerate(zip(value['scenes'], plan_scenes), 1):
            if not isinstance(scene.get('text'), str) or not scene['text'].strip(): raise ValueError('场次正文不能为空')
            texts[planned['id']] = scene['text'].strip()
            body.append(f"第{i}场 · {planned['location']} · {planned['time']}\n{scene['text'].strip()}")
        script = '\n\n'.join(body)
        rows = ledger(value.get('source_map'), data['source_units'])
        planned_rows = {r['source_id']: r for r in record['plan']['source_map']}
        mapping = []
        locked = task(project) == 'continue' or project.get('script_task_settings', {}).get('preserve_dialogue', True)
        for unit in data['source_units']:
            row = rows[unit['id']]
            if row['status'] != planned_rows[unit['id']]['status']: raise ValueError('正文不得改变采用提纲中的来源保留/省略决定')
            excerpt = row.get('script_excerpt', '')
            related = '\n'.join(texts[s['id']] for s in plan_scenes if unit['id'] in s['source_ids'])
            if not isinstance(excerpt, str) or (row['status'] != 'omit' and (not excerpt.strip() or excerpt not in related)) or (row['status'] == 'omit' and excerpt):
                raise ValueError('来源对应片段必须逐字存在于绑定场次正文，省略项不能伪造片段')
            if locked and row['status'] != 'omit' and any(q not in related for _, q in story_writing.literal_quotes(unit['text'])):
                raise ValueError(unit['id'] + '：遗漏或改写了锁定原句对白/引文')
            mapping.append({**row, 'source_quote': unit['text']})
        changes = value.get('changes')
        if not isinstance(changes, list) or not changes or any(not isinstance(c, dict) or c.get('type') not in ('新增', '合并', '删减', '重排', '改写') or not isinstance(c.get('description'), str) or not c['description'].strip() for c in changes):
            raise ValueError('任务剧本需逐项说明有效的新增、合并、删减、重排或改写')
        if record['plan']['estimated_seconds'] > float(project['duration']) and not str(value.get('duration_advice', '')).strip():
            raise ValueError('正文仍超过目标时长，需保留时长取舍提示')
        review = value.get('review_notes', [])
        if not isinstance(review, list) or any(not isinstance(n, str) for n in review): raise ValueError('正文审查建议需为文字列表')
        return {'script': script, 'script_policy': 'creative', 'script_changes': changes,
                'script_policy_note': TASKS[task(project)]['name'] + '，按采用提纲编写；请核对内容后确认正文。',
                'script_task_plan': record, 'script_task_source_map': mapping, 'script_task_review': review,
                'script_duration_advice': value.get('duration_advice', ''), 'script_task_used': task(project),
                'script_consistency': story_world.validate(project, script)}
    if progress: progress('正在按采用提纲编写' + TASKS[task(project)]['name'])
    if on_event is not None:
        from . import task_script_batches
        return task_script_batches.generate(project,record,system,data,finish,progress,on_event,metrics,force)
    return ask_checked(system, data, finish, progress)
