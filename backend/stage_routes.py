"""Authenticated main-app endpoints; the phone only controls the open viewport."""
import copy
from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse
from . import store, stage3d, stage_mobile

def install(app):
    base='/api/projects/{pid}/shots/{sid}/stage3d'

    @app.get(base)
    def read(pid:str,sid:str):return stage3d.read(store.get_project(pid),sid)

    @app.put(base)
    def save(pid:str,sid:str,body:dict):
        p=store.mutate(pid,lambda p:stage3d.save(p,sid,body))
        return {'project':p,**stage3d.read(p,sid)}

    @app.post(base+'/capture')
    def capture(pid:str,sid:str,body:dict):
        result=[]
        def apply(p):result.append(stage3d.capture(p,sid,body))
        try:p=store.mutate(pid,apply)
        except Exception:
            for m in result:store.media_path(m['media']).unlink(missing_ok=True)
            raise
        return {'project':p,'capture':result[0],**stage3d.read(p,sid)}

    @app.post(base+'/movie')
    async def movie(pid:str,sid:str,file:UploadFile=File(...),stage_hash:str=Form(...),source_hash:str=Form(...)):
        p=store.get_project(pid);body={'stage_hash':stage_hash,'source_hash':source_hash}
        stage3d.check(p,sid,stage_hash,source_hash)
        content=await file.read(50*1024*1024+1)
        if len(content)>50*1024*1024:raise ValueError('预演文件超过50MB')
        if not content.startswith(b'\x1a\x45\xdf\xa3'):raise ValueError('仅接受浏览器录制的WebM预演')
        source=store.DATA/(store.uid()+'.webm');source.write_bytes(content);m=None
        try:
            import asyncio
            m=await asyncio.to_thread(stage3d.movie,p,sid,body,source)
            def apply(current):
                stage3d.check(current,sid,stage_hash,source_hash)
                stage3d.shot(current,sid).setdefault('stage3d_captures',[]).append(copy.deepcopy(m))
                current.setdefault('media',[]).append(copy.deepcopy(m))
            saved=store.mutate(pid,apply)
            return {'project':saved,'capture':m,**stage3d.read(saved,sid)}
        except Exception:
            if m:store.media_path(m['media']).unlink(missing_ok=True)
            raise
        finally:source.unlink(missing_ok=True)

    @app.post(base+'/mobile')
    def mobile(pid:str,sid:str):
        stage3d.shot(store.get_project(pid),sid)
        return stage_mobile.create(pid,sid)

    @app.post(base+'/mobile/close')
    def close(pid:str,sid:str,body:dict):
        stage_mobile.close(pid,sid,str(body.get('token','')));return {'ok':True}

    @app.get('/api/stage3d/mobile/certificate')
    def certificate():
        cert,_=stage_mobile.certificate()
        return FileResponse(cert,filename='DirectorStudio-LAN.crt',media_type='application/x-x509-ca-cert')
