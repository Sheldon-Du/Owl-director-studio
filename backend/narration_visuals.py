"""Review the visible purpose of narration shots before detailed generation."""
import copy
import math
import re
import unicodedata

VERSION = 1
IDLE = re.compile(r'半睡|补觉|睡觉|睡着|熟睡|沉睡|闭眼|闭上眼|眼皮.{0,4}(?:合|沉重)|呼吸(?:微|起伏)')


def visible_key(text):
    return ''.join(c for c in unicodedata.normalize('NFKC',str(text or '')).casefold() if c.isalnum())


def visible_match(anchor, image):
    key=visible_key(anchor)
    return bool(key and key in visible_key(image))


def canonical_anchors(anchors, image):
    if isinstance(anchors,str):anchors=[anchors]
    if not isinstance(anchors,list) or not anchors:raise ValueError('画面方案anchors需填写具体可见主体或物件')
    # Canonicalize only presentation differences, not invented entities or
    # semantic substitutions. Evidence is verified independently below.
    result=[]
    for anchor in anchors:
        original=anchor
        # Anchors identify visible subjects; motion adjectives belong to image.
        # Drop a modifier only when the exact concrete noun is already visible.
        # Never add an entity or an action to make an invalid anchor pass.
        if isinstance(anchor,str) and not visible_match(anchor,image):
            noun=anchor.strip().rsplit('的',1)[-1] if '的' in anchor else ''
            if noun in ('双手','手指','手掌','双眼','眼睛','面孔','脸庞','嘴唇','肩膀','双脚') and noun in image:
                anchor=noun
        if isinstance(anchor,str) and not visible_match(anchor,image):
            # Strip only a closed set of framing prefixes and an explicit
            # quantity classifier. The remaining entity must already occur
            # verbatim in image; never fuzzy-match another object or append it.
            noun=re.sub(r'^(?:昏暗中|黑暗中|暗处|画面中|前景中|中景中|背景中|远处|近处)(?:的)?','',anchor.strip())
            noun=re.sub(r'^(?:大约|约|至少|近)?(?:上百|数百|上千|数千|数十|几|[零〇一二两三四五六七八九十百千万\d]+)(?:多|余)?[张把座间扇辆艘盏本件只个名位条排块支棵枚杯碗](?:的)?','',noun)
            # One-character subjects are allowed only for concrete objects;
            # avoid "他/她/人/中" or a suffix shared by unrelated entities.
            if noun!=original.strip() and (len(noun)>=2 or noun in ('床','碗','桌','椅','门','灯','车','船','书','树')) and noun in image:
                anchor=noun
        if not isinstance(anchor,str) or not visible_match(anchor,image):
            missing=[str(a) for a in anchors if not isinstance(a,str) or not visible_match(a,image)]
            raise ValueError('画面方案anchors与image的可见主体不匹配：'+ '、'.join(missing)+'；anchors应逐字摘自image，或在不改剧情的前提下将这些真实可见物写入image，仅修正本镜对应字段')
        key=visible_key(anchor)
        if key in ('压力','学历','情绪','紧张','命运','背景','旁白','画外音'):
            raise ValueError('画面要点需为具体可见主体或物件，不能只填写抽象概念')
        if key not in {visible_key(s) for s in result}:result.append(anchor.strip())
    return result


def speech_seconds(sources):
    # The same upper speech rate as timing.validate, a lower bound rather
    # than a recommended delivery speed. Pauses/acting may require more.
    count = sum(len(re.findall(r'[\u4e00-\u9fff]|[A-Za-z]+', s['text']))
                for s in sources if s['kind'] != 'quote')
    return math.ceil(count / 5 * 10) / 10


def review(outline, raw, source_index, previous=None, required=False):
    voices = [s for s in outline.get('speech_sources', []) if s['kind'] == 'voiceover']
    plan = raw.get('visual_plan')
    if plan is None:
        if voices and required:
            raise ValueError(f'分镜汇总第{outline["index"]}条有旁白，需填写具体可见的visual_plan，不能只写旁白内容')
        return outline  # Previously confirmed outlines remain usable.
    if not isinstance(plan, dict): raise ValueError('visual_plan需为画面方案对象')
    plan = copy.deepcopy(plan)
    if plan.get('mode') not in ('present_action', 'narration_illustration', 'reaction'):
        raise ValueError('画面方案mode请选择present_action、narration_illustration或reaction')
    missing_purpose=plan.get('purpose') is None or (isinstance(plan.get('purpose'),str) and not plan['purpose'].strip())
    if not missing_purpose and not isinstance(plan.get('purpose'),str):raise ValueError('画面方案purpose必须为文字说明')
    for field in ('image', 'time_context', 'cut_reason'):
        if not isinstance(plan.get(field), str) or not plan[field].strip():
            raise ValueError(f'画面方案缺少{field}，请说明可见内容、画面作用、时间层和切镜必要性')
    if re.match(r'^(?:旁白|画外音|叙述者).{0,8}(?:讲|说|提|介绍|解释)', plan['image']):
        raise ValueError('画面方案image需描述看得见的画面，不能仅复述旁白讲了什么')
    evidence = plan.get('evidence')
    if not isinstance(evidence, list) or not evidence:
        raise ValueError('画面方案需提供本镜剧本原文依据evidence')
    for position,item in enumerate(evidence):
        key = item.get('block_id') if isinstance(item, dict) else None
        quote = item.get('quote') if isinstance(item, dict) else None
        if isinstance(item,dict) and 'quote_ref' in item:
            ref=item['quote_ref']
            if ref!=key or key not in outline['source_block_ids'] or key not in source_index:raise ValueError('画面依据quote_ref必须引用本镜所属的同一来源编号，不能跨镜或跨段')
            if quote is not None and quote!=source_index[key]:raise ValueError('quote_ref的quote不得改写原文；请省略quote由程序逐字回填')
            quote=source_index[key]
            item['quote']=quote
            item['resolved_from_source']=True
        if key not in outline['source_block_ids'] or not isinstance(quote, str) or not quote.strip() or quote not in source_index[key]:
            reason='编号不属于本镜' if key not in outline['source_block_ids'] else 'quote不是该段连续原句（不可改写或拼接）'
            allowed='、'.join(outline['source_block_ids'])
            raise ValueError(f'旁白画面依据必须逐字来自本镜所属剧本段落，不能编造经历或引用其他镜头；evidence[{position}]：{reason}，允许编号：{allowed}')
    original_anchors=copy.deepcopy(plan.get('anchors'))
    plan['anchors']=canonical_anchors(original_anchors,plan['image'])
    if original_anchors!=plan['anchors']:
        plan.setdefault('metadata_corrections',[]).append({'field':'anchors','method':'existing_visible_entity',
            'from':original_anchors,'to':copy.deepcopy(plan['anchors']),
            'note':'仅规范画面要点，主体逐字存在于image；未改画面、数量、状态、剧情或原文依据。'})
    if missing_purpose:
        plan['purpose']=('以本镜已有画面承载所选旁白的原文信息：' if voices else '呈现本镜已选原文对应的可见信息：')+plan['image'].strip()
        plan.setdefault('metadata_corrections',[]).append({'field':'purpose','method':'verified_existing_image','note':'程序补齐制作说明，未修改画面、对白、依据或时间层；不代表语义审查通过。'})
    if plan['mode'] == 'narration_illustration' and not voices:
        if re.search(r'回忆|过去|闪回|概念|想象',plan['time_context']):
            raise ValueError(f'第{outline["index"]}镜未分配画外音，不能将对白另拍为回忆或概念插入；请按本镜原文改为当下动作或反应，保留原对白，不新增旁白')
        # Speech ownership is determined by verified source ids, not the AI's
        # visual mode label. Correct the label without inventing voiceover.
        plan['mode']='present_action'
        plan['mode_correction']='本镜未分配画外音，按已有原文画面改为现场动作；未添加旁白。'
    if voices and previous and any(s['kind'] == 'voiceover' for s in previous.get('speech_sources', [])):
        old = previous.get('visual_plan', {})
        repeated_image = re.sub(r'\s+', '', plan['image']) == re.sub(r'\s+', '', old.get('image', previous['focus']))
        repeated_idle = (plan['mode'] != 'narration_illustration' and old.get('mode') in ('reaction', 'present_action')
                         and outline['location'] == previous['location']
                         and IDLE.search(plan['image']) and IDLE.search(old.get('image', '')))
        if repeated_image or repeated_idle:
            raise ValueError('相邻旁白镜重复同一画面或睡觉反应，请合并同一叙事事件，或规划有原文依据的新画面信息')
    outline.update(visual_plan=plan, visual_planning_version=VERSION)
    return outline
