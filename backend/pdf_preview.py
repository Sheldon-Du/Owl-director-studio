"""Authenticated, cached original-page images; rendering never loads OCR/GPU."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading
from . import store

SLOTS = threading.BoundedSemaphore(2)

def install(app):
    from fastapi.responses import FileResponse
    from . import local_ocr

    @app.get('/api/projects/{pid}/medical-director/sources/{sid}/pages/{page}/preview')
    def preview(pid: str, sid: str, page: int):
        p = store.get_project(pid)
        source = local_ocr.source(p, sid)
        if not 1 <= page <= (source.get('page_count') or 500):
            raise ValueError('原页页码超出资料范围')
        folder = store.DATA / 'pdf-previews' / hashlib.sha256(source['hash'].encode()).hexdigest()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f'page-{page:04}-150dpi.png'
        with SLOTS:
            if not target.exists():
                temp = folder / (store.uid() + '.png')
                try:
                    entry = f"import sys,runpy;sys.path.insert(0,{str(store.ROOT)!r});runpy.run_module('backend.pdf_preview',run_name='__main__')"
                    subprocess.run([sys.executable, '-X', 'utf8', '-c', entry,
                                    str(store.media_path(source['media'])), str(page), str(temp)],
                                   cwd=store.ROOT, env=os.environ.copy(), check=True, timeout=30,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                    temp.replace(target)
                except (subprocess.SubprocessError, OSError):
                    raise ValueError('原页图片暂时无法显示，请使用“查看原文件”核对')
                finally:
                    temp.unlink(missing_ok=True)
        return FileResponse(target, media_type='image/png', headers={'Cache-Control': 'private, max-age=3600'})

def render():
    from .local_ocr import RUNTIME
    sys.path.insert(0, str(RUNTIME / 'packages'))
    import pymupdf
    with pymupdf.open(sys.argv[1]) as doc:
        if doc.needs_pass and not doc.authenticate(''):
            raise ValueError('PDF needs an opening password')
        page = int(sys.argv[2])
        if not 1 <= page <= len(doc):
            raise ValueError('Invalid PDF page')
        doc[page-1].get_pixmap(matrix=pymupdf.Matrix(150/72,150/72),alpha=False).save(sys.argv[3])

if __name__ == '__main__': render()
