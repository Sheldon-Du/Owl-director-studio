"""Conservative source-world constraints; no extra AI request is required."""
import re

ANCIENT=('帝都','司礼监','蟒袍','锦衣卫','宦官','太监','东厂','皇帝','朕','古代','明朝','清朝','唐朝','宋朝','北宋','南宋','古风','武侠')
MODERN_PROPS=('钢笔','收音机','手机','智能手机','电脑','电视机','汽车','电灯','霓虹灯','电梯','冰箱','电话机','手枪','监控摄像头')
SPEED=re.compile(r'慢镜(?:头)?|慢放|倍速|子弹时间|延时摄影|slow[- ]motion|time[- ]lapse|speed[- ]up',re.I)


def speed_change(text):
    """Explicit prohibitions are compatible with natural-time production."""
    term=r'(?:慢镜(?:头)?|慢动作|慢放|倍速|子弹时间|延时摄影|slow[- ]motion|time[- ]lapse|speed[- ]up|1/\d+\s*(?:速度|慢))'
    negative=r'(?:不(?:得|要|能)?(?:使用|采用|进行|做|用)?|无|禁止(?:使用|采用)?|避免(?:使用|采用)?|do\s+not\s+use|not|no|without)\s*(?:任何\s*)?'
    def prohibition(match):
        prefix=str(text)[max(0,match.start()-3):match.start()]
        return match.group(0) if re.search(r'不是|并非|不能|不要',prefix) else ''
    cleaned=re.sub(negative+term+r'(?:\s*(?:[、,，/和或及]|and|or)\s*'+term+r')*',prohibition,str(text),flags=re.I)
    return bool(re.search(term,cleaned,re.I))


def contract(project):
    source=str(project.get('story',''));brief=project.get('video_brief',{})
    markers=[w for w in ANCIENT if w in source]
    era=str(project.get('parameters',{}).get('时间年代',''))
    # An explicit opening era is evidence even in an ordinary village story
    # without court/martial-arts vocabulary. A modern person's historical
    # reference elsewhere in the story is not itself an opening-era contract.
    opening_era=bool(re.match(r'^\s*(?:北宋|南宋|明朝|清朝|唐朝|宋朝)',source))
    ancient=opening_era or len(markers)>=2 or bool(re.search('古代|古风|明朝|清朝|唐朝|宋朝|北宋|南宋|武侠',era))
    override=bool(brief.get('allow_world_change')) and project.get('story_policy')=='creative'
    return {'source_world':'古风/武道背景' if ancient else '以原文明确的时代与技术条件为准','source_evidence':markers,
            'configured_era':era,'world_change_allowed':override,'target_world':brief.get('target_world','') if override else '',
            'unsupported_modern_props':[w for w in MODERN_PROPS if ancient and w not in source and not override],
            'rules':['导演风格只能影响构图、色彩、光照、剪辑与表演，不把风格范例的时代、人物、物件、台词复制进故事。',
                     '架空/奇幻并不表示可以任意混入现代技术。穿越者的前世知识、内心类比与当前世界的实物分开。',
                     '未明确允许改变世界观时，创意编排仍保留原文的时代、技术水平、制度与身份。',
                     '正文与拍摄建议均使用自然实时动作，禁止慢镜、慢放、倍速、子弹时间和延时摄影。']}


def validate(project,script):
    world=contract(project)
    if project.get('story_policy','faithful')!='faithful':
        found=[w for w in world['unsupported_modern_props'] if w in script]
        if found:raise ValueError('剧本时代与原故事不一致：古风背景新增了无原文依据的现代器物（'+'、'.join(found)+'）；请保留原时代与技术条件')
        if speed_change(script):raise ValueError('剧本包含慢镜、慢放或倍速要求；请改为自然实时动作，不用速度变化凑时长')
    return {'source_world':world['source_world'],'source_evidence':world['source_evidence'],'world_change_allowed':world['world_change_allowed'],'target_world':world['target_world'],'checked':True}
