"""Trusted geometry template executed by the MIT Blender Wrapper. Y-up input."""
import bpy, math, json, os
from mathutils import Vector
scene_data=config['scene'];t=config['time']
bpy.ops.object.select_all(action='SELECT');bpy.ops.object.delete(use_global=False)
def pos(v):return Vector((v[0],v[2],v[1]))
def mat(name,c):
 m=bpy.data.materials.new(name);m.use_nodes=True;m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value=(*(int(c[i:i+2],16)/255 for i in (1,3,5)),1);return m
def cube(loc,size,m):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(m);return o
def sphere(loc,size,m):
 bpy.ops.mesh.primitive_uv_sphere_add(segments=20,ring_count=12,location=loc);o=bpy.context.object;o.scale=size;o.data.materials.append(m);return o
def interpolate(o):
 keys=[{'time':0,**o},*o.get('keyframes',[])];a=keys[0];b=a
 for k in keys:
  if k['time']<=t:a=k
  else:b=k;break
 else:b=a
 f=(t-a['time'])/(b['time']-a['time']) if b['time']>a['time'] else 0
 return {**o,'position':[x+(y-x)*f for x,y in zip(a['position'],b['position'])],'rotation':a['rotation']+(b['rotation']-a['rotation'])*f,'pose':a.get('pose',o['pose'])}
# Clothing overlapping a character is an appearance reference, not a solid wall.
characters=[interpolate(o) for o in scene_data['objects'] if o['kind']=='character']
wearables=('蟒袍','衣袍','长袍','官服','制服','校服','衣服','外套','玉带','腰带','帽子','冠冕','服装','robe','clothing','belt','outfit')
notes=[]
palette=['#70b9df','#dfac69','#be91d5','#88bf91','#dd8790','#81c8bd']
for index,raw in enumerate(scene_data['objects']):
 o=interpolate(raw)
 attached=o['kind']=='box' and any(w in o['name'].lower() for w in wearables) and any(math.hypot(o['position'][0]-a['position'][0],o['position'][2]-a['position'][2])<max(.6,a['size'][0]) and abs(o['position'][1]-a['position'][1])<a['size'][1] for a in characters)
 if attached:
  notes.append(o['name']+'：作为人物穿戴参考，不创建遮挡人物的独立方块');continue
 c=o['color']
 if c.lower()=='#8ca9c9':c='#637180' if o['kind']=='wall' else palette[index%len(palette)]
 m=mat(o['name'],c);start=set(bpy.data.objects);kind=o['kind'];w,h,d=o['size']
 if kind=='character':
  sit=o['pose'] in ('sit','kneel');z=h*(.58 if sit else .87)
  sphere((0,0,z),(.085*h,.075*h,.1*h),m);cube((0,0,z-.26*h),(.24*h,.15*h,.32*h),m)
  for x in (-.07*h,.07*h):
   if sit:
    cube((x,.13*h,.3*h),(.08*h,.3*h,.09*h),m);cube((x,.24*h,.15*h),(.07*h,.08*h,.3*h),m)
   else:cube((x,0,.24*h),(.08*h,.09*h,.48*h),m)
  for x in (-.15*h,.15*h):cube((x,0,z-.27*h),(.06*h,.07*h,.37*h),m)
 elif kind=='table':
  cube((0,0,h-.05),(w,d,.1),m)
  for x in (-w*.4,w*.4):
   for y in (-d*.4,d*.4):cube((x,y,h/2),(.07,.07,h),m)
 elif kind=='chair':
  cube((0,0,h*.42),(w,d,.1),m);cube((0,-d*.42,h*.73),(w,.08,h*.54),m)
  for x in (-w*.4,w*.4):
   for y in (-d*.4,d*.4):cube((x,y,h*.2),(.06,.06,h*.4),m)
 elif kind=='sphere':sphere((0,0,h/2),(w/2,d/2,h/2),m)
 elif kind=='door':
  for x in (-w/2,w/2):cube((x,0,h/2),(.1,d,h),m)
  cube((0,0,h),(w,d,.1),m)
 else:cube((0,0,h/2),(w,d,h),m)
 origin=pos(o['position']);angle=-math.radians(o['rotation'])
 for obj in set(bpy.data.objects)-start:
  obj.name=o['name'];p=obj.location.copy();obj.location=origin+Vector((p.x*math.cos(angle)-p.y*math.sin(angle),p.x*math.sin(angle)+p.y*math.cos(angle),p.z));obj.rotation_euler.z+=angle
cube((0,0,-.08),(30,30,.16),mat('地面',scene_data['floor']))
cam=scene_data['camera'];f=t/scene_data['duration'] if cam['motion'] else 0
cp=[a+(b-a)*f for a,b in zip(cam['position'],cam['end_position'])];ct=[a+(b-a)*f for a,b in zip(cam['target'],cam['end_target'])]
bpy.ops.object.camera_add(location=pos(cp));camera=bpy.context.object;camera.rotation_euler=(pos(ct)-camera.location).to_track_quat('-Z','Y').to_euler();camera.data.lens=cam['focal'];camera.data.sensor_width=36
s=bpy.context.scene;s.camera=camera;s.world.use_nodes=True;s.world.node_tree.nodes.get('Background').inputs['Color'].default_value=(.18,.22,.28,1);s.world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.6
bpy.ops.object.light_add(type='AREA',location=(2,-3,7));bpy.context.object.data.energy=600*scene_data['light'];bpy.context.object.data.size=5;bpy.context.object.rotation_euler=(pos(ct)-bpy.context.object.location).to_track_quat('-Z','Y').to_euler()
s.render.engine='CYCLES';s.cycles.samples=24;s.render.resolution_x=960;s.render.resolution_y=round(960*scene_data['ratio'][1]/scene_data['ratio'][0]);s.render.resolution_percentage=100
s.render.image_settings.file_format='PNG';s.render.filepath=config['image_path']
bpy.ops.wm.save_as_mainfile(filepath=config['blend_path']);bpy.ops.render.render(write_still=True)
with open(os.environ['OUTPUT_JSON'],'w',encoding='utf-8') as f:json.dump({'image':config['image_path'],'blend':config['blend_path'],'notes':notes},f)
