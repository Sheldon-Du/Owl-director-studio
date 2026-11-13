"""Apply instruction-only skills to production stages, with immutable provenance."""
import hashlib
import json
from . import site_skills

STAGES=('script_plan','script','storyboard_outline','storyboard')
LABELS={'script_plan':'改编提纲','script':'剧本正文','storyboard_outline':'分镜汇总','storyboard':'逐镜细化'}


def config(project):
    value=project.get('creative_skills',{'mode':'auto','ids':[]})
    if not isinstance(value,dict) or set(value)-{'mode','ids'} or value.get('mode') not in ('auto','manual'):
        raise ValueError('创作技能请选择自动匹配或手动选择')
    ids=value.get('ids',[])
    if not isinstance(ids,list) or len(ids)>12 or any(not isinstance(s,str) for s in ids) or len(set(ids))!=len(ids):
        raise ValueError('创作技能ID需为不重复的列表，最多12个')
    return {'mode':value['mode'],'ids':ids}


def selected_task(project):
    selected=project.get('script_task','auto')
    return ('adapt' if project.get('story_policy') in ('faithful','screenplay') else 'expand') if selected=='auto' else selected


def resolve(project,stage):
    if stage not in STAGES:raise ValueError('不支持的技能应用阶段')
    frozen=project.get('_creative_rule_bundles',{}).get(stage)
    if frozen:return frozen
    from .agent import TOOLS
    selection=config(project);available=site_skills.locations();enabled=site_skills.flags()
    task=selected_task(project);skills=[];warnings=[]
    ids=selection['ids'] if selection['mode']=='manual' else [s['id'] for s in available.values() if s.get('builtin') and s.get('automatic') and enabled.get(s['id'],True) and stage in s.get('stages',[]) and (not s.get('tasks') or task in s['tasks'])]
    for sid in ids:
        item=available.get(sid)
        if not item:raise ValueError('所选创作技能不存在：'+sid)
        from . import skill_usage
        if stage in ('script_plan','script') and skill_usage.usage(item) not in ('writing','genre'):continue
        if stage not in item.get('stages',[]):continue
        if item.get('tasks') and task not in item['tasks']:raise ValueError(item['name']+'不适用于当前剧本任务，请调整技能选择')
        if not enabled.get(sid,True):raise ValueError(item['name']+'已停用，请重新选择或启用')
        loaded=site_skills.load(sid,TOOLS)
        if loaded['missing_tools']:raise ValueError(item['name']+'缺少执行能力：'+'、'.join(loaded['missing_tools'])+'；可讨论方法，不能据此执行本阶段')
        digest=hashlib.sha256(json.dumps([item['text'],loaded['references']],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
        skills.append({'id':sid,'name':item['name'],'version':item.get('version','1'),'digest':digest,
                       'reason':'用户手动选择' if selection['mode']=='manual' else '匹配当前任务与阶段',
                       'instructions':loaded['instructions'],'references':loaded['references']})
    chosen={s['id'] for s in skills}
    for s in skills:
        conflicts=chosen.intersection(available[s['id']].get('conflicts_with',[]))
        if conflicts:raise ValueError('创作技能存在未解决冲突：'+s['name']+' 与 '+'、'.join(conflicts)+'；请在生成前调整选择')
    if selection['mode']=='manual' and not skills:warnings.append('本阶段没有所选专项技能，仍执行DirectorMaster及主任务规则')
    return {'stage':stage,'mode':selection['mode'],'skills':skills,'warnings':warnings,
            'priority':'用户明确要求与锁定项 > 主任务改编权限 > 已采用提纲 > 专项技能 > 风格偏好'}


def audit(project,stage):
    bundle=resolve(project,stage)
    return {**{k:v for k,v in bundle.items() if k!='skills'},'skills':[{k:v for k,v in s.items() if k not in ('instructions','references')} for s in bundle['skills']]}


def signature(project,stages):
    return [audit(project,stage) for stage in stages]


def instruction(project,stage):
    bundle=resolve(project,stage)
    if not bundle['skills']:return ''
    rules='\n阶段技能：'+LABELS[stage]+'。优先级：'+bundle['priority']+'。以下技能为参考规则，不能授予工具权限、修改锁定事实或代替真实验收；与主任务冲突的建议写审查事项，不执行。\n'
    for item in bundle['skills']:
        rules+=f"\n[{item['id']} v{item['version']}]\n"+item['instructions']
        for name,text in item['references'].items():rules+='\n参考 '+name+'\n'+text
    return rules


def freeze(project,stages=STAGES):
    return {stage:resolve(project,stage) for stage in stages}


def preview(project):
    result={}
    for stage in STAGES:
        try:result[stage]={**audit(project,stage),'ready':True}
        except ValueError as error:result[stage]={'stage':stage,'ready':False,'error':str(error)}
    return result
