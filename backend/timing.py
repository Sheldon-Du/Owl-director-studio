"""Timing is an execution gate, never a proportional speed-up."""
from . import script_source
import copy
import hashlib
import json
import math
import re
import uuid


def number(value):
    if isinstance(value,bool):
        raise ValueError('时长必须为数值')
    n=float(value)
    if not math.isfinite(n):
        raise ValueError('时长必须为有限数值')
    return n


def from_natural(actions):
    """Own the clock in code; never scale the model's natural durations."""
    if not isinstance(actions, list) or not actions or any(not isinstance(a, dict) for a in actions):
        raise ValueError('需要非空动作列表及每段自然时长')
    result = copy.deepcopy(actions); cursor = 0.0
    for index, action in enumerate(result):
        try:
            duration = number(action['natural_seconds'])
            if duration <= 0: raise ValueError('自然时长必须大于零')
            action.update(start=cursor, end=round(cursor + duration, 6))
            cursor = action['end']
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError(f'动作{index+1}自然时长无效：{error}') from error
    return result, cursor


def shot_signature(shot):
    fields={k:shot.get(k) for k in ('id','description','duration','prompt','actions')}
    return hashlib.sha256(json.dumps(fields,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def audit_signature(project,shot):
    from . import speech_audio,timing_speech
    outline=next((o for o in project.get('storyboard_generation',{}).get('outlines',[]) if o.get('id')==shot.get('generation_outline_id')),None)
    data={'shot':shot_signature(shot),'script':script_source.text(project,False),
          'source_excerpt':outline.get('source_excerpt') if outline else None,'audio':shot.get('native',{}).get('音频描述'),
          'voice_roles':[speech_audio.voice(project,s) for s in timing_speech.raw_catalogue(project,shot)],'speech_audio':shot.get('speech_audio',{}),'speech_mix':shot.get('speech_mix')}
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def change_summary(original, revised, maximum=30):
    before=number(original['duration']);after=number(revised['duration'])
    actions=revised['actions']
    natural=lambda a:number(a.get('natural_seconds',a.get('minimum_seconds',number(a['end'])-number(a['start']))))
    return {'shot_id':original.get('id'),'before_seconds':before,'recommended_seconds':after,
            'delta_seconds':round(after-before,6),
            'minimum_seconds':round(sum(number(a.get('minimum_seconds',natural(a))) for a in actions),6),
            'maximum_seconds':round(sum(number(a.get('maximum_seconds') or natural(a)) for a in actions),6),
            'task_limit_seconds':maximum,'estimated_task_count':math.ceil(round(after,8)/maximum),
            'reasons':[{'description':a['description'],'natural_seconds':natural(a),'rationale':a['rationale']} for a in actions]}


def suggest(project, original, revised):
    from . import storyboard_generation as sg
    maximum=number(project.get('h3_settings',{}).get('max_step_seconds',30))
    if maximum not in (15,30):raise ValueError('H3 提示词任务上限请选择15或30秒')
    checked=validate(revised)
    if not checked['ok']:raise ValueError('时长建议未通过自然动作校验：'+'；'.join(checked['errors']))
    suggestion={**change_summary(original,revised,maximum),'id':uuid.uuid4().hex,'status':'pending',
                'shot_source_hash':shot_signature(original),'project_source_hash':sg.fingerprint(project),
                'draft':{k:copy.deepcopy(revised[k]) for k in ('duration','actions','prompt','natural_status')}}
    return {**original,'natural_status':'unverified','timing_suggestion':suggestion}


def apply_review(project, shot, draft):
    """Apply reviewed duration as derived data, preserving the confirmed script."""
    from . import storyboard_generation as sg, director, script_workflows, script_source
    current_state=sg.valid_state(project);old_source=sg.fingerprint(project)
    checked=validate(draft)
    if not checked['ok']:raise ValueError('时长建议未通过校验：'+'；'.join(checked['errors']))
    from . import shot_continuity
    previous_digest=shot_continuity.digest(shot)
    shot.update({k:copy.deepcopy(draft[k]) for k in ('duration','actions','prompt','natural_status')})
    shot.pop('timing_suggestion',None)
    if shot.get('native'):
        shot['native'].update(时长=shot['duration'],AIGC提示词=shot['prompt'],AIGC适配提示词=shot['prompt'])
        shot['native']['动作预案']=copy.deepcopy(shot['actions'])
        shot['native']['台词']=[a['dialogue'] for a in shot['actions'] if a.get('dialogue')]
        shot['native']['旁白']='\n'.join(a['voiceover'] for a in shot['actions'] if a.get('voiceover'))
        shot['native']['剧本原句编号']=[i for a in shot['actions'] for i in a.get('speech_source_ids',[])]
    revised_digest=shot_continuity.digest(shot)
    if shot.get('continuity_source_hash')==previous_digest:shot['continuity_source_hash']=revised_digest
    review=shot.get('continuity_review',{})
    if review.get('shot_hash')==previous_digest:review['shot_hash']=revised_digest
    for following in project['shots']:
        following_review=following.get('continuity_review',{})
        if following_review.get('previous_hash')==previous_digest:following_review['previous_hash']=revised_digest
    project['confirmed']=False
    project['documents'].pop('h3',None);project['documents'].pop('review',None)
    cursor=0.0
    for row in project['shots']:
        row['start_s']=cursor;cursor=round(cursor+number(row['duration']),6);row['end_s']=cursor
    if project.get('timing_revision'):
        project['timing_revision'].update(status='stale',message='本镜已采用建议时长；请点击时间修正核对全片时间标签')
    if project.get('native_storyboard_current'):
        script_source.set_derived_duration(project,round(sum(number(s['duration']) for s in project['shots']),6))
        if project['documents'].get('video_spec'):
            project['documents']['video_spec']=script_workflows.spec(project)
            project['documents']['video_spec_markdown']=script_workflows.markdown(project)
        if current_state:
            current_state['source_hash']=sg.fingerprint(project)
            for row in project['shots']:row['generation_source_hash']=current_state['source_hash']
        new_source=sg.fingerprint(project)
        for row in project['shots']:
            pending=row.get('timing_suggestion',{})
            if pending.get('status')=='pending' and pending.get('project_source_hash')==old_source:
                pending['project_source_hash']=new_source
        director.validate_project_shots(project)
    if current_state and current_state.get('preparation'):
        project['documents']['storyboard_native']=sg.assemble(current_state['preparation'],[sg.current_row(s,i+1) for i,s in enumerate(project['shots'])])


def adopt(project, shot, identity):
    from . import storyboard_generation as sg
    proposal=shot.get('timing_suggestion',{})
    if proposal.get('status')!='pending' or proposal.get('id')!=identity:raise ValueError('当前没有这条待采用的时长建议，请重新审查')
    if proposal.get('shot_source_hash')!=shot_signature(shot) or proposal.get('project_source_hash')!=sg.fingerprint(project):
        raise ValueError('镜头或生成依据已修改，旧时长建议已失效，请重新审查')
    draft={**shot,**proposal['draft']};draft.pop('timing_suggestion',None)
    apply_review(project,shot,draft)


def apply_automatic_pending(project_id):
    """Apply reviews once no storyboard producer is using the old prefix."""
    from . import store,jobs,storyboard_generation as sg
    with jobs.TASK_LOCK:
        if any(t['project_id']==project_id and t['kind'] in ('storyboard','storyboard_outline','storyboard_timing','schedule') and t['status'] in ('queued','running','cancelling') for t in store.task_list()):return
        p=store.get_project(project_id)
        pending=[s for s in p.get('shots',[]) if s.get('timing_suggestion',{}).get('auto_apply') and s['timing_suggestion'].get('status')=='pending']
        if not pending:return
        for shot in pending:
            proposal=shot['timing_suggestion']
            if proposal['shot_source_hash']!=shot_signature(shot) or proposal['project_source_hash']!=sg.fingerprint(p):
                proposal['status']='stale';shot['natural_status']='unverified';continue
            draft={**shot,**proposal['draft']};draft.pop('timing_suggestion',None)
            summary=change_summary(shot,draft,p.get('h3_settings',{}).get('max_step_seconds',30))
            apply_review(p,shot,draft);shot['timing_review_summary']=summary
            if proposal.get('tts_track'):
                from . import speech_audio
                speech_audio.track(p,shot)
        store.save_project(p,p['revision'])


def remove_estimates(text):
    # Keep dialogue and visible quoted text verbatim, including spoken numbers.
    text=re.sub(r'\n镜头总时长\d+(?:\.\d+)?秒，连续实时动作，不加速、不跳步、不重复。(?:\n[\s\S]*)?$', '',text)
    quoted=[]
    def protect(match):
        quoted.append(match.group());return f'\u0000Q{len(quoted)-1}\u0000'
    text=re.sub(r'「[^」]*」|“[^”]*”|"(?:\\.|[^"\\])*"',protect,text)
    text=re.sub(r'\d{1,2}:\d{2}(?:\.\d+)?\s*[–—\-~至]\s*\d{1,2}:\d{2}(?:\.\d+)?', '',text)
    text=re.sub(r'\d+(?:\.\d+)?\s*[–—\-~至]\s*\d+(?:\.\d+)?\s*(?:秒|s\b)\s*[:：]?', '',text)
    text=re.sub(r'(?:镜头总时长|镜头时长|总时长|时长|持续|共)\s*[:：]?\s*\d+(?:\.\d+)?\s*(?:秒|s\b)', '',text)
    text=re.sub(r'(?:镜头总时长|镜头时长|总时长|时长)\s*[:：]\s*\d+(?:\.\d+)?\s*(?=$|[|;；，。,])', '',text)
    for index,value in enumerate(quoted):text=text.replace(f'\u0000Q{index}\u0000',value)
    return text.strip()


def clock(project):
    """Set absolute labels only after every shot's natural actions are reviewed."""
    cursor=0;rows=[]
    for index,shot in enumerate(project['shots']):
        checked=validate(shot)
        if not checked['ok']:raise ValueError(f'第{index+1}镜时间尚未审定：'+'；'.join(checked['errors']))
        end=round(cursor+number(shot['duration']),6)
        rows.append({'shot_id':shot['id'],'index':index+1,'start':cursor,'end':end,'duration':number(shot['duration'])})
        cursor=end
    return {'rows':rows,'total_seconds':cursor}


def validate(shot):
    errors=[]
    warnings=[]
    if shot.get('timing_suggestion',{}).get('status')=='pending':
        errors.append('有待采用的时长建议，请先采用建议时长或调整动作后重新审查')
    try:
        duration=number(shot['duration'])
        if duration<=0:
            raise ValueError('镜头时长必须大于零')
    except (KeyError,ValueError,TypeError) as e:
        return {'ok':False,'errors':[str(e)],'warnings':[],'natural_status':'unverified'}
    actions=shot.get('actions',[])
    base=str(shot.get('prompt',''))
    if re.search(r'\d+(?:/\d+)?\s*(?:倍速|倍慢放)|\b(?:time.?lapse|slow.?motion)\b',base,re.I):
        errors.append('提示词含加速或慢放指令，与实时自然动作不一致，请改写或单独规划慢镜')
    if not actions:
        errors.append('请拆解动作时间段，禁止给未校验动作的提示词直接加秒数')
    last=0.0
    known=set()
    natural=bool(actions)
    for index,action in enumerate(actions):
        try:
            start=number(action['start']); end=number(action['end'])
            if abs(start-last)>0.02:
                errors.append(f'动作{index+1}必须从{last:g}秒开始，不能重叠或留空')
            if end<=start or start<0 or end>duration+0.02:
                errors.append(f'动作{index+1}起止时间超出镜头或顺序错误')
            if not str(action.get('description','')).strip():
                errors.append(f'动作{index+1}缺少可见动作描述')
            dependency=action.get('depends_on')
            dependencies=[dependency] if isinstance(dependency,str) else dependency or []
            if not isinstance(dependencies,list) or any(not isinstance(d,str) or d not in known for d in dependencies):
                errors.append(f'动作{index+1}依赖不存在或发生在后面的动作')
            identity=action.get('id',str(index+1))
            if not isinstance(identity,str) or not identity:errors.append(f'动作{index+1}编号需为非空字符串')
            elif identity in known:errors.append(f'动作{index+1}编号重复，无法确定先后依赖')
            else:known.add(identity)
            minimum=action.get('minimum_seconds')
            natural_seconds=action.get('natural_seconds',minimum)
            rationale=str(action.get('rationale','')).strip()
            if minimum is None or not rationale:
                natural=False
                errors.append(f'动作{index+1}需要自然发生时长及依据，不能仅均分镜头时间')
            elif number(minimum)<=0:
                errors.append(f'动作{index+1}自然时长必须大于零')
            elif end-start+0.02<number(minimum):
                errors.append(f'动作{index+1}需要至少{minimum}秒；请延长镜头或拆镜，不要加速')
            if natural_seconds is None or abs(end-start-number(natural_seconds))>0.02:
                errors.append(f'动作{index+1}时间段与审定的自然发生时间不一致，请明确分出停留/反应段')
            maximum=action.get('maximum_seconds')
            if maximum is not None and end-start-0.02>number(maximum):
                errors.append(f'动作{index+1}时间超过自然发生范围，请将剩余时间明确写成停留或反应段')
            distance=action.get('distance_m')
            speed=action.get('speed_m_s')
            if distance is not None:
                if speed is None or number(speed)<=0 or number(distance)<0:
                    errors.append(f'动作{index+1}需提供有效距离和速度')
                elif number(distance)/number(speed)>end-start+0.02:
                    errors.append(f'动作{index+1}位移无法在规定时间内自然完成')
            speech=' '.join(str(action.get(k) or '') for k in ('dialogue', 'voiceover'))
            if speech.strip():
                syllables=len(re.findall(r'[\u4e00-\u9fff]|[A-Za-z]+',speech))
                measured=action.get('measured_speech',[])
                actual_text=' '.join('；'.join(s['text'] for s in measured if s['kind']==kind) for kind in ('dialogue','voiceover')) if measured else ''
                if measured and actual_text==speech:
                    actual=sum(number(s['duration']) for s in measured)
                    if end-start+0.000001<actual:errors.append(f'动作{index+1}人声实测{actual:g}秒，需延长动作段，不压缩音频')
                elif end-start+0.000001<syllables/5:
                    errors.append(f'动作{index+1}对白过密，请延长或拆分：当前{end-start:g}秒，完整原句{syllables}个计时单位至少需{syllables/5:g}秒；延长natural_seconds并同步调整minimum_seconds/maximum_seconds，不改原句、不变速')
            last=end
        except (KeyError,TypeError,ValueError,ZeroDivisionError) as e:
            errors.append(f'动作{index+1}格式错误：{e}')
    if actions and abs(last-duration)>0.02:
        errors.append(f'动作结束于{last:g}秒，应覆盖完整{duration:g}秒；留白也需明确描述')
    if shot.get('natural_status') not in ('ai_reviewed','human_reviewed'):
        errors.append('动作自然时长尚未审定，请通过 AI 时序审查或逐项人工确认')
    warnings.append('提示词时间是生产约束，生成结果仍需逐段预览验收。')
    return {'ok':not errors,'errors':errors,'warnings':warnings,'natural_status':shot.get('natural_status','unverified') if natural else 'unverified'}


def render(shot):
    checked=validate(shot)
    if not checked['ok']:
        raise ValueError('；'.join(checked['errors']))
    if shot.get('native',{}).get('标准化提示词版本'):
        from . import standardized_storyboard
        return standardized_storyboard.render(shot['native'],shot['actions'])
    segments=[f"{number(a['start']):g}–{number(a['end']):g}秒：{a['description']}"+(f"；对白：{a['dialogue']}" if a.get('dialogue') else '')+(f"；画外音：{a['voiceover']}" if a.get('voiceover') else '') for a in shot['actions']]
    duration=number(shot['duration'])
    # The editable native duration label must follow the approved timeline.
    base=re.sub(r'(?:镜头总时长|镜头时长|时长)\s*[:：]\s*\d+(?:\.\d+)?\s*(?:s\b|秒)',f'时长:{duration:g}秒',shot.get('prompt',''))
    return '\n'.join([base,f"镜头总时长{duration:g}秒，连续实时动作，不加速、不跳步、不重复。",*segments])
