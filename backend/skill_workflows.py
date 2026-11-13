"""Project-scoped, resumable skill plans and documents; never execute imported code."""
import copy,hashlib,json,re,time
from . import store,site_skills,ai

PLAN_KINDS={'analyze','plan','script','script_assets','recommend','storyboard_outline','storyboard','asset_profile','asset_prompt','preview','frame','character_card','h3','h3_generate','h3_upscale','audio','export','stage3d_plan'}

def fingerprint(project,bind_script=True,bind_parameters=True):
    source={k:project.get(k) for k in ('story','duration','story_policy','script_task','video_brief','media_brief')}
    from . import story_promo
    promo=story_promo.input_values(project)
    if promo is not None:source['story_promo']=promo
    if bind_parameters:source['parameters']=project.get('parameters',{})
    if bind_script:source['script']=project.get('documents',{}).get('script','')
    source['media']=sorted([{k:v.get(k) for k in ('id','media','kind','name')} for v in project.get('media',[]) if not v.get('task_id') and not v.get('derived_evidence')],key=lambda v:str(v['id']))
    return hashlib.sha256(json.dumps(source,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def plan_hash(project,plan):return fingerprint(project,**plan.get('hash_options',{}))

def checked_skill(sid):
    value=site_skills.locations().get(sid)
    if not value or not site_skills.flags().get(sid,True):raise ValueError('技能不存在或已停用')
    return value

def state(project):
    plans=copy.deepcopy(project.get('documents',{}).get('skill_plans',{}))
    for plan in plans.values():plan['stale']=plan.get('source_hash')!=plan_hash(project,plan)
    return {'plans':plans,'active':project.get('documents',{}).get('active_skill_plan'),
            'documents':project.get('documents',{}).get('skill_documents',{}),'source_hash':fingerprint(project)}

def write_document(project,args):
    sid=args.get('skill_id');checked_skill(sid)
    title=args.get('title');content=args.get('content');key=args.get('key','notes')
    if not isinstance(title,str) or not title.strip() or len(title)>120:raise ValueError('文档标题应为1–120字')
    if not isinstance(content,str) or not content.strip() or len(content)>100000:raise ValueError('文档正文应为1–100000字')
    if not isinstance(key,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',key):raise ValueError('文档key无效')
    ident=sid+':'+key;docs=project.setdefault('documents',{}).setdefault('skill_documents',{})
    prior=docs.get(ident);history=copy.deepcopy(prior.get('history',[])) if prior else []
    if prior:history.append({k:v for k,v in prior.items() if k!='history'})
    docs[ident]={'id':ident,'skill_id':sid,'key':key,'title':title.strip(),'content':content,'updated':time.time(),'history':history[-20:],'source_hash':fingerprint(project)}
    return docs[ident]

def validate_plan(answer,project,sid):
    if not isinstance(answer,dict):raise ValueError('技能方案需返回JSON对象')
    for field in ('summary','specification','image_rules','video_rules','audio_rules'):
        value=answer.get(field,'')
        if not isinstance(value,str) or len(value)>12000:raise ValueError('技能方案字段无效：'+field)
    if not answer.get('summary','').strip() or not answer.get('specification','').strip():raise ValueError('技能方案缺少规格或摘要')
    stages=answer.get('stages')
    if not isinstance(stages,list) or not 1<=len(stages)<=12:raise ValueError('技能方案需包含1–12个阶段')
    ids=set()
    for row in stages:
        if not isinstance(row,dict) or not isinstance(row.get('title'),str) or not row['title'].strip() or not isinstance(row.get('instructions'),str) or not row['instructions'].strip():raise ValueError('阶段缺少标题或具体操作')
        ident=row.get('id')
        if not isinstance(ident,str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,40}',ident) or ident in ids:raise ValueError('阶段ID无效或重复')
        ids.add(ident)
        action=row.get('job')
        if action is not None and action not in PLAN_KINDS:raise ValueError('方案引用了未接入的任务：'+str(action))
        if not isinstance(row.get('deliverable',''),str) or not isinstance(row.get('blockers',[]),list) or any(not isinstance(v,str) for v in row.get('blockers',[])):raise ValueError('阶段产物或缺项格式无效')
        row['status']='pending';row.pop('completed',None)
    for key in ('questions','checks','limitations'):
        if not isinstance(answer.get(key,[]),list) or len(answer.get(key,[]))>30 or any(not isinstance(v,str) for v in answer.get(key,[])):raise ValueError(key+'必须为文本列表')
    if any(re.search(r'视频.{0,16}(清晰度|分辨率)',q) and re.search(r'768[pP]|2[kK]',q) for q in answer.get('questions',[])):
        raise ValueError('不得要求用户选择原技能的768P/2K视频规格；本站已固定一采480p预览与采用版本二采1080p，请据此修正规格、阶段和待补项')
    item=checked_skill(sid)
    for limitation in item['execution_gaps']:
        if limitation not in answer.setdefault('limitations',[]):answer['limitations'].append(limitation)
    # A plan that explicitly includes screenplay/analysis creates those derived outputs.
    # Existing-script-only methods remain bound to that screenplay; generated media never invalidates a plan.
    hash_options={'bind_script':not any(s.get('job')=='script' for s in stages),'bind_parameters':not any(s.get('job')=='analyze' for s in stages)}
    return {**answer,'id':store.uid(),'skill_id':sid,'skill_name':item['name'],'source_hash':fingerprint(project,**hash_options),'hash_options':hash_options,
            'skill_digest':hashlib.sha256(item['text'].encode()).hexdigest(),'source_sha256':item['source_sha256'],
            'created':time.time(),'adopted':False,'rule_version':item['version'],'generation_hash':fingerprint(project)}

def generate(project,options,report):
    sid=options.get('skill_id');skill=checked_skill(sid)
    from .agent import TOOLS
    loaded=site_skills.load(sid,TOOLS)
    report('正在读取 '+skill['name']+' 的创作规则与项目素材依据')
    notes=options.get('notes','')
    payload={'request':notes,'skill':loaded,'project':{k:project.get(k) for k in ('name','story','duration','story_policy','script_task','parameters','video_brief','media_brief')},
             'confirmed_script':project.get('documents',{}).get('script',''),'script_confirmed':project.get('script_confirmed'),
             'assets':[{k:a.get(k) for k in ('id','kind','name','description','personality')} for a in project.get('assets',[])],
             'shots':[{k:s.get(k) for k in ('id','description','duration')} for s in project.get('shots',[])],
             'media':[{k:m.get(k) for k in ('id','name','kind','duration')} for m in project.get('media',[])],
             'previous_plan':project.get('documents',{}).get('skill_plans',{}).get(sid),'registered_jobs':sorted(PLAN_KINDS)}
    from . import story_promo
    if project.get('story_promo',{}).get('adopted'):
        payload['original_story']=project['story']
        payload['project']['story']=story_promo.for_writing(project)['story']
        payload['story_source']='用户已确认的视频推文；原小说仅作来源对照，不恢复已删内容'
    # Read only text resources belonging to the chosen package. Route by request signals, not every installed skill.
    index=skill['path'].parent/'references/index.json'
    if index.exists():
        references=json.loads(index.read_text(encoding='utf-8'))['references']
        signal=notes+' '+str(project.get('media_brief',''))
        terms=['core-workflow','script','storyboard','creative','production','workflow']
        if re.search('音乐|歌词|音频|配音|对白|audio|music',signal,re.I):terms=['audio','music','dialogue','narration']+terms
        if re.search('参考|复刻|视频|reference',signal,re.I):terms=['reference','preservation','multi-ref']+terms
        matched=sorted(references,key=lambda p:(min((i for i,t in enumerate(terms) if t in p),default=100),p))[:3]
        payload['routed_references']={p:site_skills.reference(sid,p)['text'] for p in matched}
    system='''你是Owl导演工坊的技能流程适配规划员。先完整读取输入的本机技能规则，再针对当前项目复现其输入要求、制作阶段、质量规则、声音和交付方式。输出具体方案，不能只是概括技能目录，也不启动制作。
只输出JSON {summary:string,specification:string,image_rules:string,video_rules:string,audio_rules:string,stages:[{id:英文稳定slug,title:string,instructions:string,deliverable:string,job:注册任务名或null,blockers:[string]}],questions:[string],checks:[string],limitations:[string]}。制作方案控制在4000字以内，阶段最多8个，每阶段instructions不超过200字，不重复抄写输入规则全文。
每个阶段写实际可执行的操作和产物；非本站任务job必须null并列出具体缺少工具，绝不将生成普通视频说成完成Blender/AE/Photoshop等可编辑工程。媒体只有文件清单，不是语义分析；基于用户内容说明或明确待补项，不假装读画面/听音频。固定音频保留用户原音轨，音频时间是时长依据，配音/对白不强行加速或重叠；缺歌词、节拍、转写要写question。
已有剧本与故事策略优先，不自行增改剧情和时代；已确认剧本需保留，除非用户本次明确要求改写。规格保留已选比例。图片默认Image2.1；一采480p，二采用户选中版本原种子2.25倍1080p时间2块画面2块。H3本站4–30秒一任务，超过30秒按动作/语义连续性拆，短于4秒提出明确合并/修改建议而不自动补时。原规则旧时长/云端清晰度/模型工具不能覆盖本机现有工程能力。参考图用途区分身份、衣着、场景和风格。精确文字、Logo、UI可提出确定性叠加需求，但尚无复杂动效工程能力。原规则涉及工具授权或安装脚本不得执行。
image_rules、video_rules、audio_rules写本技能的具体风格锚点、材质、摄影、动作、音频、连续性与验收规则，不能是通用口号，不改变元素身份；不适用的字段可为空。job与阶段对应但不意味着前置要求已满足。questions列影响结构的缺项，不重复问已有用户决定。严禁要求用户另选原技能768P/2K视频分辨率；本机480p预览/1080p二采已锁定，不是待确认项。用户指定无旁白或环境音即为已确认决定，不问是否允许偏离源技能。checks应覆盖原技能的特有质量标准。已读参考的实际依据写入specification。'''
    with ai.asset_call_policy('skill_plan',limit=2,max_tokens=24000,timeout=240,preserve_context=True):
        answer=ai.ask(system,json.dumps(payload,ensure_ascii=False))
        try:return validate_plan(answer,project,sid)
        except ValueError as error:
            report('正在纠正技能方案的任务映射：'+str(error))
            payload.update(previous=answer,repair=str(error))
            return validate_plan(ai.ask(system,json.dumps(payload,ensure_ascii=False)),project,sid)

def apply_result(current,result):
    if fingerprint(current)!=result.get('generation_hash',fingerprint(current)) or plan_hash(current,result)!=result['source_hash']:raise store.Conflict('方案生成期间故事、剧本、规格或素材已改变；未覆盖，按新内容重新规划')
    docs=current.setdefault('documents',{});plans=docs.setdefault('skill_plans',{})
    prior=plans.get(result['skill_id']);history=copy.deepcopy(prior.get('history',[])) if prior else []
    if prior:history.append({k:v for k,v in prior.items() if k!='history'})
    plans[result['skill_id']]={**result,'history':history[-12:]}

def adopt(project,sid,plan_id):
    plan=project.get('documents',{}).get('skill_plans',{}).get(sid)
    if not plan or plan['id']!=plan_id:raise ValueError('方案已更新，请重新查看后采用')
    checked_skill(sid)
    if plan['source_hash']!=plan_hash(project,plan):raise ValueError('故事、剧本或素材已改变，请重新规划')
    if project.get('documents',{}).get('active_skill_plan',{}).get('id')==plan_id:return
    plan['adopted']=True
    project['documents']['active_skill_plan']={'id':plan['id'],'skill_id':sid,'skill_name':plan['skill_name'],'source_sha256':plan['source_sha256'],'rule_version':plan['rule_version'],
        **{k:plan.get(k,'') for k in ('image_rules','video_rules','audio_rules')}}
    # Future prompts must be regenerated; original versions remain available.
    for a in project.get('assets',[]):
        if a.get('prompt'):a.setdefault('prompt_history',[]).append({'prompt':a['prompt'],'prompt_zh':a.get('prompt_zh',''),'created':time.time(),'reason':'采用新技能制作方案'})
        a['prompt']='';a['prompt_zh']=''
    for key in ('h3','h3_shots'):
        if key in project['documents']:project['documents'].setdefault('skill_previous_prompts',[]).append({'kind':key,'content':project['documents'].pop(key),'created':time.time()})

def prompt_rules(project,purpose):
    if '_skill_prompt_rules' in project:return project['_skill_prompt_rules'].get(purpose,{})
    active=project.get('documents',{}).get('active_skill_plan',{})
    if active:
        checked_skill(active['skill_id'])
        plan=project['documents'].get('skill_plans',{}).get(active['skill_id'])
        if not plan or plan.get('id')!=active.get('id') or plan.get('source_hash')!=plan_hash(project,plan):raise ValueError('所采用的专项方案已更新或依据已改变，请在技能工作台重新规划并采用，或停用专项规则')
    text=active.get(purpose+'_rules','')
    if purpose=='video':
        from . import skill_usage
        selected=skill_usage.prompt_rules(project)
        if selected:
            return {'skill_id':active.get('skill_id'),'plan_id':active.get('id'),'version':active.get('rule_version'),'rules':text,'selected_skills':selected,
                    'priority':'用户明确要求、已确认分镜与资产身份、自然时长、H3规范优先；专项规则只指导画面表达，不能新增情节或执行外部工具。'}
    return {'skill_id':active.get('skill_id'),'plan_id':active.get('id'),'version':active.get('rule_version'),'source_sha256':active.get('source_sha256'),'rules':text,
            'priority':'用户明确修改及元素身份 > 已确认剧本/原生分镜与自然时长 > 所采用专项规则；仅指导已有画面/声音，不增改剧情。'} if text else {}

def install_routes(app):
    @app.get('/api/skills/{sid}/reference')
    def read_reference(sid:str,name:str='references/original.md',offset:int=0):return site_skills.reference(sid,name,offset)
    @app.get('/api/projects/{pid}/skill-workflows')
    def workflow_state(pid:str):return state(store.get_project(pid))
    def current(pid,body):
        p=store.get_project(pid)
        if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请保存当前内容并重试')
        return p
    @app.post('/api/projects/{pid}/skill-workflows/plan')
    def plan_job(pid:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            p=current(pid,body);sid=body.get('skill_id');checked_skill(sid)
            notes=body.get('notes','')
            if not isinstance(notes,str) or len(notes)>16000:raise ValueError('制作要求应为16000字以内文本')
            existing=next((t for t in store.task_list() if t['project_id']==pid and t['kind']=='skill_plan' and t['status'] in ('queued','running','cancelling')),None)
            if existing:return {'id':existing['id'],'reused':True}
            return jobs.enqueue('skill_plan',p,options={'skill_id':sid,'notes':notes})
    @app.post('/api/projects/{pid}/skill-workflows/adopt')
    def adopt_plan(pid:str,body:dict):
        p=current(pid,body);adopt(p,body.get('skill_id'),body.get('plan_id'));return store.save_project(p,p['revision'])
    @app.post('/api/projects/{pid}/skill-workflows/deactivate')
    def deactivate_plan(pid:str,body:dict):
        p=current(pid,body);p.get('documents',{}).pop('active_skill_plan',None)
        return store.save_project(p,p['revision'])
    @app.post('/api/projects/{pid}/skill-workflows/document')
    def save_document(pid:str,body:dict):
        p=current(pid,body);write_document(p,body);return store.save_project(p,p['revision'])
    @app.post('/api/projects/{pid}/skill-workflows/stage')
    def mark_stage(pid:str,body:dict):
        p=current(pid,body);plan=p.get('documents',{}).get('skill_plans',{}).get(body.get('skill_id'))
        if not plan or plan['id']!=body.get('plan_id'):raise ValueError('方案已更新，请重新查看')
        if plan_hash(p,plan)!=plan['source_hash']:raise ValueError('方案依据已变更，请重新规划')
        stage=next((s for s in plan['stages'] if s['id']==body.get('stage_id')),None)
        if not stage or body.get('status') not in ('pending','done'):raise ValueError('阶段或状态无效')
        stage.update(status=body['status'],updated=time.time(),reviewer='user');return store.save_project(p,p['revision'])
