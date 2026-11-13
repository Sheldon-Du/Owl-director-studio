"""Explicit, persistent video selection, with one adopted version per interval."""
from . import store


def shot(project, sid):
    value=next((s for s in project.get('shots',[]) if s['id']==sid),None)
    if not value:raise ValueError('镜头不存在')
    return value


def interval(output, owner):
    start=float(output.get('source_offset',0))
    return start,start+float(output.get('duration',owner['duration']))


def selected(owner):
    ids=set(owner.get('adopted_video_ids',[]))
    return [m for m in owner.get('outputs',[]) if m.get('id') in ids]


def adopted(project,sid,output_id):
    owner=shot(project,sid)
    output=next((m for m in selected(owner) if m['id']==output_id),None)
    if not output:raise ValueError('请先勾选采用这一版分镜视频，再执行二采放大')
    if output.get('kind')!='video' or not store.media_path(output['media']).is_file():raise ValueError('已采用的视频文件不存在')
    return output


def adopt(project,sid,output_id,enabled=True):
    owner=shot(project,sid)
    output=next((m for m in owner.get('outputs',[]) if m['id']==output_id),None)
    if not output or output.get('kind')!='video':raise ValueError('该视频不属于本镜')
    if enabled and not store.media_path(output['media']).is_file():raise ValueError('视频文件不存在')
    ids=set(owner.get('adopted_video_ids',[]))
    if enabled:
        start,end=interval(output,owner)
        # Long shots have multiple generation tasks. Adopting a version only
        # replaces overlapping intervals, preserving the other adopted parts.
        for other in selected(owner):
            left,right=interval(other,owner)
            if min(end,right)-max(start,left)>1e-6:ids.discard(other['id'])
        ids.add(output_id)
    else:ids.discard(output_id)
    owner['adopted_video_ids']=[m['id'] for m in owner.get('outputs',[]) if m['id'] in ids]
