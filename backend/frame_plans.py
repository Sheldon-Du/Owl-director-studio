"""Editable, asset-referenced Image2.1 plans, separate from image rendering."""
from . import script_source, keyframes, ai, qwen_prompts, asset_references, store, stage3d, frame_prompt_rules, visual_reference, shot_references

def compact_asset(asset):
    # Preserve every known feature and its priority, omit repeated source quotes,
    # audit history and generated images from a text-only frame planning call.
    features={g:{k:{'value':v['value'],'source':v.get('source')} for k,v in group.get('fields',{}).items() if v.get('value') and v.get('source')!='unknown'} for g,group in asset.get('visual_profile',{}).get('groups',{}).items()}
    features={g:v for g,v in features.items() if v}
    row={k:asset.get(k) for k in ('id','name','kind','variant','prompt_notes')}
    if features:row['features']=features
    else:row['description']=asset.get('description','')
    return row

def planning_payload(project, shot, options):
    mode=options.get('mode','frame')
    if mode not in ('frame','keyframe','tail'):raise ValueError('画面类型无效')
    assets={a['id']:a for a in project.get('assets',[])}
    selection=options.get('selected_asset_ids')
    if selection is not None:
        if not isinstance(selection,list) or not selection or set(selection)-set(assets):raise ValueError('请选择本阶段可见的有效资产')
        assets={k:v for k,v in assets.items() if k in selection}
    native={k:v for k,v in shot.get('native',{}).items() if mode=='frame' or k not in ('首帧描述','首帧提示词')}
    payload={'base_source_kind':script_source.kind(project),'shot':{'description':shot.get('description'),'actions':shot.get('actions'),'native':native},'mode':mode,'five_s_card':shot.get('frame_cards',{}).get({'frame':'first','keyframe':'middle','tail':'last'}[mode],{}),'intent':options.get('description',''),
             'assets':[compact_asset(a) for a in assets.values()],
             'applied_art_style':visual_reference.art(project),'camera_override':visual_reference.active_camera(shot),'fixed_first':shot.get('first_frame_link'),'visual_priority':visual_reference.FIDELITY,'saved_3d_layout':stage3d.h3_reference(project,shot),'layout_example':stage3d.default(project,shot['id']),'layout_kinds':stage3d.KINDS,'layout_poses':stage3d.POSES,'ratio':project.get('parameters',{}).get('画幅比例','16:9')}
    if shot.get('performance'):payload['finalized_performance']={k:shot['performance'].get(k) for k in ('source_hash','duration','actions','camera','visual','finals')}
    if examples:=shot_references.guidance(shot):
        payload['shot_examples']=examples
        payload['shot_examples_rule']=shot_references.STILL_RULE
    payload['layout_example']['objects']=payload['layout_example']['objects'][:1]
    if options.get('auto_bind_adopted'):
        payload['adopted_asset_references']=[{'asset_id':a['id'],'media':a.get('adopted')} for a in assets.values()]
    return payload

def planning_fingerprint(project, shot, options):
    """Hash planning inputs, not unrelated media previews or other frame cards."""
    import hashlib,json
    # The worker plans against the enabled professional settings only. Apply
    # exactly the same view when validating in the parent process.
    from . import seedance_integration
    project=seedance_integration.filtered_project(project)
    shot=next(s for s in project['shots'] if s['id']==shot['id'])
    payload=planning_payload(project,shot,options)
    if not options.get('propose_assets'):
        # Editing against chosen references consumes their identities and profiles.
        from . import frame_reference_sets
        refs=frame_reference_sets.owners(project,options.get('references',[]))
        ids={r['asset_id'] for r in refs}
        payload['references']=refs
        payload['assets']=[{k:a.get(k) for k in ('id','name','kind','description','visual_profile','variant')} for a in project['assets'] if a['id'] in ids]
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def propose(project, shot, options, report):
    mode=options.get('mode','frame')
    if mode not in ('frame','keyframe','tail'):raise ValueError('画面类型无效')
    assets={a['id']:a for a in project.get('assets',[])}
    selection=options.get('selected_asset_ids')
    if selection is not None:
        if not isinstance(selection,list) or not selection or set(selection)-set(assets):raise ValueError('请选择本阶段可见的有效资产')
        assets={k:v for k,v in assets.items() if k in selection}
    payload=planning_payload(project,shot,options)
    system='你是Image2.1画面导演。先根据分镜编写单张画面描述与图片编辑提示词，再列出需要的资产，用户稍后选择具体图片。输出JSON：relationship、rewritten_prompt、rewritten_prompt_zh、wh_ratio、ratio_follow、required_assets。required_assets为1至16项数组，每项为{asset_id:资产目录中准确编号,usage:本画面用途与空间关系,state:需要的动作前后状态}。只选本画面真正可见的角色场景道具，不把整镜全部资产搬入，不新增剧情。首帧为动作开始前，关键帧为核心关系瞬间，不叠加不同时间点。优先选符合状态的已有变体，同一资产只列一次。严格按清单顺序分配图片：一项时正文称“图像”，多项时依次使用<image1>等全部标签。此时没有具体图片，禁止声称看过图片。用中文单段指令写清构图、角色外观、位置、视线、接触、遮挡与灯光。原文明示优先，人物特征不串用。素材白底、四宫格、俯视不照搬镜头。禁止字幕水印。wh_ratio数字比例，ratio_follow空字符串。'+qwen_prompts.rules(True)
    system+=' 同一次输出必须包含layout_scene：{objects:[{name,kind,asset_id,pose,position:[x,y,z],rotation,size:[宽,高,深]}],camera:{position:[x,y,z],target:[x,y,z],focal:35}}。kind和pose在目录范围内，Y轴向上、单位米、人物面对+Z，rotation为绕Y轴角度。只输出这些布局字段，版本、时长、颜色、背景、关键帧由程序补齐，不重复输出。layout_scene表示relationship所述本阶段瞬间，首帧是起点，关键帧是关键关系。人物与道具按required_assets绑定asset_id，简单空间支架可以为空；不新增剧情。穿在角色身上的衣袍、腰带、帽子属于角色外观，不建立独立box挡住人物；只有单独摆放的衣物才建立物体。机位不得位于墙壁或物体内部，近景需对准可见人物面部，避免道具遮满画面。'
    payload['layout_example']['objects']=payload['layout_example']['objects'][:1]
    system+=' 简模只表达构图，不建模皮肤服饰或微表情。使用满足画面所需的最少对象，不复制示例对象。输出紧凑JSON，relationship不超过200字，清单用途与状态各不超过60字。rewritten_prompt_zh填空，由程序复制中文正文。features中的明确来源优先于设计建议。'+frame_prompt_rules.rules()
    system+=' tail表示动作结束后的单一尾帧，严格使用five_s_card.last对应状态；不是首帧或关键帧，也不重复动作起点。frame、keyframe、tail各自只描述同一时刻，以本阶段5S为画面依据。'
    if options.get('layout_svg'):
        system=system.split(' 同一次输出必须包含layout_scene')[0]+frame_prompt_rules.rules()+' 本次无需layout_scene，白模SVG将在下一任务绘制。tail是动作结束后的单一尾帧，严格采用本阶段five_s_card，不叠加起点或中段。输出relationship不超过200字，rewritten_prompt_zh填空，程序复制中文正文。'
    if options.get('auto_bind_adopted'):
        system=system.replace('用户稍后选择具体图片','程序自动绑定资产卡已采用的图片').replace('此时没有具体图片，禁止声称看过图片。','adopted_asset_references提供资产卡已采用图片的文件标识，程序按required_assets顺序自动绑定；未直接查看图像，不声称视觉识别。')
        system+=' 仅使用当前勾选资产，按required_assets顺序决定图像标签分工；使用已采用参考保持身份和状态，无需用户再次逐项选图。'
    def validate(value):
        rows=value.get('required_assets')
        if not isinstance(rows,list) or not 1<=len(rows)<=16:raise ValueError('需列出1至16个所需资产')
        seen=set();clean=[]
        for row in rows:
            if not isinstance(row,dict) or row.get('asset_id') not in assets or row['asset_id'] in seen:raise ValueError('所需资产编号无效或重复')
            if any(not isinstance(row.get(k),str) or not row[k].strip() or len(row[k])>600 for k in ('usage','state')):raise ValueError('需填写资产用途与状态')
            seen.add(row['asset_id']);clean.append({k:row[k] for k in ('asset_id','usage','state')})
        out=frame_prompt_rules.validate(value,[{'media':str(i)} for i in range(len(clean))])
        if not isinstance(value.get('relationship'),str) or not value['relationship'].strip():raise ValueError('缺少画面描述')
        raw=value.get('layout_scene')
        if isinstance(raw,dict):
            raw={**raw,'version':1,'duration':shot['duration'],'ratio':payload['layout_example']['ratio']}
            if isinstance(raw.get('camera'),dict):raw['camera']={**raw['camera'],'motion':False}
            for i,o in enumerate(raw.get('objects',[])):
                if isinstance(o,dict):
                    o['keyframes']=[];o.setdefault('id',f'layout-{i+1}');o.setdefault('color','#8ca9c9')
        layout=None if options.get('layout_svg') else stage3d.normalize(raw,project,shot['id'])
        required={r['asset_id'] for r in clean}
        if layout and any(o.get('asset_id') and o['asset_id'] not in required for o in layout['objects']):raise ValueError('布局不得加入资产清单之外的元素')
        return {**out,'relationship':value['relationship'],'required_assets':clean,**({'layout_scene':layout} if layout else {})}
    system+=frame_prompt_rules.structured_rules()
    report('AI 正在编写当前帧的5S内容与资产清单'+('' if options.get('layout_svg') else '及构图布局'))
    def checked(value):
        try:return validate(value)
        except ValueError as error:
            report('画面方案校验需纠正：'+str(error))
            raise
    with ai.asset_call_policy('frame_plan',limit=2,max_tokens=16384,timeout=240,preserve_context=True,report=report,reasoning_effort='low'):
        result=ai.validated_image_response(system,payload,checked)
    plan={**result,'references':[],'reference_details':[],'asset_ids':[r['asset_id'] for r in result['required_assets']],'bindings':[],
            'source_hash':keyframes.fingerprint(project,shot),'planning_source_hash':planning_fingerprint(project,shot,options),'mode':mode,**({'selected_asset_ids':selection} if selection is not None else {})}
    if options.get('auto_bind_adopted'):
        from .frame_auto_references import bind_adopted
        plan=bind_adopted(project,plan)
        report('已自动绑定 '+str(len(plan['references']))+' 张资产卡采用图片'+('；部分资产需先采用图片' if plan['missing_adopted_assets'] else ''))
    return plan

def validate_selection(project, plan):
    rows=plan.get('required_assets')
    if not rows:return
    from . import frame_reference_sets
    refs=frame_reference_sets.owners(project,plan.get('references',[]))
    if len(refs)!=len(rows) or any(r['asset_id']!=a['asset_id'] for r,a in zip(refs,rows)):raise ValueError('请按AI资产清单为每项选择对应参考图')
    if len({r['media'] for r in refs})!=len(refs):raise ValueError('参考图片不可重复')
    for r in refs:store.media_path(r['media'])
    plan['references']=refs
    plan['reference_details']=[{**a,'media':r['media']} for a,r in zip(rows,refs)]

def dual_source_card(project,shot,options,report):
    import copy,json
    from . import performance as perf,seedance_integration as seedance,speech_audio
    phase={'frame':'first','keyframe':'middle','tail':'last'}[options.get('mode','frame')]
    if not shot.get('performance',{}).get('actions'):
        if options.get('rebuild_card'):raise ValueError(f'第 {project["shots"].index(shot)+1} 镜尚未建立动作与时序方案。打开“镜头 → 编辑与时序”完成声音、时序、画面审核后，再重做当前帧5S。')
        return None
    state=perf.status(project,shot)
    if not state['visual']:
        index=project['shots'].index(shot)+1
        pending=next(label for key,label in (('sound','声音／对白'),('timing','动作与镜头时序'),('visual','构图与空间画面')) if not state[key])
        raise ValueError(f'第 {index} 镜尚未确认{pending}。打开“镜头 → 编辑与时序”完成该项审核，再更新当前帧；现有5S与图片保留。')
    plan=shot['performance']
    timing={k:copy.deepcopy(plan.get(k)) for k in ('duration','speech','actions','camera','visual')}
    for row in timing['speech']:row.pop('gain',None)
    timing['dialogue']=[{k:row.get(k) for k in ('speech_id','speaker','text','start','duration')} for row in perf.rows(project,shot)]
    creative=perf.creative_prompt(shot)
    basis_data={'creative':creative,'finalized':timing,'phase':phase}
    examples=shot_references.guidance(shot)
    if examples:basis_data['shot_examples']=examples
    basis=speech_audio.digest(basis_data)
    if not options.get('rebuild_card') and shot.get('frame_card_sources',{}).get(phase)==basis:return None
    card=shot.get('frame_cards',{}).get(phase,{})
    system='你是分镜静帧导演。结合创作概览分镜提示词与三步定稿分镜提示词，编写当前阶段单一瞬间的5S。创作概览提供剧情、风格与画面意图；三步定稿中的实测对白、动作、镜头时间轴以及构图、空间、首尾状态为执行依据，有冲突时以定稿为准，不改变时间安排或台词。first为动作起点，middle为时间轴中的核心瞬间，last为结束状态；不能将多个时间点叠加。保留角色身份、道具状态、屏幕方向、光线和衔接。返回JSON对象card，包含goal、subject、style、shot、setting、lighting、constraints七个非空中文字符串。只写静态画面，合计约500至1000字。'
    payload={'phase':phase,'creative_storyboard_prompt':creative,'three_step_finalized_storyboard_prompt':timing,'existing_card':card,'visible_assets':[compact_asset(a) for a in project.get('assets',[]) if a['id'] in (options.get('selected_asset_ids') or shot.get('asset_ids',[]))],'user_intent':options.get('description',''),'fixed_first':shot.get('first_frame_link')}
    if examples:
        payload['shot_examples']=examples
        system+=' '+shot_references.STILL_RULE
    report('AI正结合创作概览与三步定稿，更新当前帧5S描述')
    with ai.asset_call_policy('frame_plan',limit=2,max_tokens=8192,timeout=240,preserve_context=True,report=report):
        result=ai.validated_image_response(system,payload,lambda value:seedance.card(value.get('card')))
    if phase=='first' and shot.get('first_frame_link',{}).get('mode')=='previous_tail' and shot['first_frame_link'].get('card'):result=seedance.card(shot['first_frame_link']['card'])
    return {'phase':phase,'card':result,'basis':basis}


def direct_card_plan(project,shot,options,report):
    """Compile the current editable card; never ask AI to rewrite its content."""
    from . import seedance_integration as seedance,frame_auto_references,frame_reference_sets
    mode=options.get('mode','frame')
    if mode not in ('frame','keyframe','tail'):raise ValueError('画面类型无效')
    card=seedance.card(shot.get('frame_cards',{}).get({'frame':'first','keyframe':'middle','tail':'last'}[mode],{}))
    ids=options.get('selected_asset_ids')
    if ids is None:ids=shot.get('asset_ids',[])
    assets={a['id']:a for a in project.get('assets',[])}
    refs=frame_reference_sets.owners(project,options.get('references',[]))
    if refs:ids=list(dict.fromkeys(row['asset_id'] for row in refs))
    if not ids or set(ids)-set(assets) or len(ids)>16:raise ValueError('请为当前帧选择1至16个可见资产')
    required=[{'asset_id':identity,'usage':'保持'+assets[identity]['name']+'的外观与身份，位置和状态遵循当前5S描述','state':card['subject']} for identity in ids]
    sections=dict(card)
    sections['constraints']+='；'+('图像对应'+assets[ids[0]]['name'] if len(ids)==1 else '；'.join('<image'+str(i+1)+'>对应'+assets[identity]['name'] for i,identity in enumerate(ids)))+'；参考图仅锁定对应资产，画面构图、环境、光线和动作状态严格使用以上5S；不复制参考图中的白底、四宫格或文字。'
    prompt=' '.join('【'+heading+'】'+sections[key] for key,heading in zip(frame_prompt_rules.SECTION_KEYS,frame_prompt_rules.HEADINGS))
    plan={'prompt':prompt,'prompt_zh':prompt,'rewritten_prompt':prompt,'rewritten_prompt_zh':prompt,'prompt_structure':'5s-v1','prompt_source':'frame-card-direct','relationship':seedance.card_text(card),'wh_ratio':project.get('parameters',{}).get('画幅比例','16:9'),'ratio_follow':'','required_assets':required,'references':refs,'reference_details':[],'asset_ids':ids,'bindings':[],'source_hash':keyframes.fingerprint(project,shot),'planning_source_hash':planning_fingerprint(project,shot,options),'mode':mode,'selected_asset_ids':ids}
    if refs:plan['reference_details']=[{**required[i],'media':row['media']} for i,row in enumerate(refs)]
    elif options.get('auto_bind_adopted'):plan=frame_auto_references.bind_adopted(project,plan)
    report('已直接将本帧5S描述编译为提示词，未调用AI改写')
    return plan


def generate(project, shot, options, report):
    if options.get('layout_only'):
        import copy
        mode=options.get('mode','frame');plan=copy.deepcopy(shot.get('image_plans',{}).get(mode))
        if not plan:raise ValueError('请先生成本阶段的画面描述与提示词')
        view=copy.deepcopy(project);target=next(s for s in view['shots'] if s['id']==shot['id'])
        target['stage3d']=plan.get('layout_scene') or stage3d.default(project,shot['id'])
        request='仅为本阶段静态构图调整布局，不改变剧情。阶段：'+mode+'；画面描述：'+plan['relationship']+'；用户调整：'+str(options.get('description',''))
        result=stage3d.recommend(view,shot['id'],report,request)
        scene=result['scene'];scene['camera']['motion']=False
        for o in scene['objects']:o['keyframes']=[]
        plan.update(layout_scene=scene,layout_explanation=result['explanation'],source_hash=keyframes.fingerprint(project,shot),mode=mode)
        plan.pop('composition_reference',None)
        return plan
    if options.get('card_only') and options.get('mode','frame')=='frame' and shot.get('first_frame_link',{}).get('mode')=='previous_tail':raise ValueError('首帧固定复用上一镜尾帧，请先切换独立首帧再重做')
    update=dual_source_card(project,shot,options,report)
    if options.get('card_only'):
        if not update:raise ValueError('请先完成三步定稿，再重做5S描述')
        return {'mode':options.get('mode','frame'),'frame_card_update':update,'card_only':True,'planning_source_hash':planning_fingerprint(project,shot,options),'source_hash':keyframes.fingerprint(project,shot)}
    if not update:return direct_card_plan(project,shot,options,report)
    import copy
    view=copy.deepcopy(project);target=next(row for row in view['shots'] if row['id']==shot['id'])
    target.setdefault('frame_cards',{})[update['phase']]=update['card']
    result=direct_card_plan(view,target,options,report)
    result['planning_source_hash']=planning_fingerprint(project,shot,options)
    result['frame_card_update']=update
    return result
