"""Bounded, resumable screenplay extraction with incremental delivery."""
import copy
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor,wait,FIRST_COMPLETED
from . import ai,asset_profiles as ap,character_profiles as cp,script_source as ss,visual_schema as vs,scene_identity

CONCURRENCY=2
ASSESSMENT_GROUP_SIZE=3
SINGLE_PASS_MAX_ASSETS=6
SINGLE_PASS_MAX_CHARACTERS=4000
CONTEXT_VERSION='asset-context-v2'


def recoverable_batch_error(error):
    return any(word in str(error).lower() for word in ('json','截断','输出','max_tokens','token','超时','timeout','timed out'))


def blocks(script):
    # Preserve complete scenes (including nearby people and pronoun antecedents).
    starts=list(re.finditer(r'(?m)^\s*第\s*[\d一二三四五六七八九十百]+\s*场[^\n]*',script))
    if starts:
        offsets=[0]+[m.start() for m in starts if m.start()>0]+[len(script)]
        parts=[script[a:b] for a,b in zip(offsets,offsets[1:])]
    else:
        parts=re.split(r'\n\s*\n',script)
        if len(parts)==1:parts=script.splitlines(keepends=True)
    return [{'id':f'B{i+1:03d}','text':p} for i,p in enumerate(parts) if p.strip()]


def context(script,sections,asset):
    if len(script)<=1800:return script
    aliases=[asset['name']]+[a for a in (asset.get('aliases') or []) if isinstance(a,str) and len(a)>=2 and a in script]
    hints={h for h in (asset.get('script_block_ids') or []) if isinstance(h,str)}
    chosen={i for i,b in enumerate(sections) if b['id'] in hints or any(a in b['text'] for a in aliases)}
    if not chosen:return script
    # For paragraph-form scripts retain two neighbors on each side; never
    # truncate a source block or remove other characters from ownership context.
    scene_form=bool(re.search(r'(?m)^\s*第\s*[\d一二三四五六七八九十百]+\s*场',script))
    if not scene_form:chosen={j for i in chosen for j in range(max(0,i-2),min(len(sections),i+3))}
    return '\n\n'.join(b['text'] for i,b in enumerate(sections) if i in chosen)


def context_hash(body,asset,inventory):
    identity=sorted((a['kind'],a['name']) for a in inventory)
    return hashlib.sha256(json.dumps([CONTEXT_VERSION,body,asset['kind'],asset['name'],identity],ensure_ascii=False).encode()).hexdigest()


def source_index(sections,assets):
    """One local traversal allocates source blocks to known element notebooks."""
    entries=[{'kind':a['kind'],'name':a['name'],'script_block_ids':[]} for a in assets]
    for block in sections:
        for item,asset in zip(entries,assets):
            names=[asset['name']]+[s for s in (asset.get('aliases') or []) if isinstance(s,str) and len(s)>=2]
            if any(name in block['text'] for name in names):item['script_block_ids'].append(block['id'])
    return entries


def reusable(project,existing,context_key,others):
    if existing.get('profile_source_type')!='script' or not existing.get('visual_profile'):return None
    if existing.get('is_protagonist') and 'footwear' not in existing['visual_profile'].get('groups',{}).get('outfit',{}).get('fields',{}):return None
    same_script=existing.get('profile_source_hash')==cp.source_hash(project,existing) and not existing.get('profile_stale')
    if not same_script and existing.get('profile_context_hash')!=context_key:return None
    try:
        profile=ap.normalize(existing['visual_profile'],project,existing,others)
        return {**ap.update_fields(existing,profile,existing.get('narrative_context',''),cp.source_hash(project,existing)),'profile_context_hash':context_key}
    except ValueError:return None


def expand_profile(item):
    if isinstance(item.get('visual_profile'),dict):return item['visual_profile']
    profile=vs.blank(item['kind'],item['name'])
    fields=item.get('fields')
    if not isinstance(fields,list):raise ValueError('批量回复缺少本元素的外观字段')
    for row in fields:
        if not isinstance(row,list) or len(row)<2 or row[0] not in vs.labels(item['kind']):raise ValueError('批量外观字段格式或分类无效')
        group,key=row[0].split('.')
        profile['groups'][group]['fields'][key]={'value':row[1],'source':row[2] if len(row)>2 else 'suggested','evidence':row[3] if len(row)>3 else '','owner':item['name']}
    if item['kind']=='character':profile['other_age_stages']=item.get('other_age_stages',[])
    return profile


def extract(project,progress=None,on_asset=None,metrics=None,force=False):
    progress=progress or (lambda message:None);on_asset=on_asset or (lambda event:None)
    script=ss.asset_text(project);source=ss.fingerprint(project);sections=blocks(script)
    previous=project.get('asset_analysis',{});sketches={};assessment_mode=False
    omitted=copy.deepcopy(previous.get('omitted_scenes',[]))
    if not force and previous.get('source_hash')==source and previous.get('scene_rules')==scene_identity.RULE_VERSION and isinstance(previous.get('inventory'),list):
        inventory=copy.deepcopy(previous['inventory'])
        assessment_mode=previous.get('strategy')=='cached_groups'
        progress('复用当前剧本的元素清单，检查未完成或已变化的档案')
    else:
        known=scene_identity.known_assets(project.get('assets',[]))
        assessment_mode=len(known)>SINGLE_PASS_MAX_ASSETS or len(script)>SINGLE_PASS_MAX_CHARACTERS
        progress('正在通读整份剧本，归集各元素资料缓存' if assessment_mode else '正在一次预读整份剧本，批量提取全部元素的外观与性格')
        system='''你是剧本资产分析员，只输出JSON {assets:[{name,kind:character|scene|prop,description,narrative_context,aliases:[],script_block_ids:[]}]}。
script_blocks是唯一事实来源。列出可见角色、实际场景、重要道具；只电话音或画外音且从不出镜者不建立可见角色。description只写自身简短外观，经历归narrative_context。角色年龄阶段分开；识别主角并返回is_protagonist布尔值；主角需要从头到脚的完整造型细节；不得把其他人物外貌移来，学生不默认校服。
场景以一个实际拍摄空间为单位。蒙太奇/回忆段包含小学门口、小巷、童年家中时必须分别建立场景；县中教室、家中、夜间街道必须分开；医院诊室与走廊、轿车内与事故路边也分开。绝不把整段标题作为地点名，不用／、/、|拼接多个地点。客厅和玄关可同属一套住宅，但需要独立空间画面时仍分开，名称补全所属家庭/建筑。重复出现的同一空间复用同一资产；不同年龄/昼夜只作可变状态，环境真的改变时记录独立版本。
只在对白/画外音中提及而不展示的地点不建资产。没有独立画面、没有关键动作且可依附主场景的次要过场，可省略独立场景资产；关键剧情、动作、连续性或实际需要生成环境图的空间必须保留。对省略地点返回omitted_scenes:[{name,reason,script_block_ids}]，写清原因；这仅省略资产，不删除剧本情节或镜头。
已有元素沿用existing_assets名称和类型避免重复，当前剧本未出现者不添加。aliases只填剧本实际使用的本元素别名。script_block_ids列出本元素出场、外观、性格、对白、动作或代称相关的全部原文块id，包括相关设定块，不要只选首次出现。source_quotes逐字摘录属于本元素的关键外观、性格、动作与对白短句，按出现顺序去重，保留不同年龄、衣着和状态；不要重复整场剧本。不要在此步骤填写详细visual_profile。'''
        payload={'camera_art_scheme':project.get('production_scheme',{}),'style_rule':'原文为事实依据；方案只约束suggested的时代、画风、材质及色彩，不覆盖explicit或user字段。','script_blocks':sections,'existing_assets':[{k:a.get(k) for k in ('name','kind','is_protagonist')} for a in known],'asset_source_index':source_index(sections,known),'feature_schema':{kind:vs.labels(kind) for kind in ('character','scene','prop')}}
        batch_system=system.replace('不要在此步骤填写详细visual_profile。','')+'''
先按元素身份建立独立的资料缓存，按script_blocks顺序通读一遍：每读到本元素的描写、动作、对白或代称，归入自己的缓存；新出现的可见角色、场景或道具建立新缓存。asset_source_index是已有元素的初步定位，需核实并补齐，不能因此漏掉其他段落、代称或新元素。角色、场景、道具不能串用特征。同一角色童年与成年分别归档。
通读完成后综合每个缓存的全部依据，再写最终fields。明确处理时序：当前年龄阶段与当前衣着不能叠加过去阶段；人物换衣、环境昼夜或道具状态变化记在narrative_context，不把互斥状态叠在同一身份设定。原文真的矛盾而无法判断时保留unknown并在narrative_context说明，不能凭空选择事实。保留每个缓存全部相关script_block_ids，并在source_quotes数组中逐字摘录仅属于本元素的外观、性格、动作与对白短句；不重复整场内容，不引用其他元素的外观。
同一次读取中为所有资产填写自身外观与角色性格，输出中每个asset新增fields数组：[["分组.字段","简短中文值","explicit或suggested","原文逐字短句"]]，角色还可有other_age_stages:[{label,age,note}]。不输出重复的visual_profile树、owner或总描述。字段路径来自feature_schema；unknown或未指定字段省略，由本地程序补齐。要覆盖角色六类外观（主角从头到脚，覆盖上衣、下装、四肢和鞋袜，缺失仅标suggested）及独立性格五字段、场景六类、道具五类，已知特征不得遗漏。
原文明示外观为explicit并附属于本元素的逐字原句；推断性格或独立克制造型补充为suggested且引用为空。性格从动作对白推断时也标suggested。不要把故事经历、镜头安排或疾病作为外观。不转移别人发色/服装/性别/年龄，学生不默认校服；童年与成年分阶段。特殊标志、随身标志物、发光粒子形变未写时省略，不虚构。场景和道具只写自身物理视觉特征。每个value简短明确，控制输出体积，优先完整覆盖所有元素而非重复叙事。existing_assets只用于名称对齐，不作为外貌来源。
'''
        inventory_payload={k:v for k,v in payload.items() if k!='feature_schema'}
        if assessment_mode:
            with ai.asset_call_policy('inventory',metrics,max_tokens=8192):answer=ap.request_profile(system,inventory_payload)
        else:
            try:
                with ai.asset_call_policy('batch',metrics,max_tokens=16384):answer=ap.request_profile(batch_system,payload)
            except ValueError as error:
                # Timeout or truncation falls back to a smaller cached inventory
                # instead of discarding the entire task and asking users to restart.
                if not recoverable_batch_error(error):raise
                assessment_mode=True
                progress('整批回复超时或不完整，改为保存资料缓存并分组评估')
                with ai.asset_call_policy('inventory_fallback',metrics):answer=ap.request_profile(system,inventory_payload)
        if not isinstance(answer.get('assets'),list):raise ValueError('AI 未返回剧本元素清单，请重新提取')
        progress('正在按全部剧本段落查漏出镜人物、实际场景与动作道具')
        coverage_system='''你是剧本资产清单查漏员。只输出JSON {assets:[{name,kind:character|scene|prop,description,narrative_context,aliases:[],script_block_ids:[],source_quotes:[]}]}。逐块核对script_blocks与已有inventory，只返回遗漏元素，没有遗漏返回空数组。所有出镜且有独立身份的人物都应保留；实际拍摄空间分别建立；人物手持、递交、读取、使用、检验或影响剧情因果的道具均保留，不只选最重要的一件。服饰配饰作为角色特征，背景固定陈设作为场景特征；需要独立特写或互动时才独立建道具。不把比喻、仅被提及但未展示的角色或地点当作资产，不新增剧本事实。不同地点禁止合并。已有同一实体或别名不得重复。source_quotes仅摘本元素逐字依据；script_block_ids必须来自输入。不要填写详细外观字段。'''
        with ai.asset_call_policy('inventory_coverage',metrics,max_tokens=8192):
            coverage=ap.request_profile(coverage_system,{'script_blocks':sections,'inventory':answer['assets'],'omitted_scenes':answer.get('omitted_scenes',[])})
        if not isinstance(coverage.get('assets'),list):raise ValueError('资产清单查漏未返回有效结果，请继续提取')
        if coverage['assets']:
            answer['assets'].extend(coverage['assets']);assessment_mode=True
        inventory,filtered=scene_identity.normalize_inventory(answer['assets'])
        omitted=[a for a in answer.get('omitted_scenes',[]) if isinstance(a,dict) and a.get('name') and a.get('reason')]+filtered
        sketches={(a.get('kind'),a.get('name')):a for a in inventory if isinstance(a,dict) and isinstance(a.get('name'),str)}
    inventory=list({(a['kind'],a['name']):{k:copy.deepcopy(a[k]) for k in ('kind','name','description','narrative_context','aliases','script_block_ids','source_quotes','is_protagonist') if k in a} for a in inventory if isinstance(a,dict) and a.get('kind') in ('character','scene','prop') and isinstance(a.get('name'),str) and a['name'].strip()}.values())
    total=len(inventory);results={};failures=[];reused=0
    others=project.get('assets',[])+inventory
    strategy='cached_groups' if assessment_mode else 'single_pass'
    on_asset({'type':'inventory','inventory':inventory,'source_hash':source,'total':total,'strategy':strategy,'scene_rules':scene_identity.RULE_VERSION,'omitted_scenes':omitted})

    def emit(item,is_reused=False):
        quotes=sketches.get((item['kind'],item['name']),item).get('source_quotes') or []
        quotes=list(quotes) if isinstance(quotes,list) else []
        if is_reused:
            old=next((a for a in project.get('assets',[]) if a['kind']==item['kind'] and a['name']==item['name']),{})
            quotes.extend(old.get('source_cache',{}).get('observations',[]))
        quotes.extend(field.get('evidence','') for field in vs.flatten(item['kind'],item['visual_profile']).values() if field.get('source')=='explicit')
        verified={cp.evidence_quote(script,quote) for quote in quotes if isinstance(quote,str)}-{''}
        item['source_cache']={**item.get('source_cache',{}),'observations':sorted(verified,key=script.find)}
        on_asset({'type':'asset','item':item,'source_hash':source,'completed':len(results),'total':total,'reused':reused,'failed':len(failures),'is_reused':is_reused})

    def extract_one(index,item,existing,body,key):
        began=time.monotonic()
        with ai.asset_call_policy('profile:'+item['kind'],metrics):
            update=ap.extract(project,existing,others,script_text=body)
        return index,{**item,**update,'profile_context_hash':key,'extraction_seconds':round(time.monotonic()-began,2)}

    def assess_group(group):
        # Whole-screenplay discovery has already completed. Assess only these
        # notebooks, sharing complete relevant blocks once within each request.
        related=[b for b in sections if any(b['text'] in args[3] for args in group)]
        notebooks=[]
        for _,item,existing,_,_ in group:
            quotes=item.get('source_quotes',[])
            notebooks.append({'name':item['name'],'kind':item['kind'],'is_protagonist':bool(existing.get('is_protagonist',item.get('is_protagonist'))),'script_block_ids':item['source_cache']['script_block_ids'],'source_quotes':[q for q in quotes if isinstance(q,str) and cp.evidence_quote(script,q)],'user_fields':{k:v for k,v in vs.flatten(item['kind'],ap.user_profile(existing)).items() if v.get('source')=='user'}})
        system='''根据已通读剧本归集的element_notebooks，综合评估本组所有元素。只输出JSON {assets:[{name,kind,narrative_context,fields:[["分组.字段","简短中文值","explicit或suggested","逐字依据"]],other_age_stages:[]}]}。
每个场景只包含一个指定的实际空间；同一蒙太奇中的教室、家中、街道分别取自身环境，不串用其他地点的建筑、光照、材质、陈设。不要把对另一地点的原句归为本地点特征。没有写明的环境按unknown或克制建议处理。
仅评估element_notebooks指定的名称和类型，完整返回本组每个元素。script_blocks是唯一事实来源，缓存摘录用于定位，必须结合完整相关段落核对人物身份、代称、年龄和状态。其他人物的发色、服装和外貌不得移用。fields路径来自feature_schema；省略unknown字段，本地会补齐。主角从头到脚覆盖头发面部、躯干四肢、上衣下装与鞋袜，缺失项标suggested、空引用；覆盖角色六类外观与独立性格、场景六类、道具五类。
原文明示为explicit并逐字引用属于本元素的短句；性格推断与克制造型补充为suggested且依据为空。保留用户字段。description不写经历；剧情、换衣、昼夜与不同状态放narrative_context。童年与成年分开，不叠加不同阶段的外观。真正矛盾无法判断的字段留unknown。学生不默认校服；特殊标志、随身物件、粒子发光形变原文未写不虚构。所有字段简短，直接输出最终结果，不重复剧本、资料缓存或完整profile树。'''
        began=time.monotonic()
        with ai.asset_call_policy('assessment_group',metrics,max_tokens=8192):
            answer=ap.request_profile(system,{'camera_art_scheme':project.get('production_scheme',{}),'style_rule':'方案指导建议特征，不改变原文明示事实。','element_notebooks':notebooks,'script_blocks':related,'feature_schema':{kind:vs.labels(kind) for kind in {a[1]['kind'] for a in group}},'other_identities':[{'name':a['name'],'kind':a['kind']} for a in inventory]})
        if not isinstance(answer.get('assets'),list):raise ValueError('分组输出缺少元素清单')
        return answer['assets'],round(time.monotonic()-began,2)

    pending=[]
    for index,item in enumerate(inventory):
        existing=next((a for a in project.get('assets',[]) if a['kind']==item['kind'] and a['name']==item['name']),{**item,'visual_description_source':'script'})
        body=context(script,sections,item);key=context_hash(body,item,inventory)
        item['source_cache']={'script_block_ids':[b['id'] for b in sections if b['text'] in body],'excerpt':body,'context_hash':key}
        update=None if force else reusable(project,existing,key,others)
        if update:
            reused+=1;results[index]={**item,**update};emit(results[index],True)
        else:
            try:
                raw=expand_profile(sketches.get((item['kind'],item['name']),{}))
                profile=ap.normalize(ap.preserve_user_fields(raw,existing),project,existing,others)
                update=ap.update_fields(existing,profile,item.get('narrative_context',''),cp.source_hash(project,existing))
            except (ValueError,KeyError,TypeError):pending.append((index,item,existing,body,key))
            else:results[index]={**item,**update,'profile_context_hash':key};emit(results[index])

    def report(inflight=()):
        names='、'.join(inventory[index]['name'] for index in inflight)
        progress(f'已完成 {len(results)}/{total} 个元素（复用 {reused}，失败 {len(failures)}）'+('；正在提取：'+names if names else ''))

    work_items=[('group',pending[i:i+ASSESSMENT_GROUP_SIZE]) for i in range(0,len(pending),ASSESSMENT_GROUP_SIZE)] if assessment_mode else [('single',[args]) for args in pending]
    def fail(index,error):
        failure={'name':inventory[index]['name'],'kind':inventory[index]['kind'],'error':str(error)}
        failures.append(failure)
        on_asset({'type':'failure','failure':failure,'source_hash':source,'completed':len(results),'total':total,'reused':reused,'failed':len(failures)})

    # Groups and individual repairs share a single two-worker pool, so splitting
    # a failed group never expands concurrency or re-reads the full inventory.
    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        active={}
        def fill():
            while work_items and len(active)<CONCURRENCY:
                mode,group=work_items.pop(0)
                future=pool.submit(assess_group,group) if mode=='group' else pool.submit(extract_one,*group[0])
                active[future]=(mode,group)
        def report_active():report(args[0] for _,group in active.values() for args in group)
        fill();report_active()
        while active:
            done,_=wait(active,timeout=1,return_when=FIRST_COMPLETED)
            if not done:continue
            for future in done:
                mode,group=active.pop(future)
                try:answer,seconds_or_result=future.result()
                except Exception as error:
                    if mode=='group' and recoverable_batch_error(error):
                        work_items.extend(('single',[args]) for args in group)
                    else:
                        for args in group:fail(args[0],error)
                else:
                    if mode=='single':results[answer]=seconds_or_result;emit(seconds_or_result)
                    else:
                        returned={(a.get('kind'),a.get('name')):a for a in answer if isinstance(a,dict)}
                        for args in group:
                            index,item,existing,_,key=args
                            try:
                                raw=expand_profile(returned.get((item['kind'],item['name']),{}))
                                profile=ap.normalize(ap.preserve_user_fields(raw,existing),project,existing,others)
                                update=ap.update_fields(existing,profile,returned[(item['kind'],item['name'])].get('narrative_context',item.get('narrative_context','')),cp.source_hash(project,existing))
                            except (ValueError,KeyError,TypeError):work_items.append(('single',[args]))
                            else:
                                results[index]={**item,**update,'profile_context_hash':key,'extraction_seconds':seconds_or_result};emit(results[index])
            fill();report_active()
    return {'assets':[results[i] for i in sorted(results)],'inventory':inventory,'failures':failures,'total':total,'reused':reused,'source_hash':source,'source_type':'script','strategy':strategy,'scene_rules':scene_identity.RULE_VERSION,'omitted_scenes':omitted}
