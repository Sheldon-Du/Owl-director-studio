"""Appearance archives for scenes and props, with character identity safeguards."""
import copy
import json
from . import character_profiles as cp, visual_schema as vs, script_source,scene_identity


def preserve_user_fields(profile,asset):
    if asset['kind']=='character':return cp.preserve_user_fields(profile,asset)
    if not isinstance(profile,dict):return profile
    proposed=copy.deepcopy(profile);kind=asset['kind'];stored=asset.get('visual_profile') or {}
    for path,item in vs.flatten(kind,proposed).items():
        if item.get('source')=='user':
            group,key=path.split('.');proposed['groups'][group]['fields'][key]['source']='suggested'
    for path,item in vs.flatten(kind,stored).items():
        if item.get('source')=='user':
            group,key=path.split('.');proposed.setdefault('groups',{}).setdefault(group,{}).setdefault('fields',{})[key]={**copy.deepcopy(item),'owner':asset['name']}
    summary=stored.get('user_summary')
    if not stored and asset.get('description') and asset.get('visual_description_source') not in ('analysis','script'):summary=asset['description']
    if summary:proposed['user_summary']=summary
    return proposed


def normalize(profile,project,asset,others=()):
    if asset['kind']=='character':return cp.normalize(profile,project,asset,others)
    if asset['kind']=='scene':scene_identity.single_name(asset['name'])
    if not isinstance(profile,dict) or not isinstance(profile.get('groups'),dict):raise ValueError('元素外观档案缺少分类字段')
    kind=asset['kind'];fields={};story=script_source.asset_text(project,False)
    entries=vs.flatten(kind,profile)
    for path,label in vs.labels(kind).items():
        item=entries[path]
        if not isinstance(item,dict):raise ValueError('外观字段必须标明来源：'+label)
        value=str(item.get('value','')).strip();source=item.get('source','unknown');quote=str(item.get('evidence','')).strip()
        if value.casefold() in ('unknown','未指定','未知','不详','unspecified','null','none','n/a'):value='';source='unknown';quote=''
        if source not in cp.SOURCES:raise ValueError('外观来源无效：'+label)
        if value and item.get('owner',asset['name'])!=asset['name']:raise ValueError('其他元素的外观不能归给 '+asset['name'])
        if source=='unknown':value=''
        if kind=='prop' and path.startswith('effects.') and source=='suggested':source='unknown';value=''
        note=str(item.get('source_note',''))
        if value and source=='explicit':
            quote=cp.evidence_quote(story,quote)
            if not quote:
                # An unverified scene/prop description can be retained as a
                # design proposal, but must never be presented as a story fact.
                source='suggested';note='原句引用未核实，暂按设计建议保留。'
        fields[path]={'value':value,'source':source,'evidence':quote if source=='explicit' else '','owner':asset['name']}
        if source=='suggested' and note:fields[path]['source_note']=note
        if kind=='prop' and path.startswith('effects.') and source=='suggested':fields[path].update(value='',source='unknown',evidence='');fields[path].pop('source_note',None)
    if not any(v['value'] for v in fields.values()) and not profile.get('user_summary'):raise ValueError('元素外观档案为空')
    result=vs.unflatten(kind,fields,asset['name'])
    if profile.get('user_summary'):result['user_summary']=str(profile['user_summary'])
    return result


def update_fields(asset,profile,context='',fingerprint=None):
    if asset['kind']=='character':return cp.update_fields(asset,profile,context,fingerprint)
    return {'visual_profile':profile,'description':profile.get('user_summary') or vs.describe(asset['kind'],profile),'narrative_context':context,'profile_source_hash':fingerprint,'profile_source_type':'script' if fingerprint else None,'profile_stale':False}


def request_profile(system,payload):
    from . import ai
    encoded=json.dumps(payload,ensure_ascii=False)
    try:return ai.ask(system,encoded)
    except ValueError as error:
        if not str(error).startswith('AI 未返回有效 JSON'):raise
        return ai.ask(system+'\n上次回复不是有效JSON。重新输出完整严格JSON，不使用Markdown围栏，不省略字段；每个value使用简短中文，字符串内不使用未转义的英文双引号，确保所有括号闭合。',encoded)


def extract(project,asset,other_assets=None,script_text=None):
    if asset['kind']=='character':return cp.extract(project,asset,other_assets,script_text=script_text)
    from . import ai
    system='''你是元素外观提取员，只输出JSON。输出 {visual_profile:{version:2,groups:{分组key:{fields:{字段key:{value,source,evidence,owner}}}}},narrative_context:string}。
按feature_schema填写全部分组子字段。场景六类：空间地理、建筑历史、色彩光影、材质纹理、物件陈设、氛围意境。道具五类：物理属性、色彩光泽、细节纹样、动态特效、风格气质。
原文仅指完成后的script剧本字段；导演建议不是剧情事实，不能把old_description、current_visual_profile或previous中的设计补充当作原句引用。
每个字段owner为target_name。原文明示特征source=explicit，evidence逐字引用属于本元素的短句；设计补充为suggested，引用为空；无法确定用unknown、空值。别把别的元素外观搬来。已有user字段保留。
只写可用于造型的物理视觉特征，不写剧情梗概或镜头安排。场景仅描写target_name指定的一个实际空间，蒙太奇里其他地点的建筑、光照、材质、陈设不得移用；学校门口、小巷、家中分别归属各自地点。普通道具不添加超现实发光、粒子、形变，原文没写则这些字段unknown。写实场景不默认添加魔法或科幻元素。剧情用途放narrative_context。'''
    payload={'production_style_rules':'镜头与美术方案统一时代、画风、色调、材质与空间设计；原文明示与人工外观优先。独立角色和道具保留白背景，不套用剧情机位、动作或场景灯光。','camera_art_scheme':project.get('production_scheme',{}),'target_name':asset['name'],'kind':asset['kind'],'feature_schema':vs.SCHEMA[asset['kind']],'script':script_source.asset_text(project) if script_text is None else script_text,'user_visual_profile':user_profile(asset)}
    result=request_profile(system,payload)
    try:profile=normalize(preserve_user_fields(result.get('visual_profile'),asset),project,asset)
    except ValueError as error:
        result=ai.ask(system+'\n修正校验错误，不能把别的元素特征改标建议继续使用。',json.dumps({**payload,'validation_error':str(error),'previous':result},ensure_ascii=False))
        profile=normalize(preserve_user_fields(result.get('visual_profile'),asset),project,asset)
    return update_fields(asset,profile,str(result.get('narrative_context') or asset.get('narrative_context','')),cp.source_hash(project,asset))


def user_profile(asset):
    return preserve_user_fields(vs.blank(asset['kind'],asset['name']),asset)


def prepare(project,asset):
    if asset['kind']=='character':return cp.prepare(project,asset)
    profile=asset.get('visual_profile')
    if not profile:
        if asset.get('visual_description_source') in ('analysis','script'):return extract(project,asset)
        return {}
    if asset.get('profile_stale') or asset.get('profile_source_type')!='script' or asset.get('profile_source_hash')!=cp.source_hash(project,asset):
        return extract(project,asset)
    profile=normalize(profile,project,asset)
    return update_fields(asset,profile,asset.get('narrative_context',''),cp.source_hash(project,asset))


def image_subject(asset):
    if asset.get('card'):
        from .seedance_integration import card_text
        result={**{k:copy.deepcopy(asset[k]) for k in ('name','kind','model','references') if k in asset},'description':card_text(asset['card']),'five_s':copy.deepcopy(asset['card'])}
        if asset['kind']=='character':
            result['identity_reference_instruction']='这是角色身份参考图，不是分镜画面。5S中的开场、结尾、经历、对白及与其他人物互动是连续性资料，不画成剧情。仅提取本角色可见的年龄阶段、脸型、体态、皮肤毛发、衣着配饰和稳定仪态；只选一个明确状态，不在一张图混合多个年龄或造型。不新增人物、剧情道具或疾病伤害。使用独立中性站姿或半身展示，干净背景；保留原始画风和用户明确外观。'
        return result
    if asset['kind']=='character':return cp.image_subject(asset)
    result={k:copy.deepcopy(asset[k]) for k in ('name','kind','description','model','references') if k in asset}
    profile=asset.get('visual_profile') or {}
    if profile.get('groups') and not profile.get('user_summary'):result['visual_features']=vs.image_features(asset['kind'],profile)
    return result
