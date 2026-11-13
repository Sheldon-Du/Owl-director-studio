"""Stable native device bindings for the two 24GB GPUs."""
import copy

LOADERS={
    'UNETLoader':[(0,'MODEL','gpu:0')],
    'UnetLoaderGGUF':[(0,'MODEL','gpu:0')],
    'CLIPLoader':[(0,'CLIP','gpu:1')],
    'DualCLIPLoader':[(0,'CLIP','gpu:1')],
    'TripleCLIPLoader':[(0,'CLIP','gpu:1')],
    'VAELoader':[(0,'VAE','gpu:1')],
    'CheckpointLoaderSimple':[(0,'MODEL','gpu:0'),(1,'CLIP','gpu:1'),(2,'VAE','gpu:1')],
}
SELECTORS={'MODEL':('SelectModelDevice','model'),'CLIP':('SelectCLIPDevice','clip'),'VAE':('SelectVAEDevice','vae')}

def apply(graph):
    graph=copy.deepcopy(graph)
    # Updating an existing selector is enough; repeated submission adds no
    # duplicate device nodes and uses the same cache keys across jobs.
    existing={}
    for key,spec in graph.items():
        for kind,(selector,field) in SELECTORS.items():
            if spec['class_type']==selector:
                spec['inputs']['device']='gpu:0' if kind=='MODEL' else 'gpu:1'
                source=spec['inputs'].get(field)
                if isinstance(source,list):existing[(str(source[0]),source[1],kind)]=str(key)
        if spec['class_type']=='SeedVR2LoadDiTModel':
            spec['inputs'].update(device='cuda:0',offload_device='cpu',cache_model=True)
        elif spec['class_type']=='SeedVR2LoadVAEModel':
            spec['inputs'].update(device='cuda:1',offload_device='cuda:1',cache_model=True)
    next_id=max([800000,*[int(k) for k in graph if str(k).isdigit()]])+1
    for key,spec in list(graph.items()):
        for slot,kind,device in LOADERS.get(spec['class_type'],[]):
            selector,field=SELECTORS[kind]
            selected=existing.get((str(key),slot,kind))
            # Only insert a binding when this output is actually consumed.
            consumers=[]
            for dest,node in list(graph.items()):
                if node['class_type']==selector and node['inputs'].get(field)==[str(key),slot]:continue
                for name,value in node['inputs'].items():
                    if value==[str(key),slot]:consumers.append((dest,name))
            if not consumers:continue
            if not selected:
                selected=str(next_id);next_id+=1
                graph[selected]={'class_type':selector,'inputs':{field:[str(key),slot],'device':device}}
            for dest,name in consumers:graph[dest]['inputs'][name]=[selected,0]
    return graph
