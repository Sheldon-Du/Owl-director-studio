"""Local yovoice adapter. Never installs models or rewrites yovoice state."""
import json, math, os, subprocess, threading, time
from pathlib import Path
from . import store

CLI=Path(os.environ.get('YOVOICE_CLI',r'D:\2video\TTS\yovoice-cli\yovoice.exe'))
DATA=Path(os.environ.get('YOVOICE_DATA_DIR',str(Path.home()/'.yovoice')))
LOCK=threading.RLock()
SAMPLE='你好，这是我的声音。让我们一起，把故事讲给更多人听。'
FIELDS=('tts_engine','yovoice_model','voice_mode','voice_role','voice_speaker','voice_filename','voice_description','voice_delivery','voice_language','voice_ref_text','voice_speed')

def call(args,cancel=None,timeout=1800):
    if not CLI.is_file():raise ValueError('未找到 yovoice CLI：'+str(CLI))
    with LOCK:
        proc=subprocess.Popen([str(CLI),*map(str,args),'--data-dir',str(DATA),'--json'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        started=time.monotonic()
        try:
            while True:
                if cancel:cancel()
                if time.monotonic()-started>timeout:raise ValueError('yovoice 执行超时，请检查引擎日志')
                try:out,err=proc.communicate(timeout=.2);break
                except subprocess.TimeoutExpired:pass
        except BaseException:
            # Terminate only this CLI and its own inference children.
            if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
            else:proc.kill()
            proc.communicate()
            raise
        if proc.returncode:
            message=(err or out).strip()[-1800:]
            raise ValueError('yovoice：'+message+'；如提示数据目录占用，请关闭 yovoice 桌面版后重试。')
        try:return json.loads(out)
        except ValueError:raise ValueError('yovoice 未返回有效 JSON')

def own_voices():
    root=store.DATA/'yovoice-voices'
    if not root.is_dir():return []
    result=[]
    for file in root.glob('*.json'):
        try:result.append(json.loads(file.read_text(encoding='utf-8')))
        except (OSError,ValueError):continue
    return result

def voice_trash():
    path=store.DATA/'yovoice-voice-trash.json'
    if not path.exists():return []
    return json.loads(path.read_text(encoding='utf-8'))

def remove_voice(identity):
    from . import jobs
    with jobs.TASK_LOCK,LOCK:
        item=next((v for v in voices() if v['filename']==identity),None)
        if not item:raise ValueError('音色不存在或已删除')
        used=[]
        for p in store.list_projects():
            for role,binding in p.get('tts_voice_roles',{}).items():
                if binding.get('tts_engine')=='yovoice' and binding.get('voice_filename')==identity:used.append(p['name']+' / '+role)
        if used:raise ValueError('此音色仍被角色使用，请先改绑其他音色：'+'、'.join(used))
        for task in store.task_list():
            if task['status'] not in ('queued','running','cancelling'):continue
            opts=task.get('options',{})
            configs=[opts]+[line.get('voice',{}) for line in opts.get('speech_lines',[])]
            if any(c.get('voice_filename')==identity for c in configs):raise ValueError('此音色正在用于配音任务，请任务结束后删除')
        if identity.startswith('cli:'):raise ValueError('这是 yovoice 原应用的参考音色，请在 yovoice 中删除；工作台可直接清理本地生成候选')
        name=item.get('media')
        if name:
            for p in store.list_projects(include_deleted=True):
                from .audio_delete import contains
                if contains(p,name):raise ValueError('此参考音频仍在项目中使用，请先删除对应配音：'+p['name'])
            other=[v for v in own_voices() if v.get('media')==name and v['filename']!=identity]
            if not other:store.media_path(name).unlink(missing_ok=True)
        (store.DATA/'yovoice-voices'/(identity[4:]+'.json')).unlink(missing_ok=True)
        rows=[v for v in voice_trash() if v['filename']!=identity]
        (store.DATA/'yovoice-voice-trash.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
        return item

def restore_voice(identity):
    with LOCK:
        rows=voice_trash()
        if not any(v['filename']==identity for v in rows):raise ValueError('音色不在已删除列表')
        (store.DATA/'yovoice-voice-trash.json').write_text(json.dumps([v for v in rows if v['filename']!=identity],ensure_ascii=False,indent=2),encoding='utf-8')

def voices():
    result=[{'filename':'cli:'+v['id'],'label':v['name'],'duration':v.get('duration'),'source':'yovoice'} for v in call(['voices','list'],timeout=20)]
    hidden={v['filename'] for v in voice_trash()}
    return [v for v in result+own_voices() if v['filename'] not in hidden]

def catalog():
    value=call(['models','list'],timeout=20)
    installed={v['id']:v for v in value.get('installed',[])}
    models=[]
    for model in value.get('catalog',[]):
        mid=model['id']
        if not mid.startswith(('index-','voxcpm2-','qwen3-tts-')):continue
        design=mid.startswith('voxcpm2-') or 'voicedesign' in mid
        preset='customvoice' in mid
        modes=['preset'] if preset else ['design'] if 'voicedesign' in mid else ['saved','clone']+(['design'] if design else [])
        models.append({'id':mid,'name':model['name'],'precision':model.get('precision',''),'installed':mid in installed and Path(installed[mid]['path']).is_file(),'modes':modes,'speakers':['Vivian','Serena','Uncle_Fu','Dylan','Eric','Ryan','Aiden','Ono_Anna','Sohee'] if preset else []})
    return {'cli':str(CLI),'data_dir':str(DATA),'models':models,'voices':voices(),'voice_trash':voice_trash(),'sample_text':SAMPLE}

def prepare(options,check_model=True):
    value=dict(options)
    for key,limit,default in [('prompt',12000,''),('voice_role',100,'旁白'),('voice_description',2000,''),('voice_delivery',1000,''),('voice_ref_text',2000,'')]:
        text=value.get(key,default)
        if not isinstance(text,str) or len(text)>limit:raise ValueError('配音文本或描述格式不正确')
        value[key]=text.strip()
    mode=value.get('voice_mode','saved');mid=value.get('yovoice_model','')
    if mode not in ('preset','design','clone','saved'):raise ValueError('请选择音色来源')
    if mode=='design':
        sample=value.get('voice_sample_text',SAMPLE)
        if not isinstance(sample,str) or not sample.strip() or len(sample)>200:raise ValueError('音色试读短句需为 1–200 字')
        value['prompt']=sample.strip()
        for stale in ('voice_filename','voice_ref_media','voice_ref_text'):value.pop(stale,None)
    if not value['prompt']:raise ValueError('请填写实际朗读台词')
    if check_model:
        model=next((m for m in catalog()['models'] if m['id']==mid and m['installed']),None)
        if not model:raise ValueError('请选择 yovoice 中已安装的语音模型')
        if mode not in model['modes']:raise ValueError('所选模型不支持此音色来源')
        if mode=='preset' and value.get('voice_speaker') not in model['speakers']:raise ValueError('请选择内置说话人')
    if mode=='design' and not value['voice_description']:raise ValueError('请填写角色音色描述')
    if mode=='clone':
        if not value.get('voice_authorized'):raise ValueError('请确认参考录音使用授权')
        path=store.media_path(value.get('voice_ref_media',''))
        if not path.is_file():raise ValueError('请选择有效参考录音')
        import soundfile as sf
        try:duration=sf.info(str(path)).duration
        except Exception:raise ValueError('参考录音无法读取，请使用 WAV、FLAC 或可解码的 MP3')
        if not 1<=duration<=60 or path.stat().st_size>20*1024*1024:raise ValueError('参考录音需为 1–60 秒且不超过 20 MB')
    if mode=='saved' and value.get('voice_filename') not in {v['filename'] for v in voices()}:raise ValueError('请选择可用的已保存音色')
    for key,default,low,high in [('voice_speed',1,.5,2),('silence_before_seconds',0,0,600),('silence_after_seconds',0,0,600)]:
        number=float(value.get(key,default))
        if not math.isfinite(number) or not low<=number<=high:raise ValueError('语速或静音时长超出范围')
        value[key]=number
    value['voice_language']=value.get('voice_language','zh')
    if value['voice_language'] not in ('zh','en','auto','ja','es','ar'):raise ValueError('语言不支持')
    value.update(tts_engine='yovoice',profile='tts',media_kind='audio',voice_mode=mode)
    return value

def command(options,output,textfile):
    args=['generate','--model',options['yovoice_model'],'--text-file',str(textfile),'--output',str(output),'--seed',str(options.get('seed',7))]
    mode=options['voice_mode'];mid=options['yovoice_model']
    if mode=='preset':args+=['--speaker',options['voice_speaker']]
    elif mode=='design':args+=['--voice-description','；'.join(v for v in [options['voice_description'],options.get('voice_delivery','')] if v)]
    elif mode=='clone':args+=['--reference',str(store.media_path(options['voice_ref_media']))]
    else:
        filename=options['voice_filename']
        if filename.startswith('cli:'):args+=['--voice',filename[4:]]
        else:
            ref=next(v for v in own_voices() if v['filename']==filename)
            args+=['--reference',str(store.media_path(ref['media']))]
            if ref.get('text'):args+=['--reference-text',ref['text']]
    if mode=='clone' and options.get('voice_ref_text'):args+=['--reference-text',options['voice_ref_text']]
    delivery=options.get('voice_delivery','')
    if mid.startswith('index-'):
        args+=['--speed',str(options.get('voice_speed',1)),'--language',options.get('voice_language','zh') if options.get('voice_language')!='auto' else 'zh']
        if delivery:args+=['--emotion-text',delivery]
    elif delivery and mode!='design' and (mid.startswith('voxcpm2-') and '--reference-text' not in args or 'customvoice' in mid):args+=['--voice-description',delivery]
    if mid.startswith('voxcpm2-'):
        vox_mode='design' if mode=='design' else 'continuation' if '--reference-text' in args else 'clone'
        args+=['--vox-mode',vox_mode]
    if mid.startswith('qwen3-tts-'):args+=['--language',options.get('voice_language','zh')]
    return args

def generate(options,cancel=None):
    import numpy as np,soundfile as sf
    opts=prepare(options);name=store.uid()+'.wav';output=store.media_path(name);textfile=store.media_path(store.uid()+'.txt')
    textfile.write_text(opts['prompt'],encoding='utf-8')
    try:call(command(opts,output,textfile),cancel)
    finally:textfile.unlink(missing_ok=True)
    info=sf.info(str(output))
    if info.frames<=0:raise ValueError('配音输出为空')
    saved=None
    if opts['voice_mode'] in ('design','clone'):
        reference=name if opts['voice_mode']=='design' else opts['voice_ref_media']
        duration=sf.info(str(store.media_path(reference))).duration
        # Long designed narration remains an output, but is not a valid clone anchor.
        if 1<=duration<=60:
            saved={'filename':'owl:'+store.uid(),'label':opts['voice_role'],'media':reference,'text':opts['prompt'] if opts['voice_mode']=='design' else opts.get('voice_ref_text',''),'duration':duration,'model':opts['yovoice_model'],'source':'workbench','description':opts.get('voice_description',''),'seed':opts.get('seed'),'created':time.time()}
            root=store.DATA/'yovoice-voices';root.mkdir(exist_ok=True)
            (root/(saved['filename'][4:]+'.json')).write_text(json.dumps(saved,ensure_ascii=False),encoding='utf-8')
    before=opts.get('silence_before_seconds',0);after=opts.get('silence_after_seconds',0)
    if before or after:
        audio,rate=sf.read(str(output),always_2d=True)
        audio=np.concatenate([np.zeros((round(before*rate),audio.shape[1])),audio,np.zeros((round(after*rate),audio.shape[1]))])
        # Keep the clean anchor immutable when adding delivery silence.
        name=store.uid()+'.wav';sf.write(str(store.media_path(name)),audio,rate,subtype='PCM_16')
    return name,saved

def execute(task):
    from . import jobs,speech_audio
    options=task['options'];cancel=lambda:jobs.check_cancelled(task)
    if options.get('speech_timing_shot'):
        for line in options['speech_lines']:
            if line.get('cached'):continue
            cancel();jobs.progress(task,'yovoice 正在配音：'+line['text'][:35])
            media,_=generate({**line['voice'],'prompt':line['text'],'seed':line['seed']},cancel)
            cancel();jobs.finish(task,media,{'node_id':line['output_node']})
        speech_audio.continue_review(task)
    else:
        jobs.progress(task,'yovoice 正在生成配音，完成后读取真实时长')
        media,saved=generate(options,cancel);cancel()
        if saved:options['saved_yovoice_voice']=saved['filename']
        jobs.finish(task,media)
        task['completion_message']='配音已生成并测时'+('；候选音色已保存，请试听后绑定角色' if saved else '')

def install_routes(app):
    @app.get('/api/yovoice/catalog')
    def get_catalog():
        try:return {**catalog(),'ready':True}
        except (ValueError,OSError) as e:return {'ready':False,'error':str(e),'models':[],'voices':[],'cli':str(CLI),'data_dir':str(DATA)}
    @app.get('/api/yovoice/voices/{identity}/audio')
    def preview(identity:str):
        from fastapi.responses import FileResponse
        ref=next((v for v in voices() if v['filename']==identity),None)
        if not ref:raise ValueError('音色不存在')
        path=DATA/'voices'/(identity[4:]+'.wav') if identity.startswith('cli:') else store.media_path(ref['media'])
        return FileResponse(path)
    @app.post('/api/yovoice/voices/{identity}/remove')
    def delete_voice(identity:str):
        remove_voice(identity);return {'ok':True}
    @app.post('/api/yovoice/voices/{identity}/restore')
    def undo_voice(identity:str):
        restore_voice(identity);return {'ok':True}
    @app.post('/api/projects/{pid}/yovoice/bind')
    def bind(pid:str,body:dict):
        opts=prepare({**body,'prompt':SAMPLE})
        if opts['voice_mode'] not in ('preset','saved'):raise ValueError('请先生成试听，再选择已保存音色绑定角色')
        def apply(p):
            if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请刷新后重试')
            p.setdefault('tts_voice_roles',{})[opts['voice_role']]={k:opts.get(k) for k in FIELDS}
            from . import timing_speech,speech_audio
            for shot in p.get('shots',[]):
                if any(speech_audio.role(s)==opts['voice_role'] for s in timing_speech.raw_catalogue(p,shot)):shot['natural_status']='unverified'
        return store.mutate(pid,apply)
