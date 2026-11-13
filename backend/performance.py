"""Audio-first performance timeline and three explicit approvals per shot."""
import copy,json,time
from functools import lru_cache
from . import store,speech_audio as speech,speech_mix,timing,timing_speech,ai

VISUAL_FIELDS=('composition','space','start_state','end_state','soundscape')
def find(p,sid):
    s=next((s for s in p['shots'] if s['id']==sid),None)
    if not s:raise ValueError('分镜不存在')
    return s
def generated(s):return s.get('h3_audio_mode')!='locked'
def rows(p,s):
    result=speech_mix.plan(p,s)['lines']
    if generated(s):
        for row in result:
            source=next((v for v in timing_speech.raw_catalogue(p,s) if v['id']==row['speech_id']),None)
            row['duration']=float(s.get('speech_estimates',{}).get(row['speech_id'],source['minimum_seconds'] if source else row['duration']))
            if not 0<row['duration']<=600 or not __import__('math').isfinite(row['duration']):raise ValueError('对白预计时长需为0至600秒内的有效正数')
            row['end']=row['start']+row['duration'];row['timing_basis']='estimated';row['measured']=False
    return result
def sound_hash(p,s):
    return speech.digest([({'id':r['speech_id'],'text':r['text'],'speaker':r['speaker'],'duration':r['duration']} if generated(s) else {'id':r['speech_id'],'key':r['cache_key'],'media':r['media'],'duration':r['duration']}) for r in rows(p,s)])
def source_hash(p,s):return speech.digest({'mode':'generated' if generated(s) else 'locked','sound':sound_hash(p,s),'description':s.get('description'),'lines':timing_speech.raw_catalogue(p,s)})
def timeline_hash(plan):return speech.digest({k:plan.get(k) for k in ('duration','speech','actions','camera')})
def visual_hash(plan):return speech.digest({'timeline':timeline_hash(plan),'visual':plan.get('visual')})
def compiled_hash(s):return speech.digest({k:s.get(k) for k in ('duration','actions','prompt','speech_mix')})
def status(p,s):
    plan=s.get('performance',{});final=plan.get('finals',{})
    sound=final.get('sound',{}).get('hash')==sound_hash(p,s) and (generated(s) or all(r['measured'] for r in rows(p,s)))
    current=bool(plan.get('source_hash')==source_hash(p,s))
    timed=sound and current and bool(plan.get('actions')) and final.get('timing',{}).get('hash')==timeline_hash(plan) and plan.get('compiled_hash')==compiled_hash(s)
    visual=timed and final.get('visual',{}).get('hash')==visual_hash(plan)
    return {'sound':sound,'timing':timed,'visual':visual,'current':current,'audio_current':(generated(s) or speech.current(p,s)) if timed else False,'timing_basis':'estimated' if generated(s) else 'measured','generated':generated(s)}

def creative_prompt(s):
    """Keep the creative outline independent from later timed materialization."""
    from . import authoring_prompts
    sections=s.get('seedance_sections')
    if isinstance(sections,dict):
        text=authoring_prompts.render(sections)
        if text.strip():return text
    return s.get('creative_storyboard_prompt') or s.get('performance_original_prediction',{}).get('prompt') or (s.get('prompt','') if not s.get('performance',{}).get('compiled_hash') else '')


def finalized_prompt(p,s,state=None):
    """The same approved, human-readable source feeds the group review and H3."""
    state=status(p,s) if state is None else state
    if not state['visual'] or not state['audio_current']:return None
    plan=s['performance'];catalog={r['speech_id']:r for r in rows(p,s)}
    lines=[f"正式镜头时长：{plan['duration']:.2f} 秒",'1 · 声音定稿 · 已确认']
    for r in plan['speech']:
        source=catalog[r['speech_id']]
        lines.append(f"{r['start']:.2f}–{r['start']+source['duration']:.2f} 秒｜{source['speaker']}｜{source['kind']}｜{source['text']}｜音量 {r['gain']*100:g}%")
    lines.append('声音仅作音色参考，H3重新生成对白并同步口型；保留台词内容。' if s.get('h3_audio_mode')!='locked' else '完整混音保留开头、句间与结尾静音；不变速、不截断。')
    lines.append('2 · 时序定稿 · 已确认（以下轨道可并行）')
    for kind,title in (('actions','动作'),('camera','摄影')):
        for r in plan[kind]:lines.append(f"{r['start']:.2f}–{r['end']:.2f} 秒｜{title}｜{r.get('actor','')}｜{r['text']}")
    lines.append('3 · 画面定稿 · 已确认')
    for key,title in (('composition','构图与景别'),('space','角色位置、朝向与视线'),('start_state','镜头开始状态'),('end_state','镜头结束状态'),('soundscape','环境声与动作音效')):
        lines.append(title+'：'+plan['visual'].get(key,''))
    return '\n'.join(lines)


def number(v,label):
    try:return timing.number(v)
    except (ValueError,TypeError,KeyError):raise ValueError(label+'需要有效秒数')
def validate(p,s,value):
    if not isinstance(value,dict):raise ValueError('编排需为对象')
    duration=number(value.get('duration'),'镜头时长')
    if not 0<duration<=600:raise ValueError('镜头时长需在 0–600 秒之间')
    expected={r['speech_id']:r for r in rows(p,s)};lines=value.get('speech')
    if not isinstance(lines,list) or len(lines)!=len(expected):raise ValueError('对白必须完整保留，每句出现一次')
    seen=set();clean=[]
    for r in lines:
        identity=r.get('speech_id')
        if identity not in expected or identity in seen:raise ValueError('对白编号缺失或重复')
        seen.add(identity);start=number(r.get('start'),'对白开始');gain=number(r.get('gain',1),'音量')
        if start<0 or start+expected[identity]['duration']>duration+1e-6:raise ValueError('对白超出镜头，请延长镜头，不截断或变速')
        if not 0<=gain<=2:raise ValueError('音量需为 0–200%')
        clean.append({'speech_id':identity,'start':round(start,6),'gain':gain,'locked':bool(r.get('locked'))})
    by_id={r['speech_id']:{**r,'duration':expected[r['speech_id']]['duration']} for r in clean}
    result={'duration':duration,'speech':clean,'visual':{},'rationale':str(value.get('rationale',''))[:5000]}
    for kind in ('actions','camera'):
        items=value.get(kind)
        if not isinstance(items,list) or not items or len(items)>80:raise ValueError('请保留至少一条动作与镜头时间条，最多各80条')
        identities=set();out=[]
        for item in items:
            identity=item.get('id');text=str(item.get('text','')).strip()
            if not isinstance(identity,str) or not identity or identity in identities or not text:raise ValueError('时间条需有唯一编号和具体内容')
            identities.add(identity)
            start=number(item.get('start'),'时间条开始');end=number(item.get('end'),'时间条结束')
            if start<0 or end<=start or end>duration+1e-6:raise ValueError('动作或镜头时间条超出镜头范围')
            relation=item.get('relation','free');link=item.get('speech_id') or ''
            if relation not in ('free','before','with','after'):raise ValueError('不支持的对白关联方式')
            if relation!='free' and link not in by_id:raise ValueError('关联对白不存在')
            if relation!='free':
                line=by_id[link]
                if relation=='before' and end>line['start']+1e-6:raise ValueError('说话前完成的动作超出了开口时间')
                if relation=='with' and not (start<line['start']+line['duration'] and end>line['start']):raise ValueError('伴随对白的动作需要与对白时间相交')
                if relation=='after' and start<line['start']+line['duration']-1e-6:raise ValueError(f'动作“{text[:50]}”设为说话后发生，但开始于{start:.2f}秒，关联对白到{line["start"]+line["duration"]:.2f}秒才结束。请将动作移到对白结束后，或改为“伴随对白／独立发生”。')
            row={'id':identity,'text':text[:5000],'actor':str(item.get('actor','镜头' if kind=='camera' else '场景'))[:120],'start':round(start,6),'end':round(end,6),'relation':relation,'speech_id':link,'locked':bool(item.get('locked'))}
            if kind=='actions':
                minimum=number(item.get('min_seconds',end-start),'动作自然最短时长');maximum=number(item.get('max_seconds',end-start),'动作自然最长时长')
                if minimum<=0 or maximum<minimum or not minimum-1e-6<=end-start<=maximum+1e-6:raise ValueError('动作长度超出自然时长范围，请调整或重新分析')
                rationale=str(item.get('rationale','')).strip()
                if not rationale:raise ValueError('动作需要自然时长依据')
                row.update(min_seconds=minimum,max_seconds=maximum,rationale=rationale[:3000])
            out.append(row)
        result[kind]=out
    visual=value.get('visual',{})
    for key in VISUAL_FIELDS:
        text=visual.get(key,'')
        if not isinstance(text,str) or len(text)>6000:raise ValueError('画面设定需为不超过6000字的文本')
        result['visual'][key]=text.strip()
    return result

SYSTEM='''你是短片的表演与时序导演。只调用一次，请返回一个完整JSON对象，不要Markdown。
对白音频已生成，speech_id、原句、角色、音频时长为不可改写的事实。gain是用户设定的音量，必须原值保留；每句只安排一次，只返回speech_id/start/gain，不重写台词、不改变语速、不截断。
不要被旧镜头预测时长限制；依据真实音频与自然动作决定duration。不同角色对白可重叠表现抢话；重叠不等于截断。角色听别人说话时也要有反应。
动作和镜头条允许并行，但不添加分镜中不存在的剧情。不把身体动作等分塞进对白间隙。每个动作给出合理min_seconds/max_seconds/rationale；不能把模型估计当作物理实测。
镜头条描述景别、机位、拍摄方向、构图和运镜，保持一个分镜内部的摄影连续性，不凭空剪切。每条说明actor。关联对白使用relation=free/before/with/after及speech_id；free时speech_id为空。
输出格式：{"duration":秒数,"speech":[{"speech_id":"原编号","start":秒数,"gain":1}],"actions":[{"id":"a1","actor":"实际角色","text":"可见动作","start":0,"end":1.2,"min_seconds":1,"max_seconds":1.5,"rationale":"自然时长依据","relation":"before","speech_id":"原编号"}],"camera":[{"id":"c1","actor":"镜头","text":"摄影与运镜","start":0,"end":总时长,"relation":"free","speech_id":""}],"visual":{"composition":"构图与景别","space":"角色位置、朝向与视线","start_state":"开场状态","end_state":"收尾状态","soundscape":"环境声、动作声，不重复对白，不擅加BGM"},"rationale":"整体安排依据"}。
输出紧凑JSON，禁止逐句分析或复述输入。只保留必要的动作节拍，通常3–8条动作、1–3条镜头；同时发生的动作合并描述，不遗漏剧情。每条text不超过120字、rationale不超过60字；visual各字段不超过160字、整体rationale不超过120字。
所有编排时间（duration、start、end、min_seconds、max_seconds）以0.05秒为步长，保留两位小数；真实音频duration是实测事实，不进行取整。镜头duration向上留足完整对白及动作后的静音。
所有时间有限、非负且不超出duration；动作时长落在其自然范围内。给出完整动作与镜头条，不漏剧情动作。'''

def planning_assets(project,shot,answer):
    from . import frame_reference_sets
    ids=answer.get('asset_ids',shot.get('asset_ids',[]))
    known={a['id'] for a in project.get('assets',[])}
    if not isinstance(ids,list) or any(not isinstance(identity,str) or identity not in known for identity in ids):raise ValueError('AI编排的asset_ids必须使用资产目录中的有效编号')
    # All visible dialogue speakers remain bound even if the model omits one.
    return list(dict.fromkeys(ids+frame_reference_sets.character_ids(project,shot)))

def execute(task):
    from . import jobs
    p=task['snapshot'];s=find(p,task['target']);before=source_hash(p,s)
    if not status(p,s)['sound']:raise ValueError('先完成声音定稿，再调用AI编排')
    payload={'shot':{'id':s['id'],'description':s.get('description'),'old_duration_prediction':s['duration'],'native':s.get('native',{}),'old_actions':s.get('actions',[])},'speech':[{k:r[k] for k in ('speech_id','speaker','kind','text','duration','gain')} for r in rows(p,s)],'story_context':{'logline':p.get('documents',{}).get('seedance_overview',{}).get('logline',''),'constraints':p.get('creative_constraints',[])}}
    bound=set(s.get('asset_ids',[]))
    payload['asset_catalogue']=[{k:a.get(k) for k in ('id','name','kind','description','variant')} for a in p.get('assets',[]) if a['id'] in bound]
    payload['timing_basis']='estimated' if generated(s) else 'measured'
    payload['currently_bound_asset_ids']=s.get('asset_ids',[])
    jobs.progress(task,'单次 AI 正在依据实测对白编排动作和镜头，并确定本镜资产，不改写台词')
    with ai.asset_call_policy('performance_timeline',limit=1,max_tokens=32768,timeout=300,preserve_context=True):answer=ai.ask((SYSTEM.replace('对白音频已生成','本次只有对白文字与预计时长，没有固定音轨').replace('真实音频','预计对白').replace('音频时长为不可改写的事实','台词原文为不可改写的事实，duration是预计时长') if generated(s) else SYSTEM)+'\n同时输出asset_ids数组，从asset_catalogue按准确编号选择本镜实际可见的角色、场景和道具，包含对白说话角色与动作接触物；只选剧情需要的资产，不把整个目录全选，不新增或重命名资产。保留状态变体的准确编号。',json.dumps(payload,ensure_ascii=False))
    jobs.check_cancelled(task)
    proposals=store.DATA/'performance-proposals';proposals.mkdir(exist_ok=True)
    (proposals/(task['id']+'.json')).write_text(json.dumps({'source_hash':before,'answer':answer},ensure_ascii=False,indent=2),encoding='utf-8')
    answer=copy.deepcopy(answer)
    volumes={r['speech_id']:r['gain'] for r in rows(p,s)}
    if isinstance(answer,dict) and isinstance(answer.get('speech'),list):
        for row in answer['speech']:
            if isinstance(row,dict) and row.get('speech_id') in volumes:row['gain']=volumes[row['speech_id']]
    candidate=validate(p,s,answer)
    selected_assets=planning_assets(p,s,answer)
    candidate['asset_ids']=selected_assets
    def apply(current):
        live=find(current,s['id'])
        if source_hash(current,live)!=before:raise store.Conflict('编排期间对白或分镜已修改，未覆盖当前版本')
        finals={'sound':copy.deepcopy(live.get('performance',{}).get('finals',{}).get('sound',{}))}
        old=copy.deepcopy(live.get('performance',{}))
        live.setdefault('performance_versions',[]).append(old)
        live['performance']={**candidate,'source_hash':before,'finals':finals,'created':time.time(),'ai_calls':1}
        live.setdefault('asset_binding_history',[]).append({'asset_ids':copy.deepcopy(live.get('asset_ids',[])),'created':time.time(),'reason':'AI时间编排确定可见资产'})
        live['asset_ids']=selected_assets
        live['asset_binding_source']='performance_timeline'
    jobs.mutate_task(task,apply)
    task['completion_message']='对白、动作与镜头编排已进入时间轴；可拖动试听，确认后替换原分镜的预测时间'

def compile_actions(plan):
    points=sorted({0.0,plan['duration'],*[r[k] for kind in ('actions','camera') for r in plan[kind] for k in ('start','end')]})
    result=[]
    for left,right in zip(points,points[1:]):
        if right-left<1e-6:continue
        active=[r for r in plan['actions'] if r['start']<right-1e-7 and r['end']>left+1e-7]
        camera=[r for r in plan['camera'] if r['start']<right-1e-7 and r['end']>left+1e-7]
        text='；'.join(r['actor']+'：'+r['text']+('（延续原动作，不重新起动）' if left>r['start']+1e-7 else '') for r in active) or '人物保持当前姿态与自然呼吸，等待后续动作'
        if camera:text+='；摄影：'+'；'.join(r['text'] for r in camera)
        duration=round(right-left,6)
        result.append({'id':'performance_'+str(len(result)+1),'start':left,'end':right,'description':text,'minimum_seconds':duration,'maximum_seconds':duration,'natural_seconds':duration,'rationale':'已确认并行编排的切片；原动作自然时长依据：'+'；'.join(r.get('rationale','') for r in active),'dialogue':'','voiceover':'','speech_ids':[]})
    return result


def derive(p,s):
    """Reuse accepted shot actions without another model call; user must review."""
    catalogue=rows(p,s);cursor=0;speech_rows=[]
    for row in catalogue:
        speech_rows.append({'speech_id':row['speech_id'],'start':cursor,'gain':row.get('gain',1)})
        cursor+=row['duration']
    duration=max(float(s['duration']),cursor);actions=[];at=0
    for index,row in enumerate(s.get('actions',[])):
        start=float(row.get('start',at));end=float(row.get('end',start+float(row.get('natural_seconds',1))))
        if end<=start:continue
        actions.append({'id':row.get('id') or 'a'+str(index),'actor':'角色','text':row['description'],'start':start,'end':end,'relation':'free','min_seconds':end-start,'max_seconds':end-start,'rationale':row.get('rationale') or '沿用已采用分镜的预计动作时间，待人工复核'})
        at=end
    if not actions:actions=[{'id':'a1','actor':'角色','text':s['description'],'start':0,'end':duration,'relation':'free','min_seconds':duration,'max_seconds':duration,'rationale':'沿用分镜预计时长，待人工复核'}]
    duration=max(duration,max(a['end'] for a in actions));cards=s.get('frame_cards',{})
    text=lambda key,fallback:str(cards.get(key,{}).get('subject') or fallback)
    visual={'composition':cards.get('first',{}).get('shot') or s.get('description',''),
            'space':cards.get('first',{}).get('setting') or '沿用本镜已确认空间与人物位置，定稿前复核',
            'start_state':text('first',s['description']),'end_state':text('last',s['description']),
            'soundscape':'沿用已确认环境声，不额外添加音乐'}
    value=validate(p,s,{'duration':duration,'speech':speech_rows,'actions':actions,
            'camera':[{'id':'c1','text':cards.get('first',{}).get('shot') or '沿用本镜分镜摄影设置，定稿前复核','start':0,'end':duration,'relation':'free'}],
            'visual':visual,'rationale':'本地复用既有分镜动作，顺序估算对白；需人工核对并行关系'})
    return {**value,'source_hash':source_hash(p,s),'finals':copy.deepcopy(s.get('performance',{}).get('finals',{})),'created':time.time(),'ai_calls':0,'timing_basis':'estimated' if generated(s) else 'measured'}

def materialize(p,s):
    s.setdefault('creative_storyboard_prompt',creative_prompt(s))
    plan=s['performance'];original=copy.deepcopy(timing_speech.raw_catalogue(p,s))
    # Legacy action-derived sources must survive replacement of the predicted action slots.
    if 'sound_script' not in s:s['sound_script']={'lines':original}
    if 'performance_original_prediction' not in s:s['performance_original_prediction']={k:copy.deepcopy(s.get(k)) for k in ('duration','actions','prompt','natural_status')}
    actions=compile_actions(plan);base='\n'.join(plan['visual'].get(k,'') for k in VISUAL_FIELDS)
    draft={**s,'duration':plan['duration'],'actions':actions,'prompt':base,'natural_status':'human_reviewed'}
    draft['prompt']=timing.render(draft)
    timing.apply_review(p,s,draft)
    from . import script_source
    script_source.set_derived_duration(p,round(sum(timing.number(row['duration']) for row in p['shots']),6))
    s.setdefault('h3_audio_mode','generated')
    s['speech_mix']={'basis':speech_mix.basis(p,s),'lines':[{k:r[k] for k in ('speech_id','start','gain')} for r in plan['speech']]}
    if s.get('native'):
        s['native']['台词']=[r['text'] for r in original if r['kind']=='dialogue']
        s['native']['旁白']='\n'.join(r['text'] for r in original if r['kind']=='voiceover')
    if not generated(s):speech_mix.render(p,s)
    plan['compiled_hash']=compiled_hash(s)
    # Legacy source IDs can change only during initial canonicalization; refresh the plan's source digest.
    plan['source_hash']=source_hash(p,s)
    plan['finals']['sound']['hash']=sound_hash(p,s)

def gate(p,s):
    if not s.get('performance'):
        if p.get('performance_workflow_enabled'):raise ValueError('本项目已采用对白优先流程，请先完成本镜三步定稿')
        return
    state=status(p,s)
    if not state['visual'] or not state['audio_current']:raise ValueError('本镜已启用对白优先流程，请完成声音、时序、画面三步定稿；修改后需重新确认')

def export(p,s):
    plan=s.get('performance',{});state=status(p,s)
    return {'shot_id':s['id'],'creative_storyboard_prompt':creative_prompt(s),'status':state,'step1_sound':{'lines':rows(p,s),'approval':plan.get('finals',{}).get('sound')},'step2_timing':{k:plan.get(k) for k in ('duration','speech','actions','camera','rationale')},'step3_visual':plan.get('visual',{}),'approvals':plan.get('finals',{}),'original_prediction':s.get('performance_original_prediction'),'final_audio':s.get('speech_track'),'reference_inputs':{'asset_ids':s.get('asset_ids',[]),'first_frame':s.get('first_frame'),'keyframe':s.get('adopted_keyframe'),'tailframe':s.get('adopted_tailframe')}}

def install(app):
    def current(pid,sid):
        p=store.get_project(pid);return p,find(p,sid)
    @app.get('/api/projects/{pid}/shots/{sid}/performance')
    def view(pid:str,sid:str):
        p,s=current(pid,sid);state=status(p,s);return {'plan':s.get('performance'),'creative_prompt':creative_prompt(s),'finalized_prompt':finalized_prompt(p,s,state),'status':state,'lines':rows(p,s),'generated':generated(s),'audio_media':s.get('speech_track',{}).get('media') if state['audio_current'] else None,'source_hash':source_hash(p,s),'plan_hash':speech.digest(s.get('performance')),'planning_task':next(({'id':task['id'],'status':task['status']} for task in store.task_list() if task['project_id']==pid and task.get('target')==sid and task['kind']=='performance_plan' and task['status'] in ('queued','running','cancelling')),None),'original_duration':s.get('performance_original_prediction',{}).get('duration',s['duration'])}
    @app.post('/api/projects/{pid}/shots/{sid}/performance/{action}')
    def change(pid:str,sid:str,action:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            p,s=current(pid,sid)
            if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请加载最新版本')
            if body.get('source_hash')!=source_hash(p,s):raise store.Conflict('对白或分镜已变化，请加载最新配音')
            if body.get('plan_hash')!=speech.digest(s.get('performance')):raise store.Conflict('编排已在其他页面更新，请加载最新版本后重试')
            if action=='preview':
                from fastapi.responses import Response
                checked=validate(p,s,body.get('plan'))
                return Response(speech_mix.preview_wave(p,s,checked),media_type='audio/wav',headers={'Cache-Control':'no-store'})
            if action=='derive':
                if not status(p,s)['sound']:raise ValueError('请先确认对白')
                s.setdefault('performance_versions',[]).append(copy.deepcopy(s.get('performance',{})))
                s['performance']=derive(p,s)
                return store.save_project(p,p['revision'])
            if action=='plan':
                if not status(p,s)['sound']:raise ValueError('请先声音定稿')
                prior=next((t for t in store.task_list() if t['project_id']==pid and t.get('target')==sid and t['kind']=='performance_plan' and t['status'] in ('queued','running','cancelling')),None)
                task=prior or jobs.enqueue('performance_plan',p,sid,{'single_shot':True})
                return {'task_id':task['id']}
            if action not in ('sound','save','timing','visual','audio','finalize'):raise ValueError('不支持的定稿步骤')
            if any(t['project_id']==pid and t.get('target')==sid and t['kind']=='performance_plan' and t['status'] in ('queued','running','cancelling') for t in store.task_list()):raise ValueError('AI编排正在执行，请完成后编辑')
            plan=s.setdefault('performance',{'finals':{},'source_hash':source_hash(p,s)})
            if action=='sound':
                p['performance_workflow_enabled']=True
                if not generated(s) and any(not r['measured'] for r in rows(p,s)):raise ValueError('请先生成本镜全部对白与旁白')
                if plan.get('source_hash')!=source_hash(p,s):
                    s.setdefault('performance_versions',[]).append(copy.deepcopy(plan))
                if isinstance(body.get('previous_draft'),dict):
                    s.setdefault('performance_versions',[]).append({'draft':copy.deepcopy(body['previous_draft']),'reason':'来源变化前的未保存草稿','created':time.time()})
                plan['source_hash']=source_hash(p,s);plan.setdefault('finals',{})['sound']={'hash':sound_hash(p,s),'at':time.time()}
                plan['finals'].pop('timing',None);plan['finals'].pop('visual',None)
            elif action=='finalize':
                if not status(p,s)['sound'] or plan.get('source_hash')!=source_hash(p,s):raise ValueError('声音或分镜已变化，请先重新确认声音和编排')
                checked=validate(p,s,body.get('plan') or plan)
                if any(not checked['visual'].get(k) for k in VISUAL_FIELDS):raise ValueError('请补齐构图、空间、首尾状态及环境声音')
                s.setdefault('performance_versions',[]).append(copy.deepcopy(plan))
                plan.update(checked)
                materialize(p,s)
                plan['finals']['timing']={'hash':timeline_hash(plan),'at':time.time()}
                plan['finals']['visual']={'hash':visual_hash(plan),'at':time.time()}
            elif action=='audio':
                if not status(p,s)['sound'] or plan.get('source_hash')!=source_hash(p,s):raise ValueError('声音或分镜已变化，请先重新确认声音和编排')
                checked=validate(p,s,body.get('plan') or plan)
                s.setdefault('performance_versions',[]).append(copy.deepcopy(plan))
                if visual_hash(checked)!=visual_hash(plan):plan['finals'].pop('visual',None)
                plan.update(checked)
                materialize(p,s)
                plan['finals']['timing']={'hash':timeline_hash(plan),'at':time.time()}
            elif action=='save':
                if not status(p,s)['sound']:raise ValueError('声音已变化，请重新定稿后编排')
                checked=validate(p,s,body.get('plan'))
                if plan.get('source_hash')!=source_hash(p,s):raise ValueError('编排来源已变化，请重新调用AI编排')
                without_gains=lambda value:{k:([{a:b for a,b in row.items() if a!='gain'} for row in value.get(k,[])] if k=='speech' else value.get(k)) for k in ('duration','speech','actions','camera','visual','rationale')}
                volume_only=without_gains(checked)==without_gains(plan)
                if volume_only and not generated(s):
                    speech_mix.save_gains(p,s,{'basis':speech_mix.basis(p,s),'gains':{row['speech_id']:row['gain'] for row in checked['speech']}})
                if timeline_hash(checked)!=timeline_hash(plan):plan['finals'].pop('timing',None)
                if visual_hash(checked)!=visual_hash(plan):plan['finals'].pop('visual',None)
                s.setdefault('performance_versions',[]).append(copy.deepcopy(plan));plan.update(checked)
            else:
                if not status(p,s)['sound'] or plan.get('source_hash')!=source_hash(p,s):raise ValueError('声音或分镜已变化，请重新编排')
                checked=validate(p,s,plan);plan.update(checked)
                if action=='visual':
                    if not status(p,s)['timing']:raise ValueError('请先完成时序定稿')
                    if any(not plan['visual'].get(k) for k in VISUAL_FIELDS):raise ValueError('请补齐构图、空间、首尾状态及环境声音')
                materialize(p,s)
                plan['finals']['timing']={'hash':timeline_hash(plan),'at':time.time()}
                if action=='visual':plan['finals']['visual']={'hash':visual_hash(plan),'at':time.time()}
                else:plan['finals'].pop('visual',None)
            return store.save_project(p,p['revision'])
    @app.get('/api/projects/{pid}/shots/{sid}/performance-export')
    def download(pid:str,sid:str):
        from fastapi.responses import Response
        p,s=current(pid,sid)
        return Response(json.dumps(export(p,s),ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="shot-three-stage.json"'})
    @app.get('/api/performance/waveform/{name}')
    def waveform(name:str):
        import numpy as np,soundfile as sf
        path=store.media_path(name)
        if path.suffix.lower() not in ('.wav','.flac','.mp3'):raise ValueError('仅支持音频波形')
        stat=path.stat()
        return waveform_peaks(str(path),stat.st_mtime_ns,stat.st_size)

@lru_cache(maxsize=256)
def waveform_peaks(path,modified,size):
    import numpy as np,soundfile as sf
    wave,rate=sf.read(path,dtype='float32',always_2d=True)
    mono=wave.mean(axis=1);parts=np.array_split(mono,160)
    return {'peaks':[float(np.max(np.abs(v))) if len(v) else 0 for v in parts],'duration':len(mono)/rate}
