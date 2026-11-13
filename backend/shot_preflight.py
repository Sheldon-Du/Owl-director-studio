"""Validate a draft before publishing it; repairs cannot replace good fields."""
import copy
import re
from . import timing, story_world
from . import storyboard_units,shot_continuity

REQUIRED = ('画面焦点', '景别', '角度', '运镜', '焦段', '构图', '声音',
            '首帧描述', 'AIGC提示词', '首帧提示词', '音频描述')
OPTIONAL = ('转场', '叙事目的', '色彩', '光影', '材质', '氛围', '情绪')
SPEECH_FIELDS = ('dialogue_ids', 'voiceover_ids', 'dialogue', 'voiceover')
QUOTE = re.compile(r'「([^」]+)」|“([^”]+)”|"([^"\n]+)"')


class InvalidShot(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__('；'.join(i['message'] for i in issues))


def speech_sources(outline):
    """Expose literal screenplay citations, never ask the model to retype them."""
    # New outlines carry citations parsed during the full screenplay read.
    # A cut may start with the body whose speaker label was in the previous cut.
    if isinstance(outline.get('speech_sources'), list):
        result=copy.deepcopy(outline['speech_sources'])
        lines=[line.strip() for line in outline.get('source_excerpt','').splitlines() if line.strip()]
        for source in result:
            if source.get('kind')!='quote':continue
            for index,line in enumerate(lines):
                whole=QUOTE.fullmatch(line)
                if whole and next(q for q in whole.groups() if q)==source.get('text') and index and lines[index-1].startswith('【画面'):
                    source['kind']='dialogue';source['classification_basis']='画面卡点后的独立引号台词';break
        return result
    lines = outline['source_excerpt'].splitlines()
    ids = outline.get('source_block_ids', [])
    result = []; pending = ''; speaker = ''
    for index, line in enumerate(lines):
        key = ids[index] if index < len(ids) else f'L{index+1}'
        line = line.strip()
        heading = re.fullmatch(r'【(旁白|画外音|独立叙述者|对白|对话|独白|动作|场景描述)(?:\s*[·:：｜|]\s*([^】]*))?】', line)
        if heading:
            category, speaker = heading.group(1), (heading.group(2) or '').strip()
            pending = 'voiceover' if category in ('旁白', '画外音', '独立叙述者') else 'dialogue' if category in ('对白', '对话', '独白') else ''
            continue
        inline=re.match(r'^【(旁白|画外音|独立叙述者|对白|对话|独白)(?:\s*[·:：｜|]\s*([^】]*))?】\s*(.+)$',line)
        if inline:
            category,speaker,body=inline.groups();body=body.strip();whole=QUOTE.fullmatch(body)
            result.append({'id':f'{key}-Q1','kind':'voiceover' if category in ('旁白','画外音','独立叙述者') else 'dialogue',
                           'speaker':(speaker or '').strip(),'text':next(q for q in whole.groups() if q) if whole else body})
            pending='';speaker='';continue
        if not line: continue
        if re.match(r'^(?:【|#{1,6}\s|第\s*[\d一二三四五六七八九十百]+\s*[场幕])', line):
            pending = ''; speaker = ''; continue
        if pending:
            # Keep the complete spoken paragraph, including a quoted thesis
            # title or nested quotations, instead of extracting only the quote.
            whole = QUOTE.fullmatch(line)
            literal = next(q for q in whole.groups() if q) if whole else line
            result.append({'id': f'{key}-Q1', 'kind': pending, 'speaker': speaker, 'text': literal})
            pending = ''; speaker = ''; continue
        label = re.match(r'^([^：:\n]{1,32})[：:]\s*(.*)$', line.strip())
        head = label.group(1) if label else ''
        voice = bool(re.search(r'旁白|画外音|独立叙述者|\bVO\b|V\.O\.', head or line, re.I))
        spoken = bool(head or pending or re.search(r'说|问|答|喊|低声|气声', line))
        visible = bool(re.search(r'字幕|画面文字|牌匾|招牌|写着|铭文', head or line))
        kind = 'quote' if visible else 'voiceover' if voice or pending == 'voiceover' else 'dialogue' if spoken else 'quote'
        previous=next((v.strip() for v in reversed(lines[:index]) if v.strip()),'')
        if kind=='quote' and not visible and QUOTE.fullmatch(line) and previous.startswith('【画面'):kind='dialogue'
        if head:
            speaker = re.sub(r'[（(].*', '', head).strip()
        if label and voice and label.group(2).strip():
            body = label.group(2).strip(); whole = QUOTE.fullmatch(body)
            result.append({'id': f'{key}-Q1', 'kind': 'voiceover', 'speaker': speaker,
                           'text': next(q for q in whole.groups() if q) if whole else body})
            pending = ''; speaker = ''; continue
        matches = list(QUOTE.finditer(line))
        if matches:
            for n, match in enumerate(matches):
                result.append({'id': f'{key}-Q{n+1}', 'kind': kind, 'speaker': speaker,
                               'text': next(q for q in match.groups() if q)})
            pending = ''; speaker = ''
        elif label and not label.group(2).strip():
            pending = 'voiceover' if voice else 'dialogue'
        elif label and (voice or not re.search(r'场景|地点|时间|画幅|光影|动作|镜头|标题|题目|名称|内容|说明|描述', head)):
            result.append({'id': f'{key}-Q1', 'kind': 'voiceover' if voice else 'dialogue',
                           'speaker': speaker, 'text': label.group(2).strip()})
            pending = ''; speaker = ''
        else:
            pending = ''; speaker = ''
    return result


def prepare(raw, outline, project, normalize, seed, speed_change, sources, required_speech_ids=(), previous_row=None):
    issues = []
    def issue(fields, message): issues.append({'fields': list(fields), 'message': message})
    if not isinstance(raw, dict):
        raise InvalidShot([{'fields': [*REQUIRED, *SPEECH_FIELDS, 'actions', *(['continuity'] if outline.get('content_units') else [])], 'message': 'AI未返回单镜头对象'}])
    draft = copy.deepcopy(raw); catalogue = {s['id']: s for s in sources}
    if '角色' in draft and (not isinstance(draft['角色'],list) or any(not isinstance(v,str) or not v.strip() for v in draft['角色'])):
        issue(['角色'],'角色需填写实际出镜者名字列表，无角色用空列表')
    if '音效' in draft and (not isinstance(draft['音效'],str) or not draft['音效'].strip()):
        issue(['音效'],'音效需填写环境声、动作声或明确无额外音效')
    for field in REQUIRED:
        if not isinstance(draft.get(field), str) or not draft[field].strip():
            issue([field], f'单镜头字段需填写非空字符串：{field}')
    world = story_world.contract(project)
    for field in (*REQUIRED, *OPTIONAL):
        text = draft.get(field)
        if not isinstance(text, str): continue
        if speed_change(text): issue([field], f'{field}不允许慢镜、倍速或时间压缩')
        unsupported = [w for w in world['unsupported_modern_props'] if w in text and w not in project['documents']['script']]
        if unsupported: issue([field], f'{field}混入无剧本依据的现代器物：'+'、'.join(unsupported))
        # Citations are substituted locally, preserving punctuation and dashes.
        for identity, source in catalogue.items():
            text = text.replace('{{'+identity+'}}', '“'+source['text']+'”')
        if re.search(r'\{\{[^{}]+\}\}', text): issue([field], f'{field}引用了不存在的剧本原句编号')
        for match in re.finditer(r'(?:说|问|答|喊|念|对白|旁白|画外音)[^“「"\n]{0,12}(?:「([^」]+)」|“([^”]+)”|"([^"\n]+)")', text):
            literal = next(q for q in match.groups() if q)
            if literal not in outline['source_excerpt']:
                issue([field], f'{field}含有改写或无本镜依据的台词，请使用原句编号槽位')
        draft[field] = text
    if isinstance(draft.get('AIGC提示词'), str):
        draft['AIGC提示词'] = timing.remove_estimates(draft['AIGC提示词'])
        if not draft['AIGC提示词']: issue(['AIGC提示词'], '视频提示词不能只有时间标签，需写完整动作与画面')

    plan = outline.get('visual_plan', {})
    if plan.get('mode') == 'narration_illustration':
        # Concrete visible anchors from the reviewed plan must survive in the
        # visual fields; mentioning them only in the audio is insufficient.
        for field in ('画面焦点', '首帧提示词'):
            from .narration_visuals import visible_match
            if not any(visible_match(anchor,draft.get(field)) for anchor in plan.get('anchors', [])):
                issue([field, '首帧描述', 'AIGC提示词', 'actions'], f'{field}未呈现已确认的旁白画面要点：'+ '、'.join(plan.get('anchors', [])))

    selected = []
    voice_lines = []
    for field, kind, target in (('dialogue_ids', 'dialogue', 'dialogue'), ('voiceover_ids', 'voiceover', 'voiceover')):
        if field in draft:
            values = draft[field]
            if not isinstance(values, list) or any(not isinstance(k, str) or k not in catalogue or catalogue[k]['kind'] != kind for k in values):
                issue([field], f'{field}必须引用本镜对应类型的原句编号；收到{values!r}；允许{[s["id"] for s in sources if s["kind"]==kind]!r}')
                continue
            if len(set(values)) != len(values): issue([field], f'{field}不得重复同一句话')
            selected.extend(values)
            lines = [catalogue[k]['text'] for k in values]
            if kind == 'dialogue': draft[target] = lines
            else: voice_lines = lines; draft[target] = '\n'.join(lines)
        else:
            literal = draft.get(target, [] if kind == 'dialogue' else '')
            lines = literal if isinstance(literal, list) else [literal] if isinstance(literal, str) and literal else []
            if (kind == 'dialogue' and not isinstance(literal, list)) or (kind == 'voiceover' and not isinstance(literal, str)) or any(not isinstance(s, str) or not s or s not in outline['source_excerpt'] for s in lines):
                issue([field, target, 'AIGC提示词', '音频描述'], f'本镜{kind}必须逐字来自所属剧本段落，请改用原句编号')
            else:
                if 'speech_sources' in outline and any(not any(s['kind']==kind and s['text']==line for s in sources) for line in lines):
                    issue([field, target, 'actions'], f'本镜{kind}不能引用分配给其他镜头的原句，请使用本镜原句编号')
                selected.extend(s['id'] for s in sources if s['kind'] == kind and s['text'] in lines)
                if kind == 'voiceover': voice_lines = lines
    missing_speech = set(required_speech_ids)-set(selected)
    if missing_speech:
        issue(['dialogue_ids', 'voiceover_ids', 'actions'], '本镜遗漏剧本原句：'+'、'.join(sorted(missing_speech)))
    if voice_lines: draft['_voiceover_lines'] = voice_lines

    try:
        actions, duration = timing.from_natural(draft.get('actions'))
        carried = []
        for index, action in enumerate(actions):
            if 'sound_layers' in action:
                layers=action['sound_layers']
                if not isinstance(layers,dict) or any(not isinstance(layers.get(key),str) or not layers[key].strip() for key in ('environment','music','physical','upper','transition')):
                    issue(['actions'],f'动作{index+1}的五层音效需填写非空字符串；不存在的声源写无，不新增配乐或物体')
            for field in ('id', 'description', 'rationale'):
                if not isinstance(action.get(field), str) or not action[field].strip():
                    issue(['actions'], f'动作{index+1}的{field}需填写非空字符串')
            description = str(action.get('description') or '')
            if speed_change(description): issue(['actions'], f'动作{index+1}不得使用慢镜、倍速或时间压缩')
            unsupported = [w for w in world['unsupported_modern_props'] if w in description and w not in project['documents']['script']]
            if unsupported: issue(['actions'], f'动作{index+1}混入无剧本依据的现代器物：'+'、'.join(unsupported))
            if action.get('maximum_seconds') is None:
                issue(['actions'], f'动作{index+1}缺少自然时长上限maximum_seconds')
            if 'speech_ids' in action:
                values = action['speech_ids']
                if not isinstance(values, list) or any(not isinstance(k, str) or k not in selected for k in values):
                    issue(['actions'], f'动作{index+1}需引用已选择的本镜原句编号；收到{values!r}；已选{selected!r}')
                    continue
                carried.extend(values)
                action['dialogue'] = '；'.join(catalogue[k]['text'] for k in values if catalogue[k]['kind']=='dialogue')
                action['voiceover'] = '；'.join(catalogue[k]['text'] for k in values if catalogue[k]['kind']=='voiceover')
            for kind in ('dialogue', 'voiceover'):
                value = action.get(kind, '')
                allowed = draft.get('dialogue', []) if kind=='dialogue' else voice_lines
                if 'speech_ids' not in action and value and (not isinstance(value, str) or not any(value == text or value == '；'.join(allowed) for text in allowed)):
                    issue(['actions'], f'动作{index+1}不得新增或改写本镜{kind}')
                elif value and 'speech_ids' not in action:
                    carried.extend(s['id'] for s in sources if s['kind']==kind and s['text']==value)
        if set(selected)-set(carried): issue(['actions'], '动作预案需为本镜全部对白和旁白留出自然说话时间')
        if len(carried)!=len(set(carried)): issue(['actions'], '同一句对白或旁白不得在多个动作段重复播放')
        if carried != [s['id'] for s in sources if s['id'] in set(selected)]:
            issue(['actions'], '对白与旁白应按所属剧本原句的银幕顺序播放')
        checked = timing.validate({'duration': duration, 'actions': actions, 'natural_status': 'ai_reviewed', 'prompt': ''})
        for message in checked['errors']: issue(['actions'], message)
        draft.update(actions=actions, 时长=duration)
    except (ValueError, TypeError) as error:
        issue(['actions'], str(error))
    for message in storyboard_units.check_actions(raw,outline):issue(['actions'],message)
    continuity=None
    if outline.get('content_units'):
        try:
            continuity=shot_continuity.validate(raw.get('continuity'),outline,project)
            if previous_row:
                comparison=shot_continuity.compare({'id':'previous','native':previous_row},{'native':{'连续性接口':continuity}})
                if comparison['status']=='needs_review':
                    hint='。地点已改变时需明确continuity.transition.type="location_change"（只写cut不能解释地点改变）并说明剧本依据' if any(v['field']=='location' for v in comparison['issues']) else ''
                    issue(['continuity'],'前镜结束与本镜开始的记录冲突：'+ '; '.join(f"{v['field']}：{v['previous']} → {v['next']}" for v in comparison['issues'])+'；接续已知状态，或明确剧本允许的时空转换及依据'+hint)
        except ValueError as error:issue(['continuity'],str(error))
    if issues: raise InvalidShot(issues)
    row = normalize(draft, outline, seed, project)
    row.update(动作预案=actions, 剧本原句编号=list(dict.fromkeys(selected)),
               生成预检={'version': 1, 'passed': True, 'timing': 'preliminary'})
    if continuity:row.update(连续性接口=continuity,剧情单元承载=copy.deepcopy(outline['unit_carriers']))
    return row


def merge_patch(original, answer, issues):
    allowed = set(k for i in issues for k in i['fields'])
    patch = answer.get('patch') if isinstance(answer, dict) else None
    # Some compatible models return the old wrapper; it is still a patch,
    # and unrelated fields from it are never applied.
    if not isinstance(patch, dict) and isinstance(answer, dict): patch = answer.get('shot')
    if not isinstance(patch, dict): raise ValueError('纠错需返回patch对象，只填写校验列出的字段')
    result = copy.deepcopy(original) if isinstance(original, dict) else {}
    def merge_record(before,changes):
        if not isinstance(before,dict) or not isinstance(changes,dict):return copy.deepcopy(changes)
        merged=copy.deepcopy(before)
        for key,value in changes.items():merged[key]=merge_record(merged.get(key),value)
        return merged
    for key,value in patch.items():
        if key not in allowed:continue
        # Minimal interface patches preserve unspecified valid fields; lists
        # are complete replacements. The merged result is validated again.
        result[key]=merge_record(result.get(key),value) if key=='continuity' else copy.deepcopy(value)
    return result, sorted(set(patch)-allowed)
