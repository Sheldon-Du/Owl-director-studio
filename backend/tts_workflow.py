"""One Qwen3 speech workflow, with preset, design-and-save, and saved voice routes."""
import copy,json,math,re,uuid
from pathlib import Path
from . import comfy,store

VOICES=comfy.MODEL_ROOT/'qwen-tts'/'voices'
SPEAKERS=['Aiden','Dylan','Eric','Ono_anna','Ryan','Serena','Sohee','Uncle_fu','Vivian']
SAMPLE='你好，这是我的声音。无论是平静地讲述，还是认真地回答，我都会用清晰自然的表达，让你听懂每一句话。'

def catalog():
    saved=[]
    if VOICES.is_dir():
        for p in sorted(VOICES.iterdir(),key=lambda x:x.stat().st_mtime,reverse=True):
            if not p.is_file() or p.suffix.lower() not in ('.wav','.mp3','.flac'):continue
            label=p.stem
            try:label=json.loads(p.with_suffix('.json').read_text(encoding='utf-8')).get('owl_role') or label
            except (OSError,ValueError,AttributeError):pass
            saved.append({'filename':p.name,'label':label,'created':p.stat().st_mtime,'cached':p.with_suffix('.qvp').is_file()})
    return {'speakers':SPEAKERS,'voices':saved,'sample_text':SAMPLE}

def prepare(options):
    value=dict(options);mode=value.get('voice_mode','preset')
    if mode not in ('preset','design','clone','saved','silence'):raise ValueError('请选择预设、声音设计、声音克隆、已保存音色或纯静音')
    for key,limit,default in (('prompt',12000,''),('voice_role',100,'旁白'),('voice_description',2000,''),('voice_delivery',1000,''),('voice_sample_text',200,SAMPLE),('voice_ref_text',2000,'')):
        text=value.get(key,default)
        if not isinstance(text,str) or len(text)>limit:raise ValueError(f'{key}需为不超过{limit}字的文本')
        value[key]=text.strip()
    if not value['prompt'] and mode!='silence':raise ValueError('请填写实际朗读的正文或台词')
    for key in ('silence_seconds','silence_before_seconds','silence_after_seconds'):
        try:n=float(value.get(key,1 if key=='silence_seconds' else 0))
        except (ValueError,TypeError):raise ValueError('静音时长需为秒数')
        if not math.isfinite(n) or not 0<=n<=600:raise ValueError('单段静音需为0–600秒')
        value[key]=n
    if mode=='silence' and value['silence_seconds']<=0:raise ValueError('纯静音时长需大于0秒')
    if not value['voice_role']:value['voice_role']='旁白'
    value.update(profile='tts',media_kind='audio',tts_engine='owl-qwen3',voice_mode=mode)
    value['voice_language']=value.get('voice_language','Chinese')
    if value['voice_language'] not in ('Chinese','English','Auto'):raise ValueError('请选择中文、英文或自动语言')
    if mode=='preset':
        value['voice_speaker']=value.get('voice_speaker','Vivian')
        if value['voice_speaker'] not in SPEAKERS:raise ValueError('预设说话人不存在')
    elif mode in ('design','clone'):
        if mode=='design' and (not value['voice_description'] or not value['voice_sample_text']):raise ValueError('新建音色需填写音色描述和固定试读文本')
        if mode=='clone':
            if value.get('voice_authorized') is not True:raise ValueError('请先确认参考录音与音色克隆的使用授权')
            name=value.get('voice_ref_media','')
            if not isinstance(name,str) or not name or not store.media_path(name).is_file():raise ValueError('请从项目素材中选择参考录音')
            if not value['voice_ref_text']:raise ValueError('请填写与参考录音一致的原话文字')
        # The installed save node overwrites names. Every new candidate gets an
        # independent name; a retry cannot replace an adopted voice.
        value['voice_filename']='owl-'+uuid.uuid4().hex+'.wav'
    elif mode=='saved':
        filename=value.get('voice_filename','')
        if not isinstance(filename,str) or filename not in {v['filename'] for v in catalog()['voices']}:raise ValueError('请选择声音库中已保存的音色')
    return value

def check_models(mode):
    types={'preset':['CustomVoice'],'design':['VoiceDesign','Base'],'clone':['Base'],'saved':['Base'],'silence':[]}[mode]
    for kind in types:
        root=comfy.MODEL_ROOT/'qwen-tts'/f'Qwen3-TTS-12Hz-1.7B-{kind}'
        if not (root/'config.json').is_file() or not list(root.glob('*.safetensors')):raise ValueError('缺少完整本地 Qwen3-TTS 模型：'+kind)
    if types:
        tokenizer=comfy.MODEL_ROOT/'qwen-tts'/'Qwen3-TTS-Tokenizer-12Hz'
        if not (tokenizer/'config.json').is_file() or not (tokenizer/'model.safetensors').is_file():raise ValueError('缺少完整本地Qwen3语音Tokenizer，不自动下载')

def chunks(text,limit=280):
    """Bound audio generation by natural sentences without deleting any text."""
    parts=re.findall(r'[^。！？；\n]+[。！？；\n]*|[。！？；\n]+',text)
    rows=[];buffer=''
    for part in parts:
        while len(part)>limit:
            if buffer:rows.append(buffer);buffer=''
            cut=max(part.rfind('，',0,limit),part.rfind(' ',0,limit))
            cut=cut+1 if cut>limit//2 else limit
            rows.append(part[:cut]);part=part[cut:]
        if len(buffer)+len(part)>limit:rows.append(buffer);buffer=''
        buffer+=part
    if buffer:rows.append(buffer)
    return rows

def graph(options,metadata=None):
    mode=options['voice_mode'];check_models(mode)
    seed=int(options.get('seed',42));common={'model_choice':'1.7B','device':'auto','precision':'bf16','language':options.get('voice_language','Chinese'),'seed':seed,'attention':'auto','unload_model_after_generate':True}
    if mode=='silence':
        result={'1':comfy.node('EmptyAudio',duration=options['silence_seconds'],sample_rate=24000,channels=1)};output='1'
    elif mode=='preset':
        result={'1':comfy.node('FB_Qwen3TTSCustomVoice',**common,text=options['prompt'],speaker=options['voice_speaker'],instruct=options.get('voice_delivery',''),custom_model_path=str(comfy.MODEL_ROOT/'qwen-tts'/'Qwen3-TTS-12Hz-1.7B-CustomVoice'))}
        output='1'
    elif mode in ('design','clone'):
        name=options['voice_filename']
        if not re.fullmatch(r'owl-[0-9a-f]{32}\.wav',name):raise ValueError('新音色文件名无效')
        if (VOICES/name).exists():raise ValueError('该音色候选已保存，请选择复用音色，或重新创建候选')
        reference_text=options['voice_sample_text'] if mode=='design' else options['voice_ref_text']
        if mode=='clone':
            import soundfile as sf
            try:
                audio,sr=sf.read(str(store.media_path(options['voice_ref_media'])),always_2d=True)
                seconds=len(audio)/sr
                if not 3<=seconds<=60:raise ValueError('参考录音请选择3–60秒的单人清晰语音')
                if not len(audio) or abs(audio).max()<0.0001:raise ValueError('参考录音为静音，请换成清晰的人声')
            except RuntimeError:raise ValueError('参考录音无法解码，请使用WAV、FLAC或MP3音频')
        reference=comfy.node('FB_Qwen3TTSVoiceDesign',**common,text=reference_text,instruct=options['voice_description'],max_new_tokens=4096) if mode=='design' else comfy.node('LoadAudio',audio=comfy.upload(options['voice_ref_media']))
        result={'1':reference,
                '2':comfy.node('FB_Qwen3TTSVoiceClonePrompt',ref_audio=['1',0],ref_text=reference_text,model_choice='1.7B',device='auto',precision='bf16',attention='auto',x_vector_only=False,unload_model_after_generate=True),
                '3':comfy.node('FB_Qwen3TTSSaveVoice',voice_clone_prompt=['2',0],filename=Path(name).stem,audio=['1',0],ref_text=reference_text),
                '4':comfy.node('FB_Qwen3TTSVoiceClone',**common,target_text=options['prompt'],voice_clone_prompt=['2',0])}
        output='4'
    else:
        name=options['voice_filename']
        if name not in {v['filename'] for v in catalog()['voices']}:raise ValueError('已保存音色不存在')
        result={'1':comfy.node('FB_Qwen3TTSLoadSpeaker',filename=name),
                '2':comfy.node('FB_Qwen3TTSVoiceClone',**common,target_text=options['prompt'],voice_clone_prompt=['1',0],ref_audio=['1',1],ref_text=['1',2])}
        output='2'
    # Long prose must not silently hit the model's output-token limit. Reuse
    # the exact same voice conditioning and concatenate sentences in order.
    if mode!='silence':
        segments=chunks(options['prompt']);text_key='text' if mode=='preset' else 'target_text'
        voice_node=copy.deepcopy(result[output]);voice_node['inputs']['max_new_tokens']=4096
        result[output]=copy.deepcopy(voice_node);result[output]['inputs'][text_key]=segments[0]
        if len(segments)>1:result[output]['inputs']['unload_model_after_generate']=False
        for i,text in enumerate(segments[1:],1):
            key=str(200+i);join=str(600+i)
            result[key]=copy.deepcopy(voice_node);result[key]['inputs'].update({text_key:text,'seed':(seed+i)%2147483647,'unload_model_after_generate':i==len(segments)-1})
            result[join]=comfy.node('AudioConcat',audio1=[output,0],audio2=[key,0],direction='after');output=join
    for key,direction in (('silence_before_seconds','before'),('silence_after_seconds','after')):
        seconds=options.get(key,0)
        if seconds:
            identity='9001' if direction=='before' else '9003';join=str(int(identity)+1)
            result[identity]=comfy.node('EmptyAudio',duration=seconds,sample_rate=24000,channels=1)
            result[join]=comfy.node('AudioConcat',audio1=[output,0],audio2=[identity,0],direction=direction);output=join
    role=re.sub(r'[^\w-]','_',options['voice_role'])[:80] or 'voice'
    result['10']=comfy.node('SaveAudio',audio=[output,0],filename_prefix='Owl-director/tts/'+role)
    metadata=metadata or comfy.info()
    missing=[n['class_type'] for n in result.values() if n['class_type'] not in metadata]
    if missing:raise ValueError('ComfyUI 缺少节点：'+', '.join(missing))
    return result

def gui(graph,metadata):
    """Export precisely the nodes/links submitted by the web UI for ComfyUI."""
    nodes=[];links=[];link_id=0
    for order,(key,node) in enumerate(graph.items()):
        spec=metadata[node['class_type']];inputs=[];widgets=[];widget_names=[]
        for name,field in {**spec.get('input',{}).get('required',{}),**spec.get('input',{}).get('optional',{})}.items():
            kind=field[0];settings=field[1] if len(field)>1 else {}
            fallback=settings.get('default',kind[0] if isinstance(kind,list) and kind else '' if kind in ('STRING','COMBO') else False if kind=='BOOLEAN' else 0)
            value=node['inputs'].get(name,fallback)
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and isinstance(value[1],int):
                link_id+=1;links.append([link_id,int(value[0]),value[1],int(key),len(inputs),kind]);inputs.append({'name':name,'type':kind,'link':link_id})
            elif isinstance(kind,list) or kind in ('INT','FLOAT','STRING','BOOLEAN','COMBO'):
                widgets.append(value);widget_names.append(name)
                inputs.append({'name':name,'type':kind,'link':None,'widget':{'name':name}})
                if settings.get('control_after_generate'):widgets.append('fixed');widget_names.append(None)
            else:inputs.append({'name':name,'type':kind,'link':None})
        outputs=[{'name':name,'type':kind,'links':[]} for name,kind in zip(spec.get('output_name',spec.get('output',[])),spec.get('output',[]))]
        if node['class_type']=='VHS_VideoCombine':
            # VideoHelperSuite persists dynamically selected codec widgets as
            # an object, including fields absent from /object_info.
            widgets={k:v for k,v in node['inputs'].items() if not isinstance(v,list)}
            widget_names=[]
        nodes.append({'id':int(key),'type':node['class_type'],'pos':[order*420,80 if key!='3' else 600],'size':[390,450],'flags':{},'order':order,'mode':0,'inputs':inputs,'outputs':outputs,'properties':{'Node name for S&R':node['class_type'],'owl_widget_names':widget_names},'widgets_values':widgets})
    for link in links:
        source=next(n for n in nodes if n['id']==link[1]);source['outputs'][link[2]]['links'].append(link[0])
    return {'last_node_id':max(n['id'] for n in nodes),'last_link_id':link_id,'nodes':nodes,'links':links,'groups':[],'config':{},'extra':{'owl_tts':'Qwen3 · 配音与旁白共用；新建音色保存后切换复用，不反复设计'},'version':0.4}

def register_voice(options):
    if options.get('voice_mode') not in ('design','clone'):return
    name=options['voice_filename'];path=VOICES/Path(name).with_suffix('.json')
    if not path.is_file():return
    try:record=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return
    if not isinstance(record,dict):return
    record.update(owl_role=options['voice_role'],owl_description=options['voice_description'],owl_seed=options['seed'],owl_mode=options['voice_mode'])
    path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')

def install_routes(app):
    @app.post('/api/projects/{pid}/tts/timing')
    def batch_timing(pid:str,body:dict):
        import secrets
        from . import speech_audio
        p=store.get_project(pid)
        if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请重新保存后测时')
        tasks=[speech_audio.enqueue(p,s['id'],secrets.randbelow(2147483647)) for s in p.get('shots',[]) if s.get('actions') and any(not line['cached'] for line in speech_audio.prepare(p,s['id'],0)['speech_lines'])]
        if not tasks:return {'tasks':[],'skipped':True,'message':'已有配音齐全，已跳过生成'}
        return {'tasks':[{'id':t['id'],'status':t['status']} for t in tasks]}
    @app.get('/api/projects/{pid}/tts/roles')
    def roles(pid:str):
        from . import speech_audio,timing_speech
        p=store.get_project(pid)
        names={speech_audio.role(s) for shot in p.get('shots',[]) for s in timing_speech.raw_catalogue(p,shot)}
        return {'roles':sorted(names|set(p.get('tts_voice_roles',{}))), 'bindings':p.get('tts_voice_roles',{})}
    @app.post('/api/projects/{pid}/tts/roles')
    def bind_role(pid:str,body:dict):
        options=prepare({**body,'prompt':SAMPLE})
        if options['voice_mode'] not in ('preset','saved'):raise ValueError('先试听设计或克隆结果，再从声音库选择并绑定')
        def apply(p):
            if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请刷新后保存音色绑定')
            p.setdefault('tts_voice_roles',{})[options['voice_role']]={k:options.get(k) for k in ('voice_mode','voice_speaker','voice_filename','voice_delivery','voice_language')}
            from . import speech_audio,timing_speech
            for shot in p.get('shots',[]):
                if any(speech_audio.role(s)==options['voice_role'] for s in timing_speech.raw_catalogue(p,shot)):
                    shot['natural_status']='unverified'
        return store.mutate(pid,apply)
    @app.get('/api/tts/voices')
    def read_voices():return catalog()
    @app.get('/api/tts/voices/{filename}/audio')
    def voice_preview(filename:str):
        from fastapi.responses import FileResponse
        if filename not in {v['filename'] for v in catalog()['voices']}:raise ValueError('音色参考不存在')
        return FileResponse(VOICES/filename)
    @app.post('/api/tts/workflow')
    def export_workflow(body:dict):
        from fastapi.responses import Response
        options=prepare(body);metadata=comfy.info();workflow=gui(graph(options,metadata),metadata)
        return Response(json.dumps(workflow,ensure_ascii=False),media_type='application/json',headers={'Content-Disposition':'attachment; filename="Owl-TTS.json"'})
