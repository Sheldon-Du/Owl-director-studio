import copy
import hashlib
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image
from . import store, director, timing, jobs, comfy, ai, endpoints, h3, image_prompts, h3_workflow,character_profiles,story_writing,script_source
from . import script_workflows,video_versions,shot_frames,production_canvas,workflow_files
from . import script_tasks
from . import creative_rules
from . import shot_references
from . import agent, site_skills, stage3d, stage_mobile, stage_routes

SESSIONS={}
SESSION_COOKIE=os.environ.get('DIRECTOR_SESSION_COOKIE','owl_studio_session')
ROLES={'identity','face','costume','pose','environment','prop','style','adopted'}


@asynccontextmanager
async def lifespan(app):
    from . import image_defaults
    image_defaults.migrate()
    jobs.start()
    from . import comfy_policy
    comfy_policy.start()
    from . import auto_creation
    auto_creation.start(job)
    try:yield
    finally:
        auto_creation.STOP.set()
        stage_mobile.stop()


app=FastAPI(title='导演工坊',lifespan=lifespan)


def local(request):
    return request.client.host in ('127.0.0.1','::1','localhost','testclient')


@app.middleware('http')
async def access(request,call_next):
    path=request.url.path
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'请求来源不匹配'},403)
    public=path in ('/api/session','/api/setup','/api/login')
    if (path.startswith('/api/') or path.startswith('/media/')) and not public:
        session=SESSIONS.get(request.cookies.get(SESSION_COOKIE,''))
        if not session or session<time.time():
            return JSONResponse({'detail':'请先登录工作室'},401)
    return await call_next(request)


@app.exception_handler(ValueError)
async def invalid(request,error):
    return JSONResponse({'detail':str(error)},422)


@app.exception_handler(KeyError)
async def missing(request,error):
    return JSONResponse({'detail':str(error)},404)


@app.exception_handler(store.Conflict)
async def conflict(request,error):
    return JSONResponse({'detail':str(error)},409)


@app.get('/api/session')
def session(request:Request):
    return {'configured':bool(store.settings().get('password_hash')),'authenticated':SESSIONS.get(request.cookies.get(SESSION_COOKIE,''),0)>time.time(),'can_setup':local(request),'features':['asset_enrich','asset_enrich_prompt']}


def login_response():
    token=secrets.token_urlsafe(32)
    SESSIONS[token]=time.time()+86400
    response=JSONResponse({'ok':True})
    response.set_cookie(SESSION_COOKIE,token,httponly=True,samesite='strict',max_age=86400)
    return response


@app.post('/api/setup')
def setup(request:Request,body:dict):
    if not local(request):
        raise HTTPException(403,'首次设置请在本机完成')
    with store.LOCK:
        cfg=store.settings()
        if cfg.get('password_hash'):
            raise HTTPException(409,'工作室已设置密码，请登录')
        password=body.get('password','')
        if len(password)<8:
            raise ValueError('工作室密码至少8个字符')
        salt=secrets.token_hex(16)
        cfg['password_salt']=salt
        cfg['password_hash']=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),200000).hex()
        store.settings_save(cfg)
    return login_response()


@app.post('/api/login')
def login(body:dict):
    cfg=store.settings()
    if not cfg.get('password_hash'):
        raise HTTPException(403,'请先在本机设置密码')
    digest=hashlib.pbkdf2_hmac('sha256',str(body.get('password','')).encode(),cfg['password_salt'].encode(),200000).hex()
    if not hmac.compare_digest(digest,cfg['password_hash']):
        raise HTTPException(401,'工作室密码不正确')
    return login_response()


@app.post('/api/logout')
def logout(request:Request):
    SESSIONS.pop(request.cookies.get(SESSION_COOKIE,''),None)
    response=JSONResponse({'ok':True});response.delete_cookie(SESSION_COOKIE)
    return response


@app.get('/api/catalog')
def catalog():
    return {**director.catalog(),'h3_workflow':h3_workflow.describe()}


@app.get('/api/status')
def status():
    return {'director':director.catalog()['version'],'comfy':comfy.health(),'ai_configured':bool(store.settings().get('ai_url'))}


@app.get('/api/settings')
def settings():
    cfg=store.settings()
    cfg.setdefault('ai_storyboard_max_tokens',32768)
    return {k:v for k,v in cfg.items() if k not in ('ai_key','vision_key','password_hash','password_salt')}|{'has_ai_key':bool(cfg.get('ai_key')),'has_vision_key':bool(cfg.get('vision_key'))}


@app.put('/api/settings')
def put_settings(body:dict):
    cfg=store.settings()
    if 'ai_storyboard_max_tokens' in body:
        budget=body['ai_storyboard_max_tokens']
        if isinstance(budget,bool) or not isinstance(budget,int) or not 4096<=budget<=131072:
            raise ValueError('分镜输出预算需为4096–131072的整数；实际可用上限由接口决定')
        cfg['ai_storyboard_max_tokens']=budget
    if 'vision_provider' in body and body['vision_provider'] not in ('auto','minimax','chat'):raise ValueError('图片理解类型无效')
    for key in ('comfy_url','ai_url','ai_model','ai_key','vision_provider','vision_url','vision_model','vision_key'):
        if key in body:
            cfg[key]=str(body[key]).strip()
    for key in ('comfy_url','ai_url','vision_url'):
        if cfg.get(key) and urlparse(cfg[key]).scheme not in ('http','https'):
            raise ValueError('接口地址必须为HTTP或HTTPS')
    cfg['ai_url']=endpoints.chat_url(cfg.get('ai_url',''))
    if body.get('vision_key'):
        vision_origin=urlparse(cfg.get('vision_url') or cfg.get('ai_url',''))
        cfg['vision_key_origin']=vision_origin.scheme+'://'+vision_origin.netloc
    store.settings_save(cfg)
    return {'ok':True}


@app.get('/api/projects')
def projects():
    return [{k:p.get(k) for k in ('id','name','revision','updated','duration','summary')} for p in store.list_projects()]


@app.post('/api/projects')
def create(body:dict):
    project_type = body.get('project_type', 'story')
    if project_type not in ('story', 'medical'): raise ValueError('项目类型无效')
    writing_task=body.get('script_task','auto');writing_settings=body.get('script_task_settings',{})
    writing_skills=body.get('creative_skills',{'mode':'auto','ids':[]});storyboard_method=body.get('storyboard_method','source_units')
    story=str(body.get('story','')).strip()
    if not story:
        raise ValueError('请填写故事或创意')
    body={'id':store.uid(),'name':str(body.get('name') or '未命名项目')[:120],'story':story,'source_mode':body.get('source_mode','story'),'authoring_settings':body.get('authoring_settings',{}),'story_promo':body.get('story_promo',{}),'duration':body.get('duration',30),'parameters':body.get('parameters',{}),'parameter_sources':{},'assets':[],'shots':[],'documents':{},'media':[],'timeline':[],'captions':[],'chat':[],'confirmed':False,'script_confirmed':False,'native_storyboard_current':False,'production_scheme':{},'h3_settings':{'max_step_seconds':30},'questions':[],'script_mode':body.get('script_mode','情感共鸣短视频'),'story_policy':body.get('story_policy','faithful'),'script_workflow':body.get('script_workflow','director'),'video_brief':body.get('video_brief',{}),'cinematic_mode':'电影工作室'}
    # Keep source material intact; the task controls the scope of a rewrite.
    body.update(script_task=writing_task,script_task_settings=writing_settings)
    if project_type == 'medical':
        from . import medical_director
        body['project_type'] = 'medical'; medical_director.init(body)
    body.update(creative_skills=writing_skills,storyboard_method=storyboard_method,workflow_schema_version=2)
    body['parameter_sources']={k:{'source':'user','value':v} for k,v in body['parameters'].items()}
    validate_project(body)
    return store.save_project(body)


@app.get('/api/projects/{pid}/progress')
def project_progress(pid:str):
    from . import story_promo,h3,soundtrack
    p=store.get_project(pid);state={}
    promo=story_promo.input_values(p)
    state['promo_stale']=bool(promo and promo['stale'])
    for stage in ('novel','video'):
        if p.get('story_promo',{}).get(stage):
            try:story_promo.current(p,stage)
            except ValueError:state['promo_stale']=True
    packages=[(None,p.get('documents',{}).get('h3')),*p.get('documents',{}).get('h3_shots',{}).items()]
    state['h3_stale']=any(package and not h3.is_current(p,package,sid) for sid,package in packages)
    state['soundtrack_stale']=False
    for key,track in p.get('soundtrack',{}).items():
        try:state['soundtrack_stale']|=track.get('source_hash')!=soundtrack.fingerprint(p,None if key=='all' else key)
        except ValueError:state['soundtrack_stale']=True
    return state


@app.get('/api/projects/{pid}')
def get(pid:str):
    return store.get_project(pid)


@app.get('/api/projects/{pid}/versions')
def versions(pid:str):
    store.get_project(pid)
    return store.versions(pid)


@app.post('/api/projects/{pid}/restore')
def restore(pid:str,body:dict):
    return store.restore(pid,body['version_id'],body['revision'])


@app.post('/api/projects/{pid}/copy')
def project_copy(pid:str,body:dict):
    store.get_project(pid)
    p=copy.deepcopy(body)
    p['id']=store.uid()
    p['name']=str(p.pop('copy_name',None) or (str(p.get('name','项目'))[:110]+' · 副本'))[:120]
    p.pop('deleted',None)
    p.pop('chatcut',None)
    p['confirmed']=False
    p.get('documents',{}).pop('h3',None)
    for shot in p.get('shots',[]):
        shot['natural_status']='unverified'
    validate_project(p)
    return store.save_project(p)


@app.post('/api/projects/{pid}/rename')
def project_rename(pid:str,body:dict):
    p=store.get_project(pid)
    name=str(body.get('name','')).strip()
    if not name:
        raise ValueError('请输入项目名称')
    p['name']=name[:120]
    return store.save_project(p,body['revision'])


@app.post('/api/projects/{pid}/delete')
def project_delete(pid:str,body:dict):
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        p['deleted']=True
        store.save_project(p,body['revision'])
        for task in store.task_list():
            if task['project_id']==pid and task['status'] in ('queued','running','cancelling'):
                jobs.cancel(task['id'])
    return {'ok':True}


@app.get('/api/trash')
def trash():
    return [{k:p.get(k) for k in ('id','name','revision','updated','duration')} for p in store.list_projects(include_deleted=True) if p.get('deleted')]


@app.post('/api/projects/{pid}/undelete')
def project_undelete(pid:str,body:dict):
    p=store.get_project(pid,include_deleted=True)
    p.pop('deleted',None)
    return store.save_project(p,body['revision'])


def validate_project(p):
    from . import authoring
    authoring.settings(p)
    if p.get('story_policy','faithful') not in story_writing.POLICIES:raise ValueError('请选择原文直用、忠于故事剧本化或AI编排')
    script_tasks.validate(p)
    creative_rules.config(p)
    if p.get('storyboard_method','legacy') not in ('legacy','source_units'):raise ValueError('请选择有效的分镜规划方法')
    if not 3<=timing.number(p['duration'])<=14400:
        raise ValueError('成片时长需为3秒至240分钟')
    script_workflows.validate(p)
    director.validate_scheme(p.get('production_scheme',{}))
    if p.get('h3_settings',{}).get('max_step_seconds',30) not in (15,30):raise ValueError('H3 提示词任务上限请选择15或30秒')
    if p.get('canvas_layout'):production_canvas.layout(p,p['canvas_layout'])
    for a in p['assets']:
        if a['kind'] not in ('character','scene','prop'):
            raise ValueError('非法资产类型')
        if a['model'] not in ('z-image','qwen-image-2.1'):
            raise ValueError('非法预览模型')
        if a.get('variant') and a['model']!='qwen-image-2.1':raise ValueError('参考图状态变体需使用Image2.1图片编辑模型')
        seen=set()
        for r in a.get('references',[]):
            if r['media'] in seen:
                raise ValueError('同一元素不能重复绑定同一图片，请修改原引用用途')
            seen.add(r['media'])
            if r.get('role') not in ROLES:
                raise ValueError('参考用途无效')
            if not store.media_path(r['media']).exists():
                raise ValueError('参考图片不存在')
    ids=[s['id'] for s in p['shots']]
    if len(ids)!=len(set(ids)):
        raise ValueError('镜头ID不能重复')
    asset_ids={a['id'] for a in p['assets']}
    for shot in p['shots']:
        if timing.number(shot['duration'])<=0:
            raise ValueError('镜头时长必须大于零')
        if not set(shot.get('asset_ids',[])).issubset(asset_ids):
            raise ValueError('镜头引用了已删除的资产，请先解除绑定')
        if shot.get('first_frame') and not store.media_path(shot['first_frame']).exists():
            raise ValueError('采用的首帧图片不存在')
    for item in p.get('media',[]):
        if item['kind'] not in ('image','audio','video') or not store.media_path(item['media']).exists():
            raise ValueError('项目素材不存在或类型不支持')
    for clip in p['timeline']:
        if clip['kind'] not in ('image','audio','video') or not store.media_path(clip['media']).exists():
            raise ValueError('时间线素材不存在或类型不支持')
        if timing.number(clip['duration'])<=0 or timing.number(clip.get('in',0))<0 or timing.number(clip.get('start',0))<0:
            raise ValueError('时间线时间无效')
        if not 0<=timing.number(clip.get('volume',1))<=4:
            raise ValueError('音量范围为0–4')
    for caption in p.get('captions',[]):
        if timing.number(caption['start'])<0 or timing.number(caption['end'])<=timing.number(caption['start']):
            raise ValueError('字幕时间无效')


@app.put('/api/projects/{pid}')
def update(pid:str,body:dict):
    old=store.get_project(pid)
    expected=body.get('revision')
    p=copy.deepcopy(old)
    if 'story_promo' in body and isinstance(body['story_promo'],dict) and 'settings' in body['story_promo']:
        from . import story_promo
        p.setdefault('story_promo',{})['settings']=body['story_promo']['settings']
        story_promo.settings(p)
        if story_promo.settings(p)!=story_promo.settings(old):story_promo.mark_script(p)
    allowed=('creative_constraints','source_mode','authoring_settings','seedance_mode','seedance_template','seedance_case','seedance_professional','name','story','duration','parameters','parameter_sources','assets','shots','media','timeline','captions','script_mode','story_policy','script_workflow','video_brief','cinematic_mode','chat','production_scheme','h3_settings','canvas_layout','script_task','script_task_settings','creative_skills','storyboard_method','storyboard_notes','prompt_skills')
    if 'prompt_skills' in body:
        from . import skill_usage
        skill_usage.selection({**p,'prompt_skills':body['prompt_skills']})
    if 'storyboard_notes' in body and (not isinstance(body['storyboard_notes'],str) or len(body['storyboard_notes'])>6000):raise ValueError('汇总修订要求需为6000字以内文字')
    for key in allowed:
        if key in body:
            p[key]=body[key]
    from . import authoring
    authoring.input_changed(old,p)
    from . import authoring_prompts
    previous_shots={s['id']:s for s in old.get('shots',[])}
    for shot in p.get('shots',[]):
        prior=previous_shots.get(shot['id'],{})
        for managed in ('seedance_candidate','seedance_history','sound_script','camera_override','camera_baseline','camera_history','first_frame_link','merged_from'):
            if managed in prior:shot[managed]=copy.deepcopy(prior[managed])
            else:shot.pop(managed,None)
        from . import visual_reference
        link=shot.get('first_frame_link',{})
        if link.get('mode')=='previous_tail' and link.get('media'):
            shot['first_frame']=link['media'];shot.setdefault('frame_cards',{})['first']=copy.deepcopy(link['card'])
        confirmation=prior.get('seedance_reference_confirmation')
        shot['seedance_reference_confirmation']=confirmation if confirmation and authoring_prompts.binding_hash(shot)==confirmation and shot.get('prompt')==prior.get('prompt') else None
    for shot in p.get('shots',[]):visual_reference.tail_changed(p,shot)
    for asset in p['assets']:
        if asset.get('image_skill_ids'):
            from . import skill_usage
            skill_usage.image_rules(asset)
        prior=next((a for a in old['assets'] if a['id']==asset['id']),None)
        if prior and prior.get('model')!=asset.get('model'):asset['model_source']='user'
        elif not prior and not asset.get('model_source'):asset['model_source']='default' if asset.get('model')=='qwen-image-2.1' else 'user'
    script_changed=False
    if 'script_text' in body:
        text=str(body['script_text'])
        if text!=old.get('documents',{}).get('script',''):
            if not text.strip():raise ValueError('剧本正文不能为空')
            p.setdefault('documents',{})['script']=text;p['script_confirmed']=False;p['native_storyboard_current']=False;p['confirmed']=False
            script_changed=True
    if any(p.get(k)!=old.get(k) for k in ('story','parameters','duration','script_mode','story_policy','script_workflow','video_brief','script_task','script_task_settings')) or script_source.input_hash(p)!=script_source.input_hash(old):
        p.pop('script_generation',None)
        p['script_confirmed']=False;p['native_storyboard_current']=False;p['confirmed']=False;p['script_needs_rewrite']=True
        script_workflows.invalidate(p.setdefault('documents',{}))
        p['documents'].pop('script_consistency',None)
        p['documents'].pop('script_task_plan',None)
    if script_changed:
        p.pop('script_generation',None)
        script_source.accept(p);script_source.mark_assets_stale(p);script_source.mark_extraction_pending(p)
        p['documents'].pop('script_adaptation_map',None);p['documents'].pop('script_director_notes',None)
        if p['documents'].get('script_expression_review'):p['documents']['script_expression_review'].update(semantic_fidelity='pending_user_review',audience_delivery='pending_user_review',settings_stale=True)
        for key in ('script_task_source_map','script_task_review','script_duration_advice','script_task_used'):p['documents'].pop(key,None)
        script_workflows.invalidate(p['documents'])
        p['documents'].pop('script_consistency',None)
        p['documents']['script_policy_note']='当前正文经过手动编辑，请确认内容；元素提取以此正文为准。'
    if p.get('production_scheme',{})!=old.get('production_scheme',{}):
        p['native_storyboard_current']=False;p['confirmed']=False
        for asset in p.get('assets',[]):
            asset['style_needs_refresh']=True
            for preview in asset.get('previews',[]):preview['stale']=True
    if p.get('creative_skills')!=old.get('creative_skills'):
        if creative_rules.signature(p,('script_plan','script'))!=creative_rules.signature(old,('script_plan','script')):
            p.pop('script_generation',None)
            p['script_confirmed']=False;p['script_needs_rewrite']=True;p['documents'].pop('script_task_plan',None)
        p['native_storyboard_current']=False;p['confirmed']=False
    if p.get('storyboard_method')!=old.get('storyboard_method'):
        p['native_storyboard_current']=False;p['confirmed']=False
    if script_source.fingerprint(p)!=script_source.fingerprint(old):
        script_source.mark_assets_stale(p);script_source.mark_extraction_pending(p)
    from . import shot_continuity
    shot_continuity.refresh(p)
    if p['story']!=old['story'] or p['parameters']!=old['parameters'] or p['duration']!=old['duration'] or p['shots']!=old['shots'] or p['assets']!=old['assets']:
        p['confirmed']=False
    for shot in p['shots']:
        original=next((s for s in old['shots'] if s['id']==shot['id']),None)
        for field in ('stage3d','stage3d_suggestion','stage3d_captures'):
            if original and field in original:shot[field]=copy.deepcopy(original[field])
            else:shot.pop(field,None)
        if original and 'adopted_video_ids' in original:shot['adopted_video_ids']=copy.deepcopy(original['adopted_video_ids'])
        else:shot.pop('adopted_video_ids',None)
        # Proposals are generated by the server. Editing their source expires
        # them instead of letting a client replace the reviewed AI candidate.
        shot.pop('timing_suggestion',None)
        if original and original.get('timing_suggestion'):
            from . import storyboard_generation
            proposal=copy.deepcopy(original['timing_suggestion'])
            if proposal.get('shot_source_hash')!=timing.shot_signature(shot) or proposal.get('project_source_hash')!=storyboard_generation.fingerprint(p):
                proposal['status']='stale'
            shot['timing_suggestion']=proposal
        if original is None or any(shot.get(k)!=original.get(k) for k in ('description','duration','prompt','native','actions')):
            shot['natural_status']='unverified'
        else:
            shot['natural_status']=original.get('natural_status','unverified')
    if p.get('storyboard_generation'):
        from . import storyboard_generation
        if not storyboard_generation.valid_state(p):
            p['storyboard_generation'].update(status='stale',message='汇总修订要求已修改；旧镜头保留，请按新要求重新生成汇总' if p.get('storyboard_notes')!=old.get('storyboard_notes') else '剧本、方案或元素外观已修改；已保存镜头保留，需要按新依据重新生成')
            p['native_storyboard_current']=False;p['confirmed']=False
    timing_shots_changed=[{k:s.get(k) for k in ('id','duration','prompt','actions')} for s in p['shots']]!=[{k:s.get(k) for k in ('id','duration','prompt','actions')} for s in old['shots']]
    if p.get('timing_revision') and (timing_shots_changed or script_changed or any(p.get(k)!=old.get(k) for k in ('duration','parameters','production_scheme')) or p.get('storyboard_generation',{}).get('status')=='stale'):
        p['timing_revision'].update(status='stale',message='分镜或生成依据已修改；请重新审查动作并修正时间标签')
    validate_project(p)
    saved=store.save_project(p,expected)
    if any(p.get(k)!=old.get(k) for k in ('story','parameters','duration','creative_skills','story_policy','script_mode','production_scheme','assets','shots')) or script_changed or p.get('story_promo',{}).get('settings')!=old.get('story_promo',{}).get('settings'):
        from . import auto_creation
        auto_creation.pause_for_edit(pid)
    return store.get_project(pid)


@app.post('/api/projects/{pid}/script/confirm')
def confirm_script(pid:str,body:dict):
    p=store.get_project(pid)
    if not p.get('documents',{}).get('script','').strip():raise ValueError('请先生成或填写剧本')
    from . import screenplay_expression
    screenplay_expression.confirm(p,body.get('semantic_review'))
    p['script_confirmed']=True
    script_source.accept(p)
    script_workflows.refresh(p)
    script_source.mark_extraction_pending(p)
    saved=store.save_project(p,body['revision'])
    return store.get_project(pid)


@app.get('/api/projects/{pid}/script/spec')
def video_spec(pid:str):
    return Response(script_workflows.markdown(store.get_project(pid)),media_type='text/markdown; charset=utf-8',headers={'Content-Disposition':'attachment; filename="Final_Video_Spec.md"'})


@app.post('/api/projects/{pid}/chat')
def chat(pid:str,body:dict):
    p=store.get_project(pid)
    if body.get('revision')!=p['revision']:
        raise store.Conflict('项目已更新，请先刷新')
    message=str(body.get('message','')).strip()
    if not message:
        raise ValueError('请填写消息')
    from . import ai_context
    with ai_context.session(pid):
        answer=ai.ask('你是导演工作台的对话助手。只输出JSON {message:string,parameter_updates:{原生参数名:值},story_update:string|null}。基于用户明确请求调整创作参数或故事；不生成最终图像/视频提示词。未明确要求改变原故事则story_update=null。不要声称执行过生成或已看见素材。参数枚举必须匹配给定schema。若用户请求生成，请说明需要使用对应生成按钮并先确认分镜。',json.dumps({'user':message,'story':p['story'],'parameters':p['parameters'],'schema':director.definitions('DirectorMasterCore'),'recent_chat':p['chat'][-8:]},ensure_ascii=False))
    schema=director.definitions('DirectorMasterCore')
    for key,value in answer.get('parameter_updates',{}).items():
        if key not in schema or key.startswith('AI') or (schema[key]['options'] and value not in schema[key]['options']):
            continue
        if p['parameters'].get(key)!=value:
            p['script_confirmed']=False;p['native_storyboard_current']=False;p['confirmed']=False;p['script_needs_rewrite']=True
        p['parameters'][key]=value;p['parameter_sources'][key]={'source':'suggested','value':value,'evidence':'对话修改建议'}
    if answer.get('story_update') and 'source_mode' in p:
        p.setdefault('story_suggestions',[]).append({'text':str(answer['story_update']),'created':time.time()})
    elif answer.get('story_update'):
        if p['story']!=str(answer['story_update']):
            p['script_confirmed']=False;p['native_storyboard_current']=False;p['confirmed']=False;p['script_needs_rewrite']=True
        p['story']=str(answer['story_update'])
    p['chat'] += [{'role':'user','content':message},{'role':'assistant','content':str(answer.get('message',''))}]
    return store.save_project(p,p['revision'])


@app.post('/api/projects/{pid}/jobs/{kind}')
def job(pid:str,kind:str,body:dict):
    if not (kind=='asset_enrich' and body.get('options',{}).get('rebuild_card')):
        kind={'asset_enrich':'seedance_asset','script_assets':'seedance_assets'}.get(kind,kind)
    if kind=='h3' and not body.get('target'):
        return h3_batch(pid,'rewrite',body)
    p=store.get_project(pid)
    if body.get('revision')!=p['revision']:
        raise store.Conflict('任务基于旧版本，请先刷新')
    if p.get('source_mode')=='idea' and kind in ('script','plan','recommend','storyboard','storyboard_outline','seedance_overview','seedance_storyboard','seedance_assets'):
        from . import authoring
        authoring.source(p)
    if kind not in ('tail','frame_layout','seedance_overview','seedance_storyboard','seedance_asset','seedance_frames','seedance_assets','frame_plan','asset_enrich','asset_explore','plan','script','script_assets','recommend','storyboard','storyboard_outline','storyboard_timing','h3','h3_generate','h3_upscale','analyze','schedule','asset_prompt','character_profile','asset_profile','preview','asset_upscale','character_mod','keyframe','frame','generate','audio','character_card','canvas_links','stage3d_plan','stage3d_render','export'):
        raise ValueError('不支持的任务')
    if kind=='script':
        script_tasks.validate(p)
        opts=body.get('options',{})
        if not isinstance(opts,dict) or ('plan_only' in opts and not isinstance(opts['plan_only'],bool)):raise ValueError('剧本提纲选项无效')
        if script_tasks.task(p) not in ('auto','adapt') and not opts.get('plan_only'):
            record=script_tasks.current_plan(p)
            if not record or opts.get('approved_plan')!=script_tasks.plan_hash(record):raise ValueError('请先生成提纲，再采用提纲并编写剧本')
            if record['plan'].get('pending_questions'):raise ValueError('请先解决提纲待决问题并重新生成')
        active=next((t for t in store.task_list() if t['project_id']==pid and t['kind']=='script' and t['status'] in ('queued','running','cancelling')),None)
        if active:return {k:v for k,v in active.items() if k not in ('snapshot','options')}
    if kind=='stage3d_render':
        from . import blender_render
        blender_render.executable()
        selected=stage3d.shot(p,body.get('target'));mode=body.get('options',{}).get('mode')
        if mode:
            if mode not in ('frame','keyframe') or not selected.get('image_plans',{}).get(mode,{}).get('layout_scene'):raise ValueError('请先AI生成本阶段布局指令')
        elif not selected.get('stage3d'):raise ValueError('请先保存3D布置')
    if kind=='stage3d_plan':
        stage3d.shot(p,body.get('target'))
        if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI接口和模型')
        active=next((t for t in store.task_list() if t['project_id']==pid and t['kind']==kind and t.get('target')==body.get('target') and t['status'] in ('queued','running','cancelling')),None)
        if active:return {k:v for k,v in active.items() if k not in ('snapshot','options')}
    if kind=='frame' and body.get('options',{}).get('composition_reference'):
        stage3d.reference(p,body.get('target'),body['options']['composition_reference'])
    if kind=='canvas_links':
        if not script_source.ready(p):raise ValueError('请先填写故事或有效剧本')
        if p.get('storyboard_generation',{}).get('status')=='stale':raise ValueError('请先按当前剧本重新生成分镜汇总')
        if not production_canvas.targets(p) or not p.get('assets'):raise ValueError('请先生成分镜汇总并提取资产元素')
        if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI接口及模型')
        active=next((t for t in store.task_list() if t['project_id']==pid and t['kind']=='canvas_links' and t['status'] in ('queued','running','cancelling')),None)
        if active:return {k:v for k,v in active.items() if k not in ('snapshot','options')}
    if kind in ('script_assets','character_profile','asset_profile'):script_source.text(p)
    if kind in ('asset_enrich','asset_prompt') and not p.get('seedance_mode') and not next((a.get('card') for a in p['assets'] if a['id']==body.get('target')),None) and (not p.get('production_scheme',{}).get('art') or not p.get('production_scheme',{}).get('cinematic')):raise ValueError('请先确定镜头与美术方案，再补全外观或生成资产提示词')
    if kind=='asset_enrich':
        script_source.asset_text(p)
        if not any(a['id']==body.get('target') for a in p.get('assets',[])):raise ValueError('元素不存在')
        if next(a for a in p['assets'] if a['id']==body.get('target')).get('variant'):raise ValueError('状态变体请使用生成提示词，不重新补全原资产档案')
        if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI')
    if kind=='asset_explore':
        script_source.asset_text(p)
        if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI')
        if any(t['project_id']==pid and t['kind']=='asset_explore' and t['status'] in ('queued','running','cancelling') for t in store.task_list()):raise ValueError('额外元素探索已在队列中')
    if kind=='script_assets':
        if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI接口及模型，再提取剧本元素')
        return jobs.enqueue_script_assets(p,force=bool(body.get('options',{}).get('force',False)))
    if kind in ('recommend','storyboard','storyboard_outline','storyboard_timing','h3') and not script_source.ready(p):raise ValueError('请先填写故事或有效剧本')
    if kind in ('storyboard','storyboard_outline') and (not p.get('production_scheme',{}).get('cinematic') or not p.get('production_scheme',{}).get('art')):raise ValueError('请先推荐或填写镜头与美术方案')
    if kind=='storyboard_outline':
        if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI接口及模型，再生成与剧本匹配的分镜汇总')
        return jobs.enqueue_storyboard(p,force=bool(body.get('options',{}).get('force',False)),plan_only=True,recovery_strategy=body.get('options',{}).get('recovery_strategy'))
    if kind=='storyboard':return jobs.enqueue_storyboard(p,force=bool(body.get('options',{}).get('force',False)),require_outline=True,
        target_outline=body.get('target'),regenerate=bool(body.get('options',{}).get('regenerate',False)),recovery_strategy=body.get('options',{}).get('recovery_strategy'))
    if kind=='storyboard_timing':
        if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI，再按完整动作修正时间')
        return jobs.enqueue_timing(p)
    target=body.get('target')
    opts=body.get('options',{})
    if kind=='character_mod':
        from . import character_mod
        opts=character_mod.prepare(p,target,opts)
    if kind=='asset_upscale':
        asset=next((a for a in p['assets'] if a['id']==target),None)
        if not asset or not asset.get('adopted'):raise ValueError('请先采用满意的元素图片，再进行二次放大')
        if opts.get('source_media')!=asset['adopted']:raise store.Conflict('采用图片已变化，请重新选择二次放大')
        store.media_path(asset['adopted'])
        opts['media_kind']='image'
    if kind in ('frame_plan','frame_layout'):
        if kind=='frame_layout' and not p['shots']:raise ValueError('请先生成分镜')
        if not any(s['id']==target and s.get('native') for s in p['shots']):raise ValueError('请先生成本镜具体分镜')
    if kind in ('frame','keyframe','tail') and opts.get('direct_from_5s'):
        from . import frame_plans
        shot=next((s for s in p['shots'] if s['id']==target),None)
        if not shot:raise ValueError('分镜不存在')
        if kind=='frame' and shot.get('first_frame_link',{}).get('mode')=='previous_tail':raise ValueError('本镜首帧复用上一镜尾帧，无需重复生成')
        old=shot.get('image_plans',{}).get(kind) or {}
        request={'mode':kind,'auto_bind_adopted':True}
        if old.get('selected_asset_ids'):request['selected_asset_ids']=old['selected_asset_ids']
        if old.get('references') and not old.get('selection_stale'):request['references']=old['references']
        plan=frame_plans.direct_card_plan(p,shot,request,lambda _:None)
        if plan.get('missing_adopted_assets'):raise ValueError('引用元素尚未采用可用图片：'+'、'.join(row['name'] for row in plan['missing_adopted_assets']))
        frame_plans.validate_selection(p,plan)
        shot.setdefault('image_plans',{})[kind]=plan
        opts['use_image_plan']=True
    if kind=='tail' and not opts.get('use_image_plan'):raise ValueError('请先生成尾帧提示词并绑定资产参考')
    if kind=='frame_layout' and opts.get('mode','frame') not in ('frame','keyframe','tail'):raise ValueError('帧类型无效')
    if kind in ('frame','keyframe','tail') and opts.get('use_image_plan'):
        from . import keyframes,qwen_prompts
        shot=next(s for s in p['shots'] if s['id']==target)
        plan=copy.deepcopy(shot.get('image_plans',{}).get(kind))
        if not plan or plan.get('source_hash')!=keyframes.fingerprint(p,shot):raise ValueError('请先AI预填当前画面方案')
        if plan.get('stale') or plan.get('selection_stale'):raise ValueError('本帧5S或资产选择已修改，请重新编写提示词')
        if not plan.get('prompt','').strip():raise ValueError('请填写生图提示词')
        from . import frame_plans
        frame_plans.validate_selection(p,plan)
        if plan.get('composition_reference'):
            from . import frame_prompt_rules
            white=next((r for r in shot.get('layout_images',[]) if r['media']==plan['composition_reference']),None)
            if white and white['mode']!=kind:raise ValueError('白模图必须属于当前帧阶段')
            composition=stage3d.reference(p,target,plan['composition_reference'])
            if plan.get('layout_source_hash'):
                from . import frame_layout
                if plan['layout_source_hash']!=frame_layout.fingerprint(p,shot,kind):raise ValueError('白模布局依据已修改，请重新生成本阶段布局图或取消绑定')
            count=len(plan['references'])
            if count>=16:raise ValueError('使用构图参考时最多绑定15张资产图片')
            plan['prompt']=frame_prompt_rules.with_layout(plan['prompt'],count)
            plan['prompt_zh']=plan['prompt'];plan['references']=[composition,*plan['references']]
        from . import frame_continuity
        plan=frame_continuity.bind(p,shot,kind,plan)
        qwen_prompts.validate({'rewritten_prompt':plan['prompt'],'rewritten_prompt_zh':plan.get('prompt_zh',plan['prompt']),'wh_ratio':plan['wh_ratio'],'ratio_follow':plan['ratio_follow']},{'kind':'scene','references':plan['references']})
        qwen_prompts.dimensions(plan)
        opts['image_plan']=plan
    if kind in ('keyframe','tail'):
        shot=next((s for s in p['shots'] if s['id']==target),None)
        if not shot or not shot.get('native'):raise ValueError('请先生成本镜具体分镜，再生成组合关键帧')
        if not store.settings().get('ai_url'):raise ValueError('请先配置文本 AI，用于关键帧资产关联与提示词编写')
        opts['media_kind']='image'
    if kind=='h3':h3.reference_preview(p,target)
    if kind=='h3_upscale':
        output,saved=h3_workflow.upscale_source(p,opts.get('scope_shot'),opts.get('source_output_id'))
        target=str(saved['step']['index'])
        opts.update(seed=saved['seed'],quality='second',resolution='1080P',source_output_id=output['id'])
    if p.get('workflow_schema_version',1)>=2:
        from . import workbench
        if kind=='h3_generate':
            if not workbench.current_review(p,'animatic'):raise ValueError('请先在总览中审核当前动态分镜预演')
            if p.get('assets') and not workbench.current_review(p,'assets'):raise ValueError('请先在总览中审核当前角色外观与音色设定')
        if kind=='export' and opts.get('format')=='mp4' and not workbench.current_review(p,'delivery'):raise ValueError('请先在剪辑页审核当前全片时间线')
    if kind=='h3_generate' or (kind=='export' and opts.get('format')=='h3_workflow'):
        if kind=='export' and opts.get('workflow_snapshot'):
            saved=h3_workflow.saved_snapshot(p,opts['workflow_snapshot'],target)
            opts.update(seed=saved['seed'],quality=saved['quality'],resolution=saved['resolution']);step=saved['step']
        else:
            if opts.get('quality','first')!='first' or opts.get('resolution','540P')!='540P':raise ValueError('普通生成只提供540P一采预览；二采请先勾选采用视频，再使用二采放大按钮')
            opts.update(quality='first',resolution='540P')
            step=h3_workflow.current_step(p,target,opts.get('scope_shot'))
        if 'seed' not in opts and not opts.get('new_variant'):
            recalled=h3_workflow.recalled_seed(p,step,opts.get('scope_shot'))
            if recalled is not None:opts['seed']=recalled

    opts['seed_explicit']='seed' in opts
    opts['seed']=int(opts.get('seed',secrets.randbelow(2147483647)))
    if not 0<=opts['seed']<=2147483647:raise ValueError('种子范围为0–2147483647')
    if kind=='character_card':
        asset=next((a for a in p['assets'] if a['id']==target),None)
        if not asset:raise ValueError('角色元素不存在')
        image_prompts.card_references(asset)
    if kind in ('asset_prompt','preview','character_profile','asset_profile'):
        asset=next((a for a in p['assets'] if a['id']==target),None)
        if not asset:
            raise ValueError('资产不存在')
        if kind=='character_profile' and asset['kind']!='character':raise ValueError('角色造型提取只适用于角色元素')
        from . import asset_card_render
        if kind=='preview' and asset_card_render.uses_card(asset):asset_card_render.prompt(asset,opts.get('text_only',False))
        if kind=='preview' and not asset_card_render.uses_card(asset) and not asset['prompt'].strip():
            raise ValueError('请先生成或填写资产提示词')
        if kind=='preview' and character_profiles.requires_profile_extraction(asset):raise ValueError('角色描述仍是剧情经历，请先重新生成角色提示词，自动提取独立造型')
        if kind=='preview' and asset['model']=='z-image' and asset['references'] and not opts.get('text_only'):
            raise ValueError('多参考预览请选择 Qwen-Image-2.1；Z-Image 只能明确选择不带参考的概念预览')
    if kind in ('schedule','generate','frame'):
        shot=next((s for s in p['shots'] if s['id']==target),None)
        if not shot:
            raise ValueError('镜头不存在')
        from . import shot_continuity
        if kind in ('generate','frame'):shot_continuity.gate(p,target)
        if kind=='generate':
            if not p['confirmed']:
                raise ValueError('请先确认分镜')
            timing.render(shot)
            director.validate_project_shots(p)
    if kind=='audio' and opts.get('profile') not in ('tts','music'):
        raise ValueError('音频类型无效')
    if kind=='audio' and opts.get('tts_engine')=='yovoice':
        from . import yovoice_cli
        opts=yovoice_cli.prepare(opts)
    if kind=='audio' and opts.get('tts_engine')=='owl-speech-timing':raise ValueError('请通过分镜的 TTS 实测时序按钮启动配音测时')
    if kind=='audio' and opts.get('profile')=='tts' and opts.get('tts_engine')=='owl-qwen3':
        from . import tts_workflow
        opts=tts_workflow.prepare(opts)
    if kind=='export' and opts.get('format') not in ('mp4','animatic','zip','edl','prompts','h3','h3_workflow'):
        raise ValueError('导出格式无效')
    if kind=='schedule' and opts.get('use_tts'):
        from . import speech_audio
        task=speech_audio.enqueue(p,target,opts['seed'])
        return {'id':task['id'],'status':task['status']}
    task=jobs.enqueue(kind,p,target,opts)
    return {'id':task['id'],'status':task['status']}


@app.post('/api/projects/{pid}/shots/{sid}/video/adopt')
def adopt_video(pid:str,sid:str,body:dict):
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请刷新后选择视频')
        video_versions.adopt(p,sid,body.get('output_id'),bool(body.get('adopt',True)))
        return store.save_project(p,p['revision'])


@app.post('/api/projects/{pid}/h3/batch/{action}')
def h3_batch(pid:str,action:str,body:dict):
    if action not in ('rewrite','generate','upscale'):raise ValueError('不支持的 H3 批量操作')
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请刷新后操作')
        created=[];skipped=[];batch_id=store.uid();active=store.task_list()
        kind={'rewrite':'h3','generate':'h3_generate','upscale':'h3_upscale'}[action]
        from . import shot_merge
        selected_ids=None if body.get('shot_ids') is None else {shot_merge.leader(p,sid) for sid in body['shot_ids']} if action!='upscale' else set(body['shot_ids'])
        for i,shot in enumerate(p.get('shots',[]),1):
            if action!='upscale' and shot_merge.leader(p,shot['id'])!=shot['id']:continue
            if selected_ids is not None and shot['id'] not in selected_ids:continue
            sid=shot['id'];name=f'第 {shot.get("generation_index",i)} 镜'
            try:
                if action=='rewrite':
                    if h3.package(p,sid) and h3.package(p,sid).get('steps'):
                        skipped.append({'shot_id':sid,'name':name,'reason':'已有完整且有效的 H3 提示词，已跳过'});continue
                    h3.groups(h3.scope(p,sid,allow_reference_prepare=True));targets=[(sid,{})]
                elif action=='generate':
                    package=h3.package(p,sid)
                    if not h3.is_current(p,package,sid):raise ValueError('请先转写本镜 H3 提示词')
                    targets=[(str(step['index']),{'quality':'first','resolution':'540P'}) for step in package['steps']]
                else:
                    outputs=video_versions.selected(shot)
                    if not outputs:raise ValueError('尚未勾选采用分镜视频')
                    targets=[]
                    for output in outputs:
                        try:
                            _,saved=h3_workflow.upscale_source(p,sid,output['id'])
                            targets.append((str(saved['step']['index']),{'source_output_id':output['id'],'seed':saved['seed'],'quality':'second','resolution':'1080P'}))
                        except ValueError as e:skipped.append({'shot_id':sid,'name':name,'reason':str(e)})
                for target,opts in targets:
                    if action=='generate':
                        step=next(row for row in package['steps'] if str(row['index'])==target)
                        records=step.get('outputs',[])+shot.get('outputs',[])
                        if any(m.get('media') and store.media_path(m['media']).is_file() and str(m.get('h3_step',step['index']))==target and m.get('source_shot_ids',step.get('source_shot_ids'))==step.get('source_shot_ids') for m in records):
                            skipped.append({'shot_id':sid,'name':name,'reason':'本步已有视频，已跳过'});continue
                    if action=='upscale' and any(m.get('source_output_id')==opts['source_output_id'] and m.get('media') and store.media_path(m['media']).is_file() for m in shot.get('outputs',[])):
                        skipped.append({'shot_id':sid,'name':name,'reason':'此版本已有二采视频，已跳过'});continue
                    if any(t['project_id']==pid and t['kind']==kind and t['status'] in ('queued','running','cancelling') and (t.get('target')==sid if action=='rewrite' else t.get('target')==target and t.get('options',{}).get('scope_shot')==sid and (action!='upscale' or t.get('options',{}).get('source_output_id')==opts['source_output_id'])) for t in active):
                        skipped.append({'shot_id':sid,'name':name,'reason':'相同任务已在队列中'});continue
                    opts.update(batch_id=batch_id,scope_shot=sid)
                    opts.setdefault('seed',secrets.randbelow(2147483647))
                    task=jobs.enqueue(kind,p,target,opts);active.append(task)
                    created.append({'id':task['id'],'shot_id':sid,'name':name,'status':task['status']})
            except ValueError as e:skipped.append({'shot_id':sid,'name':name,'reason':str(e)})
        return {'created':created,'skipped':skipped,'batch_id':batch_id}


@app.post('/api/projects/{pid}/assets/batch/{action}')
def asset_batch(pid:str,action:str,body:dict):
    if action not in ('prompts','previews','enrich'):
        raise ValueError('不支持的资产批量操作')
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:
            raise store.Conflict('项目已更新，请先加载最新内容')
        if not p['assets']:
            raise ValueError('请先添加资产元素')
        if action in ('enrich','prompts') and (not p.get('production_scheme',{}).get('art') or not p.get('production_scheme',{}).get('cinematic')):raise ValueError('请先确定镜头与美术方案')
        if action=='enrich':
            if not script_source.ready(p):
                raise ValueError('请先完成有效剧本，再补充资产描述')
            script_source.asset_text(p)
            if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI')
        created=[];skipped=[]
        kind='asset_enrich' if action=='enrich' else 'asset_prompt' if action=='prompts' else 'preview'
        text_only=body.get('text_only',{})
        batch_id=store.uid()
        active=store.task_list()
        for asset in p['assets']:
            reason=''
            if action=='enrich' and asset.get('enrichment_source_hash'):
                skipped.append({'asset_id':asset['id'],'name':asset['name'],'reason':'已有补充描述，已跳过'});continue
            if action=='previews' and (asset.get('adopted') or any(m.get('media') for m in asset.get('previews',[]))):
                skipped.append({'asset_id':asset['id'],'name':asset['name'],'reason':'已有预览图片，已跳过'});continue
            if action=='previews' and any(t['project_id']==pid and t.get('target')==asset['id'] and t['kind']=='preview' and t['status'] in ('queued','running','cancelling') for t in active):
                skipped.append({'asset_id':asset['id'],'name':asset['name'],'reason':'已有预览任务，已跳过'});continue
            from . import asset_card_render
            if action=='prompts' and asset_card_render.uses_card(asset):
                skipped.append({'asset_id':asset['id'],'name':asset['name'],'reason':'5S 资产直接生图，无需转换提示词'})
                continue
            if action=='previews' and asset_card_render.uses_card(asset):
                try:asset_card_render.prompt(asset,bool(text_only.get(asset['id'])))
                except ValueError:
                    skipped.append({'asset_id':asset['id'],'name':asset['name'],'reason':'请先填写完整的 5S 描述'})
                    continue
            if action=='enrich' and asset.get('variant'):reason='状态变体使用自己的参考图编辑提示词，已跳过'
            if action=='enrich' and any(t['project_id']==pid and t.get('target')==asset['id'] and t['kind']=='asset_enrich' and t['status'] in ('queued','running','cancelling') for t in active):
                reason='已有补充描述任务，正在处理'
            if action=='prompts' and str(asset.get('prompt') or '').strip():
                reason='已有提示词，已跳过'
            elif action=='prompts' and any(t['project_id']==pid and t.get('target')==asset['id'] and t['kind']=='asset_prompt' and t['status'] in ('queued','running','cancelling') for t in active):
                reason='已有提示词任务，正在处理'
            opts={'seed':secrets.randbelow(2147483647),'batch_id':batch_id,'ensure_prompt':action=='previews','text_only':bool(text_only.get(asset['id']))}
            if action=='previews' and asset['model']=='z-image' and asset['references'] and not opts['text_only']:
                reason='带参考图请切换 Qwen，或明确勾选不使用参考图'
            if action=='previews' and asset['model']=='qwen-image-2.1' and len(asset['references'])>16:
                reason='Qwen 一次最多使用16张参考图，请先减少引用'
            if action=='previews' and asset.get('prompt') and character_profiles.requires_profile_extraction(asset):
                reason='角色描述仍是剧情经历，请先重新生成提示词以提取独立造型'
            if reason:
                skipped.append({'asset_id':asset['id'],'name':asset['name'],'reason':reason})
                continue
            task=jobs.enqueue(kind,p,asset['id'],opts)
            created.append({'id':task['id'],'asset_id':asset['id'],'name':asset['name'],'status':task['status']})
        return {'created':created,'skipped':skipped,'batch_id':batch_id}


@app.post('/api/projects/{pid}/shots/{sid}/review')
def human_review(pid:str,sid:str,body:dict):
    p=store.get_project(pid)
    if body.get('revision')!=p['revision']:
        raise store.Conflict('镜头已更新，请重新检查')
    shot=next(s for s in p['shots'] if s['id']==sid)
    shot['natural_status']='human_reviewed'
    checked=timing.validate(shot)
    if not checked['ok']:
        raise ValueError('；'.join(checked['errors']))
    p['confirmed']=False
    return store.save_project(p,p['revision'])


@app.post('/api/projects/{pid}/canvas/{action}')
def canvas_action(pid:str,action:str,body:dict):
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请刷新后调整画布')
        if action=='layout':production_canvas.layout(p,body.get('layout'))
        elif action=='reference':
            if type(body.get('bound')) is not bool:raise ValueError('bound 需要布尔值')
            production_canvas.reference(p,body.get('shot_id'),body.get('asset_id'),body['bound'],body.get('from_shot_id'))
        elif action=='assemble':production_canvas.assemble(p);validate_project(p)
        else:raise ValueError('不支持的画布操作')
        return store.save_project(p,p['revision'])


@app.post('/api/projects/{pid}/shots/{sid}/frames/{action}')
def frame_action(pid:str,sid:str,action:str,body:dict):
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请刷新后选择首帧')
        shot_frames.change(p,sid,action,body.get('media'))
        return store.save_project(p,p['revision'])


@app.post('/api/projects/{pid}/shots/{sid}/previous-tail')
def previous_tail(pid:str,sid:str,body:dict):
    p=store.get_project(pid)
    if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请先刷新')
    reference=shot_references.capture(p,sid)
    try:
        with jobs.TASK_LOCK:
            current=store.get_project(pid)
            if current['revision']!=p['revision']:raise store.Conflict('提取尾帧期间项目已更新，请重新提取')
            shot_references.adopt(current,sid,reference)
            return store.save_project(current,current['revision'])
    except Exception:
        store.media_path(reference['media']).unlink(missing_ok=True);raise


@app.post('/api/projects/{pid}/shots/{sid}/timing/accept')
def accept_timing(pid:str,sid:str,body:dict):
    if any(t['project_id']==pid and t['kind']=='storyboard' and t['status'] in ('running','queued','cancelling') for t in store.task_list()):raise ValueError('分镜生成仍在进行；时长审查可以并行，采用建议请等生成任务结束，避免改变后续镜头的连续性依据')
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请先加载最新建议')
        if any(t['project_id']==pid and t['kind'] in ('storyboard','storyboard_outline','storyboard_timing','schedule') and t['status'] in ('queued','running','cancelling') for t in store.task_list()):
            raise ValueError('请等待当前分镜或时序任务结束，再采用建议时长')
        shot=next((s for s in p['shots'] if s['id']==sid),None)
        if not shot:raise ValueError('镜头不存在')
        timing.adopt(p,shot,body.get('suggestion_id'))
        return store.save_project(p,p['revision'])


@app.post('/api/projects/{pid}/storyboard/outline/confirm')
def confirm_outline(pid:str,body:dict):
    from . import storyboard_generation
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:raise store.Conflict('分镜汇总已更新，请先刷新并核对')
        state=storyboard_generation.valid_state(p)
        if state and state.get('outline_draft'):raise ValueError('汇总画面方案尚未完成，请先继续生成汇总，再核对确认')
        if not script_source.ready(p) or not state or not state.get('outlines') or not state.get('preparation'):raise ValueError('当前剧本或方案没有有效分镜汇总，请先重新生成汇总')
        if p.get('storyboard_method')=='source_units' and body.get('semantic_review') is not True:raise ValueError('请人工核对原文意义、单元粒度和背景信息交付后再确认汇总')
        if any(t['project_id']==pid and t['kind'] in ('storyboard','storyboard_outline','storyboard_timing') and t['status'] in ('queued','running','cancelling') for t in store.task_list()):raise ValueError('请等待当前分镜任务结束后，再确认汇总')
        state['outline_confirmed']=True
        if p.get('storyboard_method')=='source_units':state.setdefault('outline_review',{}).update(atomic_granularity='user_confirmed',semantic_fidelity='user_confirmed',review_basis='用户确认原文意义、单元粒度与背景交付',reviewed_at=time.time())
        state['message']='分镜汇总已确认，可以按汇总逐镜生成具体提示词'
        store.save_project(p,p['revision'])
    return store.get_project(pid)


@app.post('/api/projects/{pid}/confirm')
def confirm(pid:str,body:dict):
    p=store.get_project(pid)
    if body.get('revision')!=p['revision']:
        raise store.Conflict('项目已更新，请重新确认')
    if not p['shots']:
        raise ValueError('请先生成分镜')
    if p.get('storyboard_generation') and not p.get('native_storyboard_current'):raise ValueError('分镜尚未全部完成或生成依据已修改，请继续生成并完成整体校验后确认')
    if p.get('timing_revision',{}).get('status') in ('queued','running'):raise ValueError('时间修正尚未结束，请等待正式时间标签确定后确认分镜')
    for i,s in enumerate(p['shots']):
        checked=timing.validate(s)
        if not checked['ok']:
            raise ValueError(f'镜头{i+1}：'+'；'.join(checked['errors']))
    if abs(sum(s['duration'] for s in p['shots'])-p['duration'])>0.02:
        raise ValueError('分镜总时长与成片时长不一致；请调整片长或拆镜，不自动压缩动作')
    director.validate_project_shots(p)
    p['confirmed']=True
    return store.save_project(p,p['revision'])


@app.post('/api/timing/validate')
def timing_check(body:dict):
    return timing.validate(body)


@app.post('/api/upload')
async def upload(file:UploadFile=File(...)):
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ('.png','.jpg','.jpeg','.webp','.mp4','.mov','.webm','.wav','.mp3','.m4a','.ogg','.flac'):
        raise ValueError('支持图片、视频和音频文件')
    name=store.uid()+suffix
    path=store.media_path(name)
    total=0
    with path.open('wb') as stream:
        while chunk:=await file.read(1024*1024):
            total+=len(chunk)
            if total>1024*1024*1024:
                path.unlink(missing_ok=True)
                raise ValueError('单文件不能超过1GB')
            stream.write(chunk)
    kind='image' if suffix in ('.png','.jpg','.jpeg','.webp') else 'video' if suffix in ('.mp4','.mov','.webm') else 'audio'
    if kind=='image':
        try:
            with Image.open(path) as image:
                image.verify()
        except Exception:
            path.unlink(missing_ok=True)
            raise ValueError('图片文件无效')
    return {'id':store.uid(),'media':name,'kind':kind,'name':file.filename,'size':total}


@app.get('/media/{name}')
def media(name:str):
    path=store.media_path(name)
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path,filename=path.name if path.suffix in ('.zip','.md','.edl') else None)


@app.get('/api/tasks')
def tasks():
    from . import task_scheduler
    return task_scheduler.public_rows()


@app.post('/api/tasks/{tid}/run-parallel')
def run_parallel(tid:str):
    from . import task_scheduler
    return task_scheduler.run_parallel(tid)


@app.post('/api/tasks/{tid}/cancel')
def cancel(tid:str):
    return jobs.cancel(tid)


@app.post('/api/tasks/cancel-all')
def cancel_all():
    return jobs.cancel_all()


@app.put('/api/workflows/{profile}')
def workflow(profile:str,body:dict):
    if profile not in ('video','tts','music'):
        raise ValueError('工作流类型不支持')
    graph=body.get('graph')
    if not isinstance(graph,dict) or not graph or any(not isinstance(v,dict) or 'class_type' not in v or not isinstance(v.get('inputs'),dict) for v in graph.values()):
        raise ValueError('请提供API格式工作流 graph，不支持直接导入界面格式')
    for key,value in body.get('bindings',{}).items():
        slots=value if key=='references' else [value]
        for slot in slots:
            if str(slot['node']) not in graph or slot['input'] not in graph[str(slot['node'])]['inputs']:
                raise ValueError('输入槽指向不存在的节点或参数')
    workflow_files.write_json(workflow_files.IMPORTED/f'{profile}.json',body)
    return {'ok':True}


@app.get('/api/workflows')
def workflow_list():
    return {p:(workflow_files.IMPORTED/f'{p}.json').exists() for p in ('video','tts','music')}


@app.get('/api/events')
def events():
    import asyncio
    async def generate():
        while True:
            yield 'data: '+json.dumps({'projects':projects(),'tasks':tasks()},ensure_ascii=False)+'\n\n'
            await asyncio.sleep(2)
    return StreamingResponse(generate(),media_type='text/event-stream')


@app.get('/api/projects/{pid}/agent')
def agent_state(pid:str):
    return agent.state(pid)


@app.post('/api/projects/{pid}/agent')
def agent_message(pid:str,body:dict,request:Request):
    return agent.enqueue(pid,body,allow_local=local(request))


@app.get('/api/skills')
def skills():
    return {'items':site_skills.catalog(agent.TOOLS),'tools':[{'name':k,'description':v[0]} for k,v in agent.TOOLS.items()],
            'limitations':['当前文本AI不能自动听取音频或理解视频画面；可使用用户提供的歌词、描述和时间标注。','技能导入只读取说明和文本参考文件；脚本与外部CLI需要另行接入工具。']}


@app.post('/api/projects/{pid}/creative-skills/preview')
def creative_skill_preview(pid:str,body:dict):
    p=store.get_project(pid)
    for key in ('creative_skills','script_task','story_policy'):
        if key in body:p[key]=body[key]
    creative_rules.config(p)
    return creative_rules.preview(p)


@app.post('/api/projects/{pid}/shots/{sid}/continuity/accept')
def accept_shot_continuity(pid:str,sid:str,body:dict):
    from . import shot_continuity
    p=store.get_project(pid)
    if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请刷新后复核')
    shot_continuity.accept(p,sid,body.get('note'),body.get('shot_hash'))
    if storyboard_generation_ready(p):p['native_storyboard_current']=True
    return store.save_project(p,p['revision'])


def storyboard_generation_ready(p):
    from . import storyboard_generation as sg
    state=sg.valid_state(p)
    return bool(state and len(p['shots'])==state.get('total') and not any(s.get('continuity_review',{}).get('status')=='needs_review' for s in p['shots']))


@app.post('/api/skills/import')
async def skill_upload(file:UploadFile=File(...)):
    content=await file.read(site_skills.MAX_BYTES+1)
    return site_skills.upload(file.filename,content)


@app.post('/api/skills/import-local')
def skill_local(body:dict,request:Request):
    if not local(request):raise HTTPException(403,'本机路径导入请在本机网页完成，其他设备可上传技能文件')
    return site_skills.import_path(str(body.get('path','')).strip())


@app.post('/api/skills/{skill_id}/enable')
def skill_enable(skill_id:str,body:dict):
    if type(body.get('enabled')) is not bool:raise ValueError('enabled 需要布尔值')
    site_skills.enable(skill_id,body['enabled']);return {'ok':True}


stage_routes.install(app)
from . import skill_workflows
skill_workflows.install_routes(app)
from . import story_promo
story_promo.install_routes(app)
from . import auto_creation
auto_creation.install_routes(app)
from . import storyboard_prose
storyboard_prose.install_routes(app)
from . import keyframes
keyframes.install_routes(app)
from . import soundtrack
soundtrack.install_routes(app)
from . import audio_library
audio_library.install_routes(app)
from . import tts_workflow
tts_workflow.install_routes(app)
from . import yovoice_cli
yovoice_cli.install_routes(app)
from . import performance
performance.install(app)
from . import speech_mix
speech_mix.install_routes(app)
from . import media_evidence
media_evidence.install_routes(app)

@app.post('/api/projects/{pid}/assets/exploration/adopt')
def adopt_exploration(pid:str,body:dict):
    from . import asset_exploration
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请刷新后采用')
        asset_exploration.adopt(p,body.get('ids'))
        return store.save_project(p,p['revision'])


@app.post('/api/projects/{pid}/assets/variants')
def create_asset_variant(pid:str,body:dict):
    from . import asset_variants
    with jobs.TASK_LOCK:
        p=store.get_project(pid)
        if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请先保存或加载最新内容')
        if not store.settings().get('ai_url') or not store.settings().get('ai_model'):raise ValueError('请先配置文本AI')
        asset=asset_variants.create(p,body)
        validate_project(p)
        saved=store.save_project(p,p['revision'])
        task=jobs.enqueue('asset_prompt',saved,asset['id'],{})
        return {'project':saved,'asset_id':asset['id'],'task_id':task['id']}

from . import seedance_integration
seedance_integration.install(app)
from . import frame_images
frame_images.install(app)
from . import reference_library,authoring
reference_library.install(app)
authoring.install(app)
from . import visual_reference
visual_reference.install(app)
from . import jimeng_reference
jimeng_reference.install(app)

from . import queue_control
queue_control.install(app)

@app.get('/api/projects/{pid}/shots/{sid}/h3/reference-preview')
def h3_reference_preview(pid:str,sid:str):
    return h3.reference_preview(store.get_project(pid),sid)

from . import workbench
workbench.install(app)

from . import creative_revision
creative_revision.install(app)
from . import local_subtitles
local_subtitles.install(app)

from . import chatcut_bridge
chatcut_bridge.install(app)
from . import medical_director
medical_director.install(app)
from . import local_ocr
local_ocr.install(app)

from . import studio_import
studio_import.install(app)

web_dist=Path(os.environ.get('DIRECTOR_STUDIO_DIST',str(store.ROOT/'dist')))
if web_dist.exists():
    app.mount('/',StaticFiles(directory=web_dist,html=True),name='web')






