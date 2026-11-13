"""Keep original spoken lines, render aligned role stems and a shared final mix."""
import copy,time
from . import speech_audio as speech,store,timing

RATE=24000
MAX_SECONDS=600

def sources(project,shot):
    from .timing_speech import raw_catalogue
    return raw_catalogue(project,shot)

def basis(project,shot):
    return speech.digest([{'id':s['id'],'key':speech.key(s,speech.voice(project,s))} for s in sources(project,shot)])

def source_hash(project,shot):
    return speech.digest({'source':speech.signature(project,shot),'mix':shot.get('speech_mix'),
                         'audio':[speech.measurement(project,shot,s) for s in sources(project,shot)]})

def plan(project,shot):
    """A stable line ID drives editing; exact words and voice remain immutable."""
    catalogue=sources(project,shot);by_id={s['id']:s for s in catalogue};starts={};cursor=0
    for action in shot.get('actions',[]):
        at=float(action.get('start',cursor));ids=action.get('speech_ids')
        if ids is None:
            ids=[s['id'] for s in catalogue if s['id'] not in starts and
                 (s['text']==action.get(s['kind']) or any(m.get('text')==s['text'] and m.get('kind')==s['kind'] for m in action.get('measured_speech',[])))]
        for identity in ids:
            if identity not in by_id or identity in starts:continue
            source=by_id[identity];cached=speech.measurement(project,shot,source)
            starts[identity]=at;at+=cached['duration'] if cached else source['minimum_seconds']
        cursor=max(cursor,at)
    saved=shot.get('speech_mix',{});valid=saved.get('basis')==basis(project,shot)
    edits={s['speech_id']:s for s in saved.get('lines',[])} if valid else {}
    rows=[];cursor=0
    for source in catalogue:
        cached=speech.measurement(project,shot,source);duration=cached['duration'] if cached else source['minimum_seconds']
        start=starts.get(source['id'],cursor);edit=edits.get(source['id'],{})
        start=edit.get('start',start);gain=edit.get('gain',1)
        rows.append({'speech_id':source['id'],'speaker':speech.role(source),'kind':source['kind'],'text':source['text'],
                     'cache_key':speech.key(source,speech.voice(project,source)),'media':cached['media'] if cached else None,
                     'created':cached.get('created') if cached else None,'seed':cached.get('seed') if cached else None,
                     'duration':duration,'measured':bool(cached),'start':start,'end':round(start+duration,6),'gain':gain})
        cursor=max(cursor,start+duration)
    return {'lines':rows,'basis':basis(project,shot),'duration':shot['duration'],
            'required_duration':max([shot['duration'],*[s['end'] for s in rows]]),
            'mix_stale':bool(saved and not valid),'track_current':speech.current(project,shot),
            'track':shot.get('speech_track')}

def validated(project,shot,rows):
    expected=plan(project,shot)
    if not isinstance(rows,list) or len(rows)!=len(expected['lines']):raise ValueError('混音需保留本镜全部原句，每句出现一次')
    index={r['speech_id']:r for r in expected['lines']};result=[];seen=set()
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('speech_id'),str) or row['speech_id'] not in index or row['speech_id'] in seen:raise ValueError('混音原句编号不存在或重复')
        identity=row['speech_id'];seen.add(identity)
        if row.get('cache_key')!=index[identity]['cache_key']:raise store.Conflict('本句文字或音色已修改，请加载最新配音')
        start=timing.number(row.get('start'));gain=timing.number(row.get('gain',1))
        if not 0<=start<=MAX_SECONDS:raise ValueError('配音开始时间需在0–600秒之间')
        if not 0<=gain<=2:raise ValueError('音量需在0–200%之间；0表示静音')
        result.append({'speech_id':identity,'start':round(start,6),'gain':gain})
    return {'basis':expected['basis'],'lines':result}

def read_wave(media):
    import numpy as np,soundfile as sf
    wave,rate=sf.read(str(store.media_path(media)),dtype='float32',always_2d=True)
    if not len(wave) or not np.isfinite(wave).all():raise ValueError('原句音频为空或包含无效采样')
    wave=wave.mean(axis=1)
    if rate!=RATE:
        size=round(len(wave)*RATE/rate)
        wave=np.interp(np.arange(size)*rate/RATE,np.arange(len(wave)),wave).astype('float32')
    return wave

def write_track(project,shot,wave,name,extra):
    import soundfile as sf
    media=store.uid()+'.wav';sf.write(str(store.media_path(media)),wave,RATE,subtype='PCM_16')
    record={'id':store.uid(),'media':media,'name':name,'kind':'audio','duration':len(wave)/RATE,'created':time.time(),
            'scope_shot':shot['id'] if shot else None,**extra}
    project.setdefault('media',[]).append(record)
    return record

def synthesize(project,shot):
    """Add waves rather than overwrite; apply one gain to all stems to avoid clipping."""
    import numpy as np
    rows=plan(project,shot)['lines'];samples=round(timing.number(shot['duration'])*RATE)
    if not 0<samples<=MAX_SECONDS*RATE:raise ValueError('单镜混音时长需在0–600秒之间')
    stems={};placements=[]
    for row in rows:
        if not row['measured']:raise ValueError('原句配音尚未完成：'+row['speaker']+'；请先生成独立配音')
        wave=read_wave(row['media']);start=round(row['start']*RATE);end=start+len(wave)
        if end>samples+1:raise ValueError('配音超出镜头时长；勾选允许延长镜头，或调整开始时间，不变速或截断')
        if row['speaker'] not in stems:stems[row['speaker']]=np.zeros(samples,dtype='float32')
        length=min(len(wave),samples-start)
        stems[row['speaker']][start:start+length]+=wave[:length]*row['gain']
        placements.append({**row,'end':end/RATE,'duration':len(wave)/RATE})
    mixed=np.zeros(samples,dtype='float32')
    for wave in stems.values():mixed+=wave
    peak=float(np.max(np.abs(mixed))) if len(mixed) else 0
    # Shared attenuation means summing exported role stems reproduces the mix.
    scale=min(1,.95/peak) if peak else 1
    return samples,stems,placements,mixed,scale,peak


def preview_wave(project,shot,plan):
    """Encode draft audition with the identical mixer and PCM format as delivery."""
    import io,soundfile as sf
    draft=copy.deepcopy(shot);draft['duration']=plan['duration']
    draft['speech_mix']={'basis':basis(project,shot),'lines':plan['speech']}
    samples,stems,placements,mixed,scale,peak=synthesize(project,draft)
    stream=io.BytesIO();sf.write(stream,mixed*scale,RATE,format='WAV',subtype='PCM_16')
    return stream.getvalue()


def render(project,shot):
    samples,stems,placements,mixed,scale,peak=synthesize(project,shot)
    number=project['shots'].index(shot)+1
    records=[write_track(project,shot,wave*scale,f'第{number}镜 · {name} · 独立音轨',{'tts_stem':True,'voice_role':name}) for name,wave in stems.items()]
    master=write_track(project,shot,mixed*scale,f'第{number}镜 · 最终混合音轨',{'tts_track':True})
    shot['speech_track']={'engine':'role-mix-v1','media':master['media'],'duration':samples/RATE,'placements':placements,
                          'silence_preserved':True,'leading_silence':min((r['start'] for r in placements if r['gain']>0),default=samples/RATE),'trailing_silence':max(0,samples/RATE-max((r['end'] for r in placements if r['gain']>0),default=0)),'role_tracks':records,'mix_gain':scale,'peak_before_gain':peak,'created':master['created'],
                          'shot_signature':timing.shot_signature(shot),'source_hash':source_hash(project,shot)}
    return shot['speech_track']

def save_gains(project,shot,body):
    """Persist line volume before timing approval, without moving any clip."""
    if body.get('basis')!=basis(project,shot):raise store.Conflict('对白或音色已变化，请加载最新配音后调整音量')
    gains=body.get('gains')
    if not isinstance(gains,dict) or not gains:raise ValueError('请提供需要保存的对白音量')
    current=plan(project,shot);index={r['speech_id']:r for r in current['lines']}
    checked={}
    for identity,value in gains.items():
        if identity not in index:raise ValueError('对白编号不存在')
        gain=timing.number(value)
        if not 0<=gain<=2:raise ValueError('音量需在0–200%之间')
        checked[identity]=gain
    from . import performance as perf
    prior_status=perf.status(project,shot)
    performance=shot.get('performance',{});scheduled={r['speech_id']:r for r in performance.get('speech',[])}
    shot['speech_mix']={'basis':current['basis'],'lines':[{'speech_id':r['speech_id'],'start':scheduled.get(r['speech_id'],r)['start'],'gain':checked.get(r['speech_id'],scheduled.get(r['speech_id'],r).get('gain',1))} for r in current['lines']]}
    changed=False
    for identity,gain in checked.items():
        if identity in scheduled and scheduled[identity].get('gain',1)!=gain:
            scheduled[identity]['gain']=gain;changed=True
    if changed:
        # Volume changes keep existing spatial and timing approvals, but the old
        # rendered mix remains stale until explicitly regenerated.
        if prior_status['timing']:
            performance['compiled_hash']=perf.compiled_hash(shot)
            performance['finals']['timing']['hash']=perf.timeline_hash(performance)
            if prior_status['visual']:performance['finals']['visual']['hash']=perf.visual_hash(performance)

    return shot['speech_mix']


def apply(project,shot,body):
    if body.get('basis')!=basis(project,shot):raise store.Conflict('配音来源已修改，请加载最新原句')
    if shot.get('natural_status') not in ('ai_reviewed','human_reviewed'):raise ValueError('先完成 TTS 实测与动作时序，再调整混音落点')
    mix=None if body.get('reset') else validated(project,shot,body.get('lines'))
    if mix is None:shot.pop('speech_mix',None)
    else:shot['speech_mix']=mix
    required=plan(project,shot)['required_duration']
    if required>MAX_SECONDS:raise ValueError('单镜混合音轨最长600秒，请拆分镜头')
    if required>shot['duration']+1/RATE:
        if not body.get('extend_duration'):raise ValueError(f'全部配音需要{required:.3f}秒，当前镜头{shot["duration"]:.3f}秒；勾选允许延长镜头后再生成')
        draft=copy.deepcopy(shot);last=draft['actions'][-1];extra=required-shot['duration']
        last['natural_seconds']=timing.number(last.get('natural_seconds',last['end']-last['start']))+extra
        last['maximum_seconds']=max(last['natural_seconds'],timing.number(last.get('maximum_seconds') or 0))
        last['rationale']=str(last.get('rationale',''))+'；按完整配音末尾延长本段，不改变语速。'
        draft['actions'],draft['duration']=timing.from_natural(draft['actions']);draft['prompt']=timing.render(draft)
        timing.apply_review(project,shot,draft)
    return render(project,shot)

def export_film(project):
    import numpy as np
    shots=project.get('shots',[])
    if not shots or any(not speech.current(project,s) for s in shots):raise ValueError('先完成每个分镜的配音与混音；失效音轨需重新生成')
    for shot in shots:
        if shot['speech_track'].get('engine')!='role-mix-v1':render(project,shot)
    total=sum(round(s['duration']*RATE) for s in shots)
    if total>3600*RATE:raise ValueError('全片音频最长1小时，请分段导出')
    master=np.zeros(total,dtype='float32');stems={};cursor=0;placements=[]
    for shot in shots:
        track=shot['speech_track'];wave=read_wave(track['media']);length=round(shot['duration']*RATE)
        if len(wave)!=length:raise ValueError('分镜音轨实际长度与镜头不一致，请重新混音')
        master[cursor:cursor+length]=wave
        for stem in track.get('role_tracks',[]):
            name=stem['voice_role'];part=read_wave(stem['media'])
            if len(part)!=length:raise ValueError('角色音轨长度已改变，请重新混音')
            if name not in stems:stems[name]=np.zeros(total,dtype='float32')
            stems[name][cursor:cursor+length]+=part
        placements.extend({**p,'shot_id':shot['id'],'start':p['start']+cursor/RATE,'end':p['end']+cursor/RATE} for p in track['placements'])
        cursor+=length
    tracks=[write_track(project,None,wave,'全片 · '+name+' · 独立音轨',{'tts_stem':True,'voice_role':name}) for name,wave in stems.items()]
    final=write_track(project,None,master,'全片 · 最终混合音轨',{'tts_track':True})
    result={'media':final['media'],'duration':total/RATE,'created':final['created'],'role_tracks':tracks,'placements':placements,
            'source_hash':speech.digest([s['speech_track'] for s in shots])}
    project['speech_film_mix']=result
    return result

def archive(project,shot=None):
    import json,zipfile
    track=shot.get('speech_track') if shot else project.get('speech_film_mix')
    if not track:raise ValueError('请先生成混合音轨')
    valid=speech.current(project,shot) if shot else track.get('source_hash')==speech.digest([s.get('speech_track') for s in project['shots']]) and all(speech.current(project,s) for s in project['shots'])
    if not valid:raise ValueError('混音来源已修改，请重新生成后打包')
    name=store.uid()+'.zip'
    with zipfile.ZipFile(store.media_path(name),'w',zipfile.ZIP_DEFLATED) as z:
        z.write(store.media_path(track['media']),'final-mix.wav')
        for i,stem in enumerate(track.get('role_tracks',[]),1):z.write(store.media_path(stem['media']),f'role-{i}.wav')
        for i,p in enumerate(track['placements'],1):z.write(store.media_path(p['media']),f'original-line-{i}'+store.media_path(p['media']).suffix)
        z.writestr('timing-and-roles.json',json.dumps(track,ensure_ascii=False,indent=2))
    return name

def install_routes(app):
    def find(project,sid):
        shot=next((s for s in project.get('shots',[]) if s['id']==sid),None)
        if not shot:raise ValueError('分镜不存在')
        return shot
    @app.get('/api/projects/{pid}/shots/{sid}/tts/mix')
    def view(pid:str,sid:str):
        p=store.get_project(pid);return plan(p,find(p,sid))
    @app.post('/api/projects/{pid}/shots/{sid}/tts/mix/gains')
    def gains(pid:str,sid:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            p=store.get_project(pid)
            if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请加载最新内容后保存音量')
            shot=find(p,sid)
            if any(t['project_id']==pid and t.get('target')==sid and t['kind']=='performance_plan' and t['status'] in ('running','queued','cancelling') for t in store.task_list()):raise ValueError('本镜AI编排正在执行，完成后再修改音量')
            save_gains(p,shot,body);return store.save_project(p,p['revision'])
    @app.post('/api/projects/{pid}/shots/{sid}/tts/mix')
    def mix(pid:str,sid:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            p=store.get_project(pid)
            if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请加载最新内容再混音')
            if any(t['project_id']==pid and t['status'] in ('running','cancelling') and
                   (t.get('options',{}).get('speech_timing_shot')==sid or t['kind']=='schedule' and t.get('target')==sid) for t in store.task_list()):
                raise ValueError('本镜正在配音或审查时序，完成后再混音')
            apply(p,find(p,sid),body);return store.save_project(p,p['revision'])
    @app.post('/api/projects/{pid}/shots/{sid}/tts/lines/{identity}')
    def generate_line(pid:str,sid:str,identity:str,body:dict):
        import secrets
        from . import jobs
        with jobs.TASK_LOCK:
            p=store.get_project(pid)
            if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请加载最新配音')
            find(p,sid)
            task=speech.enqueue_line(p,sid,identity,secrets.randbelow(2147483647),body.get('regenerate',False))
            return {'id':task['id'],'status':task['status']}
    @app.post('/api/projects/{pid}/tts/mix/export')
    def full_mix(pid:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            p=store.get_project(pid)
            if body.get('revision')!=p['revision']:raise store.Conflict('项目已更新，请加载最新混音')
            export_film(p);return store.save_project(p,p['revision'])
    @app.get('/api/projects/{pid}/tts/mix/archive')
    def download(pid:str,shot_id:str=''):
        from fastapi.responses import FileResponse
        p=store.get_project(pid);name=archive(p,find(p,shot_id) if shot_id else None)
        return FileResponse(store.media_path(name),media_type='application/zip',filename='Owl-voice-tracks.zip')
