"""Chief's web searches as steps in the chat's work log, so the owner can look in.

Kevin (2026-09-25): "if i send chief to search for something, a something
should appear in the chat that allows me to look in on what chief is doing."
A search runs inside the model call (Anthropic's server-side web_search), so
there is no browser to watch; what there is to see is the query while it runs
and the pages it found when it lands. Each search becomes one `step` on the
existing stream (same id for start and end), carrying `search.query` and,
when done, `search.results` (title, url, host).

Result titles and links are third-party text shown to the owner only; nothing
here is added to what the model reads. Only http(s) links are passed on.
"""
import json
import time
import uuid
from urllib.parse import urlsplit

MAX_RESULTS = 8


def _query(text):
    return ' '.join(str(text or '').split())[:160]


def _results(content):
    out = []
    for item in content or []:
        if not isinstance(item, dict) or item.get('type') != 'web_search_result':
            continue
        url = str(item.get('url') or '')
        try:
            parts = urlsplit(url)
        except ValueError:
            continue
        if parts.scheme not in ('http', 'https') or not parts.hostname or len(url) > 2048:
            continue
        host = parts.hostname.removeprefix('www.')
        out.append({'title': ' '.join(str(item.get('title') or host).split())[:140], 'url': url, 'host': host})
        if len(out) >= MAX_RESULTS:
            break
    return out


class SearchSteps:
    """Fed the model stream's content blocks for one attempt; emits steps."""

    def __init__(self, emit):
        self.emit = emit
        self.open = {}      # server tool_use id -> step
        self.indexes = {}   # stream block index -> server tool_use id

    def block_start(self, index, block):
        kind = block.get('type')
        if kind == 'server_tool_use' and block.get('name') == 'web_search':
            use_id = str(block.get('id') or uuid.uuid4().hex)
            given = block.get('input') if isinstance(block.get('input'), dict) else {}
            step = {'id': 'ws' + uuid.uuid4().hex[:10], 'query': _query(given.get('query')),
                    't0': time.monotonic(), 'json': []}
            self.open[use_id] = step
            self.indexes[index] = use_id
            self._send(step, 'running')
        elif kind == 'web_search_tool_result':
            step = self.open.pop(str(block.get('tool_use_id') or ''), None)
            if step is not None:
                content = block.get('content')
                if isinstance(content, list):
                    self._send(step, 'done', _results(content))
                else:
                    self._send(step, 'failed')

    def delta(self, index, delta):
        use_id = self.indexes.get(index)
        if use_id in self.open and delta.get('type') == 'input_json_delta':
            self.open[use_id]['json'].append(delta.get('partial_json') or '')

    def block_stop(self, index):
        use_id = self.indexes.pop(index, None)
        step = self.open.get(use_id)
        if step is None:
            return
        try:
            query = _query((json.loads(''.join(step['json']) or '{}') or {}).get('query'))
        except (ValueError, AttributeError):
            query = ''
        if query and query != step['query']:
            step['query'] = query
            self._send(step, 'running')

    def close(self):
        """An attempt ended: a search with no result never reads as running."""
        for step in list(self.open.values()):
            self._send(step, 'failed')
        self.open.clear()
        self.indexes.clear()

    def _send(self, step, state, results=None):
        query = step['query']
        if state == 'running':
            label = f'Searching the web for "{query}"' if query else 'Searching the web'
        elif state == 'done':
            pages = f' · {len(results)} page{"" if len(results) == 1 else "s"}' if results else ''
            label = (f'Searched "{query}"' if query else 'Searched the web') + pages
        else:
            label = 'The web search did not finish'
        body = {'id': step['id'], 'action': 'web_search', 'label': label, 'state': state,
                'search': {'query': query, **({'results': results} if results is not None else {})}}
        if state != 'running':
            body['ms'] = int((time.monotonic() - step['t0']) * 1000)
        try:
            self.emit(body)
        except Exception:
            pass  # The work log is a view; it must never break the turn.
