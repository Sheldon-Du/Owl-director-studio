"""5S organization for frame cards; retain the Image2.1 edit contract."""
import re
from pathlib import Path
from . import qwen_prompts

HEADINGS = (
    '任务目标', 'Subject 主体', 'Style 风格', 'Shot 镜头与构图',
    'Setting 场景', 'Scene lighting 光照与影调', '约束与优先级',
)
RULE_PATH = Path(__file__).resolve().parents[1] / 'rules' / 'frame-5s.md'
TITLE_PATTERN = re.compile('【(' + '|'.join(re.escape(h) for h in HEADINGS) + ')】')
SECTION_KEYS = ('goal','subject','style','shot','setting','lighting','constraints')


def structured_rules():
    return '\n最高输出格式要求：不再生成rewritten_prompt或重复中文稿，改为输出five_s对象，准确包含goal、subject、style、shot、setting、lighting、constraints七个非空中文字符串，分别填写任务目标、主体、风格、镜头构图、场景、光照、约束。每项只描述当前单一瞬间，合计约500至1000字，标题由程序添加。图片标签仍写在对应字段内容中，不能省略必需主体与已选图片。rewritten_prompt_zh填空。其他清单、画幅及布局字段仍按要求返回，简洁而完整。'


def rules():
    return '\n首帧／关键帧专用组织规则（优先于通用规则的单段组织建议）：\n' + RULE_PATH.read_text(encoding='utf-8')


def validate(value, references):
    if not isinstance(value, dict):
        raise ValueError('5S 画面提示词需返回对象')
    sections=value.get('five_s')
    if sections is not None:
        if not isinstance(sections,dict) or any(not isinstance(sections.get(k),str) or not sections[k].strip() for k in SECTION_KEYS):
            raise ValueError('5S字段需完整填写goal、subject、style、shot、setting、lighting、constraints')
        value={**value,'rewritten_prompt':' '.join('【'+h+'】'+sections[k].strip() for k,h in zip(SECTION_KEYS,HEADINGS)),'rewritten_prompt_zh':''}
    prompt = value.get('rewritten_prompt')
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError('5S 画面提示词为空')
    titles = list(TITLE_PATTERN.finditer(prompt))
    if [m[1] for m in titles] != list(HEADINGS) or prompt[:titles[0].start()].strip():
        raise ValueError('5S 提示词需依次包含：' + '、'.join('【'+h+'】' for h in HEADINGS))
    for index, match in enumerate(titles):
        end = titles[index+1].start() if index+1 < len(titles) else len(prompt)
        if not prompt[match.end():end].strip():
            raise ValueError('5S 提示词内容为空：' + match[1])
    # The model accepts a single editing instruction; card sections stay readable
    # through their labels, without a second duplicate prompt or JSON object.
    normalized = re.sub(r'\s*\n\s*', ' ', prompt).strip()
    result = qwen_prompts.validate({**value, 'rewritten_prompt': normalized},
                                   {'kind': 'scene', 'references': references})
    return {**result, 'prompt_structure': '5s-v1'}


def with_layout(prompt, reference_count):
    """Insert the layout image without breaking section order or asset slots."""
    if reference_count == 1:
        prompt = prompt.replace('图像', '<image2>')
    else:
        prompt = re.sub(r'<image(\d+)>', lambda m: f'<image{int(m[1])+1}>', prompt)
    instruction = '以<image1>为构图布局参考，保留主体位置、相对大小、透视、姿态与遮挡；去掉简模、网格和辅助标记，不复制预演颜色，真实外观以其余资产图片为准。'
    marker = '【Shot 镜头与构图】'
    return prompt.replace(marker, marker + instruction, 1) if marker in prompt else instruction + prompt
