"""Fail-closed second layer for Dev Desk text.

Shared desktop vectors cover rules 2-9; known values stay on the desktop.
Owner instructions bypass this layer only at authenticated instruction endpoints.
"""
import asyncio
import math
import re
from collections import Counter

KEEP = frozenset('id ids at key task_id rev kind state status sender agent owner handle since card_id sha256 created_at screen_rev'.split())
_SENSITIVE = re.compile(
    r'secret|token|passw(?:or)?d|pwd|api[_-]?key|access[_-]?key|private[_-]?key|'
    r'client[_-]?secret|(?<![a-z0-9])auth(?![a-z0-9])|credential|cookie|'
    r'session[_-]?key|dsn|database_url|connection[_-]?string|webhook[_-]?url|service[_-]?role', re.I)
_TRIVIAL = re.compile(r'(?:true|false|null|undefined|none|yes|no|on|off|\$\{?[A-Za-z_]\w*\}?|%[A-Za-z_]\w*%|\[redacted(?::[a-z-]+)?\])', re.I)
_NAME = r'(?=[\w.-]*(?:' + _SENSITIVE.pattern + r'))[A-Za-z_][\w.-]*'
_TOKENS = re.compile(
    r'(?<![A-Za-z0-9_-])(?:sk-(?:ant-|proj-)[\w-]{8,}|sk-[\w-]{20,}|'
    r'(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{8,}|whsec_[A-Za-z0-9+/=]{8,}|'
    r'gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[\w]{20,}|glpat-[\w-]{20,}|'
    r'xox[abprs]-[A-Za-z0-9-]{10,}|(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])|'
    r'AIza[\w-]{35}|ya29\.[\w-]{20,}|npm_[A-Za-z0-9]{30,}|'
    r'SG\.[\w-]{16,}\.[\w-]{16,}|re_(?=[\w]*\d)(?=[\w]*[A-Z])[\w]{16,}|'
    r'xai-[A-Za-z0-9]{20,}|SK[0-9a-fA-F]{32}(?![0-9a-fA-F])|'
    r'eyJ[\w-]{8,}\.eyJ[\w-]{8,}\.[\w-]*)')
_QUERY = r'(?:token|key|api_key|apikey|access_token|refresh_token|secret|sig|signature|X-Amz-Signature|X-Amz-Credential|code|password)'
_QUOTED = r'"(?:\\.|[^"\\\r\n])*"|\x27(?:\\.|[^\x27\\\r\n])*\x27'
_ASSIGN = re.compile(r'(?i)(?<![\w.-])((?:\$env:)?["\x27]?(' + _NAME + r')["\x27]?[ \t]*[:=][ \t]*)(' + _QUOTED + r'|[^\s"\x27\x60,;}&?#|]+)')
_FLAG = re.compile(r'(?i)(?<![\w-])(--(' + _NAME + r')(?:=|[ \t]+))(' + _QUOTED + r'|[^\s"\x27\x60-][^\s"\x27\x60]*)')
_ENV_LINE = re.compile(r'^([ \t⎿│|>]*(?:export[ \t]+|set[ \t]+)?[A-Za-z_][\w().-]*=)(.*)$')
_ENV_COMMENT = re.compile(r'^[ \t⎿│|>]*#')
_PLACEHOLDER = re.compile(r'\x00\d+\x00')
THREAD_THRESHOLD = 4096


def text(value: str) -> str:
    """Pure redaction. Exceptions propagate: callers must not store raw text."""
    if not isinstance(value, str):
        raise TypeError('redaction requires text')
    saved = []

    def save(s):
        saved.append(s)
        return '\x00' + str(len(saved) - 1) + '\x00'

    def marker(kind):
        return save('[redacted:' + kind + ']' if kind else '[redacted]')

    value = value.replace('\x00', '')
    value = re.sub(r'\[redacted(?::[a-z-]+)?\]', lambda m: save(m[0]), value)
    value = re.sub(r'-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----|[A-Za-z0-9+/=\s]*)',
                   lambda m: marker('private-key'), value)
    value = re.sub(r'(?i)\b((?:Proxy-Authorization|Authorization|X-Api-Key|Api-Key|Set-Cookie|Cookie)[ \t]*:[ \t]*)([^\r\n"\x27\x60]+)',
                   lambda m: m[0] if _PLACEHOLDER.fullmatch(m[2].strip()) else m[1] + marker('header'), value)
    value = re.sub(r'\b(Bearer|Basic)([ \t]+)([A-Za-z0-9+/=_~.-]{8,})',
                   lambda m: m[1] + m[2] + marker('token') if re.search(r'[0-9._~+/=-]', m[3]) or len(m[3]) >= 20 else m[0], value)
    value = _TOKENS.sub(lambda m: marker('token'), value)
    value = re.sub(r'(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@:"\x27\x60]+:)([^\s/@?"\x27\x60#]+)@',
                   lambda m: m[0] if _PLACEHOLDER.fullmatch(m[2]) else m[1] + marker('') + '@', value)
    value = re.sub(r'(?i)([?&]' + _QUERY + r'=)([^&#\s"\x27\x60<>]+)',
                   lambda m: m[0] if _PLACEHOLDER.fullmatch(m[2]) else m[1] + marker(''), value)

    def assigned(m):
        raw = m[3]
        quote = raw[0] if raw[:1] in ('"', "'") else ''
        inner = raw[1:-1] if quote else raw
        if not _SENSITIVE.search(m[2]) or not inner or _TRIVIAL.fullmatch(inner.strip()) or _PLACEHOLDER.fullmatch(inner):
            return m[0]
        return m[1] + quote + marker('secret') + quote

    # Consume each name once, then inspect it. The left boundary prevents
    # retrying at every dash; a flag is never another flag's value.
    value = _FLAG.sub(assigned, value)
    value = _ASSIGN.sub(assigned, value)
    lines = value.split('\n')
    i = 0
    while i < len(lines):
        if not _ENV_LINE.match(lines[i]):
            i += 1
            continue
        j, count = i, 0
        while j < len(lines) and (_ENV_LINE.match(lines[j]) or _ENV_COMMENT.match(lines[j])):
            count += bool(_ENV_LINE.match(lines[j]))
            j += 1
        if count >= 3:
            for k in range(i, j):
                m = _ENV_LINE.match(lines[k])
                if not m:
                    continue
                raw = m[2].removesuffix('\r')
                v = raw.strip()
                if not v or _PLACEHOLDER.fullmatch(v) or _TRIVIAL.fullmatch(v):
                    continue
                lines[k] = m[1] + raw[:len(raw) - len(raw.lstrip())] + marker('env') + ('\r' if m[2].endswith('\r') else '')
        i = j
    value = '\n'.join(lines)

    def entropy(m):
        s = m[0]
        before, after = value[max(0, m.start()-1):m.start()], value[m.end():m.end()+1]
        if before in ('/', '\\', '.', '@', '~') or s.startswith('/') or after == '\\' or (after == '.' and value[m.end()+1:m.end()+2].isalnum()):
            return s
        if re.fullmatch(r'(?:[A-Za-z]{1,6}-)?[0-9a-fA-F-]+', s):
            return s
        classes = sum(bool(re.search(p, s)) for p in (r'[a-z]', r'[A-Z]', r'[0-9]', r'[+/=_-]'))
        h = -sum((n / len(s)) * math.log2(n / len(s)) for n in Counter(s).values())
        return marker('entropy') if classes >= 3 and h >= 4 else s

    value = re.sub(r'[A-Za-z0-9+/_-]{32,}={0,2}', entropy, value)
    return re.sub(r'\x00(\d+)\x00', lambda m: saved[int(m[1])], value)


def deep(value, *, keep=KEEP):
    if isinstance(value, str):
        return text(value)
    if isinstance(value, list):
        return [deep(v, keep=keep) for v in value]
    if isinstance(value, dict):
        return {k: v if k in keep else ('[redacted:secret]' if _SENSITIVE.search(k) and isinstance(v, str) and v and not _TRIVIAL.fullmatch(v.strip()) else deep(v, keep=keep)) for k, v in value.items()}
    return value


async def text_async(value: str) -> str:
    """Keep large screens and notes off the event loop, before truncation."""
    if len(value) >= THREAD_THRESHOLD:
        return await asyncio.to_thread(text, value)
    return text(value)
