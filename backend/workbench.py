"""Read-only workflow diagnostics and version-bound human reviews."""
import copy, hashlib, json, math, time
from . import store, timing_speech, video_versions

VERSION = 2
STAGES = [('script','剧本','documents','ai'),('assets','设定','assets','ai'),
          ('shots','分镜','shots','ai'),('animatic','预演','overview','local'),
          ('video','生成','h3','ai_local'),('edit','剪辑','timeline','local'),
          ('delivery','交付','timeline','human')]


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def media_exists(name):
    return bool(name and store.media_path(name).is_file())


def animatic_basis(p):
    return digest([{'id':s['id'],'description':s.get('description'),'duration':s.get('duration'),
                    'frames':[s.get(k) for k in ('first_frame','adopted_keyframe','adopted_tailframe')],
                    'speech':s.get('sound_script'),'audio':s.get('speech_track'),
                    'mode':s.get('h3_audio_mode'),'performance':s.get('performance')}
                   for s in p.get('shots',[])])


def review_basis(p,kind,target=None):
    if kind=='assets':return digest({'assets':[{k:a.get(k) for k in ('id','kind','name','card','description','adopted','voice','character_mod')} for a in p.get('assets',[])],'voice_roles':p.get('tts_voice_roles',{})})
    if kind=='animatic':return animatic_basis(p)
    if kind=='delivery':return digest({'timeline':p.get('timeline',[]),'captions':p.get('captions',[])})
    if kind=='video':
        media=next((m for s in p.get('shots',[]) for m in s.get('outputs',[]) if m.get('id')==target),None)
        if not media:raise ValueError('视频版本不存在')
        return digest(media)
    raise ValueError('审核类别无效')


def current_review(p,kind,target=None):
    key=kind+(':'+target if target else '')
    row=p.get('workflow_reviews',{}).get(key)
    return row if row and row.get('basis')==review_basis(p,kind,target) else None


def preflight(p,sid=None,check_files=True):
    from . import h3_reference_limits, h3_voice, performance
    issues=[];shots=[s for s in p.get('shots',[]) if not sid or s['id']==sid]
    if sid and not shots:raise ValueError('分镜不存在')
    if not shots:issues.append({'level':'error','message':'请先建立分镜','tab':'documents'})
    def add(level,message,s,tab):issues.append({'level':level,'message':message,'shot_id':s['id'],'tab':tab})
    for s in shots:
        duration=s.get('duration',0)
        if type(duration) not in (int,float) or not math.isfinite(duration) or duration<=0:
            add('error','镜头时长需为有效正数',s,'shots');continue
        lines=timing_speech.raw_catalogue(p,s)
        estimate=sum(float(r['minimum_seconds']) for r in lines)
        if estimate>duration:add('warning',f'顺序对白预计 {estimate:.1f} 秒，超过镜头 {duration:g} 秒；请检查并行或延长',s,'voice')
        try:
            state=performance.status(p,s)
            if not state['visual']:add('error','表演、时序与画面尚未定稿',s,'voice')
        except (ValueError,KeyError):add('error','编排依据需要更新',s,'voice')
        if s.get('h3_audio_mode')=='locked':
            from . import speech_audio
            if not speech_audio.current(p,s):add('error','锁定模式缺少当前正式音轨',s,'voice')
        elif check_files:
            try:h3_voice.references(p,{'clips':[{'source_id':s['id']}]},[])
            except ValueError as e:add('error',str(e),s,'voice')
        roles=s.get('h3_frame_roles')
        if roles is None:roles=['first'] if s.get('h3_reference_mode') in ('first_frame','previous_tail') else ['first','keyframe','tail']
        if s.get('h3_reference_mode') not in ('text','assets'):
            for role,field in [('first','first_frame'),('keyframe','adopted_keyframe'),('tail','adopted_tailframe')]:
                if role in roles and s.get(field) and check_files and not media_exists(s[field]):add('error',role+' 已采用图片缺失',s,'frames')
        # Use the same scoped reference planner as the actual writer, including group limits.
        if check_files:
            try:
                from . import h3
                h3.reference_preview(p,s['id'])
            except (ValueError,KeyError) as e:add('error',str(e),s,'h3')
        for package in [p.get('documents',{}).get('h3_shots',{}).get(s['id'])]:
            if package:
                for step in package.get('steps',[]):
                    try:h3_reference_limits.validate_media(step.get('references',[]),int(bool(step.get('audio_binding'))));h3_reference_limits.validate_prompt(step.get('prompt',''))
                    except ValueError as e:add('error',str(e),s,'h3')
    # Never equate absent runtime information with healthy hardware.
    issues=list({(r.get('shot_id'),r['level'],r['message']):r for r in issues}.values())
    return {'ready':not any(r['level']=='error' for r in issues),'issues':issues,
            'shot_count':len(shots),'runtime_checked':False,'runtime_message':'节点与设备在实际提交前检查',
            'estimated_seconds':None,'estimate_message':'暂无相同规格历史估算；不据此承诺完成时间'}


def timeline_progress(p):
    """Only real video clips represent final editing, not an image animatic."""
    clips=[c for c in p.get('timeline',[]) if c.get('kind')=='video' and media_exists(c.get('media'))]
    used={c['media'] for c in clips}
    shots=p.get('shots',[])
    covered=sum(any(m.get('media') in used for m in video_versions.selected(s)) for s in shots)
    return covered,len(shots),len(clips)


def workflow_nodes(p,legacy):
    from . import performance
    shots=p.get('shots',[]);base={n['id']:n for n in legacy};nodes=[]
    def add(key,label,tab,work,lane,count=0,total=1,hint='',state=None,optional=False):
        state=state or ('adopted' if total and count>=total else 'partial' if count else 'empty')
        nodes.append(dict(id=key,label=label,tab=tab,work=work,lane=lane,count=count,total=total,state=state,hint=hint,optional=optional))
    add('brief','创作设定','brief','human',0,int(bool(p.get('story','').strip()) and bool(p.get('parameters'))),hint='填写创意、时长、画幅与创作约束。')
    add('skills','案例与模板','skills','human',0,int(bool(p.get('primary_reference') or p.get('reference_selection_resolved'))),hint='选择参考案例与模板；也可以不使用模板。',optional=True)
    add('style','美术风格','production','human',0,int(bool(p.get('art_references',{}).get('applied') or p.get('seedance_professional',{}).get('art',{}).get('enabled'))),hint='选择整体视觉风格；不指定时沿用创作设定。',optional=True)
    add('script','创作概览','documents','ai',0,base['script']['count'],hint='整理剧本、资产设计、分镜与声音脚本，审核后采用。',state='stale' if p.get('script_needs_rewrite') else base['script']['state'])
    add('shots','分镜编排','shots','ai',1,len(shots),len(shots),hint='逐镜检查动作、对白、运镜与前后衔接。',state='stale' if p.get('storyboard_generation',{}).get('status')=='stale' else None)
    add('assets','资产与角色','assets','ai_local',1,base['assets']['count'],base['assets']['total'],hint='制作角色、场景、道具，确认角色 MOD 与声音样本。',state=base['assets']['state'])
    timed=0
    for shot in shots:
        try:timed+=bool(performance.status(p,shot)['visual'])
        except (ValueError,KeyError,TypeError):pass
    add('voice','声音与时序','voice','human',1,timed,len(shots),hint='确认台词、说话人、动作和预计时序。声音参考模式无需先生成固定配音。')
    frame_count=0
    for s in shots:
        roles=s.get('h3_frame_roles')
        if roles is None:roles=['first'] if s.get('h3_reference_mode') in ('first_frame','previous_tail') else ['first','keyframe','tail']
        frame_count+=s.get('h3_reference_mode') in ('text','assets') or bool(roles) and all(media_exists(s.get({'first':'first_frame','keyframe':'adopted_keyframe','tail':'adopted_tailframe'}.get(r,''))) for r in roles)
    add('frames','首·关键·尾帧','frames','ai_local',1,int(frame_count),len(shots),hint='制作并采用当前镜头启用的帧参考；文生和仅资产参考模式不要求帧图。')
    add('animatic','预演审核','overview','human',1,base['animatic']['count'],hint='本地播放动态分镜，人工检查节奏、对白与衔接后确认。',state=base['animatic']['state'])
    generated=sum(any(m.get('kind')=='video' and media_exists(m.get('media')) for m in s.get('outputs',[])) for s in shots)
    add('video','H3 视频','h3','ai_local',2,generated,len(shots),hint='提交已确认镜头和实际参考素材；H3 生成画面、声音与口型。')
    reviewed=sum(bool(video_versions.selected(s)) and all(media_exists(m.get('media')) and current_review(p,'video',m['id']) for m in video_versions.selected(s)) for s in shots)
    add('review','版本审片','shots','human',2,int(reviewed),len(shots),hint='打开镜头版本对比，检查外观、台词、动作、衔接与技术质量，审核后采用。')
    music=any(v.get('outputs') for v in p.get('soundtrack',{}).values() if isinstance(v,dict)) or any(c.get('kind')=='audio' and media_exists(c.get('media')) for c in p.get('timeline',[]))
    add('soundtrack','配乐与声音','soundtrack','ai',2,int(music),hint='按需要制作配乐或加入现有音轨；不需要配乐可直接剪辑。',optional=True)
    count,total,clips=timeline_progress(p)
    add('edit','剪辑合成','timeline','local',2,count,total,hint='剪辑时间线需包含已采用的真实视频。静帧预演与空占位不计为成片剪辑完成。',state='partial' if clips and count<total else None)
    add('delivery','审核与导出','timeline','human',2,base['delivery']['count'],hint='完整审看时间线并确认交付，再选择 MP4 或项目包导出。',state=base['delivery']['state'])
    return nodes


def status(p):
    shots=p.get('shots',[]);documents=p.get('documents',{});run=p.get('authoring_run',{})
    adopted=sum(bool(video_versions.selected(s)) for s in shots)
    frames=sum(bool(s.get('first_frame') or s.get('adopted_keyframe') or s.get('adopted_tailframe')) for s in shots)
    reviewed=sum(bool(current_review(p,'video',m['id'])) for s in shots for m in video_versions.selected(s))
    all_outputs=sum(len(s.get('outputs',[])) for s in shots)
    counts={'script':int(bool(p.get('script_confirmed'))),'assets':sum(bool(a.get('adopted')) for a in p.get('assets',[])),
            'shots':len(shots),'animatic':int(bool(current_review(p,'animatic'))),'video':adopted,
            'edit':timeline_progress(p)[0],
            'delivery':int(bool(current_review(p,'delivery')))}
    targets={'script':1,'assets':len(p.get('assets',[])),'shots':len(shots),'animatic':1,'video':len(shots),'edit':len(shots),'delivery':1}
    nodes=[]
    for key,label,tab,work in STAGES:
        n=counts[key];total=targets[key]
        state='adopted' if total and n>=total else 'partial' if n else 'empty'
        if key=='assets' and total and n>=total and not current_review(p,'assets'):state='review'
        if key=='script' and run.get('status')=='awaiting_review':state='review'
        nodes.append({'id':key,'label':label,'tab':tab,'work':work,'state':state,'count':n,'total':total})
    return {'schema_version':VERSION,'impact':p.get('workflow_impact',[]),'nodes':nodes,'workflow_nodes':workflow_nodes(p,nodes),'shot_count':len(shots),'adopted_shots':adopted,
            'reviewed_videos':reviewed,'video_versions':all_outputs,'shots_with_frames':frames,
            'animatic_basis':animatic_basis(p),'animatic_review':current_review(p,'animatic'),
            'assets_basis':review_basis(p,'assets'),'assets_review':current_review(p,'assets'),'delivery_basis':review_basis(p,'delivery'),'delivery_review':current_review(p,'delivery')}


def install(app):
    @app.get('/api/projects/{pid}/workbench')
    def read(pid:str):return status(store.get_project(pid))

    @app.get('/api/projects/{pid}/preflight')
    def check(pid:str,shot_id:str|None=None):
        result=preflight(store.get_project(pid),shot_id)
        from . import h3_workflow,comfy
        runtime=h3_workflow.describe();result['runtime_checked']=True
        result['runtime_message']='H3 工作流节点已检查' if runtime.get('ready') else runtime.get('error','H3 工作流尚未连接')
        if not runtime.get('ready'):
            result['ready']=False;result['issues'].append({'level':'error','message':result['runtime_message'],'tab':'h3'})
        else:
            try:
                stats=comfy.request('GET','/system_stats',timeout=3)
                result['devices']=[{'name':d.get('name'),'type':d.get('type'),'vram_total':d.get('vram_total')} for d in stats.get('devices',[])]
                if shot_id:result.update(estimate(store.get_project(pid),shot_id,result['devices']))
            except Exception:result['devices']=[]
        return result

    @app.get('/api/projects/{pid}/ai-calls')
    def calls(pid:str):
        store.get_project(pid)
        with store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS ai_request_log (id TEXT PRIMARY KEY, project_id TEXT, created REAL, body TEXT)')
            rows=c.execute('SELECT body FROM ai_request_log WHERE project_id=? ORDER BY created DESC LIMIT 100',(pid,)).fetchall()
        return {'calls':[json.loads(row[0]) for row in rows]}

    @app.post('/api/projects/{pid}/workbench/review')
    def review(pid:str,body:dict):
        def change(p):
            if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请重新加载审核依据')
            kind=body.get('kind');target=body.get('target');basis=review_basis(p,kind,target)
            if body.get('basis')!=basis:raise store.Conflict('审核依据已变化，请重新检查')
            decision=body.get('decision','approve')
            if decision not in ('approve','reject','revoke'):raise ValueError('审核操作无效')
            checks=body.get('checks',{})
            if kind=='delivery' and decision=='approve':
                visuals=[clip for clip in p.get('timeline',[]) if clip.get('kind') in ('video','image')]
                if not visuals:raise ValueError('请先建立剪辑时间线')
                if any(not media_exists(clip.get('media')) for clip in visuals):raise ValueError('时间线存在缺失媒体')
                used={clip['media'] for clip in visuals}
                for shot in p.get('shots',[]):
                    for output in shot.get('outputs',[]):
                        if output.get('media') in used and not current_review(p,'video',output['id']):raise ValueError('时间线中的生成视频尚未完成逐镜人工审片')
            if kind=='video' and decision=='approve' and not all(checks.get(k) is True for k in ('identity','dialogue','motion','continuity','technical')):raise ValueError('请完成全部人工审片检查')
            key=kind+(':'+target if target else '')
            if decision=='approve':p.setdefault('workflow_reviews',{})[key]={'basis':basis,'at':time.time(),'reviewer':'user','checks':checks}
            else:p.setdefault('workflow_reviews',{}).pop(key,None)
            at=body.get('at_seconds')
            if at is not None and (type(at) not in (int,float) or not math.isfinite(at) or at<0):raise ValueError('批注时间无效')
            p.setdefault('workflow_review_history',[]).append({'kind':kind,'target':target,'decision':decision,'basis':basis,'note':str(body.get('note',''))[:4000],'at_seconds':at,'created':time.time()})
        return store.mutate(pid,change)

    @app.get('/api/projects/{pid}/video-review-basis/{mid}')
    def video_basis(pid:str,mid:str):
        p=store.get_project(pid)
        return {'basis':review_basis(p,'video',mid),'review':current_review(p,'video',mid),'notes':[r for r in p.get('workflow_review_history',[]) if r.get('target')==mid]}


def register_changes(old,p):
    if not old:return
    prior={s['id']:s for s in old.get('shots',[])};assets={a['id']:a for a in old.get('assets',[])};visual=set();voices=set()
    for asset in p.get('assets',[]):
        before=assets.get(asset['id'],{})
        if any(before.get(k)!=asset.get(k) for k in ('description','card','adopted','variant')):visual.add(asset['id'])
        if before.get('voice')!=asset.get('voice'):voices.add(asset['id'])
    before_roles=old.get('tts_voice_roles',{});after_roles=p.get('tts_voice_roles',{})
    roles={name for name in before_roles.keys()|after_roles.keys() if before_roles.get(name)!=after_roles.get(name)}
    impact=[]
    fields=('duration','description','seedance_sections','creative_storyboard_prompt','sound_script','actions','camera_override','first_frame','adopted_keyframe','adopted_tailframe','h3_frame_roles','h3_reference_mode','h3_audio_mode','speech_estimates','asset_ids')
    for shot in p.get('shots',[]):
        before=prior.get(shot['id'])
        if not before:continue
        changed=[k for k in fields if before.get(k)!=shot.get(k)]
        ids=set(shot.get('asset_ids',[]));speakers={l.get('speaker') for l in shot.get('sound_script',{}).get('lines',[])}
        if ids&visual:changed.append('asset_appearance')
        if ids&voices or speakers&roles:changed.append('voice_reference')
        if changed:
            impact.append({'shot_id':shot['id'],'changed':changed,'downstream':['预演','H3提示词','视频'],'at':time.time()})
            for output in shot.get('outputs',[]):output['stale']=True
    if [s['id'] for s in old.get('shots',[])]!=[s['id'] for s in p.get('shots',[])]:impact.append({'changed':['shot_order'],'downstream':['衔接','预演','剪辑检查'],'at':time.time()})
    if impact:p['workflow_impact']=impact


def estimate(p,sid,devices):
    import statistics
    from . import h3_workflow,shot_merge
    group=shot_merge.group_for(p,sid);ids=set(group['shot_ids']) if group else {sid}
    seconds=sum(float(s['duration']) for s in p['shots'] if s['id'] in ids)
    stamp=h3_workflow.SOURCE.stat().st_mtime_ns if h3_workflow.SOURCE.exists() else None
    samples=[]
    for task in store.task_list():
        opts=task.get('options',{});length=opts.get('h3_step',{}).get('duration',0)
        if task.get('kind')=='h3_generate' and task.get('status')=='completed' and opts.get('runtime_hardware')==devices and opts.get('runtime_workflow_stamp')==stamp and opts.get('resolution')=='540P' and length and .8<=length/seconds<=1.2:
            elapsed=task.get('finished',0)-task.get('started',0)
            if 0<elapsed<86400:samples.append(elapsed/length*seconds)
    if len(samples)<3:return {'estimated_seconds':None,'estimate_message':'相同设备、工作流与规格的有效历史不足3条，暂无估算'}
    return {'estimated_seconds':round(statistics.median(samples)),'estimate_samples':len(samples),'estimate_message':f'按{len(samples)}条相同设备与近似规格历史估算，非完成承诺'}
