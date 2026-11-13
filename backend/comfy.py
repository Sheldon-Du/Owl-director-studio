import copy
import json
import math
import time
import threading
from pathlib import Path
import httpx
from . import store,workflow_files,gpu_placement

MODEL_ROOT=Path(r'D:\2video\ComfyUI_Mie_2026_V9.0_Large\ComfyUI\models')
SUBMISSION_LOCK=threading.RLock()

def retained_graph(graph):
    graph=copy.deepcopy(graph)
    for spec in graph.values():
        inputs=spec['inputs'];kind=spec['class_type']
        for key in ('unload_model_after_generate','force_unload'):
            if key in inputs:inputs[key]=False
        if kind in ('SeedVR2LoadDiTModel','SeedVR2LoadVAEModel'):inputs['cache_model']=True
        if kind.startswith('LayerUtility: PurgeVRAM'):
            for key,value in list(inputs.items()):
                if isinstance(value,bool) and ('purge' in key.lower() or 'unload' in key.lower()):inputs[key]=False
    return gpu_placement.apply(graph)


def url():
    return store.settings()['comfy_url'].rstrip('/')


def request(method,path,**kw):
    with SUBMISSION_LOCK:
        with httpx.Client(timeout=kw.pop('timeout',30),trust_env=False,follow_redirects=False) as client:
            response=client.request(method,url()+path,**kw)
            response.raise_for_status()
            return response.json()


def info():
    return request('GET','/object_info',timeout=90)


def health():
    try:
        result=request('GET','/system_stats',timeout=3)
        return {'online':True,'devices':result.get('devices',[])}
    except Exception as e:
        return {'online':False,'error':str(e)}


def model_name(metadata,node,input_key,needle):
    fields=metadata.get(node,{}).get('input',{})
    value=fields.get('required',{}).get(input_key) or fields.get('optional',{}).get(input_key)
    options=value[0] if value else None
    if options=='COMBO' and len(value)>1:options=value[1].get('options',[])
    if not isinstance(options,list):
        raise ValueError('缺少模型加载节点：'+node)
    match=[m for m in options if Path(m.replace('\\','/')).name==needle]
    if not match:
        raise ValueError('缺少模型：'+needle)
    return match[0]


def node(kind,**inputs):
    return {'class_type':kind,'inputs':inputs}


def upload(name):
    path=store.media_path(name)
    with path.open('rb') as stream:
        result=request('POST','/upload/image',files={'image':(path.name,stream,'image/png')},data={'type':'input','overwrite':'false'})
    return '/'.join(x for x in (result.get('subfolder',''),result['name']) if x)


def krea2_image_workflow(prompt,seed,metadata):
    config=workflow_files.krea2_config(metadata)
    graph=copy.deepcopy(config['graph'])
    for key,value in (('prompt',prompt),('seed',seed)):
        slot=config['bindings'][key]
        graph[slot['node']]['inputs'][slot['input']]=value
    missing=sorted({v['class_type'] for v in graph.values() if v['class_type'] not in metadata})
    if missing:raise ValueError('Krea2 工作流缺少节点：'+', '.join(missing))
    for spec in graph.values():
        kind=spec['class_type']
        if kind in ('UNETLoader','CLIPLoader','VAELoader','LoraLoaderModelOnly'):
            key={'UNETLoader':'unet_name','CLIPLoader':'clip_name','VAELoader':'vae_name','LoraLoaderModelOnly':'lora_name'}[kind]
            spec['inputs'][key]=model_name(metadata,kind,key,Path(spec['inputs'][key].replace('\\','/')).name)
    return graph


def image_workflow(model,prompt,seed,references,width=768,height=768):
    metadata=info()
    if model not in ('z-image','krea2','qwen-image-2.1'):
        raise ValueError('未知预览模型')
    # Image2.1 handles both text-only and reference generation by default.
    # Krea2 is an explicit alternate; never switch models silently.
    if model in ('z-image','krea2') and not references:
        return krea2_image_workflow(prompt,seed,metadata)
    graph={}
    if model in ('z-image','krea2'):
        if references:
            raise ValueError('Krea2 文生图工作流不接受参考图。请切换多图参考模式，或明确选择不带参考的生成。')
    elif model=='qwen-image-2.1':
        if len(references)>16:
            raise ValueError('Qwen-Image-2.1 单次支持最多16个参考槽，请明确选择本次参考，不能静默丢弃。')
        graph={
            '1':node('UNETLoader',unet_name=model_name(metadata,'UNETLoader','unet_name','qwen_image_2.1_int8_convrot.safetensors'),weight_dtype='default'),
            '2':node('CLIPLoader',clip_name=model_name(metadata,'CLIPLoader','clip_name','qwen3vl_8b_int8_convrot.safetensors'),type='qwen_image',device='default'),
            '3':node('VAELoader',vae_name=model_name(metadata,'VAELoader','vae_name','qwen_image_2.1_vae_bf16.safetensors')),
            '4':node('TextEncodeQwenImage21',clip=['2',0],prompt=prompt,negative_prompt='',vae=['3',0],resolution=768),
            '6':node('EmptySD3LatentImage',width=width,height=height,batch_size=1),
            '7':node('ModelSamplingAuraFlow',model=['1',0],shift=3.0),
            '8':node('KSampler',model=['7',0],positive=['4',0],negative=['4',1],latent_image=['4',2],seed=seed,steps=25,cfg=1.0,sampler_name='euler',scheduler='simple',denoise=1.0)}
        for i,ref in enumerate(references):
            key=str(20+i)
            graph[key]=node('LoadImage',image=upload(ref['media']))
            graph['4']['inputs'][f'images.image_{i+1}']=[key,0]
        if width!=height:
            # Preserve Qwen 2.1's 64-channel latent while setting the requested
            # output canvas. EmptySD3LatentImage has incompatible channels.
            # This generic node assumes an 8px VAE, while Qwen decodes at 16px.
            graph['11']=node('LatentUpscale',samples=['4',2],upscale_method='nearest-exact',width=width//2,height=height//2,crop='disabled')
            graph['8']['inputs']['latent_image']=['11',0]
    else:
        raise ValueError('未知预览模型')
    graph['9']=node('VAEDecode',samples=['8',0],vae=['3',0])
    graph['10']=node('SaveImage',images=['9',0],filename_prefix='director-studio/preview')
    missing=[v['class_type'] for v in graph.values() if v['class_type'] not in metadata]
    if missing:
        raise ValueError('ComfyUI 缺少节点：'+', '.join(missing))
    return graph


def custom_workflow(profile,bindings,references):
    path=workflow_files.IMPORTED/f'{profile}.json'
    if not path.exists():
        return builtin_workflow(profile,bindings,references)
    config=json.loads(path.read_text(encoding='utf-8'))
    graph=copy.deepcopy(config['graph'])
    slots=config.get('bindings',{})
    if len(references)>len(slots.get('references',[])):
        raise ValueError('工作流参考槽不足，不能静默丢弃图片')
    for key,value in bindings.items():
        slot=slots.get(key)
        if slot:
            graph[str(slot['node'])]['inputs'][slot['input']]=value
    for ref,slot in zip(references,slots.get('references',[])):
        graph[str(slot['node'])]['inputs'][slot['input']]=upload(ref['media'])
    for slot in slots.get('references',[])[len(references):]:
        if slot.get('required',True):
            raise ValueError('缺少工作流必需参考图片')
    return graph


def asset_upscale_workflow(media):
    """Real ComfyUI model upscaling; never redraw a selected asset."""
    metadata=info()
    required=('LoadImage','UpscaleModelLoader','ImageUpscaleWithModel','SaveImage')
    missing=[kind for kind in required if kind not in metadata]
    if missing:raise ValueError('图片二次放大缺少节点：'+', '.join(missing))
    field=metadata['UpscaleModelLoader'].get('input',{}).get('required',{}).get('model_name',[[]])
    options=field[0]
    if options=='COMBO' and len(field)>1:options=field[1].get('options',[])
    if not isinstance(options,list) or not options:raise ValueError('ComfyUI 未安装图片放大模型，请在 models/upscale_models 中配置后重试；不会自动下载')
    preferred=next((name for name in options if 'realesrgan' in name.lower() or 'ultrasharp' in name.lower()),next((name for name in options if '4x' in name.lower() or '2x' in name.lower()),None))
    if not preferred:raise ValueError('没有可用的2x或4x图片放大模型；1x去噪模型不能用作二次放大')
    graph={'1':node('LoadImage',image=upload(media)),
           '2':node('UpscaleModelLoader',model_name=preferred),
           '3':node('ImageUpscaleWithModel',upscale_model=['2',0],image=['1',0]),
           '4':node('SaveImage',images=['3',0],filename_prefix='owl-director/asset-upscale')}
    return graph,preferred


def builtin_workflow(profile,values,references):
    metadata=info()
    seed=values.get('seed',42)
    prompt=values.get('prompt','')
    duration=float(values.get('duration',5))
    if profile=='video':
        if len(references)!=1:
            raise ValueError('内置 Wan 工作流需要一张已确认首帧。先使用多参考图生成首帧，再采用；它不直接消费多图。')
        if duration>10 or duration<1:
            raise ValueError('内置 Wan 单镜支持1–10秒；较长动作请拆镜或导入长镜工作流，不能自动加速。')
        frame_count=math.ceil((math.ceil(duration*16)-1)/4)*4+1
        graph={
            '1':node('UnetLoaderGGUF',unet_name=model_name(metadata,'UnetLoaderGGUF','unet_name','wan2.1-i2v-14b-480p-Q6_K.gguf')),
            '2':node('CLIPLoader',clip_name=model_name(metadata,'CLIPLoader','clip_name','umt5_xxl_fp8_e4m3fn_scaled.safetensors'),type='wan',device='default'),
            '3':node('VAELoader',vae_name=model_name(metadata,'VAELoader','vae_name','wan_2.1_vae.safetensors')),
            '4':node('CLIPTextEncode',clip=['2',0],text=prompt),
            '5':node('CLIPTextEncode',clip=['2',0],text='加速，动作跳步，瞬移，变形，多余手指，文字水印'),
            '6':node('LoadImage',image=upload(references[0]['media'])),
            '7':node('CLIPVisionLoader',clip_name=model_name(metadata,'CLIPVisionLoader','clip_name','clip_vision_h.safetensors')),
            '8':node('CLIPVisionEncode',clip_vision=['7',0],image=['6',0],crop='center'),
            '9':node('WanImageToVideo',positive=['4',0],negative=['5',0],vae=['3',0],width=512,height=320,length=frame_count,batch_size=1,start_image=['6',0],clip_vision_output=['8',0]),
            '10':node('ModelSamplingSD3',model=['1',0],shift=8.0),
            '11':node('KSampler',model=['10',0],positive=['9',0],negative=['9',1],latent_image=['9',2],seed=seed,steps=20,cfg=6.0,sampler_name='uni_pc',scheduler='simple',denoise=1.0),
            '12':node('VAEDecode',samples=['11',0],vae=['3',0]),
            '13':node('VHS_VideoCombine',images=['12',0],frame_rate=16,loop_count=0,filename_prefix='director-studio/video',format='video/h264-mp4',pingpong=False,save_output=True,pix_fmt='yuv420p',crf=19,save_metadata=True,trim_to_audio=False)}
    elif profile=='tts':
        model=MODEL_ROOT/'qwen-tts'/'Qwen3-TTS-12Hz-1.7B-CustomVoice'
        if not (model/'config.json').exists():
            raise ValueError('缺少本地 Qwen3-TTS 模型，不自动联网下载')
        graph={'1':node('FB_Qwen3TTSCustomVoice',text=prompt,speaker='Vivian',model_choice='1.7B',device='auto',precision='bf16',language='Chinese',seed=seed,instruct='',attention='auto',unload_model_after_generate=True,custom_model_path=str(model)),
               '2':node('SaveAudioMP3',audio=['1',0],filename_prefix='director-studio/tts',quality='V0')}
    elif profile=='music':
        graph={
            '1':node('CheckpointLoaderSimple',ckpt_name=model_name(metadata,'CheckpointLoaderSimple','ckpt_name','ace_step_1.5_turbo_aio.safetensors')),
            '2':node('TextEncodeAceStepAudio1.5',clip=['1',1],tags=prompt,lyrics='[Instrumental]',seed=seed,bpm=100,duration=duration,timesignature='4',language='unknown',keyscale='C major',generate_audio_codes=False,cfg_scale=2.0,temperature=.85,top_p=.9,top_k=0,min_p=0.0),
            '3':node('EmptyAceStep1.5LatentAudio',seconds=duration,batch_size=1),
            '4':node('ConditioningZeroOut',conditioning=['2',0]),
            '5':node('ModelSamplingAuraFlow',model=['1',0],shift=3.0),
            '6':node('KSampler',model=['5',0],positive=['2',0],negative=['4',0],latent_image=['3',0],seed=seed,steps=8,cfg=1.0,sampler_name='euler',scheduler='simple',denoise=1.0),
            '7':node('VAEDecodeAudio',samples=['6',0],vae=['1',2]),
            '8':node('SaveAudioMP3',audio=['7',0],filename_prefix='director-studio/music',quality='128k')}
    else:
        raise ValueError('未知生成能力')
    missing=[v['class_type'] for v in graph.values() if v['class_type'] not in metadata]
    if missing:
        raise ValueError('缺少节点：'+', '.join(missing))
    return graph


def submit(graph,task_id):
    with SUBMISSION_LOCK:
        from .jobs import CANCEL
        base=str(task_id).split('-')[0]
        while True:
            if task_id in CANCEL or base in CANCEL:raise InterruptedError('已取消，未提交 ComfyUI')
            queued=request('GET','/queue')
            if not queued.get('queue_running') and not queued.get('queue_pending'):break
            time.sleep(.5)
        graph=retained_graph(graph)
        workflow_files.save_submission(graph)
        result=request('POST','/prompt',json={'prompt':graph,'client_id':'director-studio-'+task_id})
        if result.get('node_errors'):
            raise ValueError(json.dumps(result['node_errors'],ensure_ascii=False))
        return result['prompt_id']


def wait_result(task,cancelled):
    from .comfy_progress import monitor
    with monitor(task):
        outputs=_wait_result(task,cancelled)
    state=task.get('comfy_progress')
    if state:
        state.update(status='completed',phase='输出已完成',current=None,total=None,percent=None)
        for row in state.get('stages',[]):row.update(current=row['total'],percent=100)
    return outputs


def _wait_result(task,cancelled):
    # Receipt is persisted before waiting; a restart can reattach instead of duplicating.
    started=time.time()
    while time.time()-started<7200:
        if cancelled():
            queue=request('GET','/queue')
            pending=[str(x[1]) for x in queue.get('queue_pending',[])]
            running=[str(x[1]) for x in queue.get('queue_running',[])]
            if task['prompt_id'] in pending:
                request('POST','/queue',json={'delete':[task['prompt_id']]})
                raise InterruptedError('已取消排队任务')
            if running==[task['prompt_id']]:
                request('POST','/interrupt',json={'prompt_id':task['prompt_id']})
                raise InterruptedError('已取消本工作台正在执行的任务')
            raise InterruptedError('已取消本任务，停止结果回填')
        history=request('GET','/history/'+task['prompt_id'])
        item=history.get(task['prompt_id'])
        if item:
            status=item.get('status',{})
            if status.get('status_str')=='error':
                details=[m[1] for m in status.get('messages',[]) if m[0]=='execution_error']
                error=details[-1] if details else {}
                raise ValueError('ComfyUI '+str(error.get('node_type',''))+' 执行失败：'+str(error.get('exception_message',status.get('status_str')))[:1000])
            outputs=[]
            final_nodes=task.get('options',{}).get('final_output_nodes')
            for node_id,value in item.get('outputs',{}).items():
                if final_nodes and str(node_id) not in final_nodes:continue
                for key in ('images','gifs','audio','videos'):
                    outputs.extend({**output,'node_id':node_id} for output in value.get(key,[]))
            if not outputs:
                raise ValueError('工作流执行完成，但没有保存媒体输出')
            return outputs
        time.sleep(1)
    raise TimeoutError('生成超时，可根据保存的 prompt_id 恢复任务')


def download(output):
    original=output['filename']
    name=store.uid()+Path(original).suffix.lower()
    with httpx.Client(timeout=120,trust_env=False) as client:
        response=client.get(url()+'/view',params={k:output.get(k,'') for k in ('filename','subfolder','type')})
        response.raise_for_status()
        store.media_path(name).write_bytes(response.content)
    return name
