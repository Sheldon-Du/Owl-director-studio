"""Official H3 reference categories and final executable prompt limits."""
def counts(refs,extra_audio=0):
    result={'image':0,'video':0,'audio':extra_audio}
    for ref in refs:
        kind='video' if ref.get('refmod') else ref.get('media_type','image')
        if kind not in result:raise ValueError('H3参考媒体类型无效')
        result[kind]+=1
    result['total']=sum(result.values())
    return result

def validate_media(refs,extra_audio=0):
    value=counts(refs,extra_audio)
    if value['image']>9 or value['video']>3 or value['audio']>3 or value['total']>12:
        raise ValueError(f'H3参考超限：当前{value["image"]}图、{value["video"]}视频、{value["audio"]}音频，共{value["total"]}项；上限9图、3视频、3音频，混合总计12项。请减少引用或拆分分段，不会静默丢弃媒体')
    return value

def prompt_length(prompt):
    # Match the official CLI's JavaScript string.length, including surrogate pairs.
    return len(prompt.encode('utf-16-le'))//2

def validate_prompt(prompt):
    count=prompt_length(prompt)
    if count>7000:raise ValueError(f'H3 单步提示词超过7000字符（实际{count}字符）；请精简重复描述或拆分分段，不能截断动作与对白')
    return count
