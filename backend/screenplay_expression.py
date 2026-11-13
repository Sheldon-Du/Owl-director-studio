"""Filmable expressions with immutable provenance, not literal-filled action text."""
import hashlib
import re
from . import story_world

DOC_KEYS=('script_source_view','script_production_settings','script_expression_review','script_questions','script_source_history')
KINDS=('动作','对白','画外音','场景描述','制作设定','音效')

INSTRUCTION='''
本次忠实剧本化使用两层：source_parts逐字保管原文，expression是独立的可拍摄正文。最终JSON格式：
{"scenes":[{"location":"单一具体地点","time":"故事内时间","director_note":"拍摄建议","units":[{"part_ids":["S001-P1"],"kind":"动作","speaker":"","expression":"简明可表演表达","audience_delivery":"required","reason":"表达选择的依据"}]}],"questions":[{"part_ids":["S001-P1"],"question":"需人工决定的问题"}]}。
kind单选动作、对白、画外音、场景描述、制作设定或音效；audience_delivery单选required、visible或background。禁止把选项拼成“动作|对白”等字符串。一条unit仅对应一种表达，多种表达要分条并各自引用独立原文片段，不重叠分配；part_ids使用source_parts的P编号，不另外加Q编号，同一个引文片段不能同时归动作与对白。
所有part_ids按给定顺序恰好使用一次，允许合并连续片段。不输出原文副本；原文永远由程序保存。覆盖记录仅证明去向，不等于语义忠实。
动作和场景描述写当下可见内容；忠实保留执行者、对象、具体动作、时间跨度、结果及因果，不添加关键行动。原文“她说：”可与其对白片段一起引用为一条对白，不强行变成无画面价值的独立动作。
对白只引用一条quotation_type=对白或广播原句，可以附相邻说话归属叙述，由程序回填原句，不能新增或改写对白。speaker必须依据原文，广播不能指派主角；未知则标待确认并列questions，不能猜人名。
引号不等于发话：术语、书名、画面文字、内心原句、动物拟声可分别作为可见文字、画外音、制作设定或音效。引用词语可合并邻近叙述，不能将“嫩叶”等词单独让人物说出口。音效与人物对白分开。
关键内心、回忆、因果信息无法通过既有动作表达时使用画外音，保留叙述身份与人物所知。不把背景或记忆改成新发生的行动，也不把每句文学叙述逐字塞入动作或旁白。
外貌、服装、环境、静态时代资料可作制作设定，expression必须忠实保留这些具体特征，reason写适用角色/场景；静态可见设定用visible，不需要观众独立获知的背景才用background。关键事件、人物选择或因果资料不能藏入background；观众必须获知的事实需写进动作/画外音等正文，audience_delivery=required。
未明确的外貌和衣物保持未明确，不擅自设计；导演建议只在director_note。自然实时，不慢镜、倍速、补造事件或删剧情凑时长。有争议的转换列questions，状态保持待人工核对。
仅输出最终完整JSON对象，不输出思考、方案说明、示例、代码围栏或省略号。字符串中的英文双引号必须转义；引文表述优先中文引号。同一事项的连续叙述或术语片段可以合并，完整保留细节，不机械为每个part另写一条。reason只写简明表达依据，导演参数范例与故事不一致直接遵守原文，不反复论证为何未采用范例器物。
'''


def render(value, units, source_text=None):
    from . import story_writing as sw
    # IDs, ordering and exact source storage are checked independently of text.
    issues=[];locked=None
    try:locked=sw.locked_parts(value,units,strict_dialogue=False)
    except ValueError as error:issues.append(str(error))
    for scene in value.get('scenes',[]) if isinstance(value.get('scenes'),list) else []:
        for item in scene.get('units',[]) if isinstance(scene,dict) and isinstance(scene.get('units'),list) else []:
            if not isinstance(item,dict):continue
            prefix=str(item.get('part_ids'))
            if item.get('kind') not in KINDS:issues.append(prefix+'：kind='+str(item.get('kind'))+' 无效。类型需单选动作、对白、画外音、场景描述、制作设定或音效；禁止用|拼接。动作和对白分条，引用各自片段且不重叠')
            if not isinstance(item.get('expression'),str) or not item['expression'].strip():issues.append(prefix+'：需填写非空expression；不能仅给原文加标签')
    if issues:raise ValueError('\n'.join(issues))
    parts=sw.source_parts(units);by_id={p['id']:p for p in parts}
    body=[];mapping=[];settings=[];notes=[];questions=value.get('questions',[])
    if not isinstance(questions,list):raise ValueError('剧本疑义需为questions数组')
    for q in questions:
        if not isinstance(q,dict) or not isinstance(q.get('question'),str) or not q['question'].strip() or not isinstance(q.get('part_ids'),list) or not q['part_ids'] or any(k not in by_id for k in q['part_ids']):raise ValueError('剧本疑义需含有效part_ids和question')
    unresolved=[]
    for i,scene in enumerate(locked['scenes'],1):
        if not scene['units']:raise ValueError('剧本化场次缺少正文或设定')
        location=str(scene.get('location') or '地点未明确');clock=str(scene.get('time') or '时间未明确')
        body.append(f'第{i}场 · {location} · {clock}')
        note=str(scene.get('director_note',''))
        if story_world.speed_change(note):raise ValueError(f'第{i}场导演表现建议不得使用慢放或倍速，动作按自然时间发生；仅修改director_note')
        if note:notes.append({'scene':i,'note':note})
        for n,item in enumerate(scene['units'],1):
            kind=item.get('kind');expr=item.get('expression');ids=item['part_ids']
            if kind not in KINDS:raise ValueError('可拍摄表达类型需为'+ '|'.join(KINDS))
            if not isinstance(expr,str) or not expr.strip():raise ValueError('、'.join(ids)+'：需填写非空expression；不能仅给原文加标签')
            expr=expr.strip();original=''.join(by_id[k]['text'] for k in ids)
            delivery=item.get('audience_delivery')
            if delivery not in ('required','visible','background'):raise ValueError('、'.join(ids)+'：需明确audience_delivery=required|visible|background')
            reason=item.get('reason')
            if not isinstance(reason,str) or not reason.strip():raise ValueError('、'.join(ids)+'：需记录表达或设定交付的reason')
            if kind=='场景描述' and delivery=='background':
                kind='制作设定'
                unresolved.append({'part_ids':ids,'question':'该场景描述被标为背景，已保管为候选制作设定；请核对是否包含必须让观众得知的事实，必要时写入正文：'+expr})
            elif kind!='制作设定' and delivery=='background':
                delivery='required'
                unresolved.append({'part_ids':ids,'question':'模型把实际'+kind+'标为背景，字段冲突；表达已完整保留在正文交付，确认前核对用途：'+expr})
            if kind=='制作设定' and delivery=='required':raise ValueError('观众必须此刻获知的信息需在正文交付，不能仅留在制作设定')
            if story_world.speed_change(expr) and not story_world.speed_change(original):raise ValueError('剧本表达不得通过速度变化改变动作时间')
            speaker=str(item.get('speaker') or '').strip()
            required_quotes=[]
            for key in ids:
                part=by_id[key]
                if part.get('quotation_type')!='对白或广播' or not part.get('quotation_id'):continue
                original_unit=next(u['text'] for u in units if u['id']==part['source_id'])
                prefix=original_unit[:original_unit.find(part['text'])]
                if re.search(r'(?:说|问|喊|叫|答|广播|念|喝)[^。！？]*[:：]\s*$',prefix):required_quotes.append(key)
            if required_quotes and kind!='对白':raise ValueError('、'.join(required_quotes)+'：原文明确说出口的对白必须保留原句并标为对白，不可改写或藏入动作/设定')
            if kind=='对白':
                spoken=[by_id[k] for k in ids if by_id[k]['quotation_type']=='对白或广播' and by_id[k]['quotation_id']]
                if len(spoken)!=1:raise ValueError('、'.join(ids)+'：对白必须对应一条原文人物话语，不得新增台词或将术语当对白')
                expr=next(q['text'] for row in sw.dialogue_contract(units) for q in row['literals'] if q['id']==spoken[0]['quotation_id'])
                if not speaker or speaker in ('未知','未明确','待确认'):speaker='待确认';unresolved.append({'part_ids':ids,'question':'请核对该原句的说话人：'+expr})
            row={'id':f'SC{i:03}-E{n:03}','scene':i,'location':location,'time':clock,
                'part_ids':ids,'source_ids':item['source_ids'],'source_quote':original,'kind':kind,
                'script_excerpt':expr,'audience_delivery':delivery,'reason':reason,'semantic_status':'pending_user_review'}
            mapping.append(row)
            if kind=='制作设定':settings.append(row)
            else:body.append('【'+kind+(' · '+speaker if speaker else '')+'】\n'+expr)
        body.append('')
    source=source_text if source_text is not None else '\n'.join(u['text'] for u in units)
    version=hashlib.sha256(source.encode()).hexdigest()
    return {'script':'\n\n'.join(body).strip(),'script_policy':'screenplay','script_changes':[],
        'script_adaptation_map':mapping,'script_director_notes':notes,
        'script_source_view':{'version':version,'text':source,'parts':parts,'alias_adjustments':locked.get('source_alias_adjustments',[])},
        'script_production_settings':settings,'script_questions':questions+unresolved,
        'script_expression_review':{'structure':'passed','semantic_fidelity':'pending_user_review','audience_delivery':'pending_user_review','actual_media':'not_generated'},
        'script_policy_note':'原文逐字保存在来源对照；正文是 AI 编写的可拍摄表达，静态资料另存制作设定。程序已核对来源覆盖、顺序和原句对白，表达忠实、信息交付与说话人需人工核对后确认；实际声画另行审查。'}


def confirm(project, acknowledged):
    docs=project.get('documents',{})
    if not docs.get('script_expression_review'):return
    if acknowledged is not True:raise ValueError('请人工核对剧本表达、来源对应、制作设定与疑义后确认')
    if '【对白 · 待确认】' in docs.get('script',''):raise ValueError('仍有说话人待确认，请先编辑对应对白标签，再确认剧本')
    docs['script_expression_review'].update(semantic_fidelity='user_confirmed',audience_delivery='user_confirmed',
        confirmed_script_hash=hashlib.sha256(docs['script'].encode()).hexdigest())
