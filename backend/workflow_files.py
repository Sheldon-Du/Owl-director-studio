"""Canonical location for the web app's editable ComfyUI workflows."""
import json
import os
import uuid
from pathlib import Path

ROOT=Path(r'D:\2video\ComfyUI_Mie_2026_V9.0_Large\ComfyUI\user\default\workflows\Owl')
API=ROOT/'_api'
IMPORTED=API/'imported'

def write_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    # A reader must never see half of a saved workflow.
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)

def krea2_config(metadata):
    source=ROOT/'全能角色资产制作【krea2】.json'
    workflow=json.loads(source.read_text(encoding='utf-8-sig'))
    nodes={str(n['id']):n for n in workflow['nodes']}
    links={l[0]:l for l in workflow['links']}
    graph={}
    adjustments=[]
    def collect(node_id):
        if node_id in graph:return
        n=nodes[node_id]
        if n['type'] not in metadata:raise ValueError('Krea2 工作流缺少节点：'+n['type'])
        values=dict(n.get('widgets_values_named',{}))
        values.pop('control_after_generate',None)
        graph[node_id]={'class_type':n['type'],'inputs':values}
        if node_id=='10':values['text']=''
        for item in n.get('inputs',[]):
            if item.get('link') is None or (node_id=='10' and item['name']=='text'):continue
            l=links[item['link']];upstream,slot=str(l[1]),l[2]
            seen=set()
            while nodes[upstream].get('mode')==4:
                if upstream in seen:raise ValueError('Krea2 工作流旁路线存在循环')
                seen.add(upstream)
                bypass=next(i for i in nodes[upstream]['inputs'] if i.get('link') is not None and i['type']==item['type'])
                l=links[bypass['link']];upstream,slot=str(l[1]),l[2]
            values[item['name']]=[upstream,slot]
            collect(upstream)
        schema=metadata[n['type']]['input']
        fields={**schema.get('required',{}),**schema.get('optional',{})}
        for key,value in list(values.items()):
            if key not in fields:
                del values[key];continue
            field=fields[key]
            if field[0]=='BOOLEAN' and not isinstance(value,bool):
                replacement=field[1].get('default',False)
                adjustments.append({'node':node_id,'input':key,'source':value,'value':replacement})
                values[key]=replacement
    collect('42')
    result={'source':str(source),'graph':graph,
            'bindings':{'prompt':{'node':'10','input':'text'},'seed':{'node':'7','input':'seed'}},
            'final_output_nodes':['42'],'adjustments':adjustments}
    write_json(API/'krea2_image.json',result)
    return result

def save_submission(graph):
    kinds={n['class_type'] for n in graph.values()}
    if 'SeedVR2VideoUpscaler' in kinds:name='Krea2-文生图'
    elif 'TextEncodeQwenImage21' in kinds:name='Qwen-多图参考'
    elif 'MiniMaxH3Easy' in kinds:name='H3-视频'
    elif 'TextEncodeMinimaxMusic' in kinds or any('Music' in k for k in kinds):name='音乐'
    elif any('TTS' in k or 'AudioSilence' in k for k in kinds):name='配音'
    elif 'ImageUpscaleWithModel' in kinds:name='图片二次放大'
    else:name='其他媒体'
    write_json(API/'最近提交'/f'{name}.json',graph)
