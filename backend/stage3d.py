"""Per-shot editable previs. Scene drafts never rewrite reviewed timing or H3."""
from . import script_source
import base64
import copy
import hashlib
import io
import json
import math
import re
import time
from PIL import Image
from . import store, ai, exporter

KINDS = ('character', 'box', 'sphere', 'wall', 'table', 'chair', 'door')
POSES = ('stand', 'sit', 'kneel', 'walk', 'run', 'raise_hand', 'arms_out')


def shot(project, sid):
    result = next((s for s in project.get('shots', []) if s['id'] == sid), None)
    if not result:raise ValueError('本镜不存在，请先生成具体分镜')
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def stage_hash(project, sid):
    return digest(shot(project, sid).get('stage3d'))


def h3_reference(project, s):
    """Use saved spatial planning, never turn proxy geometry into final appearance."""
    scene=s.get('stage3d')
    if not scene:return None
    names={a['id']:a.get('name') for a in project.get('assets',[])}
    objects=[{**{k:o.get(k) for k in ('id','name','kind','asset_id','pose','position','rotation','size','keyframes')},'asset_name':names.get(o.get('asset_id'))} for o in scene.get('objects',[])]
    return {'duration':scene.get('duration'),'shot_duration':s.get('duration'),'ratio':scene.get('ratio'),
        'camera':copy.deepcopy(scene.get('camera',{})),'objects':objects,
        'timing_matches':scene.get('duration')==s.get('duration'),
        'usage':'Saved previs: spatial blocking, camera position/target, focal length and camera path only. Real appearance comes from asset images; approved shot actions and timing take precedence.'}


def source_hash(project, sid):
    s = shot(project, sid)
    return digest({'shot':{k:s.get(k) for k in ('id','description','prompt','duration','native','actions','asset_ids')},
        'assets':[{k:a.get(k) for k in ('id','name','kind','description')} for a in project.get('assets', [])],
        'scheme':project.get('production_scheme'), 'script':script_source.text(project,False)})


def number(value, lo, hi, name):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'3D {name}需为 {lo} 至 {hi} 的有限数值')
    return round(value, 5)


def vector(value, name, lo=-100, hi=100):
    if not isinstance(value,list) or len(value)!=3:raise ValueError('3D '+name+'需要三个坐标')
    return [number(v,lo,hi,name) for v in value]


def color(value):
    if not isinstance(value,str) or not re.fullmatch(r'#[0-9a-fA-F]{6}',value):raise ValueError('3D 颜色需为 #RRGGBB')
    return value


def normalize(scene, project, sid):
    if not isinstance(scene,dict) or scene.get('version')!=1:raise ValueError('3D 工程版本不支持')
    s=shot(project,sid);duration=float(s['duration'])
    if abs(number(scene.get('duration'),.1,14400,'时长')-duration)>.001:raise ValueError('预演时长须与本镜一致，不自动改变动作时长')
    ratio=scene.get('ratio',[16,9])
    if ratio not in ([16,9],[9,16],[1,1],[4,3],[21,9]):raise ValueError('3D 画幅不支持')
    items=scene.get('objects')
    if not isinstance(items,list) or len(items)>48:raise ValueError('3D 对象最多48个')
    known={a['id']:a for a in project.get('assets',[])};seen=set();objects=[]
    for o in items:
        if not isinstance(o,dict):raise ValueError('3D 对象格式无效')
        identity=o.get('id');kind=o.get('kind');name=o.get('name')
        if not isinstance(identity,str) or not 1<=len(identity)<=80 or identity in seen:raise ValueError('3D 对象ID无效或重复')
        if kind not in KINDS or not isinstance(name,str) or not name.strip() or len(name)>120:raise ValueError('3D 对象类型或名称无效')
        asset=o.get('asset_id') or None
        if asset and (asset not in known or (kind=='character' and known[asset]['kind']!='character')):raise ValueError('3D 引用了其他项目或已删除的资产')
        pose=o.get('pose','stand')
        if pose not in POSES:raise ValueError('3D 姿态不支持')
        row={'id':identity,'kind':kind,'name':name,'asset_id':asset,'pose':pose,
             'position':vector(o.get('position'),'位置'),'rotation':number(o.get('rotation',0),-3600,3600,'朝向'),
             'size':vector(o.get('size',[1,1.7,1]),'尺寸',.03,30),'color':color(o.get('color','#8ca9c9'))}
        keys=o.get('keyframes',[])
        if not isinstance(keys,list) or len(keys)>12:raise ValueError('每个对象最多12个位置关键帧')
        row['keyframes']=[];last=-1
        for key in keys:
            if not isinstance(key,dict):raise ValueError('3D 关键帧格式无效')
            t=number(key.get('time'),0,duration,'关键帧时间')
            if t<=last:raise ValueError('3D 关键帧须按时间递增，不能重复')
            last=t;kp=key.get('pose',pose)
            if kp not in POSES:raise ValueError('3D 关键帧姿态不支持')
            row['keyframes'].append({'time':t,'position':vector(key.get('position'),'关键帧位置'),
                'rotation':number(key.get('rotation',row['rotation']),-3600,3600,'关键帧朝向'),'pose':kp})
        objects.append(row);seen.add(identity)
    cam=scene.get('camera',{})
    if not isinstance(cam,dict):raise ValueError('3D 机位格式无效')
    camera={'position':vector(cam.get('position'),'机位'),'target':vector(cam.get('target'),'注视点'),
        'focal':number(cam.get('focal',35),12,200,'焦距'),'motion':bool(cam.get('motion',False)),
        'end_position':vector(cam.get('end_position',cam.get('position')),'结束机位'),
        'end_target':vector(cam.get('end_target',cam.get('target')),'结束注视点')}
    for p,t in ((camera['position'],camera['target']),(camera['end_position'],camera['end_target'])):
        if sum((a-b)**2 for a,b in zip(p,t))<.0001:raise ValueError('机位与注视点不能重合')
    return {'version':1,'duration':duration,'ratio':ratio,'objects':objects,'camera':camera,
        'background':color(scene.get('background','#171f2e')),'floor':color(scene.get('floor','#485365')),
        'light':number(scene.get('light',2),.1,8,'灯光强度')}


def default(project, sid):
    s=shot(project,sid);ids=set(s.get('asset_ids',[]));visible=[]
    if ids:visible=[a for a in project.get('assets',[]) if a['id'] in ids and a['kind'] in ('character','prop')]
    else:
        text=' '.join(str(s.get(k,'')) for k in ('description','prompt'))
        visible=[a for a in project.get('assets',[]) if a['name'] in text and a['kind'] in ('character','prop')]
    objects=[]
    for i,a in enumerate(visible[:12]):
        kind='character' if a['kind']=='character' else 'table' if any(v in a['name'] for v in ('桌','table')) else 'box'
        objects.append({'id':'asset-'+a['id'],'asset_id':a['id'],'name':a['name'],'kind':kind,'pose':'stand',
            'position':[(i%4-1.5)*1.3,0,(i//4)*2],'rotation':0,'size':[1,1.7,1] if kind=='character' else [1.2,.8,.6],
            'color':['#91b9ce','#d0a87c','#bc95bc','#a5bf90'][i%4],'keyframes':[]})
    if not objects:objects=[{'id':'actor-1','name':'站位人物','kind':'character','pose':'stand','position':[0,0,0],'rotation':0,'size':[1,1.7,1],'color':'#91b9ce','keyframes':[]}]
    ratio=[9,16] if '9:16' in str(project.get('parameters',{}).get('画幅比例','')) else [16,9]
    return normalize({'version':1,'duration':s['duration'],'ratio':ratio,'objects':objects,
        'camera':{'position':[4,2.3,6],'target':[0,.95,0],'focal':35}},project,sid)


def read(project,sid):
    s=shot(project,sid)
    # A deleted asset does not make the editor inaccessible; detach its draft link.
    scene=copy.deepcopy(s.get('stage3d') or default(project,sid))
    known={a['id'] for a in project.get('assets',[])}
    for o in scene['objects']:
        if o.get('asset_id') not in known:o['asset_id']=None
    scene['duration']=float(s['duration'])
    for o in scene['objects']:o['keyframes']=[k for k in o.get('keyframes',[]) if k['time']<=scene['duration']]
    return {'scene':scene,'stage_hash':stage_hash(project,sid),'source_hash':source_hash(project,sid),
        'suggestion':s.get('stage3d_suggestion'),'captures':s.get('stage3d_captures',[]),'revision':project['revision']}


def check(project,sid,expected,source):
    if expected!=stage_hash(project,sid):raise store.Conflict('本镜3D预演已更新，未覆盖当前布置；请重新加载')
    if source!=source_hash(project,sid):raise store.Conflict('本镜剧本、时长或资产已更新，请重新加载3D预演再保存')


def save(project,sid,body):
    check(project,sid,body.get('stage_hash'),body.get('source_hash'))
    scene=normalize(body.get('scene'),project,sid)
    shot(project,sid)['stage3d']=scene
    return scene


def capture(project,sid,body):
    check(project,sid,body.get('stage_hash'),body.get('source_hash'))
    s=shot(project,sid)
    if not s.get('stage3d'):raise ValueError('请先保存3D布置')
    value=body.get('image','')
    if not isinstance(value,str) or not value.startswith('data:image/png;base64,') or len(value)>6000000:raise ValueError('截图需为6MB以内的PNG')
    try:
        data=base64.b64decode(value.split(',',1)[1],validate=True)
        with Image.open(io.BytesIO(data)) as image:
            if image.format!='PNG' or not (64<=image.width<=2048 and 64<=image.height<=2048):raise ValueError('截图尺寸无效')
            width,height=image.size;image.verify()
    except Exception as error:raise ValueError('3D 截图无效') from error
    t=number(body.get('time',0),0,s['duration'],'截图时间')
    name=store.uid()+'.png';store.media_path(name).write_bytes(data)
    m={'id':store.uid(),'media':name,'kind':'image','name':f'3D构图 · {s.get("description",sid)[:25]} · {t:g}s',
        'origin':'stage3d','source_shot_id':sid,'is_previs':True,'stage_hash':body['stage_hash'],'stage_scene':copy.deepcopy(s['stage3d']),
        'time':t,'width':width,'height':height,'created':time.time()}
    s.setdefault('stage3d_captures',[]).append(copy.deepcopy(m));s.setdefault('frames',[]).append(copy.deepcopy(m));project['media'].append(m)
    return m


def reference(project,sid,media):
    s=shot(project,sid)
    layout=next((m for m in s.get('layout_images',[]) if m['media']==media and m['kind']=='image'),None)
    if layout and store.media_path(media).is_file():return {'media':media,'role':'composition','note':'只参考本阶段白模的构图、站位、姿态、相对大小与遮挡；外貌、服饰、材质以资产图为准，不复制白模、标签或灰色材质'}
    m=next((m for m in s.get('stage3d_captures',[]) if m['media']==media and m['kind']=='image'),None)
    if not m or not store.media_path(media).is_file():raise ValueError('构图参考必须是本镜保存的3D截图')
    return {'media':media,'role':'composition','note':'只参考本镜3D预演的构图、人物站位、姿态、遮挡和机位；人物外貌、服饰和场景材质以资产图为准'}


def recommend(project,sid,report=None,description=''):
    s=shot(project,sid);report=report or (lambda v:None)
    schema=default(project,sid)
    evidence=next((v.strip() for v in [s.get('description'),s.get('prompt'),*s.get('native',{}).values()] if isinstance(v,str) and v.strip()),'')
    if not evidence:raise ValueError('本镜缺少画面描述，请先完成具体分镜')
    payload={'shot':{k:s.get(k) for k in ('description','prompt','duration','native','actions','asset_ids')},
        'scheme':project.get('production_scheme'),'assets':[{k:a.get(k) for k in ('id','kind','name','description')} for a in project.get('assets',[])],
        'scene_example':s.get('stage3d') or schema,'kinds':KINDS,'poses':POSES,'user_layout_request':str(description)[:6000]}
    system='''按用户已生成的 DirectorMaster 分镜推荐可编辑3D预演。只输出JSON {scene:工程,evidence:本镜原句,explanation:布置解释}。不改剧本、动作顺序、镜头时长；duration严格等于本镜duration。参考native中的构图、景别、运镜和动作预案。工程version=1，格式严格按scene_example：位置三元素数组，rotation为绕Y轴度数，size为三元素正数，颜色#RRGGBB，对象kind和pose必须在目录内。已有角色/道具只能使用目录中的asset_id；墙、桌、门等简单空间支架可asset_id=null。不把未出现在本镜的人物加入。最多24个对象、每对象最多12个递增位置关键帧(time/position/rotation/pose)；起始位置与关键帧0一致。只表达有依据的动作，不伪造精细动作能力。camera包含position/target/focal/motion/end_position/end_target；人物面对+Z，Y竖直向上，单位米。evidence必须逐字引用本镜description或prompt或native的一段。场景是预演人偶，不生成外貌图片。'''
    system+=' user_layout_request是用户对空间、姿态、尺寸和摄影机的补充要求，请在现有布局基础上调整，仍不得新增剧情。'
    system=system.replace('JSON {scene:工程,evidence:本镜原句,explanation:布置解释}','JSON {scene:工程,explanation:布置解释}').replace('evidence必须逐字引用本镜description或prompt或native的一段。','本镜原句由程序绑定，不需要返回或重新抄写evidence。')
    report('正在按本镜 DirectorMaster 构图、空间与动作规则推荐3D布置')
    error=''
    for attempt in range(2):
        with ai.asset_call_policy('stage3d',limit=1,max_tokens=6000,timeout=180):
            result=ai.ask(system,json.dumps({**payload,**({'repair':error} if error else {})},ensure_ascii=False))
        try:
            scene=normalize(result.get('scene'),project,sid)
            explanation=result.get('explanation')
            explanation=explanation.strip() if isinstance(explanation,str) else ''
            if not explanation:
                names='、'.join(o['name'] for o in scene['objects']) or '空场景'
                explanation=f'布局对象：{names}。摄影机位置：{scene["camera"]["position"]}；注视点：{scene["camera"]["target"]}；焦距：{scene["camera"]["focal"]:g}mm。请查看Blender布局图核对空间关系。'
            return {'id':store.uid(),'scene':scene,'evidence':evidence,'explanation':explanation[:4000],
                'evidence_source':'shot','stage_hash':stage_hash(project,sid),'source_hash':source_hash(project,sid),'created':time.time()}
        except ValueError as exc:
            error=str(exc);report('修正3D布置格式：'+error)
    raise ValueError('AI 3D 推荐未通过校验：'+error)


def movie(project,sid,body,source):
    check(project,sid,body.get('stage_hash'),body.get('source_hash'))
    s=shot(project,sid);duration=float(s['duration'])
    if not s.get('stage3d') or duration>30:raise ValueError('预演导出需先保存布置；单镜最多30秒，请分段规划长镜')
    import imageio_ffmpeg
    reader=imageio_ffmpeg.read_frames(str(source))
    try:meta=next(reader)
    finally:reader.close()
    if abs(float(meta['duration'])-duration)>.2:raise ValueError('预演录制时长与本镜不符，请重新导出；不慢放补时')
    name=store.uid()+'.mp4'
    try:
        exporter.run(['-i',str(source),'-an','-vf','scale=-2:480','-r','24','-c:v','libx264','-crf','20','-pix_fmt','yuv420p','-t',str(duration),'-movflags','+faststart',str(store.media_path(name))])
    except Exception:
        store.media_path(name).unlink(missing_ok=True);raise
    m={'id':store.uid(),'media':name,'kind':'video','name':'3D预演 · '+s.get('description',sid)[:30],
        'duration':duration,'origin':'stage3d','is_previs':True,'source_shot_id':sid,
        'stage_hash':body['stage_hash'],'stage_scene':copy.deepcopy(s['stage3d']),'created':time.time()}
    s.setdefault('stage3d_captures',[]).append(copy.deepcopy(m));project['media'].append(m)
    return m
