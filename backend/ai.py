import json
import hashlib
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar
from . import director, store, timing, endpoints, script_source

_ASSET_POLICY=ContextVar('asset_call_policy',default=None)


@contextmanager
def asset_call_policy(phase,metrics=None,limit=2,max_tokens=8192,timeout=300,preserve_context=False,report=None,reasoning_effort='medium',reuse=False,force=False):
    token=_ASSET_POLICY.set({'phase':phase,'metrics':metrics,'calls':0,'limit':limit,'max_tokens':max_tokens,'timeout':timeout,'preserve_context':preserve_context,'report':report,'reasoning_effort':reasoning_effort,'reuse':reuse,'force':force})
    try:yield
    finally:_ASSET_POLICY.reset(token)


@contextmanager
def writing_call_policy(source_length):
    """Allow full source-ledger JSON for longer stories, without blind retries."""
    if _ASSET_POLICY.get():
        # A caller may already own a measured budget and cancellation policy.
        yield
        return
    budget=32768 if source_length>6000 else 16384 if source_length>=2400 else 8192
    with asset_call_policy('screenplay',limit=3,max_tokens=budget,timeout=300,preserve_context=True):
        yield


def response_text(text):
    # MiniMax's OpenAI-compatible content can prefix the final answer with
    # <think>...</think>. Never parse draft JSON inside that reasoning block.
    cleaned=str(text or '').strip().lstrip('\ufeff').strip()
    while re.match(r'^<think\b',cleaned,re.I):
        reasoning=re.match(r'^<think\b[^>]*>.*?</think\s*>\s*',cleaned,re.I|re.S)
        if not reasoning:return ''
        cleaned=cleaned[reasoning.end():].strip()
    return cleaned


class InvalidJSONResponse(ValueError):
    def __init__(self,message,raw_response):
        super().__init__(message)
        self.raw_response=raw_response


def parse_response(text):
    director.package()
    from pln_llm import json_loads_tolerant
    cleaned=response_text(text)
    data,diagnostic=json_loads_tolerant(cleaned)
    if not isinstance(data,dict):
        # Some compatible models return literal line breaks inside a JSON
        # prompt string. Accept those characters without changing the text;
        # every caller still validates its domain schema and source evidence.
        candidates=[cleaned]
        fenced=re.search(r'```(?:json)?\s*([\s\S]*?)```',cleaned,re.I)
        if fenced:candidates.append(fenced.group(1).strip())
        if '{' in cleaned:candidates.append(cleaned[cleaned.index('{'):])
        for candidate in candidates:
            try:
                parsed,_=json.JSONDecoder(strict=False).raw_decode(candidate)
                if isinstance(parsed,dict):data=parsed;break
            except (ValueError,TypeError):pass
    if not isinstance(data,dict):
        raise InvalidJSONResponse('AI 未返回有效 JSON：'+diagnostic[:180],cleaned)
    return data


def validated_image_response(system,payload,validator):
    """Repair generated image JSON/schema errors, never transport errors."""
    previous=None;error=None
    system+='\n仅输出一个完整JSON对象，不使用Markdown围栏或说明文字。所有键名和字符串必须用英文双引号包裹；字符串内的英文双引号、换行与反斜杠必须按JSON转义。'
    policy=_ASSET_POLICY.get()
    attempts=min(2,max(0,policy['limit']-policy['calls'])) if policy else 2
    for attempt in range(attempts):
        request=payload if not attempt else {**payload,'validation_error':error,'previous':previous}
        instruction=system if not attempt else system+'\n上次回复未通过JSON或内容校验。按validation_error修正，重新返回完整对象；保留元素身份、人工修改和参考图分工，不改变输出字段，不用解释替代JSON。'
        try:previous=ask(instruction,json.dumps(request,ensure_ascii=False))
        except ValueError as failure:
            if not str(failure).startswith('AI 未返回有效 JSON') and not (policy and policy.get('phase')=='owl_authoring' and any(word in str(failure) for word in ('上游截断','请求超时','HTTP 502','HTTP 503','HTTP 504'))):raise
            error=str(failure);previous=None
        else:
            try:return validator(previous)
            except ValueError as failure:
                from . import ai_requests
                ai_requests.discard_last();error=str(failure)
    label='创作阶段' if policy and policy.get('phase')=='owl_authoring' else '画面描述与提示词' if policy and policy.get('phase')=='frame_plan' else '配乐风格标签' if policy and policy.get('phase')=='soundtrack_prompt' else '动作时序审查' if policy and policy.get('phase')=='storyboard_timing' else '资产提示词'
    raise ValueError(f'{label}自动纠正{max(0,attempts-1)}次后仍未通过：'+str(error or '当前调用额度已用完')+'；已有内容保留，可单独重试')


def ask(system, user, *, response_parser=None):
    import os
    from .creation_recovery import INSTRUCTIONS
    strategy=os.environ.get('DIRECTOR_AI_RECOVERY_STRATEGY')
    if strategy in INSTRUCTIONS:system+='\n'+INSTRUCTIONS[strategy]
    from . import ai_context,ai_requests
    original_characters=len(system)+len(user)
    system,user,saved_characters=ai_requests.prepare(system,user)
    context_meta={'context_prefix_reused':False,'context_source_characters':0,'duplicate_characters_removed':saved_characters,'original_input_characters':original_characters,'contract_version':ai_requests.CONTRACT_VERSION}
    # Complete required sources are sent once; local prefix reuse is not provider caching.
    cfg=store.settings()
    if not cfg.get('ai_url') or not cfg.get('ai_model'):
        raise ValueError('请先在设置中配置文本 AI 接口及模型。DirectorMaster 原生规划不需要接口。')
    director.package()
    from pln_llm import call_ai_ex
    policy=_ASSET_POLICY.get()
    options={}
    if policy:
        if policy['calls']>=policy['limit']:raise ValueError('本元素的修正次数已用完，可手动修改或重新提取失败项')
        policy['calls']+=1
        options={'timeout':policy['timeout'],'max_retries_per_step':1,'enable_recovery':False,'freeze_system':True}
        if policy.get('preserve_context'):
            # The planner owns actual batching and durable checkpoints. Native
            # transport must not silently drop screenplay text or repeat a
            # truncated whole-plan request with only an appended hint.
            options.update(max_split_retries=0,allow_context_compression=False)
    began=time.monotonic();meta={};outcome='failed'
    cache_id=ai_requests.cache_key(system,user,cfg,{k:policy.get(k) for k in ('phase','max_tokens','reasoning_effort')} if policy else 'text_ai')
    ai_requests.LAST_KEY.set(cache_id)
    if policy and policy.get('reuse') and not policy.get('force'):
        cached=ai_requests.lookup(cache_id)
        if cached is not None:
            ai_requests.record({'phase':policy['phase'],'outcome':'reused','result_reused':True,'input_characters':0,'avoided_input_characters':len(system)+len(user),'seconds':0,'contract_version':ai_requests.CONTRACT_VERSION})
            return cached
    try:
        if policy and (policy['phase'] in ('owl_authoring','asset_image_prompt','frame_plan','h3_rewrite','h3_translation','h3_compression','h3_language','h3_lock_repair','h3_failure_repair') or policy['phase'].startswith('story_promo_')):
            from . import authoring_transport
            resume_hint='重新点击画面描述与提示词' if policy['phase']=='frame_plan' else '重新点击生成提示词或生成预览' if policy['phase']=='asset_image_prompt' else '点击继续未完成步骤'
            parsed,meta=authoring_transport.generate(cfg,endpoints.chat_url(cfg['ai_url']),system,user,policy['max_tokens'],policy['timeout'],store.DATA,response_parser or parse_response,policy.get('report'),effort=policy.get('reasoning_effort','medium'),resume_hint=resume_hint)
            outcome='completed'
            if policy.get('reuse'):ai_requests.save(cache_id,parsed)
            return parsed
        result=call_ai_ex(endpoints.chat_url(cfg['ai_url']),cfg.get('ai_key',''),cfg['ai_model'],system,user,0.3,policy['max_tokens'] if policy else 8192,**options)
        if isinstance(result,tuple):
            text,error,meta=result
            if error:
                if any('HTTP '+str(code) in error for code in (301,302,303,307,308)):
                    raise ValueError('AI 接口返回地址重定向。请使用服务商的完整聊天接口地址（通常以 /v1/chat/completions 结尾）；/v1 基础地址已自动补全。')
                raise ValueError('AI 调用失败：'+error)
        else:
            text=result.get('text','') if isinstance(result,dict) else str(result)
            meta=result.get('meta',{}) if isinstance(result,dict) else {}
        parsed=(response_parser or parse_response)(text);outcome='completed'
        if policy and policy.get('reuse'):ai_requests.save(cache_id,parsed)
        return parsed
    finally:
        ai_requests.record({'phase':policy['phase'] if policy else 'text_ai','seconds':round(time.monotonic()-began,3),'input_characters':len(system)+len(user),'outcome':outcome,'result_reused':False,'model':cfg.get('ai_model'),'usage':meta.get('usage'),**ai_requests.usage_summary(meta.get('usage')),'request_payload':json.loads(user) if user.lstrip().startswith('{') else user,'rule_digest':hashlib.sha256(system.encode()).hexdigest(),**context_meta})
        metrics=policy.get('metrics') if policy and policy.get('metrics') else ai_context.recorder()
        if metrics:
            metrics({'phase':policy['phase'] if policy else 'text_ai','call':policy['calls'] if policy else 1,'seconds':round(time.monotonic()-began,3),'input_characters':len(system)+len(user),'output_budget':max(16384,min(32768,policy['max_tokens'])) if policy and (policy['phase'] in ('owl_authoring','asset_image_prompt') or policy['phase'].startswith('story_promo_')) else policy['max_tokens'] if policy else 8192,'complete_context':policy.get('preserve_context',False) if policy else False,'outcome':outcome,**context_meta,**{k:meta.get(k) for k in ('attempts','split_hint_retries','compression','levels_tried','fallback_used','finish_reason','usage','recovered_characters')}})


def analyze(project,progress=None):
    progress=progress or (lambda message:None)
    core=director.definitions('DirectorMasterCore')
    rules={k:{'options':v['options'],'type':v['type']} for k,v in core.items() if not k.startswith('AI')}
    answer=ask('''你是故事阅读与导演参数预填助手。只输出JSON {parameters:{参数名:{value,source,evidence}},questions:[关键缺项问题],summary:故事概述}，不改写故事。
参数必须来自DirectorMaster参数表，枚举准确匹配；明确内容source=explicit并逐字引用evidence，推断source=suggested。保护用户设定。本步骤只阅读故事与预填创作参数，不列资产、不提取人物外貌、场景、道具或性格；元素提取在剧本编写完成之后进行。''',json.dumps({'story':project['story'],'existing_parameters':project.get('parameters',{}),'parameter_schema':rules},ensure_ascii=False))
    parameters={}
    for key,item in answer.get('parameters',{}).items():
        if key not in rules or not isinstance(item,dict):
            continue
        value=item.get('value')
        if rules[key]['options'] and value not in rules[key]['options']:
            continue
        if item.get('source') not in ('explicit','suggested'):
            item['source']='suggested'
        # User edits are always protected.
        if project.get('parameter_sources',{}).get(key,{}).get('source')=='user':
            continue
        parameters[key]=item
    answer['parameters']=parameters
    return {'parameters':parameters,'questions':answer.get('questions',[]),'summary':str(answer.get('summary',''))}


def script_assets(project,progress=None,on_asset=None,metrics=None,force=False):
    from . import asset_extraction
    return asset_extraction.extract(project,progress,on_asset,metrics,force)


def schedule(project, shot, revise_time=False):
    if not revise_time:
        # The same natural audit yields a concrete proposal when the current
        # duration is insufficient. Applying it requires no second AI call.
        revised=schedule(project,shot,revise_time=True)
        if abs(timing.number(revised['duration'])-timing.number(shot['duration']))>0.02:
            return timing.suggest(project,shot,revised)
        return revised
    if revise_time:
        outline=next((o for o in project.get('storyboard_generation',{}).get('outlines',[]) if o['id']==shot.get('generation_outline_id')),None)
        from . import timing_speech
        sources=timing_speech.catalogue(project,shot)
        system='你是DirectorMaster实时动作时序审查员。只处理当前镜头，依据动作先决条件、位移、反应和原句决定自然所需时间。初估时长可以延长或缩短，禁止均分目标时长、加速、慢放、瞬移、跳步或填充空等待。完整保留本镜动作顺序与结尾，不新增剧情。输出严格JSON {actions:[{id,description,natural_seconds,minimum_seconds,maximum_seconds,rationale,speech_ids:[]}]}。可选depends_on、distance_m、speed_m_s。不输出start/end或镜头总时长，程序累计自然时长。只选择speech_sources原句id分配到实际说话动作，不输出dialogue或voiceover文本，不抄写或改写台词。全部原句必须恰好播放一次；说话留够正常语速、呼吸与情绪停顿，原句不可截断或重复。没有人声的动作speech_ids=[]。对白按画内发声，旁白保持画外音，不让角色嘴型替代旁白。description描述动作与说话方式，不重复抄写原句。'
        payload={'current_shot_script':outline['source_excerpt'] if outline else shot.get('description',''),'audio_reference':shot.get('native',{}).get('音频描述',''),'native_prompt':shot['prompt'],'initial_estimate_seconds':shot['duration'],'current_actions':shot.get('actions',[]),'speech_sources':sources}
        if any(s.get('measured_seconds') for s in sources):
            system+='\n带measured_seconds的原句已由TTS实际生成，其秒数是固定真实音频时长，不能重新按字数估算或压缩。只审查动作自然时长及声音落点；动作和说话并行时至少容纳较长者，先动作后说话等顺序关系需计入前置动作时间。没有人声的动作段预留纯静音，配乐另行叠加。每个带speech_ids的动作段，其人声必须从该段开始播放；若需要先动作再说话或说完再动作，将前后纯动作拆为独立speech_ids=[]的段落，不能把前置动作藏在说话段内。'
        def validate(result):
            actions=timing_speech.bind(result.get('actions',[]),sources)
            actions,duration=timing.from_natural(actions)
            draft={**shot,'duration':duration,'actions':actions,'natural_status':'ai_reviewed','prompt':timing.remove_estimates(shot['prompt'])}
            draft.pop('timing_suggestion',None)
            checked=timing.validate(draft)
            if not checked['ok']:raise ValueError('AI时间修正未通过校验：'+'；'.join(checked['errors']))
            return {'actions':actions,'duration':duration}
        result=validated_image_response(system,payload,validate)
        actions,duration=result['actions'],result['duration']
        draft={**shot,'duration':duration,'actions':actions,'natural_status':'ai_reviewed','prompt':timing.remove_estimates(shot['prompt'])}
        draft.pop('timing_suggestion',None)
        checked=timing.validate(draft)
        if not checked['ok']:raise ValueError('AI 时间修正未通过校验：'+'；'.join(checked['errors']))
        draft['prompt']=timing.render(draft)
        return draft


def recommendation_inputs(project):
    from . import story_promo
    docs=project.get('documents',{})
    return {'visual_promo':story_promo.input_values(project),'confirmed_script':script_source.text(project,False),'director_rules':docs.get('core_prompt',''),'core_pack':docs.get('core_pack',''),'duration':project.get('duration'),'current_scheme':project.get('production_scheme',{}),'writing_plan':docs.get('script_workflow_plan'),'video_spec':{k:v for k,v in docs.get('video_spec',{}).items() if k!='title'}}


def recommendation_fingerprint(project):
    values={**recommendation_inputs(project),'script_confirmed':bool(project.get('script_confirmed')),'script_needs_rewrite':bool(project.get('script_needs_rewrite')),'script_inputs':script_source.input_hash(project)}
    return hashlib.sha256(json.dumps(values,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def recommend(project):
    if not script_source.ready(project):raise ValueError('请先填写故事或有效剧本')
    schema=director.production_schema()
    rules={section:{k:{'type':v['type'],'options':v['options'],'default':v['default'],'rule':v['tooltip']} for k,v in fields.items()} for section,fields in schema.items()}
    answer=ask('你是 DirectorMaster 镜头与美术方案推荐员。先阅读完整来源（有效剧本或原始故事）、已采用画面化推文、导演核心规则和参数表，再推荐一套完整可编辑的拍摄方案。只输出JSON {scheme:{cinematic:{原生参数名:值},art:{原生参数名:值}},summary:string,reasons:{cinematic:{参数名:中文依据},art:{参数名:中文依据}}}。方案两个区都必须有值；枚举必须逐字匹配给定表，禁止创造参数名。只规划，不输出最终分镜提示词。保护故事人物与情节，不重写剧本；未知设定用建议表达。运镜、光影、构图、材质需服务剧本。保持自然实时动作，不选慢镜/慢放/子弹时间/延时摄影/倍速；分镜的动作时间不足时延长或拆镜。',json.dumps({'visual_promo':recommendation_inputs(project).get('visual_promo'),'confirmed_script':script_source.text(project),'director_rules':project['documents'].get('core_prompt',''),'core_pack':project['documents'].get('core_pack',''),'duration':project['duration'],'parameter_schema':rules,'current_scheme':project.get('production_scheme',{}),'writing_plan':project['documents'].get('script_workflow_plan'),'video_spec':project['documents'].get('video_spec')},ensure_ascii=False))
    try:
        scheme=director.validate_scheme(answer.get('scheme'))
    except ValueError as error:
        # One constrained repair keeps invented enum values out of the native
        # nodes, while avoiding a failed recommendation for a spelling mistake.
        answer=ask('修正 DirectorMaster 方案的参数校验错误。只返回 JSON {scheme:{cinematic:{原生参数名:值},art:{原生参数名:值}},summary:string,reasons:{cinematic:{参数名:依据},art:{参数名:依据}}}。所有枚举逐字复制 parameter_schema.options 中的一个值，不能用解释文字、简称或自创选项。布尔字段只能 true/false。保留原方案意图并依据已确认剧本；禁止慢镜、慢放、子弹时间、延时摄影或倍速。不输出分镜。',json.dumps({'validation_error':str(error),'previous_recommendation':answer,'parameter_schema':rules,'confirmed_script':script_source.text(project)},ensure_ascii=False))
        scheme=director.validate_scheme(answer.get('scheme'))
    if not scheme.get('cinematic') or not scheme.get('art'):raise ValueError('AI 未返回完整镜头与美术方案')
    completed={section:{k:params.get(k,v['default']) for k,v in fields.items()} for section,fields in schema.items() for params in [scheme[section]]}
    director.validate_scheme(completed)
    return {'scheme':completed,'summary':str(answer.get('summary','')),'reasons':answer.get('reasons',{}),'source_hash':recommendation_fingerprint(project)}
