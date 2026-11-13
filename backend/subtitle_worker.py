"""Runs only inside pyVideoTrans's bundled Python 3.10 runtime."""
import os,sys
from subtitle_packaged_imports import enable
enable(os.path.join(os.path.dirname(os.path.dirname(sys.argv[3])),'sp.exe'))
import json
from pathlib import Path

def main():
    source,destination,model=sys.argv[1:]
    from faster_whisper import WhisperModel
    # Offline only: use the user's existing pyVideoTrans model files, no download.
    engine=WhisperModel(model,device='cpu',compute_type='int8',local_files_only=True,cpu_threads=min(8,os.cpu_count() or 4))
    segments,info=engine.transcribe(source,language=None,beam_size=5,vad_filter=True,word_timestamps=True)
    rows=[]
    for segment in segments:
        words=segment.words or []
        start=words[0].start if words else segment.start
        end=words[-1].end if words else segment.end
        text=segment.text.strip()
        if text and end>start:rows.append({'start':round(start,3),'end':round(end,3),'text':text})
    Path(destination).write_text(json.dumps({'captions':rows,'language':info.language},ensure_ascii=False),encoding='utf-8')

if __name__=='__main__':main()
