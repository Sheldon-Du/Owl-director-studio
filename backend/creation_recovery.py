"""Constrained recovery decisions. Errors are data, never executable instructions."""
INSTRUCTIONS={
 'compact':'本次为自动恢复：精简重复解释与非必要修饰，保持完整必填字段、原文事实和来源引用，不删除情节或对白，不改时长规则。只输出所需的严格JSON。',
 'json':'本次为格式恢复：只输出一个完整有效JSON对象，不加围栏或说明。所有字符串的引号、换行和反斜杠正确转义，数组和对象保留完整，不删必填字段。',
 'source':'本次为来源引用修复：逐项核对本任务给定的原句编号、人物归属及画面可见主体。对白和旁白只引用对应类型的给定编号，动作引用本镜编号；anchors逐字摘自image。不新增、删减或改写剧情，不编造引用。',
 'portrait':'本次为资产外观修复：只描写目标元素自身的可见外观、服装、稳定气质与造型。禁止混入其他人物外貌、剧情经历、旁白方式或拍摄叙事。保留剧本明示特征与人工设定，普通补充仍标为建议。',
}

def decide(kind,message,cancelled=False):
    if cancelled:return {'action':'stop','reason':'用户已取消任务，不自动重启'}
    if any(w in message for w in ('已手动修改','期间项目','期间剧本','设定已修改','生成依据已','密钥','HTTP 401','HTTP 403','权限','不存在','显存','CUDA','OutOfMemory')):
        return {'action':'stop','reason':'需要核对用户修改、连接配置或本地资源，保留结果并停止自动修改'}
    if '请求超时' in message or 'finish_reason=length' in message:
        return {'action':'retry','strategy':'compact','reason':'输入或输出过大／响应超时，精简输出；剧本复用已拆小的未完成批次','delay':0}
    if 'AI 未返回有效 JSON' in message:
        return {'action':'retry','strategy':'json','reason':'返回格式错误，追加严格序列化要求，仅重做失败项','delay':0}
    if any(w in message for w in ('HTTP 429','HTTP 502','HTTP 503','HTTP 504','连接失败','连接中断')):
        return {'action':'retry','strategy':'compact','reason':'上游临时不可用，等待后重试，不修改故事内容','delay':20}
    if kind in ('asset_prompt','asset_enrich') and any(w in message for w in ('混入','混有其他人物','造型','外貌依据','角色设定图')):
        return {'action':'retry','strategy':'portrait','reason':'外观与剧情或人物归属混淆，追加目标元素独立外观约束','delay':0}
    if kind in ('storyboard','storyboard_outline') and any(w in message for w in ('dialogue_ids','speech_ids','原句编号','anchors','可见主体','跨过','银幕顺序','旁白说明画面')):
        return {'action':'retry','strategy':'source','reason':'来源或画面对应未通过，追加引用核对约束，复用已完成镜头','delay':0}
    return {'action':'stop','reason':'未识别为可安全自动修复的错误，保留原结果与完整诊断'}
