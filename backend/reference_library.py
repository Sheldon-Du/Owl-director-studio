"""Versioned local authoring references. Flova directory follows the featured web feed."""
import copy, hashlib, json, os, re, shutil, subprocess, threading, time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse
from . import store, seedance_catalogue

ROOT=store.DATA/'reference-library'
LOCK=threading.RLock()
FEED='https://service.flova.tv/api/v2/skill/list_public_v2'
PAGE='https://flova.tv/zh-CN/skill/?tab=featured'
STATE={'status':'idle'}
CATEGORY_LABELS={'cat_anime':'动漫','cat_commerce':'商业广告','cat_design':'视觉设计','cat_director':'电影与导演','cat_drama':'剧情','cat_mv':'音乐视频','cat_product':'产品展示','cat_short':'短片','cat_tool':'工具方法','cat_trending':'热门创意','cat_vlog':'生活记录','catch_all':'通用','commercial':'商业广告','foundation':'基础方法','motion':'动作与运动','narrative':'叙事','realism':'写实','stylized':'风格化','video':'视频案例'}
def categories(v):return [CATEGORY_LABELS.get(s.strip(),s.strip()) for s in v.get('category','').split(',') if s.strip()]

def hashof(v):return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+store.uid()+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf-8');tmp.replace(path)
def read(path,default):
    return json.loads(path.read_text('utf-8')) if path.is_file() else copy.deepcopy(default)
def progress(**fields):
    with LOCK:STATE.update(fields);write(ROOT/'sync.json',STATE)
def state():
    with LOCK:
        value=copy.deepcopy(STATE if STATE.get('status')=='running' else read(ROOT/'sync.json',STATE))
        if STATE.get('status')!='running' and value.get('status')=='running':value.update(status='interrupted',message='上次同步被中断，已有资料保留，可重新更新')
        return value

def markdown(value):
    if isinstance(value,str):text=value.strip()
    elif isinstance(value,list):
        parts=[]
        for row in value:
            if not isinstance(row,dict) or not isinstance(row.get('content'),str):raise ValueError('Skill 分段格式不支持')
            parts.append('## '+str(row.get('section','创作方法'))+'\n\n'+row['content'])
            if row.get('config'):parts.append('配置：\n```json\n'+json.dumps(row['config'],ensure_ascii=False,indent=2)+'\n```')
        text='\n\n'.join(parts).strip()
    else:raise ValueError('未取得完整 Skill 正文')
    if len(text)<30 or text.strip() in ('登录查看','Login to view'):raise ValueError('正文为空或需要登录')
    return text

def cli_detail(identity):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',identity):raise ValueError('Skill ID 无效')
    executable=shutil.which('flova') or str(Path(os.environ.get('LOCALAPPDATA',''))/'Programs/flova/flova.exe')
    if not Path(executable).is_file():raise ValueError('未安装 Flova CLI，无法读取需登录的正文')
    r=subprocess.run([executable,'skill','get',identity],capture_output=True,encoding='utf-8',timeout=90,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    try:result=json.loads(r.stdout)
    except ValueError:raise ValueError('Flova 正文读取失败，请检查本机 CLI 登录和连接')
    if result.get('code')!=0:raise ValueError('Flova 正文不可访问，请检查本机 CLI 登录')
    return result['data']

def remote_rows():
    # This is the site's verified featured sort; CLI public feed is not a fallback.
    rows=[];seen=set()
    with httpx.Client(timeout=45) as client:
        for page in range(1,101):
            r=client.get(FEED,params={'page':page,'page_size':20,'locale':'zh','only_brief':'true','sort':'default'});r.raise_for_status();body=r.json()
            if body.get('code')!=0:raise ValueError('精选页面目录不可用，保留本地版本')
            data=body['data'];items=data.get('items',[])
            for item in items:
                if item['skill_id'] not in seen:rows.append(item);seen.add(item['skill_id'])
            if page*20>=data.get('total',len(rows)) or not items:return rows
    raise ValueError('精选目录页数异常，未替换本地目录')

def download(url,path,limit=1024*1024*1024):
    host=urlparse(url).hostname or ''
    if urlparse(url).scheme!='https' or not any(host==d or host.endswith('.'+d) for d in ('flova.tv','flova.ai')):raise ValueError('不支持的 Flova 媒体来源')
    path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.'+store.uid()+'.part')
    try:
        with httpx.stream('GET',url,timeout=60,follow_redirects=False) as r:
            r.raise_for_status()
            if not r.headers.get('content-type','').split(';')[0].startswith(('image/','video/','application/octet-stream')):raise ValueError('资源地址未返回媒体文件')
            size=0
            with tmp.open('wb') as f:
                for chunk in r.iter_bytes():
                    size+=len(chunk)
                    if size>limit:raise ValueError('资源超过单文件缓存大小上限')
                    f.write(chunk)
            if not size:raise ValueError('下载内容为空')
        tmp.replace(path)
    finally:
        if tmp.exists():tmp.unlink()

def seedance_rows():
    data=seedance_catalogue.library();cases={c['slug']:c for c in data['cases']};rows=[]
    for kind in ('templates','cases'):
        for v in data[kind]:
            identity='seedance-'+('template-' if kind=='templates' else 'case-')+str(v.get('id') or v['slug'])
            videos=[v] if kind=='cases' else [cases[s] for s in v.get('exampleCases',[]) if s in cases]
            body='\n\n'.join('## '+k+'\n'+str(seedance_catalogue.zh(v[k])) for k in ('description','summary','useWhen','structure','guidance','pitfalls','copyPrompt','promptFull') if v.get(k))
            rows.append({'id':identity,'source':'seedance','kind':kind,'method_template_id':v.get('template_id') if kind=='cases' else v.get('id'),'title':seedance_catalogue.zh(v.get('title','')),'category':v.get('category') or v.get('template_id') or '未分类','author':v.get('creator','LearnPrompt'),'source_url':v.get('sourceUrl','https://github.com/LearnPrompt/awesome-seedance'),'content':body,'version':hashof(body)[:12],'videos':[{'url':c.get('mediaUrl'),'poster':c.get('posterUrl'),'title':seedance_catalogue.zh(c.get('title',''))} for c in videos if c.get('mediaType')!='image' and c.get('mediaUrl')],'available':bool(body)})
    return rows

def catalogue():return seedance_rows()+read(ROOT/'flova.json',[])+read(ROOT/'local.json',[])
def item(identity):
    result=next((r for r in catalogue() if r['id']==identity),None)
    if result is None:raise ValueError('参考条目不存在，请刷新目录')
    return result

def sync(source):
    errors=[];updated=0
    try:
        if source in ('seedance','all'):seedance_catalogue.refresh()
        if source in ('flova','all'):
            rows=remote_rows();old={r['id']:r for r in read(ROOT/'flova.json',[])};out=[]
            for index,brief in enumerate(rows):
                identity='flova-'+brief['skill_id'];prior=old.get(identity)
                progress(completed=index,total=len(rows),message='同步 '+brief['skill_name'])
                if prior and prior.get('remote_version')==brief.get('version') and prior.get('available'):
                    out.append(prior);continue
                try:
                    detail=cli_detail(brief['skill_id']);content=markdown(detail.get('skill_content'))
                    version=str(detail.get('version',0))+'-'+hashof(content)[:12];folder=ROOT/identity/version
                    write(folder/'original.json',detail);(folder/'skill.md').write_text(content,'utf-8')
                    media=detail.get('attrs',{}).get('material_resource',{});poster=media.get('thumbnail_url') or detail.get('cover_standard_url',{}).get('compressed')
                    current={'id':identity,'source':'flova','kind':'skill','title':detail['skill_name'],'author':detail.get('author',{}).get('name',''),'category':', '.join(detail.get('attrs',{}).get('category_ids',[])),'source_url':detail.get('skill_url',PAGE),'content':content,'version':version,'remote_version':detail.get('version'),'updated_at':detail.get('updated_at'),'synced_at':time.time(),'available':True,'videos':[{'url':media['url'],'poster':poster,'title':detail['skill_name']}] if media.get('type')=='video' and media.get('url') else []}
                    if poster:
                        try:download(poster,folder/'poster.webp',20*1024*1024);current['poster_local']=identity+'/'+version+'/poster.webp'
                        except Exception:current['cover_error']='封面暂未缓存，可稍后重试'
                    out.append(current);updated+=1
                except Exception as e:
                    errors.append({'title':brief['skill_name'],'message':str(e)[:200]})
                    out.append(prior or {'id':identity,'source':'flova','kind':'skill','title':brief['skill_name'],'author':brief.get('author',{}).get('name',''),'category':'','source_url':PAGE,'available':False,'content':'','version':'','videos':[],'error':str(e)[:200]})
            # A complete fetched directory is published together; historical files remain.
            write(ROOT/'flova.json',out)
        progress(status='completed',completed=len(rows) if source in ('flova','all') else 1,updated=updated,errors=errors,message='资料库已更新',finished=time.time())
    except Exception as e:progress(status='failed',errors=errors,message='更新失败，旧资料保留：'+str(e)[:250],finished=time.time())

def cache_video(identity,version=None):
    v=item(identity)
    if v['source']!='flova' or not v.get('videos'):return
    if version and v['version']!=version:return
    folder=ROOT/identity/v['version'];status=folder/'video-status.json'
    if (folder/'reference.mp4').exists():return
    try:
        write(status,{'status':'running'})
        try:download(v['videos'][0]['url'],folder/'reference.mp4')
        except Exception:
            fresh=cli_detail(identity.removeprefix('flova-'));media=fresh.get('attrs',{}).get('material_resource',{})
            if urlparse(media.get('url','')).path!=urlparse(v['videos'][0]['url']).path:raise ValueError('该视频已更新，请先更新并采用新版本')
            download(media['url'],folder/'reference.mp4')
        write(status,{'status':'completed'})
    except Exception as e:write(status,{'status':'failed','message':str(e)[:200]})

def public(v,full=False):
    result=copy.deepcopy(v)
    if not full:result.pop('content',None)
    if v['source'] in ('flova','local') and v.get('version'):
        folder=ROOT/v['id']/v['version'];prefix='/api/reference-library/files/'+v['id']+'/'+v['version']+'/'
        if (folder/'poster.webp').exists():result['poster_url']=prefix+'poster.webp'
        if (folder/'reference.mp4').exists():result['video_url']=prefix+'reference.mp4'
        result['video_cache']=read(folder/'video-status.json',{'status':'not_cached'})
        result['markdown_url']=prefix+'skill.md' if (folder/'skill.md').exists() else None
    from .reference_profile import profile
    scope=profile({'primary_reference':v})
    result['application_summary']={key:scope[key] for key in ('coverage','status','origin','warnings')}
    if full:result['reference_profile']=scope
    return result

def install(app):
    @app.post('/api/reference-library/import')
    async def import_skill(title:str=Form(...),content:UploadFile=File(...),video:UploadFile=File(None)):
        if not title.strip() or len(title)>200:raise ValueError('标题需为1–200字')
        raw=await content.read(2*1024*1024+1)
        if len(raw)>2*1024*1024:raise ValueError('Skill 文件不可超过2MB')
        try:body=markdown(raw.decode('utf-8-sig'))
        except UnicodeDecodeError:raise ValueError('请上传UTF-8编码的skill.md')
        identity='local-'+store.uid();version=hashof(body)[:12];folder=ROOT/identity/version
        folder.mkdir(parents=True,exist_ok=True);(folder/'skill.md').write_text(body,'utf-8')
        value={'id':identity,'source':'local','kind':'skill','title':title.strip(),'author':'用户导入','category':'手动导入','source_url':'','content':body,'version':version,'synced_at':time.time(),'available':True,'videos':[]}
        if video and video.filename:
            if Path(video.filename).suffix.lower()!='.mp4':raise ValueError('请上传MP4视频')
            path=folder/'reference.mp4';temp=folder/'upload.part';size=0
            try:
                with temp.open('wb') as f:
                    while chunk:=await video.read(1024*1024):
                        size+=len(chunk)
                        if size>1024*1024*1024:raise ValueError('视频不可超过1GB')
                        f.write(chunk)
                if not size:raise ValueError('视频文件为空')
                temp.replace(path)
            finally:
                if temp.exists():temp.unlink()
            write(folder/'video-status.json',{'status':'completed'})
        write(folder/'original.json',{k:v for k,v in value.items() if k!='content'})
        with LOCK:write(ROOT/'local.json',read(ROOT/'local.json',[])+[value])
        return public(value,True)
    @app.get('/api/reference-library')
    def listing(source:str='',category:str='',q:str='',page:int=1,application:str=''):
        all_rows=catalogue()
        rows=[v for v in all_rows if (not source or source==v['source']) and (not category or category in categories(v)) and q.lower() in (v['title']+' '+v.get('content','')).lower()]
        if application not in ('','narrative','camera','art'):raise ValueError('应用范围筛选无效')
        from .reference_profile import profile
        scopes={v['id']:profile({'primary_reference':v})['coverage'] for v in rows}
        application_counts={'all':len(rows),**{key:sum(bool(scope[key]) for scope in scopes.values()) for key in ('narrative','camera','art')}}
        if application:rows=[v for v in rows if scopes[v['id']][application]]
        start=max(0,page-1)*24
        return {'items':[public(v) for v in rows[start:start+24]],'total':len(rows),'page':page,'page_size':24,'application_counts':application_counts,'application':application,'categories':sorted({c for v in all_rows if not source or source==v['source'] for c in categories(v)}),'sync':state()}
    @app.post('/api/reference-library/sync')
    def start_sync(body:dict):
        source=body.get('source','all')
        if source not in ('all','flova','seedance'):raise ValueError('资料来源无效')
        with LOCK:
            if STATE['status']=='running':return state()
            progress(status='running',source=source,completed=0,total=0,errors=[],message='正在读取精选目录',started=time.time())
            threading.Thread(target=sync,args=(source,),daemon=True).start()
        return state()
    @app.get('/api/reference-library/files/{identity}/{version}/{filename}')
    def file(identity:str,version:str,filename:str):
        if filename not in ('skill.md','poster.webp','reference.mp4'):raise ValueError('文件类型无效')
        path=(ROOT/identity/version/filename).resolve()
        if not path.is_relative_to(ROOT.resolve()) or not path.is_file():raise ValueError('本地文件不存在')
        return FileResponse(path)
    @app.get('/api/reference-library/{identity}')
    def detail(identity:str):return public(item(identity),True)
    @app.post('/api/reference-library/{identity}/cache-video')
    def cache(identity:str):
        v=item(identity)
        threading.Thread(target=cache_video,args=(identity,v['version']),daemon=True).start()
        return {'status':'queued'}
    @app.post('/api/projects/{pid}/primary-reference')
    def adopt(pid:str,body:dict):
        p=store.get_project(pid)
        if p['revision']!=body.get('revision'):raise store.Conflict('项目已更新，请刷新后采用')
        v=item(body['id']) if body.get('id') else None
        if v and body.get('version') and body['version']!=v['version']:raise ValueError('资料库版本已更新，请查看库中最新版本后明确采用')
        if v and not v.get('available'):raise ValueError('需先取得完整正文后才能采用')
        if v:
            from .reference_profile import profile
            if profile({'primary_reference':v})['status']=='review_only':raise ValueError('此条目暂只有查看资料，没有可应用的叙事、镜头或美术方法；请选择已有方法的模板')
        p['primary_reference']=copy.deepcopy(v)
        p['reference_selection_resolved']=True
        from . import authoring
        authoring.invalidate(p,1)
        saved=store.save_project(p,p['revision'])
        if v and v['source']=='flova':threading.Thread(target=cache_video,args=(v['id'],v['version']),daemon=True).start()
        return saved
    @app.get('/api/projects/{pid}/primary-reference')
    def pinned(pid:str):
        value=store.get_project(pid).get('primary_reference')
        return public(value,True) if value else None
