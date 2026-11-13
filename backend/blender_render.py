"""Local Blender Wrapper adapter: validated data only, fixed trusted template."""
import os,json,time,subprocess,copy
from pathlib import Path
from PIL import Image
from . import store,stage3d
ROOT=Path(__file__).parent/'blender_runtime'
def executable():
 p=Path(os.environ.get('DIRECTOR_BLENDER_EXE',r'D:\2video\blender-5.4.0\blender.exe'))
 if not p.is_file():raise ValueError('本地Blender不存在，请设置DIRECTOR_BLENDER_EXE')
 return p
def render(project,sid,options,report,cancel=lambda:None):
 shot=stage3d.shot(project,sid)
 mode=options.get('mode');plan=shot.get('image_plans',{}).get(mode) if mode else None
 raw=plan.get('layout_scene') if plan else shot.get('stage3d')
 if not raw:raise ValueError('请先AI生成本阶段布局指令')
 scene=stage3d.normalize(raw,project,sid);at=stage3d.number(options.get('time',0),0,scene['duration'],'渲染时间')
 directory=store.media_path(store.uid()+'.png').parent/'blender_jobs'/store.uid();directory.mkdir(parents=True)
 exe=executable();template=directory/'template.blend'
 image=store.uid()+'.png';blend=store.uid()+'.blend'
 config={'scene':scene,'time':at,'image_path':str(store.media_path(image)),'blend_path':str(store.media_path(blend))}
 cp=directory/'config.json';cp.write_text(json.dumps(config,ensure_ascii=False),encoding='utf-8');result=directory/'result.json'
 def run(args,env=None):
  with (directory/'render.log').open('a',encoding='utf-8') as log:
   proc=subprocess.Popen([str(exe),'--background',*args],env=env,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   try:
    deadline=time.monotonic()+180
    while proc.poll() is None:
     cancel()
     if time.monotonic()>deadline:raise ValueError('Blender渲染超时，布局已保留')
     time.sleep(.25)
    if proc.returncode:raise ValueError('Blender执行失败，请查看 '+str(directory/'render.log'))
   finally:
    if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
 report('正在创建可复用Blender场景模板')
 run(['--python',str(ROOT/'bootstrap.py'),'--',str(ROOT/'main.py'),str(template)])
 env={**os.environ,'BLEND_FILE':str(template),'CONFIG_FILE':str(cp),'INPUT_MODEL':'','OUTPUT_JSON':str(result)}
 report(f'Blender Wrapper 正在渲染 {at:g} 秒构图')
 run(['--python',str(ROOT/'wrapper.py')],env)
 if not result.is_file() or not store.media_path(image).is_file():raise ValueError('Blender未返回构图结果，请查看 '+str(directory/'render.log'))
 with Image.open(store.media_path(image)) as im:width,height=im.size
 return {'id':store.uid(),'media':image,'kind':'image','name':f'Blender构图 · {at:g}s','origin':'stage3d','source_shot_id':sid,'is_previs':True,
  'stage_hash':stage3d.stage_hash(project,sid),'source_hash':stage3d.source_hash(project,sid),'stage_scene':copy.deepcopy(scene),'time':at,'width':width,'height':height,'created':time.time(),'blend_media':blend,'renderer':'Blender Wrapper','mode':mode,'layout_hash':stage3d.digest(raw)}
def apply(project,sid,result):
 # Keep finished versions even if the user edits the layout during rendering.
 s=stage3d.shot(project,sid);mode=result.get('mode');plan=s.get('image_plans',{}).get(mode) if mode else None
 result['stale']=(not plan or stage3d.digest(plan.get('layout_scene'))!=result['layout_hash']) if mode else result['stage_hash']!=stage3d.stage_hash(project,sid)
 result['stale']=result['stale'] or result['source_hash']!=stage3d.source_hash(project,sid)
 if mode and not result['stale']:plan['composition_reference']=result['media']
 s.setdefault('stage3d_captures',[]).append(copy.deepcopy(result));project['media'].append(copy.deepcopy(result))
