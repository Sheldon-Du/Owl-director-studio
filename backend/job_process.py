"""A cancellable process invokes the original director and text AI code."""
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def watch_parent(parent_pid):
    if os.name=='nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        kernel.WaitForSingleObject.restype=wintypes.DWORD
        handle=kernel.OpenProcess(0x00100000,False,parent_pid)
        if not handle or kernel.WaitForSingleObject(handle,0xFFFFFFFF)==0:
            os._exit(2)
    else:
        import time
        while os.getppid()==parent_pid:
            time.sleep(.25)
        os._exit(2)


def main():
    request_path=Path(sys.argv[1])
    output_path=Path(sys.argv[2])
    progress_path=Path(sys.argv[3])
    threading.Thread(target=watch_parent,args=(int(sys.argv[4]),),daemon=True).start()
    from backend import jobs
    task=json.loads(request_path.read_text(encoding='utf-8'))
    event_dir=progress_path.parent/'events';event_dir.mkdir(exist_ok=True)
    event_number=0;metric_lock=threading.Lock()
    def on_asset(event):
        nonlocal event_number
        event_number+=1
        path=event_dir/f'{event_number:06d}.json'
        tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(event,ensure_ascii=False),encoding='utf-8');tmp.replace(path)
    def metrics(record):
        # Only timings and router counters; no prompts, source quotes or keys.
        with metric_lock,(progress_path.parent/'ai-timings.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps(record,ensure_ascii=False)+'\n')
    def progress(message):
        temp=progress_path.with_suffix('.tmp')
        temp.write_text(json.dumps({'message':message},ensure_ascii=False),encoding='utf-8')
        # Windows can temporarily deny replacement while the parent reads the
        # previous update. Progress reporting must not abort native generation.
        for attempt in range(20):
            try:
                temp.replace(progress_path)
                return
            except PermissionError:
                time.sleep(.01)
    try:
        from backend import ai_context
        os.environ['DIRECTOR_AI_PROJECT_ID']=task['project_id']
        with ai_context.session(task['project_id'],metrics):
            result={'ok':True,'result':jobs.text_result(task,progress,on_asset=on_asset,metrics=metrics)}
    except Exception as error:
        result={'ok':False,'error':str(error)}
    output_path.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')


if __name__=='__main__':
    main()
