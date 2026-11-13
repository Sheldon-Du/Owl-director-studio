"""Seedance authoring within the original Owl project and task queue."""
import copy,hashlib,json,math
from . import store,ai,seedance_catalogue
FIELDS={'goal':'任务目标','subject':'Subject 主体','style':'Style 风格','shot':'Shot 镜头与构图','setting':'Setting 场景与环境','lighting':'Scene lighting 光照与影调','constraints':'约束参考'}
KINDS=('seedance_overview','seedance_storyboard','seedance_asset','seedance_frames','seedance_assets')
GUIDE='每张静帧用5S：goal任务用途；subject身份、皮肤毛发、服装材质、姿态、站位、眼神；style审美色彩质感；shot景别机位构图、前中后景清晰关系；setting环境空间文字原文；lighting方向冷暖、主补轮廓光、明暗影调；constraints必须保留、禁止事项、冲突优先级。身份资产只写稳定身份，画面干净；镜头帧只写单一时刻。'

def effective(p):
    out={}
    for key in ('script','cinematic','art'):
        if key=='cinematic':continue  # Camera controls now belong to individual shots.
        cfg=p.get('seedance_professional',{}).get(key,{})
        if cfg.get('enabled'):
            values={k:copy.deepcopy(v) for k,v in cfg.get('options',{}).items() if k in cfg.get('selected',[])}
            if key=='script':
                grouped={}
                for prefix,label in (('core::','核心参数'),('script::','剧本参数')):
                    rows={name[len(prefix):]:values.pop(name) for name in list(values) if name.startswith(prefix)}
                    if rows:grouped[label]=rows
                values.update(grouped)
            if values:out[key]=values
    return out

def source(p):
    promo=p.get('story_promo',{})
    selected=promo.get('adopted')
    if isinstance(selected,dict):
        from . import story_promo
        adopted=story_promo.input_values(p)
        if adopted['stale']:raise ValueError('画面化推文依据已变化，请重新整理并确认后制作分镜')
        return adopted['text']
    return (promo.get(selected,{}) or {}).get('text') if selected in ('video','novel') else p.get('documents',{}).get('script') or p['story']

def context(p,original=False):
    from . import authoring,visual_reference
    if p.get('source_mode')=='idea':authoring.source(p)
    return {'source':authoring.source(p) if original and 'source_mode' in p else p['story'] if original else source(p),'story_policy':p.get('story_policy','screenplay'),'duration':p['duration'],
      'ratio':p.get('parameters',{}).get('画幅比例','16:9'),'seedance_template':None,
      'seedance_case':None,'professional':effective(p),'applied_art_style':visual_reference.art(p)}

def fingerprint(p,target=None,kind=None):
    assets=p.get('assets',[]);shots=p.get('shots',[])
    if target and kind=='seedance_asset':assets=[a for a in assets if a['id']==target];shots=[]
    if target and kind=='seedance_frames':shots=[s for s in shots if s['id']==target]
    return hashlib.sha256(json.dumps([context(p),p['story'],p.get('documents',{}).get('seedance_overview'),assets,shots],ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def card(value):
    if not isinstance(value,dict):raise ValueError('5S必须为对象')
    out={k:value.get(k) for k in FIELDS}
    if any(not isinstance(v,str) or not v.strip() for v in out.values()):raise ValueError('5S七个字段均需填写具体描述')
    return out

def card_text(value):return '\n'.join(FIELDS[k]+'：'+str(value.get(k,'')) for k in FIELDS)

def validate_assets(rows):
    if not isinstance(rows,list) or len(rows)>80:raise ValueError('资产清单格式无效')
    seen=set()
    for a in rows:
        if a.get('kind') not in ('character','scene','prop') or not isinstance(a.get('name'),str) or not a['name'].strip():raise ValueError('资产kind须为character/scene/prop，且填写名字')
        key=(a['kind'],a['name'])
        if key in seen:raise ValueError('资产不可重复')
        seen.add(key);a['card']=card(a.get('card'))
    return rows

def generate(task,report):
    p=task['snapshot'];kind=task['kind'];base=context(p,original=kind=='seedance_overview');target=task.get('target')
    from . import visual_reference,reference_profile
    reference=reference_profile.routed(p,'overview' if kind=='seedance_overview' else 'shot' if kind=='seedance_storyboard' else 'none')
    if reference:base['reference']=reference
    report('正在按 Seedance 方法生成，专业模块只参考明确选中项')
    system='你是Seedance创作工作台。忠于输入事实，不改写项目原始故事字段；剧本可按故事处理策略组织，不新增无依据人物。动作时间遵守自然速度。professional是用户明确选用的附加专业参数，仅在对应剧本、镜头或美术范围内参考；未给出的参数不套用DirectorMaster默认值。核心参数与剧本参数同名时，剧本参数在剧本生成中优先，原始输入事实与人工明确约束优先。'+GUIDE
    system+=' '+visual_reference.FIDELITY
    if kind=='seedance_overview':
        system+=' 创作概览overview.style应明确applied_art_style中已采用的视觉风格、色彩、光影和渲染方向；剧本画面表达与之协调，不改变原剧情因果和对白。'
        system+=' 返回{overview:{logline,theme,style,structure,beats:[string],notes:string},script:string,assets:[{kind,name,card:{goal,subject,style,shot,setting,lighting,constraints},voice_description:string}]}。script为完整可用剧本，overview不复制原故事全文。每个独立角色、场景、道具建立5S档案，人物声音词另写voice_description，只描述稳定音色、音域、共鸣、气息、口音与节奏，不写具体台词或剧情限制。'
        def validate(v):
            if not isinstance(v.get('overview'),dict) or not isinstance(v.get('script'),str) or not v['script'].strip():raise ValueError('缺少创作概览或剧本')
            v['assets']=validate_assets(v.get('assets'));return v
    elif kind=='seedance_assets':
        system+=' 返回{assets:[{kind,name,card:{goal,subject,style,shot,setting,lighting,constraints},voice_description:string}]}。归集当前来源里的独立角色、场景、道具，为每项填写完整5S。保留现有人工字段。'
        base['existing_assets']=p['assets']
        def validate(v):v['assets']=validate_assets(v.get('assets'));return v
    elif kind=='seedance_storyboard':
        from . import authoring_prompts
        if p.get('shots') and not task.get('options',{}).get('replace'):raise ValueError('已有分镜，请明确确认重生成')
        system+=' 返回{shots:[{description,prompt,duration,asset_names:[string],dialogue,voiceover,actions:[{description,natural_seconds}],frame_cards:{first:{5S七字段},middle:{5S七字段},last:{5S七字段}}}]}。第一帧为动作起点、关键帧为关键动作中段、尾帧为动作终点，三帧身份空间光线连续。每镜3–15秒，动作秒数之和等于duration；镜头prompt中文包含按秒动作、摄像与声音。对白不改原文，超时拆镜。'
        base.update(assets=[{'name':a['name'],'kind':a['kind'],'card':a.get('card'),'description':a.get('description')} for a in p['assets']],overview=p.get('documents',{}).get('seedance_overview'),shots=task.get('options',{}).get('count',6))
        system=system.replace('镜头prompt中文包含按秒动作、摄像与声音','镜头prompt中文包含因果动作序列、摄像与声音；秒数只写内部actions数据，不拼入提示词')
        system+='\n'+authoring_prompts.rules()+'\n每镜另返回seedance_sections对象，以规定的中文段落标题为键；由系统拼成prompt。未绑定真实媒体不得使用<<<标签。'
        def validate(v):
            rows=v.get('shots')
            if not isinstance(rows,list) or not 1<=len(rows)<=100:raise ValueError('缺少分镜')
            names={a['name'] for a in p['assets']}
            for s in rows:
                if not isinstance(s.get('description'),str) or not s['description'].strip() or not isinstance(s.get('prompt'),str):raise ValueError('镜头需要描述和提示词')
                d=s.get('duration')
                if not isinstance(d,(int,float)) or not math.isfinite(d) or not 3<=d<=15:raise ValueError('每镜时长3–15秒')
                actions=s.get('actions',[])
                if not actions or any(not isinstance(a.get('natural_seconds'),(int,float)) or not math.isfinite(a['natural_seconds']) or a['natural_seconds']<=0 for a in actions) or abs(sum(a['natural_seconds'] for a in actions)-d)>.05:raise ValueError('动作时间需为正数且总和等于镜头时长')
                if not isinstance(s.get('asset_names'),list) or set(s['asset_names'])-names:raise ValueError('引用了不存在的资产')
                s['frame_cards']={k:card(s.get('frame_cards',{}).get(k)) for k in ('first','middle','last')}
                if s.get('seedance_sections') or 'source_mode' in p:s['prompt']=authoring_prompts.validate(s.get('seedance_sections'),p.get('authoring_settings',{}).get('seedance_model','2.5'))
            return v
    else:
        item=next((a for a in p['assets' if kind=='seedance_asset' else 'shots'] if a['id']==target),None)
        if not item:raise ValueError('对象不存在')
        base['item']=item
        system+=(' 返回{card:{goal,subject,style,shot,setting,lighting,constraints},voice_description:string}，保留人工已填写字段，不更换身份。' if kind=='seedance_asset' else ' 返回{frame_cards:{first:{5S七字段},middle:{5S七字段},last:{5S七字段}}}，仅补齐缺失帧描述，不改已有手工描述。')
        def validate(v):
            if kind=='seedance_asset':v['card']=card(v.get('card'))
            else:v['frame_cards']={k:card(v.get('frame_cards',{}).get(k)) for k in ('first','middle','last')}
            return v
    with ai.writing_call_policy(max(3000,len(base['source']))):result=ai.validated_image_response(system,base,validate)
    return {'source_hash':fingerprint(p,target,kind),'result':result,'target':target,'kind':kind}

def merge_assets(p,rows):
    for raw in rows:
        old=next((a for a in p['assets'] if a['name']==raw['name'] and a['kind']==raw['kind']),None)
        if old is None:
            old={'id':store.uid(),'kind':raw['kind'],'name':raw['name'],'description':'','model':'qwen-image-2.1','references':[],'previews':[],'adopted':None,'prompt':''};p['assets'].append(old)
        old.setdefault('card',{})
        for k,v in raw['card'].items():
            if not old['card'].get(k):old['card'][k]=v
        old['description']=card_text(old['card'])
        if old['kind']=='character':
            voice=old.setdefault('voice',{})
            if not voice.get('description'):voice['description']=raw.get('voice_description','')

def apply(p,result):
    if fingerprint(p,result.get('target'),result['kind'])!=result['source_hash']:raise store.Conflict('生成期间依据被修改，旧结果已保留在任务中，未覆盖项目')
    v=result['result'];kind=result['kind'];p['seedance_mode']=True
    if kind=='seedance_overview':
        if p['documents'].get('script'):p.setdefault('seedance_script_history',[]).append(p['documents']['script'])
        p['documents']['seedance_overview']=v['overview'];p['documents']['script']=v['script'];p['script_confirmed']=True
        merge_assets(p,v['assets'])
    elif kind=='seedance_assets':merge_assets(p,v['assets'])
    elif kind=='seedance_storyboard':
        if p['shots']:p.setdefault('seedance_shot_history',[]).append(copy.deepcopy(p['shots']))
        p['shots']=[]
        for raw in v['shots']:
            s=copy.deepcopy(raw);s.update(id=store.uid(),asset_ids=[a['id'] for a in p['assets'] if a['name'] in raw['asset_names']],outputs=[],frames=[],keyframes=[],natural_status='ai_reviewed',timing_status='ai_reviewed')
            cursor=0
            for a in s['actions']:
                a.update(id=store.uid(),start=cursor,end=cursor+a['natural_seconds'],minimum_seconds=a['natural_seconds'],rationale='Seedance自然动作时序');cursor=a['end']
            s['native']={'画面焦点':s['description'],'AIGC提示词':s['prompt'],'时长':s['duration'],'台词':[s.get('dialogue','')],'旁白':s.get('voiceover',''),'动作预案':s['actions'],'景别':s['frame_cards']['first']['shot']}
            p['shots'].append(s)
        p['duration']=sum(s['duration'] for s in p['shots']);p['native_storyboard_current']=True;p['confirmed']=False
        p['documents']['storyboard_native']={'contract_version':2,'分镜表':[copy.deepcopy(s['native']) for s in p['shots']]}
        p.pop('storyboard_generation',None)
    else:
        item=next(a for a in p['assets' if kind=='seedance_asset' else 'shots'] if a['id']==result['target'])
        if kind=='seedance_asset':merge_assets(p,[{**item,**v}])
        else:
            item.setdefault('frame_cards',{})
            for name,c in v['frame_cards'].items():
                current=item['frame_cards'].setdefault(name,{})
                for k,value in c.items():
                    if not current.get(k):current[k]=value

def filtered_project(p):
    value=copy.deepcopy(p);refs=effective(p)
    script=refs.get('script',{})
    value['parameters']={'画幅比例':p.get('parameters',{}).get('画幅比例','16:9'),**{k:v for k,v in script.items() if k not in ('核心参数','剧本参数')},**script.get('核心参数',{})}
    if script.get('剧本参数'):value['parameters']['剧本专业参数']=script['剧本参数']
    value['production_scheme']={k:refs.get(k,{}) for k in ('cinematic','art')}
    value['documents'].pop('core_pack',None);value['documents'].pop('core_prompt',None);value['documents'].pop('art',None)
    return value

def install(app):
    @app.get('/api/seedance/library')
    def library():return seedance_catalogue.library()
