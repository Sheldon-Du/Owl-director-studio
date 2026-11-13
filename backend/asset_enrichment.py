"""Fill missing asset appearance fields without re-extracting known identity."""
import copy,hashlib,json
from . import ai,asset_profiles,asset_extraction,asset_exploration,visual_schema as vs,script_source,character_profiles as cp,store

def fingerprint(project,asset):
    return hashlib.sha256(json.dumps([script_source.asset_text(project),cp.design_hash(asset),{k:asset.get(k) for k in ('model','references','prompt_notes','image_skill_ids')},project.get('parameters',{}),project.get('production_scheme',{})],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def merge(project,asset,raw):
    profile=asset_extraction.expand_profile({**raw,'kind':asset['kind'],'name':asset['name']})
    fields=vs.flatten(asset['kind'],profile)
    existing=asset.get('visual_profile') or vs.blank(asset['kind'],asset['name'])
    if asset['kind']=='character':existing=vs.from_legacy('character',existing,asset['name'])
    old=vs.flatten(asset['kind'],existing)
    # Ignore the AI's proposals for known values before validating new fields.
    for path,item in fields.items():
        if old[path].get('value') and old[path].get('source')!='unknown':fields[path]={}
    proposed=vs.unflatten(asset['kind'],fields,asset['name'])
    filled=vs.flatten(asset['kind'],proposed)
    for path,item in old.items():
        if item.get('value') and item.get('source')!='unknown':filled[path]=copy.deepcopy(item)
    merged=vs.unflatten(asset['kind'],filled,asset['name'],existing.get('other_age_stages',[]))
    if existing.get('user_summary'):merged['user_summary']=existing['user_summary']
    merged=asset_profiles.normalize(merged,project,asset,project.get('assets',[]))
    return asset_profiles.update_fields(asset,merged,asset.get('narrative_context',''),cp.source_hash(project,asset))

def generate(project,asset,report):
    report('正在一次补全 '+asset['name']+' 的描述并生成图片提示词，共用剧本上下文')
    system=asset_exploration.DESIGN_RULES+'''\n此次只补充target一个已有元素，不探索新元素、不重新提取或替换已有字段。current_visual_profile中的非空有效字段及old_description中的人工明确外观均锁定，只填缺失的普通外观。允许普通造型补全不等于新增剧情。只输出JSON {fields:[[分组.字段,具体中文特征,explicit或suggested,逐字依据或空串]]}。原文没有明确细节时主动设计合理细节并标suggested。保持原有中性仪态与稳定性格，不添加经历、特殊能力或新情节。没有必要的配饰写无；原文未写的特殊标志、超现实特效省略。'''
    payload={'production_style_rules':'镜头与美术方案统一时代、画风、色调、材质与空间设计；原文明示与人工外观优先。独立角色和道具保留白背景，不套用剧情机位、动作或场景灯光。','camera_art_scheme':project.get('production_scheme',{}),'target':{'name':asset['name'],'kind':asset['kind']},'script':script_source.asset_text(project),'parameters':project.get('parameters',{}),'art':project.get('production_scheme',{}).get('art',{}),'current_visual_profile':asset.get('visual_profile',{}),'old_description':asset.get('description',''),'feature_schema':vs.labels(asset['kind']),'existing_assets':[{'name':a['name'],'kind':a['kind'],'description':a.get('description','')} for a in project.get('assets',[]) if a['id']!=asset['id']]}
    system+='\n只返回一个严格JSON对象，不加Markdown围栏。fields每项恰好四个字符串；字符串中的英文双引号、换行、反斜杠必须正确转义。'
    from . import enrichment_image_prompt as image
    image_rules,image_input=image.rules(asset);system+=image_rules;payload['image_input']=image_input
    from . import story_promo,skill_workflows
    context=story_promo.asset_context(project,asset)
    payload['visual_promo_context']={k:context[k] for k in ('visual_promo_excerpts','rule')}
    payload['adopted_image_rules']=skill_workflows.prompt_rules(project,'image')
    with ai.asset_call_policy('asset_enrich',limit=2,max_tokens=8192,timeout=240):
        previous=None;error=None
        for attempt in range(2):
            try:
                request=payload if not attempt else {'target':payload['target'],'feature_schema':payload['feature_schema'],'image_input':image_input,'current_visual_profile':asset.get('visual_profile',{}),'previous':previous,'validation_error':error}
                raw=ai.ask(system if not attempt else system+'\n仅定点修复上次字段或图片提示词的格式/校验问题，保留已合格描述，不重新阅读剧本、不新增事实。',json.dumps(request,ensure_ascii=False));previous=raw
                if not isinstance(raw.get('fields'),list):raise ValueError('fields应为数组')
                if any(not isinstance(row,list) or len(row)!=4 or not all(isinstance(value,str) for value in row) for row in raw['fields']):raise ValueError('补充描述每项需要四个字符串')
                update=merge(project,asset,raw)
                update.update(image.validate(raw.get('image_prompt'),{**asset,**update}))
                return {'source_hash':fingerprint(project,asset),'update':update}
            except ai.InvalidJSONResponse as failure:previous=failure.raw_response;error=str(failure)
            except ValueError as failure:
                if previous is None:raise
                error=str(failure)
            report('描述与提示词正在局部纠错，不重复提交完整剧本')
        raise ValueError('描述与图片提示词联合生成未通过：'+str(error)+'；已有信息和图片保留')

def redo_card(project,asset,report):
    from . import seedance_integration as seedance
    report('正在重新编写 '+asset['name']+' 的5S描述，已有图片保留')
    payload={'target':{k:asset.get(k) for k in ('name','kind','card','description','visual_profile','variant','prompt_notes')},'script':script_source.asset_text(project),'art_scheme':project.get('production_scheme',{}),'references':asset.get('references',[])}
    system=seedance.GUIDE+' 重新编写target这个已有资产的5S描述，返回JSON {card:{goal,subject,style,shot,setting,lighting,constraints}}。保持原文明确事实、人工补充描述、身份、时代、资产类型与状态变体；重做表述与合理外观设计，不新增剧情、人物或资产。已有参考图仅说明有身份参考，不声称看过图像。输出为资产设定图而非剧情瞬间。'
    with ai.asset_call_policy('asset_enrich',limit=2,max_tokens=8192,timeout=240):
        card=ai.validated_image_response(system,payload,lambda value:seedance.card(value.get('card')))
    return {'source_hash':fingerprint(project,asset),'card_source_hash':hashlib.sha256(json.dumps(asset.get('card'),ensure_ascii=False,sort_keys=True).encode()).hexdigest(),'redo_card':card}


def apply_result(project,target,result):
    asset=next((a for a in project.get('assets',[]) if a['id']==target),None)
    if not asset or fingerprint(project,asset)!=result['source_hash']:raise store.Conflict('补充期间该元素或剧本风格已修改，未覆盖，请重新补充')
    if result.get('redo_card'):
        from . import seedance_integration as seedance
        import time
        before=hashlib.sha256(json.dumps(asset.get('card'),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        if before!=result['card_source_hash']:raise store.Conflict('重做期间5S描述已被编辑，未覆盖当前内容')
        asset.setdefault('card_history',[]).append({'card':copy.deepcopy(asset.get('card',{})),'created':time.time()})
        asset['card']=result['redo_card'];asset['description']=seedance.card_text(asset['card'])
        asset['prompt']='';asset['prompt_zh']=''
        return
    if asset.get('prompt'):asset.setdefault('prompt_history',[]).append({'prompt':asset['prompt'],'prompt_zh':asset.get('prompt_zh',''),'reason':'AI补全外观描述'})
    asset.update(result['update'])
    asset['enrichment_source_hash']=fingerprint(project,asset)
    asset['style_needs_refresh']=False
    if not result['update'].get('prompt'):asset['prompt']='';asset['prompt_zh']=''
    for image in asset.get('previews',[]):image['stale']=True
