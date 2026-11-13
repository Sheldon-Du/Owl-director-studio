"""Project-scoped conversation storage; chatting never increments project revision."""
import json
import time
from . import store


def tables(c):
    c.execute('CREATE TABLE IF NOT EXISTS agent_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT, run_id TEXT, body TEXT)')
    c.execute('CREATE INDEX IF NOT EXISTS agent_message_project ON agent_messages(project_id,id)')
    c.execute('CREATE TABLE IF NOT EXISTS agent_memory (project_id TEXT PRIMARY KEY, body TEXT)')


def append(pid, run_id, role, content, **extra):
    body={'role':role,'content':content,'created':time.time(),**extra}
    with store.LOCK,store.connect() as c:
        tables(c)
        cursor=c.execute('INSERT INTO agent_messages(project_id,run_id,body) VALUES (?,?,?)',(pid,run_id,json.dumps(body,ensure_ascii=False)))
        body.update(id=cursor.lastrowid,run_id=run_id)
    return body


def messages(pid, limit=100):
    with store.connect() as c:
        tables(c)
        rows=c.execute('SELECT id,run_id,body FROM agent_messages WHERE project_id=? ORDER BY id DESC LIMIT ?',(pid,limit)).fetchall()
    return [{**json.loads(row[2]),'id':row[0],'run_id':row[1]} for row in reversed(rows)]


def memory(pid):
    with store.connect() as c:
        tables(c)
        row=c.execute('SELECT body FROM agent_memory WHERE project_id=?',(pid,)).fetchone()
    return json.loads(row[0]) if row else ''


def remember(pid, text):
    if not isinstance(text,str) or len(text)>5000:raise ValueError('项目记忆应为不超过5000字的文本')
    with store.LOCK,store.connect() as c:
        tables(c)
        c.execute('INSERT OR REPLACE INTO agent_memory VALUES (?,?)',(pid,json.dumps(text,ensure_ascii=False)))
