"""Flova-derived writing methods, adapted to the user's local production rules."""
import hashlib
import json
import math
import re

PROFILES={
    'director':{'title':'DirectorMaster 原有流程','rules':[]},
    'story':{'title':'完整故事创作','rules':[
        '先用一句话明确主题与故事变化，依据成片规格安排建立、发展、转折和收束；节奏服从故事而非平均切段。',
        '剧本写清场景、可见动作、准确对白、画外音及表演；镜头建议区分景别、角度和运动。',
        '同一角色的年龄、服装或状态变化逐项注明；不同物理地点独立命名，明确主要动作区与道具位置。',
        '分别规划背景音乐、独立旁白、角色对白和音效；声音特征、准确文本及覆盖节拍清楚对应。']},
    'adaptation':{'title':'已有剧本忠实适配','rules':[
        '输入是既有剧本。严格保留原人物、场景顺序、因果、动作结果、对白和旁白原句，仅作技术性分场与拍摄建议。',
        '不得用规则范例补写故事，不为时长限制删除事实或改变台词；容量不足列为待用户核对事项。',
        '每个独立角色、道具和物理场景分别命名；多年龄与多造型保留身份连续性，原文未给出的外观留待手动资产设计。',
        '对白与独立画外音分别标注，音色与语调及覆盖节拍明确，避免在视频和独立音轨重复同一旁白。']},
    'product':{'title':'产品广告创作','rules':[
        '先明确产品、受众、给定卖点、视觉基调与品牌要求，不编造产品功能、规格、功效或宣传承诺。',
        '围绕已提供的使用场景设计广告；素材支持时至少提出两种独立应用场景，缺少依据则列为待补充建议。',
        '区分产品出镜的主展示与不含产品的功能、环境、纹理辅助段落；每段只表达一个重点，并明确产品是否出镜。',
        '按建立环境、使用展示、细节或情绪、品牌收束组织节奏；剪切有明确视觉变化，运镜与节奏服务卖点。',
        '品牌、包装、准确文案及尾版停留遵守用户要求；Logo或字幕可列入后期合成计划，不擅自重绘已有产品或Logo。']},
}
BRIEF_FIELDS=('visual_style','output_language','audience','requirements','product_name','selling_points','use_scenarios','brand_requirements')
DOC_KEYS=('video_spec','video_spec_markdown','script_workflow','script_workflow_plan')


def validate(project):
    workflow=project.get('script_workflow','director')
    if workflow not in PROFILES:raise ValueError('请选择有效的剧本创作流程参考')
    if workflow=='adaptation' and project.get('story_policy','faithful')=='creative':raise ValueError('已有剧本忠实适配请选择原文直用或忠于故事剧本化')
    brief=project.get('video_brief',{})
    if not isinstance(brief,dict):raise ValueError('成片规格必须为对象')
    if set(brief)-set(BRIEF_FIELDS)-{'logo_seconds','allow_world_change','target_world'}:raise ValueError('成片规格包含不支持的字段')
    for key in BRIEF_FIELDS:
        if key in brief and (not isinstance(brief[key],str) or len(brief[key])>4000):raise ValueError('成片规格文字需在4000字以内')
    if 'allow_world_change' in brief and not isinstance(brief['allow_world_change'],bool):raise ValueError('世界观改编选项必须为布尔值')
    if 'target_world' in brief and (not isinstance(brief['target_world'],str) or len(brief['target_world'])>1000):raise ValueError('目标世界观需为1000字以内的文字')
    if brief.get('allow_world_change') and (project.get('story_policy')!='creative' or not brief.get('target_world','').strip()):raise ValueError('改变时代与世界观需选择AI编排并填写目标时代与技术条件')
    if 'logo_seconds' in brief:
        value=brief['logo_seconds']
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=min(30,float(project['duration'])):raise ValueError('品牌尾版时长需为0至30秒，且不超过成片时长')


def enabled(project):return project.get('script_workflow','director')!='director' or any(k in project.get('video_brief',{}) for k in (*BRIEF_FIELDS,'logo_seconds'))


def director_only(project):
    """The retired UI reference modes do not affect new screenplay writing."""
    return {**project,'script_workflow':'director',
            'video_brief':{k:v for k,v in project.get('video_brief',{}).items() if k in ('allow_world_change','target_world')}}


def input_values(project):
    # Preserve existing screenplay hashes for every project that has not opted in.
    if project.get('script_workflow','director')=='director' and not project.get('video_brief'):return None
    return {'script_workflow':project.get('script_workflow','director'),'video_brief':project.get('video_brief',{})}


def spec(project):
    from . import story_world
    validate(project)
    brief=project.get('video_brief',{});params=project.get('parameters',{})
    return {'title':project.get('name','未命名项目'),'type':params.get('题材类型') or project.get('script_mode','未指定'),
            'aspect_ratio':params.get('画幅比例','16:9'),'duration_seconds':float(project['duration']),
            'visual_style':brief.get('visual_style') or params.get('视觉风格') or params.get('视觉调性') or '按 DirectorMaster 设定',
            'output_language':brief.get('output_language') or '中文','audience':brief.get('audience',''),
            'requirements':brief.get('requirements',''),'product':{k:brief.get(k,'') for k in ('product_name','selling_points','use_scenarios','brand_requirements')} if project.get('script_workflow')=='product' else {},
            'logo_seconds':brief.get('logo_seconds',0) if project.get('script_workflow')=='product' else 0,'story_world':story_world.contract(project),'image_model':'Image2.1 / Qwen-Image-2.1','video_model':'MiniMax H3',
            'preview_resolution':'480p','max_generation_seconds':30,'h3_prompt_language':'English','motion_timing':'自然实时动作，禁止变速压缩'}


def markdown(project):
    s=spec(project)
    lines=['# Final Video Spec','',f"- 标题：{s['title']}",f"- 类型：{s['type']}",f"- 比例：{s['aspect_ratio']}",f"- 成片时长：{s['duration_seconds']:g} 秒",
           f"- 视觉风格：{s['visual_style']}",f"- 对白 / 旁白语言：{s['output_language']}",f"- 受众：{s['audience'] or '未指定'}",f"- 剧本创作参考：{PROFILES[project.get('script_workflow','director')]['title']}",
           '- 图片：Image2.1 默认，按已有提示词规则；参考图保持原绑定', '- 视频：MiniMax H3，英文提示词，480p 一采预览，逐段记录种子',
           '- 每个生成任务最多30秒；更长内容由H3阶段分步规划', '- 动作使用自然发生的时长；内容过多时延长或调整内容', '', '## 创作要求','',s['requirements'] or '按已保存的 DirectorMaster 设定。']
    lines+=['',f"- 世界观：{s['story_world']['target_world'] if s['story_world']['world_change_allowed'] else s['story_world']['source_world']}",'- 导演风格服从原故事时代与技术条件；未明确允许时保持原世界观。']
    if project.get('script_workflow')=='product':
        lines+=['','## 产品与品牌','']+[f"- {label}：{s['product'][key] or '待补充'}" for key,label in [('product_name','产品'),('selling_points','已确认卖点'),('use_scenarios','使用场景'),('brand_requirements','品牌与包装要求')]]
        lines+=[f"- 尾版停留：{s['logo_seconds']:g} 秒"]
    return '\n'.join(lines)+'\n'


def context(project):
    if not enabled(project):return {}
    validate(project)
    profile=PROFILES[project.get('script_workflow','director')]
    return {'writing_method':profile,'final_video_spec':spec(project),
            'existing_elements':[{'element_id':a['id'],'name':a['name'],'kind':a['kind'],'reference_count':len(a.get('references',[])),'has_adopted_image':bool(a.get('adopted'))} for a in project.get('assets',[])],
            'production_constraints':['原文保留/忠实剧本化/AI编排以用户所选 story_policy 为准。',
                '已有参考图优先复用；未做图像分析不得声称已看过参考图。',
                '当前只编写剧本和创作建议，资产参数必须在正文完成后由用户手动提取。',
                '后续镜头与美术、分镜提示词继续按 DirectorMaster 原生规则生成，H3 按当前专用规则转写。',
                '节拍是叙事规划，不是最终分镜或生成任务；不强制长镜头，不均分秒数；正文与镜头建议均禁止慢镜、慢放、倍速、子弹时间和延时摄影。',
                '阶段推进通过用户手动操作和已有确认按钮；不自动生成图片、视频或音频。']}


PLAN_SCHEMA='''额外返回 workflow_plan:{logline:string,beats:[{id:B01等,source_excerpt:剧本正文中的原句,location:string,story_content:string,camera:string,estimated_seconds:number,dialogue:[{speaker:string,text:正文中的准确原句}],voiceover:正文中的准确画外音或空字符串,product_visible?:boolean}],audio_layers:[{id:string,type:bgm|narration|dialogue|sfx,beat_ids:[节拍id],text:string,voice:string,tone:string,note:string}],continuity_notes:[string],review_notes:[string]}。
最多给12个关键叙事节拍，长片以段落规划。source_excerpt必须逐字出现在最终script正文中；对白、旁白文本必须来自最终正文。对白和旁白不得在规划阶段再次改写。非创意模式保持原文顺序，未明确的事实列入review_notes，不得写成事实。estimated_seconds依据动作、对白与停留自然估计，不能均分；超过目标片长时标明需要延长或调整，不加速，不省略情节。BGM、音效text是声音描述；narration和dialogue的text须逐字存在正文。音乐是可审阅建议，用户可省略。每条音轨指定覆盖节拍，独立旁白只出现在独立音轨中，角色对白保留在视频声音中。'''


def instruction(project):
    if not enabled(project):return ''
    return '\n按照 writing_method 与 final_video_spec 编写。DirectorMaster 与用户原文忠实度及自然时序要求优先。'+PLAN_SCHEMA


def plan_hash(project,script):
    values=spec(project);values.pop('title',None)
    return hashlib.sha256(json.dumps([script,project.get('script_workflow','director'),values],ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def normalize_plan(raw,project,script):
    if not isinstance(raw,dict) or not str(raw.get('logline','')).strip():raise ValueError('创作流程规划缺少一句话梗概')
    beats=raw.get('beats');audio=raw.get('audio_layers',[])
    if not isinstance(beats,list) or not 1<=len(beats)<=12:raise ValueError('创作流程规划需包含1至12个关键节拍')
    clean=[];ids=set();last_position=-1
    for i,beat in enumerate(beats):
        if not isinstance(beat,dict):raise ValueError('创作节拍格式无效')
        excerpt=str(beat.get('source_excerpt','')).strip();bid=str(beat.get('id',f'B{i+1:02}'))
        if not excerpt or excerpt not in script:raise ValueError('创作节拍缺少有效的剧本原文依据')
        position=script.find(excerpt,max(0,last_position)) if project.get('story_policy','faithful')!='creative' else script.find(excerpt)
        if position<0:raise ValueError('忠实创作规划不得改变原剧本事件顺序')
        last_position=position
        if not bid or bid in ids:raise ValueError('创作节拍编号重复或为空')
        ids.add(bid)
        seconds=beat.get('estimated_seconds')
        if isinstance(seconds,bool) or not isinstance(seconds,(int,float)) or not math.isfinite(seconds) or not 0<seconds<=14400:raise ValueError('创作节拍需填写有效的自然时长估计')
        dialogues=beat.get('dialogue',[])
        if not isinstance(dialogues,list) or any(not isinstance(d,dict) or not d.get('text') or d['text'] not in script for d in dialogues):raise ValueError('创作规划的对白必须来自剧本正文原句')
        voiceover=str(beat.get('voiceover',''))
        if voiceover and voiceover not in script:raise ValueError('创作规划的旁白必须来自剧本正文原句')
        if not str(beat.get('story_content','')).strip():raise ValueError('创作节拍缺少故事内容')
        from . import story_world
        if story_world.speed_change(str(beat.get('camera',''))):raise ValueError('创作镜头建议需使用自然实时动作，不能推荐慢放或倍速')
        clean.append({**{k:str(beat.get(k,'')) for k in ('location','story_content','camera')},'id':bid,'source_excerpt':excerpt,'estimated_seconds':seconds,'dialogue':dialogues,'voiceover':voiceover,**({'product_visible':beat['product_visible']} if isinstance(beat.get('product_visible'),bool) else {})})
    if not isinstance(audio,list) or len(audio)>16:raise ValueError('音频规划格式无效')
    clean_audio=[];audio_ids=set()
    for layer in audio:
        if not isinstance(layer,dict) or layer.get('type') not in ('bgm','narration','dialogue','sfx'):raise ValueError('音轨类型无效')
        aid=str(layer.get('id',''));scope=layer.get('beat_ids')
        if not aid or aid in audio_ids or not isinstance(scope,list) or not scope or any(b not in ids for b in scope):raise ValueError('音轨需使用独立编号并关联有效节拍')
        audio_ids.add(aid);text=str(layer.get('text',''))
        if layer['type'] in ('narration','dialogue') and (not text or text not in script):raise ValueError('音频规划的对白和旁白必须来自剧本原句')
        clean_audio.append({**{k:str(layer.get(k,'')) for k in ('type','text','voice','tone','note')},'id':aid,'beat_ids':scope})
    notes={key:raw.get(key,[]) for key in ('continuity_notes','review_notes')}
    if any(not isinstance(value,list) or any(not isinstance(s,str) for s in value) for value in notes.values()):raise ValueError('创作规划核对事项格式无效')
    estimated=sum(b['estimated_seconds'] for b in clean)
    if estimated>float(project['duration'])+.01:notes['review_notes']=[*notes['review_notes'],f'节拍自然时长估计共 {estimated:g} 秒，超过目标 {float(project["duration"]):g} 秒；请延长片长或调整内容，不能压缩动作。']
    return {'logline':str(raw['logline']),'beats':clean,'audio_layers':clean_audio,**notes,'estimated_seconds':estimated,'source_hash':plan_hash(project,script)}


def documents(project,script,raw=None):
    if not enabled(project):return {}
    result={'video_spec':spec(project),'video_spec_markdown':markdown(project),'script_workflow':project.get('script_workflow','director')}
    if raw is not None:result['script_workflow_plan']=normalize_plan(raw,project,script)
    return result


def invalidate(docs):
    for key in DOC_KEYS:docs.pop(key,None)


def refresh(project):
    docs=project.setdefault('documents',{});plan=docs.get('script_workflow_plan')
    if plan and (not enabled(project) or plan.get('source_hash')!=plan_hash(project,docs.get('script',''))):docs.pop('script_workflow_plan',None)
    if enabled(project):docs.update(documents(project,docs.get('script','')))
    else:invalidate(docs)


def storyboard_input(project):
    script=project.get('documents',{}).get('script','')
    from . import script_source
    if not script.strip():script=script_source.text(project)
    if script_source.kind(project)=='story':return script
    if not enabled(project):return script
    plan=project['documents'].get('script_workflow_plan')
    if plan and plan.get('source_hash')!=plan_hash(project,script):raise ValueError('剧本创作规划已过期，请按当前正文重新编写或确认')
    return script+'\n\n【制作规格与创作建议：不是新剧情】\n'+json.dumps({'spec':spec(project),'workflow_plan':plan,'rules':PROFILES[project.get('script_workflow','director')]['rules'],'instruction':'以以上已确认剧本为情节与准确台词依据，建议不增加事实或修改情节。仍用 DirectorMaster 原生分镜规则和自然动作时长。'},ensure_ascii=False)
