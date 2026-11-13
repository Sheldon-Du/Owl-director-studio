"""Optional asset exploration: suggestions are reviewed before creating cards."""
import hashlib,json,time,copy
from . import ai,store,script_source,story_promo,scene_identity,asset_profiles,asset_extraction,visual_schema,character_profiles

DESIGN_RULES='''你同时是一位影视美术设计师与角色造型师。本按钮必须在发现额外元素的同一次任务中，为每个候选完成“基于剧本约束的资产设计补全”，不能只摘录已有文字或等待采用后再生成描述。
先理解剧本时代、地域文化、现实或奇幻属性、身份制度与技术条件，再确定已确认的电影/美术风格、色彩与材质语言。优先级：剧本明确事实与用户锁定外观 > 已确认制作美术与视觉设定 > 与已有资产统一的设计补全。导演风格只指导视觉表达，不引入其他时代的实物、服饰或建筑。未明确的风格从剧本上下文提出一致建议，不照抄参考案例。
描写很少的元素也要主动设计完整、可用于图片生成的普通外观：角色依据年龄、身份与经济条件补全衣着和体态；场景依据地域、功能与时代补全合理布局和材质；道具依据用途、工艺和使用环境补全结构、尺寸感和磨损。给出一套明确连贯的设计，不并列互斥选项，不写“自行决定”“参照剧本”等空话。缺少明示不等于全部字段未知；有依据的普通设计应填写suggested。
严格区分“已有元素的外观补全”和“新增元素”：即使忠于故事，也允许为已有元素补充普通外观并标为设计建议，但禁止新增事件、关系、能力、身份秘密或改变因果。伤疤、纹身、特殊饰物、稀有能力等可能暗示未写经历的内容不自动补充。原文明示字段保留并逐字引用；所有补全字段标suggested、引用为空。不用人物经历或剧情发生后的情绪变化代替外貌。配饰与特效没有必要就写无，不为丰富而堆砌。
角色完整覆盖从头到鞋的设计顺序：整体印象、头发、面部、颈肩、躯干、手臂手部、上衣、下装、腿部、袜鞋，再补必要配饰、稳定性格及中性仪态。角色设定图为独立全身纯白背景。
场景描述包括空间布局与尺度、建筑时代风格、色彩光影、材质纹理、关键陈设与氛围，明确入口、通道和主要区域的位置关系，不合并不同地点。
道具描述包括轮廓尺寸、结构、材质、颜色光泽、工艺细节、合理磨损及项目风格；只展示道具与自身组成部分，纯白背景，无人物、手、其他物品或环境陈设。纯白仅指背景，道具本色与电影/动画质感必须沿用项目。
description写完整外观设计而非故事梗概；fields是同一设计的分类档案，逐项标明explicit（剧本明确）或suggested（设计建议），description不能包含fields之外的新属性。视频推文仅帮助理解画面需求，不覆盖剧本事实。'''

def fingerprint(project):
    return hashlib.sha256(json.dumps(['classified-asset-v3-design',script_source.asset_text(project),project.get('story_policy','faithful'),story_promo.additions_allowed(project),project.get('parameters',{}),project.get('production_scheme',{}).get('art',{}),project.get('documents',{}).get('art','')],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def validate(project,items,require_profiles=False):
    if not isinstance(items,list) or len(items)>30:raise ValueError('额外元素候选需为不超过30项的列表')
    script=script_source.asset_text(project);allowed=story_promo.additions_allowed(project)
    known={(a['kind'],a['name']) for a in project.get('assets',[])};result=[]
    for row in items:
        if not isinstance(row,dict):raise ValueError('额外元素候选格式错误')
        kind=row.get('kind');name=row.get('name','');origin=row.get('origin')
        if kind not in ('character','scene','prop') or not isinstance(name,str) or not name.strip() or len(name)>100:raise ValueError('候选须有角色、场景或道具类型及名称')
        name=name.strip()
        if (kind,name) in known:continue
        if kind=='scene':scene_identity.single_name(name)
        for key in ('description','reason'):
            if not isinstance(row.get(key),str) or not row[key].strip() or len(row[key])>3000:raise ValueError('候选须说明自身外观及用途：'+name)
        evidence=row.get('evidence','')
        if origin=='source':
            if not isinstance(evidence,str) or not evidence.strip() or evidence not in script:raise ValueError('查漏候选须引用剧本连续原句：'+name)
            aliases=row.get('aliases',[])
            if not isinstance(aliases,list) or any(not isinstance(a,str) for a in aliases):raise ValueError('候选别名格式错误')
            if not any(n in evidence for n in [name,*aliases] if n):raise ValueError('候选名称或原文别名须出现在依据中：'+name)
        elif origin=='design':
            if not allowed:raise ValueError('忠于故事或关闭新增时，不允许新增设计元素：'+name)
            evidence=''
        else:raise ValueError('候选来源需为source（剧本查漏）或design（额外设计）')
        candidate={'id':store.uid(),'kind':kind,'name':name,'description':row['description'].strip(),'reason':row['reason'].strip(),'origin':origin,'evidence':evidence,'aliases':row.get('aliases',[])}
        if row.get('fields') is not None or row.get('visual_profile') is not None:
            raw=asset_extraction.expand_profile({**row,'kind':kind,'name':name})
            if origin=='design':
                for group in raw.get('groups',{}).values():
                    for field in group.get('fields',{}).values():
                        if field.get('value'):field.update(source='suggested',evidence='')
            profile=asset_profiles.normalize(raw,project,candidate,project.get('assets',[])+items)
            candidate['visual_profile']=profile
            candidate['description']=visual_schema.describe(kind,profile)
        elif require_profiles:raise ValueError('额外元素缺少分类外观描述：'+name)
        result.append(candidate)
        known.add((kind,name))
    return result

def generate(project,report):
    script=script_source.asset_text(project)
    report('正在探索额外可用元素，并按剧本环境与美术风格补全详细外观描述')
    system='''你是影视资产探索助手。只输出JSON {candidates:[{name,kind:character|scene|prop,description:自身外观而非人物经历,reason:实际镜头用途,origin:source|design,evidence:剧本连续逐字原句,aliases:[剧本原名]}]}。
    从完整剧本探索遗漏的出镜角色、不同拍摄空间、手持或互动道具、特写道具、关键环境物件。已有资产不要重复。按实用性排序，不为凑数量拆出无用卡片。source候选的名称或别名必须出现在evidence，旁白仅提及而不展示的不推荐。单一场景对应单一空间，不合并地点。角色不挪用他人外貌，未明确外貌标为造型建议。忠于故事或allow_additions=false只能查漏已有事实，禁止新增人物、事件、物件和地点；allow_additions=true可提出时代文化合理、服务已确认情节的额外美术设计，origin=design且evidence为空，明确是新增候选，不改写剧本或分镜。视频推文只参考画面需求，不能作为新增事实的剧本依据。最多30项，可以没有新候选。'''
    system+='''\n每个候选还必须返回fields数组，格式[[分组.字段,简短中文特征,explicit或suggested,逐字短句或空串]]，路径来自feature_schema。填入所有有用分类，不只一句概述。角色按头发、面部、颈肩、躯干、手臂手部、上衣、下装、腿部及袜鞋从头到脚整理六类外观和独立稳定性格；主角造型用于完整全身白背景。场景填空间地理、建筑时代、色光、材质、陈设、氛围六类；道具填轮廓尺寸材质、色彩光泽、细节、已明确特效、风格五类。明确原文事实为explicit并给本人/本物逐字依据；未明确的普通造型仅作suggested，不冒充原文，不新增特殊标志、能力或剧情。design候选全部为suggested且引用为空。未知字段省略，由系统填unknown。正文按分类顺序描述，不写经历或发生剧情后的情绪变化。单次优先至多12个完整实用候选，避免为凑数输出残缺。道具与场景遵守同一电影或美术风格与时代。'''
    system+='\n'+DESIGN_RULES
    payload={'script':script,'visual_promo':story_promo.input_values(project),'parameters':project.get('parameters',{}),'art':project.get('production_scheme',{}).get('art',{}),'confirmed_art_document':str(project.get('documents',{}).get('art',''))[:8000],'feature_schema':{kind:visual_schema.labels(kind) for kind in ('character','scene','prop')},'existing_assets':[{'kind':a['kind'],'name':a['name'],'description':a.get('description','')} for a in project.get('assets',[])],'allow_additions':story_promo.additions_allowed(project),'allow_appearance_design_completion':True,'fact_policy':'新增元素权限与普通外观补全分别处理：普通补全为suggested，不改剧本事实或已明确外观'}
    with ai.asset_call_policy('asset_explore',limit=1,max_tokens=16384,timeout=240):
        answer=ai.ask(system,json.dumps(payload,ensure_ascii=False))
    if not isinstance(answer,dict):raise ValueError('AI未返回候选对象')
    return {'source_hash':fingerprint(project),'candidates':validate(project,answer.get('candidates'),require_profiles=True),'created':time.time()}

def apply_result(project,result):
    if fingerprint(project)!=result['source_hash']:raise store.Conflict('探索期间剧本或新增权限已修改，候选未覆盖，请重新探索')
    previous=project.get('asset_exploration',{})
    project['asset_exploration']={**result,'history':[*previous.get('history',[]),{k:v for k,v in previous.items() if k!='history'}][-10:] if previous else []}

def adopt(project,ids):
    state=project.get('asset_exploration',{})
    if state.get('source_hash')!=fingerprint(project):raise ValueError('候选依据已变化，请重新探索')
    if not isinstance(ids,list) or not ids or any(not isinstance(s,str) for s in ids) or len(set(ids))!=len(ids):raise ValueError('请选择候选元素')
    rows=[r for r in state.get('candidates',[]) if r['id'] in ids and not r.get('adopted')]
    if len(rows)!=len(ids):raise ValueError('候选不存在或已经采用')
    candidates=validate(project,rows)
    if len(candidates)!=len(rows):raise ValueError('同名元素已存在，请重新核对候选')
    for original,c in zip(rows,candidates):
        asset={'id':store.uid(),'kind':c['kind'],'name':c['name'],'description':c['description'],'visual_description_source':'script' if c['origin']=='source' else 'suggested','model':'qwen-image-2.1','model_source':'default','prompt':'','references':[],'previews':[],'adopted':None,'aliases':c['aliases'],'exploration_origin':c['origin'],'exploration_evidence':c['evidence'],'exploration_reason':c['reason']}
        if c.get('visual_profile'):asset.update(asset_profiles.update_fields(asset,c['visual_profile'],'',character_profiles.source_hash(project,asset)))
        project.setdefault('assets',[]).append(asset)
        original['adopted']=True
