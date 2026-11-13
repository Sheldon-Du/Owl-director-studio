"""Native rules, a compact coverage plan, and durable per-shot results."""
from . import script_source
import copy
import hashlib
import json
import math
import re
from . import ai, director, script_workflows, store, story_world, shot_preflight, narration_visuals
from . import creative_rules, storyboard_units, screenplay_expression

VERSION = 1
MAX_SHOTS = 160


def fingerprint(project):
    from . import story_promo
    spec = script_workflows.spec(project); spec.pop('title', None)
    values = {k: project.get(k) for k in ('parameters', 'duration', 'production_scheme')}
    values.update(script=story_promo.full_script(project), visual_promo=story_promo.input_values(project), spec=spec,
                  plan=project.get('documents', {}).get('script_workflow_plan'),
                  assets=[{k: a.get(k) for k in ('id', 'kind', 'name', 'description', 'personality', 'age', 'gender', 'costume', 'visual_profile')} for a in project.get('assets', []) if a.get('visual_description_source') not in ('script','analysis') or a.get('visual_profile_source')=='user' or '"source": "user"' in json.dumps(a.get('visual_profile',{}),ensure_ascii=False)])
    if project.get('_production_source_kind')=='story' or script_source.kind(project)=='story':values['base_source_kind']='story'
    if 'storyboard_method' in project:values['storyboard_method']=project['storyboard_method']
    if storyboard_units.enabled(project):values['unit_contract_version']=3
    if 'creative_skills' in project:values['creative_rules']=creative_rules.signature(project,('storyboard_outline','storyboard'))
    if project.get('storyboard_notes','').strip():values['storyboard_notes']=project['storyboard_notes'].strip()
    if script_source.kind(project)=='script' and project.get('documents',{}).get('script_production_settings'):values['production_settings']=project['documents']['script_production_settings']
    return hashlib.sha256(json.dumps([VERSION, values], ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def revision_instruction(project):
    return ('\nsummary_revision_notes是用户的汇总修订要求，只调整镜头拆分、画面承载和估时，不改已确认剧本、对白、银幕顺序或来源归属。必要时按独立动作、状态变化、地点和时间边界拆分粗条目；完整声音仅execute一次，context/result不重演。新版需重新人工确认，旧产物不代表新版通过。' if project.get('storyboard_notes','').strip() else '')


def planning_context(project):
    return {'summary_revision_notes':project.get('storyboard_notes','').strip(),
            'production_settings':project.get('documents',{}).get('script_production_settings',[])}


def valid_state(project):
    state = project.get('storyboard_generation', {})
    return state if state.get('version') == VERSION and state.get('source_hash') == fingerprint(project) else None

def require_confirmed_outline(project,force=False):
    state=project.get('storyboard_generation') or {}
    if force:raise ValueError('继续生成不能使用重建选项；请先重新规划并确认汇总，旧镜头保留')
    if not state.get('outlines'):raise ValueError('尚无完整分镜汇总，请先生成并确认汇总')
    if not valid_state(project):raise ValueError('已有分镜汇总，但当前剧本、推文、时长、镜头美术方案或人工资产造型与汇总保存时的依据不一致。旧汇总和已生成镜头保留；请核对变更后重新规划并确认汇总，不能直接继续旧汇总。')
    if not outline_confirmed(project):raise ValueError('已有分镜汇总尚未确认，请先核对汇总与剧本的对应关系并点击确认，再继续生成')


def blocks(project):
    from . import story_promo
    project=story_promo.for_storyboard(project)
    lines = [s.strip() for s in project['documents']['script'].splitlines() if s.strip()]
    return [{'id': f'S{i+1:04}', 'text': s, 'role': 'context' if context_kind(s) else 'content'} for i, s in enumerate(lines)]


def context_kind(text):
    # Scene headings, formatting and time labels are shared context, not
    # actions to replay whenever the next shot cites the same heading.
    if re.fullmatch(r'[─━—_\-=*\s]{3,}', text): return 'separator'
    if re.fullmatch(r'(?:#{1,6}\s*)?第\s*[\d一二三四五六七八九十百〇零]+\s*(?:场|幕)(?:\s*[·｜|:：—\-].*)?',text):return 'scene'
    if re.fullmatch(r'【(?:场景描述|动作|音效|叙述|人物设定|旁白|画外音|独立叙述者|对白|对话|独白)(?:\s*[·:：｜|][^】]*)?】',text):return 'format'
    if not any(ch.isalnum() for ch in text):return 'format'
    if re.match(r'^【(?:场景|画幅|视觉风格|时间|地点)】', text): return text.split('】')[0]
    if re.fullmatch(r'[△▶]?\s*\d{1,2}:\d{2}(?:\.\d+)?\s*[–—\-~至]\s*\d{1,2}:\d{2}(?:\.\d+)?\s*', text): return 'time'
    return ''


def coverage_report(raw,source):
    required=[b for b in source if not context_kind(b['text'])]
    provided={key for row in raw if isinstance(row,dict) and isinstance(row.get('source_block_ids'),list) for key in row['source_block_ids'] if isinstance(key,str)} if isinstance(raw,list) else set()
    return {'required_content_ids':[b['id'] for b in required],
            'context_ids':[b['id'] for b in source if context_kind(b['text'])],
            'missing_content':[{'id':b['id'],'text':b['text']} for b in required if b['id'] not in provided]}


def seconds(value):
    if isinstance(value, bool): raise ValueError('镜头自然时长无效')
    try: number = float(str(value).removesuffix('s'))
    except (ValueError, TypeError): raise ValueError('镜头自然时长无效')
    if not math.isfinite(number) or not 0 < number <= 14400: raise ValueError('镜头自然时长无效')
    return number


def normalize_outlines(raw, source, review_visuals=False, correct_estimates=None,background_ids=()):
    correct_estimates=review_visuals if correct_estimates is None else correct_estimates
    if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_SHOTS: raise ValueError('镜头提纲需包含1至160镜')
    index = {b['id']: i for i, b in enumerate(source)}
    content = [b['id'] for b in source if not context_kind(b['text']) and b['id'] not in background_ids]
    rank = {key: i for i, key in enumerate(content)}; covered = set(); last = -1; result = []
    speech = shot_preflight.speech_sources({'source_excerpt':'\n'.join(b['text'] for b in source), 'source_block_ids':[b['id'] for b in source]})
    spoken = set()
    for i, item in enumerate(raw):
        ids = item.get('source_block_ids') if isinstance(item, dict) else None
        if not isinstance(ids, list) or not ids or any(not isinstance(k,str) or k not in index for k in ids): raise ValueError(f'分镜汇总第{i+1}条缺少有效的剧本段落依据')
        ids = sorted(set(k for k in ids if k in rank), key=index.get)
        if not ids: raise ValueError(f'分镜汇总第{i+1}条只有场景或时间标签，需对应实际动作、对白或字幕')
        positions = [rank[k] for k in ids]
        if positions != list(range(min(positions), max(positions)+1)):
            raise ValueError(f'分镜汇总第{i+1}条跨过了中间的剧本内容：{ids[0]}–{ids[-1]}；请拆成顺序相邻的条目')
        if min(positions) < last:
            raise ValueError(f'分镜提纲不得改变已确认剧本的银幕顺序：第{i+1}条从{ids[0]}回到上一条之前；共享标题写作上下文，动作不得倒序')
        last = max(positions); covered.update(ids)
        for key in ('focus', 'location'):
            if not isinstance(item.get(key), str) or not item[key].strip(): raise ValueError('镜头提纲缺少画面焦点或地点')
        context = {}
        for block in source[:index[ids[-1]]+1]:
            kind=context_kind(block['text'])
            if kind and kind not in ('separator','format'): context[kind]=block
        outline = {'id': store.uid(), 'index': i+1, 'source_block_ids': ids,
                       'context_block_ids': [b['id'] for b in context.values()],
                       'context_excerpt': '\n'.join(b['text'] for b in context.values()),
                       'source_excerpt': '\n'.join(source[index[k]]['text'] for k in ids),
                       'focus': item['focus'], 'location': item['location'], 'natural_seconds': seconds(item.get('natural_seconds'))}
        citations = [s for s in speech if s['id'].split('-Q')[0] in ids and s['id'] not in spoken]
        spoken.update(s['id'] for s in citations)
        outline.update(speech_sources=citations, speech_min_seconds=narration_visuals.speech_seconds(citations))
        if correct_estimates and outline['natural_seconds'] < outline['speech_min_seconds']:
            # The overview contains estimates, not generated action durations.
            # Correct a calculable lower bound locally; do not spend an AI
            # repair call or fabricate holds to make a rough estimate pass.
            corrected = seconds(outline['speech_min_seconds'])
            outline['estimate_adjustment'] = {'ai_seconds':outline['natural_seconds'], 'estimated_seconds':corrected,
                'speech_min_seconds':outline['speech_min_seconds'], 'reason':'原文朗读时间超过AI初估；此处仅校正汇总初估，具体动作与停顿另行审定'}
            outline['natural_seconds'] = corrected
        narration_visuals.review(outline, item, {b['id']:b['text'] for b in source}, result[-1] if result else None, required=review_visuals)
        result.append(outline)
    if covered != set(content): raise ValueError('镜头提纲遗漏剧本段落：'+ '、'.join(k for k in content if k not in covered)+'；保留全部情节与对白，不用删节或倍速凑片长')
    return result


def native_preparation(project):
    # The old node's optional whole-document enhancement precedes the JSON
    # builder and does not update its shot rows. Run those native rules locally.
    offline = {'ai_url': '', 'ai_key': '', 'ai_model': ''}
    base = {**project, 'story': project['documents']['script']}
    core = director.core_project(base, offline); pack = core['核心数据包']
    art, _ = director.invoke('DirectorMasterArt', {**project['production_scheme']['art'], '核心数据包': pack})
    output, _ = director.invoke('DirectorMasterCinematic', {**project['production_scheme']['cinematic'], '核心数据包': pack,
        '剧本输入': script_workflows.storyboard_input(project), '美术输入': art['美术'], '目标时长(分钟)': float(project['duration'])/60})
    from aggregator.storyboard_contract import parse_storyboard_json, validate_storyboard
    board, warnings = parse_storyboard_json(output['分镜JSON'])
    check = validate_storyboard(board)
    if not check['ok']: raise ValueError('原生分镜结构校验失败：'+json.dumps(check['errors'], ensure_ascii=False))
    return {'core_pack': director.safe_pack(pack), 'core_prompt': core['统一电影提示词'], 'art': art['美术'], 'blueprint': board}


def request(system, payload, phase, metrics):
    # Batching belongs to the planner. Preserve the complete input and let
    # truncation return immediately rather than repeating the whole document.
    budget=int(store.settings().get('ai_storyboard_max_tokens') or 32768)
    if phase.startswith('storyboard_outline_compact') and len([b for b in payload.get('script_blocks',[]) if b.get('role')=='content'])<=160:
        budget=min(budget,32768)
    if phase.startswith('storyboard_outline_visual_'):
        budget=min(budget,32768)
    repair_json=phase.startswith('storyboard_shot_')
    instruction=system+'\n只返回严格JSON对象，不使用Markdown围栏。字符串中的英文双引号、反斜杠及换行必须正确转义。'
    with ai.asset_call_policy(phase, metrics, limit=2 if repair_json else 1, max_tokens=budget, timeout=300,preserve_context=True):
        try:answer=ai.ask(instruction, json.dumps(payload, ensure_ascii=False))
        except ai.InvalidJSONResponse as error:
            if not repair_json:raise
            if metrics:metrics({'phase':phase+'_json_repair','error':str(error)})
            answer=ai.ask('你是JSON语法修复器。仅修复invalid_response的语法与字符串转义，保留原字段、原值、镜头顺序、动作时长、对白及来源编号。不新增、删除或改写剧情，不猜测缺失内容。输出一个严格JSON对象，不使用Markdown。',json.dumps({'invalid_response':error.raw_response,'validation_error':str(error)},ensure_ascii=False))
    if metrics and phase.startswith('storyboard_shot_') and isinstance(answer.get('shot'),dict):
        metrics({'phase':phase+'_schema','fields':{k:{'type':type(v).__name__,'size':len(v) if isinstance(v,(str,list,dict)) else None} for k,v in answer['shot'].items()}})
    return answer


def plan_outlines(project, prep, metrics=None, progress=None, draft=None, on_checkpoint=None):
    # Source-unit allocation uses immutable cache IDs even for short promos.
    # Asking for the unit ledger and every visual in one answer can hide
    # allocation errors behind the first visual validation failure.
    if draft or storyboard_units.enabled(project) or len(blocks(project))>=20 or len(project['documents']['script'])>4000:
        from . import outline_batches
        return outline_batches.plan(project,prep,metrics,progress,draft,on_checkpoint)
    source = blocks(project)
    system = '''你是遵守DirectorMaster规则的分镜统筹。只输出严格有效的JSON，结构为 {"shots":[{"source_block_ids":["S0001"],"location":"单一具体地点","focus":"简短画面内容","natural_seconds":6}]}，示例编号需替换为本镜实际content编号。所有字段名与段落编号使用双引号，字符串里的英文双引号必须转义；引用对白可使用中文「」避免破坏JSON。不输出分析、注释或围栏。
只编写紧凑镜头汇总，不写完整提示词。按script_blocks的书写顺序，覆盖每个role=content原文块；时间轴中的闪回也按剧本给定的银幕顺序呈现。role=context是场景标题、画幅或时间标签，只提供上下文，不作为独立镜头，无需反复写入source_block_ids。source_block_ids只写本镜实际动作、对白、旁白、字幕的content编号，每条编号连续，不跨过中间content；下条最早编号不得早于上条最后编号。同一长段可拆镜复用该段id，边界段落可复用，不能把此前已结束的事件再演一遍。声音标签和对应台词保持相邻，完整保留事件、对白、旁白和结局。地点必须单一具体，人物与物件只能来自剧本及该人物资产，不照抄原生结构参考的虚构事实。每镜只承载自然可完成的动作，按动作、准确台词及必要反应估时，不均分目标时长、不慢放或加速；超过目标片长也完整保留。最多160镜。'''
    seeds = [{k: r.get(k) for k in ('镜号', '阶段', '景别', '角度', '运镜', '焦段')} for r in prep['blueprint']['分镜表']]
    payload = {**planning_context(project),'script_blocks': source, 'parameters': project['parameters'], 'scheme': project['production_scheme'],
          'spec': script_workflows.spec(project), 'workflow_plan': project['documents'].get('script_workflow_plan'), 'native_camera_structure': seeds,
          'coverage_contract':{'required_content_ids':[b['id'] for b in source if b['role']=='content'],
                               'context_ids':[b['id'] for b in source if b['role']=='context']}}
    system+='\ncoverage_contract.required_content_ids 是必须覆盖的完整清单；context_ids 不需要独立镜头。第N场标题和单独的【场景描述】标签只作上下文，标题下的实际场景描述仍需覆盖。提交前逐项核对清单，不能遗漏开场、转场后的内容或结尾。修正时依 coverage_report.missing_content 补齐真实缺项，保持已有有效条目的焦点、地点和顺序，不为补漏重复事件，不把标签做成镜头。'
    system+='''
按叙事事件、可见信息变化和情绪转折决定切镜，不按段落、旁白句数或目标镜头数拆镜。连续多个旁白段落讲同一事件时优先合并，不为凑自然时长反复拍睡觉、呼吸、手指或眼皮。慢节奏风格不等于每句话单独一镜。保留原文全部声音，旁白与画面可同时发生，估时至少覆盖自然说话时间，不将并行画面动作和说话机械相加，也不能压缩台词。
每个有旁白的条目必须增加visual_plan：{"mode":"narration_illustration","image":"具体可见的画面","anchors":["image中逐字出现的可见主体或物件短语"],"purpose":"这幅画面提供的新信息或情绪作用","time_context":"当下／原文回忆示意／概念插入","cut_reason":"为什么需要切到这幅画面","evidence":[{"block_id":"本镜content编号","quote":"该段逐字原文依据"}]}。mode可选present_action（当下实际动作）、narration_illustration（旁白对应的说明画面）、reaction（必要反应）；无旁白条目也可填写。
画面不要仅写“旁白讲述某事”。旁白提到论文时可表现原文论文、修改文字的细节；提到已发生的经历时可用有依据的回忆示意或物件细节。只做原文信息的视觉呈现，不增添新人物关系、对白、关键事件或未来情节；没有具体依据的外貌、地点、时代器物不得当成已发生事实。地点写实际出现在画面中的单一地点，time_context说明画面时间层，保持旁白播放与剧本书写顺序，回忆示意后衔接回当前动作。锚点用于后续首帧和视频生成，必须是可见内容，不能是“学历”“压力”等抽象词。若叙事确实需要睡觉或静止反应，集中为一个必要镜头并说明作用；相邻旁白不得重复同一睡觉反应。'''
    payload['speech_sources']=shot_preflight.speech_sources({'source_excerpt':'\n'.join(b['text'] for b in source), 'source_block_ids':[b['id'] for b in source]})
    system+='\nvisual_plan.mode必须按本镜实际分配的声音选择：只有本镜所属且尚未被前镜播放的voiceover原句存在时，才可用narration_illustration。仅对白或动作的镜头使用present_action或reaction；不要把对白当旁白、不要为画面方案新增画外音。共享段落的声音只由首次使用该原句的镜头播放，后续同段拆镜仍可展示当下动作。'
    system+='\n画面依据优先使用evidence:[{block_id:本镜所属编号,quote_ref:同一编号}]，不要自行改写或拼接quote。程序从本次script_blocks逐字回填原文；quote_ref只能来自本镜source_block_ids。必须先检查该段确实支持image，再填写引用；来源引用不是新增剧情许可。旧quote写法仍须逐字连续匹配。不能用原始故事或完整剧本的句子代替当前画面化推文script_blocks。'
    payload['speech_timing_contract']={'maximum_units_per_second':5, 'phase':'outline_estimate',
        'source_minimums':[{'id':s['id'],'minimum_seconds':narration_visuals.speech_seconds([s])} for s in payload['speech_sources'] if s['kind']!='quote']}
    system+='\nspeech_timing_contract.source_minimums给出逐条原句的朗读下限。按本镜完整原句和动作估时；同一人物连续说话不并行播放。程序会将不足的汇总初估校正到原文朗读下限并记录原因，此值仅作初估，不代表已审定动作时长，不额外添加静止、循环或慢放来补时间。'
    system+=creative_rules.instruction(project,'storyboard_outline')
    system+=revision_instruction(project)
    if storyboard_units.enabled(project):system+=storyboard_units.INSTRUCTION
    for attempt in range(2):
        if progress: progress('正在按剧本核对并修正分镜汇总（仅修正一次，不生成具体镜头）' if attempt else '正在通读已确认剧本，生成分镜汇总并匹配原文')
        answer=None
        try:
            answer=request(system, payload, 'storyboard_outline_repair' if attempt else 'storyboard_outline', metrics)
            outlines=normalize_answer(project,answer,source,review_visuals=True)
            metadata=[{'index':o['index'],'corrections':o.get('visual_plan',{}).get('metadata_corrections')} for o in outlines if o.get('visual_plan',{}).get('metadata_corrections')]
            if metadata:
                if metrics:metrics({'phase':'storyboard_outline_metadata','items':metadata})
                if progress:progress(f'已保留画面与原文依据，为{len(metadata)}条汇总规范制作说明与画面要点')
            adjusted=[o for o in outlines if o.get('estimate_adjustment')]
            if adjusted:
                if metrics: metrics({'phase':'storyboard_outline_estimates','adjustments':[{'index':o['index'],**o['estimate_adjustment']} for o in adjusted]})
                if progress: progress(f'分镜汇总已核对；{len(adjusted)}条初估已按原文朗读下限校正，具体动作时长待逐镜审定')
            return outlines
        except ValueError as error:
            # Only returned JSON/schema problems get a repair call. Provider
            # timeouts and network failures still stop without retries.
            if answer is None and not str(error).startswith('AI 未返回有效 JSON'):raise
            if metrics: metrics({'phase':'storyboard_outline_validation', 'error':str(error)})
            if isinstance(answer,dict) and isinstance(answer.get('shots'),list):
                from . import outline_batches
                try:visual_draft=outline_batches.seed_answer(project,prep,answer,source,metrics)
                except ValueError as allocation_error:
                    if metrics:metrics({'phase':'storyboard_outline_allocation_validation','error':str(allocation_error)})
                    payload['allocation_validation_error']=str(allocation_error)
                else:
                    if progress:progress('全片顺序与原文分配已核对，保留合格画面，仅定点修正未通过的镜头')
                    return outline_batches.plan(project,prep,metrics,progress,visual_draft,on_checkpoint)
            if attempt: raise ValueError(str(error)+'；汇总未通过核对，未开始具体分镜生成')
            invalid=answer.get('shots') if answer else None
            payload.update(validation_error=str(error), invalid_outline=invalid,coverage_report=coverage_report(invalid,source),
                           repair_instruction='按错误信息修正画面方案、自然估时或段落覆盖。合并重复的旁白反应镜，或补充本镜原文支持的可见信息；按书写顺序补齐missing_content。保留合格内容，不改剧本、不删声音、不压缩自然时间。')


def normalize_answer(project,answer,source,review_visuals=False):
    if not storyboard_units.enabled(project):
        raw=copy.deepcopy(answer.get('shots'))
        adjustments={}
        if isinstance(raw,list):
            index={b['id']:i for i,b in enumerate(source)}
            for position,row in enumerate(raw):
                ids=row.get('source_block_ids',[]) if isinstance(row,dict) else []
                if not ids or any(k not in index for k in ids):continue
                first,last=min(index[k] for k in ids),max(index[k] for k in ids)
                span=source[first:last+1]
                missing=[b['id'] for b in span if not context_kind(b['text']) and b['id'] not in ids]
                other={k for j,r in enumerate(raw) if j!=position and isinstance(r,dict) for k in r.get('source_block_ids',[]) if isinstance(k,str)}
                boundary=any(context_kind(b['text']) in ('scene','time','【时间','【地点','【场景') for b in span[1:])
                if missing and len(missing)<=3 and len(span)<=8 and not boundary and not set(missing)&other and sum(len(b['text']) for b in span)<=1200:
                    row['source_block_ids']=[b['id'] for b in span if not context_kind(b['text'])]
                    adjustments[position]={'added_block_ids':missing,'reason':'同一连续空间内补齐被跳过的原文引用，未改写正文、对白或顺序'}
        result=normalize_outlines(raw,source,review_visuals=review_visuals,correct_estimates=True)
        for position,adjustment in adjustments.items():result[position]['source_alignment']=adjustment
        return result
    answer=storyboard_units.without_format_units(answer,source)
    backgrounds={u.get('block_id') for u in answer.get('units',[]) if isinstance(u,dict) and u.get('kind')=='context' and u.get('delivery')=='background' and u.get('context_reason')} if isinstance(answer.get('units'),list) else set()
    outlines=normalize_outlines(answer.get('shots'),source,correct_estimates=False,background_ids=backgrounds)
    speech=shot_preflight.speech_sources({'source_excerpt':'\n'.join(b['text'] for b in source),'source_block_ids':[b['id'] for b in source]})
    storyboard_units.bind(answer,source,outlines,speech)
    if review_visuals:
        for o,item in zip(outlines,answer['shots']):narration_visuals.review(o,item,{b['id']:b['text'] for b in source},outlines[o['index']-2] if o['index']>1 else None,required=True)
    return outlines


def normalize_saved(project,outlines,source,review_visuals=False):
    modern=storyboard_units.enabled(project)
    backgrounds={u['block_id'] for o in outlines for u in o.get('content_units',[]) if u.get('kind')=='context' and u.get('delivery')=='background'} if modern else set()
    result=normalize_outlines(outlines,source,review_visuals=review_visuals and not modern,correct_estimates=not modern,background_ids=backgrounds)
    for old,new in zip(outlines,result):
        new['id']=old['id'];storyboard_units.keep(old,new)
        if old.get('estimate_adjustment'):new['estimate_adjustment']=copy.deepcopy(old['estimate_adjustment'])
    if review_visuals and modern:
        for o,item in zip(result,outlines):narration_visuals.review(o,item,{b['id']:b['text'] for b in source},result[o['index']-2] if o['index']>1 else None,required=True)
    return result


def outline_confirmed(project):
    state=valid_state(project)
    # Existing saved shots can continue with their already-used outline.
    return bool(state and not state.get('outline_draft') and state.get('outlines') and state.get('outline_confirmed', bool(project.get('shots'))))


def speed_change(text):
    return story_world.speed_change(text)


def normalize_shot(raw, outline, seed, project):
    if not isinstance(raw, dict): raise ValueError('AI未返回单镜头参数')
    raw=copy.deepcopy(raw)
    required = shot_preflight.REQUIRED
    missing=[k for k in required if not isinstance(raw.get(k),str) or not raw[k].strip()]
    if missing: raise ValueError('单镜头字段需填写非空字符串：'+'、'.join(missing))
    # Outline timing is an initial estimate, never an approved lower bound.
    # Actual natural duration is audited after the complete action is written.
    dur = seconds(raw.get('时长'))
    text = '\n'.join(str(raw.get(k, '')) for k in required)
    if speed_change(text): raise ValueError('分镜不允许慢镜、倍速或时间压缩')
    world = story_world.contract(project)
    unsupported = [w for w in world['unsupported_modern_props'] if w in text and w not in project['documents']['script']]
    if unsupported: raise ValueError('分镜混入无剧本依据的现代器物：'+'、'.join(unsupported))
    dialogue = raw.get('dialogue', []); voiceover = raw.get('voiceover', '')
    if not isinstance(dialogue, list) or any(not isinstance(d, str) or not d or d not in outline['source_excerpt'] for d in dialogue): raise ValueError('本镜对白必须逐字来自所属剧本段落')
    voice_lines=raw.get('_voiceover_lines', [voiceover] if voiceover else [])
    if not isinstance(voiceover, str) or any(not isinstance(v,str) or v not in outline['source_excerpt'] for v in voice_lines): raise ValueError('本镜旁白必须逐字来自所属剧本段落')
    # The structured speech has already been verified against the screenplay.
    # Render it verbatim locally rather than spending another model call to
    # fix omitted punctuation or a missing speech section in the rich prompt.
    if dialogue:
        spoken='；'.join('“'+line+'”' for line in dialogue)
        if any(line not in raw['AIGC提示词'] for line in dialogue):raw['AIGC提示词']+='\n角色对白（逐字原文，只说一遍）：'+spoken
        if any(line not in raw['音频描述'] for line in dialogue):raw['音频描述']+='\n同期角色对白（逐字原文）：'+spoken
    for line in voice_lines:
        if line not in raw['音频描述']:raw['音频描述']+='\n独立画外音（逐字原文，不让画面角色口播）：'+line
    row = {k: copy.deepcopy(seed[k]) for k in ('阶段', '类型阶段', '情感强度', '线', 'POV', '时间线', '叙事标签', '拓扑张力') if k in seed}
    row.update({k: raw.get(k, '') for k in (*required, '转场', '叙事目的', '色彩', '光影', '材质', '氛围', '情绪')})
    roles=raw.get('角色',[])
    if '角色' in raw:row['角色']=roles if isinstance(roles,(list,str)) else []
    row.update(场景=outline.get('location',''),台词=copy.deepcopy(dialogue),旁白=voiceover,音效=raw.get('音效',''))
    if isinstance(raw.get('调色和打光'),str):row['调色和打光']=raw['调色和打光']
    row.update(镜号=outline['index'], 银幕序=outline['index'], 时序位=outline['index'], 时长=dur)
    if outline.get('visual_plan'): row['旁白画面方案']=copy.deepcopy(outline['visual_plan'])
    from aggregator.aigc_adapter import adapt_shot_for_mode
    mode=project['production_scheme']['cinematic'].get('AIGC生产模式', '文生视频')
    if mode=='自动判别':mode='文生视频'
    # Native mode guidance is additive: its compact focus line must not replace
    # the full seven-part prompt or discard exact speech and lighting.
    row['AIGC适配提示词'] = adapt_shot_for_mode(row, mode)+'\n'+row['AIGC提示词']
    check = director.validate_native({'contract_version': 2, '分镜表': [row]})
    if not check['ok']: raise ValueError('单镜头原生契约校验失败：'+json.dumps(check['errors'], ensure_ascii=False))
    return row


def outline_context(outline,include_units=False):
    # The complete screenplay is supplied separately. Global navigation does
    # not need repeated excerpts and execution-state records for every unit.
    value={k:copy.deepcopy(outline[k]) for k in ('id','index','location','focus','natural_seconds','source_block_ids','unit_carriers') if k in outline}
    if outline.get('visual_plan'):value['visual_plan']={k:copy.deepcopy(outline['visual_plan'][k]) for k in ('image','purpose','time_context','cut_reason') if k in outline['visual_plan']}
    if include_units:value['content_units']=[{k:copy.deepcopy(u[k]) for k in ('id','block_id','kind','quote','story_time') if k in u} for u in outline.get('content_units',[])]
    return value


def local_unit_handles(outline):
    value=copy.deepcopy(outline)
    lookup={u['id']:f'E{i+1}' for i,u in enumerate(value.get('content_units',[]))}
    for unit in value.get('content_units',[]):unit['id']=lookup[unit['id']]
    for carrier in value.get('unit_carriers',[]):carrier['unit_id']=lookup[carrier['unit_id']]
    return value,{alias:identity for identity,alias in lookup.items()}


def map_action_units(value,identities):
    value=copy.deepcopy(value)
    if not isinstance(value,dict):return value
    for action in value.get('actions',[]) if isinstance(value.get('actions'),list) else []:
        if isinstance(action,dict) and isinstance(action.get('unit_ids'),list):
            action['unit_ids']=[identities.get(k,k) if isinstance(k,str) else k for k in action['unit_ids']]
    return value


def generate_shot(project, prep, outlines, outline, completed, report, metrics):
    from aggregator.llm_engine import _build_native_prompt
    scheme = project['production_scheme']; pack = json.loads(prep['core_pack'])
    native = _build_native_prompt('分镜', scheme['cinematic'].get('画面模式', '电影工作室'), pack.get('_导演风格', '王家卫'),
                                  {'scene': outline['source_excerpt'], 'mood': pack.get('_情绪基调', ''), 'intent': pack.get('_导演意图_观众应感到', '')})
    system = native + '''\n本次只生成指定的一镜，严格遵守已确认剧本和用户方案。前面关于整篇输出长度的要求不适用于本次单镜JSON：每个参数简短明确，完整视频提示词最多500字；不编写整篇分镜或分析报告。返回严格有效的JSON，外层键为"shot"，内部完整填写shot_template所有字段。字段名和字符串必须双引号，不能用string、number之类占位词作输出。填写前自查required_fields，尤其"构图"必须是具体站位、空间关系和画面布局，不能缺省、空值或用景别代替。
导演风格只影响视觉，不增加范例的故事、时代或器物。原生结构仅作机位和组织参考。本镜只呈现current_outline所属段落，不提前表演下一镜；previous_shots只用于人物位置、朝向、光线、动作与物件连续性。不得照抄别人的外貌。全部动作实时自然发生，不慢放、倍速、延时、重复循环；输出使用“自然实时”表述速度，不写上述速度变换词，即使是否定句。提纲natural_seconds仅为初估，不把初估当作下限；context_excerpt中的时间标签不用于限时或压缩动作。
同时填写actions，先决定各完整动作、说话、反应、位移的自然时长与依据。每段必须有id、description、natural_seconds、minimum_seconds、maximum_seconds、rationale、speech_ids。natural_seconds落在min/max范围；位移补distance_m和speed_m_s；depends_on只能引用前面的动作id。不要输出start/end或镜头总时长，程序会按自然时长累计，禁止均分目标片长。对白和旁白只选择speech_sources中的id，分别填dialogue_ids和voiceover_ids；actions.speech_ids将原句分配到对应动作段，全部所选原句只播放一次并留够自然说话与呼吸时间。required_speech_ids全部保留，未提及对白则dialogue_ids=[]。不自己抄写、改标点或润色台词，完整提示词中的原句用{{原句id}}槽位，程序逐字填入。独立画外音写音频描述，不让角色口播。首帧是动作起点，需自然起动并完成。完整提示词写清主体、空间、动作起止、景别机位运镜、光色材质、声音，不写秒数或时间标签。'''
    system+='''\ncurrent_outline.visual_plan是已确认的画面方案。按其image、anchors、purpose、time_context写本镜画面、首帧与动作；叙述当下过去经历的旁白可以配该方案中有原文依据的回忆说明画面，不能因previous_shots位于车厢等地点就一直沿用同一睡觉画面。画面时间层不同要明确衔接，旁白顺序保持原文；镜头风格不改变原文事实。narration_illustration的anchors至少一个逐字出现在画面焦点及首帧提示词中，不只提在声音字段。声音与画面同时发生时，在同一actions段承载，按二者所需的较长时间估算。'''
    system+=creative_rules.instruction(project,'storyboard')
    if outline.get('content_units'):system+='\ncontent_units与unit_carriers是已确认的执行分配。每个actions填写unit_ids；execute单元全部恰好执行一次，context和result只说明已有状态，不再执行动作/对白，不提前执行next_outline单元。填写continuity的start/end接口，包含location、story_time、characters[{asset_id,name,position,facing,costume}]、props[{asset_id,name,holder,state}]、lighting、sound；transition={type:continuous|cut|time_change|location_change,reason:衔接理由}。未知状态写未明确，不伪造资产ID；首帧呈现start状态，结束画面呈现end状态。连续同地镜复制前镜结束时的已知道具归属、服装、光线规范标签，改变要有剧本依据。'
    system+='\nasset_id_contract是已有资产注册表，不是需要补建的清单。asset_id只能从对应类型allowed_ids选取；没有对应资产的角色和道具一律填空字符串""，不能写名字、未明确、null或新造编号。location严格使用current_outline.location，拍摄位置和机位写构图，不另改地点标识。'
    system+='\nspeech_timing_contract给出完整原句朗读下限；同一actions内所选对白和旁白按顺序播放，应累计各原句下限，再考虑动作和停顿。同段画面与声音并行取较长者。不得为贴合汇总初估缩短自然时长；min/max与自然时长保持一致。all_outlines是紧凑导航，完整原文始终在confirmed_script，本镜详细分配在current_outline，next_outline仅供接续，不提前执行。'
    seed_rows = prep['blueprint']['分镜表']; seed = seed_rows[min(len(seed_rows)-1, int((outline['index']-1)*len(seed_rows)/len(outlines)))]
    sources=shot_preflight.speech_sources(outline)
    shared={key for other in outlines if other['id']!=outline['id'] for key in other.get('source_block_ids',[])}
    required_speech=[s['id'] for s in sources if s['kind']!='quote' and ('speech_sources' in outline or s['id'].split('-Q')[0] not in shared)]
    template={key:'' for key in (*shot_preflight.REQUIRED,*shot_preflight.OPTIONAL)}
    from . import storyboard_prose
    system+='\n'+storyboard_prose.rules()+'\n角色填写本镜实际出镜角色名字列表；场景使用current_outline.location；音效字段填写环境声与动作声，或明确无额外音效。台词与旁白继续用原句id槽位及dialogue_ids/voiceover_ids，程序逐字写入并排成文字稿。'
    from . import standardized_storyboard
    system+='\n'+standardized_storyboard.rules()
    template.update(角色=[],场景=outline['location'],音效='',dialogue_ids=[],voiceover_ids=[],actions=[{'id':'a1','description':'','natural_seconds':3,'minimum_seconds':2,'maximum_seconds':4,'rationale':'','speech_ids':[]}])
    template['调色和打光']=''
    template['actions'][0]['sound_layers']={key:'' for key in ('environment','music','physical','upper','transition')}
    if outline.get('content_units'):
        template['actions'][0]['unit_ids']=[]
        state_template={'location':outline['location'],'story_time':'','characters':[],'props':[],'lighting':'','sound':''}
        template['continuity']={'start':copy.deepcopy(state_template),'end':copy.deepcopy(state_template),'transition':{'type':'continuous','reason':''}}
        previous_end=completed[-1].get('连续性接口',{}).get('end',{}) if completed else {}
        if previous_end.get('location') and previous_end['location']!=outline['location']:
            template['continuity']['transition']['type']='location_change'
            system+='\n本镜的地点标识与前镜不同。continuity.transition.type必须用location_change并依据确认剧本说明从前镜地点切到本镜地点；不能填continuous或仅填cut。不同空间的光照可不同，人物服装、携带物和故事时间仍依剧本保持接续。'
    current,unit_ids=local_unit_handles(outline)
    system+='\ncurrent_outline使用本次请求的短单元编号E1、E2等；actions.unit_ids从unit_id_contract.execute_ids逐字选取，程序将其还原为固定缓存ID。不得使用段落S编号、别的镜头单元或自行编造单元ID。'
    payload = {**planning_context(project),'current_outline': current, 'next_outline': outline_context(outlines[outline['index']],True) if outline['index'] < len(outlines) else None,
        'all_outlines':[outline_context(o) for o in outlines],'native_art_direction':prep['art'],
        'confirmed_script':project['documents']['script'],
        'previous_shots': [{k: r.get(k) for k in ('镜号', '画面焦点', '构图', '光影', 'AIGC提示词','连续性接口')} for r in completed[-2:]],
        'scheme': scheme, 'native_camera_reference': {k: seed.get(k) for k in ('阶段', '景别', '角度', '运镜', '焦段')},
        'world': story_world.contract(project), 'assets': [{k: a.get(k) for k in ('id','name', 'kind', 'description', 'personality','visual_profile','age','gender','costume')} for a in project.get('assets', [])],
        'required_fields':list(shot_preflight.REQUIRED),'shot_template':template,'speech_sources':sources,'required_speech_ids':required_speech,
        'asset_id_contract':{'unbound_id':'','allowed_ids':{kind:[a['id'] for a in project.get('assets',[]) if a.get('kind')==kind] for kind in ('character','prop')}},
        'unit_id_contract':{mode+'_ids':[c['unit_id'] for c in current.get('unit_carriers',[]) if c['mode']==mode] for mode in ('execute','context','result')},
        'speech_id_contract':{'dialogue_ids':[s['id'] for s in sources if s['kind']=='dialogue'],'voiceover_ids':[s['id'] for s in sources if s['kind']=='voiceover'],'forbidden':'禁止引用S段落编号、E动作单元编号、其他镜头原句编号；actions.speech_ids只能来自本镜已选dialogue_ids与voiceover_ids'},
        'speech_timing_contract':{'maximum_units_per_second':5,'source_minimums':[{'id':s['id'],'minimum_seconds':narration_visuals.speech_seconds([s])} for s in sources if s['kind']!='quote']}}
    report(f'正在生成第 {outline["index"]}/{len(outlines)} 镜（含动作自然时长预案）；保存前核对全部字段与剧本原句')
    answer=request(system,payload,f'storyboard_shot_{outline["index"]}',metrics)
    raw=map_action_units(answer.get('shot'),unit_ids)
    try:
        row=shot_preflight.prepare(raw,outline,project,normalize_shot,seed,speed_change,sources,required_speech,completed[-1] if completed else None)
    except shot_preflight.InvalidShot as error:
        if metrics:metrics({'phase':f'storyboard_shot_{outline["index"]}_validation','error':str(error),'issues':error.issues})
        allowed=sorted(set(k for i in error.issues for k in i['fields']))
        report(f'第 {outline["index"]}/{len(outlines)} 镜保存前纠错：'+ '、'.join(allowed)+'；保留其余已合格字段')
        repair_system=system+'\n本轮为保存前定点纠错。只返回JSON {"patch":{需要修改的字段:修正值}}，只允许填写repair_fields列出的键。未列出的字段已通过校验，严禁重写。一次处理validation_issues的全部问题，actions若有错需返回完整动作列表；continuity支持只修改对应start/end/transition子字段，省略的现有字段保留。不要返回整镜shot。'
        working=map_action_units(raw,{v:k for k,v in unit_ids.items()})
        repair_payload={**payload,'repair_fields':allowed,'validation_issues':error.issues,'invalid_fields':{k:working.get(k) for k in allowed} if isinstance(working,dict) else {},
                        'accepted_fields':{k:v for k,v in working.items() if k not in allowed} if isinstance(working,dict) else {}}
        patched=request(repair_system,repair_payload,f'storyboard_shot_{outline["index"]}_repair',metrics)
        repaired,ignored=shot_preflight.merge_patch(raw,patched,error.issues)
        repaired=map_action_units(repaired,unit_ids)
        if metrics:metrics({'phase':f'storyboard_shot_{outline["index"]}_patch','changed_fields':allowed,'ignored_fields':ignored})
        try:row=shot_preflight.prepare(repaired,outline,project,normalize_shot,seed,speed_change,sources,required_speech,completed[-1] if completed else None)
        except ValueError as final:
            if metrics:metrics({'phase':f'storyboard_shot_{outline["index"]}_validation','error':str(final)})
            raise ValueError(f'第{outline["index"]}镜保存前预检未通过：{final}；本镜未发布，前面已完成镜头保留') from final
    row['创作规则应用']=creative_rules.audit(project,'storyboard')
    standardized_storyboard.apply(row)
    return row


def single_target(project, identity):
    state=valid_state(project)
    if not outline_confirmed(project):raise ValueError('请先确认与剧本匹配的分镜汇总')
    outline=next((o for o in state['outlines'] if o['id']==identity),None)
    if not outline:raise ValueError('单镜生成目标不在当前分镜汇总中')
    existing={s.get('generation_outline_id'):s for s in project.get('shots',[]) if s.get('generation_source_hash')==state['source_hash']}
    missing=next((o for o in state['outlines'][:outline['index']-1] if o['id'] not in existing),None)
    if missing:raise ValueError(f'请先完成第{missing["index"]}镜，再生成第{outline["index"]}镜，以衔接人物、空间与动作')
    from . import shot_continuity
    for prior in project.get('shots',[]):
        if prior.get('generation_index',0)<outline['index']:shot_continuity.gate(project,prior['id'])
    return outline


def generate(project, config, progress=None, on_event=None, metrics=None, force=False, plan_only=False, require_outline=False, target_outline=None, regenerate=False):
    from . import story_promo
    project=story_promo.for_storyboard(project)
    report = progress or (lambda m: None); emit = on_event or (lambda e: None)
    if not project.get('documents', {}).get('script'): raise ValueError('请先填写故事或有效剧本')
    if storyboard_units.enabled(project) and (not config.get('ai_url') or not config.get('ai_model')):raise ValueError('剧情单元分配需要配置文本AI；已有段落汇总仍可使用原生离线方式')
    scheme = director.validate_scheme(project.get('production_scheme', {}))
    if not scheme.get('art') or not scheme.get('cinematic'): raise ValueError('请先填写镜头与美术方案')
    if target_outline:
        if force or plan_only:raise ValueError('单镜生成不能同时重建分镜汇总')
        single_target(project,target_outline)
    source = fingerprint(project); state = None if force else valid_state(project)
    if require_outline:require_confirmed_outline(project,force)
    if not state or not state.get('preparation') or state.get('outline_draft'):
        draft=(state or {}).get('outline_draft')
        if not isinstance(draft,dict) or draft.get('version')!=1 or draft.get('source_hash')!=source:draft=None
        report('正在按原生规则准备镜头结构与美术空间（本地执行）')
        prep = copy.deepcopy(draft['preparation']) if draft and draft.get('preparation') else native_preparation(project)
        report('正在通读已确认剧本，编写紧凑镜头提纲（单次AI等待上限330秒）')
        if config.get('ai_url') and config.get('ai_model'):
            def checkpoint(value):
                emit({'type':'storyboard_outline_checkpoint','source_hash':source,'draft':value})
            outlines = plan_outlines(project, prep, metrics, report,draft,checkpoint)
        else:
            # Preserve the native offline option and checkpoint each row.
            outlines = [{'id': store.uid(), 'index': i+1, 'natural_seconds': seconds(r['时长']), 'focus': r['画面焦点'],
                         'location': '原生场景', 'source_excerpt': project['documents']['script'], 'source_block_ids': []} for i, r in enumerate(prep['blueprint']['分镜表'])]
        state = {'version': VERSION, 'source_hash': source, 'preparation': prep, 'outlines': outlines, 'total': len(outlines), 'outline_confirmed': not plan_only,
                 'outline_review': {'ordered':True, 'covered':True, 'content_blocks':len([b for b in blocks(project) if b['role']=='content'])}}
        state['rule_application']=creative_rules.audit(project,'storyboard_outline')
        if storyboard_units.enabled(project):state['outline_review'].update(atomic_granularity='pending_user_review',semantic_fidelity='pending_user_review',actual_visual_continuity='not_applicable_yet')
        emit({'type': 'storyboard_plan', 'source_hash': source, 'state': state})
    if plan_only:
        return {'plan_only':True, 'source_hash':source, 'total':len(state['outlines']),
                'estimate_adjusted':sum(bool(o.get('estimate_adjustment')) for o in state['outlines'])}
    prep = state['preparation']; outlines = state['outlines']
    existing = {s.get('generation_outline_id'): s for s in project.get('shots', []) if s.get('generation_source_hash') == source}
    completed = []; reused = 0
    for outline in outlines:
        old = existing.get(outline['id'])
        replace=bool(old and target_outline==outline['id'] and regenerate)
        if target_outline and target_outline!=outline['id'] and not old:continue
        if old and not replace:
            from . import shot_continuity
            shot_continuity.gate(project,old['id'])
            row = current_row(old, outline['index']); reused += 1
        elif config.get('ai_url') and config.get('ai_model'):
            row = generate_shot(project, prep, outlines, outline, completed, report, metrics)
        else:
            row = copy.deepcopy(prep['blueprint']['分镜表'][outline['index']-1])
        if not old or replace:
            from . import timing
            emit({'type': 'storyboard_shot', 'source_hash': source, 'outline_id': outline['id'], 'index': outline['index'], 'row': row, 'prefix_hash': prefix_hash(completed),
                  'replace':replace,'expected_shot_hash':timing.shot_signature(old) if replace else None})
        completed.append(row)
        report(f'已保存 {len(completed)}/{len(outlines)} 镜（复用 {reused} 镜），可中断后继续')
    result={'source_hash':source,'total':len(outlines),'reused':reused,'single_shot':bool(target_outline),'complete':len(completed)==len(outlines),
            'generated_index':next((o['index'] for o in outlines if o['id']==target_outline),None)}
    if not result['complete']:return result
    board = assemble(prep, completed)
    report('全部镜头已保存，正在执行原生整体契约与审查')
    docs = director.checked_storyboard(prep['core_pack'], prep['core_prompt'], project['documents']['script'], {'分镜JSON': json.dumps(board, ensure_ascii=False)}, report, prep['art'])
    docs.update({k: project['documents'][k] for k in (*screenplay_expression.DOC_KEYS,'script_policy', 'script_changes', 'script_policy_note', 'script_adaptation_map', 'script_director_notes', 'script_input_hash', 'script_consistency','script_task_plan','script_task_source_map','script_task_review','script_duration_advice','script_task_used','creative_rule_application', *script_workflows.DOC_KEYS) if k in project['documents']})
    # A story-only planning view must never publish the story as screenplay.
    if project.get('_production_source_kind')=='story':
        docs.pop('script',None)
    else:docs['script']=story_promo.full_script(project)
    return {**result,'documents':docs}


def current_row(shot, index):
    row = copy.deepcopy(shot['native'])
    for key in ('start', 'end', 'start_s', 'end_s', 'duration_s'): row.pop(key, None)
    row.update(镜号=index, 银幕序=index, 时长=shot['duration'], 画面焦点=shot['description'], AIGC提示词=shot['prompt'], AIGC适配提示词=shot['prompt'])
    return row


def prefix_hash(rows):
    values=[{'index':r['镜号'],'duration':seconds(r['时长']),'description':r['画面焦点'],'prompt':r.get('AIGC适配提示词') or r['AIGC提示词']} for r in rows]
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def assemble(prep, rows):
    board = copy.deepcopy(prep['blueprint'])
    board.update(分镜表=rows, 分镜数=len(rows), 总时长秒=round(sum(seconds(r['时长']) for r in rows), 3))
    board['情感曲线'] = [r.get('情感强度', 5) for r in rows]
    board['叙事元数据'] = [{'line': r.get('线', 'A'), 'pov': r.get('POV', '全知'), 'timeline': r.get('时间线', '现在')} for r in rows]
    return board
