"""Two-stage, resumable character reference creation from adopted artwork."""
import copy,json,re,time
from pathlib import Path
from . import comfy,store,workflow_files

GRID=workflow_files.ROOT/'角色图8宫格keyrole-image_qwen_image_storyboard_2kupscale_character_data.json'
MOD=workflow_files.ROOT/'角色图mod_refmod.json'
ARTIFACTS=Path(r'D:\2video\codex\owl-character-mod-20261014\generated')

def current(asset):
    value=asset.get('character_mod') or {}
    if asset.get('kind')!='character' or value.get('status')!='ready' or value.get('source_media')!=asset.get('adopted'):return None
    name=value.get('name','')
    if not isinstance(name,str) or '..' in Path(name).parts:return None
    path=(comfy.MODEL_ROOT/'refmods'/name).with_suffix('.safetensors')
    if not name or not path.is_relative_to(comfy.MODEL_ROOT/'refmods') or not path.is_file():return None
    return value

def prepare(project,target,options):
    asset=next((a for a in project['assets'] if a['id']==target),None)
    if not asset or asset.get('kind')!='character' or not asset.get('adopted'):raise ValueError('请先采用一张角色图片，再制作角色 mod')
    if options.get('source_media')!=asset['adopted']:raise store.Conflict('已采用角色图片发生变化，请重新制作')
    if any(t.get('kind')=='character_mod' and t.get('project_id')==project['id'] and t.get('target')==target and t.get('status') in ('queued','running') for t in store.task_list()):raise ValueError('该角色的 mod 正在制作，请等待当前任务')
    store.media_path(asset['adopted'])
    return {**options,'source_media':asset['adopted']}

def to_api(path,metadata,roots):
    w=json.loads(path.read_text(encoding='utf-8-sig'))
    nodes={str(n['id']):n for n in w['nodes']};links={l[0]:l for l in w['links']}
    setters={n['widgets_values'][0]:n for n in w['nodes'] if n['type']=='SetNode'}
    graph={}
    def origin(link):
        seen=set()
        while True:
            key=str(link[1]);n=nodes[key]
            if key in seen:raise ValueError('角色工作流变量或旁路线循环')
            seen.add(key)
            if n['type']=='GetNode':
                setter=setters[n['widgets_values'][0]]
                link=links[next(i['link'] for i in setter['inputs'] if i.get('link'))]
            elif n['type']=='SetNode' or n.get('mode')==4:
                link=links[next(i['link'] for i in n['inputs'] if i.get('link') and i['type']==link[5])]
            else:return [key,link[2]]
    def collect(key):
        if key in graph:return
        n=nodes[key];kind=n['type']
        if kind not in metadata:raise ValueError('角色工作流缺少节点：'+kind)
        fields={**metadata[kind]['input'].get('required',{}),**metadata[kind]['input'].get('optional',{})}
        values=dict(n.get('widgets_values_named') or {})
        if not values:
            names=[i['widget']['name'] for i in n.get('inputs',[]) if i.get('widget')]
            values=dict(zip(names,n.get('widgets_values',[])))
        values={name:value for name,value in values.items() if name in fields}
        graph[key]=comfy.node(kind,**values)
        for item in n.get('inputs',[]):
            if item.get('link') not in links:continue
            name=item['name']
            if kind=='TextEncodeQwenImage21' and name=='image':name='images.image_1'
            source=origin(links[item['link']]);values[name]=source;collect(source[0])
        # node() constructs its own dict; publish the resolved input values.
        graph[key]['inputs']=values
        for name,field in fields.items():
            if name in values or field[0]=='COMFY_AUTOGROW_V3':continue
            if name in metadata[kind]['input'].get('required',{}) and len(field)>1 and 'default' in field[1]:values[name]=field[1]['default']
        if kind in ('UNETLoader','CLIPLoader','VAELoader','LoraLoaderModelOnly'):
            name={'UNETLoader':'unet_name','CLIPLoader':'clip_name','VAELoader':'vae_name','LoraLoaderModelOnly':'lora_name'}[kind]
            values[name]=comfy.model_name(metadata,kind,name,Path(values[name].replace('\\','/')).name)
    for key in roots:collect(str(key))
    return graph

def grid_graph(asset,seed,metadata):
    g=to_api(GRID,metadata,['521'])
    g['494']['inputs']['image']=comfy.upload(asset['adopted'])
    for i,n in enumerate(g.values()):
        if n['class_type']=='KSampler':n['inputs']['seed']=(seed+i)%18446744073709551615
    g['521']['inputs']['filename_prefix']='owl/character-mod/views'
    return g

def mod_graph(folder,name,subfolder,metadata):
    g=to_api(MOD,metadata,['7'])
    g['4']['inputs'].update(folder=str(folder),max_items=8)
    g['3']['inputs'].update(name=name,subfolder=subfolder,save=True)
    # Extraction is unchanged; avoid decoding an unused full-video preview.
    g['5']['inputs']['preview']='off'
    return g

def validate_file(path):
    from safetensors import safe_open
    with safe_open(str(path),framework='pt',device='cpu') as f:
        meta=json.loads((f.metadata() or {}).get('refmod_meta','{}'))
        if meta.get('kind')!='video':raise ValueError('角色 mod 没有保存为多视角 video 参考，请检查八张图与提取参数')
    return meta

def execute(task,cancelled,on_submitted=None):
    from .jobs import progress,mutate_task,check_cancelled
    opts=task['options'];pid=task['project_id'];aid=task['target']
    def asset_now():
        p=store.get_project(pid);a=next((a for a in p['assets'] if a['id']==aid),None)
        if not a or a.get('adopted')!=opts['source_media']:raise store.Conflict('采用图已更换，停止旧角色 mod 制作；请按新图重新制作')
        return a
    a=asset_now();metadata=comfy.info()
    if opts.get('grid_prompt_id') and on_submitted:on_submitted()
    folder=ARTIFACTS/task['id']/'views';folder.mkdir(parents=True,exist_ok=True)
    def submit_stage(stage,graph,outputs):
        check_cancelled(task);asset_now()
        workflow_files.write_json(workflow_files.API/'角色mod'/f'{task["id"]}-{stage}.json',graph)
        receipt=comfy.submit(graph,task['id']+'-'+stage)
        opts[stage+'_prompt_id']=receipt;task['prompt_id']=receipt;opts['final_output_nodes']=outputs
        store.task_save(task)
        if on_submitted:on_submitted()
        return receipt
    if not opts.get('grid_prompt_id'):
        progress(task,'正在生成角色八视图并逐张放大')
        submit_stage('grid',grid_graph(a,opts['seed'],metadata),['521'])
    if not opts.get('views_ready'):
        progress(task,'等待角色八视图及放大结果')
        outputs=comfy.wait_result({**task,'prompt_id':opts['grid_prompt_id'],'options':{**opts,'final_output_nodes':['521']}},cancelled)
        if len(outputs)!=8:raise ValueError(f'角色八视图工作流输出了 {len(outputs)} 张图，要求恰好八张；未制作 mod')
        for i,output in enumerate(outputs):
            check_cancelled(task)
            name=comfy.download(output)
            (folder/f'{i+1:02d}.png').write_bytes(store.media_path(name).read_bytes())
        opts['views_ready']=True;store.task_save(task)
    name='owl_'+re.sub(r'[^a-zA-Z0-9_-]','_',aid)+'_'+task['id']
    subfolder='character/owl/'+re.sub(r'[^a-zA-Z0-9_-]','_',pid)
    path=comfy.MODEL_ROOT/'refmods'/subfolder/(name+'.safetensors')
    if not opts.get('mod_prompt_id'):
        progress(task,'八视图已完成，正在提取并保存角色 mod')
        submit_stage('mod',mod_graph(folder,name,subfolder,metadata),['7'])
    comfy.wait_result({**task,'prompt_id':opts['mod_prompt_id'],'options':{**opts,'final_output_nodes':['7']}},cancelled)
    check_cancelled(task);asset_now()
    if not path.is_file():raise ValueError('提取任务完成，但对应角色 mod 文件未保存')
    meta=validate_file(path)
    def apply(project):
        asset=next(a for a in project['assets'] if a['id']==aid)
        if asset.get('adopted')!=opts['source_media']:raise store.Conflict('角色采用图已改变，未绑定旧 mod')
        asset['character_mod']={'status':'ready','name':subfolder+'/'+name,'source_media':opts['source_media'],
                                'kind':'video','task_id':task['id'],'created':time.time(),'views_folder':str(folder),
                                'token_count':meta.get('token_count'),'path':str(path)}
    saved=mutate_task(task,apply);task['project_revision']=saved['revision'];task['completion_message']='mod 已制作'

def video_nodes(reference,metadata,video_vae,start):
    value=reference['refmod'];name=value['name']
    fields=metadata['MiniMaxH3RefModsLoader']['input']['required']
    inputs={}
    for key,field in fields.items():
        setting=field[1] if len(field)>1 else {}
        inputs[key]=setting.get('default',field[0][0] if isinstance(field[0],list) else False if field[0]=='BOOLEAN' else 1)
    inputs['mod_1']=name;inputs['strength_1']=1;inputs['copies_1']=1
    for i in range(2,9):inputs['mod_'+str(i)]='(none)'
    loader=str(start);inspect=str(start+1)
    return {loader:comfy.node('MiniMaxH3RefModsLoader',**inputs),
            inspect:comfy.node('MiniMaxH3RefModInspect',mods=[loader,0],vae=video_vae,index=0,preview='stored',strength=1,visual_preview='full_video')},[inspect,1]
