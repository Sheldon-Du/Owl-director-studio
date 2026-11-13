"""Plan a compact whole-film overview, then checkpoint bounded visual work.

Every request retains the complete screenplay. Output batches follow an already
verified global plan, never arbitrary cuts of the screenplay or reordered events.
"""
import copy
import json
from . import storyboard_generation as sg, narration_visuals as nv, script_workflows
from . import creative_rules,storyboard_units

VERSION=1
BATCH_SIZE=3


def asset_context(project):
    # Planning needs known identity/appearance and its provenance priority,
    # not each asset's repeated source quotes, audit logs or generated media.
    from .frame_plans import compact_asset
    return [{**compact_asset(a),**{k:a[k] for k in ('age','gender','personality','costume') if a.get(k)}} for a in project.get('assets',[])]

COMPACT_SYSTEM='''你是遵守DirectorMaster规则的全片分镜统筹。完整阅读script_blocks、导演方案和美术规则，只输出严格JSON {"shots":[{"source_block_ids":["S0001"],"location":"单一具体地点","focus":"具体可见的画面焦点","natural_seconds":6}]}。
本轮仅生成紧凑全片汇总，每镜只写上述四个字段，不写visual_plan、完整提示词、原文副本、分析或围栏。后续另行完善画面方案。
按已确认剧本的银幕顺序覆盖所有role=content编号；context仅提供场景或时间背景。每条content编号连续，下条最早编号不得早于上条最后编号。声音与动作标签和正文保持相邻，不单独拍一个标签。长段或边界段落可复用编号，但事件不能重演，原句声音只能播放一遍。最多160镜。
先理解整场戏的事件、人物关系和情绪变化，再决定切镜。用一镜或少数必要镜头承载同一事件，不能按段落数、旁白句数、原生模板数量或目标时长机械拆镜。每个切镜应提供新可见信息或必要情绪变化。
完整保留原文事件、对白、旁白、结局和时代。旁白可用本段原文支持的说明画面与物件细节，不反复拍主角睡觉、呼吸或眼皮来填声音；插入画面不能发明重要经历或提前揭示未来事件。若旁白对应论文内容，可设计有依据的论文细节。地点写当前画面实际的单一地点。
遵守用户镜头与美术方向，长镜也需有效调度或情绪变化；不可机械轮换景别和运镜。画面与声音同时发生，估时取各自自然需求的较长值，不将并行内容机械相加；至少完整容纳原句朗读，不均分片长、不加速、不慢放，超过目标时长也保留全部内容。'''

CACHED_SYSTEM='''你是遵守DirectorMaster规则的分镜统筹。script_blocks是完整确认稿，unit_cache是程序按其表达标签建立的逐字内容缓存。完整阅读两者后只返回严格JSON：
{"shots":[{"execute_unit_ids":["缓存C编号"],"context_unit_ids":[],"result_unit_ids":[],"location":"单一具体地点","focus":"具体画面焦点","natural_seconds":6}],"unit_overrides":[]}。
不返回units、原文副本、状态长文或source_block_ids；程序按缓存ID回填。每个非背景缓存内容必须恰好execute一次，执行顺序保持剧本银幕顺序；context/result只能引用已有执行结果，背景需明确声明，不把动作漏掉。不同物理地点分开，整句对白或旁白仅由一镜承载。合并连续内容时仍完整保留动作和信息；按事件而不是段落数量决定切镜。
缓存粒度是工作稿粒度，须检查一个内容块是否包含需要分开承载的独立事件、状态改变或地点转移。必要时在unit_overrides中写{block_id,units:[{id:新唯一ID,quote:本块逐字连续片段,kind:action|dialogue|voiceover|information|text,story_time,start_state,end_state}]}并用新ID承载；拆分片段须按原序完整覆盖原块，不把整句声音切开。无必要就保留缓存ID。
静态背景可用unit_overrides把整个原块重分类为{ id:原缓存ID,whole_block:true,kind:context,delivery:background,context_reason:为什么无需独立交付或如何作为世界背景呈现 }，只能context引用，确认汇总前由人审查。观众必须此刻得知的信息仍须execute一次。概括已由动作表达时，应同镜承载信息与动作，避免额外重演。
完整保留原文的时代、身份、因果、事实与结局，不能复制规则范例人物道具。自然估时依据动作、完整原句和必要反应，画面与声音并行取所需较长值，顺序动作累计；不均分目标片长，不慢放、不加速，内容多可超目标时长。最多160镜。省略字段并非省略内容，提交前逐项核对所有缓存ID的承载。'''

VISUAL_SYSTEM='''你是遵守DirectorMaster方案的分镜导演。完整剧本和已经核对的全片汇总只提供背景，本轮仅完善targets指定镜头。不得改变任何镜头编号、所属原文、地点、焦点或银幕顺序。
只输出严格JSON {"plans":[{"index":1,"visual_plan":{"mode":"narration_illustration","image":"具体看得见的画面","anchors":["画面中可见的主体或物件"],"purpose":"提供的新信息或情绪作用","time_context":"当下／原文回忆说明","cut_reason":"此处切镜的必要性","evidence":[{"block_id":"本镜实际content编号","quote":"该段逐字原文依据"}]}}]}。不输出分析、围栏、其他镜头或完整提示词；每幅方案简明明确。
mode选present_action、narration_illustration或reaction。index必须使用targets里的全片编号，不能从1重新编号。原文依据必须逐字来自本镜，回忆或说明不能编造重要经历、对白、时代器物、人物关系或未来情节。image必须具体可见，不能只复述旁白。anchors是image中逐字出现的可见主体/物件短语，不是压力、学历等抽象词。遵守资产身份、场景空间、原生美术方向。
target_evidence_sources列出各镜允许引用的段落。evidence只选同一index下的block_id与text中的连续原句，不从全片导航、前后镜或场景标题摘取，不拼接省略的片段，不改标点。纠错时核对invalid_visual_plan：仅修正出错字段；若画面本身依赖别镜内容，连同相关画面字段一起修正，不能仅换证据掩盖该错误。
按事件信息和情绪变化组织画面；不能为每句旁白反复拍睡觉、呼吸、手指和眼皮。相邻方案不要重复静止反应。叙事时间与画面说明时间不同需明确标注，回到当前戏时保持人物、空间和动作衔接。已有合格画面方案不可重写。'''


def compact(project,prep,source,metrics,report):
    payload={**sg.planning_context(project),'script_blocks':source,'parameters':project['parameters'],'scheme':project['production_scheme'],
        'spec':script_workflows.spec(project),'director_rules':prep.get('core_prompt',''),'art_direction':prep.get('art',''),
        'assets':asset_context(project),
        'coverage_contract':{'required_content_ids':[b['id'] for b in source if b['role']=='content']}}
    cache=storyboard_units.content_cache(source,sg.shot_preflight.speech_sources({'source_excerpt':'\n'.join(b['text'] for b in source),'source_block_ids':[b['id'] for b in source]})) if storyboard_units.enabled(project) else None
    if cache is not None:payload['unit_cache']=cache
    for attempt in range(2):
        report('正在核对紧凑全片汇总的原文覆盖与顺序' if attempt else '正在完整阅读剧本，规划全片事件与镜头汇总（暂不输出详细画面方案）')
        answer=None
        try:
            system=CACHED_SYSTEM if cache is not None else COMPACT_SYSTEM
            system+=creative_rules.instruction(project,'storyboard_outline')
            system+=sg.revision_instruction(project)
            answer=sg.request(system,payload,'storyboard_outline_compact_repair' if attempt else 'storyboard_outline_compact',metrics)
            if cache is not None:answer=storyboard_units.from_cache(answer,cache,source)
            # This phase intentionally has no rich visual plan. Estimates are
            # corrected locally while complete speech stays cached verbatim.
            returned=answer.get('shots')
            if not isinstance(returned,list):raise ValueError('紧凑汇总需返回shots数组')
            raw=[{k:r.get(k) for k in ('source_block_ids','location','focus','natural_seconds')} if isinstance(r,dict) else r for r in returned]
            return sg.normalize_answer(project,{**answer,'shots':returned if storyboard_units.enabled(project) else raw},source)
        except ValueError as error:
            if answer is None and not str(error).startswith('AI 未返回有效 JSON'):raise
            if attempt:raise ValueError(str(error)+'；紧凑汇总未通过核对，已有草稿保留') from error
            invalid=answer.get('shots') if isinstance(answer,dict) else None
            payload.update(validation_error=str(error),invalid_outline=invalid,coverage_report=sg.coverage_report(invalid,source))


def seed_answer(project,prep,answer,source,metrics=None):
    """Keep a verified whole-film allocation, then isolate invalid visuals.

    This is also the checkpoint path for small overviews. Source/order/speech
    errors must still fail structural normalization and use the normal repair.
    """
    structural=copy.deepcopy(answer)
    for row in structural.get('shots',[]):
        if isinstance(row,dict):row.pop('visual_plan',None)
    outlines=sg.normalize_answer(project,structural,source)
    index={b['id']:b['text'] for b in source};candidates={};targets=[]
    for outline,raw in zip(outlines,answer['shots']):
        if not any(s['kind']=='voiceover' for s in outline.get('speech_sources',[])) and not raw.get('visual_plan'):continue
        targets.append(outline['index'])
        try:nv.review(outline,raw,index,outlines[outline['index']-2] if outline['index']>1 else None,required=True)
        except ValueError as error:
            candidates[str(outline['index'])]={'raw':copy.deepcopy(raw),'error':str(error)}
            if metrics:metrics({'phase':'storyboard_outline_visual_validation','index':outline['index'],'error':str(error)})
    return {'version':VERSION,'source_hash':sg.fingerprint(project),'preparation':copy.deepcopy(prep),
            'outlines':outlines,'visual_candidates':candidates,'visual_targets':targets}


def plan(project,prep,metrics=None,progress=None,draft=None,on_checkpoint=None):
    report=progress or (lambda m:None);emit=on_checkpoint or (lambda d:None)
    source=sg.blocks(project);source_hash=sg.fingerprint(project);source_index={b['id']:b['text'] for b in source}
    state=copy.deepcopy(draft) if draft else {'version':VERSION,'source_hash':source_hash,'preparation':copy.deepcopy(prep),'outlines':[]}
    if state.get('version')!=VERSION or state.get('source_hash')!=source_hash:raise ValueError('汇总草稿依据已改变，请重新创建分镜汇总')

    def save():
        targets=set(state.get('visual_targets',[o['index'] for o in state['outlines'] if any(s['kind']=='voiceover' for s in o.get('speech_sources',[]))]))
        total=len(targets)
        done=sum(o['index'] in targets and bool(o.get('visual_plan')) for o in state['outlines'])
        state.update(phase='visuals' if state['outlines'] else 'compact',total=total,completed=done)
        emit(copy.deepcopy(state))
    save()
    if not state['outlines']:
        state['outlines']=compact(project,prep,source,metrics,report)
        save()
    # Verify cached identities, evidence and complete coverage on continuation.
    outlines=state['outlines']
    verified=sg.normalize_saved(project,outlines,source)
    for old,new in zip(outlines,verified):
        if old.get('index')!=new['index'] or not old.get('id'):raise ValueError('汇总草稿镜头身份无效，请重新创建')
        new['id']=old['id']
        storyboard_units.keep(old,new)
        if old.get('estimate_adjustment'):new['estimate_adjustment']=copy.deepcopy(old['estimate_adjustment'])
    state['outlines']=outlines=verified
    candidates=state.setdefault('visual_candidates',{})
    pending=[o for o in outlines if (any(s['kind']=='voiceover' for s in o.get('speech_sources',[])) or str(o['index']) in candidates) and not o.get('visual_plan')]
    if metrics:metrics({'phase':'storyboard_outline_resume','saved_visuals':state['completed'],'remaining_visuals':len(pending),'total_shots':len(outlines)})
    payload={**sg.planning_context(project),'script_blocks':source,'all_outlines':outlines,'scheme':project['production_scheme'],
        'parameters':project['parameters'],'art_direction':prep.get('art',''),
        'assets':asset_context(project)}

    def request_group(group,repair=None,original=None):
        first,last=group[0]['index'],group[-1]['index']
        report(f'{"正在定点修正" if repair else "正在完善"}汇总第 {first}–{last} 镜的旁白画面（已保存 {state["completed"]}/{state["total"]} 套画面方案；保留完整剧本上下文）')
        body={**payload,'targets':group,'target_evidence_sources':[
            {'index':o['index'],'sources':[{'block_id':key,'text':source_index[key]} for key in o['source_block_ids'] if key in source_index]}
            for o in group]}
        if repair:body.update(validation_error=repair,repair_instruction='仅修正targets指定的画面方案，其余已保存结果保留')
        if repair and original and isinstance(original.get('visual_plan'),dict):body['invalid_visual_plan']=copy.deepcopy(original['visual_plan'])
        anchor_only=bool(original and isinstance(original.get('visual_plan'),dict) and repair and 'anchors与image' in repair)
        system=VISUAL_SYSTEM
        if anchor_only:
            body.update(invalid_visual_plan=original['visual_plan'],repair_instruction='只修改anchors，其他字段由程序保留。每个要点必须是invalid_visual_plan.image中逐字连续出现的具体可见名词短语，不总结、不换序、不添加词。')
            system='仅修正画面要点，返回严格JSON {"plans":[{"index":targets中的全片编号,"visual_plan":{"anchors":["从invalid_visual_plan.image逐字摘出的短语"]}}]}。只返回anchors，不重写image、evidence或其他字段；至少一个真实可见主体或物件。'
        response=sg.request(system+creative_rules.instruction(project,'storyboard_outline'),body,f'storyboard_outline_visual_{first}_{last}'+('_repair' if repair else ''),metrics)
        raw=response.get('plans')
        if not isinstance(raw,list):raise ValueError('画面批次需返回plans列表')
        expected={o['index'] for o in group};mapped={}
        for item in raw:
            index=item.get('index') if isinstance(item,dict) else None
            if anchor_only and isinstance(item,dict):
                patch=item.get('visual_plan',{});item={**original,'index':index,'visual_plan':{**original['visual_plan'],'anchors':patch.get('anchors') if isinstance(patch,dict) else None}}
            # A single-target repair sometimes restarts numbering at 1. Only
            # recover the identity when its literal evidence uniquely belongs
            # to this target across the complete saved overview. All other
            # visual validation remains mandatory.
            if len(group)==1 and len(raw)==1 and isinstance(item,dict) and index not in expected:
                evidence=item.get('visual_plan',{}).get('evidence') if isinstance(item.get('visual_plan'),dict) else None
                if isinstance(evidence,list) and evidence and all(isinstance(e,dict) and isinstance(e.get('quote'),str) and e['quote'].strip() and e.get('block_id') in source_index and e['quote'] in source_index[e['block_id']] for e in evidence):
                    candidates=[o['index'] for o in outlines if all(e['block_id'] in o['source_block_ids'] for e in evidence)]
                    if candidates==[group[0]['index']]:
                        item=copy.deepcopy(item);index=group[0]['index'];item['index']=index
                        if metrics:metrics({'phase':'storyboard_outline_visual_identity','requested_index':index,'returned_index':raw[0].get('index'),'basis':'unique_literal_source_evidence'})
            if isinstance(index,bool) or not isinstance(index,int) or index not in expected or index in mapped:raise ValueError('画面批次返回了重复、未知或无效的镜头编号')
            mapped[index]=item
        return mapped

    def apply_one(outline,item):
        if not item:raise ValueError(f'画面批次遗漏第{outline["index"]}镜')
        previous=outlines[outline['index']-2] if outline['index']>1 else None
        nv.review(outline,item,source_index,previous,required=True)
        candidates.pop(str(outline['index']),None)
        save()
        report(f'已保存 {state["completed"]}/{state["total"]} 套画面方案；可中断后继续')

    def batch(group):
        try:mapped=request_group(group)
        except ValueError as error:
            diagnostic=str(error)
            # Truly reduce the requested output; never repeat the same long
            # request. Timeouts/auth/connection failures stop immediately.
            if diagnostic.startswith('AI 调用失败') and not any(s in diagnostic for s in ('截断','finish_reason=length')):raise
            if len(group)>1:
                middle=len(group)//2
                batch(group[:middle]);batch(group[middle:]);return
            if diagnostic.startswith('AI 调用失败'):raise
            mapped=request_group(group,diagnostic)
        for outline in group:
            try:apply_one(outline,mapped.get(outline['index']))
            except ValueError as error:
                if metrics:metrics({'phase':'storyboard_outline_visual_validation','index':outline['index'],'error':str(error)})
                candidates[str(outline['index'])]={'raw':copy.deepcopy(mapped.get(outline['index']) or {}),'error':str(error)}
                save()
                fixed=request_group([outline],str(error),mapped.get(outline['index']))
                try:apply_one(outline,fixed.get(outline['index']))
                except ValueError as final:
                    candidates[str(outline['index'])]={'raw':copy.deepcopy(fixed.get(outline['index']) or mapped.get(outline['index']) or {}),'error':str(final)}
                    save()
                    raise ValueError(f'汇总第{outline["index"]}镜画面修正未通过：{final}；已保存方案保留，点击继续生成汇总') from final
    # A returned small-film overview already has usable visual work. Repair
    # only the failed target instead of generating a new whole-film answer.
    fresh=[]
    for outline in pending:
        candidate=candidates.get(str(outline['index']))
        if not candidate:
            fresh.append(outline);continue
        fixed=request_group([outline],candidate['error'],candidate['raw'])
        try:apply_one(outline,fixed.get(outline['index']))
        except ValueError as error:
            candidates[str(outline['index'])]={'raw':copy.deepcopy(fixed.get(outline['index']) or candidate['raw']),'error':str(error)}
            save()
            raise ValueError(f'汇总第{outline["index"]}镜画面修正未通过：{error}；已保存方案保留，点击继续生成汇总') from error
    for start in range(0,len(fresh),BATCH_SIZE):batch(fresh[start:start+BATCH_SIZE])
    result=sg.normalize_saved(project,outlines,source,review_visuals=True)
    for old,new in zip(outlines,result):
        new['id']=old['id']
        storyboard_units.keep(old,new)
        if old.get('estimate_adjustment'):new['estimate_adjustment']=copy.deepcopy(old['estimate_adjustment'])
    report(f'完整汇总已核对：{len(result)}镜，旁白画面方案{state["completed"]}套；等待人工确认')
    return result
