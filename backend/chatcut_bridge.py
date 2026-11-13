"""Project-bound ChatCut Desktop MCP client. No credentials are copied or logged."""
import copy
import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
from . import store

LOCK = threading.RLock()
READS = {'read_project', 'preview_timeline', 'inspect_item', 'inspect_asset', 'browse_assets', 'manage_timelines', 'read_captions'}
EDITS = {'edit_item', 'edit_captions', 'edit_track'}


class Client:
    def __enter__(self):
        launcher = Path(os.environ.get('APPDATA', '')) / 'ChatCut' / 'chatcut-mcp.cmd'
        if not launcher.is_file():
            raise ValueError('未找到 ChatCut Desktop 本地 MCP 启动器，请先在 ChatCut 配置本地 Agent 连接')
        self.messages = queue.Queue()
        self.seq = 0
        self.process = subprocess.Popen([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', str(launcher)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        threading.Thread(target=self._read, daemon=True).start()
        try:
            self.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                'clientInfo': {'name': 'owl-chatcut', 'version': '1.0.0'}})
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
            self.tools = {t['name']: t for t in self.request('tools/list', {}).get('tools', [])}
            self.active = self.call('get_active_project')
            return self
        except Exception:
            self.close()
            raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try: self.messages.put(json.loads(line))
                except (ValueError, UnicodeError): continue
        finally: self.messages.put(None)

    def send(self, message):
        self.process.stdin.write((json.dumps(message, ensure_ascii=False) + '\n').encode('utf-8'))
        self.process.stdin.flush()

    def request(self, method, params, timeout=120):
        self.seq += 1
        identity = self.seq
        self.send({'jsonrpc': '2.0', 'id': identity, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while True:
            try: message = self.messages.get(timeout=max(.01, deadline-time.monotonic()))
            except queue.Empty: raise ValueError('ChatCut 响应超时；操作结果未知，请检查状态后再决定是否重试')
            if message is None: raise ValueError('ChatCut MCP 连接已关闭')
            if 'method' in message:
                if 'id' in message:
                    self.send({'jsonrpc': '2.0', 'id': message['id'], 'error': {'code': -32601, 'message': 'Interactive MCP requests are unsupported by Owl'}})
                continue
            if message.get('id') != identity: continue
            if message.get('error'): raise ValueError('ChatCut MCP: ' + str(message['error'].get('message', '请求失败')))
            return message.get('result', {})

    def call(self, name, arguments=None):
        if name not in self.tools: raise ValueError('ChatCut 当前版本未提供工具：' + name)
        result = self.request('tools/call', {'name': name, 'arguments': arguments or {}})
        blocks = [b.get('text', '') for b in result.get('content', []) if b.get('type') == 'text']
        text = '\n'.join(blocks)
        if result.get('isError'): raise ValueError('ChatCut: ' + text[:1600])
        if isinstance(result.get('structuredContent'), dict): return result['structuredContent']
        try: return json.loads(text)
        except ValueError: return {'message': text}

    def close(self):
        if self.process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            else:
                self.process.terminate()
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process.stdout.close()
        self.process.stdin.close()

    def __exit__(self, *args): self.close()


def finite(value, label, minimum=0):
    number = float(value)
    if not math.isfinite(number) or number < minimum: raise ValueError(label + '无效')
    return number


def plan(project, fps=30):
    clips = project.get('timeline', [])
    if not clips: raise ValueError('请先组装或编辑 Owl 时间线')
    rows = []
    cursor = 0
    for clip in clips:
        kind = clip.get('kind')
        if kind not in ('video', 'image', 'audio'): raise ValueError('不支持的素材类型')
        path = store.media_path(clip['media'])
        if not path.is_file(): raise ValueError('素材不存在：' + clip['media'])
        duration = finite(clip.get('duration'), '片段时长', .001)
        start = finite(clip.get('start', 0), '音频开始') if kind == 'audio' else cursor
        first = round(start*fps)
        end = round((start+duration)*fps)
        if end <= first: raise ValueError('片段时长不足一帧')
        rows.append({'owl_id': clip['id'], 'file': str(path), 'type': kind,
            'startFrame': first, 'durationFrames': end-first,
            'sourceIn': round(finite(clip.get('in', 0), '入点')*1000000),
            'volume': finite(clip.get('volume', 1), '音量')})
        if rows[-1]['volume'] > 1: raise ValueError('当前 ChatCut 适配器仅支持 0–1 音量，请先降低超出范围的音量')
        if kind != 'audio': cursor += duration
    return rows


def save_binding(pid, binding):
    with store.LOCK:
        project = store.get_project(pid)
        project['chatcut'] = copy.deepcopy(binding)
        return store.save_project(project, project['revision'])


def bound(client, project):
    binding = project.get('chatcut', {})
    if not binding.get('project_id'): raise ValueError('请先发送当前时间线到 ChatCut')
    if binding.get('owl_project_id') != project['id']: raise ValueError('此绑定来自其他 Owl 项目，请重新发送当前时间线')
    client.call('target_project', {'projectId': binding['project_id']})
    current = client.call('read_project')
    timeline = binding.get('timeline_id')
    if timeline and current.get('activeTimeline', {}).get('id') != timeline:
        client.call('manage_timelines', {'action': 'switch', 'timelineId': timeline})
        current = client.call('read_project')
    return binding, current


def status():
    with LOCK, Client() as client:
        return {'connected': True, 'active': client.active,
            'tools': sorted((READS | EDITS) & client.tools.keys())}


def schema(name):
    if name not in READS | EDITS: raise ValueError('未开放的 ChatCut 工具')
    with LOCK, Client() as client:
        tool = client.tools.get(name)
        if not tool: raise ValueError('当前版本未提供该工具')
        return {'name': name, 'description': tool.get('description'), 'inputSchema': tool.get('inputSchema')}


def send_timeline(pid, expected):
    with LOCK:
        project = store.get_project(pid)
        if project['revision'] != expected: raise store.Conflict('项目已更新，请保存后再发送')
        if project.get('chatcut', {}).get('project_id') and project['chatcut'].get('owl_project_id') == pid:
            raise ValueError('本项目已绑定 ChatCut；为避免重复添加，请使用 Agent 继续剪辑现有工程')
        if project.get('captions'): raise ValueError('本版时间线发送尚不转换 Owl 字幕，请先在 ChatCut 添加字幕；未发送任何素材')
        rows = plan(project)
        ratio = re.search(r'(\d+)\s*[:：]\s*(\d+)', project.get('parameters', {}).get('画幅比例', '16:9'))
        aspect = (int(ratio[1]), int(ratio[2])) if ratio else (16, 9)
        if min(aspect) <= 0: raise ValueError('画幅比例无效')
        width, height = (max(2, round(1920*n/max(aspect)/2)*2) for n in aspect)
        with Client() as client:
            created = client.call('create_project', {'name': 'Owl · ' + project['name'], 'fps': 30,
                'compositionWidth': width, 'compositionHeight': height})
            cid = created.get('projectId') or created.get('project', {}).get('projectId')
            if not cid: raise ValueError('ChatCut 未返回 projectId；请检查新建工程，不要重复发送')
            binding = {'project_id': cid, 'owl_project_id': pid, 'timeline_id': created.get('timelineId'), 'owl_revision': expected, 'fps': 30, 'stage': 'created', 'assets': {}, 'created': time.time()}
            save_binding(pid, binding)
            try:
                current = client.call('read_project')
                binding['timeline_id'] = current['activeTimeline']['id']
                save_binding(pid, binding)
                adds = []
                for row in rows:
                    path = row['file']
                    if path not in binding['assets']:
                        imported = client.call('push_asset', {'filePath': path})
                        asset = find_asset(imported)
                        if not asset: raise ValueError('ChatCut 导入结果缺少素材 ID，请检查工程后继续')
                        binding['assets'][path] = asset
                        save_binding(pid, binding)
                    adds.append({k: row[k] for k in ('type','startFrame','durationFrames','sourceIn','volume')} | {'assetId': binding['assets'][path], 'fit': 'contain'} if row['type'] != 'audio' else {k: row[k] for k in ('type','startFrame','durationFrames','sourceIn','volume')} | {'assetId': binding['assets'][path]})
                client.call('edit_item', {'adds': adds, 'validateOnly': True})
                binding['stage'] = 'applying'
                save_binding(pid, binding)
                result = client.call('edit_item', {'adds': adds})
                binding['stage'] = 'ready'
                binding['items'] = result
                saved = save_binding(pid, binding)
                return {'revision': saved['revision'], 'chatcut': binding, 'clips': len(adds)}
            except Exception:
                binding['stage'] = 'needs_review'
                save_binding(pid, binding)
                raise


def find_asset(value):
    if isinstance(value, dict):
        for key in ('assetId', 'asset_id'):
            if isinstance(value.get(key), str): return value[key]
        if value.get('id') and (value.get('type') or value.get('kind')): return value['id']
        for key in ('assets', 'imported', 'asset', 'results', 'registered'):
            found = find_asset(value.get(key))
            if found: return found
    if isinstance(value, list):
        for item in value:
            found = find_asset(item)
            if found: return found
    return None


def command(pid, name, arguments):
    if name not in READS | EDITS: raise ValueError('未开放的 ChatCut 工具')
    if name == 'manage_timelines' and arguments.get('action') != 'list': raise ValueError('只允许列出时间线')
    with LOCK, Client() as client:
        bound(client, store.get_project(pid))
        result = client.call(name, arguments)
        return {'result': result}


def export(pid):
    with LOCK, Client() as client:
        project = store.get_project(pid)
        binding, current = bound(client, project)
        binding = copy.deepcopy(binding)
        if binding.get('export_task'):
            if not binding.get('collected_media'): raise ValueError('已有导出任务，请先查询导出状态并收回成片，避免重复导出')
            binding.setdefault('export_history', []).append({'task': binding.pop('export_task'), 'media': binding.pop('collected_media')})
        result = client.call('local_export', {'format': 'video', 'resolution': '1080p', 'timelineId': binding['timeline_id']})
        binding['export_task'] = result
        saved = save_binding(pid, binding)
        return {'revision': saved['revision'], 'export': result, 'note': '尚未完成；请用 chatcut_progress 查询结果'}


def progress(pid):
    with LOCK, Client() as client:
        project = store.get_project(pid)
        binding, current = bound(client, project)
        result = client.call('track_progress', {'target': 'export', 'action': 'status',
            **({'exportTaskIds': binding['export_task']['taskId']} if binding.get('export_task', {}).get('taskId') else {})})
        return {'result': result, 'binding': binding}


def collect(pid):
    """Only import the completed export recorded for this Owl project."""
    with LOCK:
        snapshot = progress(pid)
        binding = snapshot['binding']
        if binding.get('collected_media'):
            return {'media': binding['collected_media'], 'already_collected': True}
        task = binding.get('export_task', {})
        task_id = task.get('taskId')
        path = task.get('outputPath')
        if not task_id or not path: raise ValueError('导出记录缺少 taskId/outputPath，请检查 ChatCut 返回结果')
        def completed(value):
            if isinstance(value, dict):
                if (value.get('taskId') == task_id or value.get('id') == task_id) and value.get('status') in ('completed', 'done', 'success'):
                    return True
                return any(completed(v) for v in value.values() if isinstance(v, (dict, list)))
            if isinstance(value, list): return any(completed(v) for v in value)
            return False
        if not completed(snapshot['result']): raise ValueError('尚未确认此导出任务完成，不会导入未完成的文件')
        source = Path(path)
        if not source.is_absolute() or source.suffix.lower() != '.mp4' or not source.is_file(): raise ValueError('导出文件不存在或不是 MP4')
        filename = store.uid()+'.mp4'
        destination = store.media_path(filename)
        shutil.copyfile(source, destination)
        import imageio_ffmpeg
        reader = imageio_ffmpeg.read_frames(str(destination))
        try: metadata = next(reader)
        finally: reader.close()
        with store.LOCK:
            project = store.get_project(pid)
            media = {'id': store.uid(), 'media': filename, 'name': project['name']+' · ChatCut 成片',
                'kind': 'video', 'duration': metadata['duration'], 'created': time.time(),
                'source': 'chatcut', 'chatcut_task_id': task_id}
            project.setdefault('media', []).append(media)
            project['chatcut']['collected_media'] = media
            saved = store.save_project(project, project['revision'])
        return {'revision': saved['revision'], 'media': media}


def install(app):
    @app.get('/api/chatcut/status')
    def connection(): return status()

    @app.post('/api/projects/{pid}/chatcut/send')
    def send(pid: str, body: dict): return send_timeline(pid, body.get('revision'))

    @app.post('/api/projects/{pid}/chatcut/export')
    def render(pid: str): return export(pid)

    @app.get('/api/projects/{pid}/chatcut/progress')
    def poll(pid: str): return progress(pid)

    @app.post('/api/projects/{pid}/chatcut/collect')
    def receive(pid: str): return collect(pid)
