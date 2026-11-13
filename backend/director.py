"""Invoke the original DirectorMaster package. No copied prompt engine."""
import importlib.util
import json
import os
import re
import sys
import threading
from pathlib import Path
from . import endpoints, screenplay_expression

DM_PATH = Path(os.environ.get('DIRECTORMASTER_PATH', r'D:\2video\ComfyUI_Mie_2026_V9.0_Large\ComfyUI\custom_nodes\ComfyUI-DirectorMaster'))
LOCK = threading.RLock()
_package = None


def package():
    global _package
    with LOCK:
        if _package is None:
            if not (DM_PATH / '__init__.py').exists():
                raise RuntimeError('DirectorMaster 原始目录不存在')
            spec = importlib.util.spec_from_file_location('studio_directormaster', DM_PATH / '__init__.py', submodule_search_locations=[str(DM_PATH)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            _package = module
    return _package


def definitions(name):
    cls = package().NODE_CLASS_MAPPINGS[name]
    result = {}
    for group, fields in cls.INPUT_TYPES().items():
        if group not in ('required','optional'):
            continue
        for key, field in fields.items():
            kind = field[0]
            meta = field[1] if len(field)>1 and isinstance(field[1],dict) else {}
            default = meta.get('default',kind[0] if isinstance(kind,list) and kind else '' if kind=='STRING' else False if kind=='BOOLEAN' else 0)
            if isinstance(kind,str) and kind in ('IMAGE','VIDEO','AUDIO'):
                continue
            result[key] = {'type':'select' if isinstance(kind,list) else kind,'options':kind if isinstance(kind,list) else [],'default':default,'required':group=='required','tooltip':meta.get('tooltip',''),**{k:meta[k] for k in ('min','max','step','multiline') if k in meta}}
    return result


def invoke(name, inputs):
    with LOCK:
        cls = package().NODE_CLASS_MAPPINGS.get(name)
        if cls is None:
            raise RuntimeError('DirectorMaster 节点不可用：'+name)
        fields = definitions(name)
        values = {k:v['default'] for k,v in fields.items()}
        values.update({k:v for k,v in inputs.items() if k in fields})
        for key,field in fields.items():
            if field['options'] and values[key] not in field['options']:
                raise ValueError(f'DirectorMaster 参数 {key} 不在原生枚举中：{values[key]}')
        result = getattr(cls(),cls.FUNCTION)(**values)
        if isinstance(result,tuple) and len(result)==2 and isinstance(result[0],tuple) and isinstance(result[1],dict):
            result = result[0]
        return dict(zip(cls.RETURN_NAMES,result)), values


def catalog():
    mod = package()
    return {'version':getattr(mod,'__version__','unknown'),'nodes':list(mod.NODE_CLASS_MAPPINGS),'core':definitions('DirectorMasterCore'),'script':definitions('DirectorMasterScript'),'cinematic':definitions('DirectorMasterCinematic'),'art':definitions('DirectorMasterArt'),'production':production_schema(),'professional':professional_schema()}

def professional_schema():
    """Complete native authoring controls; transport stays in studio settings."""
    hidden={'AI接口地址','AI密钥','AI模型名'}
    result={'script':{},'cinematic':{},'art':{}}
    for group,node in (('core','DirectorMasterCore'),('script','DirectorMasterScript')):
        for key,spec in definitions(node).items():
            if key not in hidden:result['script'][group+'::'+key]={**spec,'label':key,'group':group,'native_node':node}
    for group,node in (('cinematic','DirectorMasterCinematic'),('art','DirectorMasterArt')):
        result[group]={key:{**spec,'label':key,'group':group,'native_node':node} for key,spec in definitions(node).items() if key not in hidden}
    return result


def production_schema():
    keep={'cinematic':('画面模式','景别偏好','运镜风格','焦段偏好','构图法则','剪辑节奏','运镜风格_多选','节奏风格','直觉风险','复杂叙事结构','叙事编排','叙事线型','AIGC生产模式','卖点清单'),
          'art':('美术模式','启用反AI规则','色彩风格','光影方向','材质重点','构图法则','摄影风格','色彩风格_多选')}
    return {section:{k:v for k,v in definitions('DirectorMasterCinematic' if section=='cinematic' else 'DirectorMasterArt').items() if k in keys} for section,keys in keep.items()}


def validate_scheme(scheme):
    schemas=production_schema()
    if not isinstance(scheme,dict):raise ValueError('镜头与美术方案必须为参数对象')
    for section,params in scheme.items():
        if section not in schemas or not isinstance(params,dict):raise ValueError('方案包含未知参数区')
        for key,value in params.items():
            field=schemas[section].get(key)
            if not field:raise ValueError('方案包含未知原生参数：'+key)
            if field['options'] and value not in field['options']:raise ValueError('方案参数不在 DirectorMaster 原生枚举中：'+key)
            if field['type']=='BOOLEAN' and not isinstance(value,bool):raise ValueError('方案开关必须为布尔值：'+key)
            if field['type']=='STRING' and not isinstance(value,str):raise ValueError('方案参数必须为文字：'+key)
            if any(word in str(value) for word in ('慢镜','慢放','子弹时间','延时摄影','倍速')):raise ValueError('自然动作时序不允许通过慢放或倍速改变动作：'+key)
    return scheme


def core_project(project,config):
    from . import story_promo
    project=story_promo.for_writing(project)
    values=dict(project.get('parameters',{}))
    values.update({'项目名':project['name'],'场景描述':project['story'],'随机种子':42,'AI接口地址':endpoints.chat_url(config.get('ai_url','')),'AI密钥':config.get('ai_key',''),'AI模型名':config.get('ai_model','')})
    result,_=invoke('DirectorMasterCore',values)
    return result


def script(project,config,progress=None,plan_only=False,approved_plan=None,on_event=None,metrics=None,force=False):
    from . import story_promo
    project=story_promo.for_writing(project)
    from . import script_workflows
    project=script_workflows.director_only(project)
    report=progress or (lambda message:None)
    report('正在执行导演核心规则')
    # Run the original rule engine locally. Its optional AI enhancement also
    # rewrites story material, so only the selected creative policy may invoke
    # the text model below. This avoids an unused, slow rewrite in faithful mode.
    core=core_project(project,{**config,'ai_url':'','ai_key':'','ai_model':''})
    report('正在生成原生剧本')
    result,_=invoke('DirectorMasterScript',{'核心数据包':core['核心数据包'],'剧本模式':project.get('script_mode','情感共鸣短视频'),'目标时长(分钟)':float(project['duration'])/60})
    from . import story_writing
    report('正在按'+{'faithful':'原文直用','screenplay':'忠于故事剧本化','creative':'AI创意编排'}.get(project.get('story_policy','faithful'),'原文直用')+'模式整理剧本')
    return {'core_pack':safe_pack(core['核心数据包']),'core_prompt':core['统一电影提示词'],'native_script_reference':result['剧本'],**story_writing.write(project,core,result['剧本'],progress=report,plan_only=plan_only,approved_plan=approved_plan,on_event=on_event,metrics=metrics,force=force),'engine_version':getattr(package(),'__version__','unknown')}


def storyboard(project,config,progress=None):
    from . import script_workflows
    from . import story_promo
    project=story_promo.for_storyboard(project)
    if not project.get('documents',{}).get('script'):
        raise ValueError('请先填写故事或有效剧本')
    scheme=validate_scheme(project.get('production_scheme',{}))
    if not scheme.get('cinematic') or not scheme.get('art'):raise ValueError('请先推荐或填写镜头与美术方案')
    report=progress or (lambda message:None)
    report('正在执行原生美术指导与空间规则')
    core=core_project(project,config);pack=core['核心数据包']
    art,_=invoke('DirectorMasterArt',{**scheme['art'],'核心数据包':pack})
    report('正在依据已确认剧本与方案生成原生分镜')
    output,_=invoke('DirectorMasterCinematic',{**scheme['cinematic'],'核心数据包':pack,'剧本输入':script_workflows.storyboard_input(project),'美术输入':art['美术'],'目标时长(分钟)':float(project['duration'])/60})
    result={**checked_storyboard(pack,core['统一电影提示词'],project['documents']['script'],output,report,art['美术']),**{k:project['documents'][k] for k in (*screenplay_expression.DOC_KEYS,'script_policy','script_changes','script_policy_note','script_adaptation_map','script_director_notes','script_input_hash','script_consistency',*script_workflows.DOC_KEYS) if k in project['documents']}}
    if project.get('_production_source_kind')=='story':result.pop('script',None)
    else:result['script']=story_promo.full_script(project)
    return result


def checked_storyboard(pack,core_prompt,script_text,shots,report,art=''):
    report('正在执行分镜契约与原生审查')
    from aggregator.storyboard_contract import parse_storyboard_json,validate_storyboard
    data,warnings=parse_storyboard_json(shots['分镜JSON'])
    validation=validate_storyboard(data)
    if not validation['ok']:raise ValueError('DirectorMaster 分镜契约校验失败：'+json.dumps(validation['errors'],ensure_ascii=False))
    from aggregator.review_engine import review_artifacts
    from .store import DATA
    reviewed=review_artifacts(artifact_text=shots['分镜JSON'],brief=json.loads(pack),mode='全量审查',checkpoint_dir=str(DATA/'director-checkpoints'))
    return {'core_pack':safe_pack(pack),'core_prompt':core_prompt,'script':script_text,'art':art,'storyboard_native':data,'review':{'审查报告':reviewed['report'],'审查JSON':json.dumps(reviewed,ensure_ascii=False)},'validation':{'ok':True,'warnings':validation['warnings']+warnings},'engine_version':getattr(package(),'__version__','unknown')}


def safe_pack(text):
    body = json.loads(text)
    for key in list(body):
        if '密钥' in key or 'key' in key.lower():
            body[key] = ''
    return json.dumps(body,ensure_ascii=False)


def plan(project, config, progress=None):
    from . import story_promo
    project=story_promo.for_writing(project)
    report=progress or (lambda message:None)
    report('正在执行导演核心规则')
    values = dict(project.get('parameters',{}))
    values.update({'项目名':project['name'],'场景描述':project['story'],'随机种子':42,'AI接口地址':endpoints.chat_url(config.get('ai_url','')),'AI密钥':config.get('ai_key',''),'AI模型名':config.get('ai_model','')})
    core, _ = invoke('DirectorMasterCore',values)
    pack = core['核心数据包']
    minutes = float(project.get('duration',30)) / 60
    report('正在生成原生剧本')
    script,_ = invoke('DirectorMasterScript',{'核心数据包':pack,'剧本模式':project.get('script_mode','情感共鸣短视频'),'目标时长(分钟)':minutes})
    from . import story_writing,script_workflows
    written=story_writing.write(project,core,script['剧本'])
    report('正在生成原生分镜')
    shots,_ = invoke('DirectorMasterCinematic',{'核心数据包':pack,'剧本输入':script_workflows.storyboard_input({**project,'documents':written}),'画面模式':project.get('cinematic_mode','电影工作室'),'目标时长(分钟)':minutes})
    return {**checked_storyboard(pack,core['统一电影提示词'],written['script'],shots,report),**written}


def asset_prompt(project, asset):
    from . import character_profiles
    if asset['kind']=='character' and character_profiles.narrative_description(asset.get('description','')):raise ValueError('角色出图前请先提取独立的外貌、衣着与性格档案')
    mode = {'character':'角色设定','scene':'环境设定','prop':'服化道设定'}[asset['kind']]
    refs = asset.get('references',[])
    reference_text = '\n'.join(f"@图片{i+1} {r.get('role','identity')}: {r.get('note','')}" for i,r in enumerate(refs))
    from .store import media_path
    params = {'项目名':project['name'],'核心数据包':project.get('documents',{}).get('core_pack',''),'节点模式':mode,'角色名':asset['name'],'角色外貌':asset['description'],'环境描述':asset['description'],'服化道描述':asset['description'],'角色年龄':asset.get('age') or '未指定','角色性别':asset.get('gender') or '不限','角色性格':asset.get('personality') or '依据当前元素档案，不增加未指定设定','角色服装':asset.get('costume') or '依据描述与参考图，不增加未指定服装细节','参考图路径':','.join(str(media_path(r['media'])) for r in refs)}
    if asset['kind'] in ('character','scene','prop'):
        # Native rules still run, but the whole-story pack cannot inject another
        # person's identity or turn a life event into a character-card scene.
        params['核心数据包']=''
        if params['角色性别'] not in definitions('DirectorMasterCharacters')['角色性别']['options']:params['角色性别']='不限'
    result,_ = invoke('DirectorMasterCharacters',params)
    native=result['完整资产']
    production=re.search(r'生成提示词\s*[:：]\s*(.+)',native)
    prompt=production.group(1) if production else f"{asset['name']}。{asset['description']}\n{native}"
    # Extract native visual constraints only, excluding workflow instructions.
    visual=[]
    for key in ('光','色彩','构图'):
        match=re.search(r'^\s*'+key+r'\s*[:：]\s*(.+)$',native,re.M)
        if match:visual.append(key+'：'+match.group(1))
    if visual:prompt+='\n'+'；'.join(visual)
    if reference_text:
        prompt += '\n参考绑定（按槽位顺序）：\n'+reference_text
    return prompt,result


def validate_native(data):
    package()
    from aggregator.storyboard_contract import validate_storyboard
    return validate_storyboard(data)


def validate_project_shots(project):
    """Re-run the original contract after editable shot changes."""
    import copy
    data=copy.deepcopy(project.get('documents',{}).get('storyboard_native',{}))
    rows=[]
    for index,shot in enumerate(project.get('shots',[])):
        row=copy.deepcopy(shot.get('native',{}))
        # Rebuild the sequential timeline; old derived timestamps are stale.
        for key in ('start','end','start_s','end_s','duration_s'):
            row.pop(key,None)
        row.update({'镜号':index+1,'时长':shot['duration'],'AIGC提示词':shot.get('prompt','')})
        if 'AIGC适配提示词' in row:
            row['AIGC适配提示词']=shot.get('prompt','')
        rows.append(row)
    data.update({'分镜表':rows,'分镜数':len(rows),'总时长秒':sum(s['duration'] for s in project.get('shots',[]))})
    checked=validate_native(data)
    if not checked['ok']:
        raise ValueError('DirectorMaster 原生分镜校验失败：'+json.dumps(checked['errors'],ensure_ascii=False))
    return checked
