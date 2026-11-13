"""Separate story authorship from visual prompt instructions."""
import hashlib
import json
from . import site_skills

WRITING={'screenplay-methods','world-continuity','beat-diagnostic','character-arc','information-reveal','dialogue-polish'}
GENRE={'design-half-narrated-2d-short-drama','design-half-narrated-3d-short-drama','design-half-narrated-live-action-short-drama','design-pov-short-film-generator','design-sitcom-story-video','design-wes-anderson-style-short-film-generator','design-chinese-traditional-animation-shortfilm','design-wool-felt-story-short','design-3d-animation-short-generator'}
TOOLS={'design-skill-creator','design-astra-prompt-optimizer','design-touchdesigner-workflow','design-podcast-studio','design-short-drama-multilingual-dubbing'}
TOOLS.update({'design-blender-workflow','design-blender-product-film','design-deepwhite-blender-previs','design-design-after-effects','design-design-photoshop','design-houdini-workflow','design-interior-modeling-render','design-video-highlight-edit','design-voice-clone','design-video-deconstruct','design-shot-by-shot-study'})
IMAGES={'design-character-identity-asset-studio','design-neoimage-prompt-engine-public','design-material-propagation-poster','design-logo-creative-material-motion-lab'}
IMAGES.update({'design-cultural-pattern-visual-system-generator','design-ecommerce-visual-creator'})

def usage(item):
    if item.get('usage') in ('writing','video','image','tools'):return item['usage']
    sid=item['id']
    if sid in WRITING:return 'writing'
    if sid in GENRE:return 'genre'
    if sid in TOOLS:return 'tools'
    if sid in IMAGES:return 'image'
    if sid.startswith('design-'):return 'video' # Existing imported adapters only; new installations require explicit usage.
    if 'script' in item.get('stages',[]) or 'script_plan' in item.get('stages',[]):return 'writing'
    return 'tools'

def selection(project):
    value=project.get('prompt_skills',{'ids':[]})
    if not isinstance(value,dict) or set(value)-{'ids'}:raise ValueError('视频提示词技能设置无效')
    ids=value.get('ids',[])
    if not isinstance(ids,list) or len(ids)>3 or any(not isinstance(s,str) for s in ids) or len(set(ids))!=len(ids):raise ValueError('视频提示词最多选择3个不重复技能')
    available=site_skills.locations()
    for sid in ids:
        if sid not in available or usage(available[sid]) not in ('video','genre'):raise ValueError('请选择视频提示词或题材风格技能：'+sid)
        if not site_skills.flags().get(sid,True):raise ValueError('视频提示词技能已停用：'+sid)
    return ids

def prompt_rules(project):
    from .agent import TOOLS as tool_names
    result=[]
    for sid in selection(project):
        item=site_skills.locations()[sid];loaded=site_skills.load(sid,tool_names)
        # Prompt authoring does not run any external workflow declared by a skill.
        text=loaded['instructions'][:2500]
        text+='\n'+str(loaded['references'].get('references/original.md',''))[:6500]
        result.append({'id':sid,'name':item['name'],'version':item['version'],'digest':hashlib.sha256(json.dumps([item['text'],loaded['references']],ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'rules':text,
                       'scope':'仅抽取适合本镜的摄影、构图、表演、视觉与声音规则；不执行原技能完整工作流，不改变已确认剧情、资产身份、自然时长或H3格式。','execution_gaps':item['execution_gaps']})
    return result


def image_rules(asset):
    ids=asset.get('image_skill_ids',[])
    if not isinstance(ids,list) or len(ids)>3 or any(not isinstance(s,str) for s in ids) or len(set(ids))!=len(ids):raise ValueError('图片提示词最多选择3个不重复技能')
    from .agent import TOOLS as tool_names
    result=[]
    for sid in ids:
        item=site_skills.locations().get(sid)
        if not item or usage(item)!='image':raise ValueError('请选择图片资产技能：'+sid)
        loaded=site_skills.load(sid,tool_names)
        result.append({'id':sid,'version':item['version'],'rules':loaded['instructions'][:2500]+'\n'+str(loaded['references'].get('references/original.md',''))[:6500],'scope':'只影响当前独立资产图片表达；不改变剧本、角色身份、时代与已确认外观。模型基础格式与人工明确要求优先。'})
    return result
