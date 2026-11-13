"""Bounded, durable continuation for authoring responses; never publish partial JSON."""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
import httpx

MAX_CHARS = 400000

def complete(text):
    try:
        value = json.loads(text, strict=False)
        return isinstance(value, dict)
    except (ValueError, TypeError):
        return False

def append_suffix(prefix, suffix):
    if suffix.startswith(prefix):
        return suffix
    # Some providers repeat the final sentence despite the continuation instruction.
    for size in range(min(len(prefix), len(suffix), 4000), 19, -1):
        if prefix[-size:] == suffix[:size]:
            return prefix + suffix[size:]
    return prefix + suffix

def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)

def request(url, key, body, timeout, checkpoint):
    """Save visible text while streaming; reasoning never becomes manuscript text."""
    text = ''; finish = None; usage = {}; saved_at = time.monotonic()
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout, connect=30), follow_redirects=False) as client:
            with client.stream('POST', url, headers={'Authorization': 'Bearer '+key}, json=body) as response:
                if response.status_code != 200:
                    raise ValueError('AI 调用失败：HTTP '+str(response.status_code))
                if 'text/event-stream' not in response.headers.get('content-type',''):
                    data=json.loads(response.read())
                    if data.get('error') or data.get('base_resp',{}).get('status_code',0):
                        raise ValueError('AI 服务返回错误，请检查模型与接口配置')
                    choices=data.get('choices') or []
                    if not choices:raise ValueError('AI 返回缺少 choices')
                    row=choices[0];text=row.get('message',{}).get('content') or ''
                    if not isinstance(text,str):raise ValueError('AI 返回正文格式不受支持')
                    return text,row.get('finish_reason'),data.get('usage',{})
                for line in response.iter_lines():
                    if not line.startswith('data:'):continue
                    raw=line[5:].strip()
                    if raw=='[DONE]':break
                    if not raw:continue
                    data=json.loads(raw)
                    if data.get('error') or data.get('base_resp',{}).get('status_code',0):
                        raise ValueError('AI 服务流式响应错误，已保留可恢复草稿')
                    usage=data.get('usage') or usage
                    for row in data.get('choices') or []:
                        if row.get('index',0)!=0:continue
                        content=row.get('delta',{}).get('content') or ''
                        if not isinstance(content,str):raise ValueError('AI 流式正文格式不受支持')
                        text+=content
                        finish=row.get('finish_reason') or finish
                    if len(text)>MAX_CHARS:raise ValueError('AI 回复超过草稿存储上限')
                    if time.monotonic()-saved_at>1:
                        checkpoint(text);saved_at=time.monotonic()
        return text,finish,usage
    except (httpx.TimeoutException,httpx.TransportError):
        return text,'interrupted',usage
    finally:
        if text:checkpoint(text)

def generate(cfg, url, system, user, budget, timeout, directory, parser, report=None,effort='medium',resume_hint='点击继续未完成步骤'):
    report=report or (lambda message:None)
    # A changed prompt/model never resumes an unrelated draft. No API key is stored.
    digest=hashlib.sha256(json.dumps([url,cfg['ai_model'],system,user],ensure_ascii=False).encode()).hexdigest()
    path=Path(directory)/'authoring-drafts'/(digest+'.json')
    state={'text':'','attempts':0}
    if path.exists():
        try:state=json.loads(path.read_text('utf-8'))
        except (ValueError,OSError):pass
    prefix=str(state.get('text',''))
    if len(prefix)>MAX_CHARS:raise ValueError('恢复草稿超过存储上限')
    if complete(prefix):
        value=parser(json.dumps(json.loads(prefix,strict=False),ensure_ascii=False));path.unlink(missing_ok=True)
        return value,{'attempts':0,'finish_reason':'recovered','recovered_characters':len(prefix)}
    minimax=cfg['ai_model'].lower().startswith('minimax-')
    meta={'attempts':0,'recovered_characters':len(prefix),'usage':[]}
    for attempt in range(3):
        messages=[{'role':'system','content':system+'\n输出一个完整 JSON 对象，正文和必要字段优先；辅助说明简洁，不重复正文，不输出 Markdown 围栏。'}, {'role':'user','content':user}]
        if prefix:
            report('正在自动补全：已保留 '+str(len(prefix))+' 字符，只续写未完成部分')
            messages.extend([{'role':'assistant','content':prefix},{'role':'user','content':'上条回复因传输或长度限制中断。只输出紧接其最后一个字符的后续内容，不重复、不重新开始，不使用围栏。可能从 JSON 字符串中间续接；补齐当前字段及剩余字段直到对象完整闭合。字符串内换行必须转义成\\n，双引号必须正确转义。已有内容保持不变，确保故事结局和所有必需条目完整。'}])
        elif attempt:
            report('正在自动恢复：上次尚未返回正文，降低思考强度后重试')
        body={'model':cfg['ai_model'],'messages':messages,'stream':True,'max_tokens':max(16384,min(32768,budget))}
        if minimax:
            body['reasoning_effort']=effort if attempt==0 and not prefix else 'low'
            body['stream_options']={'include_usage':True}
        else:body['temperature']=0.3
        current=prefix
        def checkpoint(fragment):
            text=append_suffix(current,fragment)
            if len(text)>MAX_CHARS:raise ValueError('恢复草稿超过存储上限')
            save(path,{'text':text,'attempts':state.get('attempts',0)+attempt+1,'updated':time.time()})
        suffix,finish,usage=request(url,cfg.get('ai_key',''),body,timeout,checkpoint)
        prefix=append_suffix(current,suffix)
        checkpoint(suffix)
        meta.update(attempts=attempt+1,finish_reason=finish)
        meta['usage'].append(usage)
        if finish in ('content_filter','refusal'):raise ValueError('AI 服务未完成内容生成，已保留草稿，请检查任务内容')
        # A complete object still goes through the caller's schema/fidelity validation.
        if complete(prefix) or finish=='stop':
            try:value=parser(json.dumps(json.loads(prefix,strict=False),ensure_ascii=False) if complete(prefix) else prefix)
            except ValueError:
                if finish=='stop':
                    path.unlink(missing_ok=True)
                    raise
            else:
                path.unlink(missing_ok=True)
                return value,meta
        if finish not in ('length','interrupted',None):
            raise ValueError('AI 回复未完整结束，已保留草稿')
    raise ValueError('自动补全已达本轮上限，草稿已保存；'+resume_hint+'将从断点恢复，不必重新创作')
