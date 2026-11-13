"""Offline subtitle timing using pyVideoTrans's installed runtime and ASR model."""
import copy,json,os,subprocess,threading,time,hashlib
from pathlib import Path
from . import store,exporter
ROOT=Path(r'D:\2video\v2text\pyvideotrans')
LOCK=threading.Lock()
STATES={}

def state_file(pid):return store.DATA/'subtitles'/'states'/(hashlib.sha256(pid.encode()).hexdigest()+'.json')

def saved_state(pid):
    if pid in STATES:return STATES[pid]
    path=state_file(pid)
    if path.is_file():
        try:return json.loads(path.read_text('utf-8'))
        except (ValueError,OSError):pass
    return {'status':'idle'}

def paths():
    runtime=ROOT/'_internal';model=ROOT/'models'/'models--mobiuslabsgmbh--faster-whisper-large-v3-turbo'
    if not (runtime/'python310.dll').is_file():raise ValueError('未找到本地 pyVideoTrans Python 3.10 运行库')
    if not (model/'model.bin').is_file():raise ValueError('未找到 pyVideoTrans 已下载的 Whisper 模型，请在该软件中下载本地模型')
    return runtime,model

def timeline_hash(p):
    from .speech_audio import digest
    return digest(p.get('timeline',[]))

def run(p):
    pid=p['id'];work=store.DATA/'subtitles'/store.uid();work.mkdir(parents=True,exist_ok=True)
    try:
        runtime,model=paths();clips=p.get('timeline',[]);total=sum(float(c['duration']) for c in clips if c['kind']!='audio')
        if total<=0:raise ValueError('时间线中没有画面片段')
        # Render audio only; retain video-source dialogue, trims, volumes and music offsets.
        inputs=['-f','lavfi','-i',f'anullsrc=r=16000:cl=mono:d={total}'];filters=[];labels=['[0:a]'];cursor=0;index=0
        for c in clips:
            duration=float(c['duration']);audio=c['kind']=='audio'
            start=float(c.get('start',0)) if audio else cursor
            if audio or c['kind']=='video' and exporter.has_audio(store.media_path(c['media'])):
                index+=1;inputs+=['-ss',str(c.get('in',0)),'-t',str(duration),'-i',str(store.media_path(c['media']))]
                filters.append(f'[{index}:a]aresample=16000,aformat=channel_layouts=mono,asetpts=PTS-STARTPTS,volume={float(c.get("volume",1))},adelay={round(start*1000)}:all=1[a{index}]');labels.append(f'[a{index}]')
            if not audio:cursor+=duration
        if not index:raise ValueError('时间线没有可识别声音，请先加入对白或含声音的视频')
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:normalize=0:duration=first[out]')
        wav=work/'timeline.wav';exporter.run([*inputs,'-filter_complex',';'.join(filters),'-map','[out]','-t',str(total),'-c:a','pcm_s16le',str(wav)])
        output=work/'captions.json';script=Path(__file__).with_name('subtitle_worker.py');launcher=Path(__file__).with_name('subtitle_runtime.ps1')
        command=['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',str(launcher),'-RuntimeRoot',str(runtime),'-Script',str(script),'-InputFile',str(wav),'-OutputFile',str(output),'-ModelPath',str(model)]
        env={k:v for k,v in os.environ.items() if k not in ('PYTHONHOME','PYTHONPATH')};env['HF_HUB_OFFLINE']='1';env['TRANSFORMERS_OFFLINE']='1'
        result=subprocess.run(command,capture_output=True,timeout=7200,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or not output.is_file():raise ValueError('本地识别失败：'+(result.stderr or result.stdout).decode('utf-8',errors='replace')[-1800:])
        rows=json.loads(output.read_text('utf-8'))['captions']
        for r in rows:r['id']=store.uid()
        def stamp(n):
            ms=round(n*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
        name=store.uid()+'.srt';store.media_path(name).write_text('\n\n'.join(f'{i+1}\n{stamp(r["start"])} --> {stamp(r["end"])}\n{r["text"]}' for i,r in enumerate(rows)),encoding='utf-8-sig')
        STATES[pid]={'status':'completed','captions':rows,'media':name,'timeline_hash':timeline_hash(p),'created':time.time()}
    except Exception as e:STATES[pid]={'status':'failed','message':str(e)}
    finally:
        from .authoring_transport import save
        try:save(state_file(pid),STATES[pid])
        finally:LOCK.release()

def execute(task):
    from . import jobs
    jobs.check_cancelled(task)
    if not LOCK.acquire(blocking=False):raise ValueError('已有本地字幕任务正在识别，请稍后重试')
    STATES[task['project_id']]={'status':'running','created':time.time()}
    jobs.progress(task,'正在读取剪辑音轨并调用 pyVideoTrans 本地 Whisper 模型')
    run(copy.deepcopy(task['snapshot']))
    if STATES[task['project_id']]['status']=='failed':raise ValueError(STATES[task['project_id']]['message'])
    task['completion_message']='字幕识别完成，请到剪辑页核对并载入结果'

def install(app):
    @app.get('/api/projects/{pid}/subtitles/status')
    def status(pid:str):
        p=store.get_project(pid);value=copy.deepcopy(saved_state(pid))
        active=next((t for t in store.task_list() if t['project_id']==pid and t['kind']=='subtitle_recognize' and t['status'] in ('queued','running','cancelling')),None)
        if active:return {'status':active['status'],'task_id':active['id']}
        if value.get('timeline_hash') and value['timeline_hash']!=timeline_hash(p):value.update(stale=True,message='识别后时间线已变化，请重新识别或核对时间点')
        return value
    @app.post('/api/projects/{pid}/subtitles/recognize')
    def recognize(pid:str,body:dict):
        p=store.get_project(pid)
        if p['revision']!=body.get('revision'):raise store.Conflict('时间线已更新，请先保存')
        paths()
        if not p.get('timeline'):raise ValueError('请先将视频加入剪辑时间线')
        from . import jobs
        with jobs.TASK_LOCK:
            if any(t['kind']=='subtitle_recognize' and t['status'] in ('queued','running','cancelling') for t in store.task_list()):raise ValueError('已有本地字幕识别任务排队或运行，请稍后重试')
            task=jobs.enqueue('subtitle_recognize',p)
            return {'status':'queued','task_id':task['id']}
