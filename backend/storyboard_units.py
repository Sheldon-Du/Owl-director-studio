"""A literal screenplay ledger with exactly one execution carrier per unit."""
import copy
import hashlib
import re

KINDS=('action','dialogue','voiceover','information','text','context')
MODES=('execute','context','result')
INSTRUCTION='''
本次启用剧情单元分配。除shots外同一次通读输出units:[{id:"U01",block_id:"S0001",quote:"该块逐字连续原文",kind:"action|dialogue|voiceover|information|text|context",story_time:"故事内时间",start_state:"单元发生前状态",end_state:"单元发生后状态"}]。
以一次动作执行或一次信息交付为单元，不机械按逗号切分。quote完整覆盖各content块的所有实质文字，不能伪造、遗漏细节或只摘公共词。对白/旁白的整条原句不得拆成多条单元；标签可作为context单元。每条单元只来自一个block；同块单元按原文顺序列出，不重叠。同文重复时增加offset（逐字quote在块内的起点字符位置）消除歧义。
每个shot增加carriers:[{unit_id:"U01",mode:"execute|context|result"}]。execute是真正执行动作/播放声音/呈现信息，每个非context单元必须恰有一个execute镜头；context只引用背景，不再表演；result只展示此前已执行的结果，不重演。单元引用需在shot.source_block_ids内，引用原文的顺序仍不能回跳；context/result只可引用本镜或此前已执行单元。标签context单元只使用context模式。
切镜必须服务叙事。先确定执行分配，再估自然时间；不同地点必须分开，整句声音只分到一个镜头。单元的story_time与镜头银幕顺序分开。不要照抄样例人物、道具或ID。
role=context的格式标签不需要写units，不是待执行剧情。覆盖整个content块的单元优先填whole_block:true并省略quote和offset，由程序从原文缓存回填；只有确需拆同一块时才用逐字quote及offset。实际content均须作为action、dialogue、voiceover、information或text交付一次，不可将其标context以省略。每个单元第一次承载必须execute，后续才可context/result。
整块缓存单元最简格式为{id,block_id,whole_block:true,kind}；story_time、start_state、end_state可以省略，程序填已写明的场次时间及尚未执行/已完成的执行状态，不能把这些程序状态当成实际人物空间状态。具体人物、道具、姿态及光声连续性在逐镜细化的continuity接口分析。优先用这个最简格式，避免重复描述每段原文。
'''


def enabled(project):return project.get('storyboard_method')=='source_units'


def content_cache(source,speech):
    spoken={s['id'].split('-Q')[0]:s['kind'] for s in speech if s['kind']!='quote'}
    result=[];label=''
    for block in source:
        if block['role']=='context':
            if re.match(r'^第.+场\s*·',block['text']):label=''
            heading=re.fullmatch(r'【([^·:：｜|】]+)(?:[^】]*)】',block['text'])
            if heading:label=heading[1].strip()
            continue
        kind=spoken.get(block['id']) or ('action' if label=='动作' else 'information')
        result.append({'id':'C-'+block['id'],'block_id':block['id'],'whole_block':True,'kind':kind})
    return result


def from_cache(answer,cache,source):
    """AI assigns immutable cache IDs; optional splits retain exact evidence."""
    value=copy.deepcopy(answer);units=copy.deepcopy(cache)
    changes=value.get('unit_overrides',[])
    if not isinstance(changes,list):raise ValueError('局部单元拆分须为unit_overrides数组')
    changed=set();blocks={b['id']:b for b in source}
    for change in changes:
        bid=change.get('block_id') if isinstance(change,dict) else None
        rows=change.get('units') if isinstance(change,dict) else None
        if bid not in blocks or blocks[bid]['role']!='content' or bid in changed or not isinstance(rows,list) or not rows:
            raise ValueError('局部拆分引用了无效或重复的内容块')
        changed.add(bid);replacement=[]
        for item in rows:
            if not isinstance(item,dict) or item.get('block_id',bid)!=bid:raise ValueError('拆分不得挪用其他段落')
            item={**item,'block_id':bid}
            if item.get('kind')=='context' and (item.get('delivery')!='background' or not isinstance(item.get('context_reason'),str) or not item['context_reason'].strip()):
                raise ValueError('背景单元需声明delivery=background及context_reason，供人工核对信息是否仍需交付')
            replacement.append(item)
        at=next((i for i,u in enumerate(units) if u['block_id']==bid),None)
        if at is None:raise ValueError('拆分目标不在缓存中')
        units[at:at+1]=replacement
    value['units']=units;lookup={u.get('id'):u for u in units};rank={b['id']:i for i,b in enumerate(source)}
    if not isinstance(value.get('shots'),list):raise ValueError('缓存汇总需包含shots数组')
    for row in value['shots']:
        if not isinstance(row,dict):raise ValueError('汇总条目需为对象')
        refs=[]
        for key,mode in (('execute_unit_ids','execute'),('context_unit_ids','context'),('result_unit_ids','result')):
            ids=row.get(key,[])
            if not isinstance(ids,list) or any(not isinstance(k,str) or k not in lookup for k in ids):raise ValueError('汇总引用了无效缓存ID：'+key)
            refs.extend({'unit_id':k,'mode':mode} for k in ids)
        row['carriers']=refs
        # The authoritative references generate the redundant source IDs.
        ids={lookup[c['unit_id']]['block_id'] for c in refs if c['mode']=='execute'}
        if not ids:ids={lookup[c['unit_id']]['block_id'] for c in refs}
        row['source_block_ids']=sorted(ids,key=rank.get)
    return value


def without_format_units(answer,source):
    """Formatting-only context is not an action or information to perform."""
    value=copy.deepcopy(answer);contexts={b['id']:b['text'] for b in source if b['role']=='context'}
    if not isinstance(value.get('units'),list):return value
    removed={u.get('id') for u in value['units'] if isinstance(u,dict) and isinstance(u.get('id'),str) and u['id'] and u.get('kind')=='context'
             and u.get('block_id') in contexts and u.get('quote')==contexts[u['block_id']]}
    if removed:
        value['units']=[u for u in value['units'] if not isinstance(u,dict) or u.get('id') not in removed]
        for row in value.get('shots',[]):
            if isinstance(row,dict) and isinstance(row.get('carriers'),list):
                row['carriers']=[c for c in row['carriers'] if not isinstance(c,dict) or c.get('unit_id') not in removed or c.get('mode')!='context']
    return value


def substantive(text):
    return {i for i,ch in enumerate(text) if ch.isalnum()}


def bind(answer,source,outlines,speech):
    raw=answer.get('units')
    if not isinstance(raw,list) or not raw or len(raw)>2000:raise ValueError('剧情单元表需包含1至2000条units')
    blocks={b['id']:b for b in source};units={};covered={};last=(-1,-1);block_rank={b['id']:i for i,b in enumerate(source)}
    times={};current_time='原文未明确'
    for block in source:
        if block['role']=='context' and re.match(r'^第.+场\s*·',block['text']):current_time=block['text'].split(' · ')[-1]
        times[block['id']]=current_time
    for item in raw:
        if not isinstance(item,dict):raise ValueError('剧情单元需为对象')
        identity=item.get('id');bid=item.get('block_id');quote=item.get('quote')
        if not isinstance(identity,str) or not identity.strip() or identity in units:raise ValueError('剧情单元ID重复或为空')
        if bid not in blocks or blocks[bid]['role']!='content':raise ValueError('剧情单元引用了未知或非内容段落')
        text=blocks[bid]['text']
        if item.get('whole_block') is True:
            if quote is not None and quote!=text:raise ValueError('整块单元不得改写缓存原文')
            if item.get('offset',0)!=0:raise ValueError('整块单元必须从原文起点开始')
            quote=text
        if not isinstance(quote,str) or not quote.strip() or quote not in text:raise ValueError('剧情单元摘录必须逐字存在于所属剧本块')
        offset=item.get('offset',text.find(quote))
        if type(offset) is not int or offset<0 or text[offset:offset+len(quote)]!=quote:raise ValueError('剧情单元摘录位置不匹配原文')
        if 'offset' not in item and text.find(quote,offset+1)>=0:raise ValueError('剧情单元摘录有多处同文，请用offset标明位置')
        position=(block_rank[bid],offset)
        if position<last:raise ValueError('剧情单元须保持已确认剧本的银幕书写顺序')
        last=position
        span=set(range(offset,offset+len(quote)))
        if span.intersection(covered.setdefault(bid,set())):raise ValueError('剧情单元摘录重叠，会重复执行同一内容')
        covered[bid].update(span)
        if item.get('kind') not in KINDS:raise ValueError('剧情单元类型无效')
        if item['kind']=='context' and (item.get('delivery')!='background' or not item.get('context_reason')):raise ValueError('实际剧本内容如作背景需声明delivery=background及context_reason，不能作为动作执行')
        item=copy.deepcopy(item)
        if item.get('whole_block') is True or (quote==text and offset==0):
            defaults={'story_time':times[bid],'start_state':'本单元内容尚未执行或交付','end_state':'本单元内容已执行或交付'}
            if item.get('kind')=='context':defaults.update(start_state='背景事实；观众交付方式待核对',end_state='背景事实；观众交付方式待核对')
            if any(k not in item for k in defaults):item['state_basis']='程序执行状态；实际空间状态见单镜连续性接口'
            for key,value in defaults.items():item.setdefault(key,value)
        for key in ('story_time','start_state','end_state'):
            if not isinstance(item.get(key),str) or not item[key].strip():raise ValueError('剧情单元缺少状态/时间：'+key)
        stable='U-'+hashlib.sha256(f'{bid}:{offset}:{quote}'.encode()).hexdigest()[:16]
        units[identity]={**item,'id':stable,'quote':quote,'offset':offset,'end_offset':offset+len(quote),'speech_ids':[]}
    for bid,block in blocks.items():
        if block['role']=='content' and substantive(block['text'])-covered.get(bid,set()):raise ValueError('剧情单元遗漏剧本实质文字：'+bid+'；不得删除来源来通过')
    carriers={};owners={};unit_rank={u['id']:i for i,u in enumerate(units.values())};last_execute=-1
    for i,(row,outline) in enumerate(zip(answer['shots'],outlines)):
        if re.search(r'[／/；;]|\s[→|]\s',outline['location']):raise ValueError('一个镜头只能有一个具体地点，不能合并不同场景')
        refs=row.get('carriers')
        if not isinstance(refs,list) or not refs:raise ValueError(f'第{i+1}镜缺少剧情单元承载关系')
        seen=set();normalized=[]
        for ref in refs:
            if not isinstance(ref,dict) or ref.get('unit_id') not in units or ref.get('mode') not in MODES:raise ValueError('镜头承载引用了无效单元或模式')
            unit=units[ref['unit_id']];uid=unit['id'];mode=ref['mode']
            if uid in seen or (mode=='execute' and unit['block_id'] not in outline['source_block_ids']):raise ValueError('单元承载重复或超出本镜剧本依据')
            seen.add(uid)
            if unit['kind']=='context' and mode!='context':raise ValueError('格式/背景单元不能作为动作执行')
            if mode=='execute':
                if uid in owners:raise ValueError('同一剧情单元只能执行一次：'+unit['quote'])
                rank=unit_rank[uid]
                if rank<last_execute:raise ValueError('剧情单元执行改变了已确认剧本的银幕顺序')
                last_execute=rank;owners[uid]=i+1
            elif unit['kind']!='context' and (uid not in owners or (mode=='result' and owners[uid]>=i+1)):
                raise ValueError('上下文/结果单元必须有此前的执行依据')
            normalized.append({'unit_id':uid,'mode':mode});carriers.setdefault(uid,[]).append({'index':i+1,'mode':mode})
        outline['unit_carriers']=normalized
    for unit in units.values():
        if unit['kind']!='context' and unit['id'] not in owners:raise ValueError('剧情单元没有唯一执行镜头：'+unit['quote'])
        if unit['kind']=='context' and not carriers.get(unit['id']):raise ValueError('背景单元需明确对应的应用镜头')
        unit['execute_index']=owners.get(unit['id']);unit['carriers']=carriers.get(unit['id'],[])
    for line in speech:
        if line['kind']=='quote':continue
        bid=line['id'].split('-Q')[0]
        matches=[u for u in units.values() if u['block_id']==bid and line['text'] in u['quote'] and u['kind'] in ('dialogue','voiceover')]
        if len(matches)!=1 or matches[0]['kind']!=line['kind']:raise ValueError('原句声音必须完整分配给一个对应类型的剧情单元：'+line['id'])
        matches[0]['speech_ids'].append(line['id'])
    catalogue={u['id']:u for u in units.values()}
    for outline in outlines:
        outline['content_units']=[copy.deepcopy(catalogue[c['unit_id']]) for c in outline['unit_carriers']]
        ids={sid for c in outline['unit_carriers'] if c['mode']=='execute' for sid in catalogue[c['unit_id']]['speech_ids']}
        outline['speech_sources']=[copy.deepcopy(s) for s in speech if s['id'] in ids]
        from . import narration_visuals
        outline['speech_min_seconds']=narration_visuals.speech_seconds(outline['speech_sources'])
        if outline['natural_seconds']<outline['speech_min_seconds']:outline['natural_seconds']=outline['speech_min_seconds']
    return outlines


def keep(old,new):
    for key in ('content_units','unit_carriers'):
        if key in old:new[key]=copy.deepcopy(old[key])
    if 'content_units' in old:
        new['speech_sources']=copy.deepcopy(old['speech_sources']);new['speech_min_seconds']=old['speech_min_seconds']
    return new


def check_actions(raw,outline):
    expected={c['unit_id'] for c in outline.get('unit_carriers',[]) if c['mode']=='execute'}
    if not outline.get('content_units'):return []
    found=[];errors=[]
    for action in raw.get('actions',[]) if isinstance(raw.get('actions'),list) else []:
        ids=action.get('unit_ids') if isinstance(action,dict) else None
        if not isinstance(ids,list) or any(s not in expected for s in ids):errors.append('动作unit_ids只能引用本镜execute剧情单元');continue
        found.extend(ids)
    if set(found)!=expected or len(found)!=len(set(found)):errors.append('动作须恰好执行本镜全部剧情单元一次，context/result不得重演')
    return errors
