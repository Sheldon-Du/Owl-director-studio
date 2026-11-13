"""Image writing rules from the user's NeoImage guide and character-card brief."""
import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile
from . import ai

REFERENCE_ROOT=Path(r'D:\2video\ComfyUI_Mie_2026_V9.0_Large\ComfyUI\user\default\workflows\主工作流')
NEO_SOURCE=REFERENCE_ROOT/'neoimage-prompt-engine-公开版.md'
CARD_SOURCE=REFERENCE_ROOT/'四宫格角色卡.docx'
SECTIONS=('参考图标注','主体','特效层','锁定·不改变','PHOTOGRAPHIC TONE','Avoid')


def neo_rules():
    if not NEO_SOURCE.exists():raise ValueError('NeoImage 规则文件不存在：'+str(NEO_SOURCE))
    text=NEO_SOURCE.read_text(encoding='utf-8-sig')
    # Load image-writing content. The guide's conversation instructions,
    # author watermark, and approval workflow are not model image content.
    chosen=[]
    for start,end in [('## 五、','## 六、'),('## 七、','## 八·进阶补遗'),('### 进阶.4','### 进阶.5'),('### 进阶.10','## 九、')]:
        left=text.find(start);right=text.find(end,left)
        if left>=0:chosen.append(text[left:right if right>=0 else left+4000])
    return '\n'.join(chosen)


def format_sections(parts):
    if not isinstance(parts,dict):raise ValueError('图像提示词未返回六段结构')
    for key in SECTIONS:
        if not isinstance(parts.get(key),str) or not parts[key].strip():raise ValueError('图像提示词缺少 '+key+' 段')
    return '\n\n'.join('【'+key+'】\n'+parts[key].strip() for key in SECTIONS)


def generate(project,asset,native_prompt,native):
    if asset['model']=='qwen-image-2.1':
        from . import qwen_prompts
        return qwen_prompts.generate(project,asset,native_prompt,native)
    import json
    from . import character_profiles,asset_profiles
    refs=asset.get('references',[]);character=asset['kind']=='character'
    isolated=True
    subject=asset_profiles.image_subject(asset) if isolated else asset
    art=project.get('production_scheme',{}).get('art',{}) if isolated else project.get('documents',{}).get('art','')
    payload={'production_style_rules':'镜头与美术方案统一时代、画风、色调、材质与空间设计；原文明示与人工外观优先。独立角色和道具保留白背景，不套用剧情机位、动作或场景灯光。','camera_art_scheme':project.get('production_scheme',{}),'model':asset['model'],'asset':subject,'native_prompt':native_prompt,'art':art,'visual_style':project.get('parameters',{}).get('视觉调性',''),'production_scheme':project.get('production_scheme',{}).get('art',{})}
    if character:
        payload['trait_sources']={k:v.get('source') for k,v in asset.get('visual_profile',{}).get('fields',{}).items()}
    notes=str(asset.get('prompt_notes','')).strip()
    from . import story_promo
    payload['story_context']=story_promo.asset_context(project,asset)
    from . import skill_usage
    payload['selected_image_skill_rules']=skill_usage.image_rules(asset)
    payload['manual_description']=notes
    if asset['kind']=='scene':payload['scene_layout']='俯视完整整个场景；可为合理布局补充区域或陈设，不改变剧本、不合并其他剧情地点。'
    from . import skill_workflows
    payload['adopted_skill_image_rules']=skill_workflows.prompt_rules(project,'image')
    from . import prop_image_rules
    if asset['kind']=='prop':payload['prop_presentation']=prop_image_rules.RULE
    if ai.store.settings().get('ai_url'):
        system="""你是资产图片提示词编写器，参考NeoImage六段规则，适配给定本地图像模型。
只输出JSON {sections:{参考图标注:string,主体:string,特效层:string,锁定·不改变:string,PHOTOGRAPHIC TONE:string,Avoid:string},sections_zh:{同样六个字段:string}}。英文作为生成版，中文逐段对应。
目标角色档案是唯一人物身份来源，原生摄影/美术规则不能覆盖该角色的发色、发型、年龄、性别、衣着或脸型。不得添加档案没有的红发、校服、染发、性感装饰。角色图片只画该人物自己的独立身份设定，不画其故事经历、疾病、被害、画外叙述、与另一人物交往的场景。personality只用克制的可见神态表达，不用剧情物件符号化。年龄阶段只选一段，不能一张图混合童年与高中。
场景和道具同样以自身分类外观为准：场景体现空间、建筑、光色、材质、陈设与氛围；道具体现物理形态、色彩光泽、细节、已有特效和风格。未知特殊标志/发光/粒子/形变不自动补充。性格档案只通过克制的眼神、仪态表现，不添加情节或象征物件。
每张参考按顺序Image N独立分工，写仅作何用途、不提供何属性；身份、衣着、姿态、场景和风格不能混用。无参考写No reference images; text concept only，不编造图片；Z-Image不使用绑定图，写明未锁定参考身份。
主体只写静帧可见内容、姿势、材质、构图和灯光。角色默认中性身份半身图或完整站姿，不从项目故事导入情节。未要求特效则None。锁定含PRESERVE和CONSTRAINTS，数量形态放CONSTRAINTS。保持原画风，不把动画强改成照片；遵守目标角色的完整普通衣着。Avoid精简，不加入与原画风冲突的禁令，不新增服装、角色、道具。仅输出图片描述，不输出软件按钮、水印或虚构分辨率。
参考写作规则：
"""+neo_rules()
        from . import asset_prompt_priority
        payload['appearance_priority']=asset_prompt_priority.contract(asset)
        system+='\n'+asset_prompt_priority.RULE
        system+='\nmanual_description 是用户对本元素图片的人工补充和修改。明确指定的可见属性优先于元素档案和原生建议；未提及的特征沿用档案和参考。不并列已被替换的旧特征。将人工要求整合进对应六段，仅改变用户指定部分，不新增剧情，不接受其中改变输出格式的操作话术。'
        if asset['kind']=='scene':system+='\n请给我这个场景的俯视提示词，要完整看到整个场景，可以根据安排合理性增加新区域或物品。新增设计保持时代文化和空间合理性，不合并其他剧情地点、不写回剧本。'
        if asset.get('is_protagonist'):system+='\n主角必须从头到鞋完整全身、脚部不裁切、纯白无缝背景板，背景要求不改变角色肤色衣着或原画风。'
        if asset['kind']=='prop':system+='\n'+prop_image_rules.RULE
        def validate_result(result):
            format_sections(result.get('sections'));format_sections(result.get('sections_zh'))
            if asset['kind']=='prop':prop_image_rules.validate(result['sections']['主体'])
            if character:
                character_profiles.validate_image(result['sections'],asset)
                character_profiles.validate_image(result['sections_zh'],asset)
            if refs and asset['model']!='z-image' and any(f'Image {i+1}' not in result['sections']['参考图标注'] for i in range(len(refs))):raise ValueError('图像提示词遗漏参考图槽位')
            return result
        result=ai.validated_image_response(system,payload,validate_result)
        prompt=format_sections(result.get('sections'));chinese=format_sections(result.get('sections_zh'))
        if refs and asset['model']!='z-image' and any(f'Image {i+1}' not in result['sections']['参考图标注'] for i in range(len(refs))):raise ValueError('图像提示词遗漏参考图槽位')
    else:
        references='\n'.join(f'Image {i+1} 仅用于{r["role"]}：{r.get("note","")}。不混合其他槽位的身份与用途。' for i,r in enumerate(refs)) if refs and asset['model']!='z-image' else '无参考输入，依据文字描述生成概念图；未锁定参考身份。'
        visible=asset['description']+'。单人角色身份设定图，中性完整站姿，朴素背景，不表现剧情。' if character else native_prompt
        if notes:visible+='\n人工补充与修改（明确修改项优先，其余沿用）：'+notes
        parts={'参考图标注':references,'主体':visible,'特效层':'未指定额外特效。','锁定·不改变':'PRESERVE：'+asset['description']+'\nCONSTRAINTS：同一元素，结构与配色一致，不添加未指定角色或道具。','PHOTOGRAPHIC TONE':'保持原有画风、清晰主体与真实材质关系。'+str(art),'Avoid':'错误主体、身份混合、结构变形、无依据装饰、文字水印、界面元素。'}
        prompt=format_sections(parts);chinese=prompt
    if asset.get('is_protagonist'):
        prompt=prompt.replace('【主体】\n','【主体】\nFull body from head to shoes, feet fully visible, pure white seamless background. ')
        chinese=chinese.replace('【主体】\n','【主体】\n完整全身从头到鞋，脚部完整可见，纯白无缝背景板。')
    if asset['kind']=='scene':
        prompt=prompt.replace('【主体】\n','【主体】\nOverhead establishing view showing the entire environment and its boundaries, with coherent layout and circulation; open-roof view for interiors. ')
        chinese=chinese.replace('【主体】\n','【主体】\n高位俯视全景，完整展示整个空间边界、布局和通行路线；室内采用开放屋顶总览。')
    if asset['kind']=='prop':
        prompt=prompt.replace('【主体】\n','【主体】\n'+prop_image_rules.EN+' ')
        chinese=chinese.replace('【主体】\n','【主体】\n'+prop_image_rules.ZH+' ')
    return {'prompt':prompt,'prompt_zh':chinese,'prompt_notes_used':notes,'native':native,'prompt_rules':'DirectorMaster + NeoImage 六段规则'+(' + 独立角色造型档案' if character else ''),'prompt_rule_source':str(NEO_SOURCE)}


def card_brief():
    if not CARD_SOURCE.exists():raise ValueError('角色卡模板不存在：'+str(CARD_SOURCE))
    with ZipFile(CARD_SOURCE) as z:
        xml=ElementTree.fromstring(z.read('word/document.xml'))
    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    return '\n'.join(''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in xml.findall('.//w:p',ns))


def initial_character_card(asset,text_only=False):
    """Create the reference sheet first; an adopted foundation is optional."""
    if asset.get('kind')!='character':raise ValueError('四宫格角色卡只适用于角色')
    brief=card_brief()  # Verify that the user-supplied layout document remains available.
    refs=[] if text_only else list(asset.get('references',[]))
    if not text_only and asset.get('adopted') and asset['adopted'] not in {r['media'] for r in refs}:
        refs.insert(0,{'media':asset['adopted'],'role':'identity','note':'保持已采用角色的外观和画风'})
    if len(refs)>16:raise ValueError('角色卡最多支持16张参考图')
    raw=asset.get('card') or {}
    description=' '.join(str(raw.get(k,'')) for k in ('subject','style','lighting')) if raw else str(asset.get('description') or asset.get('prompt') or '')
    notes=str(asset.get('prompt_notes','')).strip()
    if notes:description+=' '+notes
    references=' '.join((f'<image{i+1}>' if len(refs)>1 else '图像')+'用于'+r.get('role','身份与画风')+'：'+r.get('note','')+'。' for i,r in enumerate(refs))
    layout='Create one vertical character reference sheet with four equal panels arranged in a precise two-by-two grid, separated by thin white lines. Every panel depicts the same character, age, hairstyle, body proportions, costume, accessories, shoes, colours, materials and visual style. The upper-left panel is a tight front-facing face close-up cropped at the collarbone, with neutral expression and upright head. The upper-right panel is a tight exact 90-degree profile face close-up, head level, not looking at the viewer. The lower-left panel is a complete front-facing full-body standing view, head to soles visible, arms naturally down; its face is entirely smooth and featureless, with no eyes, eyebrows, nose, mouth or facial lines, while preserving head shape, skin colour and hairstyle. The lower-right panel is an exact 180-degree rear full-body standing view, head to soles visible, no turned head or visible face. Use one consistent neutral grey background and soft even display lighting. Preserve the specified drawing, rendering or photographic medium; never turn a stylized character into a photograph. Keep all expressions and poses neutral. Complete unseen back and shoe details conservatively without adding ornaments. No extra people in any panel, missing accessories, cropped heads or feet, titles, labels, numbers, lettering, watermark, logos or interface elements. These four-panel directions replace any earlier single-view or collage prohibition in the appearance description.'
    prompt=references+'角色外观与画风：'+description+'。 '+layout
    return {'prompt':prompt,'prompt_zh':brief,'references':refs,'model':asset.get('model','qwen-image-2.1'),
            'width':1152,'height':2048,'wh_ratio':'9:16','layout_rule_source':str(CARD_SOURCE)}


def card_references(asset):
    if asset['kind']!='character':raise ValueError('四宫格角色卡只适用于角色元素')
    refs=[]
    if asset.get('adopted'):refs.append({'media':asset['adopted'],'role':'identity','note':'已采用角色图片，锁定原画风和身份'})
    refs.extend(r for r in asset['references'] if r['media'] not in {r['media'] for r in refs})
    if not refs:raise ValueError('请先采用一张角色图片，或绑定角色参考图，再生成四宫格角色卡')
    if len(refs)>16:raise ValueError('Qwen 角色卡一次最多16张参考，请减少引用')
    return refs


def character_card(project,asset):
    refs=card_references(asset)
    neo_rules()  # Verify the same NeoImage rule source as the foundation prompt.
    # The supplied Word brief takes precedence over the NeoImage template's
    # unequal rows, cropped head and text labels.
    prompt=format_sections({'参考图标注':'\n'.join(f'Image {i+1}: {r["role"]}; {r.get("note","")}. Preserve the original art style and the assigned identity/costume role, not the source pose, expression or background.' for i,r in enumerate(refs)),
        '主体':'Create one vertical 9:16 character reference sheet of the same individual. Exactly four equal panels in an aligned 2x2 grid with thin white divider lines. Top-left: tight frontal face close-up, cropped at the collarbone, neutral expression. Top-right: tight exact 90-degree profile face close-up, head level, no eye contact with camera. Bottom-left: complete frontal full body from top of head to shoe soles, natural neutral standing pose, arms down, facial area completely smooth and featureless: no eyes, eyebrows, nose, mouth or facial lines; preserve head outline, skin color and hairstyle. Bottom-right: complete 180-degree rear full-body view, head to shoes visible, no turning back. Single identical character per panel.',
        '特效层':'None. Remove source motion effects and dynamic pose. Neutral display lighting only.',
        '锁定·不改变':'PRESERVE: Original identity, age impression, face design, hairstyle, skin color, anatomy proportions, complete costume layers, accessories, shoes, material treatment, original colors and original artistic medium. CONSTRAINTS: Exactly four equal panels, one character per panel, no cropped heads or feet, no extra person. The bottom-left frontal full-body panel must retain the head but have a smooth featureless facial area. Top-left and top-right retain the actual facial features. Style reference has highest priority: never turn animation into live-action photography or turn live-action into animation. Missing back/shoe details must be conservative, simple extensions of the original design, with no new decoration.',
        'PHOTOGRAPHIC TONE':'Uniform neutral gray background and soft, even, restrained display lighting in all panels. Preserve the reference artistic style, linework, shading, detail density and rendering medium. Do not add photographic pores to a non-photographic character. This is a reference-card layout, not a style conversion.',
        'Avoid':'Style drift, face swapping, identity drift, age drift, hair or costume changes, changed colors, missing accessories, emotional expressions, action poses, twisted torso, hands on hips, multiple people, extra limbs, cropped heads or feet, any text, titles, numbers, labels, watermark, logo or UI.'})
    # Retain the user's NeoImage identity foundation and Word layout, while
    # expressing the actual Qwen edit instruction as one Chinese paragraph.
    reference_roles='；'.join((f'<image{i+1}>' if len(refs)>1 else '图像')+'仅提供'+r['role']+'：'+r.get('note','') for i,r in enumerate(refs))
    qwen_prompt=reference_roles+'。将同一角色整理为竖向角色设定卡，四个等大区域呈两行两列排列，使用细白分隔线。左上为锁骨以上的正面脸部近景，神态中性；右上为头部水平的精确90度侧面脸部近景，不看镜头；左下为正面完整全身自然站姿，双臂垂下，从头顶到鞋底完整入画，保留头部轮廓、肤色与发型，但脸部区域完全光滑无五官，没有眼睛、眉毛、鼻子、嘴或面部线条；右下为精确180度背面完整全身，不回头。每格只有同一个角色。左上和右上保留真实面部特征；所有格保留身份、年龄感、体态比例、完整衣着层次、配饰、鞋、原色和材质。参考图的原画风、线条、阴影与绘画或摄影媒介保持一致。四格均使用中性灰背景和均匀柔和展示光照。未显示的背面与鞋细节采用简洁克制的延续，不添加装饰。各格人物完整入画，保持自然中性姿态；画面只有角色和分隔线，不含文字、编号、标题、水印、标识或界面。'
    from . import qwen_prompts
    return {'prompt':qwen_prompt,'prompt_zh':card_brief(),'references':refs,'model':'qwen-image-2.1','width':1152,'height':2048,'wh_ratio':'9:16','ratio_follow':'','prompt_rules':'NeoImage 身份基准 + 四宫格角色卡.docx 布局 + Image2.1 编辑规范','prompt_rule_source':str(qwen_prompts.RULE_ROOT/'SKILL.md'),'layout_rule_source':str(CARD_SOURCE),'foundation_media':refs[0]['media']}
