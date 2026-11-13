"""Display metadata retained after task snapshots are discarded."""
import math

IMAGE_MODELS={'qwen-image-2.1':'Image2.1（Qwen）','z-image':'Krea2 备用文生图','krea2':'Krea2 备用文生图'}
DISPLAY_OPTIONS=('seed','resolution','upscale_factor','temporal_chunks','spatial_chunks',
                 'output_width','output_height','format')


def describe(task,settings=None):
    project=task.get('snapshot') or {}
    kind=task.get('kind');target=task.get('target');options=task.get('options') or {}
    result={'project_name':project.get('name') or task.get('project_name',''),
            'target_label':('目标 '+str(target)[:12]) if target else '全项目'}
    mode=options.get('mode',kind if kind in ('frame','keyframe','tail') else None)
    if mode in ('frame','keyframe','tail'):result['frame_mode']=mode
    asset=next((a for a in project.get('assets',[]) if a.get('id')==target),None) if target else None
    shot_target=options.get('scope_shot') or target
    shots=project.get('shots',[])
    shot=next((s for s in shots if s.get('id')==shot_target),None) if shot_target else None
    outlines=project.get('storyboard_generation',{}).get('outlines',[])
    outline=next((s for s in outlines if s.get('id')==target),None) if target else None
    if asset:
        result['target_label']={'character':'角色','scene':'场景','prop':'道具'}.get(asset.get('kind'),'元素')+' · '+str(asset.get('name',''))
        result['image_model_label']=IMAGE_MODELS.get(asset.get('model'),asset.get('model','图片工作流'))
    elif shot:
        result['target_label']=f'第{shots.index(shot)+1}镜'+(' · '+str(shot.get('description',''))[:100] if shot.get('description') else '')
        result['planned_seconds']=shot.get('duration')
        if kind in ('h3_generate','h3_upscale'):result['target_label']+=' · H3 第'+str(target)+'步'
    elif outline:
        result['target_label']=f'第{outline.get("index") or outlines.index(outline)+1}镜 · '+str(outline.get('focus',''))[:100]
        result['planned_seconds']=outline.get('natural_seconds')
    elif kind=='story_promo':
        mode=project.get('story_promo',{}).get('settings',{}).get('mode')
        labels={'rules':'生成两步通用编辑规则','novel':'第一步 · 通用内容整理','video':'第二步 · 通用视觉编排','both':'内容整理 → 视频画面化'} if mode=='other' else {'novel':'第一步 · 科普讲解整理','video':'第二步 · 科普画面化','both':'科普整理 → 科普画面化'} if mode=='science' else {'novel':'第一步 · 小说推文整理','video':'第二步 · 视频推文优化','both':'小说整理 → 视频推文'}
        result['target_label']=labels.get(options.get('stage'),'推文预处理')
    elif kind=='medical_ocr':
        source=next((s for s in project.get('medical_director',{}).get('sources',[]) if s['id']==target),{})
        result['target_label']='本地 OCR · '+source.get('name','PDF')
    elif kind=='medical_director':
        from . import medical_director
        result['target_label']=medical_director.LABELS.get(options.get('stage'),'医学视频导演')
    elif kind=='authoring_run':result['target_label']='六步自动创作'
    elif kind=='script':result['target_label']='整部剧本'
    elif kind=='storyboard_outline':result['target_label']='全片分镜汇总'
    elif kind in ('storyboard','storyboard_timing'):result['target_label']='全片分镜'
    elif kind=='asset_explore':result['target_label']='额外角色、场景与道具候选'
    elif kind=='script_assets':result['target_label']='全片角色、场景与道具'
    elif kind=='h3':result['target_label']='全片 H3 提示词'
    elif kind in ('h3_generate','h3_upscale'):
        result['target_label']='H3 第'+str(target or '待定')+'步'
    elif kind=='performance_plan':result['engine_label']='文本 AI · 单次对白、动作与镜头编排'
    elif kind=='canvas_links':result['target_label']='全片资产与分镜关系'
    if options.get('effective_image_model'):
        result['image_model_label']=IMAGE_MODELS.get(options['effective_image_model'],options['effective_image_model'])
    if kind in ('preview','character_card'):result['engine_label']='ComfyUI · '+result.get('image_model_label','图片工作流')+(' · 5S 直接生图' if kind=='preview' and asset and asset.get('card') else '')
    elif kind in ('frame','keyframe','tail'):result['engine_label']='ComfyUI · Image2.1（Qwen）'
    elif kind=='frame_layout':result['engine_label']='MiniMax 文本模型 → 白模 SVG / PNG'
    elif kind in ('h3_generate','h3_upscale'):result['engine_label']='ComfyUI · 高质量数字人-minimaxh3-自行生成声音'
    elif kind=='audio' and (options.get('tts_engine')=='yovoice' or options.get('yovoice_timing')):
        result['engine_label']='yovoice CLI · '+options.get('yovoice_model','逐句配音测时')
        result['target_label']=options.get('voice_role','旁白')+' · 配音与旁白'
    elif kind=='audio' and options.get('tts_engine')=='owl-qwen3':
        result['engine_label']='ComfyUI · Qwen3-TTS · '+{'preset':'预设音色','design':'设计并保存音色','clone':'克隆并保存音色','silence':'纯静音','saved':'复用已保存音色'}.get(options.get('voice_mode'),'配音')
        result['target_label']=options.get('voice_role','旁白')+' · 配音与旁白'
    elif kind=='audio' and options.get('tts_engine')=='owl-speech-timing':
        result['engine_label']='ComfyUI · Qwen3-TTS · 分镜人声实测'
        result['target_label']='分镜对白与旁白 · 实测时长'
    elif kind in ('generate','audio'):result['engine_label']='ComfyUI · 已配置'+('视频' if kind=='generate' else '音频')+'工作流'
    elif kind=='character_mod':result['engine_label']='ComfyUI · 角色八视图 → RefMod'
    elif kind=='music_generate':result['engine_label']='ComfyUI · MiniMax Music 3 纯音乐'
    elif kind=='export':result['engine_label']='本地导出'
    else:result['engine_label']='文本 AI'+(' · '+str(settings.get('ai_model')) if settings and settings.get('ai_model') else '')
    return result


def public(task):
    # Never send the screenplay snapshot or raw options (prompts/reference
    # bindings and provider settings) in the global queue response.
    result={k:v for k,v in task.items() if k not in ('snapshot','options','layout_result')}
    if not task.get('target_label'):result.update(describe(task))
    options=task.get('options') or {}
    safe={k:options[k] for k in DISPLAY_OPTIONS
          if isinstance(options.get(k),(str,int,float)) and not isinstance(options.get(k),bool)}
    if safe:result['generation_details']=safe
    duration=options.get('h3_step',{}).get('duration')
    if isinstance(duration,(int,float)) and not isinstance(duration,bool) and math.isfinite(duration) and duration>0:
        result['planned_seconds']=duration
    return result
