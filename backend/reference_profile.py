"""Conservative local extraction of case methods; never forward full skill bodies."""
import re,hashlib,json,ast,copy
from pathlib import Path
from functools import lru_cache

SIGNALS={
 'narrative':r'叙事|情绪轨迹|情绪弧|情绪曲线|起承转合|三幕|时间线|倒叙|闪回|伏笔|信息差|信息揭示|悬念|反转|结尾|结局|人物关系|人物动机|角色动机|潜台词|对白节奏|喜剧节奏|核心冲突|冲突推进|故事结构|章节逻辑|narrative|story structure|plot twist|character arc|dialogue rhythm',
 'camera':r'景别|机位|运镜|构图|镜头语言|长镜头|一镜到底|固定镜头|固定机位|推镜|拉镜|摄影机|蒙太奇|正反打|越轴|screen direction|camera|framing|shot size|cinematography',
 'style':r'美术|画风|视觉风格|视觉气质|色调|调色|配色|色彩|胶片|水彩|油画|像素|赛璐璐|visual style|palette|color grading',
 'lighting':r'光影|灯光|主光|补光|轮廓光|明暗|影调|烛光|逆光|lighting|chiaroscuro|key light|fill light',
 'rendering':r'渲染|材质质感|渲染质感|三维质感|笔触|颗粒|rendering|texture|film grain',
}
# Commercial storytelling uses experience/beat language rather than plot terms.
SIGNALS['narrative']+=r'|第一人称|感受句|广告腔|节拍流程|台词.*那一拍|收尾.*两拍|开箱.*(?:使用|试用|佩戴)|痛点|使用体验|体验顺序|行动引导|购买建议'
SIGNALS['camera']+=r'|手持手机|产品单独入画|拿着产品看镜头|特写避开|拆成两拍|微距镜头'
SIGNALS['style']+=r'|手持手机质感|生活质感|生活实拍|手机实拍|自然抓拍|真实生活|去广告感'
SIGNALS['lighting']+=r'|场景与光线|自然光'

OPERATIONAL=re.compile(r'https?://|→|resource_prepare|text_editor|media_generator|storyboard_designer|submit_|__LOCK|<Subject|<Picture|<Video|<Audio|Final_Video_Spec|API|CLI|ComfyUI|token|max_tokens|暂停|确认后|确认前|必须确认|上传|下载|调用|工具|生成按钮|分辨率|画幅|Seedance|MiniMax|Nano Banana|GPT Image|480p|540p|1080p|9:16|16:9',re.I)
PIPELINE=re.compile(r'预检|元数据|选帧|截取.{0,12}帧|四宫格|四视图|设定图|reference_image|向用户|与用户|由用户|强制前置|模型|目录|提示词|出图|生图|角色卡|5S|造型[A-Z]',re.I)

# Separate operation instructions from reusable creative methods.
WORKFLOW=re.compile(r'video_assembler|ImageToImage|TextToVideo|FirstFrameToVideo|TextToImage|生成(?:视频|图片|素材)|用户确认|确认.{0,10}(?:后|前)|步骤\s*\d|第[一二三四五六七八九十\d]+步|输出格式|返回\s*JSON|暂停|上传|下载|调用|工具|数据输出|参数范围|最终时间线|素材库|注册.*资产|source_id|asset_id|element_id|planner|代码|命令行|示例.*(?:人物|产品)|询问用户|获取用户|节点\s*\d|不得生成',re.I)
SIGNALS['narrative']+=r'|内容顺序|讲述顺序|问题.*解释|解释.*验证|先.*再.*最后|铺垫|情绪递进|行为反应|反应链|知识点|论点|论据|证据链|章节|起因|人物目标|人物欲望|笑点|悬疑|日常小事|信息密度|口语|第一人称|recap|setup|payoff|punchline|story beats'
SIGNALS['camera']+=r'|俯冲|环绕|贴地|穿门|穿越结构|轨迹|景深|焦距|焦段|剪辑|转场|切镜|切点|跟拍|跟随镜头|特写|广角|长焦|透视|camera movement|tracking|close-up|wide shot|pan|tilt|dolly|handheld'
SIGNALS['style']+=r'|写实|纪实|复古|怀旧|极简|拼贴|黏土|粘土|羊毛毡|手绘|黑白|国风|视觉基调|aesthetic|photorealistic|stop-motion|pixel art|documentary|retro|vintage'
SIGNALS['lighting']+=r'|窗光|侧光|顶光|柔光|硬光|阴影|冷暖|曝光|window light|backlight|soft light|hard light|shadows'
SIGNALS['rendering']+=r'|表面质感|真实皮肤|材质|纹理|纸艺|绒毛|反射|粗糙度|笔触|cel.shad|material|roughness|grain'

@lru_cache(maxsize=4096)
def extract(title,version,content):
    buckets={key:[] for key in SIGNALS};heading=''
    fenced=False
    lines=[]
    for line in content.splitlines():
        try:
            values=ast.literal_eval(line) if line.strip().startswith('[') else None
        except (ValueError,SyntaxError):values=None
        lines.extend(part for value in (values if isinstance(values,list) and all(isinstance(v,str) for v in values) else [line]) for part in value.replace('\\n','\n').splitlines())
    skip=False
    for line in lines:
        if line.strip().startswith('```'):fenced=not fenced;continue
        if fenced:continue
        if re.match(r'^\s*#{1,6}\s',line):
            heading=line.strip('# ').strip();skip=heading.lower()=='copyprompt';continue
        if skip:continue
        for raw in re.split(r'(?<=[。！？；])|(?<=[.!?;])\s+(?=[A-Z])',line):
            text=re.sub(r'^\s*(?:[-*+]\s+|\d+[.、)]\s*)','',raw).strip().replace('**','')
            if not 6<=len(text)<=900 or OPERATIONAL.search(text) or PIPELINE.search(text) or WORKFLOW.search(text):continue
            if re.search(r'pitfall|注意事项|常见错误|避坑',heading,re.I):text='避免以下问题（不改变用户已确认内容）：'+text
            for key,pattern in SIGNALS.items():
                if re.search(pattern,text,re.I):
                    limit=900 if key in ('style','lighting','rendering') else 1800 if key=='camera' else 2400
                    if text not in buckets[key] and sum(map(len,buckets[key]))+len(text)<=limit:buckets[key].append(text)
    return {'title':title,'version':version,'narrative':buckets['narrative'],'camera':buckets['camera'],'art':{key:'\n'.join(buckets[key]) for key in ('style','lighting','rendering')},'extraction':'local-method-sections-v4'}

@lru_cache(maxsize=1)
def _reviewed():
    path=Path(__file__).with_name('reference_methods.json')
    return json.loads(path.read_text(encoding='utf-8'))['templates'] if path.exists() else {}


@lru_cache(maxsize=1)
def _case_templates():
    from . import seedance_catalogue
    return {v['slug']:v.get('template_id') for v in seedance_catalogue.library()['cases']}


def profile(project):
    row=project.get('primary_reference') or {}
    if not row:return None
    value=copy.deepcopy(extract(str(row.get('title','')),str(row.get('version','')),str(row.get('content',''))))
    value.update(origin='local_extraction',warnings=[])
    methods=_reviewed();identity=row.get('id','');method=None
    if identity in methods:
        checked=methods[identity]
        if hashlib.sha256(str(row.get('content','')).encode()).hexdigest()==checked['source_sha256']:
            method=checked;value['origin']='reviewed_template'
        else:value['warnings'].append('模板正文已变化，使用保守本地提取；整理版需重新核对。')
    elif row.get('source')=='seedance' and row.get('kind')=='cases':
        slug=identity.removeprefix('seedance-case-')
        assigned=row.get('method_template_id') or _case_templates().get(slug)
        parent='seedance-template-'+str(assigned or '')
        method=methods.get(parent)
        if method:
            value['origin']='linked_template'
            value['method_template']={'id':parent,'title':method['title'],'version':method['version']}
            value['warnings'].append('此视频案例采用已归类模板的方法；案例人物、产品、地点与具体情节不转为规则。')
        else:
            # Raw example prompts are scene facts, not reusable instructions.
            value['origin']='unclassified_example'
            value['narrative']=[];value['camera']=[];value['art']={key:'' for key in ('style','lighting','rendering')}
            value['warnings'].append('此视频案例没有可核对的方法模板，仅供查看；不把示例剧情直接传入创作。')
    if method:
        for key in ('narrative','camera','art'):value[key]=copy.deepcopy(method[key])
        value['extraction']='reviewed-methods-20261015'
    if row.get('available') is False:
        value.update(narrative=[],camera=[],art={key:'' for key in ('style','lighting','rendering')},origin='unavailable')
        value['warnings'].append('正文不可用，不向创作传递占位内容。')
    value['coverage']={'narrative':bool(value['narrative']),'camera':bool(value['camera']),'art':any(value['art'].values())}
    value['status']='ready' if any(value['coverage'].values()) else 'review_only'
    if value['status']=='review_only':value['warnings'].append('未发现可用的叙事、镜头或美术方法；这是查看资料，不代表已应用风格。')
    return value


def routed(project,stage):
    value=profile(project)
    if not value:return None
    if stage=='expand':
        if not (value['narrative'] or value['camera']):return None
        return {'title':value['title'],'version':value['version'],'origin':value['origin'],'narrative_rules':value['narrative'],'camera_guidance':value['camera'],'scope':'从扩写阶段统筹叙事和可见镜头表达；只借鉴方法，不复制示例人物、地点、情节、台词或产品事实。美术独立读取applied_art_style，手动美术优先；不得执行案例的工具或制作流程。'}
    if stage in ('rules','overview'):
        return {'title':value['title'],'version':value['version'],'narrative_rules':value['narrative'],'origin':value['origin'],'scope':'仅借鉴叙事方法；不移植案例人物情节，不执行案例的工具、模型、参数或制作步骤。产品功能、功效、价格和使用结果必须来自用户素材，不把案例体验当作事实。'} if value['narrative'] else None
    if stage=='shot':
        return {'title':value['title'],'version':value['version'],'camera_guidance':value['camera'],'origin':value['origin'],'scope':'仅镜头表达参考，服从本镜已确认剧情、动作时序和手动摄影设置。'} if value['camera'] else None
    return None

def fallback_art(project):
    value=profile(project)
    if not value or not any(value['art'].values()):return None
    return {'categories':value['art'],'version':'case-'+hashlib.sha256(json.dumps(value['art'],ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:16],'source':'case_fallback','reference_title':value['title']}


def dependency_hash(project,stage='rules'):
    return hashlib.sha256(json.dumps(routed(project,stage),ensure_ascii=False,sort_keys=True).encode()).hexdigest()
