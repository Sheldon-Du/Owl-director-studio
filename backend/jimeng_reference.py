"""Read public, server-rendered Jimeng image detail data without cookies."""
import json,re
from urllib.parse import urlparse
import httpx

def detail_url(url):
    if not isinstance(url,str) or len(url)>3000:raise ValueError('即梦详情链接无效')
    parsed=urlparse(url)
    if parsed.scheme!='https' or parsed.hostname!='jimeng.jianying.com' or parsed.username or parsed.password or parsed.port not in (None,443) or not re.fullmatch(r'/ai-tool/work-detail/\d+/?',parsed.path):raise ValueError('请粘贴即梦图片详情链接，不能使用探索首页地址')
    return url

def parse(html,url):
    match=re.search(r'window\._ROUTER_DATA\s*=\s*',html)
    if not match:raise ValueError('页面没有公开详情数据，请手动粘贴图片和提示词')
    try:data,_=json.JSONDecoder().raw_decode(html[match.end():])
    except ValueError:raise ValueError('公开详情数据格式变化，请使用手动输入')
    if not isinstance(data,dict) or not isinstance(data.get('loaderData'),dict):raise ValueError('公开详情格式变化，请使用手动输入')
    loaders=data['loaderData']
    page=next((v for v in loaders.values() if isinstance(v,dict) and isinstance(v.get('workDetail'),dict)),{})
    value=page.get('workDetail',{}).get('value',{})
    if not isinstance(value,dict):raise ValueError('作品详情不可用，请使用手动输入')
    prompt=(value.get('aigcImageParams',{}).get('text2imageParams',{}) or value.get('text2imageParams',{})).get('prompt','')
    images=(value.get('image') or {}).get('largeImages',[])
    if not isinstance(prompt,str) or not prompt.strip() or not images:raise ValueError('该作品没有公开图片与提示词，请选择图片作品，或手动填写')
    image=next((v for v in images if isinstance(v,dict) and isinstance(v.get('imageUrl'),str) and v['imageUrl'].startswith('https://')),None)
    if not image:raise ValueError('没有可下载的公开原图')
    return {'source_url':url,'image_url':image['imageUrl'],'prompt':prompt,'title':value.get('commonAttr',{}).get('title') or '即梦图片 '+urlparse(url).path.strip('/').split('/')[-1]}

def fetch(url):
    detail_url(url)
    with httpx.Client(timeout=25,trust_env=False,follow_redirects=False) as client:
        with client.stream('GET',url,headers={'User-Agent':'Mozilla/5.0'}) as response:
            if response.status_code!=200:raise ValueError('暂时无法读取公开详情，请手动输入或稍后重试')
            parts=[];size=0
            for part in response.iter_bytes():
                size+=len(part)
                if size>3*1024*1024:raise ValueError('详情页面过大，请使用手动输入')
                parts.append(part)
            return parse(b''.join(parts).decode('utf8'),url)

def install(app):
    @app.post('/api/visual/jimeng/detail')
    def read(body:dict):return fetch(body.get('url'))
