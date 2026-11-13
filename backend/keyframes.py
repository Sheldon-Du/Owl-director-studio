"""Independent Image2.1 asset-composition pictures for each storyboard shot."""
from . import script_source
import copy,hashlib,json
from . import ai,asset_references,shot_asset_binding,qwen_prompts,store,skill_workflows

def fingerprint(project,shot):
    from . import visual_reference
    data={'shot':{k:shot.get(k) for k in ('id','description','prompt','actions','native','frame_cards','excluded_asset_ids')},
          'assets':[{k:a.get(k) for k in ('id','name','kind','description','references','previews','adopted')} for a in project.get('assets',[])],
          'rules':skill_workflows.prompt_rules(project,'image')}
    data['applied_art_style']=visual_reference.art(project);data['camera']=visual_reference.active_camera(shot);data['first_frame_link']=shot.get('first_frame_link')
    if script_source.kind(project)=='story':data['base_source']=script_source.fingerprint(project)
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def generate(project,shot,report):
    source=fingerprint(project,shot)
    # This image expresses the shot's central relationship, rather than its start pose.
    view=copy.deepcopy(shot);view['manual_asset_ids']=[];view['asset_ids']=[];view.pop('frame_asset_binding',None)
    view['native']={**view.get('native',{}),'首帧描述':shot['description'],'首帧提示词':'本镜关键关系组合画面：'+shot['description']}
    report('AI 正在从本镜描述提炼角色、场景、道具及组合关系')
    association=shot_asset_binding.associate(project,view,lambda message:report(message.replace('首帧','关键帧')))
    view['asset_ids']=association['asset_ids'];view['frame_asset_binding']=association
    selected=[a for a in project['assets'] if a['id'] in view['asset_ids']]
    if not selected:raise ValueError('未识别到本镜可见资产，请先提取角色、场景和道具')
    missing=[a['name'] for a in selected if not asset_references.effective(a)]
    if missing:raise ValueError('以下关键帧元素没有参考图片，请先生成并采用：'+'、'.join(missing))
    refs=shot_asset_binding.references(project,view)
    if len(refs)>16:raise ValueError('关键帧组合超过 Image2.1 的16张参考上限，请减少对应元素的参考图')
    payload={'shot_description':shot['description'],'actions':shot.get('actions',[]),'camera':{k:shot.get('native',{}).get(k) for k in ('构图','景别','角度','运镜','画面焦点','调色和打光')},
             'bindings':association['bindings'],'assets':[{k:a.get(k) for k in ('id','name','kind','description')} for a in selected],
             'references':[{**r,'slot':f'<image{i+1}>'} for i,r in enumerate(refs)],'adopted_rules':skill_workflows.prompt_rules(project,'image')}
    system='''你是 Image2.1 图片编辑提示词编写器。根据本镜描述和动作，选择一个实际发生、最能表达角色与场景道具关系的瞬间，将所选资产参考组合为单张关键帧，不能叠加多个时间点。输出JSON {rewritten_prompt:中文单段编辑指令,rewritten_prompt_zh:同文中文,wh_ratio:比例,ratio_follow:"",relationship:完整组合关系说明}。
明确谁在哪里、朝向谁、谁持有什么、动作接触点、前中后景、尺度、遮挡、视线和光影。人物身份与衣着、道具形态保持各自参考，场景重构为本镜机位；角色白背景板和场景俯视资产只是素材，不能把白底、四宫格或俯视布局照搬进成片构图。多图逐张用<imageN>分工，单图用“图像”。仅有图片用途与备注，不声称已视觉识别参考内容。只描绘本镜已有事实，不新增人物、道具、动作或故事。关键帧独立于首帧，不强制选动作起点；不改动首帧采用。尺寸与比例只写参数，不进prompt；不使用六段标题、字幕、水印或界面。'''+qwen_prompts.rules(True)
    report(f'AI 正在编写 {len(selected)} 个元素、{len(refs)} 张参考的 Image2.1 组合提示词')
    def validate(value):
        out=qwen_prompts.validate(value,{'kind':'scene','references':refs})
        relation=value.get('relationship')
        if not isinstance(relation,str) or not relation.strip():raise ValueError('关键帧缺少角色、场景和道具的组合关系说明')
        return {**out,'relationship':relation}
    with ai.asset_call_policy('keyframe_prompt',limit=1,max_tokens=12000,timeout=240,preserve_context=True):
        result=ai.validated_image_response(system,payload,validate)
    return {**result,'source_hash':source,'asset_ids':view['asset_ids'],'bindings':association['bindings'],'references':refs}

def install_routes(app):
    @app.post('/api/projects/{pid}/shots/{sid}/keyframes/{action}')
    def change(pid:str,sid:str,action:str,body:dict):
        from . import jobs
        with jobs.TASK_LOCK:
            project=store.get_project(pid)
            if project['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请刷新后重试')
            shot=next((s for s in project['shots'] if s['id']==sid),None)
            if not shot:raise ValueError('分镜不存在')
            name=body.get('media');items=shot.setdefault('keyframes',[]);trash=shot.setdefault('keyframe_trash',[])
            pool=trash if action=='restore' else items
            item=next((m for m in pool if m['media']==name),None)
            if not item:raise ValueError('请从本镜关键帧候选中选择图片')
            if action=='adopt':shot['adopted_keyframe']=name
            elif action=='remove':
                items.remove(item);trash.append(item)
                if shot.get('adopted_keyframe')==name:shot.pop('adopted_keyframe',None)
            elif action=='restore':trash.remove(item);items.append(item)
            else:raise ValueError('关键帧操作无效')
            return store.save_project(project,project['revision'])
