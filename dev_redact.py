"""Fail-closed second layer for Dev Desk text. Never log the input on failure.

Rules and shared vectors follow M-3 §3.5. Desktop-only known values are not
collected here. Structural IDs are preserved by deep(); prose is never exempt.
"""
import math
import re
from collections import Counter

KEEP = frozenset('id ids at key task_id rev kind state status sender agent owner handle since card_id sha256 created_at screen_rev'.split())
_SENSITIVE = r'(?:secret|token|passw(?:or)?d|pwd|api[_-]?key|access[_-]?key|private[_-]?key|client[_-]?secret|auth|credential|cookie|session[_-]?key|dsn|database_url|connection[_-]?string|webhook[_-]?url|service[_-]?role)'
# Look ahead for a sensitive component, then consume the name once. Two
# overlapping greedy runs around the component are quadratic on authauth...
_NAME = r'(?=[\w.-]*' + _SENSITIVE + r')[\w.-]+'
_TOKENS = re.compile(
    r'\b(?:sk-(?:ant-|proj-)?[\w-]{20,}|(?:sk|rk)_(?:live|test)_[\w-]+|whsec_[\w-]+'
    r'|gh[pousr]_[\w]+|github_pat_[\w]+|glpat-[\w-]+|xox[abprs]-[\w-]+'
    r'|(?:AKIA|ASIA)[A-Z0-9]{16}|AIza[\w-]{35}|ya29\.[\w.-]+|npm_[\w]+'
    r'|SG\.[\w-]+\.[\w-]+|re_[A-Za-z0-9]{16,}|xai-[\w-]+|SK[0-9a-fA-F]{32}'
    r'|eyJ[\w-]+\.eyJ[\w-]+\.[\w-]+)\b')
_QUERY = r'(?:token|key|api_key|apikey|access_token|refresh_token|secret|sig|signature|X-Amz-Signature|X-Amz-Credential|code|password)'


def text(value: str) -> str:
    """Pure redaction. Exceptions deliberately propagate: callers must not store raw text."""
    if not isinstance(value, str):
        raise TypeError('redaction requires text')
    # Protect replacements so later rules cannot turn markers into partial secrets.
    saved = []

    def marker(kind):
        saved.append('[redacted:' + kind + ']' if kind else '[redacted]')
        return '\x00' + str(len(saved) - 1) + '\x00'

    def save(s):
        saved.append(s)
        return '\x00' + str(len(saved) - 1) + '\x00'

    # Reject embedded sentinels rather than accidentally restoring attacker input.
    value = value.replace('\x00', '')
    value = re.sub(r'\[redacted(?::[a-z-]+)?\]', lambda m: save(m[0]), value)
    value = re.sub(r'-----BEGIN ([A-Z ]*PRIVATE KEY)-----[\s\S]*?-----END \1-----',
                   lambda m: marker('private-key'), value)
    value = re.sub(r'(?im)^(\s*(?:Authorization|Proxy-Authorization|X-Api-Key|Api-Key|Cookie|Set-Cookie)\s*:\s*)[^\r\n]+',
                   lambda m: m[1] + marker('header'), value)
    value = re.sub(r'(?i)\b(Bearer|Basic)\s+[A-Za-z0-9+/=_~.-]+',
                   lambda m: m[1] + ' ' + marker('token'), value)
    value = _TOKENS.sub(lambda m: marker('token'), value)
    value = re.sub(r'(\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@:]+:)[^\s/@]*@',
                   lambda m: m[1] + marker('') + '@', value)
    value = re.sub(r'(?i)([?&]' + _QUERY + r'=)[^&#\s]+', lambda m: m[1] + marker('query'), value)
    assignment = re.compile(r'(?i)(?<![\w.-])(["\x27]?' + _NAME + r'["\x27]?\s*[:=]\s*)("(?:\\.|[^"\\\r\n])*"|\x27(?:\\.|[^\x27\\\r\n])*\x27|[^\s,;}&?#]+)')

    def assigned(m):
        raw = m[2]
        if re.fullmatch(r'[\"\x27]?\x00\d+\x00[\"\x27]?', raw):
            return m[1] + raw
        quote = raw[0] if raw[:1] in ('"', "'") else ''
        return m[1] + quote + marker('assignment') + quote

    value = assignment.sub(assigned, value)
    value = re.sub(r'(?i)(--' + _NAME + r'\s+)("[^"\r\n]*"|\x27[^\x27\r\n]*\x27|[^\s]+)', assigned, value)
    # A run can include sensitive assignments that already became sentinels.
    value = re.sub(r'(?m)(?:^[ \t]*(?:export )?[A-Za-z_][\w]*=[^\r\n]*(?:\r?\n|$)){3,}',
                   lambda m: re.sub(r'(?m)(^[ \t]*(?:export )?[A-Za-z_][\w]*=)[^\r\n]*',
                                    lambda a: a[1] + marker('env'), m[0]), value)

    def entropy(m):
        s = m[0]
        before, after = value[max(0, m.start()-1):m.start()], value[m.end():m.end()+1]
        # Whole path/URL tokens remain readable; explicit URL secrets were removed above.
        token_start = max(value.rfind(' ', 0, m.start()), value.rfind('\n', 0, m.start())) + 1
        prefix = value[token_start:m.start()]
        if before in ('/', '\\', '.') or after in ('/', '\\', '.') or '://' in prefix or re.search(r'[A-Za-z]:\\', prefix):
            return s
        if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', s):
            return s
        if re.fullmatch(r'[a-fA-F0-9]+', s):
            return s
        classes = sum(bool(re.search(p, s)) for p in (r'[a-z]', r'[A-Z]', r'[0-9]', r'[+/=_-]'))
        h = -sum((n / len(s)) * math.log2(n / len(s)) for n in Counter(s).values())
        return marker('entropy') if classes >= 3 and h >= 4 else s

    value = re.sub(r'[A-Za-z0-9+/=_-]{32,}', entropy, value)
    return re.sub(r'\x00(\d+)\x00', lambda m: saved[int(m[1])], value)


def deep(value, *, keep=KEEP):
    if isinstance(value, str):
        return text(value)
    if isinstance(value, list):
        return [deep(v, keep=keep) for v in value]
    if isinstance(value, dict):
        return {k: v if k in keep else ('[redacted:assignment]' if re.search(_SENSITIVE, k, re.I) and isinstance(v, str) else deep(v, keep=keep)) for k, v in value.items()}
    return value
