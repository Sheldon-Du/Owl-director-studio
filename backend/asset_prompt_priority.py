"""Preserve provenance when appearance profiles become image-writing input."""
from . import visual_schema as vs

RULE='''外观依据按优先级执行：用户本次明确修改 > 剧本明示（explicit） > AI设计建议（suggested）。script_explicit是必须保留的身份、结构和造型锚点，优先写在主体描述前部，准确呈现，不弱化、不替换、不通过其他人物补充。ai_suggested仅填补原文与人工要求未确定的属性，描述简短克制；出现冲突时舍弃建议。建议的装饰、光效和细节不得抢占主体，不把建议当作剧本事实。user_locked是已有人工确认的特征，保持不变，除非本次人工明确修改。场景新增陈设同样属于低优先级设计。这里只调整语义优先级，不输出未经模型支持的括号数字权重语法。'''

def contract(asset):
    kind=asset['kind'];profile=asset.get('visual_profile') or {}
    if kind=='character':profile=vs.from_legacy(kind,profile,asset['name'])
    result={'script_explicit':[],'user_locked':[],'ai_suggested':[]}
    for path,item in vs.flatten(kind,profile).items():
        if kind=='character' and path.startswith('personality.'):continue
        value=item.get('value');source=item.get('source')
        if not value or source not in ('explicit','user','suggested'):continue
        key={'explicit':'script_explicit','user':'user_locked','suggested':'ai_suggested'}[source]
        result[key].append({'field':path,'value':value})
    return result
