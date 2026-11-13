import copy
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('DIRECTOR_STUDIO_DATA', str(ROOT / 'data')))
DATA.mkdir(parents=True, exist_ok=True)
LOCK = threading.RLock()


def uid():
    return uuid.uuid4().hex


@contextmanager
def connect():
    con = sqlite3.connect(DATA / 'studio.sqlite', timeout=30)
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, revision INTEGER, updated REAL, body TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS versions (id TEXT PRIMARY KEY, project_id TEXT, revision INTEGER, created REAL, body TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, body TEXT)')
    con.commit()
    try:
        with con:
            yield con
    finally:
        con.close()


def list_projects(include_deleted=False):
    with connect() as c:
        projects=[json.loads(r[0]) for r in c.execute('SELECT body FROM projects ORDER BY updated DESC')]
    return projects if include_deleted else [p for p in projects if not p.get('deleted')]


def get_project(project_id,include_deleted=False):
    with connect() as c:
        row = c.execute('SELECT body FROM projects WHERE id=?', (project_id,)).fetchone()
    if not row:
        raise KeyError('项目不存在')
    body=json.loads(row[0])
    if body.get('deleted') and not include_deleted:
        raise KeyError('项目已删除，可在回收站恢复')
    return body


def versions(project_id):
    with connect() as c:
        rows=c.execute('SELECT id,revision,created,body FROM versions WHERE project_id=? ORDER BY revision DESC LIMIT 100',(project_id,)).fetchall()
    return [{'id':r[0],'revision':r[1],'created':r[2],'name':json.loads(r[3])['name']} for r in rows]


def restore(project_id,version_id,expected):
    with LOCK,connect() as c:
        row=c.execute('SELECT body FROM versions WHERE project_id=? AND id=?',(project_id,version_id)).fetchone()
        if not row:raise KeyError('版本不存在')
        body=json.loads(row[0])
    return save_project(body,expected)


class Conflict(Exception):
    pass


def save_project(body, expected=None):
    body = copy.deepcopy(body)
    with LOCK, connect() as c:
        row = c.execute('SELECT revision,body FROM projects WHERE id=?', (body['id'],)).fetchone()
        if row and expected != row[0]:
            raise Conflict('其他设备已修改，请加载最新版本后合并')
        if row:
            c.execute('INSERT INTO versions VALUES (?,?,?,?,?)', (uid(), body['id'], row[0], time.time(), row[1]))
        if body.get('workflow_schema_version',1)>=2:
            from . import workbench
            workbench.register_changes(json.loads(row[1]) if row else None,body)
        body['revision'] = (row[0] if row else 0) + 1
        body['updated'] = time.time()
        c.execute('INSERT OR REPLACE INTO projects VALUES (?,?,?,?)', (body['id'], body['revision'], body['updated'], json.dumps(body, ensure_ascii=False)))
    return body


def mutate(project_id, operation):
    with LOCK:
        body = get_project(project_id)
        revision = body['revision']
        operation(body)
        return save_project(body, revision)


def task_save(task):
    with LOCK, connect() as c:
        c.execute('INSERT OR REPLACE INTO tasks VALUES (?,?)', (task['id'], json.dumps(task, ensure_ascii=False)))


def task_list():
    with connect() as c:
        return [json.loads(r[0]) for r in c.execute('SELECT body FROM tasks')]


def task_get(task_id):
    with connect() as c:
        row=c.execute('SELECT body FROM tasks WHERE id=?',(task_id,)).fetchone()
    if not row:
        raise KeyError('任务不存在')
    return json.loads(row[0])


def settings():
    path = DATA / 'settings.json'
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    return {'comfy_url':'http://127.0.0.1:8188','ai_url':'','ai_key':'','ai_model':'','password_hash':''}


def settings_save(values):
    with LOCK:
        tmp = DATA / 'settings.tmp'
        tmp.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(DATA / 'settings.json')


def media_path(name):
    root = (DATA / 'media').resolve()
    root.mkdir(exist_ok=True)
    path = (root / name).resolve()
    if not path.is_relative_to(root):
        raise ValueError('非法媒体路径')
    return path
