"""Offline Unlimited-OCR. Heavy imports occur only in the cancellable job process."""
import copy
import hashlib
import json
import os
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from . import store

RUNTIME = Path(r'D:\2video\Owl-ocr-runtime')
REVISION = '8249d20b2822a7d8a4c22c8d8c9069b5ac36bda3'
DEFAULTS = {'gpu': 0, 'dpi': 200}


def settings():
    file = store.DATA / 'local-ocr-settings.json'
    cfg = {**DEFAULTS, **(json.loads(file.read_text(encoding='utf-8')) if file.exists() else {})}
    if type(cfg['gpu']) is not int or cfg['gpu'] not in (0, 1):
        raise ValueError('本地 OCR 显卡请选择 0 或 1')
    if cfg['dpi'] not in (150, 200, 300):
        raise ValueError('识别清晰度请选择 150、200 或 300 DPI')
    return cfg


def status():
    model = RUNTIME / 'model'
    version = RUNTIME / 'model-version.json'
    ready = False
    if version.exists():
        try:
            data = json.loads(version.read_text(encoding='utf-8'))
            ready = data.get('revision') == REVISION and all((model / n).is_file() for n in data['weights'])
        except (ValueError, KeyError, TypeError):
            pass
    ready = ready and (RUNTIME / 'packages' / 'pymupdf').is_dir() and (RUNTIME / 'packages' / 'transformers').is_dir()
    return {'ready': ready, 'provider': '百度 Unlimited-OCR · 本地', 'settings': settings(),
            'message': '本地模型已就绪，首次识别需要加载显卡' if ready else '本地识别模型或专用依赖尚未准备完成',
            'offline': True, 'revision': REVISION}


def source(p, sid):
    s = next((s for s in p.get('medical_director', {}).get('sources', []) if s['id'] == sid), None)
    if not s:
        raise KeyError('原文资料不存在')
    if not s['media'].lower().endswith('.pdf'):
        raise ValueError('本地 OCR 入口用于 PDF 资料')
    return s


def basis(s):
    from .medical_director import digest
    return digest([s['id'], s['hash'], s['blocks']])


def runtime_imports():
    path = str(RUNTIME / 'packages')
    if path not in sys.path:
        sys.path.insert(0, path)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['TRANSFORMERS_OFFLINE'] = '1'
    os.environ['HF_DATASETS_OFFLINE'] = '1'
    os.environ['HF_MODULES_CACHE'] = str(RUNTIME / 'modules-cache')


@contextmanager
def exclusive():
    lock = RUNTIME / 'inference.lock'
    with lock.open('a+b') as stream:
        stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('本地 OCR 正在识别另一份资料，请稍后继续')
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def load_model(cfg, report):
    runtime_imports()
    os.environ['CUDA_VISIBLE_DEVICES'] = str(cfg['gpu'])
    import torch
    from transformers import AutoModel, AutoTokenizer
    if not torch.cuda.is_available():
        raise ValueError('本地 OCR 未检测到可用 CUDA 显卡')
    free, _ = torch.cuda.mem_get_info(0)
    if free < 10 * 1024 ** 3:
        raise ValueError(f'显卡 {cfg["gpu"]} 空闲显存不足 10GB，请先结束该显卡上的其他生成任务')
    report(f'正在将 Unlimited-OCR 加载到 {cfg["gpu"]} 号显卡，文档留在本机')
    folder = str(RUNTIME / 'model')
    tokenizer = AutoTokenizer.from_pretrained(folder, trust_remote_code=True, local_files_only=True)
    model = AutoModel.from_pretrained(folder, trust_remote_code=True, local_files_only=True,
                                     use_safetensors=True, dtype=torch.bfloat16,
                                     attn_implementation='eager').eval().cuda()
    original_generate = model.generate
    def tracked_generate(*args, **kwargs):
        # The upstream generation_config sets max_new_tokens=32768, which
        # otherwise overrides infer(max_length=16384). Bound output explicitly.
        kwargs.pop('max_length', None)
        kwargs['max_new_tokens'] = 16384
        if 'input_ids' in kwargs and 'attention_mask' not in kwargs:
            kwargs['attention_mask'] = torch.ones_like(kwargs['input_ids'])
        kwargs.setdefault('pad_token_id', tokenizer.eos_token_id)
        result = original_generate(*args, **kwargs)
        if result[0, -1].item() != tokenizer.eos_token_id:
            raise ValueError('该页识别达到输出上限，未将截断文字保存为完整结果；请拆分过密页面后重试')
        return result
    model.generate = tracked_generate
    return model, tokenizer


def recognize(model, tokenizer, image, folder):
    # eval_mode returns text before upstream visualization helpers that use
    # eval() on generated coordinates. Never execute generated content.
    value = model.infer(tokenizer, prompt='<image>document parsing.', image_file=str(image),
                        output_path=str(folder), base_size=1024, image_size=640,
                        crop_mode=True, max_length=16384, no_repeat_ngram_size=35,
                        ngram_window=128, save_results=False, eval_mode=True)
    if not isinstance(value, str):
        raise ValueError('本地 OCR 未返回可读文字')
    return value


def clean(raw):
    if not isinstance(raw, str) or len(raw) > 400000:
        raise ValueError('单页 OCR 结果无效或过长')
    regions = []
    lines, skip_image = [], False
    for line in raw.splitlines():
        line = line.strip()
        old = re.match(r'<\|ref\|>(.*?)<\|/ref\|><\|det\|>(.*?)<\|/det\|>(.*)', line)
        new = re.match(r'<\|det\|>([\w-]+)(.*?)<\|/det\|>(.*)', line)
        if old or new:
            match = old or new
            kind, bounds, content = match.groups()
            regions.append({'kind': kind, 'bounds': bounds.strip()})
            skip_image = kind.strip() == 'image'
            if not skip_image:
                lines.extend(['', content])
        elif not skip_image:
            lines.append(line)
    body = '\n'.join(lines).replace('<｜end▁of▁sentence｜>', '').strip()
    return body, regions


def generate(task, report):
    from . import medical_director as m
    if not status()['ready']:
        raise ValueError(status()['message'])
    s = source(task['snapshot'], task['target'])
    cfg = task['options']['ocr_settings']
    runtime_imports()
    import pymupdf
    original = store.media_path(s['media'])
    if hashlib.sha256(original.read_bytes()).hexdigest() != s['hash']:
        raise ValueError('PDF 原文件已变化，停止识别以保护引用依据')
    with exclusive(), pymupdf.open(str(original)) as doc:
        if doc.needs_pass and not doc.authenticate(''):
            raise ValueError('PDF 需要打开密码，请先用已有密码另存为可读取的 PDF')
        if not 1 <= len(doc) <= 500:
            raise ValueError('本地 OCR 支持 1–500 页 PDF')
        blocks, pages, warnings = [], [], []
        model, tokenizer = None, None
        root = store.DATA / 'ocr-cache' / m.digest([s['hash'], REVISION, cfg['dpi'], 'gundam-16384-v2'])
        root.mkdir(parents=True, exist_ok=True)
        labels = s.get('page_labels', [])
        total_chars = 0
        for i, page in enumerate(doc):
            report(f'本地 OCR 第 {i+1}/{len(doc)} 页，已完成页面会保留供续跑')
            cache = root / f'page-{i+1:04}.json'
            if cache.exists():
                result = json.loads(cache.read_text(encoding='utf-8'))
                raw = result['raw']
            else:
                if model is None:
                    model, tokenizer = load_model(cfg, report)
                image = root / f'page-{i+1:04}.png'
                scale = min(cfg['dpi']/72, 3600/max(page.rect.width, page.rect.height))
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                pix.save(str(image))
                try:
                    raw = recognize(model, tokenizer, image, root)
                finally:
                    image.unlink(missing_ok=True)
                # Validate before committing a reusable page checkpoint.
                clean(raw)
                tmp = cache.with_suffix('.' + store.uid() + '.tmp')
                tmp.write_text(json.dumps({'raw': raw}, ensure_ascii=False), encoding='utf-8'); tmp.replace(cache)
            text, regions = clean(raw)
            total_chars += len(text)
            if total_chars > 350000:
                raise ValueError('识别文字超过单份资料 35 万字，请按章节拆分；已完成页面缓存保留')
            rows = m.split_text(text, i+1)
            for row in rows:
                row['printed_page'] = labels[i] if i < len(labels) else None
            blocks.extend(rows)
            pages.append({'page': i+1, 'raw': raw, 'regions': regions})
            if not text:
                warnings.append(f'第 {i+1} 页未识别到正文，请核对是否为空白、图片或识别失败')
        if not blocks:
            raise ValueError('未识别到可用正文，请检查扫描清晰度或更换文件')
        warnings.append('本地 OCR 已完成；请重点核对数字、单位、否定词、表格、脚注及阅读顺序，再采用资料分析')
        return {'id': store.uid(), 'source_hash': s['hash'], 'base_hash': basis(s), 'blocks': blocks,
                'pages': pages, 'page_count': len(doc), 'warnings': warnings,
                'provider': 'baidu/Unlimited-OCR', 'model_revision': REVISION,
                'settings': cfg, 'created': time.time()}


def apply_result(p, sid, result):
    s = source(p, sid)
    s['ocr_candidate'] = result


def adopt(p, sid):
    s = source(p, sid)
    result = s.get('ocr_candidate')
    if not result or result['source_hash'] != s['hash'] or result['base_hash'] != basis(s):
        raise ValueError('OCR 结果的资料依据已变化，请重新识别；旧结果仍保留')
    from . import medical_director as m
    other = sum(len(b['text']) for v in m.state(p)['sources'] if v['id'] != sid for b in v['blocks'])
    if other + sum(len(b['text']) for b in result['blocks']) > 500000:
        raise ValueError('项目资料总量超过 50 万字，请缩小本期范围')
    prior = {k: copy.deepcopy(s.get(k)) for k in ('blocks', 'warnings', 'quality_reviewed', 'review_note', 'ocr_pages', 'extraction')}
    prior['created'] = time.time()
    s.setdefault('extraction_history', []).append(prior)
    s.update(blocks=result['blocks'], warnings=result['warnings'], quality_reviewed=False, review_note='',
             ocr_pages=result['pages'], extraction='unlimited-ocr-local', page_count=result['page_count'])
    s.pop('ocr_candidate')
    m.init(p)['settings'].update(selected_modules=[], module_depths={}, selected_hook='')


def execute(task):
    from . import jobs
    result = jobs.run_text(task)
    saved = jobs.mutate_task(task, lambda p: apply_result(p, task['target'], result))
    task['project_revision'] = saved['revision']
    task['completion_message'] = f'本地 OCR 已完成 {result["page_count"]} 页，请预览并采用；原文件保留'


def install(app):
    from . import pdf_preview
    pdf_preview.install(app)
    @app.get('/api/local-ocr')
    def get_status():
        return status()

    @app.post('/api/local-ocr/settings')
    def configure(body: dict):
        if set(body) - set(DEFAULTS):
            raise ValueError('本地识别设置无效')
        cfg = {**settings(), **body}
        if type(cfg['gpu']) is not int or cfg['gpu'] not in (0, 1) or cfg['dpi'] not in (150, 200, 300):
            raise ValueError('显卡或清晰度设置无效')
        with store.LOCK:
            path = store.DATA / 'local-ocr-settings.json'
            tmp = path.with_suffix('.tmp'); tmp.write_text(json.dumps(cfg), encoding='utf-8'); tmp.replace(path)
        return status()

    @app.post('/api/projects/{pid}/medical-director/sources/{sid}/ocr')
    def run(pid: str, sid: str, body: dict):
        from . import jobs, medical_director as m
        with jobs.TASK_LOCK, store.LOCK:
            p = store.get_project(pid); m.check_revision(p, body.get('revision'))
            source(p, sid)
            if not status()['ready']:
                raise ValueError(status()['message'])
            t = jobs.enqueue('medical_ocr', p, sid, {'ocr_settings': settings()})
            return {'task_id': t['id']}

    @app.post('/api/projects/{pid}/medical-director/sources/{sid}/ocr/adopt')
    def apply(pid: str, sid: str, body: dict):
        from . import medical_director as m
        with store.LOCK:
            p = store.get_project(pid); m.check_revision(p, body.get('revision'))
            adopt(p, sid)
            return {'project': store.save_project(p, p['revision'])}
