"""Ephemeral LAN phone controller. Tokens grant camera control, never project writes."""
import asyncio
import datetime
import ipaddress
import json
import math
import os
import secrets
import socket
import threading
import time
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from . import store

LOCK=threading.RLock()
SESSIONS={}
SERVER=None
PORT=None
ERROR=''


def addresses():
    result=[]
    try:
        for row in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET):
            addr=row[4][0]
            if not addr.startswith('127.') and addr not in result:result.append(addr)
    except OSError:pass
    return result


def certificate():
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    root=store.DATA/'stage3d-tls';root.mkdir(exist_ok=True)
    cert=root/'controller.crt';key=root/'controller.key'
    hosts=['127.0.0.1',*addresses()]
    renew=True
    if cert.exists() and key.exists():
        try:
            current=x509.load_pem_x509_certificate(cert.read_bytes())
            sans=current.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            renew=not set(hosts).issubset({str(v) for v in sans.get_values_for_type(x509.IPAddress)}) or current.not_valid_after_utc<datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1)
        except Exception:pass
    if renew:
        private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        owner=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'Director Studio LAN Camera')])
        now=datetime.datetime.now(datetime.timezone.utc)
        value=(x509.CertificateBuilder().subject_name(owner).issuer_name(owner).public_key(private.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-datetime.timedelta(minutes=5))
            .not_valid_after(now+datetime.timedelta(days=365))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName('localhost'),*[x509.IPAddress(ipaddress.ip_address(v)) for v in hosts]]),False)
            .add_extension(x509.BasicConstraints(ca=True,path_length=0),True).sign(private,hashes.SHA256()))
        key.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        cert.write_bytes(value.public_bytes(serialization.Encoding.PEM))
    return cert,key


def start():
    global SERVER,PORT,ERROR
    with LOCK:
        if SERVER and not SERVER.should_exit:return
        ERROR=''
        import uvicorn
        cert,key=certificate()
        listener=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:listener.bind(('0.0.0.0',int(os.environ.get('DIRECTOR_MOBILE_PORT','8879'))))
        except OSError:listener.bind(('0.0.0.0',0))
        PORT=listener.getsockname()[1]
        listener.listen(128)
        cfg=uvicorn.Config(phone_app,host='0.0.0.0',port=PORT,ssl_keyfile=str(key),ssl_certfile=str(cert),log_level='warning',access_log=False,ws_max_size=600000,limit_concurrency=20)
        SERVER=uvicorn.Server(cfg)
        def serve():
            global ERROR
            try:SERVER.run(sockets=[listener])
            except Exception as e:ERROR=str(e)
        threading.Thread(target=serve,daemon=True,name='stage-phone-https').start()
    for _ in range(30):
        if SERVER.started:return
        if ERROR:raise ValueError('手机取景服务启动失败：'+ERROR)
        time.sleep(.1)
    raise ValueError('手机取景服务尚未启动，请重试')


def create(pid,sid):
    start()
    token=secrets.token_urlsafe(28);desktop=secrets.token_urlsafe(28)
    with LOCK:
        for old,session in list(SESSIONS.items()):
            if session['expires']<time.time():SESSIONS.pop(old,None)
        if len(SESSIONS)>=16:raise ValueError('手机配对会话过多，请先关闭旧会话')
        SESSIONS[token]={'project':pid,'shot':sid,'desktop_key':desktop,'expires':time.time()+3600,'peers':{}}
    urls=[f'https://{v}:{PORT}/phone#{token}' for v in addresses()]
    import qrcode,io,base64
    codes=[]
    for url in urls:
        image=qrcode.make(url);buffer=io.BytesIO();image.save(buffer,format='PNG')
        codes.append('data:image/png;base64,'+base64.b64encode(buffer.getvalue()).decode())
    return {'token':token,'desktop_key':desktop,'port':PORT,'phone_urls':urls,
        'qr_codes':codes,'trust_url':f'https://127.0.0.1:{PORT}/','expires':time.time()+3600}


def close(pid,sid,token):
    with LOCK:
        session=SESSIONS.get(token)
        if session and session['project']==pid and session['shot']==sid:session['expires']=0


def stop():
    if SERVER:SERVER.should_exit=True
    SESSIONS.clear()


def packet(data):
    if not isinstance(data,dict) or data.get('type') not in ('control','capture','calibrate'):raise ValueError('控制包无效')
    if data['type'] in ('capture','calibrate'):return {'type':data['type']}
    result={'type':'control'}
    limits={'move_x':(-1,1),'move_z':(-1,1),'lift':(-1,1),'yaw':(-1,1),'pitch':(-1,1),'focal':(12,200),
        'alpha':(-360,360),'beta':(-180,180),'gamma':(-180,180),'screen':(-360,360)}
    for key,(lo,hi) in limits.items():
        if key not in data:continue
        value=data[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('控制数值无效')
        result[key]=value
    return result


phone_app=FastAPI()


@phone_app.get('/')
def trust():
    return HTMLResponse('<meta charset="utf-8"><title>导演工坊手机取景</title><body style="background:#172032;color:#eef;font:18px sans-serif;padding:40px"><h2>本机手机取景服务已连接</h2><p>返回导演工坊，点击“连接桌面”。手机与电脑须在同一局域网。</p><p>此 HTTPS 服务只用于临时机位控制和取景画面。</p></body>')


@phone_app.get('/phone')
def page():return HTMLResponse(PAGE)


@phone_app.websocket('/control')
async def control(ws:WebSocket):
    await ws.accept()
    session=None;role=None
    try:
        hello=await asyncio.wait_for(ws.receive_json(),8)
        token=hello.get('token');role=hello.get('role')
        with LOCK:session=SESSIONS.get(token)
        if not session or session['expires']<time.time() or role not in ('desktop','phone'):
            await ws.close(1008);return
        if role=='desktop' and not secrets.compare_digest(str(hello.get('key','')),session['desktop_key']):
            await ws.close(1008);return
        if role in session['peers']:
            await ws.close(1008);return
        session['peers'][role]=ws
        await ws.send_json({'type':'connected','role':role})
        peer=session['peers'].get('phone' if role=='desktop' else 'desktop')
        if peer:await peer.send_json({'type':'peer','online':True})
        last=0
        while session['expires']>time.time():
            try:message=await asyncio.wait_for(ws.receive(),20)
            except asyncio.TimeoutError:
                await ws.send_json({'type':'heartbeat'});continue
            if message['type']=='websocket.disconnect':break
            now=time.monotonic()
            if now-last<.02:continue
            last=now;peer=session['peers'].get('phone' if role=='desktop' else 'desktop')
            if message.get('bytes') is not None:
                raw=message['bytes']
                if role!='desktop' or len(raw)>500000 or not raw.startswith(b'\xff\xd8'):continue
                if peer:await peer.send_bytes(raw)
            elif role=='desktop' and message.get('text') and len(message['text'])<1000:
                value=json.loads(message['text'])
                if value.get('type')=='view' and isinstance(value.get('focal'),(int,float)) and 12<=value['focal']<=200:
                    if peer:await peer.send_json({'type':'view','focal':value['focal']})
            elif role=='phone' and message.get('text'):
                if len(message['text'])>2000:continue
                value=packet(json.loads(message['text']))
                if peer:await peer.send_json(value)
    except Exception:pass
    finally:
        if session and session['peers'].get(role) is ws:
            session['peers'].pop(role,None)
            peer=session['peers'].get('phone' if role=='desktop' else 'desktop')
            if peer:
                try:await peer.send_json({'type':'peer','online':False})
                except Exception:pass
        try:await ws.close()
        except Exception:pass


PAGE='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>导演工坊 · 手机取景</title>
<style>*{box-sizing:border-box}body{margin:0;background:#101726;color:#e7eefb;font:14px system-ui;touch-action:manipulation}header{padding:15px;display:flex;justify-content:space-between}#status{color:#adc9eb}img{display:block;width:100%;height:46vh;object-fit:contain;background:#06090f}main{padding:16px;display:grid;grid-template-columns:1fr 1fr;gap:18px}button{padding:13px;background:#29436c;color:white;border:1px solid #5475a3;border-radius:8px}label{display:block;margin:8px 0}input{width:100%}.pad{height:140px;border:1px solid #4c668c;border-radius:16px;display:flex;align-items:center;justify-content:center;touch-action:none;background:#192a43}.pad span{pointer-events:none}small{color:#afc1dc;display:block;line-height:1.7}.buttons{display:flex;gap:8px;padding:0 16px}.hint{padding:12px 16px}#focal{accent-color:#87b4ff}</style>
<header><strong>导演工坊 · 虚拟取景器</strong><span id="status">正在连接…</span></header><img id="view" alt="电脑机位画面"><main><div><div class="pad" id="move"><span>平移／前后</span></div><small>按住并拖动，松手停止</small></div><div><div class="pad" id="aim"><span>触屏转向</span></div><small>未开启陀螺仪时用此控件</small></div><div><label>升降<input id="lift" type="range" min="-1" max="1" step=".05" value="0"></label></div><div><label>焦距 <b id="mm">35</b> mm<input id="focal" type="range" min="12" max="200" value="35"></label></div></main><div class="buttons"><button id="gyro">开启陀螺仪</button><button id="reset">朝向归零</button><button id="capture">保存截图</button></div><small id="hint" class="hint">手机转动控制朝向；空间平移由触屏摇杆控制。</small>
<script>(()=>{const $=s=>document.getElementById(s),token=location.hash.slice(1),state={move_x:0,move_z:0,yaw:0,pitch:0,lift:0};let ws,url,gyro=false,disposed=false;
function connect(){if(disposed)return;ws=new WebSocket('wss://'+location.host+'/control');ws.binaryType='blob';ws.onopen=()=>{ws.send(JSON.stringify({token,role:'phone'}));$('status').textContent='等待电脑连接'};ws.onmessage=e=>{if(e.data instanceof Blob){if(url)URL.revokeObjectURL(url);url=URL.createObjectURL(e.data);$('view').src=url;return}const v=JSON.parse(e.data);if(v.type==='view'){$('focal').value=v.focal;$('mm').textContent=Math.round(v.focal)}if(v.type==='peer')$('status').textContent=v.online?'已连接电脑':'电脑已断开';if(v.type==='connected')$('status').textContent='已配对 · 等待画面'};ws.onclose=()=>{$('status').textContent='连接断开，可刷新重连'}}
function send(data){if(ws?.readyState===1)ws.send(JSON.stringify(data))}
function pad(id,keys){const el=$(id);el.addEventListener('pointerdown',e=>{el.setPointerCapture(e.pointerId);update(e)});el.addEventListener('pointermove',e=>{if(el.hasPointerCapture(e.pointerId))update(e)});function update(e){const r=el.getBoundingClientRect();state[keys[0]]=Math.max(-1,Math.min(1,(e.clientX-r.left-r.width/2)/(r.width/2)));state[keys[1]]=Math.max(-1,Math.min(1,(e.clientY-r.top-r.height/2)/(r.height/2)))}for(const event of ['pointerup','pointercancel','lostpointercapture'])el.addEventListener(event,()=>{state[keys[0]]=state[keys[1]]=0})}
pad('move',['move_x','move_z']);pad('aim',['yaw','pitch']);$('lift').oninput=e=>state.lift=+e.target.value;$('lift').onpointerup=()=>{state.lift=0;$('lift').value=0};$('focal').oninput=e=>{state.focal=+e.target.value;$('mm').textContent=state.focal};
function orient(e){if(e.alpha==null||e.beta==null||e.gamma==null)return;Object.assign(state,{alpha:e.alpha,beta:e.beta,gamma:e.gamma,screen:screen.orientation?.angle||window.orientation||0})}
$('gyro').onclick=async()=>{try{if(!window.isSecureContext||!window.DeviceOrientationEvent)throw Error('此手机未开放方向传感器，请用触屏转向');if(DeviceOrientationEvent.requestPermission&&await DeviceOrientationEvent.requestPermission()!=='granted')throw Error('未获得传感器权限，请用触屏转向');if(!gyro){window.addEventListener('deviceorientation',orient);gyro=true;$('gyro').textContent='关闭陀螺仪';$('hint').textContent='转动手机取景。若无方向数据，请确认手机已信任此局域网HTTPS证书。'}else{window.removeEventListener('deviceorientation',orient);gyro=false;delete state.alpha;delete state.beta;delete state.gamma;$('gyro').textContent='开启陀螺仪'}send({type:'calibrate'})}catch(e){$('hint').textContent=e.message}};
$('reset').onclick=()=>send({type:'calibrate'});$('capture').onclick=()=>send({type:'capture'});const interval=setInterval(()=>{if(!document.hidden)send({type:'control',...state})},66);document.addEventListener('visibilitychange',()=>{if(document.hidden){state.move_x=state.move_z=state.lift=state.yaw=state.pitch=0;send({type:'control',...state})}});window.addEventListener('pagehide',()=>{disposed=true;clearInterval(interval);ws?.close();if(url)URL.revokeObjectURL(url)});if(token)connect();else $('status').textContent='请从电脑的配对链接打开';})();</script></html>'''
