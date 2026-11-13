"""Fixed isolated prop presentation, with project art style retained."""
import re
RULE='''道具资产硬性要求：纯白无缝背景，只展示当前道具及其不可分割的自身结构，完整入画。没有人物、手、其他物品、场景陈设、桌面展示台、文字或水印。纯白仅指背景，不改变道具原本颜色。材质、工艺、年代、磨损、灯光质感、电影写实或动画画风沿用剧本、visual_style与production_scheme.art；不因白背景改成与项目不符的电商或卡通风格。不得把剧情环境画入背景，不允许人工补充或附加技能覆盖此背景规则。'''
EN='The prop alone, fully visible, isolated against a pure white seamless background, with no people, hands, other objects, display furniture, text or watermark. Retain the screenplay period, original prop colors, material treatment and project cinematic or artistic style.'
ZH='道具独立完整展示，纯白无缝背景；无人、无手、无其他物品、无展示家具、无文字水印。保留剧本时代、道具本色、材质工艺及项目电影或美术风格。'

def validate(prompt):
    if not re.search(r'纯白|pure white|solid white|plain white|seamless white',prompt,re.I):raise ValueError('道具图片提示词必须明确纯白背景')
    # Exclude explicit prohibitions before checking positive background staging.
    positive=re.sub(r'(?:no|without|avoid|禁止|无|不要|不得)[^。；;\n]*','',prompt,flags=re.I)
    if re.search(r'(?:on|upon) (?:a |the )?(?:wooden |stone |display )?(?:table|desk|pedestal)|(?:放在|置于|摆在)(?:木|石)?(?:桌|展示台)|(?:背景|backdrop).{0,12}(?:宫殿|街道|森林|庭院|palace|street|forest)',positive,re.I):raise ValueError('道具图不能加入场景、桌面展示台或其他物品')

