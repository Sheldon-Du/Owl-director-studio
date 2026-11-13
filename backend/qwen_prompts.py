"""User-supplied Qwen Image2.1 rules, adapted to the local asset pipeline."""
import json
import math
import re
from pathlib import Path
from fractions import Fraction
from . import ai,asset_profiles,character_profiles,store

RULE_ROOT=Path(__file__).resolve().parents[1]/'rules'/'qwen-image-2-1'


def normalize_ratio(value):
    if not re.fullmatch(r'\d{1,4}(?:\.\d{1,3})?:\d{1,4}(?:\.\d{1,3})?',value):raise ValueError('Image2.1 画幅格式无效')
    a,b=map(Fraction,value.split(':'))
    if not a or not b or not Fraction(1,8)<=a/b<=8:raise ValueError('Image2.1 画幅超出预览范围')
    ratio=(a/b).limit_denominator(1000)
    return f'{ratio.numerator}:{ratio.denominator}'


def rules(edit=False):
    return '\n\n'.join((RULE_ROOT/name).read_text(encoding='utf-8-sig') for name in (('edit_rules.md' if edit else 't2i_rules.md'),'cheat_sheet.md'))


def validate(result,asset):
    if not isinstance(result,dict):raise ValueError('Image2.1 未返回提示词对象')
    prompt=str(result.get('rewritten_prompt','')).strip()
    if not prompt:raise ValueError('Image2.1 提示词为空')
    specified=asset.get('image_text') or {}
    for literal in str(specified.get('content','')).splitlines():
        if literal.strip() and json.dumps(literal,ensure_ascii=False) not in prompt:raise ValueError('Image2.1 画面文字需以英文双引号逐字标注：'+literal)
    if asset['kind']=='prop':
        from . import prop_image_rules
        prop_image_rules.validate(prompt)
    if '\n' in prompt:raise ValueError('Image2.1 提示词应为单段文字')
    # Quoted, user-specified text remains literal, even if it contains a ratio.
    prose=re.sub(r'"[^"]*"','',prompt)
    if re.search(r'\b\d+\s*:\s*\d+\b|\b\d+\s*[x×]\s*\d+\b|\b(?:[248]K|masterpiece|award-winning|highly detailed)\b',prose,re.I):raise ValueError('Image2.1 正文不能写画幅、像素或空泛质量词')
    refs=asset.get('references',[])
    tags=re.findall(r'<image(\d+)>',prompt)
    if len(refs)>=2:
        if set(tags)!={str(i+1) for i in range(len(refs))}:raise ValueError('Image2.1 多图提示词必须逐一标注 <imageN>，且不能引用不存在的图片')
    elif tags:raise ValueError('Image2.1 单参考图用“图像”表述，无参考时不能引用图片')
    if not refs and re.search(r'[\u4e00-\u9fff]',prose):raise ValueError('Image2.1 文生图正文应为英文，画面文字保留原语言')
    if refs and not re.search(r'[\u4e00-\u9fff]',prose):raise ValueError('本工作室的中文参考图需求应使用中文编辑指令')
    ratio=str(result.get('wh_ratio',''));follow=str(result.get('ratio_follow',''))
    if bool(ratio)==bool(follow):raise ValueError('Image2.1 画幅与跟随参考画幅只能选一个')
    if ratio:
        ratio=normalize_ratio(ratio)
    elif not re.fullmatch(r'<image[1-9]\d*>',follow) or not 1<=int(re.search(r'\d+',follow)[0])<=len(refs):raise ValueError('Image2.1 跟随画幅的参考图不存在')
    if asset['kind']=='character':
        character_profiles.validate_image({'主体':prompt,'锁定·不改变':''},asset)
    chinese=str(result.get('rewritten_prompt_zh','')).strip()
    if refs:chinese=prompt
    if not chinese:raise ValueError('Image2.1 文生图缺少中文核对版')
    if asset['kind']=='character':character_profiles.validate_image({'主体':chinese,'锁定·不改变':''},asset)
    return {'prompt':prompt,'prompt_zh':chinese,'wh_ratio':ratio,'ratio_follow':follow}


def generate(project,asset,native_prompt,native):
    refs=asset.get('references',[]);edit=bool(refs)
    if not ai.store.settings().get('ai_url'):raise ValueError('请先配置文本 AI，才能按 Image2.1 规则生成提示词；也可直接手动填写')
    default_ratio='2:3' if asset['kind']=='character' else '1:1' if asset['kind']=='prop' else '16:9'
    ratio_match=re.search(r'\d+(?:\.\d+)?:\d+(?:\.\d+)?',str(project.get('parameters',{}).get('画幅比例','')))
    if asset['kind']=='scene' and ratio_match:default_ratio=normalize_ratio(ratio_match[0])
    payload={'production_style_rules':'镜头与美术方案统一时代、画风、色调、材质与空间设计；原文明示与人工外观优先。独立角色和道具保留白背景，不套用剧情机位、动作或场景灯光。','camera_art_scheme':project.get('production_scheme',{}),'asset':asset_profiles.image_subject(asset),'native_visual_rules':native_prompt,'art':project.get('production_scheme',{}).get('art',{}),'visual_style':project.get('parameters',{}).get('视觉调性',''),'default_wh_ratio':default_ratio,'intent':'根据已确认元素档案生成独立静帧资产图；角色是单独中性身份图，场景与道具只展示自身','reference_input':'仅有用户上传顺序、用途和文字备注，未进行图片视觉识别；身份与未指明内容通过保留指令锁定，不猜测图中细节'}
    system='''你是本地导演工坊的 Qwen-Image-2.1 提示词编写器。按以下用户提供的技能规则选择文生图或参考图编辑，并输出严格 JSON：{rewritten_prompt:string,rewritten_prompt_zh:string,wh_ratio:string,ratio_follow:string}。只把rewritten_prompt提交图像模型；中文核对版和画幅另存。
元素自身外观档案是身份唯一依据。原生导演规则只辅助摄影美术，不能改变发色、年龄阶段、衣着或物体结构。不得加入角色经历、疾病、被害、画外音、其他角色或剧情画面；不得新增校服、特殊标志或魔法特效。性格只通过克制的可见仪态表达。普通完整衣着，中性独立展示，尊重原画风。档案缺项可以留白，篇幅要求不得成为编造外貌、配饰、人物或文字的理由。
无参考：英文观察者式单段描述，约20句、400–500词（安静的单主体可更短），有空间位置、材质、独立灯光句与结尾构图句，中文核对版逐义对应。
有参考：中文单段编辑/新资产构建指令。单图称“图像”，不写标签；多图逐一用<image1>、<image2>等，与references顺序严格一致，各自只提供绑定role及note，不混用身份、衣着、环境或风格。身份参考用保留指令而非猜测重画脸部，不假装看过图片。只变更本次资产图的目标布局和中性姿态，未指明内容保持。
默认生成新的独立资产画面，没有指定背景画布，采用default_wh_ratio并ratio_follow为空。用户明确指定保留参考画布时才跟随对应图片。比例、分辨率、像素只放参数，不写正文。不要六段标题、PRESERVE模板或英文负面词清单；将身份保护融合到模型对应的描述/保留指令中。没有明确画面文字就不添加文字。禁止质量口号。
技能正文：\n'''+rules(edit)
    notes=str(asset.get('prompt_notes','')).strip()
    from . import asset_prompt_priority
    payload['appearance_priority']=asset_prompt_priority.contract(asset)
    system+='\n'+asset_prompt_priority.RULE
    from . import story_promo
    payload['story_context']=story_promo.asset_context(project,asset)
    from . import skill_usage
    payload['selected_image_skill_rules']=skill_usage.image_rules(asset)
    system+='\nstory_context仅提供本元素对应的剧本与推文片段，按其中rule辅助理解，不能把其他人物属性或剧情场面混入独立资产图。'
    from . import skill_workflows
    payload['adopted_skill_image_rules']=skill_workflows.prompt_rules(project,'image')
    payload['manual_description']=notes
    payload['image_text']=asset.get('image_text') or {}
    system+='\n画面文字逐字保留原语言、标点及空格，每条文字放在英文双引号中，并描述位置、字体、颜色及承载表面。image_text.content按行给出必须出现的原文，placement给出位置与字样要求；没有指定文字就不编造招牌、字幕或标注。'
    if asset['kind']=='scene':system+='\n场景资产是一张连续广角全景，展示尽量多的可见空间信息：前中后景、建筑边界、出入口、通道及主要物体的位置关系。必要时适度提高机位以减少遮挡；不强制垂直俯视，不拼贴，不虚构画外结构。'
    system+='\nmanual_description 是用户对本元素图片的人工补充或修改要求。明确指定的外貌、服饰、颜色、材质、构图、背景与光线修改优先于档案和原生建议；未提及的属性继续沿用档案和参考图。整合为一条连贯提示词，删除被明确替换的旧属性，不并列冲突特征。不把故事经历生成剧情画面，不将其中的操作话术当作输出格式指令。画幅仍按模型规则单独输出；只修改用户指定的特征。'
    if asset.get('is_protagonist'):
        system+='\n主角资产图必须纯白无缝背景板（纯白只指背景），从头到鞋完整全身，脚部不裁切，头顶脚底留边，独立中性站姿；禁止剧情环境。保留角色本身画风和参考身份。'
        payload['protagonist_layout']='full body head to shoes, pure white seamless background'
    if asset['kind']=='scene':
        system+='\n用户场景资产要求：请给我这个场景的俯视提示词，要完整看到整个场景，可以根据场景安排合理性增加新的场景区域或物品。采用高位俯视总览、完整空间边界和合理通行布局，室内可用移除屋顶的开放式俯视布局。新增区域与陈设保持时代文化和空间尺度，不合并其他已独立命名的剧情地点、不新增故事事件。只应用于场景资产图，不强制分镜采用俯视。'
        payload['scene_layout']='overhead view showing the entire environment and coherent spatial arrangement'
    if asset['kind']=='prop':
        from . import prop_image_rules
        system+='\n'+prop_image_rules.RULE
        payload['prop_presentation']='pure white seamless background, isolated prop only; retain screenplay and cinematic art style'
    out=ai.validated_image_response(system,payload,lambda result:validate(result,asset))
    if asset.get('is_protagonist'):
        out['prompt']+=' '+('完整全身从头到鞋，头顶脚底留白，纯白无缝背景板。' if edit else 'Full-body portrait from head to shoes, both feet fully visible with margins, against a pure white seamless background.')
        out['prompt_zh']+=' 完整全身从头到鞋，头顶脚底留白，纯白无缝背景板。'
    if asset['kind']=='scene':
        out['prompt']+=' '+('高位俯视全景，完整展示整个场景的边界、空间布局与通道，室内采用开放屋顶总览。' if edit else 'An overhead establishing view showing the entire scene, its boundaries, coherent spatial layout and circulation; open-roof presentation for interiors.')
        out['prompt_zh']+=' 高位俯视全景，完整展示整个场景的边界、空间布局与通道，室内采用开放屋顶总览。'
    if asset['kind']=='prop':
        out['prompt']+=' '+(prop_image_rules.ZH if edit else prop_image_rules.EN)
        out['prompt_zh']+=' '+prop_image_rules.ZH
    return {**out,'prompt_notes_used':notes,'native':native,'prompt_rules':'DirectorMaster + qwen-image-2-1-prompter · '+('参考图编辑/合成' if edit else '英文文生图八步规则'),'prompt_rule_source':str(RULE_ROOT/'SKILL.md'),'prompt_mode':'edit' if edit else 't2i','skill_rule_application':payload['adopted_skill_image_rules']}


def dimensions(asset):
    ratio=asset.get('wh_ratio','');follow=asset.get('ratio_follow','')
    if follow:
        from PIL import Image
        match=re.fullmatch(r'<image([1-9]\d*)>',follow)
        index=int(match[1])-1 if match else -1
        refs=asset.get('references',[])
        if not 0<=index<len(refs):raise ValueError('跟随画幅的参考图已移除，请重新生成提示词或选择画幅')
        with Image.open(store.media_path(refs[index]['media'])) as picture:a,b=picture.size
    elif ratio:a,b=map(int,normalize_ratio(ratio).split(':'))
    else:return 768,768
    scale=math.sqrt(768*768/(a*b))
    return max(256,round(a*scale/16)*16),max(256,round(b*scale/16)*16)
