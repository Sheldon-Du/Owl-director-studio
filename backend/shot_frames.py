"""Manage per-shot first-frame candidates without deleting shared media files."""
import copy
import time


def candidates(project, shot):
    result = copy.deepcopy(shot.get('frames', []))
    selected = shot.get('first_frame')
    if selected and not any(m.get('media') == selected for m in result):
        existing = next((m for m in project.get('media', []) if m.get('media') == selected and m.get('kind') == 'image'), None)
        result.insert(0, copy.deepcopy(existing or {'media': selected, 'kind': 'image'}))
    return result


def clear(project, shot):
    shot.pop('first_frame', None)
    shot.pop('first_frame_needs_review',None)
    shot.pop('previous_tail_reference', None)
    if shot.get('h3_reference_mode') in ('first_frame', 'previous_tail'):
        shot['h3_reference_mode'] = 'auto'
    project['confirmed'] = False


def change(project, shot_id, action, media=None):
    shot = next((s for s in project['shots'] if s['id'] == shot_id), None)
    if not shot:
        raise ValueError('镜头不存在')
    link=shot.get('first_frame_link',{})
    if link.get('mode')=='previous_tail' and (action=='clear' or action=='adopt' and media!=link.get('media') or action=='remove' and media==link.get('media')):
        raise ValueError('首帧已固定上一镜尾帧；先在分镜详情切换为独立首帧或更新复用版本')
    if action == 'clear':
        clear(project, shot)
        return
    if action not in ('adopt', 'remove', 'restore') or not media:
        raise ValueError('不支持的首帧操作')
    current = candidates(project, shot)
    candidate = next((m for m in current if m.get('media') == media), None)
    trash = shot.setdefault('frame_trash', [])
    if action == 'restore':
        removed = next((m for m in trash if m.get('media') == media), None)
        if not removed:
            raise ValueError('首帧不在已删除候选中')
        shot['frames'] = current
        if not candidate:
            shot['frames'].append({k: v for k, v in removed.items() if k != 'removed_at'})
        shot['frame_trash'] = [m for m in trash if m.get('media') != media]
        return
    if action == 'adopt':
        if any(m.get('media') == media for m in trash):
            raise ValueError('请先恢复已删除首帧')
        if not candidate:
            candidate = next((m for m in project.get('media', []) if m.get('media') == media and m.get('kind') == 'image'), None)
        if not candidate:
            raise ValueError('图片不属于本项目的首帧或图片素材')
        if not any(m.get('media') == media for m in current):
            current.append(copy.deepcopy(candidate))
        shot['frames'] = current
        shot['first_frame'] = media
        shot.pop('first_frame_needs_review',None)
        shot['h3_reference_mode'] = 'first_frame'
        shot.pop('previous_tail_reference', None)
        project['confirmed'] = False
        return
    if not candidate:
        raise ValueError('首帧候选不存在')
    shot['frames'] = [m for m in current if m.get('media') != media]
    if not any(m.get('media') == media for m in trash):
        trash.append({**candidate, 'removed_at': time.time()})
    if shot.get('first_frame') == media:
        clear(project, shot)
