"""Bind actual adopted frame pixels for composition continuity, without circular refs."""
import copy
from . import store,speech_audio

def anchor(project,shot,mode):
    if shot.get('frame_continuity')=='independent':return None
    if mode in ('keyframe','tail'):
        media=shot.get('first_frame')
        if not media:raise ValueError('请先采用本镜首帧，关键帧和尾帧将自动沿用其构图；需要重新构图时，在帧详情选择“独立构图”。')
        role='same_shot';note='沿用本镜首帧的机位、透视、主体相对大小、站位和光线，仅按当前5S推进动作和道具状态；不重复起始动作。'
    else:
        index=project['shots'].index(shot)
        if not index:return None
        prior=project['shots'][index-1]
        if not set(prior.get('asset_ids',[]))&set(shot.get('asset_ids',[])):return None
        media=prior.get('adopted_tailframe') or prior.get('first_frame')
        if not media:return None
        role='adjacent_shot';note='沿用上一镜场景空间、人物与道具的世界位置、朝向、屏幕方向和光源。按本镜景别重新取景；不能把人物画面占比强行复制到不同景别，也不能把上一镜后续动作提前到本镜。'
    if not store.media_path(media).is_file():raise ValueError('构图锚点图片文件缺失，请重新采用首帧／上一镜尾帧')
    return {'media':media,'role':role,'note':note}

def bind(project,shot,mode,plan):
    result=copy.deepcopy(plan);ref=anchor(project,shot,mode)
    if not ref:return result
    references=result['references'];existing=next((i for i,r in enumerate(references) if r['media']==ref['media']),None)
    if existing is None:
        if len(references)>=16:raise ValueError('加上构图锚点后超过16张参考，请减少资产图片')
        if len(references)==1:result['prompt']=result['prompt'].replace('图像','<image1>')
        references.append({**ref,'source':'composition_anchor'});existing=len(references)-1
    tag='图像' if len(references)==1 else f'<image{existing+1}>'
    result['prompt']+=' '+tag+'仅作构图连续性参考：'+ref['note']
    result['prompt_zh']=result['prompt'];result['continuity_anchor']=ref
    result['continuity_hash']=speech_audio.digest(ref)
    return result

def check(project,shot,mode,plan):
    if plan.get('continuity_hash') and speech_audio.digest(anchor(project,shot,mode))!=plan['continuity_hash']:raise store.Conflict('等待期间构图锚点已更换，请重新提交当前帧生成')
