import copy,json,subprocess,sys,threading
from pathlib import Path
from . import store
PATH=store.ROOT/'seedance_data'
LANG=('title','description','useWhen','structure','guidance','pitfalls','copyPrompt')
def read(name): return json.loads((PATH/(name+'.json')).read_text('utf-8'))
def overlay(a,b):
    out=copy.deepcopy(a)
    for k,v in b.items(): out[k]={**out[k],**v} if k in LANG and isinstance(v,dict) and isinstance(out.get(k),dict) else v
    return out
def library(snapshot=None):
    loader=(lambda name:snapshot[name]) if snapshot is not None else read
    base=loader('style-library'); local=loader('templates-local')
    cats={c['id']:c for c in base.get('categories',[])}
    for c in local.get('categories',[]): cats[c['id']]=overlay(cats.get(c['id'],{}),c)
    templates={t['id']:t for t in base['templates']}
    for k,v in local.get('overrides',{}).items():
        if k not in templates: raise ValueError('未知模板覆盖 '+k)
        templates[k]=overlay(templates[k],v)
    for t in local.get('templates',[]):
        if t['id'] in templates or t['category'] not in cats: raise ValueError('模板分类或重复 ID 错误')
        templates[t['id']]=t
    assignments=loader('case-taxonomy')['assignments']
    cases=loader('cases')
    for c in cases['cases']:
        c['template_id']=assignments.get(c['slug'])
        c['search_text']=' '.join(str(c.get(k,'')) for k in ('title','titleEn','summary','creator','promptFull')).lower()
    skills={s.get('id',s.get('slug')):s for s in loader('skills')['skills']}
    for s in loader('site-skills')['skills']: skills.setdefault(s.get('id',s.get('slug')),s)
    return {'cases':cases['cases'],'meta':cases['meta'],'templates':list(templates.values()),'categories':list(cats.values()),'skills':list(skills.values())}
def zh(v): return v.get('zh',v.get('en','')) if isinstance(v,dict) else v
def template(identity):
    return next((x for x in library()['templates'] if x['id']==identity),None)
def case_snapshot(slug):
    c=next((x for x in library()['cases'] if x['slug']==slug),None)
    if not c:raise ValueError('案例不存在')
    return {k:c.get(k) for k in ('slug','title','summary','promptFull','sourceUrl','creator','models','template_id')}
def refresh():
    # Fetch into a temporary clone; validate before replacing the data snapshot.
    import shutil,tempfile,os
    with tempfile.TemporaryDirectory(dir=store.DATA) as temp:
        r=subprocess.run(['git','clone','--depth','1','https://github.com/LearnPrompt/awesome-seedance.git',temp],capture_output=True,timeout=180)
        if r.returncode: raise ValueError('更新下载失败，旧资料保留')
        p=Path(temp)/'data'
        for name in ('cases','style-library','templates-local','case-taxonomy','skills','site-skills'):
            json.loads((p/(name+'.json')).read_text('utf-8'))
        # Persist one complete snapshot atomically; loader then switches to it.
        snapshot={name:json.loads((p/(name+'.json')).read_text('utf-8')) for name in ('cases','style-library','templates-local','case-taxonomy','skills','site-skills')}
        library(snapshot)
        pending=store.DATA/'catalogue.tmp'; pending.write_text(json.dumps(snapshot,ensure_ascii=False),'utf-8'); pending.replace(store.DATA/'catalogue.json')
    return {'updated':True}
_read=read
def read(name):
    p=store.DATA/'catalogue.json'
    return json.loads(p.read_text('utf-8'))[name] if p.exists() else _read(name)
