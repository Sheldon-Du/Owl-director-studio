"""User-authored reference-image edits kept as separate reusable asset cards."""
import copy,json
from . import ai,store,qwen_prompts,asset_profiles,asset_prompt_priority

def create(project,body):
    parent=next((a for a in project['assets'] if a['id']==body.get('parent_id')),None)
    if not parent:raise ValueError('请选择原资产')
    intent=str(body.get('intent','')).strip()
    if not intent or len(intent)>4000:raise ValueError('请用一句话描述变化（最多4000字）')
    refs=body.get('references')
    if not isinstance(refs,list) or not 1<=len(refs)<=16:raise ValueError('请选择1至16张参考图片')
    references=[];seen=set()
    allowed={'identity','costume','prop','environment','style','pose'}
    for ref in refs:
        if not isinstance(ref,dict) or ref.get('role') not in allowed:raise ValueError('请选择有效参考用途')
        name=ref.get('media')
        if not isinstance(name,str) or name in seen or not store.media_path(name).is_file():raise ValueError('参考图不存在或重复')
        from PIL import Image
        try:
            with Image.open(store.media_path(name)) as image:image.verify()
        except Exception as error:raise ValueError('仅支持可读取的参考图片') from error
        seen.add(name);references.append({'id':store.uid(),'media':name,'role':ref['role'],'note':str(ref.get('note',''))[:2000]})
    asset=copy.deepcopy(parent)
    for key in ('prompt_history','profile_result_hash','native','prompt_rules','skill_rule_application','wh_ratio','ratio_follow'):asset.pop(key,None)
    asset.update(id=store.uid(),name=str(body.get('name') or parent['name']+' · 状态变体')[:120],model='qwen-image-2.1',model_source='user',prompt='',prompt_zh='',prompt_notes='',references=references,previews=[],adopted=None)
    asset['variant']={'parent_id':parent['id'],'parent_name':parent['name'],'intent':intent,'base_subject':asset_profiles.image_subject(parent),'base_priority':asset_prompt_priority.contract(parent)}
    project['assets'].append(asset)
    return asset

def generate(project,asset,report):
    variant=asset['variant'];refs=asset['references']
    if not refs:raise ValueError('状态变体至少需要一张参考图')
    report('正在按参考图片分工和变化要求编写 '+asset['name']+' 的Image2.1提示词')
    system='''你是Image2.1参考图编辑与多图融合提示词编写器。只输出JSON {"rewritten_prompt":"中文单段指令","rewritten_prompt_zh":"相同中文指令","wh_ratio":"比例","ratio_follow":""}。
    原资产不变，本次输出为其独立状态变体。用户变化要求优先，其他身份、体型、结构、时代、材质和画风保留；不主动新增剧情和其他主体。用户本次明确变化 > 剧本明示 > 原资产已确认特征 > AI普通细节建议。变化状态是用户设计要求，不声称是剧本已发生的事实。单图称“图像”；多图逐张称<image1>、<image2>等，严格对应references顺序，说明各图提供什么及不提供什么；衣服参考不改变目标人物的脸，天气参考不改变场景布局。用户一句话不足的普通视觉细节可克制补全。未进行图像识别，不猜测参考图中人物外貌，使用保留指令。比例只放参数。角色为独立中性完整造型，主角白背景全身；道具单独纯白背景无其他物体，容器内容物等用户要求的状态属于道具本身；场景保持布局与完整俯视总览。返回可直接交给模型的编辑指令，不输出按钮说明或数字权重。
    '''+qwen_prompts.rules(True)
    payload={'base_subject':variant['base_subject'],'base_priority':variant['base_priority'],'change':variant['intent'],'manual_adjustment':asset.get('prompt_notes',''),'references':[{'slot':i+1,'role':r['role'],'note':r.get('note','')} for i,r in enumerate(refs)],'art':project.get('production_scheme',{}).get('art',{}),'style':project.get('parameters',{}).get('视觉调性',''),'default_ratio':'16:9' if asset['kind']=='scene' else '2:3' if asset['kind']=='character' else '1:1'}
    # Character changes are explicitly authorized; use the shared format/reference
    # validator without checking the replaced costume against the old identity.
    validation_asset={**asset,'kind':'scene'} if asset['kind']=='character' else asset
    with ai.asset_call_policy('asset_variant_prompt',limit=3,max_tokens=8192,timeout=240):
        result=ai.validated_image_response(system,payload,lambda raw:qwen_prompts.validate(raw,validation_asset))
    if asset['kind']=='prop':
        from . import prop_image_rules
        result['prompt']+=' '+prop_image_rules.ZH;result['prompt_zh']+=' '+prop_image_rules.ZH
    return {**result,'prompt_notes_used':asset.get('prompt_notes','').strip(),'prompt_rules':'Image2.1 · 参考图融合／状态变体','prompt_mode':'edit'}
