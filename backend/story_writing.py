"""An explicit choice between preserving the input story and creative arrangement."""
import json
import re
from . import script_workflows as workflows
from . import story_world
from . import script_tasks
from . import creative_rules

POLICIES=('faithful','screenplay','creative')


def source_units(story):
    paragraphs=[p.strip() for p in re.split(r'\n\s*\n|\r?\n',story) if p.strip()]
    return [{'id':f'S{i+1:03d}','text':p} for i,p in enumerate(paragraphs)]


def literal_quotes(text):
    pattern=r'“([^”]+)”|「([^」]+)」|『([^』]+)』|‘([^’]+)’|"([^"\n]+)"'
    return [(m.start(),next(s for s in m.groups() if s)) for m in re.finditer(pattern,text)]


def dialogue_contract(units):
    rows=[]
    for unit in units:
        literals=[]
        for i,(start,quote) in enumerate(literal_quotes(unit['text'])):
            prefix=unit['text'][max(0,start-50):start]
            if re.search(r'(?:字样|文字|一行字|封面|标题|题名|屏幕|牌匾|刻着|写着)[^。！？]*$',prefix):kind='画面文字'
            elif re.search(r'(?:心想|暗想|心中|心里|默念)[^。！？]*$',prefix):kind='内心引文'
            elif re.search(r'(?:所谓|什么是|称为|称作|叫作|名为|上面的|其中的|这种|这个|这些)\s*$',prefix):kind='叙述引文'
            elif re.fullmatch(r'(?:汪|喵|吱|咔|砰|轰|哐|叮|咚)[汪喵吱咔砰轰哐叮咚、，。！!…]*',quote) and ((re.search(r'(?:狗|犬|猫)[^。！？]*[:：]\s*$',prefix) and not re.search(r'模仿|学着|学狗|学猫',prefix)) or not re.search(r'(?:说|问|喊|叫|答)[^。！？]*[:：]\s*$',prefix)):kind='拟声引文'
            else:kind='对白或广播'
            literals.append({'id':f'{unit["id"]}-Q{i+1}','text':quote,'type':kind})
        if not literals:
            source=unit['text']
            speech=re.search(r'(?:说道|说|问道|问|答道|回答|喊道|喊|叫道|叫|喝道|喝|叹道|叹)[:：]\s*(.+)$',source)
            named=re.match(r'^([\u4e00-\u9fffA-Za-z·]{1,12})[:：]\s*(.+)$',source)
            non_speakers=('旁白','画外音','叙述','心理','内心','心想','OS','字幕','文字','标题','书名','地点','时间','场景','说明','结论','备注')
            if speech or (named and named[1] not in non_speakers):
                text=(speech[1] if speech else named[2]).strip()
                text=re.sub(r'(?<=[。！？!?…])\d+$','',text)
                if text:literals.append({'id':f'{unit["id"]}-Q1','text':text,'type':'对白或广播'})
        rows.append({'source_id':unit['id'],'literals':literals,
                     'dialogue_allowed':any(q['type']=='对白或广播' for q in literals)})
    return rows


def same_source_narration(content,original):
    # Some pasted story paragraphs carry a numeric citation after punctuation.
    # Ignore that suffix for this comparison only; never edit source material.
    plain=content.strip('“”「」『』‘’"')
    source=re.sub(r'(?<=[。！？!?…])\d+$','',original.strip())
    return bool(plain) and ''.join(plain.split()) in (''.join(original.split()),''.join(source.split()))


def source_parts(units):
    """Literal narrative and quotation spans; no facts are left to retyping."""
    result=[]
    pattern=re.compile(r'“([^”]+)”|「([^」]+)」|『([^』]+)』|‘([^’]+)’|"([^"\n]+)"')
    contracts={row['source_id']:row for row in dialogue_contract(units)}
    for unit in units:
        spans=[];cursor=0;quotation=0
        for match in pattern.finditer(unit['text']):
            if match.start()>cursor:spans.append((cursor,match.start(),None))
            quotation+=1;spans.append((match.start(),match.end(),f'{unit["id"]}-Q{quotation}'))
            cursor=match.end()
        if cursor<len(unit['text']):spans.append((cursor,len(unit['text']),None))
        quotes={q['id']:q for q in contracts[unit['id']]['literals']}
        for number,(start,end,qid) in enumerate(spans,1):
            text=unit['text'][start:end]
            if text.strip():result.append({'id':f'{unit["id"]}-P{number}','source_id':unit['id'],'text':text,
                'quotation_id':qid,'quotation_type':quotes.get(qid,{}).get('type','叙述')})
    return result


def locked_parts(result,units,strict_dialogue=True):
    import copy
    value=copy.deepcopy(result);parts=source_parts(units);lookup={p['id']:p for p in parts};seen=[]
    quote_aliases={p['quotation_id']:p['id'] for p in parts if p.get('quotation_id')}
    alias_adjustments=[]
    # A prose attribution between two quote fragments is concurrent delivery
    # context, not a second plot event. It may precede the spoken sentence in
    # filmable text; quote order and paragraph/event order remain locked.
    attributions={}
    if not strict_dialogue:
        for pos,p in enumerate(parts):
            adjacent=parts[max(0,pos-1):pos]+parts[pos+1:pos+2]
            speech=any(q['source_id']==p['source_id'] and q.get('quotation_id') and q.get('quotation_type')=='对白或广播' for q in adjacent)
            temporal=re.search(r'之后|以前|半晌|时辰|分钟|秒|后来|数日|一夜|小时|次日|第二天|翌日',p['text'])
            if speech and not temporal and re.fullmatch(r'[\u4e00-\u9fffA-Za-z·]{1,12}(?:笑道|说道|答道|问道|喊道|叫道|说|问|答|冒出一句|欢呼雀跃)[，,:：。\s]*',p['text']):
                attributions[p['id']]=p
        for scene in value.get('scenes',[]) or []:
            for item in scene.get('units',[]) if isinstance(scene,dict) else []:
                ids=item.get('part_ids') if isinstance(item,dict) else None
                if not isinstance(ids,list) or len(ids)!=1 or ids[0] not in lookup:continue
                origin=lookup[ids[0]];expr=str(item.get('expression','')).strip()
                candidates=[p for p in parts if p['source_id']==origin['source_id'] and (
                    (item.get('kind')=='对白' and not origin.get('quotation_id') and p.get('quotation_type')=='对白或广播' and p.get('quotation_id') and expr==p['text'].strip('“”「」『』‘’"'))
                    or (item.get('kind')=='动作' and origin.get('quotation_id') and p['id'] in attributions and re.sub(r'[，,:：。\s]','',expr)==re.sub(r'[，,:：。\s]','',p['text'])))]
                if len(candidates)==1:
                    item['part_ids']=[candidates[0]['id']]
                    alias_adjustments.append({'from':ids[0],'to':candidates[0]['id'],'basis':'同段表达与原文片段唯一逐字匹配，仅纠正引用编号'})
        cited={k for s in value.get('scenes',[]) if isinstance(s,dict) for u in s.get('units',[]) if isinstance(u,dict) for k in u.get('part_ids',[]) if isinstance(k,str)}
        for scene in value.get('scenes',[]) or []:
            for item in scene.get('units',[]) if isinstance(scene,dict) else []:
                ids=item.get('part_ids') if isinstance(item,dict) else None
                if item.get('kind')!='动作' or not isinstance(ids,list) or len(ids)!=1 or ids[0] not in lookup:continue
                canonical=re.sub(r'[，,:：。\s]','',str(item.get('expression','')))
                matches=[p for k,p in attributions.items() if k not in cited and p['source_id']==lookup[ids[0]]['source_id'] and canonical==re.sub(r'[，,:：。\s]','',p['text'])]
                if len(matches)==1:
                    original=ids[0];item['part_ids']=[matches[0]['id']]
                    alias_adjustments.append({'from':original,'to':matches[0]['id'],'basis':'同段发话归属原句唯一匹配，未改表达或对白'})
    if not isinstance(value.get('scenes'),list):raise ValueError('剧本化缺少分场正文')
    for scene in value['scenes']:
        if not isinstance(scene,dict) or not isinstance(scene.get('units'),list):raise ValueError('剧本化场次需含units数组')
        for item in scene['units']:
            if not isinstance(item,dict):raise ValueError('原文片段分配需为对象')
            ids=item.get('part_ids')
            if isinstance(ids,list):
                alias_adjustments.extend({'from':k,'to':quote_aliases[k]} for k in ids if isinstance(k,str) and k in quote_aliases)
                ids=[quote_aliases.get(k,k) if isinstance(k,str) else k for k in ids];item['part_ids']=ids
            if not isinstance(ids,list) or not ids or any(not isinstance(k,str) or k not in lookup for k in ids):
                invalid=ids if not isinstance(ids,list) else [k for k in ids if not isinstance(k,str) or k not in lookup]
                raise ValueError('忠实剧本化需引用有效part_ids；无效编号：'+str(invalid)+'。仅从source_parts中选择，正文另写expression；原文由程序回填')
            seen.extend(ids);selected=[lookup[k] for k in ids]
            item['source_ids']=list(dict.fromkeys(p['source_id'] for p in selected))
            item['text']=''.join(p['text'] for p in selected)
            item.pop('dialogue_id',None)
            if strict_dialogue and item.get('kind')=='对白':
                if len(selected)!=1 or not selected[0]['quotation_id']:
                    raise ValueError('、'.join(ids)+'：对白只引用一个原文引文片段；前后的叙述另作动作或画外音')
                item['dialogue_id']=selected[0]['quotation_id']
    expected=[p['id'] for p in parts]
    paragraph_order=[lookup[k]['source_id'] for k in seen]
    paragraph_order=[k for i,k in enumerate(paragraph_order) if i==0 or k!=paragraph_order[i-1]]
    parallel_attribution=(bool(attributions) and len(seen)==len(set(seen)) and set(seen)==set(expected)
        and [k for k in seen if k not in attributions]==[k for k in expected if k not in attributions]
        and paragraph_order==[u['id'] for u in units])
    if seen!=expected and not parallel_attribution:
        missing=[k for k in expected if k not in seen];duplicates=list(dict.fromkeys(k for k in seen if seen.count(k)>1))
        raise ValueError('原文片段必须按顺序完整覆盖且恰好使用一次，不遗漏、重排或重复；缺失：'+str(missing)+'；重复：'+str(duplicates)+'；按source_parts原序修正')
    if alias_adjustments:value['source_alias_adjustments']=alias_adjustments
    return value


def render_screenplay(result,units,require_parts=False):
    declared=any(isinstance(s,dict) and isinstance(s.get('units'),list) and any(isinstance(i,dict) and 'part_ids' in i for i in s['units']) for s in result.get('scenes',[]) or [])
    if require_parts or declared:result=locked_parts(result,units)
    scenes=result.get('scenes')
    if not isinstance(scenes,list) or not scenes:raise ValueError('剧本化缺少分场正文')
    seen=[];body=[];mapping=[];notes=[];parts={u['id']:[] for u in units}
    originals={u['id']:u['text'] for u in units}
    contracts={u['source_id']:u for u in dialogue_contract(units)};adjustments=[]
    for index,scene in enumerate(scenes):
        if not isinstance(scene,dict) or not isinstance(scene.get('units'),list) or not scene['units']:raise ValueError('剧本化场次缺少正文段落')
        body.append(f"第{index+1}场 · {str(scene.get('location') or '地点未明确')} · {str(scene.get('time') or '时间未明确')}")
        if scene.get('director_note'):
            note=str(scene['director_note'])
            if story_world.speed_change(note):raise ValueError(f'第{index+1}场导演表现建议不得使用慢放或倍速，动作按自然时间发生；请仅修改director_note，以构图、机位、光线和自然停留表达，保留正文和原文编号')
            notes.append({'scene':index+1,'note':note})
        for item in scene['units']:
            if not isinstance(item,dict):raise ValueError(f'第{index+1}场剧本段落必须是对象')
            ids=item.get('source_ids');kind=item.get('kind');content=str(item.get('text','')).strip()
            if not isinstance(ids,list) or not ids or any(i not in originals for i in ids):raise ValueError('剧本化段落缺少有效原文对应编号')
            if kind not in ('动作','对白','画外音','人物设定','场景描述','叙述') or (not content and not (kind=='对白' and item.get('dialogue_id'))):raise ValueError('剧本化段落类型或正文无效')
            seen.extend(ids)
            original='\n'.join(originals[i] for i in ids)
            literals=[q for source_id in ids for q in contracts[source_id]['literals']]
            spoken=[q for q in literals if q['type']=='对白或广播']
            if kind=='对白':
                quote_id=item.get('dialogue_id')
                if quote_id is not None:
                    locked=next((q for q in spoken if q['id']==quote_id),None)
                    if not locked:raise ValueError(f'第{index+1}场 {"、".join(ids)} 的dialogue_id不属于本段原文对白或广播；请引用dialogue_contract中的对应编号')
                    content=locked['text']
                elif not spoken:
                    visible=[q['text'] for q in literals if q['type']=='画面文字']
                    inner=[q['text'] for q in literals if q['type']=='内心引文']
                    if any(content.strip('“”「」『』‘’"')==q for q in visible):kind='场景描述'
                    elif any(content.strip('“”「」『』‘’"')==q for q in inner) or same_source_narration(content,original):kind='画外音'
                    else:raise ValueError(f'第{index+1}场 {"、".join(ids)}：忠于故事剧本化不能为无对白原文添加对白；本段没有人物对白或广播。请保持原文意思并使用动作、叙述或画外音，不把内心判断变成说出口的台词')
                    adjustments.append({'scene':index+1,'source_ids':ids,'from':'对白','to':kind})
                else:
                    allowed=[q['text'] for q in spoken];written=[q for _,q in literal_quotes(content)]
                    if not any(q in content for q in allowed) or any(q not in allowed for q in written):
                        raise ValueError(f'第{index+1}场 {"、".join(ids)}：剧本化改写或新增了原文对白；请使用dialogue_contract中的dialogue_id，由程序回填完整原句')
            if story_world.speed_change(content) and not story_world.speed_change(original):raise ValueError('剧本化不得通过速度变化改变动作时间')
            for source_id in ids:
                if content in parts[source_id]:raise ValueError('剧本化重复了同一段情节正文')
                parts[source_id].append(content)
            label=kind+(' · '+str(item['speaker']) if item.get('speaker') else '')
            body.append(f'【{label}】\n{content}')
            mapping.append({'source_ids':ids,'source_quote':original,'scene':index+1,'kind':kind,'script_excerpt':content,
                            **({'part_ids':item['part_ids']} if 'part_ids' in item else {})})
        body.append('')
    order=[value for i,value in enumerate(seen) if i==0 or value!=seen[i-1]]
    if order!=[u['id'] for u in units]:raise ValueError('剧本化必须完整覆盖原文且保持事件顺序，不得遗漏、回跳或重排')
    for unit in units:
        quoted=[q for _,q in literal_quotes(unit['text'])]
        combined='\n'.join(parts[unit['id']])
        if any(q not in combined for q in quoted):raise ValueError(f'{unit["id"]}：剧本化遗漏或改写原文中的对白/引文；请保留dialogue_contract中本段全部原句')
    return {'script':'\n\n'.join(body).strip(),'script_adaptation_map':mapping,'script_director_notes':notes,'script_dialogue_adjustments':adjustments,'script_policy':'screenplay','script_changes':[],
            'script_policy_note':('按原文片段逐字回填为来源对照式剧本工作稿，AI负责分场与表达标签，全部片段依原顺序恰好使用一次。逐字保管不代表表达已通过审查；请核对引文是否说出口、背景交付、动作和说话人。' if require_parts or declared else '')+'按 DirectorMaster 设定剧本化，逐段记录原文依据，导演表现建议单独列出。'+(f'已将{len(adjustments)}段仅标签错误的原文叙述或画面文字归回画外音/场景描述，原句保留。' if adjustments else '')+'确认正文后进入镜头与美术设计。'}


def adapt(project,core,structure,progress=None,*,target_units=None,raw=False,completed_context=None):
    from . import ai
    all_units=source_units(project['story'])
    units=target_units if target_units is not None else all_units
    if not units:raise ValueError('请先填写故事')
    from . import screenplay_expression
    system='''你是遵循 DirectorMaster 设定的忠实改编编剧。将故事写为可拍摄的中文分场剧本，只输出JSON。
保留人物身份、关系、年龄、关键事实、因果、银幕事件顺序与结局，不新增情节或对白。规则范例不能成为新人物或新事件。导演参数服务原文，不改变时代；自然实时，不慢放或倍速，不删内容凑时长。地点与时间未明确就注明未明确。'''
    system+=workflows.instruction(project)+'\n'+script_tasks.instruction(project)+creative_rules.instruction(project,'script')
    payload={'source_units':all_units,'dialogue_contract':dialogue_contract(all_units),'duration_seconds':project['duration'],'script_mode':project.get('script_mode'),'director_parameters':project.get('parameters',{}),'director_rules':core['统一电影提示词'],'native_script_structure_reference':structure,'story_world_contract':story_world.contract(project),**workflows.context(project)}
    payload['source_parts']=source_parts(units)
    system+=screenplay_expression.INSTRUCTION
    if target_units is not None:
        payload['dialogue_contract']=dialogue_contract(units)
        payload.update(complete_story=project['story'],
            target_source_ids=[u['id'] for u in units],
            completed_source_ids=[u['part_ids'] for scene in (completed_context or {}).get('scenes',[]) for u in scene.get('units',[])],
            completed_screenplay={'scenes':(completed_context or {}).get('scenes',[])[-1:],'questions':[]})
        system+='\n这是全片剧本的一个输出批次。完整故事和source_units保留全片人物、时代、因果、说话归属，source_parts与dialogue_contract只详细列出当前批次；completed_source_ids记录已完成表达，completed_screenplay保留上一场用于衔接。只输出target_source_ids内source_parts的表达与疑义，按其顺序恰好覆盖一次，禁止输出其他批次或改写已保存内容。一个批次可以有多个场次，同一地点的连续动作不为批次刻意制造转场。不复述来源，不输出全片总结或重复论证规则。'
        system+='\n如果本批首场在同一地点、同一故事时间延续completed_screenplay的最后一场，在该场添加continues_previous_scene:true并严格沿用其location和time；确有故事转场则为false。此字段仅用于跨批次连续场次的合并，不能合并不同地点或不同时间。'
    def finish(value):
        if target_units is not None and isinstance(value.get('scenes'),list) and value['scenes']:
            first=value['scenes'][0]
            if isinstance(first,dict) and 'continues_previous_scene' in first:
                if not isinstance(first['continues_previous_scene'],bool):raise ValueError('continues_previous_scene需为布尔值')
                if first['continues_previous_scene']:
                    previous=(completed_context or {}).get('scenes',[])
                    if not previous or (first.get('location'),first.get('time'))!=(previous[-1].get('location'),previous[-1].get('time')):
                        first['continues_previous_scene']=False
        out=screenplay_expression.render(value,units,source_text=project['story'])
        setting_text='\n'.join(r['script_excerpt'] for r in out['script_production_settings'])
        out['script_consistency']=story_world.validate(project,out['script']+'\n'+setting_text)
        if workflows.enabled(project):out.update(workflows.documents(project,out['script'],value.get('workflow_plan',{})))
        return out
    previous=None;error=None;report=progress or (lambda message:None)
    for attempt in range(3):
        if attempt:report(f'剧本正在自动纠正 {attempt}/2：{error[:180]}')
        data=payload if not attempt else {**payload,'validation_error':error,'previous':previous}
        instruction=system if not attempt else system+'\n按validation_error修正上次回复，返回完整JSON。若仅导演表现建议违规，只改对应director_note，不改正文、source_ids或对白。保持原文完整覆盖与顺序；不得用删除场次、压缩动作或改写对白通过校验。'
        if attempt and isinstance(previous,str):
            # A malformed serialization has already written the expressions.
            # Repair its syntax within the same bounded call budget; do not
            # ask for a fresh adaptation or discard its valid values.
            instruction='你是JSON格式修复员。只返回一个完整有效JSON对象。修复invalid_json的引号、转义、逗号、括号及显然漏掉的结构键；场次对象的表达数组键为units。保留所有已有part_ids、kind、speaker、expression、audience_delivery、reason、场次、问题和导演备注字段值及顺序，不改写内容、不删条目、不补造字段值。缺少必要内容不能猜测。严格JSON，不输出思考或围栏。'
            data={'invalid_json':previous,'syntax_error':error,'schema':{'scenes':[{'location':'string','time':'string','director_note':'string','units':[{'part_ids':['原编号'],'kind':'原值','speaker':'原值','expression':'原值','audience_delivery':'原值','reason':'原值'}]}],'questions':[]}}
        try:previous=ai.ask(instruction,json.dumps(data,ensure_ascii=False))
        except ValueError as failure:
            if not str(failure).startswith('AI 未返回有效 JSON'):raise
            error=str(failure);previous=getattr(failure,'raw_response',None)
        else:
            if target_units is not None:
                from .screenplay_batches import normalize_continuation
                previous=normalize_continuation(previous,completed_context)
            try:
                out=finish(previous)
                return previous if raw else out
            except ValueError as failure:error=str(failure)
    raise ValueError('剧本自动纠正2次后仍未通过：'+error+'；已有剧本保留，可重试编写')


def write(project,core,native_script,progress=None,plan_only=False,approved_plan=None,on_event=None,metrics=None,force=False):
    from . import story_promo
    project=story_promo.for_writing(project)
    from . import ai
    with ai.writing_call_policy(len(project.get('story',''))):
        out=_write(project,core,native_script,progress,plan_only,approved_plan,on_event,metrics,force)
    stage='script_plan' if plan_only else 'script'
    out['creative_rule_application']={**creative_rules.audit(project,stage),'status':'原文直用，未调用AI改写' if project.get('story_policy')=='faithful' and not plan_only else '规则已传入本阶段AI；内容需复核'}
    return out


def _write(project,core,native_script,progress=None,plan_only=False,approved_plan=None,on_event=None,metrics=None,force=False):
    workflows.validate(project)
    script_tasks.validate(project)
    policy=project.get('story_policy','faithful')
    if policy not in POLICIES:raise ValueError('请选择原文直用、忠于故事剧本化或AI编排')
    titles={'故事梗概','人物小传','场景列表','完整剧本','剧本正文','三幕结构','五幕结构','故事架构','角色弧光','对白设计','叙事设计','导演叙事设计','节拍表','结构设计'}
    structure={'mode':project.get('script_mode'),'section_titles':list(dict.fromkeys(t for t in re.findall(r'【([^】]+)】',native_script) if t in titles))}
    if plan_only:return script_tasks.generate_plan(project,core,structure,progress)
    if script_tasks.task(project) not in ('auto','adapt'):
        return script_tasks.write_task(project,core,structure,approved_plan,progress,on_event=on_event,metrics=metrics,force=force)
    if policy=='faithful':
        # Story fidelity is enforced by the data path. No model rewrite can add
        # a person, borrow sample dialogue, reorder an event or change an ending.
        out={'script':project['story'],'script_policy':'faithful','script_changes':[],'script_policy_note':'故事原文完整保留为剧本正文，DirectorMaster规则用于镜头、美术与分镜设计，不增删情节。','script_consistency':story_world.validate(project,project['story'])}
        if workflows.enabled(project):
            from . import ai
            system='你是剧本创作规划助手。正文由程序直接保留，不输出或改写正文。只返回JSON {workflow_plan:...}，以script为唯一情节、对白与旁白来源。'+workflows.instruction(project)
            payload={'script':project['story'],'story_policy':'faithful','director_rules':core.get('统一电影提示词',''),'story_world_contract':story_world.contract(project),**workflows.context(project)}
            result=ai.ask(system,json.dumps(payload,ensure_ascii=False))
            try:out.update(workflows.documents(project,out['script'],result.get('workflow_plan',{})))
            except ValueError as error:
                repaired=ai.ask(system+'\n修正规划校验错误；正文原文不变。',json.dumps({**payload,'validation_error':str(error),'previous':result},ensure_ascii=False))
                out.update(workflows.documents(project,out['script'],repaired.get('workflow_plan',{})))
        return out
    from . import ai,character_profiles
    # Native Script contains illustrative scene content as well as structure.
    # Keep only structural headings in the model's input so that example scenes
    # cannot be mistaken for the user's source material or its change history.
    if policy=='screenplay':
        if on_event is not None:
            from . import screenplay_batches
            return screenplay_batches.generate(project,core,structure,progress,on_event,metrics,force)
        return adapt(project,core,structure,progress)
    system='''你是遵循DirectorMaster规则的创意编剧。只输出JSON {script:string,changes:[{type:string,description:string}],approach:string}。
用户选择AI编排模式：输入故事是参考素材，允许在给定导演、题材、时代、受众、片长及剧本模式的范围内创造性组织结构、重排事件、补充转折与对白。保持素材的核心主题与关键人物可辨识，禁止复制规则文件的范例台词或把范例人物当作用户人物。遵循参数给定的导演语言和叙事规则，不能以“规则允许”作为脱离用户素材的理由。完整输出可读、可编辑的剧本正文，区分场景、动作、对白和画外音，适合之后分镜。
逐项列出相对于reference_story原文的新增、删减、重排和改写，不能声称未改动。改动清单只与用户参考故事比较：规则中的范例、模板和结构标题不属于用户情节，不能将“不采用模板里的情节”列为对原故事的删减或改写。用户指定duration_seconds是本次实际片长；规则中的范例片长不能覆盖它。
人物身份、年龄、发型、服饰分别归属本人，不能将另一人物的特征移到主角；童年与成年/高中阶段分开。已有角色造型只是角色身份依据，非剧情梗概。character_personalities提供稳定性格、社交方式、情绪反应、习惯、价值观与动机，参考其设计角色选择和反应，用户设定应保留，推断建议不得冒充原文事实。不要把片长不足解决为动作倍速；素材较多则主动收束创作范围并在changes说明。'''+workflows.instruction(project)+'\n'+script_tasks.instruction(project)
    system+=creative_rules.instruction(project,'script')
    system+='\n严格遵守 story_world_contract：保留原故事时代与技术条件，导演风格不是添加时代器物的许可；仅在 world_change_allowed=true 时按 target_world 进行明确世界观改编。原文穿越者的前世知识不是当前世界中存在现代实物的证据。正文与镜头描述一律自然实时，禁止慢镜、慢放、倍速等速度变化。'
    payload={'reference_story':project['story'],'duration_seconds':project['duration'],'script_mode':project.get('script_mode'),'director_parameters':project.get('parameters',{}),'director_rules':core['统一电影提示词'],'native_script_structure_reference':structure,'character_designs':[{k:a.get(k) for k in ('name','age','description','costume','personality')} for a in project.get('assets',[]) if a.get('kind')=='character' and a.get('visual_profile')],'character_personalities':[{'name':a['name'],'features':character_profiles.personality_notes(a)} for a in project.get('assets',[]) if a.get('kind')=='character'],'story_world_contract':story_world.contract(project),**workflows.context(project)}
    def finish(value):
        script=str(value.get('script','')).strip()
        if not script:raise ValueError('AI编排未返回剧本正文')
        changes=value.get('changes',[])
        if not isinstance(changes,list) or any(not isinstance(c,dict) or not c.get('description') for c in changes):raise ValueError('AI编排缺少有效的改动说明')
        if script!=project['story'] and not changes:raise ValueError('AI编排改变了故事，却未列出新增或改动')
        out={'script':script,'script_policy':'creative','script_changes':changes,'script_policy_note':str(value.get('approach','AI参考原故事，依照DirectorMaster规则进行创意编排。'))}
        out['script_consistency']=story_world.validate(project,script)
        if workflows.enabled(project):out.update(workflows.documents(project,script,value.get('workflow_plan',{})))
        return out
    result=ai.ask(system,json.dumps(payload,ensure_ascii=False))
    if not workflows.enabled(project):
        # Repair newly detected world/timing violations even in the original
        # workflow; retain the existing strict errors for missing change logs.
        try:story_world.validate(project,str(result.get('script','')))
        except ValueError as error:
            repaired=ai.ask(system+'\n修正时代与自然时序校验错误，保持故事世界观。',json.dumps({**payload,'validation_error':str(error),'previous':result},ensure_ascii=False))
            return finish(repaired)
        return finish(result)
    try:return finish(result)
    except ValueError as error:
        repaired=ai.ask(system+'\n修正剧本及创作规划校验错误。',json.dumps({**payload,'validation_error':str(error),'previous':result},ensure_ascii=False))
        return finish(repaired)
