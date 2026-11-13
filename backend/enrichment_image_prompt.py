"""Image-writing rules and validation for a combined description/prompt reply."""
from . import qwen_prompts,image_prompts,asset_prompt_priority,character_profiles,prop_image_rules,skill_usage

def rules(asset):
    if asset.get('variant'):raise ValueError('状态变体请使用生成提示词，保留原资产档案')
    qwen=asset.get('model')=='qwen-image-2.1';edit=bool(asset.get('references')) and qwen
    output='image_prompt:{rewritten_prompt:string,rewritten_prompt_zh:string,wh_ratio:string,ratio_follow:string}' if qwen else 'image_prompt:{sections:{参考图标注:string,主体:string,特效层:string,锁定·不改变:string,PHOTOGRAPHIC TONE:string,Avoid:string},sections_zh:{同样六段}}'
    instruction='\n同一个JSON同时返回fields和'+output+'。先在内部完成缺失特征补全，再基于合并后的完整外观写图片提示词，两者必须一致。已知字段和人工描述不能被补全建议覆盖。性格仅用克制可见仪态表达，不写剧情经历、对白或画外音。'
    instruction+='\n缺失的普通外观应给出符合时代、美术的具体设计建议（suggested），不要把unknown、未知、null填进value。无配饰可明确写无；无法判断的特殊标志留空，不能虚构。'
    instruction+='\n'+asset_prompt_priority.RULE
    instruction+='\n用户人工修改只影响明确要求的可见属性，未提及的特征保留。主角纯白背景从头到鞋全身；场景用一张连续广角全景展示尽量多的可见空间信息，包括前中后景、出入口、通道和主要物体位置，不强制垂直俯视；道具独立纯白背景，保留时代、材质、实际颜色和电影风格。比例放参数，不混入正文。'
    instruction+='\n所有明确指定的画面文字必须逐字保留原语言、标点和空格，用英文双引号标注，并描述位置、字体、颜色与承载表面。没有指定文字则不添加文字。'
    if asset['kind']=='prop':instruction+='\n'+prop_image_rules.RULE
    if qwen:
        instruction+='\nImage2.1：无参考图用英文单段描述，有参考图用中文单段编辑指令；单图称图像，多图逐张<image1>等并按用途分工，不能猜测未识别的图片内容。中文核对版逐义对应。默认ratio_follow为空，wh_ratio为角色2:3、场景16:9、道具1:1。\n'+qwen_prompts.rules(edit)
    else:instruction+='\nNeoImage六段，英文生成版和中文核对版；Z-Image仅文字概念预览，不假装使用参考图片。\n'+image_prompts.neo_rules()
    return instruction,{'model':asset.get('model'),'references':[{'slot':i+1,'role':r['role'],'note':r.get('note','')} for i,r in enumerate(asset.get('references',[]))],'manual_description':asset.get('prompt_notes',''),'appearance_priority':asset_prompt_priority.contract(asset),'selected_image_skills':skill_usage.image_rules(asset)}

def validate(raw,asset):
    if not isinstance(raw,dict):raise ValueError('需同时返回image_prompt对象')
    if asset.get('model')=='qwen-image-2.1':
        result=qwen_prompts.validate(raw,asset)
        if asset.get('is_protagonist'):
            clause='完整全身从头到鞋，脚部完整可见，纯白无缝背景板。' if asset.get('references') else 'Full body from head to shoes, feet fully visible, pure white seamless background.'
            result['prompt']+=' '+clause;result['prompt_zh']+=' 完整全身从头到鞋，脚部完整可见，纯白无缝背景板。'
        if asset['kind']=='scene':
            result['prompt']+=' '+('连续广角全景，尽量完整呈现前中后景、空间边界、出入口、通道和主要物体位置，适度提高机位以减少遮挡。' if asset.get('references') else 'One continuous wide panoramic establishing view showing foreground, middle ground, background, boundaries, entrances, exits and circulation routes, with an elevated viewpoint where useful to reduce occlusion.');result['prompt_zh']+=' 连续广角全景，尽量完整呈现前中后景、空间边界、出入口、通道和主要物体位置，适度提高机位以减少遮挡。'
        if asset['kind']=='prop':result['prompt']+=' '+(prop_image_rules.ZH if asset.get('references') else prop_image_rules.EN);result['prompt_zh']+=' '+prop_image_rules.ZH
    else:
        result={'prompt':image_prompts.format_sections(raw.get('sections')),'prompt_zh':image_prompts.format_sections(raw.get('sections_zh'))}
        if asset['kind']=='character':
            character_profiles.validate_image(raw['sections'],asset);character_profiles.validate_image(raw['sections_zh'],asset)
        if asset['kind']=='prop':prop_image_rules.validate(raw['sections']['主体']);prop_image_rules.validate(raw['sections_zh']['主体'])
    return {**result,'prompt_notes_used':asset.get('prompt_notes','').strip(),'prompt_rules':'外观补全 + '+('Image2.1 专用规则' if asset.get('model')=='qwen-image-2.1' else 'NeoImage 六段规则'),'prompt_mode':'edit' if asset.get('references') and asset.get('model')=='qwen-image-2.1' else 't2i'}
