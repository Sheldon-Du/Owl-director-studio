"""Activate the local Comfy cache policy only when existing jobs are finished."""
import json,logging,subprocess,threading,time
from pathlib import Path
import httpx
from . import comfy,store

CONFIG=Path(r'D:\2video\codex\owl-comfy-serial-idle-20261015\restart-config.json')
STATE=CONFIG.with_name('activation.json')

def activate_when_idle():
    from . import jobs,workflow_files
    while True:
        time.sleep(3)
        try:
            with httpx.Client(trust_env=False,timeout=5) as c:
                r=c.get(comfy.url()+'/owl/model-retention')
                if r.status_code==200:
                    workflow_files.write_json(STATE,{'status':'active',**r.json()});return
            # Never restart with an in-flight pipeline or unfilled results.
            active=[t for t in store.task_list() if t.get('kind') in jobs.COMFY_KINDS and t.get('status') in ('running','cancelling')]
            if active:time.sleep(3);continue
            with comfy.SUBMISSION_LOCK:
                queued=comfy.request('GET','/queue')
                if queued.get('queue_running') or queued.get('queue_pending'):continue
                active=[t for t in store.task_list() if t.get('kind') in jobs.COMFY_KINDS and t.get('status') in ('running','cancelling') and t.get('prompt_id')]
                if active:continue
                workflow_files.write_json(STATE,{'status':'activating'})
                script=CONFIG.with_name('restart-comfy.ps1')
                result=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',str(script)],capture_output=True,text=True,timeout=30)
                if result.returncode:raise RuntimeError(result.stderr or result.stdout)
                # Hold new submissions until Comfy has loaded all nodes.
                for _ in range(240):
                    try:
                        with httpx.Client(trust_env=False,timeout=3) as c:
                            ready=c.get(comfy.url()+'/owl/model-retention')
                            if ready.status_code==200:
                                workflow_files.write_json(STATE,{'status':'active',**ready.json()});return
                    except httpx.HTTPError:pass
                    time.sleep(1)
                raise RuntimeError('ComfyUI restart did not finish in time')
        except Exception as error:
            workflow_files.write_json(STATE,{'status':'waiting','error':str(error)})
            logging.getLogger(__name__).warning('Comfy policy activation waiting: %s',error)
            time.sleep(5)

def start():
    threading.Thread(target=activate_when_idle,name='Comfy-policy-activation',daemon=True).start()
