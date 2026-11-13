"""Editable production relationships, including ungenerated storyboard rows."""
import copy
import json
import math
import time
from . import store, ai, shot_asset_binding as binding, video_versions


def targets(project):
    shots = {s.get('generation_outline_id', s['id']): s for s in project.get('shots', [])}
    result = []; seen = set()
    for outline in project.get('storyboard_generation', {}).get('outlines', []):
        identity = outline['id']; shot = shots.get(identity)
        if not shot:
            prior = project.get('canvas_bindings', {}).get(identity, {})
            shot = {'id': identity, 'generation_outline_id': identity, 'description': outline.get('focus', ''),
                    'prompt': outline.get('source_excerpt', ''), 'actions': [], 'native': {},
                    'asset_ids': prior.get('asset_ids', []), 'manual_asset_ids': prior.get('manual_asset_ids', []),
                    'excluded_asset_ids': prior.get('excluded_asset_ids', []), 'frame_asset_binding': prior.get('result')}
        result.append(shot); seen.add(shot['id'])
    result.extend(s for s in project.get('shots', []) if s['id'] not in seen)
    return result


def target(project, identity):
    shot = next((s for s in targets(project) if s['id'] == identity), None)
    if not shot:
        raise ValueError('分镜或分镜汇总条目不存在')
    return shot


def apply(project, identity, result):
    shot = target(project, identity)
    if binding.fingerprint(project, shot) != result['source_hash']:
        raise store.Conflict('画布关联期间本镜或资产已修改，保留用户连接；请继续关联未完成镜头')
    if any(s['id'] == identity for s in project.get('shots', [])):
        binding.apply(project, identity, result)
    else:
        project.setdefault('canvas_bindings', {})[identity] = {
            'asset_ids': result['asset_ids'], 'manual_asset_ids': result['manual_asset_ids'],
            'excluded_asset_ids': shot.get('excluded_asset_ids', []), 'result': copy.deepcopy(result)}


def inherit(project, shot):
    """Keep placeholder relationships when the real shot is first generated."""
    prior = project.get('canvas_bindings', {}).get(shot.get('generation_outline_id'))
    if prior:
        known = {a['id'] for a in project.get('assets', [])}
        for key in ('asset_ids', 'manual_asset_ids', 'excluded_asset_ids'):
            shot[key] = [identity for identity in prior.get(key, []) if identity in known]


def reference(project, identity, asset_id, enabled, previous=None):
    if not any(a['id'] == asset_id for a in project.get('assets', [])):
        raise ValueError('资产元素不存在')
    owner = target(project, identity)
    prior_owner = target(project, previous) if previous and previous != identity else None
    def change(shot, bound):
        ids = list(shot.get('asset_ids', [])); manual = list(shot.get('manual_asset_ids', ids)); excluded = list(shot.get('excluded_asset_ids', []))
        shot['asset_ids'] = list(dict.fromkeys(ids + [asset_id])) if bound else [x for x in ids if x != asset_id]
        shot['manual_asset_ids'] = list(dict.fromkeys(manual + [asset_id])) if bound else [x for x in manual if x != asset_id]
        shot['excluded_asset_ids'] = [x for x in excluded if x != asset_id] if bound else list(dict.fromkeys(excluded + [asset_id]))
        if not any(s['id'] == shot['id'] for s in project.get('shots', [])):
            project.setdefault('canvas_bindings', {})[shot['id']] = {k: copy.deepcopy(shot[k]) for k in ('asset_ids', 'manual_asset_ids', 'excluded_asset_ids')}
    if prior_owner:
        change(prior_owner, False)
    change(owner, enabled)
    project['confirmed'] = False


def layout(project, value):
    if not isinstance(value, dict) or not isinstance(value.get('nodes'), dict) or len(value['nodes']) > 5000:
        raise ValueError('画布布局格式无效')
    nodes = {}
    for key, point in value['nodes'].items():
        if not isinstance(key, str) or len(key) > 160 or not isinstance(point, dict):
            raise ValueError('画布节点位置无效')
        coordinates = {}
        for axis in ('x', 'y'):
            number = point.get(axis)
            if isinstance(number, bool) or not isinstance(number, (float, int)) or not math.isfinite(number) or not -10000 <= number <= 100000:
                raise ValueError('画布节点位置超出范围')
            coordinates[axis] = round(number, 2)
        nodes[key] = coordinates
    project['canvas_layout'] = {'nodes': nodes, 'updated': time.time(), 'lane_version':2}


def associate(project, report=None, on_event=None, metrics=None):
    report = report or (lambda message: None); on_event = on_event or (lambda event: None)
    rows = targets(project)
    if not rows:
        raise ValueError('请先生成分镜汇总，再由 AI 连接资产关系')
    if not project.get('assets'):
        raise ValueError('请先提取或创建资产元素')
    results = []; pending = []
    for shot in rows:
        cached = binding.cached(project, shot)
        if cached:
            results.append({'shot_id': shot['id'], 'result': cached}); continue
        pending.append(shot)
    reused = len(results)
    for offset in range(0, len(pending), 6):
        group = pending[offset:offset + 6]
        report(f'AI 正在关联分镜 {offset+1}–{offset+len(group)}/{len(pending)}；已复用 {reused} 镜')
        data_by_id = {s['id']: binding.inputs(project, s) for s in group}
        catalog = [{k: (v[:1200] if isinstance(v, str) else v) for k, v in a.items() if k != 'visual_profile'} for a in next(iter(data_by_id.values()))['asset_catalog']]
        payload = {'asset_catalog': catalog, 'shots': [{'shot_id': sid, **{k: v for k, v in data.items() if k not in ('asset_catalog', 'script_hash')}} for sid, data in data_by_id.items()]}
        system = '''你是导演台制作画布的资产关联助手。只输出 JSON {"shots":[{"shot_id":"给定镜头ID","bindings":[{"asset_id":"资产目录ID","evidence":"逐字摘录本镜描述、提示词或剧本上下文","usage":"本镜实际可见元素的位置、用途和保持一致的特征"}]}]}。
每个指定镜头恰好返回一次，可返回空 bindings。按本镜真实空间、出镜人物和可见物件匹配资产；不能合并不同地点，不能把他人的发色衣着归给主角。明确首帧时依据首帧可见元素；未生成镜头时依据分镜汇总和对应剧本。只在对白中被提及而不出镜的元素不要连入。manual_asset_ids 是用户保留，excluded_asset_ids 不得重新连入。依据必须逐字来自本镜而非资产目录。只建立参考关系，不改写剧情、时序或造型。'''
        def validate(answer):
            items = answer.get('shots') if isinstance(answer, dict) else None
            if not isinstance(items, list) or len(items) != len(group):
                raise ValueError('AI 必须返回本组全部镜头的关联')
            parsed = {}; known = set(data_by_id)
            for item in items:
                if not isinstance(item, dict) or item.get('shot_id') not in known or item['shot_id'] in parsed:
                    raise ValueError('AI 返回了未知或重复的镜头ID')
                sid = item['shot_id']; parsed[sid] = binding.validate(item, data_by_id[sid])
            return parsed
        with ai.asset_call_policy('canvas_links', metrics, limit=2, max_tokens=4096, timeout=180):
            answer = ai.ask(system, json.dumps(payload, ensure_ascii=False))
            try:
                parsed = validate(answer)
            except ValueError as error:
                report('正在修正本组镜头ID或资产原文依据')
                answer = ai.ask(system, json.dumps({'inputs': payload, 'previous': answer, 'validation_error': str(error)}, ensure_ascii=False))
                parsed = validate(answer)
        for shot in group:
            sid = shot['id']; data = data_by_id[sid]; excluded = set(data['excluded_asset_ids']); known = {a['id'] for a in catalog}
            ids = list(dict.fromkeys([x for x in data['manual_asset_ids'] if x in known] + [b['asset_id'] for b in parsed[sid]]))
            result = {'source_hash': binding.fingerprint(project, shot), 'asset_ids': [x for x in ids if x not in excluded],
                      'bindings': [b for b in parsed[sid] if b['asset_id'] not in excluded], 'manual_asset_ids': data['manual_asset_ids'], 'source': 'AI', 'created': time.time()}
            item = {'shot_id': sid, 'result': result}; results.append(item)
            on_event({'type': 'canvas_binding', **item, 'completed': len(results), 'total': len(rows), 'reused': reused})
    return {'rows': results, 'total': len(rows), 'reused': reused}


def assemble(project):
    clips = []; total = 0; fixed = project.get('media_brief', {}).get('mode') == 'fixed_audio'
    ordered = targets(project)
    real_ids = {s['id'] for s in project.get('shots', [])}
    if any(s['id'] not in real_ids for s in ordered):
        raise ValueError('还有未生成的分镜占位框，请完成并采用这些镜头后再组装完整时间线')
    if project.get('storyboard_generation', {}).get('status') == 'stale':
        raise ValueError('分镜汇总已过期，请确认当前分镜顺序后再组装')
    for shot in ordered:
        selected = sorted(video_versions.selected(shot), key=lambda m: video_versions.interval(m, shot)[0]); covered = 0
        if not selected:
            raise ValueError(f'第 {len({c["shot_id"] for c in clips})+1} 镜尚未采用视频，请先选择最终版本')
        for output in selected:
            if output.get('stale') or not store.media_path(output['media']).is_file():
                raise ValueError('已采用视频过期或文件不存在，请重新选择')
            left, right = video_versions.interval(output, shot)
            if abs(left - covered) > .05:
                raise ValueError('已采用视频存在空缺或重叠，请补齐该镜头各段')
            covered = right
            clips.append({'id': store.uid(), 'shot_id': shot['id'], 'output_id': output['id'], 'media': output['media'], 'kind': 'video',
                          'in': float(output.get('in', 0)), 'duration': right-left, 'start': 0, 'volume': 0 if fixed else 1})
        if abs(covered-float(shot['duration'])) > .05:
            raise ValueError('已采用视频未完整覆盖该镜头')
        total += covered
    if not clips:
        raise ValueError('尚无已采用分镜视频')
    audio = copy.deepcopy([c for c in project.get('timeline', []) if c['kind'] == 'audio'])
    if fixed:
        source = project['media_brief']['source']
        if abs(float(source['duration']) - total) > .1:
            raise ValueError('分镜时长与固定音频不一致，请先修正自然时序')
        if not any(c['media'] == source['media'] for c in audio):
            audio.append({'id': store.uid(), 'media': source['media'], 'kind': 'audio', 'in': 0, 'duration': source['duration'], 'start': 0, 'volume': 1})
    project.setdefault('timeline_history', []).append({'created': time.time(), 'timeline': copy.deepcopy(project.get('timeline', []))})
    project['timeline'] = clips + audio
