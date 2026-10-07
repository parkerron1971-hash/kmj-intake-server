"""Tracked links on a business's own site, plus results (marketing suite B6).

business_marketing_links (the short link, the tagged destination, the words
that go out), its wiring into the desk API (business_marketing), the /go/
route on a business's own host (public_site) and the results
(business_marketing_outcomes). No network: PostgREST, the marketing_follow
RPC and the site renderers are in-memory fakes. The RPC's own rules (a click
counts only for a post that went out) are proven against Postgres by
__tests__/business_marketing_db.mjs; the fake here mirrors them.
"""
from __future__ import annotations

import copy
import pathlib
import sys
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

import business_marketing as bm
import business_marketing_links as links
import business_marketing_outcomes as outcomes
import business_marketing_store as store
import platform_marketing
import sb_clients
from __tests__ import test_business_marketing_api as api
from __tests__.test_business_marketing_api import (  # noqa: F401  (s is the desk API fixture)
    BIZ, FB, MEMBER, NOW, OTHER, OWNER, STRANGER, call, s, slot)

SITE = 'https://fadestreet.com'
SUB = 'https://fade-street.mysolutionist.app'
X = 'c0000000-0000-4000-8000-000000000009'
SENT = ('submitted', 'published', 'partly_published')


# ── a PostgREST that also reads JSON paths, numbers and dates ─────────

TIMEY = {'ts', 'created_at', 'day', 'run_at'}


def value_of(row, column):
    if '->>' in column:
        head, key = column.split('->>', 1)
        inner = row.get(head) or {}
        got = inner.get(key) if isinstance(inner, dict) else None
        return None if got is None else str(got)
    return row.get(column)


def _pair(value, arg, column):
    if column in TIMEY:
        return api._when(value), api._when(arg)
    return float(value), float(arg)


def project(row, columns):
    out = {}
    for col in columns.split(','):
        alias, _, source = col.rpartition(':')
        out[alias or source.split('->>')[-1]] = value_of(row, source)
    return out


def filt(rows, path):
    out, limit, columns = list(rows), None, None
    for key, expr in api.pairs(path):
        if key == 'select':
            columns = None if expr == '*' else expr
            continue
        if key == 'order':
            column, _, direction = expr.partition('.')
            out.sort(key=lambda r: str(r.get(column) or ''), reverse=direction.startswith('desc'))
            continue
        if key == 'limit':
            limit = int(expr)
            continue
        op, _, arg = expr.partition('.')
        if op == 'eq':
            out = [r for r in out if api._norm(value_of(r, key)) == arg]
        elif op == 'in':
            wanted = arg[1:-1].split(',')
            out = [r for r in out if api._norm(value_of(r, key)) in wanted]
        elif op in ('gte', 'gt'):
            def keep(r):
                v = value_of(r, key)
                if v is None:
                    return False
                a, b = _pair(v, arg, key)
                return a >= b if op == 'gte' else a > b
            out = [r for r in out if keep(r)]
        else:
            raise AssertionError(f'unexpected filter {key}={expr}')
    out = out[:limit] if limit else out
    return [project(r, columns) for r in out] if columns else out


class Store(api.FakeStore):
    """The desk's tables, plus marketing_link_clicks and marketing_follow (as the migration has it)."""

    def __init__(self):
        super().__init__()
        self.clicks, self.follows = [], []

    async def request(self, method, path, body=None):
        table = path.split('?', 1)[0]
        if table not in ('/rpc/marketing_follow', '/marketing_link_clicks'):
            return await super().request(method, path, body)
        self.paths.append((method, path))
        assert '+' not in (path.split('?', 1)[1] if '?' in path else '')
        if any(f in path for f in self.fail):
            raise store.StoreUnavailable('Marketing storage is unavailable. Please retry.')
        if table == '/marketing_link_clicks':
            return copy.deepcopy(filt(self.clicks, path))
        self.follows.append((body['p_code'], body['p_count_click']))
        post = next((p for p in self.posts.values() if p.get('link_code') == body['p_code']), None)
        if post is None:
            return []
        if body['p_count_click'] and post['status'] in SENT:
            day = NOW.date().isoformat()
            hit = next((c for c in self.clicks if c['post_id'] == post['id'] and c['day'] == day), None)
            if hit:
                hit['clicks'] += 1
            else:
                self.clicks.append({'post_id': post['id'], 'business_id': post['business_id'], 'day': day,
                                    'clicks': 1})
        return [{'business_id': post['business_id'], 'tracked_url': post.get('tracked_url')}]

    def counted(self, post_id):
        return sum(c['clicks'] for c in self.clicks if c['post_id'] == post_id)


class Service(api.FakeService):
    """The desk's service reads, with a published site, services, visits and contacts."""

    def __init__(self):
        super().__init__()
        self.sites[0]['status'] = 'published'
        self.offerings, self.events, self.contacts = [], [], []

    def get(self, path):
        mine = {'/business_sites': self.sites, '/offerings': self.offerings,
                '/site_events': self.events, '/contacts': self.contacts}
        table = path.split('?', 1)[0]
        if table not in mine:
            return super().get(path)
        self.reads.append(path)
        if any(f in path for f in self.fail):
            return None
        return copy.deepcopy(filt(mine[table], path))

    def bookable(self, *, offering=True):
        self.businesses[BIZ]['settings']['booking_page'] = {'published': True}
        self.modules = [{'business_id': BIZ, 'archetype': 'booking_calendar', 'is_active': True, 'id': 'm1'}]
        if offering:
            self.offerings = [{'id': 'o1', 'business_id': BIZ, 'category': 'service', 'is_active': True,
                               'duration_min': 30}]


@pytest.fixture
def t(s, monkeypatch):
    """The desk API fixture with the fakes above."""
    db, svc = Store(), Service()
    monkeypatch.setattr(store, 'request', db.request)
    monkeypatch.setattr(sb_clients, 'sb_get_as_service', svc.get)
    s.db, s.svc = db, svc
    return s


def site_of(t, biz=BIZ):
    return links.site_from_row(next(r for r in t.svc.sites if r['business_id'] == biz))


def put(t, *, biz=BIZ, status='published', landing=f'{SITE}/', run_at=None, caption='Fresh fades all week.',
        targets=(FB,)):
    """A post as the desk saves it (with its link when it has a landing), straight into the fake table."""
    pid = str(uuid4())
    by_id = {c['id']: c for c in t.svc.connections}
    when = run_at or NOW - timedelta(days=2)
    row = bm.new_post(biz, pid, caption=caption, media={}, targets=[bm._target(by_id[x]) for x in targets],
                      run_at=when, expires_at=when + bm.WINDOW, landing=landing,
                      site=site_of(t, biz) if landing else None)
    row.update(status=status, design_status='none', approved_hash=None, approved_by=None, approved_at=None,
               approved_via=None, error=None, external_urls=[], run_id=None, play_id=None, opening=None,
               created_at=NOW.isoformat(), updated_at=NOW.isoformat())
    t.db.posts[pid] = row
    return copy.deepcopy(row)


def tags(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


# ── the code, the origin, the destination, the words ─────────────────

def test_codes_are_deterministic_unique_per_post_and_not_the_platform_code():
    a, b = uuid4(), uuid4()
    assert store.link_code(a) == store.link_code(str(a)) == store.link_code(str(a).upper())
    assert store.link_code(a) != store.link_code(b)
    assert store.GO_CODE.match(store.link_code(a))
    assert store.link_code(a) != platform_marketing.link_code(a)
    codes = {store.link_code(uuid4()) for _ in range(2000)}
    assert len(codes) == 2000


@pytest.mark.parametrize('cfg,expected_origin,hosts', [
    ({'custom_domain': 'fadestreet.com', 'custom_domain_status': 'verified'}, SITE,
     {'fade-street.mysolutionist.app', 'fadestreet.com', 'www.fadestreet.com'}),
    ({'custom_domain': 'https://WWW.FadeStreet.com/', 'custom_domain_status': 'Verified'}, SITE,
     {'fade-street.mysolutionist.app', 'fadestreet.com', 'www.fadestreet.com'}),
    ({'custom_domain': 'fadestreet.com', 'custom_domain_status': 'pending'}, SUB, {'fade-street.mysolutionist.app'}),
    ({}, SUB, {'fade-street.mysolutionist.app'}),
], ids=['verified', 'stored loosely', 'pending', 'no domain'])
def test_the_origin_is_the_verified_domain_else_the_subdomain(cfg, expected_origin, hosts):
    whole = links.site_from_row({'business_id': BIZ, 'slug': 'Fade-Street', 'status': 'published', 'site_config': cfg})
    narrow = links.site_from_row({'business_id': BIZ, 'slug': 'fade-street', 'status': 'published',
                                  'custom_domain': cfg.get('custom_domain'),
                                  'custom_domain_status': cfg.get('custom_domain_status')})
    assert whole == narrow
    assert links.origin(whole) == expected_origin and set(links.own_hosts(whole)) == hosts
    assert links.short_link(whole, 'abcdefgh') == f'{expected_origin}/go/abcdefgh'
    assert links.site_from_row({'business_id': BIZ, 'slug': None}) is None and links.origin(None) is None


def test_the_tracked_url_keeps_the_page_and_names_the_post():
    site = links.site_from_row({'business_id': BIZ, 'slug': 'fade-street',
                                'site_config': {'custom_domain': 'fadestreet.com', 'custom_domain_status': 'verified'}})
    pid = str(uuid4())
    url = links.tracked_url(f'{SITE}/book?service=fade&utm_source=old#times', pid, site)
    parts = urlsplit(url)
    assert parts.scheme == 'https' and parts.hostname == 'fadestreet.com' and parts.path == '/book'
    assert parts.fragment == 'times'
    assert tags(url) == {'service': 'fade', 'utm_source': 'social', 'utm_medium': 'organic_social',
                         'utm_campaign': 'marketing_desk', 'utm_content': pid}
    assert urlsplit(links.tracked_url(SITE, pid, site)).path == '/'


@pytest.mark.parametrize('landing', [
    'https://evil.example/', 'http://fadestreet.com/', 'https://fadestreet.com.evil.example/',
    'https://user@fadestreet.com/', 'https://fadestreet.com:8443/', 'https://elsewhere.mysolutionist.app/',
    'https://mysolutionist.app/', 'javascript:alert(1)', '//fadestreet.com/', ''])
def test_a_tracked_url_is_only_ever_on_the_business_own_hosts(landing):
    site = links.site_from_row({'business_id': BIZ, 'slug': 'fade-street',
                                'site_config': {'custom_domain': 'fadestreet.com', 'custom_domain_status': 'verified'}})
    with pytest.raises(ValueError):
        links.tracked_url(landing, uuid4(), site)


def test_the_words_swap_a_mention_of_the_page_or_add_the_link_once():
    site = links.site_from_row({'business_id': BIZ, 'slug': 'fade-street',
                                'site_config': {'custom_domain': 'fadestreet.com', 'custom_domain_status': 'verified'}})
    link = f'{SITE}/go/abcdefgh'
    assert links.publish_text('Book at fadestreet.com/book today.', f'{SITE}/book', link, site) == \
        f'Book at {link} today.'
    assert links.publish_text('Book at www.fadestreet.com/book.', f'{SITE}/book', link, site) == f'Book at {link}.'
    assert links.publish_text('Book at fade-street.mysolutionist.app/book!', f'{SUB}/book', link, site) == \
        f'Book at {link}!'
    assert links.publish_text('Fresh fades.', f'{SITE}/book', link, site) == f'Fresh fades.\n\n{link}'
    assert links.publish_text('See fadestreet.com.evil.example/book', f'{SITE}/book', link, site) == \
        f'See fadestreet.com.evil.example/book\n\n{link}'
    assert links.publish_text(f'Already here: {link}', f'{SITE}/book', link, site) == f'Already here: {link}'
    assert links.publish_text('', f'{SITE}/book', link, site) == link


def test_the_platform_caption_rule_is_unchanged_by_default():
    link = 'https://mysolutionist.app/go/abcdefgh'
    assert platform_marketing.caption_with_landing_link(
        'Start at mysolutionist.app/start.', 'https://mysolutionist.app/start', link) == f'Start at {link}.'
    assert platform_marketing.caption_with_landing_link(
        'See fadestreet.com/', 'https://mysolutionist.app/', link) == f'See fadestreet.com/\n\n{link}'


# ── a post carries its link ───────────────────────────────────────────

def test_a_new_post_carries_its_short_link_on_the_business_own_origin(t):
    r = call(t, 'POST', '/ideas', {'caption': 'Fresh fades all week.', 'run_at': '2026-10-09T16:00:00Z'})
    assert r.status_code == 200, r.text
    row = t.db.posts[r.json()['post']['id']]
    code = store.link_code(row['id'])
    assert row['link_code'] == code and r.json()['link'] == f'{SITE}/go/{code}'
    assert row['landing_url'] == f'{SITE}/'                        # published site, nothing bookable: its home
    assert urlsplit(row['tracked_url']).hostname == 'fadestreet.com'
    assert tags(row['tracked_url'])['utm_content'] == row['id']
    assert row['publish_text'] == f'Fresh fades all week.\n\n{SITE}/go/{code}'
    assert row['content_hash'] == store.digest(row)
    assert store.bound_content(row)['publish_text'] == row['publish_text']
    assert store.bound_content(row)['landing_url'] == row['landing_url']


def test_the_booking_page_when_anything_is_bookable(t):
    t.svc.bookable()
    r = call(t, 'POST', '/ideas', {'caption': 'Two chairs open.'})
    row = t.db.posts[r.json()['post']['id']]
    assert row['landing_url'] == f'{SITE}/book' and urlsplit(row['tracked_url']).path == '/book'
    t.svc.offerings = []                                           # a calendar with nothing to book
    r = call(t, 'POST', '/ideas', {'caption': 'Two chairs open again.'})
    assert t.db.posts[r.json()['post']['id']]['landing_url'] == f'{SITE}/'


def test_the_post_link_then_the_desk_link_win_and_stay_on_the_business_hosts(t):
    t.db.desks[BIZ] = {**bm.DESK_DEFAULTS, 'business_id': BIZ, 'landing_url': f'{SUB}/about'}
    r = call(t, 'POST', '/ideas', {'caption': 'About us.'})
    row = t.db.posts[r.json()['post']['id']]
    assert row['landing_url'] == f'{SUB}/about'
    assert urlsplit(row['tracked_url']).hostname == 'fade-street.mysolutionist.app'
    assert row['publish_text'].endswith(f"{SITE}/go/{row['link_code']}")     # the short link is on the origin
    r = call(t, 'POST', '/ideas', {'caption': 'Book.', 'landing_url': 'https://www.fadestreet.com/book'})
    row = t.db.posts[r.json()['post']['id']]
    assert row['landing_url'] == 'https://www.fadestreet.com/book'
    assert urlsplit(row['tracked_url']).hostname == 'www.fadestreet.com'
    for bad in ('https://evil.example/', 'https://elsewhere.mysolutionist.app/'):
        assert call(t, 'POST', '/ideas', {'caption': 'x', 'landing_url': bad}).status_code == 422


def test_a_desk_link_that_left_the_site_falls_back_to_the_default(t):
    t.db.desks[BIZ] = {**bm.DESK_DEFAULTS, 'business_id': BIZ, 'landing_url': f'{SITE}/old'}
    t.svc.sites[0]['site_config']['custom_domain_status'] = 'pending'
    r = call(t, 'POST', '/ideas', {'caption': 'Fresh.'})
    row = t.db.posts[r.json()['post']['id']]
    assert row['landing_url'] == f'{SUB}/' and row['publish_text'].endswith(f"{SUB}/go/{row['link_code']}")


def test_without_a_verified_domain_the_link_is_on_the_subdomain(t):
    t.svc.sites[0]['site_config'] = {'custom_domain': 'fadestreet.com', 'custom_domain_status': 'pending'}
    r = call(t, 'POST', '/ideas', {'caption': 'Fresh.'})
    row = t.db.posts[r.json()['post']['id']]
    assert r.json()['link'] == f"{SUB}/go/{row['link_code']}"
    assert urlsplit(row['tracked_url']).hostname == 'fade-street.mysolutionist.app'


@pytest.mark.parametrize('how', ['no site row', 'nothing published or bookable'])
def test_a_business_with_no_site_posts_with_no_link(t, how):
    if how == 'no site row':
        t.svc.sites = [x for x in t.svc.sites if x['business_id'] != BIZ]
    else:
        t.svc.sites[0]['status'] = 'booking_only'
    r = call(t, 'POST', '/ideas', {'caption': 'Fresh fades.'})
    assert r.status_code == 200, r.text
    row = t.db.posts[r.json()['post']['id']]
    assert row['publish_text'] == 'Fresh fades.' and row['tracked_url'] is None and row['landing_url'] is None
    assert r.json()['link'] is None and row['content_hash'] == store.digest(row)


def test_changing_where_a_post_goes_changes_what_was_approved(t):
    t.svc.bookable()
    p = call(t, 'POST', '/ideas', {'caption': 'Two chairs open.', 'run_at': '2026-10-09T16:00:00Z'}).json()['post']
    assert call(t, 'POST', '/approve', {'items': [api.item(p)]}).status_code == 200
    r = call(t, 'POST', '/slot/edit', {'items': [slot(t.db.posts[p['id']])], 'landing_url': f'{SITE}/about'})
    assert r.status_code == 200, r.text
    row = t.db.posts[p['id']]
    assert row['landing_url'] == f'{SITE}/about' and urlsplit(row['tracked_url']).path == '/about'
    assert row['content_hash'] == store.digest(row) != p['content_hash']
    assert row['status'] == 'draft' and row['approved_hash'] is None
    assert row['link_code'] == p['link_code'] and row['publish_text'] == p['publish_text']
    r = call(t, 'POST', '/slot/edit', {'items': [slot(row)], 'landing_url': ''})            # back to the default
    assert t.db.posts[p['id']]['landing_url'] == f'{SITE}/book'


def test_a_caption_edit_keeps_the_link(t):
    p = put(t, status='draft', run_at=NOW + timedelta(days=2), landing=f'{SITE}/book')
    r = call(t, 'POST', '/slot/edit', {'items': [slot(p)], 'caption': 'Book at fadestreet.com/book now.'})
    assert r.status_code == 200, r.text
    row = t.db.posts[p['id']]
    assert row['publish_text'] == f"Book at {SITE}/go/{row['link_code']} now."
    assert row['tracked_url'] == p['tracked_url'] and row['content_hash'] == store.digest(row)


def test_a_post_whose_link_left_the_site_is_refused_until_its_link_changes(t):
    p = put(t, status='draft', run_at=NOW + timedelta(days=2), landing=f'{SITE}/book')
    t.svc.sites[0]['site_config']['custom_domain_status'] = 'pending'
    r = call(t, 'POST', '/slot/edit', {'items': [slot(p)], 'caption': 'New words.'})
    assert r.status_code == 422 and r.json()['detail'] == bm.LINK_GONE
    assert t.db.posts[p['id']]['revision'] == p['revision']
    r = call(t, 'POST', '/slot/edit', {'items': [slot(p)], 'caption': 'New words.', 'landing_url': ''})
    assert r.status_code == 200 and t.db.posts[p['id']]['landing_url'] == f'{SUB}/'


def test_a_post_saved_before_links_gets_one_when_it_is_edited(t):
    p = api.seed(t)                                  # landing None, publish_text the bare caption
    assert p['tracked_url'] is None
    r = call(t, 'POST', '/slot/edit', {'items': [slot(p)], 'caption': 'Fresh fades, new words.'})
    row = t.db.posts[p['id']]
    assert r.status_code == 200 and row['landing_url'] == f'{SITE}/'
    assert row['publish_text'] == f"Fresh fades, new words.\n\n{SITE}/go/{row['link_code']}"


def test_the_short_link_counts_toward_each_network_limit(t):
    t.svc.connections.append(api.connection(X, 'x'))
    r = call(t, 'POST', '/ideas', {'caption': 'y' * 260, 'connection_ids': [X]})
    assert r.status_code == 422 and 'X allows 280 characters' in r.json()['detail'] and t.db.posts == {}
    t.svc.sites[0]['status'] = 'booking_only'                   # no link: the same caption fits
    assert call(t, 'POST', '/ideas', {'caption': 'y' * 260, 'connection_ids': [X]}).status_code == 200


@pytest.mark.parametrize('fail', ['/business_sites', '/custom_modules', '/offerings'])
def test_a_failed_read_behind_the_link_refuses_and_writes_nothing(t, fail):
    t.svc.bookable()
    t.svc.fail = (fail,)
    r = call(t, 'POST', '/ideas', {'caption': 'Fresh fades.'})
    assert r.status_code == 503 and t.db.writes == [] and t.db.posts == {}


# ── /go/ on the business's own host ───────────────────────────────────

PERSON = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


@pytest.fixture
def go(t, monkeypatch):
    import public_site
    t.served = []

    async def by_slug(slug, path='/'):
        t.served.append(('slug', slug, path))
        return HTMLResponse('their own 404', status_code=404)

    async def by_domain(domain, path='/'):
        t.served.append(('domain', domain, path))
        return HTMLResponse('their own 404', status_code=404)

    async def platform_follow(code, *, count_click):
        raise AssertionError("a business's host never resolves a platform link")
    monkeypatch.setattr(public_site, '_serve_site_by_slug', by_slug)
    monkeypatch.setattr(public_site, '_serve_site_by_custom_domain', by_domain)
    monkeypatch.setattr(public_site, '_rate_buckets', {})
    monkeypatch.setattr(platform_marketing, 'follow', platform_follow)
    app = FastAPI()
    app.include_router(public_site.router)

    def hit(host, code, agent=PERSON, **headers):
        return page(host, f'/go/{code}', agent, **headers)

    def page(host, path, agent=PERSON, **headers):
        client = TestClient(app, base_url=f'https://{host}')
        return client.get(path, headers={'user-agent': agent, **headers}, follow_redirects=False)
    t.hit, t.page = hit, page
    return t


@pytest.mark.parametrize('host', ['fade-street.mysolutionist.app', 'fadestreet.com', 'www.fadestreet.com',
                                  'fade-street.getsolutionist.com'])
def test_the_right_host_redirects_a_person_and_counts_the_click(go, host):
    p = put(go)
    r = go.hit(host, p['link_code'])
    assert r.status_code == 302 and r.headers['location'] == p['tracked_url']
    assert r.headers['cache-control'] == 'no-store' and r.headers['x-robots-tag'] == 'noindex'
    assert go.db.counted(p['id']) == 1
    assert go.db.follows == [(p['link_code'], False), (p['link_code'], True)]    # checked before counted
    assert go.served == []


def test_the_custom_domain_reaches_through_the_edge_header(go):
    p = put(go)
    r = go.hit('kmj-intake-server-production.up.railway.app', p['link_code'], **{'x-original-host': 'fadestreet.com'})
    assert r.status_code == 302 and r.headers['location'] == p['tracked_url'] and go.db.counted(p['id']) == 1


@pytest.mark.parametrize('agent,extra', [
    ('facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)', {}),
    ('Twitterbot/1.0', {}), ('LinkedInBot/1.0 (compatible; Mozilla/5.0)', {}), ('WhatsApp/2.23.20.0', {}),
    ('', {}), (PERSON, {'dnt': '1'})], ids=['facebook', 'x', 'linkedin', 'whatsapp', 'no agent', 'do not track'])
def test_previews_and_do_not_track_are_redirected_but_not_counted(go, agent, extra):
    p = put(go)
    r = go.hit('fade-street.mysolutionist.app', p['link_code'], agent=agent, **extra)
    assert r.status_code == 302 and r.headers['location'] == p['tracked_url']
    assert go.db.counted(p['id']) == 0 and go.db.follows == [(p['link_code'], False)]


@pytest.mark.parametrize('status', ['draft', 'approved', 'dispatching', 'failed', 'uncertain', 'cancelled'])
def test_a_post_that_did_not_go_out_does_not_count(go, status):
    p = put(go, status=status)
    r = go.hit('fade-street.mysolutionist.app', p['link_code'])
    assert r.status_code == 302 and go.db.counted(p['id']) == 0


def test_a_code_used_on_another_business_host_is_refused_and_not_counted(go):
    theirs = put(go, biz=OTHER, landing='https://elsewhere.mysolutionist.app/')
    r = go.hit('fade-street.mysolutionist.app', theirs['link_code'])
    assert r.status_code == 404 and r.text == 'their own 404'
    assert go.db.counted(theirs['id']) == 0 and go.db.follows == [(theirs['link_code'], False)]
    assert go.served == [('slug', 'fade-street', f"/go/{theirs['link_code']}")]
    mine = put(go)
    assert go.hit('elsewhere.mysolutionist.app', mine['link_code']).status_code == 404
    assert go.db.counted(mine['id']) == 0
    # Even a row of theirs that points at this business's own site is not this business's link.
    go.db.posts[theirs['id']]['tracked_url'] = f'{SITE}/?utm_content={theirs["id"]}'
    assert go.hit('fadestreet.com', theirs['link_code']).status_code == 404
    assert go.db.counted(theirs['id']) == 0


@pytest.mark.parametrize('stored', [
    'https://evil.example/', 'http://fadestreet.com/', 'https://fadestreet.com.evil.example/',
    'https://user@fadestreet.com/', 'https://elsewhere.mysolutionist.app/', 'https://mysolutionist.app/',
    'https://fadestreet.com:8443/', 'javascript:alert(1)', None])
def test_never_an_open_redirect(go, stored):
    p = put(go)
    go.db.posts[p['id']]['tracked_url'] = stored
    r = go.hit('fadestreet.com', p['link_code'])
    assert r.status_code == 404 and r.text == 'their own 404' and go.db.counted(p['id']) == 0


def test_an_unverified_domain_is_not_a_destination(go):
    p = put(go)                                                   # tracked on fadestreet.com while verified
    go.svc.sites[0]['site_config']['custom_domain_status'] = 'pending'
    assert go.hit('fade-street.mysolutionist.app', p['link_code']).status_code == 404
    sub = put(go, landing=f'{SUB}/')
    r = go.hit('fadestreet.com', sub['link_code'])                # the pending domain's host still finds the site
    assert r.status_code == 302 and r.headers['location'] == sub['tracked_url']


@pytest.mark.parametrize('code', ['zzzzzzzz', 'short', 'ABCDEFGH1', 'abc-defg', 'abcd1890'])
def test_an_unknown_or_malformed_code_is_the_site_404(go, code):
    r = go.hit('fade-street.mysolutionist.app', code)
    assert r.status_code == 404 and r.text == 'their own 404'
    if not store.GO_CODE.match(code.lower()):
        assert go.db.follows == []


@pytest.mark.parametrize('fail,where', [('/rpc/marketing_follow', 'db'), ('/business_sites', 'svc')])
def test_a_storage_failure_is_the_site_404(go, fail, where):
    p = put(go)
    getattr(go, where).fail = (fail,)
    r = go.hit('fade-street.mysolutionist.app', p['link_code'])
    assert r.status_code == 404 and r.text == 'their own 404' and go.db.counted(p['id']) == 0


def test_an_unknown_site_host_is_the_site_answer(go):
    p = put(go)
    r = go.hit('nobody-here.mysolutionist.app', p['link_code'])
    assert r.status_code == 404 and go.db.follows == []


def test_a_go_flood_never_429s_the_site_pages(go, monkeypatch):
    import public_site
    monkeypatch.setattr(public_site, 'GO_RATE_LIMIT_PER_MIN', 3)
    p = put(go)
    for _ in range(3):
        assert go.hit('fade-street.mysolutionist.app', p['link_code']).status_code == 302
    assert go.hit('fade-street.mysolutionist.app', p['link_code']).status_code == 429
    assert go.hit('fade-street.mysolutionist.app', 'zzzzzzzz').status_code == 429      # dead codes too
    assert go.db.counted(p['id']) == 3
    assert 'fade-street' not in public_site._rate_buckets                 # the page bucket was never charged
    r = go.page('fade-street.mysolutionist.app', '/')
    assert r.status_code == 404 and r.text == 'their own 404'              # pages still answer
    theirs = put(go, biz=OTHER, landing='https://elsewhere.mysolutionist.app/')
    assert go.hit('elsewhere.mysolutionist.app', theirs['link_code']).status_code == 302   # another host's links too


def test_busy_pages_never_429_the_links(go, monkeypatch):
    import public_site
    monkeypatch.setattr(public_site, 'RATE_LIMIT_PER_MIN', 2)
    for _ in range(2):
        assert go.page('fade-street.mysolutionist.app', '/').status_code == 404
    assert go.page('fade-street.mysolutionist.app', '/').status_code == 429
    p = put(go)
    r = go.hit('fade-street.mysolutionist.app', p['link_code'])
    assert r.status_code == 302 and r.headers['location'] == p['tracked_url'] and go.db.counted(p['id']) == 1
    r = go.hit('fade-street.mysolutionist.app', 'zzzzzzzz')               # a miss still gets the site's 404
    assert r.status_code == 404 and r.text == 'their own 404'


def test_each_go_hit_is_charged_once_to_its_own_bucket(go):
    import public_site
    p = put(go)
    assert go.hit('fade-street.mysolutionist.app', 'zzzzzzzz').status_code == 404       # a miss
    assert public_site._rate_buckets.keys() == {'go:fade-street'}
    assert public_site._rate_buckets['go:fade-street']['count'] == 1
    assert go.hit('fade-street.mysolutionist.app', p['link_code']).status_code == 302   # a hit
    assert public_site._rate_buckets['go:fade-street']['count'] == 2
    go.hit('fadestreet.com', 'zzzzzzzz'), go.hit('www.fadestreet.com', p['link_code'])
    assert public_site._rate_buckets.keys() == {'go:fade-street', 'go:fadestreet.com'}  # www shares the apex
    assert public_site._rate_buckets['go:fadestreet.com']['count'] == 2


def test_the_apex_still_follows_the_platform_link(go, monkeypatch):
    seen = []

    async def platform_follow(code, *, count_click):
        seen.append((code, count_click))
        return 'https://mysolutionist.app/?utm_content=post'
    monkeypatch.setattr(platform_marketing, 'follow', platform_follow)
    p = put(go)
    r = go.hit('mysolutionist.app', p['link_code'])
    assert r.status_code == 302 and r.headers['location'] == 'https://mysolutionist.app/?utm_content=post'
    assert seen == [(p['link_code'], True)] and go.db.follows == [] and go.served == []
    r = go.hit('www.mysolutionist.app', 'abcdefgh', agent='Twitterbot/1.0')
    assert r.status_code == 302 and seen[-1] == ('abcdefgh', False)


# ── results ───────────────────────────────────────────────────────────

def visit(t, post, session, *, biz=BIZ, days_ago=1):
    t.svc.events.append({'business_id': biz, 'session_id': session, 'event': 'view', 'path': '/',
                         'ts': (NOW - timedelta(days=days_ago)).isoformat().replace('+00:00', 'Z'),
                         'data': {'utm_content': post['id'], 'utm_source': 'social'}})


def lead(t, post, *, biz=BIZ, days_ago=1):
    t.svc.contacts.append({'id': str(uuid4()), 'business_id': biz, 'attribution': {'utm_content': post['id']},
                           'created_at': (NOW - timedelta(days=days_ago)).isoformat()})


def click(t, post, n, *, days_ago=1):
    t.db.clicks.append({'post_id': post['id'], 'business_id': post['business_id'],
                        'day': (NOW - timedelta(days=days_ago)).date().isoformat(), 'clicks': n})


def test_results_per_post_and_in_total(t):
    a, b = put(t, caption='Post A'), put(t, status='partly_published', caption='Post B')
    bare = put(t, landing=None, caption='No link')
    put(t, status='draft', run_at=NOW + timedelta(days=1))                     # not out yet
    put(t, run_at=NOW - timedelta(days=40))                                    # outside the 30 days
    theirs = put(t, biz=OTHER, landing='https://elsewhere.mysolutionist.app/')
    click(t, a, 3), click(t, a, 2, days_ago=2), click(t, b, 1)
    visit(t, a, 's1'), visit(t, a, 's1'), visit(t, a, 's2'), visit(t, b, 's3')
    visit(t, a, 's9', biz=OTHER), visit(t, theirs, 's8', biz=OTHER)
    lead(t, a), lead(t, theirs, biz=OTHER)
    r = call(t, 'GET', '/results')
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['totals'] == {'clicks': 6, 'visits': 3, 'leads': 1}
    assert body['sources'] == {'clicks': 'loaded', 'visits': 'loaded', 'leads': 'loaded'}
    assert body['sent'] == 3 and body['linked'] == 2 and body['window_days'] == 30
    assert body['site'] == {'state': 'ready', 'origin': SITE}
    by = {p['id']: p for p in body['posts']}
    assert set(by) == {a['id'], b['id'], bare['id']}
    assert (by[a['id']]['clicks'], by[a['id']]['visits'], by[a['id']]['leads']) == (5, 2, 1)
    assert (by[b['id']]['clicks'], by[b['id']]['visits'], by[b['id']]['leads']) == (1, 1, 0)
    assert by[bare['id']]['has_link'] is False and by[bare['id']]['clicks'] is None
    assert by[a['id']]['accounts'] == ['Facebook'] and by[a['id']]['link_code'] == a['link_code']
    assert body['headline'] == '6 visits and 1 lead came through the links in your 2 posts from the last 30 days.'
    assert 'brought' not in body['headline']
    assert t.db.writes == []
    reads = [p for p in t.svc.reads if p.startswith(('/site_events', '/contacts'))]
    assert reads and all(f'business_id=eq.{BIZ}' in p for p in reads)


def test_an_unreadable_source_is_unavailable_never_zero(t):
    a = put(t)
    click(t, a, 2)
    t.svc.fail = ('/site_events',)
    body = call(t, 'GET', '/results').json()
    assert body['totals'] == {'clicks': 2, 'visits': None, 'leads': 0}
    assert body['sources'] == {'clicks': 'loaded', 'visits': 'unavailable', 'leads': 'loaded'}
    assert body['posts'][0]['visits'] is None and body['posts'][0]['leads'] == 0
    assert body['headline'].startswith('Some results could not be read just now')
    t.svc.fail = ()
    t.db.fail = ('/marketing_link_clicks',)
    body = call(t, 'GET', '/results').json()
    assert body['totals']['clicks'] is None and body['sources']['clicks'] == 'unavailable'


def test_nothing_came_through_is_a_real_zero(t):
    put(t)
    body = call(t, 'GET', '/results').json()
    assert body['totals'] == {'clicks': 0, 'visits': 0, 'leads': 0}
    assert body['headline'] == 'No one has followed the links in your 1 post from the last 30 days yet.'


def test_a_read_at_its_limit_is_a_floor(t, monkeypatch):
    a = put(t)
    monkeypatch.setitem(outcomes.LIMITS, 'visits', 2)
    for n in range(3):
        visit(t, a, f's{n}')
    body = call(t, 'GET', '/results').json()
    assert body['sources']['visits'] == 'partial' and body['headline'].startswith('At least ')


def test_results_say_when_there_is_no_site(t):
    put(t, landing=None)
    t.svc.sites = [x for x in t.svc.sites if x['business_id'] != BIZ]
    body = call(t, 'GET', '/results').json()
    assert body['site'] == {'state': 'none', 'origin': None} and body['linked'] == 0
    assert body['totals'] == {'clicks': 0, 'visits': 0, 'leads': 0}
    assert 'no site or booking page' in body['headline']
    t.db.posts.clear()
    assert 'no link until this business has a site' in call(t, 'GET', '/results').json()['headline']


def test_results_with_nothing_sent(t):
    put(t, status='draft', run_at=NOW + timedelta(days=1))
    body = call(t, 'GET', '/results').json()
    assert body['sent'] == 0 and body['posts'] == []
    assert body['headline'].startswith('Nothing has gone out from the marketing desk in the last 30 days')


def test_unreadable_posts_are_a_503_and_an_unreadable_site_is_named(t):
    put(t)
    t.svc.fail = ('/business_sites',)
    body = call(t, 'GET', '/results').json()
    assert body['site'] == {'state': 'unavailable', 'origin': None}
    t.svc.fail = ()
    t.db.fail = ('/marketing_posts',)
    r = call(t, 'GET', '/results')
    assert r.status_code == 503 and r.json()['detail'] == bm.READ_DOWN


def test_owner_and_members_read_results_and_a_stranger_does_not(t):
    put(t)
    assert call(t, 'GET', '/results').status_code == 200
    t.user = MEMBER
    assert call(t, 'GET', '/results').status_code == 200
    t.user = STRANGER
    assert call(t, 'GET', '/results').status_code == 404
    assert call(t, 'GET', '/results', biz=str(uuid4())).status_code == 404
    assert t.db.writes == []


# ── the site keeps the tags for the session ───────────────────────────

def test_the_business_beacon_reports_which_post_a_visit_came_from():
    import public_site
    js = public_site._traffic_beacon(BIZ)
    assert "'utm_content'" in js and 'c:C' in js and "sessionStorage.setItem('sol_c'" in js
    assert js.index('doNotTrack') < js.index("'utm_content'") < js.index('fetch(')
    assert 'sendBeacon' not in js
