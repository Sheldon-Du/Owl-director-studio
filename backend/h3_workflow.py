"""Bind reviewed H3 prompts to the user's local, self-voiced H3 workflow."""
import copy
import json
import re
import math
import os
from pathlib import Path
from zipfile import ZipFile
from . import comfy,h3,store,video_versions,workflow_files,character_mod

SOURCE=workflow_files.ROOT/'高质量数字人-minimaxh3-自行生成声音.json'
AUDIO_SOURCE=SOURCE.with_name('高质量数字人-minimaxh3.json')


def tile_plan(seconds):
    # Use actual sampled length; keep spatial context consistent at 1080P.
    if seconds>25:return 3,2
    if seconds>15:return 2,2
    return 1,2


def sampling_profile(project,step,options):
    shots=[s for s in project.get('shots',[]) if s['id'] in step.get('source_shot_ids',[])]
    text=' '.join(str(s.get(k,'')) for s in shots for k in ('description','prompt'))+' '+step.get('prompt','')
    motion=options.get('motion') or (shots[0].get('h3_motion','auto') if shots else 'auto')
    texture=options.get('texture') or (shots[0].get('h3_texture','auto') if shots else 'auto')
    high=motion=='high' or motion=='auto' and bool(re.search(r'追逐|打斗|搏斗|爆炸|奔跑|高速|激烈|chase|fight|explosion|sprint',text,re.I))
    drama=texture=='on' or texture=='auto' and not high and bool(re.search(r'文戏|对白|对话|交谈|独白|dialogue|conversation|r34l1sm',text,re.I))
    return {'high_motion':high,'drama_texture':drama,'motion':motion,'texture':texture}

def recalled_seed(project,step,scope_shot=None):
    outputs=step.get('outputs',[]) or [m for s in project.get('shots',[]) if s['id'] in step.get('source_shot_ids',[]) for m in s.get('outputs',[]) if m.get('h3_step')==step['index']]
    latest=next((m for m in reversed(outputs) if m.get('seed') is not None),None)
    if latest:return int(latest['seed'])
    history=[t for t in store.task_list() if t['project_id']==project['id'] and t['kind'] in ('h3_generate','export') and t['status'] in ('queued','running','completed') and str(t.get('target'))==str(step['index']) and t.get('options',{}).get('scope_shot')==scope_shot and (t['kind']!='export' or t.get('options',{}).get('format')=='h3_workflow') and t.get('options',{}).get('seed') is not None]
    return int(max(history,key=lambda t:t.get('created',0))['options']['seed']) if history else None


def sampling_seconds(duration):
    # Installed Easy node rounds to 17*n+5 frames at 24fps. Request the next
    # grid point to avoid cutting a natural action short; deliver at normal speed.
    frames=math.ceil((max(4,duration)*24-5)/17)*17+5
    return min(30,frames/24)


def current_step(project,index,shot_id=None):
    package=h3.package(project,shot_id)
    if not h3.is_current(project,package,shot_id):raise ValueError('H3 提示词来源已改变，请重新转写后生成视频')
    h3.groups(h3.scope(project,shot_id))
    step=next((s for s in package['steps'] if s['index']==int(index)),None)
    if not step:raise ValueError('H3 提示词任务不存在')
    return step


def template(source=None):
    source=source or SOURCE
    if not source.exists():raise ValueError('指定 H3 工作流不存在：'+str(source))
    return json.loads(source.read_text(encoding='utf-8-sig'))


def describe():
    try:
        metadata=comfy.info();workflow=template();graph=to_api(workflow,metadata,42)
        graph=prune(graph,['434']);validate_graph(graph,metadata)
        node=next(n for n in graph.values() if n['class_type']=='MiniMaxH3Easy')
        fields=metadata['MiniMaxH3Easy']['input']['required']
        return {'ready':True,'name':SOURCE.stem,'source':str(SOURCE),'audio_workflow':AUDIO_SOURCE.stem,'audio_source':str(AUDIO_SOURCE),'supports_bound_audio':AUDIO_SOURCE.is_file(),'max_seconds':fields['seconds'][1]['max'],'resolutions':['540P'],'default_resolution':'540P','default_quality':'first','generates_audio':True}
    except Exception as error:
        return {'ready':False,'name':SOURCE.stem,'source':str(SOURCE),'error':str(error)}


def widgets(node):
    values=node.get('widgets_values',[])
    if isinstance(values,dict):return dict(values)
    if node['type']=='MiniMaxH3Easy' and len(values)>2 and values[2] is None:values=[*values[:2],*values[3:]]
    if node.get('properties',{}).get('owl_widget_names'):return {k:v for k,v in zip(node['properties']['owl_widget_names'],values) if k}
    if node['type']=='MinimaxH3LatentUpscaler3D':
        if len(values)==8:
            return dict(zip(('model_name','mode','mode.scale','align','enable_temporal_chunking','force_unload','device','precision'),values))
        # The source predates two new switches in the installed node schema.
        return {'model_name':values[0],'mode':values[1],'mode.scale':values[2],'align':values[3],'device':values[4],'precision':values[5],'enable_temporal_chunking':values[6],'force_unload':True}
    names=[i['widget']['name'] for i in node.get('inputs',[]) if i.get('widget')]
    return dict(zip(names,values))


def to_api(workflow,metadata,seed):
    links={link[0]:link for link in workflow['links']}
    nodes={n['id']:n for n in workflow['nodes']}
    def origin(link):
        visited=set()
        while nodes.get(link[1],{}).get('mode')==4:
            if link[1] in visited:raise ValueError('工作流旁路连接循环')
            visited.add(link[1]);node=nodes[link[1]]
            compatible=[i for i in node.get('inputs',[]) if i.get('link') in links and i.get('type')==link[5]]
            if len(compatible)!=1:raise ValueError('无法解析旁路节点：'+node['type'])
            link=links[compatible[0]['link']]
        return link
    graph={}
    ignored={'Note','MarkdownNote','Fast Groups Bypasser (rgthree)'}
    for n in workflow['nodes']:
        if n['type'] in ignored or n.get('mode') in (2,4) or n['type']=='Seed (rgthree)':continue
        if n['type'] not in metadata:raise ValueError('ComfyUI 缺少工作流节点：'+n['type'])
        inputs=widgets(n)
        for item in n.get('inputs',[]):
            link=links.get(item.get('link'))
            if link:
                link=origin(link)
                inputs[item['name']]=seed if link[1]==436 else [str(link[1]),link[2]]
        # LoadImage's upload button is not an API input.
        inputs.pop('upload',None)
        inputs.pop('audioUI',None)
        if n['type']=='MiniMaxH3Easy':
            inputs['mode']={'参考生视频':'reference','图生视频':'image','数字人':'digital_human'}.get(inputs.get('mode'),inputs.get('mode'))
            inputs['keyframe_role']={'首帧优先':'first','尾帧优先':'last'}.get(inputs.get('keyframe_role'),inputs.get('keyframe_role'))
            inputs['reference_mention_mode']={'按序号':'index','按文件名':'filename'}.get(inputs.get('reference_mention_mode'),inputs.get('reference_mention_mode'))
            inputs['ref_image_size']={'原图（不缩放）':'original'}.get(inputs.get('ref_image_size'),inputs.get('ref_image_size','1k'))
            if inputs.get('prompt_optimizer_scene_guide') not in metadata[n['type']]['input']['required']['prompt_optimizer_scene_guide'][0]:inputs['prompt_optimizer_scene_guide']='none'
            inputs.setdefault('prompt_optimizer_settings',False)
            fields=metadata[n['type']]['input']
            inputs={k:v for k,v in inputs.items() if k in fields.get('required',{}) or k in fields.get('optional',{})}
        graph[str(n['id'])]={'class_type':n['type'],'inputs':inputs}
    return graph


def prune(graph,outputs):
    needed=set()
    def visit(key):
        if key in needed:return
        if key not in graph:raise ValueError('H3 工作流连接缺失：'+key)
        needed.add(key)
        for value in graph[key]['inputs'].values():
            if isinstance(value,list) and len(value)==2 and isinstance(value[0],str) and isinstance(value[1],int):visit(value[0])
    for key in outputs:visit(key)
    return {k:v for k,v in graph.items() if k in needed}



def bind_audio_drive(graph,metadata,audio_source):
    """Lock supplied audio in the main AV latent with the installed native node."""
    kind='VRGDG_MiniMaxH3AudioDrive'
    if kind not in metadata:raise ValueError('缺少音频驱动节点 VRGDG_MiniMaxH3AudioDrive，请安装并重启 ComfyUI')
    key='4900'
    if key in graph:raise ValueError('音频驱动节点编号冲突：'+key)
    graph[key]=comfy.node(kind,av_latent=['211',1],source_audio=audio_source,audio_vae=['211',3])
    graph['337']['inputs']['latent_image']=[key,0]
    graph['434']['inputs']['audio']=[key,1]
    return key


def filled(project,index,options=None):
    options=options or {};step=current_step(project,index,options.get('scope_shot'));metadata=comfy.info();bound_audio=bool(step.get('audio_binding'));source=AUDIO_SOURCE if bound_audio else SOURCE;workflow=template(source)
    quality=options.get('quality','first')
    if quality!='first':raise ValueError('导演台仅开启一采，二采请在后期工作流中执行')
    graph=to_api(workflow,metadata,int(options.get('seed',42)))
    easy_nodes=[(k,n) for k,n in graph.items() if n['class_type']=='MiniMaxH3Easy']
    if len(easy_nodes)!=1:raise ValueError('指定工作流必须有一个 MiniMaxH3Easy 提示词入口')
    easy_id,easy=easy_nodes[0];inputs=easy['inputs'];limits=metadata['MiniMaxH3Easy']['input']['required']
    if not 0<step['duration']<=limits['seconds'][1].get('max',30):raise ValueError('提示词任务时长超出本地 H3 节点范围')
    resolution=options.get('resolution','540P')
    if resolution!='540P':raise ValueError('导演台只生成540P预览视频')
    if resolution not in limits['resolution'][0]:raise ValueError('本地 H3 节点缺少540P分辨率')
    ratio=str(project.get('parameters',{}).get('画幅比例','16:9')).split(' ')[0]
    if ratio not in limits['aspect_ratio'][0]:raise ValueError('本地 H3 不支持该画幅，请修改项目画幅')
    from . import h3_reference_limits
    refs=step['references'];h3_reference_limits.validate_media(refs,extra_audio=int(bound_audio));mapping={};image_count=0;video_count=0;audio_count=0
    for r in refs:
        if r.get('refmod'):
            video_count+=1;mapping[r['label']]=f'<Video {video_count}>'
        elif r.get('media_type')=='audio':
            audio_count+=1;mapping[r['label']]=f'<Audio {audio_count}>'
        else:
            image_count+=1;mapping[r['label']]=f'<Picture {image_count}>'
    # Independent ComfyUI jobs bind their own consecutive image slots. Keep a
    # mapping to the stable project labels, without changing the saved prompt.
    profile=sampling_profile(project,step,options)
    if profile['high_motion']:graph['338']['inputs']['steps']=8
    prompt=re.sub(r'<(?:Picture|Video|Audio) \d+>',lambda m:mapping.get(m.group(),m.group()),step['prompt'])
    if profile['drama_texture']:prompt='r34l1sm\n'+re.sub(r'^\s*r34l1sm\s*','',prompt)
    # Character identity instructions are part of the reviewed prompt, already budgeted.
    h3_reference_limits.validate_prompt(prompt)
    inputs.update(prompt=prompt,seconds=sampling_seconds(step['duration']),fps=24,resolution=resolution,aspect_ratio=ratio,mode='reference' if step['mode']=='Ref2VA' else 'image',keyframe_role='last' if step['mode']=='L2VA' else 'first',reference_mention_mode='index',prompt_optimizer_settings=False,prompt_optimizer_prompt_connected=True)
    for key in list(inputs):
        if key=='media' or re.fullmatch(r'media_(?:type_)?\d+',key):inputs.pop(key)
    uploaded=[]
    for i,r in enumerate(refs,1):
        if r.get('refmod'):
            adapter=graph['365']['inputs'];nodes,source_link=character_mod.video_nodes(r,metadata,adapter['video_vae'],10000+i*2)
            graph.update(nodes)
            inputs['media_'+str(i)]=source_link;inputs['media_type_'+str(i)]='video';inputs['mode']='reference'
            uploaded.append({'project_label':r['label'],'workflow_label':mapping[r['label']],'media':r['media'],'refmod':r['refmod'],
                             'media_type':'video','source_slot':source_link[1],'node_id':int(source_link[0])})
            continue
        path=store.media_path(r['media'])
        if not path.exists():raise ValueError('H3 参考素材缺失：'+r['media'])
        name=comfy.upload(r['media']);key=str(900+i)
        kind=r.get('media_type','image')
        graph[key]=comfy.node('LoadAudio',audio=name) if kind=='audio' else comfy.node('LoadImage',image=name)
        inputs['media_'+str(i)]=[key,0];inputs['media_type_'+str(i)]=kind
        if kind=='audio':inputs['mode']='reference'
        uploaded.append({'project_label':r['label'],'workflow_label':mapping[r['label']],'media':r['media'],'comfy_input':name,'media_type':kind,'node_id':int(key)})
    clips=next(s['clips'] for s in h3.groups(h3.scope(project,options.get('scope_shot'))) if s['index']==step['index'])
    audio_binding=None
    if bound_audio:
        from . import speech_audio
        audio_binding=speech_audio.step_audio(project,clips,step['duration'],inputs['seconds'])
        audio_name=comfy.upload(audio_binding['media'])
        graph['468']=comfy.node('LoadAudio',audio=audio_name)
        # Explicitly activate trimming rather than leave the user's bypassed
        # node dangling. Pad to the H3 frame grid, then trim delivery normally.
        graph['467']=comfy.node('TrimAudioDuration',audio=['468',0],start_index=0,duration=inputs['seconds'])
        inputs['media_'+str(len(refs)+1)]=['467',0];inputs['media_type_'+str(len(refs)+1)]='audio';inputs['mode']='reference'
        drive_id=bind_audio_drive(graph,metadata,['467',0])
        audio_binding.update(comfy_input=audio_name,node_id=468,audio_drive_node=int(drive_id),audio_drive_type='VRGDG_MiniMaxH3AudioDrive')
    for key in ('406','434'):
        if key in graph:
            graph[key]['inputs'].update(filename_prefix=f'director-studio/H3-step-{step["index"]}-'+('second' if key=='406' else 'first'),save_output=True,trim_to_audio=False,save_metadata=True)
    graph=prune(graph,['434'])
    validate_graph(graph,metadata)
    # Return a GUI workflow as well as the executable API graph.
    gui=copy.deepcopy(workflow)
    for n in gui['nodes']:
        if n['id']==346 and profile['high_motion']:
            names=[i['widget']['name'] for i in n.get('inputs',[]) if i.get('widget')]
            n['widgets_values'][names.index('step')]=6
        if str(n['id']) in graph and n['id']!=197:
            api_inputs=graph[str(n['id'])]['inputs']
            if isinstance(n.get('widgets_values'),dict):n['widgets_values'].update({k:v for k,v in api_inputs.items() if not isinstance(v,list)})
            elif n['type']=='MinimaxH3LatentUpscaler3D':n['widgets_values']=[api_inputs[k] for k in ('model_name','mode','mode.scale','align','enable_temporal_chunking','force_unload','device','precision')]
            else:
                names=[i['widget']['name'] for i in n.get('inputs',[]) if i.get('widget')]
                for i,key in enumerate(names):
                    if key in api_inputs and not isinstance(api_inputs[key],list):n['widgets_values'][i]=api_inputs[key]
        if str(n['id'])==easy_id:
            old_values=widgets(n);old_values.update({k:v for k,v in inputs.items() if not isinstance(v,list)})
            n['widgets_values']=[old_values[i['widget']['name']] for i in n['inputs'] if i.get('widget')]
            n.setdefault('properties',{})['minimax_h3_virtual_media_links']=[{'media_type':r.get('media_type','image'),'source_slot':r.get('source_slot',0),'source_type':'AUDIO' if r.get('media_type')=='audio' else 'IMAGE','source_id':r['node_id'],'order':i+1} for i,r in enumerate(uploaded)]
            n['properties']['feihou_h3_embedded_media']=[]
        elif n['id']==436:n['widgets_values'][0]=int(options.get('seed',42))
        elif n['id'] in (406,434):n['widgets_values'].update(graph.get(str(n['id']),{'inputs':{}})['inputs'])
        if quality=='first' and n['id'] in (288,289,346,349,350,357,448,478,295,481,406) and not n['type'].startswith('Select'):n['mode']=2
    for i,r in enumerate(uploaded):
        if r.get('refmod') or r.get('media_type')=='audio':continue
        gui['nodes'].append({'id':r['node_id'],'type':'LoadImage','pos':[-500,50+i*320],'size':[300,270],'flags':{},'order':i,'mode':0,'inputs':[],'outputs':[{'name':'IMAGE','type':'IMAGE','links':None},{'name':'MASK','type':'MASK','links':None}],'properties':{'Node name for S&R':'LoadImage'},'widgets_values':[r['comfy_input'],'image']})
    if video_count:
        from . import tts_workflow
        extra=tts_workflow.gui(graph,metadata)
        originals={n['id'] for n in gui['nodes']}
        for n in extra['nodes']:
            if n['id']>=10000 and n['id'] not in originals:gui['nodes'].append(n)
        existing_links={l[0] for l in gui['links']};next_link=max(existing_links,default=0)+1
        for l in extra['links']:
            if l[3]<10000:continue
            copied=[next_link,*l[1:]];next_link+=1;gui['links'].append(copied)
            target=next(n for n in gui['nodes'] if n['id']==l[3]);target['inputs'][l[4]]['link']=copied[0]
        gui['last_link_id']=next_link-1
        # Rebuild outgoing links on new nodes using remapped GUI link IDs.
        for n in gui['nodes']:
            for output in n.get('outputs',[]):output['links']=[]
        for l in gui['links']:
            source=next(n for n in gui['nodes'] if n['id']==l[1]);source['outputs'][l[2]]['links'].append(l[0])
    gui['last_node_id']=max(gui['last_node_id'],900+len(uploaded),*(r['node_id'] for r in uploaded))
    gui['nodes']=[n for n in gui['nodes'] if n['id'] not in (465,466)]
    if bound_audio or audio_count:
        from . import tts_workflow
        # Keep dormant second-pass nodes in the GUI for later fixed-seed replay.
        gui_nodes=tts_workflow.gui(graph,metadata)
        active_ids={n['id'] for n in gui_nodes['nodes']}
        dormant=[n for n in gui['nodes'] if n['id'] not in active_ids and n['id'] not in (465,466)]
        dormant_ids={n['id'] for n in dormant}
        offset=gui_nodes['last_link_id']
        extra_links=[l for l in gui['links'] if l[3] in dormant_ids]
        for l in extra_links:l[0]+=offset
        link_map={l[0]-offset:l[0] for l in extra_links}
        for n in dormant:
            for i in n.get('inputs',[]):
                if i.get('link') in link_map:i['link']=link_map[i['link']]
            for out in n.get('outputs',[]):out['links']=[link_map[x] for x in (out.get('links') or []) if x in link_map]
        for l in extra_links:
            n=next((n for n in gui_nodes['nodes'] if n['id']==l[1]),None)
            if n:n['outputs'][l[2]]['links'].append(l[0])
        gui_nodes['nodes']+=dormant;gui_nodes['links']+=extra_links
        gui_nodes['last_node_id']=max(n['id'] for n in gui_nodes['nodes']);gui_nodes['last_link_id']=max(l[0] for l in gui_nodes['links'])
        gui=gui_nodes
        easy_gui=next(n for n in gui['nodes'] if str(n['id'])==easy_id)
        easy_gui['properties']['minimax_h3_virtual_media_links']=[{'media_type':r.get('media_type','image'),'source_slot':r.get('source_slot',0),'source_type':'AUDIO' if r.get('media_type')=='audio' else 'IMAGE','source_id':r['node_id'],'order':i+1} for i,r in enumerate(uploaded)]+([{'media_type':'audio','source_slot':0,'source_type':'AUDIO','source_id':467,'order':len(uploaded)+1}] if bound_audio else [])
    return {'sampling_profile':profile,'graph':graph,'workflow':gui,'scope_shot':options.get('scope_shot'),'step':step,'clips':clips,'references':uploaded,'audio_binding':audio_binding,'quality':quality,'resolution':resolution,'seed':int(options.get('seed',42)),'source':str(source),'sampling_seconds':inputs['seconds'],'delivery_seconds':step['duration'],'delivery_fps':24}


def validate_graph(graph,metadata):
    for key,n in graph.items():
        fields=metadata[n['class_type']]['input'];required=fields.get('required',{})
        for name,field in required.items():
            if name not in n['inputs']:raise ValueError('工作流缺少必需输入：'+n['class_type']+'.'+name)
            value=n['inputs'][name]
            if isinstance(value,list):continue
            if (n['class_type'],name) in (('LoadImage','image'),('LoadAudio','audio')):continue  # uploaded after metadata snapshot
            options=field[0] if isinstance(field[0],list) else field[1].get('options',[]) if len(field)>1 and field[0]=='COMBO' else []
            if options and value not in options:
                matches=[v for v in options if isinstance(v,str) and Path(v.replace('\\','/')).name==Path(str(value).replace('\\','/')).name] if name.endswith('_name') else []
                if len(matches)==1:n['inputs'][name]=matches[0]
                else:raise ValueError('工作流参数或模型不可用：'+n['class_type']+'.'+name+' = '+str(value))


def saved_snapshot(project,snapshot,index=None):
    """Export the exact generated version even after prompts have changed."""
    records=list(project.get('media',[]))
    records.extend(m for shot in project.get('shots',[]) for m in shot.get('outputs',[]))
    documents=project.get('documents',{})
    for package in [documents.get('h3',{}),*documents.get('h3_shots',{}).values()]:
        records.extend({**m,'h3_step':step['index']} for step in package.get('steps',[]) for m in step.get('outputs',[]))
    matches=[m for m in records if m.get('workflow_snapshot')==snapshot and m.get('h3_step') is not None]
    if not matches:raise ValueError('生成工作流快照不属于该项目的视频任务')
    data=json.loads(store.media_path(snapshot).read_text(encoding='utf-8'))
    saved=next((m for m in matches if m.get('seed')==data.get('seed') and m['h3_step']==data.get('step',{}).get('index')),None)
    if not saved or (index is not None and int(index)!=data['step']['index']):raise ValueError('生成工作流快照与视频记录不一致')
    if (data.get('quality'),data.get('resolution')) not in (('first','480P'),('first','540P'),('second','1080P')):raise ValueError('导演台只导出540P一采、历史480P一采或1080P二采快照')
    if saved.get('quality','first')!=data['quality'] or saved.get('resolution','480P')!=data['resolution']:raise ValueError('生成工作流快照的采样规格与视频记录不一致')
    return data


def upscale_source(project,sid,output_id):
    output=video_versions.adopted(project,sid,output_id)
    if output.get('quality')!='first' or output.get('resolution') not in ('480P','540P') or output.get('seed') is None or not output.get('workflow_snapshot'):
        raise ValueError('二采需要采用带固定种子和工作流快照的 H3 一采视频')
    data=saved_snapshot(project,output['workflow_snapshot'],output.get('h3_step'))
    if data['quality']!='first':raise ValueError('二采来源必须为一采视频')
    if sid not in data['step'].get('source_shot_ids',[]):raise ValueError('工作流快照未绑定本镜')
    return output,data


def sync_gui(gui,graph):
    """Persist executable widget values, including newer installed widgets."""
    for n in gui['nodes']:
        api=graph.get(str(n['id']))
        if not api:continue
        inputs=api['inputs']
        if n['type']=='LoadImage':n['widgets_values'][0]=inputs['image']
        elif n['type']=='MinimaxH3LatentUpscaler3D':
            names=('model_name','mode','align','enable_temporal_chunking','force_unload','device','precision')
            n['inputs']=[i for i in n['inputs'] if not i.get('widget')]+[{'name':k,'type':'*','widget':{'name':k},'link':None} for k in names]
            n['widgets_values']=[inputs[k] for k in ('model_name','mode','mode.scale','align','enable_temporal_chunking','force_unload','device','precision')]
        elif isinstance(n.get('widgets_values'),dict):
            n['widgets_values'].update({k:v for k,v in inputs.items() if not isinstance(v,list)})
        else:
            if n['type']=='GoohaiMinimaxH3TiledSampler' and not any(i['name']=='time_segments' for i in n['inputs']):
                n['inputs'].append({'name':'time_segments','type':'COMBO','widget':{'name':'time_segments'},'link':None})
                n['widgets_values'].append('2 段')
            for i,key in enumerate(item['widget']['name'] for item in n.get('inputs',[]) if item.get('widget')):
                if key in inputs and not isinstance(inputs[key],list):n['widgets_values'][i]=inputs[key]


def upscaled(project,sid,output_id):
    """Replay the adopted version's first pass and activate its second branch."""
    output,saved=upscale_source(project,sid,output_id)
    data=copy.deepcopy(saved);gui=data['workflow'];metadata=comfy.info()
    fields=metadata.get('GoohaiMinimaxH3TiledSampler',{}).get('input',{})
    temporal={**fields.get('required',{}),**fields.get('optional',{})}.get('time_segments')
    choices=(temporal[0] if isinstance(temporal[0],list) else temporal[1].get('options',[])) if temporal else []
    if not all(choice in choices for choice in ('不分段','2 段','3 段')):raise ValueError('当前二采分块节点缺少时间分段参数，请更新并重启 ComfyUI')
    for n in gui['nodes']:
        if n['id'] in (288,289,346,349,350,357,448,478,295,481,406):n['mode']=0
    graph=to_api(gui,metadata,saved['seed'])
    # Exact saved models, conditioning, first-pass noise and prompt take
    # precedence over current project settings and current source workflow.
    graph.update(copy.deepcopy(saved['graph']))
    if graph['197']['inputs']['resolution']!=saved['resolution'] or graph['277']['inputs']['noise_seed']!=saved['seed']:raise ValueError('一采快照的分辨率设置或固定种子不一致')
    for r in data['references']:
        if not store.media_path(r['media']).is_file():raise ValueError('原版本参考图片缺失：'+r['media'])
        r['comfy_input']=comfy.upload(r['media'])
        if r.get('refmod'):continue
        graph[str(r['node_id'])]['inputs']['audio' if r.get('media_type')=='audio' else 'image']=r['comfy_input']
    if data.get('audio_binding'):
        binding=data['audio_binding'];binding['comfy_input']=comfy.upload(binding['media'])
        graph['468']['inputs']['audio']=binding['comfy_input'];graph['406']['inputs']['audio']=['467',0]
    temporal_chunks,spatial_chunks=tile_plan(graph['197']['inputs']['seconds'])
    factor=2 if saved['resolution']=='540P' else 2.25
    if saved.get('sampling_profile',{}).get('high_motion'):graph['346']['inputs']['step']=6
    graph['357']['inputs'].update(mode='scale by multiplier',**{'mode.scale':factor},enable_temporal_chunking=True,force_unload=False,align=32)
    graph['448']['inputs'].update(enable_tiling=True,n_tiles=spatial_chunks,tile_overlap=128,time_segments='不分段' if temporal_chunks==1 else f'{temporal_chunks} 段',refine_seams=False)
    ratio=graph['197']['inputs']['aspect_ratio'];w,h=map(int,ratio.split(':'))
    width,height=(round(1080*w/h/2)*2,1080) if w>=h else (1080,round(1080*h/w/2)*2)
    # Neural latent upscaling keeps the adopted source scale (540P: 2x). Its 32px alignment produces e.g.
    # 1088px; normalize the decoded frame to the requested 1080P delivery.
    scale_id='1901'
    graph[scale_id]=comfy.node('ImageScale',image=['295',0],upscale_method='bicubic',width=width,height=height,crop='center')
    graph['406']['inputs'].update(images=[scale_id,0],filename_prefix=f'director-studio/H3-step-{data["step"]["index"]}-second',save_output=True,trim_to_audio=False,save_metadata=True)
    graph=prune(graph,['406']);validate_graph(graph,metadata)
    old_link=next(l for l in gui['links'] if l[3]==406 and l[4]==0)
    old_link[1]=int(scale_id);old_link[2]=0
    new_link=max(l[0] for l in gui['links'])+1
    gui['links'].append([new_link,295,0,int(scale_id),0,'IMAGE'])
    gui['nodes'].append({'id':int(scale_id),'type':'ImageScale','pos':[0,0],'size':[280,150],'flags':{},'order':len(gui['nodes']),'mode':0,'inputs':[{'name':'image','type':'IMAGE','link':new_link},*({'name':k,'type':'*','widget':{'name':k},'link':None} for k in ('upscale_method','width','height','crop'))],'outputs':[{'name':'IMAGE','type':'IMAGE','links':[old_link[0]]}],'properties':{'Node name for S&R':'ImageScale'},'widgets_values':['bicubic',width,height,'center']})
    for n in gui['nodes']:
        if n['id']==295:n['outputs'][0]['links']=[new_link]
        if n['id']==434:n['mode']=2
    gui['last_node_id']=max(gui['last_node_id'],int(scale_id));gui['last_link_id']=new_link
    sync_gui(gui,graph)
    data.update(graph=graph,quality='second',resolution='1080P',first_resolution=saved['resolution'],upscale_factor=factor,temporal_chunks=temporal_chunks,spatial_chunks=spatial_chunks,output_width=width,output_height=height,source_output_id=output_id,source_video=output['media'],source_workflow_snapshot=output['workflow_snapshot'],scope_shot=sid)
    if not data.get('clips'):
        owner=video_versions.shot(project,sid)
        data['clips']=[{'source_id':sid,'start':output.get('in',0),'end':output.get('in',0)+output.get('duration',owner['duration']),'source_offset':output.get('source_offset',0)}]
    return data


def export(project,index,options=None):
    options=options or {}
    snapshot=options.get('workflow_snapshot')
    if snapshot:
        data=saved_snapshot(project,snapshot,index)
    else:
        data=filled(project,index,options)
    name=store.uid()+'.zip'
    with ZipFile(store.media_path(name),'w') as archive:
        written=set()
        def add_file(path,destination):
            destination=str(destination).replace('\\','/')
            if destination.startswith('/') or ':' in destination or '..' in Path(destination).parts:raise ValueError('工作流引用路径无效')
            if destination not in written:
                archive.write(path,destination);written.add(destination)
        archive.writestr('workflow.json',json.dumps(data['workflow'],ensure_ascii=False,indent=2))
        archive.writestr('workflow-api.json',json.dumps(data['graph'],ensure_ascii=False,indent=2))
        archive.writestr('bindings.json',json.dumps({'source':data['source'],'step':data['step']['index'],'duration':data['step']['duration'],'sampling_seconds':data.get('sampling_seconds',data['step']['duration']),'delivery_fps':24,'references':data['references'],'seed':data['seed'],'resolution':data['resolution'],'quality':data['quality']},ensure_ascii=False,indent=2))
        archive.writestr('prompt.txt',data['step']['prompt'])
        for r in data['references']:
            source=store.media_path(r['media']);add_file(source,'references/'+r['media'])
            if r.get('comfy_input'):add_file(source,'ComfyUI/input/'+r['comfy_input'])
            if r.get('refmod'):
                mod=r['refmod']['name'];folder=(comfy.MODEL_ROOT/'refmods').resolve();path=(folder/mod).with_suffix('.safetensors').resolve()
                if not path.is_relative_to(folder) or not path.is_file():raise ValueError('角色 MOD 文件缺失，无法导出完整工作流')
                add_file(path,'ComfyUI/models/refmods/'+str(path.relative_to(folder)))
        if data.get('audio_binding'):
            audio=data['audio_binding'];source=store.media_path(audio['media']);add_file(source,'references/'+audio['media'])
            if audio.get('comfy_input'):add_file(source,'ComfyUI/input/'+audio['comfy_input'])
        archive.writestr('使用说明.txt','workflow.json 为已填好的界面工作流，workflow-api.json 为 API 工作流。\n将 ComfyUI 文件夹内容合并到本机 ComfyUI 同名目录，再加载工作流。\n参考图、声音样本、角色 MOD、提示词和种子均已填入；仍需本机安装对应基础模型与节点。\n')
    return name
