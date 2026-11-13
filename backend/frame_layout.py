"""MiniMax-authored white-model SVG, rasterized locally for ComfyUI."""
import copy,hashlib,json,math,re,time
import xml.etree.ElementTree as ET
from PIL import Image,ImageDraw,ImageFont
from . import ai,store,keyframes

MODES={'frame':'first','keyframe':'middle','tail':'last'}
TAGS={'svg','g','rect','ellipse','circle','polygon','polyline','line','path','text'}
ATTRS={'width','height','viewBox','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','points','d','fill','stroke','stroke-width','font-size','text-anchor','opacity','fill-opacity','stroke-opacity','stroke-linecap','stroke-linejoin','id','xmlns'}
NUM=r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?'

def fingerprint(project,shot,mode):
    plan=shot.get('image_plans',{}).get(mode,{})
    return hashlib.sha256(json.dumps({'base':keyframes.fingerprint(project,shot),'mode':mode,'plan':{k:plan.get(k) for k in ('relationship','prompt','required_assets','selected_asset_ids')},'selected':plan.get('asset_ids',shot.get('asset_ids',[]))},ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def validate(value):
    svg=value.get('svg')
    if not isinstance(svg,str) or not 30<len(svg)<150000 or re.search(r'<!|<\?|https?://(?!www\.w3\.org/2000/svg)',svg,re.I):raise ValueError('布局SVG必须是独立静态图形，不能包含外部内容')
    try:root=ET.fromstring(svg)
    except ET.ParseError:raise ValueError('布局SVG语法无效')
    if root.tag.split('}')[-1]!='svg':raise ValueError('布局需以svg为根元素')
    if len(list(root.iter()))>400:raise ValueError('布局图过于复杂，请使用简模')
    box=re.findall(NUM,root.get('viewBox',''))
    if len(box)!=4 or [float(n) for n in box[:2]]!=[0,0]:raise ValueError('布局viewBox必须从0,0开始')
    w,h=[float(n) for n in box[2:]]
    if not all(math.isfinite(n) and 64<=n<=2048 for n in (w,h)):raise ValueError('布局尺寸无效')
    shapes=0
    for e in root.iter():
        tag=e.tag.split('}')[-1]
        if tag not in TAGS or any(k not in ATTRS for k in e.attrib):raise ValueError('布局仅允许静态基础图形和文字，禁止脚本、外链、样式及变换')
        for k,v in e.attrib.items():
            if k in ('fill','stroke') and not re.fullmatch(r'none|white|black|#[0-9a-fA-F]{6}',v):raise ValueError('白模图使用直接颜色值')
            if k in ('fill','stroke') and v.startswith('#') and not v[1:3].lower()==v[3:5].lower()==v[5:7].lower():raise ValueError('白模图只使用灰度颜色')
            if k not in ('fill','stroke','id','text-anchor','stroke-linecap','stroke-linejoin'):
                numbers=[float(n) for n in re.findall(NUM,v)]
                if any(not math.isfinite(n) or abs(n)>10000 for n in numbers):raise ValueError('图形坐标越界')
        if tag=='path':path_points(e.get('d',''))
        if tag in ('polygon','polyline') and len(re.findall(NUM,e.get('points','')))%2:raise ValueError('图形点坐标应成对')
        if tag not in ('svg','g','text'):shapes+=1
    if shapes<3:raise ValueError('布局图须包含具体白模和空间关系')
    if not isinstance(value.get('explanation',''),str):raise ValueError('布局说明格式无效')
    return {'svg':ET.tostring(root,encoding='unicode'),'explanation':value.get('explanation',''),'width':int(w),'height':int(h)}

def path_points(d):
    tokens=re.findall(r'[A-Za-z]|'+NUM,d)
    if re.sub(r'[MLQCZmlqcz\s,]|'+NUM,'',d):raise ValueError('路径只支持M/L/Q/C/Z指令')
    out=[];pos=(0.,0.);start=pos;cmd=None;i=0
    while i<len(tokens):
        if tokens[i].isalpha():cmd=tokens[i];i+=1
        if not cmd:raise ValueError('路径缺少指令')
        if cmd.upper()=='Z':out.append(start);pos=start;cmd=None;continue
        count={'M':2,'L':2,'Q':4,'C':6}.get(cmd.upper())
        if not count or i+count>len(tokens) or any(t.isalpha() for t in tokens[i:i+count]):raise ValueError('路径坐标不完整')
        v=[float(t) for t in tokens[i:i+count]];i+=count
        pairs=list(zip(v[::2],v[1::2]))
        if cmd.islower():pairs=[(x+pos[0],y+pos[1]) for x,y in pairs]
        if cmd.upper() in ('M','L'):
            pos=pairs[0];out.append(pos)
            if cmd.upper()=='M':start=pos;cmd='l' if cmd.islower() else 'L'
        else:
            p0=pos
            for step in range(1,17):
                t=step/16;u=1-t
                if cmd.upper()=='Q':p1,p2=pairs;point=tuple(u*u*p0[k]+2*u*t*p1[k]+t*t*p2[k] for k in (0,1))
                else:p1,p2,p3=pairs;point=tuple(u**3*p0[k]+3*u*u*t*p1[k]+3*u*t*t*p2[k]+t**3*p3[k] for k in (0,1))
                out.append(point)
            pos=pairs[-1]
    return out

def raster(value,path):
    scale=2;root=ET.fromstring(value['svg']);image=Image.new('RGB',(value['width']*scale,value['height']*scale),'#e6e6e6');draw=ImageDraw.Draw(image)
    def paint(e,inherited):
        style={**inherited,**e.attrib};tag=e.tag.split('}')[-1]
        num=lambda k,default=0:float(e.get(k,default))*scale
        fill=style.get('fill','#ffffff');fill=None if fill=='none' else fill
        stroke=style.get('stroke','#777777');stroke=None if stroke=='none' else stroke
        width=max(1,int(float(style.get('stroke-width',2))*scale))
        if tag=='rect':draw.rectangle((num('x'),num('y'),num('x')+num('width'),num('y')+num('height')),fill=fill,outline=stroke,width=width)
        elif tag in ('ellipse','circle'):
            rx=num('r') if tag=='circle' else num('rx');ry=num('r') if tag=='circle' else num('ry');draw.ellipse((num('cx')-rx,num('cy')-ry,num('cx')+rx,num('cy')+ry),fill=fill,outline=stroke,width=width)
        elif tag=='line':draw.line([(num('x1'),num('y1')),(num('x2'),num('y2'))],fill=stroke or '#777777',width=width)
        elif tag in ('polygon','polyline','path'):
            if tag=='path':points=path_points(e.get('d',''))
            else:vals=[float(n) for n in re.findall(NUM,e.get('points',''))];points=list(zip(vals[::2],vals[1::2]))
            points=[(x*scale,y*scale) for x,y in points]
            if len(points)>1:
                if fill and tag!='polyline':draw.polygon(points,fill=fill)
                if stroke:draw.line(points+([points[0]] if tag=='polygon' else []),fill=stroke,width=width,joint='curve')
        elif tag=='text':
            font=ImageFont.truetype(r'C:\Windows\Fonts\msyh.ttc',max(10,int(float(style.get('font-size',18))*scale)))
            anchor={'middle':'ms','end':'rs'}.get(style.get('text-anchor'),'ls')
            draw.text((num('x'),num('y')),''.join(e.itertext())[:150],fill=fill or '#333333',font=font,anchor=anchor)
        for child in e:paint(child,style)
    paint(root,{'fill':'#ffffff','stroke':'#777777','stroke-width':'2'})
    image.resize((value['width'],value['height']),Image.Resampling.LANCZOS).save(path,format='PNG')

def generate(project,shot,options,report):
    mode=options.get('mode','frame')
    if mode not in MODES:raise ValueError('布局帧类型无效')
    plan=shot.get('image_plans',{}).get(mode,{})
    ids=plan.get('selected_asset_ids',plan.get('asset_ids',shot.get('asset_ids',[])))
    five_s=shot.get('frame_cards',{}).get(MODES[mode],{})
    payload={'stage':MODES[mode],'ratio':project.get('parameters',{}).get('画幅比例','16:9'),'five_s':{k:five_s.get(k,'') for k in ('goal','subject','shot','setting','constraints')},'image_prompt':plan.get('prompt',''),'relationship':plan.get('relationship',''),'assets':[{k:a.get(k) for k in ('id','name','kind')} for a in project['assets'] if a['id'] in ids],'adjustment':str(options.get('description',''))[:6000]}
    system='你是白模构图图绘制助手。直接绘制一张SVG白模位置参考图，只输出JSON {svg:string,explanation:string}。服从本阶段5S、构图、透视、景别、人物姿态和遮挡，只画单一瞬间，不新增资产、不重复人物。用白色无五官人偶、几何道具和灰色空间表达位置与相对大小，头用椭圆，身体和四肢用多边形或曲线；白模有前后灰阶与简单阴影。按camera看到的角度绘制，不默认俯视平面图。引用资产编号写小标签A1/A2等，说明中列对应资产，禁止大块文字遮挡。仅允许svg/g/rect/ellipse/circle/polygon/polyline/line/path/text；svg viewBox从0 0开始，宽高对应画幅且各64–2048；推荐1024x576。只允许直接坐标、fill/stroke为none/white/black/#RRGGBB灰度、stroke-width、font-size、text-anchor；禁止transform/style/css/defs/filter/use/image/script/外链。路径只用M/L/Q/C/Z和小写形式，每张至少3个图形；所有文字位置直接指定x/y，不能使用tspan。几何体有清楚外轮廓和空间接触，不生成美术细节或成片。explanation简要说明空间关系和阶段状态。'
    system+=' 这是低复杂度位置草图：总共最多24个基础图形，总SVG不超过8000字符；每个角色只需头、躯干、两臂、两腿的白模轮廓，道具只画一个几何体。不要精密建模机器人零件、花瓣、手指，不画重复细节或网格。快速给出完整SVG，优先关系准确和完整收尾，explanation不超过120字。'
    report('MiniMax 正在直接绘制本阶段白模 SVG 位置图')
    with ai.asset_call_policy('frame_layout',limit=2,max_tokens=16384,timeout=150,preserve_context=True):
        try:value=ai.validated_image_response(system,payload,validate)
        except ValueError as error:
            if 'finish_reason=length' not in str(error):raise
            report('上游截断，已缩减为最多12个图形的简洁白模位置图')
            value=ai.validated_image_response(system+' 本次限制最多12个rect/ellipse/polygon/line元素，SVG不超过3000字符，不使用path或text。',payload,validate)
    return {**value,'mode':mode,'source_hash':fingerprint(project,shot,mode)}

def apply(project,sid,result):
    shot=next(s for s in project['shots'] if s['id']==sid);mode=result['mode']
    if fingerprint(project,shot,mode)!=result['source_hash']:raise store.Conflict('布局生成期间画面或资产参考已修改，旧结果未覆盖')
    uid=store.uid();svg='layout-'+uid+'.svg';png='layout-'+uid+'.png'
    raster(result,store.media_path(png));store.media_path(svg).write_text(result['svg'],encoding='utf-8')
    record={'id':uid,'media':png,'svg_media':svg,'kind':'image','mode':mode,'model':store.settings().get('ai_model'),'generator':'minimax-svg','source_hash':result['source_hash'],'explanation':result['explanation'],'created':time.time()}
    shot.setdefault('layout_images',[]).append(copy.deepcopy(record));project['media'].append(record)
    plan=shot.setdefault('image_plans',{}).setdefault(mode,{})
    plan.update(composition_reference=png,layout_svg=svg,layout_explanation=result['explanation'],layout_source_hash=result['source_hash'])
    return record
