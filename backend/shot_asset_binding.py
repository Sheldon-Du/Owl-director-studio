"""Associate visible shot subjects with known assets, using auditable evidence."""
import copy
import hashlib
import json
import time
from . import ai, store, asset_references


def inputs(project, shot):
    from . import skill_workflows
    outline = next((o for o in project.get('storyboard_generation', {}).get('outlines', []) if o.get('id') == shot.get('generation_outline_id')), {})
    return {
        'adopted_skill_image_rules':skill_workflows.prompt_rules(project,'image'),
        'script_hash': hashlib.sha256(str(project.get('documents', {}).get('script', '')).encode()).hexdigest(),
        'shot': {k: shot.get(k) for k in ('description', 'prompt', 'actions')},
        'first_frame': {k: shot.get('native', {}).get(k) for k in ('首帧描述', '首帧提示词')},
        'script_context': {k: outline.get(k) for k in ('location', 'source_excerpt', 'context_excerpt')},
        'asset_catalog': [{k: a.get(k) for k in ('id', 'name', 'kind', 'description', 'age', 'gender', 'costume', 'visual_profile')} for a in project.get('assets', [])],
        # Legacy bindings remain user-controlled. New AI associations never
        # become manual selections when the next candidate is generated.
        'manual_asset_ids': shot.get('manual_asset_ids', shot.get('asset_ids', [])),
        'excluded_asset_ids': shot.get('excluded_asset_ids', []),
    }


def fingerprint(project, shot):
    return hashlib.sha256(json.dumps(inputs(project, shot), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def cached(project, shot):
    result = shot.get('frame_asset_binding')
    return copy.deepcopy(result) if result and result.get('source_hash') == fingerprint(project, shot) else None


def evidence_sources(data):
    sources=[]
    def collect(value):
        if isinstance(value,str) and value.strip() and value not in sources:sources.append(value)
        elif isinstance(value,dict):
            for child in value.values():collect(child)
        elif isinstance(value,list):
            for child in value:collect(child)
    for group in ('shot','first_frame','script_context'):collect(data.get(group,{}))
    return [{'source_id':f'E{i+1}','text':value} for i,value in enumerate(sources)]


def validate(answer, data):
    if not isinstance(answer, dict) or not isinstance(answer.get('bindings'), list):
        raise ValueError('AI 资产关联需要返回 bindings 列表')
    catalog = {a['id']: a for a in data['asset_catalog']}
    sources=evidence_sources(data);source_map={s['source_id']:s['text'] for s in sources}
    bindings = []; seen = set()
    for row in answer['bindings']:
        if not isinstance(row, dict) or row.get('asset_id') not in catalog:
            raise ValueError('AI 关联了资产目录中不存在的元素')
        identity = row['asset_id']
        label=catalog[identity]['name']
        evidence=row.get('evidence','');usage=row.get('usage','')
        if not isinstance(evidence,str) or not isinstance(usage,str):raise ValueError(f'资产「{label}」的 evidence 和 usage 必须是文字')
        evidence=evidence.strip();usage=usage.strip()
        source_id=row.get('evidence_source_id')
        if source_id is not None:
            if not isinstance(source_id,str) or source_id not in source_map:raise ValueError(f'资产「{label}」引用了不存在的原文依据编号')
            allowed=[source_map[source_id]]
            if not evidence:evidence=allowed[0]
        else:allowed=[s['text'] for s in sources]
        def matches(text):
            return evidence in text or ''.join(evidence.split()) in ''.join(text.split())
        if not evidence or not any(matches(text) for text in allowed):
            raise ValueError(f'资产「{label}」的原文依据不是本镜原句；请复制 evidence_sources 中的文字，或返回其 evidence_source_id，不能改写或引用资产档案')
        if not usage:raise ValueError(f'资产「{label}」缺少画面用途 usage；请写明首帧中的位置、可见用途及需保持的特征')
        if identity in seen:
            raise ValueError('AI 资产关联重复')
        bindings.append({'asset_id': identity, 'evidence': evidence, 'usage': usage}); seen.add(identity)
    return bindings


def associate(project, shot, report=None, metrics=None):
    report = report or (lambda message: None)
    previous = cached(project, shot)
    if previous:
        report('复用本镜 AI 资产关联，使用各元素当前参考图')
        return previous
    data = inputs(project, shot)
    report('AI 正在核对本镜角色、场景和道具，关联首帧参考元素')
    bindings = []
    if data['asset_catalog']:
        request_data = copy.deepcopy(data)
        request_data['evidence_sources']=evidence_sources(data)
        # Association needs identity and local context, not every field's
        # extraction history and citations from the entire asset library.
        request_data['asset_catalog'] = [{k: (v[:1200] if isinstance(v, str) else v) for k, v in a.items() if k != 'visual_profile'} for a in data['asset_catalog']]
        system = '''你是分镜首帧的资产关联助手。只输出 JSON {"bindings":[{"asset_id":"目录中的ID","evidence":"逐字摘录本镜或本镜剧本上下文","usage":"此元素在首帧中的位置、用途和需保留的身份/空间/物件特征"}]}。
阅读 shot、first_frame、script_context，匹配 asset_catalog 中首帧实际可见的角色、场景和道具。只能使用目录ID，场景按实际空间匹配；不能把不同地点合并，也不能把他人的发色服装身份赋给本角色。对白中提到但不出镜的人、回忆之外的人、未来才出现的道具不要加入首帧。依据必须逐字来自本镜或本镜剧本上下文，不能来自资产目录自身。没有适用资产返回空列表。manual_asset_ids 是用户保留的绑定，不必强行重复；excluded_asset_ids 不得重新绑定。保持导演台既有构图和动作起点，不改写剧情。'''
        system+='\n程序已将可引用原文整理为 evidence_sources。每条绑定可填写 evidence_source_id（如E1），由程序回填该原句；也可直接填写 evidence 的逐字短引文。usage 必须填写非空文字。编号只能来自本镜提供的列表；不能用资产目录描述作为依据。仅返回严格JSON，字符串内英文双引号必须转义。'
        previous=None;error=None
        with ai.asset_call_policy('frame_assets', metrics, limit=2, max_tokens=4096, timeout=120):
            for attempt in range(2):
                if attempt:report('正在修正本镜资产关联：'+error[:180])
                payload=request_data if not attempt else {'inputs':request_data,'previous':previous,'validation_error':error}
                try:previous=ai.ask(system,json.dumps(payload,ensure_ascii=False))
                except ValueError as failure:
                    if not str(failure).startswith('AI 未返回有效 JSON'):raise
                    error=str(failure);previous=None
                else:
                    try:bindings=validate(previous,data);break
                    except ValueError as failure:error=str(failure)
            else:raise ValueError('首帧资产关联自动纠正后仍未通过：'+error+'；未提交ComfyUI，已有首帧和手动绑定保留，可重试本镜')
    excluded = set(data['excluded_asset_ids']); known = {a['id'] for a in data['asset_catalog']}
    ids = list(dict.fromkeys([x for x in data['manual_asset_ids'] if x in known] + [b['asset_id'] for b in bindings]))
    return {'source_hash': fingerprint(project, shot), 'asset_ids': [x for x in ids if x not in excluded],
            'bindings': [b for b in bindings if b['asset_id'] not in excluded], 'manual_asset_ids': data['manual_asset_ids'],
            'source': 'AI', 'created': time.time()}


def apply(project, shot_id, result):
    shot = next((s for s in project['shots'] if s['id'] == shot_id), None)
    if not shot or fingerprint(project, shot) != result['source_hash']:
        raise store.Conflict('资产关联期间本镜或资产设定已修改，请重新生成首帧；未覆盖用户修改')
    shot['manual_asset_ids'] = copy.deepcopy(result['manual_asset_ids'])
    shot['asset_ids'] = list(result['asset_ids'])
    shot['frame_asset_binding'] = copy.deepcopy(result)


def references(project, shot):
    refs = asset_references.for_shot(project, shot)
    usages = {r['asset_id']: r['usage'] for r in shot.get('frame_asset_binding', {}).get('bindings', [])}
    for ref in refs:
        for asset in project['assets']:
            if asset['id'] in shot.get('asset_ids', []) and asset['id'] in usages and any(r['media'] == ref['media'] for r in asset_references.effective(asset)):
                ref['note'] += '；本镜用途：' + usages[asset['id']]
    return refs


def visual_constraints(project, shot):
    lines = []
    usages = {r['asset_id']: r['usage'] for r in shot.get('frame_asset_binding', {}).get('bindings', [])}
    for asset in project.get('assets', []):
        if asset['id'] not in shot.get('asset_ids', []):
            continue
        features = []
        for group in asset.get('visual_profile', {}).get('groups', {}).values():
            for field in group.get('fields', {}).values():
                if field.get('value') and field.get('source') != 'unknown':
                    features.append(str(field['value']))
        if not features:
            features = [str(asset[k]) for k in ('description', 'age', 'gender', 'costume') if asset.get(k)]
        label = {'character': '角色', 'scene': '场景', 'prop': '道具'}.get(asset.get('kind'), '元素')
        lines.append(f"{label}「{asset['name']}」：{'；'.join(dict.fromkeys(features))}。本镜用途：{usages.get(asset['id'], '用户保留的绑定，请保持其自身身份与外观')}。")
    return '\n'.join(lines)


def render_inputs(project, shot):
    return {'source_hash': fingerprint(project, shot), 'asset_ids': shot.get('asset_ids', []), 'references': references(project, shot)}
