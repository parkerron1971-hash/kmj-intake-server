"""In-memory PostgREST/RPC rig. Real SQL is also exercised by dev_relay_db.mjs."""
import asyncio
import copy
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
import dev_relay as store
import dev_fleet
import dev_cards
import dev_alerts
import dev_bridge

D1 = '11111111-1111-4111-8111-111111111111'
D2 = '22222222-2222-4222-8222-222222222222'
S1 = 's-aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
S2 = 's-bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'


def run(coro):
    return asyncio.run(coro)


class Client:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class Fake:
    def __init__(self):
        self.tables = defaultdict(list)
        self.stamp = datetime(2026, 10, 15, 16, 0, tzinfo=timezone.utc)
        self.tables['dev_bridge_devices'] = [
            {'id': D1, 'name': 'one', 'revoked': False, 'token_hash': dev_bridge._hash_token('one'), 'last_seen_at': store.z(self.stamp)},
            {'id': D2, 'name': 'two', 'revoked': False, 'token_hash': dev_bridge._hash_token('two'), 'last_seen_at': store.z(self.stamp)}]
        self.pushes, self.emails, self.uploads, self.removed, self.calls = [], [], {}, [], []
        self.budgets = {}
        self.push_count = 1
        self.dedupe = {}

    def tick(self, seconds):
        self.stamp += timedelta(seconds=seconds)

    def match(self, row, params):
        for k, v in params.items():
            if k in ('select', 'order', 'limit', 'offset'):
                continue
            if k in ('or', 'and'):
                parts = v[1:-1].split(',')
                matches = [self.match(row, {p.split('.', 1)[0]: p.split('.', 1)[1]}) for p in parts]
                if not (any(matches) if k == 'or' else all(matches)):
                    return False
                continue
            have = row.get(k)
            actual = str(have).lower() if isinstance(have, bool) else str(have)
            if v.startswith('eq.') and actual != v[3:]:
                return False
            if v.startswith('neq.') and actual == v[4:]:
                return False
            if v == 'is.null' and have is not None:
                return False
            if v == 'not.is.null' and have is None:
                return False
            if v.startswith('in.') and str(have) not in v[4:-1].split(','):
                return False
            for op, fn in [('gt.', lambda a,b:a>b), ('gte.', lambda a,b:a>=b),
                           ('lt.', lambda a,b:a<b), ('lte.', lambda a,b:a<=b)]:
                if v.startswith(op):
                    a, b = store.parse(have), store.parse(v[len(op):])
                    if not a or not fn(a, b):
                        return False
        return True

    async def get(self, c, table, params):
        self.calls.append(('GET', table, copy.deepcopy(params)))
        rows = [copy.deepcopy(r) for r in self.tables[table] if self.match(r, params)]
        order = params.get('order', '')
        for term in reversed(order.split(',')):
            if term:
                key = term.split('.')[0]
                rows.sort(key=lambda r: str(r.get(key) or ''), reverse='.desc' in term)
        offset = int(params.get('offset', 0))
        rows = rows[offset:offset+int(params.get('limit', 1000))]
        select = params.get('select', '*')
        return rows if select == '*' else [{k:r.get(k) for k in select.split(',')} for r in rows]

    async def patch(self, c, table, params, body):
        out = []
        for row in self.tables[table]:
            if self.match(row, params):
                row.update(copy.deepcopy(body))
                out.append(copy.deepcopy(row))
        return out

    async def insert(self, c, table, body):
        self.tables[table].append(copy.deepcopy(body))
        return [copy.deepcopy(body)]

    async def delete(self, c, table, params):
        rows = [r for r in self.tables[table] if self.match(r, params)]
        self.tables[table] = [r for r in self.tables[table] if not self.match(r, params)]
        if table == 'dev_fleet_sessions':
            keys = {(r['device_id'],r['session_key']) for r in rows}
            self.tables['dev_fleet_screens'] = [r for r in self.tables['dev_fleet_screens']
                if (r['device_id'],r['session_key']) not in keys]
        return copy.deepcopy(rows)

    async def rpc(self, c, name, body):
        if name == 'dev_alert_unread':
            return sum(not r.get('read_at') for r in self.tables['dev_alerts'])
        if name == 'dev_alert_claim':
            row = copy.deepcopy(body['p_row'])
            base = (row['source'], row['device_id'], row['watch_id'])
            scope = base if row['source'] == 'sites' else base + (row['key'],)
            previous = self.dedupe.get(scope)
            if previous and previous['key'] == row['key'] and (row['source'] in ('ci','sites') or
                    self.stamp-store.parse(previous['created_at']) < timedelta(minutes=30)):
                previous['count'] += 1
                return {'deduped': True}
            self.tables['dev_alerts'].append(row)
            self.dedupe[scope] = row
            return {'row': copy.deepcopy(row)}
        device_id = body['p_device']
        if not any(d['id'] == device_id and not d['revoked'] for d in self.tables['dev_bridge_devices']):
            return {'error': 401}
        if name == 'dev_fleet_sync':
            sessions = self.tables['dev_fleet_sessions']
            keys = {r['session_key'] for r in body['p_sessions']}
            if body['p_full']:
                for r in sessions:
                    if r['device_id'] == device_id and r['session_key'] not in keys and not r.get('ended_at'):
                        r.update(state='ended', ended_at=store.z(self.stamp))
            for item in body['p_sessions']:
                existing = next((r for r in sessions if r['device_id'] == device_id and r['session_key'] == item['session_key']), None)
                row = {**item, 'device_id': device_id, 'updated_at': store.z(self.stamp),
                       'ended_at': store.z(self.stamp) if item['state'] == 'ended' else None}
                if existing:
                    existing.update(row)
                else:
                    sessions.append(row)
            return {'ok': True}
        if name == 'dev_fleet_screen':
            match = {'device_id': f'eq.{device_id}', 'session_key': f"eq.{body['p_key']}"}
            if not await self.get(c, 'dev_fleet_sessions', match):
                return {'error': 404}
            screens = self.tables['dev_fleet_screens']
            old = next((r for r in screens if self.match(r, match)), None)
            if old and old['rev'] >= body['p_rev']:
                return {'ok': True, 'stale': True}
            if old and (self.stamp-store.parse(old['received_at'])).total_seconds() < 1.5:
                return {'error': 429}
            row = {'device_id':device_id, 'session_key':body['p_key'], 'rev':body['p_rev'],
                   'text':body['p_text'], 'state':body['p_state'], 'at':body['p_at'], 'received_at':store.z(self.stamp)}
            if old:
                old.update(row)
            else:
                screens.append(row)
            return {'ok': True}
        raise AssertionError(name)

    async def push(self, c, title, body, **kw):
        self.pushes.append((title, body, kw))
        return self.push_count

    async def email(self, row):
        self.emails.append(copy.deepcopy(row))
        return True

    async def budget(self, bucket, key, maximum=None):
        import rate_limit
        default, window = rate_limit._LIMITS[bucket]
        count, start = self.budgets.get((bucket,key), (0, self.stamp))
        if (self.stamp-start).total_seconds() >= window:
            count, start = 0, self.stamp
        if count >= (maximum or default):
            return False
        self.budgets[bucket,key] = count+1, start
        return True

    async def upload(self, c, path, data, mime):
        self.uploads[path] = (data, mime)

    async def remove(self, c, paths):
        self.removed.extend(paths)
        for p in paths:
            self.uploads.pop(p, None)


@pytest.fixture
def relay(monkeypatch):
    fake = Fake()
    monkeypatch.setattr(store, 'now', lambda: fake.stamp)
    for name in ('get','patch','insert','delete','rpc'):
        monkeypatch.setattr(store, name, getattr(fake,name))
    monkeypatch.setattr(dev_bridge, '_sb_get', fake.get)
    monkeypatch.setattr(dev_bridge, '_sb_patch', fake.patch)
    monkeypatch.setattr(dev_fleet.rate_limit, 'allow_strict', lambda *a, **kw: True)
    monkeypatch.setattr(dev_alerts, 'budget', fake.budget)
    monkeypatch.setattr(dev_alerts, '_push_owner', fake.push)
    monkeypatch.setattr(dev_alerts, '_email', fake.email)
    monkeypatch.setattr(dev_cards, '_upload', fake.upload)
    monkeypatch.setattr(dev_cards, '_remove_objects', fake.remove)
    monkeypatch.setattr(dev_fleet.httpx, 'AsyncClient', Client)
    monkeypatch.setenv('DEV_ALERTS', 'on')
    return fake
