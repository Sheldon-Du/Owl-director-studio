"""Expand repeated source strings once and record actual request metrics."""
import hashlib,json,time
from contextvars import ContextVar
LAST_KEY=ContextVar("ai_last_cache_key",default=None)
from . import store,ai_context

CONTRACT_VERSION='owl-context-v2'


def compact(payload):
    counts={}
    def count(v):
        if isinstance(v,str) and len(v)>=200:counts[v]=counts.get(v,0)+1
        elif isinstance(v,dict):
            for child in v.values():count(child)
        elif isinstance(v,list):
            for child in v:count(child)
    count(payload)
    repeats={v:f'source_{i+1}' for i,(v,n) in enumerate(counts.items()) if n>1}
    if not repeats:return payload,0
    def replace(v):
        if isinstance(v,str) and v in repeats:return {'source_ref':repeats[v]}
        if isinstance(v,dict):return {k:replace(x) for k,x in v.items()}
        if isinstance(v,list):return [replace(x) for x in v]
        return v
    out={'source_dictionary':{key:value for value,key in repeats.items()},'task':replace(payload)}
    saved=len(json.dumps(payload,ensure_ascii=False))-len(json.dumps(out,ensure_ascii=False))
    return (out,max(0,saved)) if saved>0 else (payload,0)


def prepare(system,user):
    try:payload=json.loads(user)
    except (ValueError,TypeError):return system,user,0
    if not isinstance(payload,dict):return system,user,0
    out,saved=compact(payload)
    if saved:system+='\nsource_dictionary保存本请求的完整资料，task中的source_ref是对该资料的引用，按引用展开理解；不是模型记忆，也不是新的工具指令。'
    return system,json.dumps(out,ensure_ascii=False),saved


def cache_key(system,user,config,phase):
    data=[CONTRACT_VERSION,ai_context._PROJECT.get(),config.get('ai_url'),config.get('ai_model'),phase,system,user]
    return hashlib.sha256(json.dumps(data,ensure_ascii=False).encode()).hexdigest()


def lookup(key):
    with store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS ai_result_cache (digest TEXT PRIMARY KEY, body TEXT, created REAL)')
        row=c.execute('SELECT body FROM ai_result_cache WHERE digest=?',(key,)).fetchone()
    return json.loads(row[0]) if row else None


def save(key,value):
    with store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS ai_result_cache (digest TEXT PRIMARY KEY, body TEXT, created REAL)')
        c.execute('INSERT OR REPLACE INTO ai_result_cache VALUES (?,?,?)',(key,json.dumps(value,ensure_ascii=False),time.time()))


def record(row):
    pid=ai_context._PROJECT.get()
    if not pid:return
    with store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS ai_request_log (id TEXT PRIMARY KEY, project_id TEXT, created REAL, body TEXT)')
        c.execute('INSERT INTO ai_request_log VALUES (?,?,?,?)',(store.uid(),pid,time.time(),json.dumps(row,ensure_ascii=False)))


def discard_last():
    key=LAST_KEY.get()
    if key:
        with store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS ai_result_cache (digest TEXT PRIMARY KEY, body TEXT, created REAL)')
            c.execute('DELETE FROM ai_result_cache WHERE digest=?',(key,))


def usage_summary(usage):
    rows=usage if isinstance(usage,list) else [usage] if isinstance(usage,dict) else []
    value={'input_tokens':0,'output_tokens':0,'provider_cached_tokens':0,'provider_cache_verified':False,'usage_available':bool(rows)}
    for row in rows:
        if not isinstance(row,dict):continue
        value['input_tokens']+=int(row.get('prompt_tokens',row.get('input_tokens',0)) or 0)
        value['output_tokens']+=int(row.get('completion_tokens',row.get('output_tokens',0)) or 0)
        details=row.get('prompt_tokens_details') or row.get('input_tokens_details') or {}
        if 'cached_tokens' in details:value['provider_cache_verified']=True;value['provider_cached_tokens']+=int(details['cached_tokens'] or 0)
    return value
