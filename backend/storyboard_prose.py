"""Readable prose derived from the same shots used for media production."""
from pathlib import Path
from fastapi.responses import Response
from . import store

RULE=Path(__file__).resolve().parents[1]/'rules/storyboard-prose.md'

def rules():return RULE.read_text(encoding='utf-8')

def lines(value):
    if isinstance(value,str):return value.strip()
    if isinstance(value,list):return '\n'.join(str(v) for v in value if isinstance(v,str) and v.strip())
    return ''

def shot_text(project,shot,index):
    native=shot.get('native',{});roles=lines(native.get('角色'))
    if not roles and '角色' in native:roles='无出镜角色'
    if not roles:
        names=[r.get('name') for r in native.get('连续性接口',{}).get('start',{}).get('characters',[]) if isinstance(r,dict) and r.get('name')]
        roles='、'.join(names) if names else '待核对：旧分镜未单独标注出镜角色'
    location=native.get('场景')
    if not location:location=next((o.get('location') for o in project.get('storyboard_generation',{}).get('outlines',[]) if o.get('id')==shot.get('generation_outline_id')),'')
    dialogue=lines(native.get('台词'))
    if not dialogue:dialogue='\n'.join(dict.fromkeys(a.get('dialogue','') for a in shot.get('actions',[]) if a.get('dialogue')))
    voiceover=lines(native.get('旁白'))
    if not voiceover:voiceover='\n'.join(dict.fromkeys(a.get('voiceover','') for a in shot.get('actions',[]) if a.get('voiceover')))
    speech_known='台词' in native or bool(native.get('生成预检',{}).get('passed'))
    sound=lines(native.get('音效')) or ('未单独标注；完整声音设计：'+str(native.get('声音') or native.get('音频描述') or '待核对'))
    rows=[f'第 {index} 镜 · 当前时长 {shot.get("duration",native.get("时长","待定"))} 秒',
          '画面内容：'+str(native.get('画面焦点') or shot.get('description') or '待填写'),
          '景别：'+str(native.get('景别') or '待填写'),'视角：'+str(native.get('角度') or '待填写'),'运镜：'+str(native.get('运镜') or '待填写'),
          '角色：'+roles,'场景：'+str(location or '待核对：旧分镜未单独标注地点'),
          '台词：'+(dialogue or ('无对白' if speech_known else '待核对：旧分镜未单独标注台词'))]
    if voiceover:rows.append('旁白：'+voiceover)
    rows.append('音效：'+sound)
    return '\n'.join(rows)

def render(project):
    shots=project.get('shots',[])
    return project.get('name','分镜文字稿')+' · 分镜文字稿\n\n'+('\n\n'.join(shot_text(project,s,i+1) for i,s in enumerate(shots)) if shots else '具体分镜尚未生成。完成一镜即可查看这一镜的文字稿。')

def install_routes(app):
    @app.get('/api/projects/{pid}/storyboard/text')
    def text(pid:str):
        p=store.get_project(pid);return {'text':render(p),'count':len(p.get('shots',[])),'revision':p['revision']}
    @app.get('/api/projects/{pid}/storyboard/text/download')
    def download(pid:str):return Response(render(store.get_project(pid)),media_type='text/plain; charset=utf-8',headers={'Content-Disposition':'attachment; filename="Owl-storyboard.txt"'})
