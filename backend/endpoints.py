"""Accept SDK base URLs without changing the native HTTP transport."""
from urllib.parse import urlsplit, urlunsplit


def chat_url(value):
    value=str(value or '').strip()
    if not value:
        return ''
    parsed=urlsplit(value)
    if parsed.scheme not in ('http','https') or not parsed.hostname:
        raise ValueError('文本 AI 地址必须为完整 HTTP 或 HTTPS 地址')
    path=parsed.path.rstrip('/')
    if not path:
        path='/v1/chat/completions'
    elif path.endswith('/v1'):
        path+='/chat/completions'
    elif path.endswith('/chat/completions'):
        # A trailing slash can redirect POST requests on some API gateways.
        pass
    else:
        path=parsed.path
    return urlunsplit((parsed.scheme,parsed.netloc,path,parsed.query,''))
