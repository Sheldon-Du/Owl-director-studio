"""Upgrade inherited image defaults without losing previous creative work."""
import time
from . import store

DEFAULT_MODEL='qwen-image-2.1'


def apply(project):
    changed=0
    for asset in project.get('assets',[]):
        if asset.get('model_source')=='user' or asset.get('model') not in (None,'z-image',DEFAULT_MODEL):continue
        if asset.get('model')==DEFAULT_MODEL:
            if not asset.get('model_source'):asset['model_source']='default';changed+=1
            continue
        if asset.get('prompt'):
            asset.setdefault('prompt_history',[]).append({'prompt':asset['prompt'],'prompt_zh':asset.get('prompt_zh',''),'model':asset.get('model','z-image'),'reason':'默认图像模型更新为 Image2.1','created':time.time()})
        asset.update(model=DEFAULT_MODEL,model_source='default',prompt='',prompt_zh='')
        for key in ('wh_ratio','ratio_follow','prompt_rules','prompt_rule_source','prompt_mode'):asset.pop(key,None)
        changed+=1
    return changed


def migrate():
    # Each save creates a normal project version, making this upgrade reversible.
    updated=[]
    with store.LOCK:
        for project in store.list_projects():
            count=apply(project)
            if count:
                store.save_project(project,project['revision'])
                updated.append({'project_id':project['id'],'assets':count})
    return updated
