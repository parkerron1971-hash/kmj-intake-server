"""A Solutionist post can be followed back from what it brought in.

The short link in the caption, the redirect that tags it, the site scripts
that carry the tag to signup, and the join that counts what came through.
No network: the database is faked at the one seam every reader uses.
"""
import asyncio
import pathlib
import sys
from uuid import uuid4

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import marketing_outcomes as outcomes
import platform_marketing as m


def run(coro):
    return asyncio.run(coro)


# ── the code ──────────────────────────────────────────────────────────

def test_link_code_is_stable_short_and_per_post():
    a, b = uuid4(), uuid4()
    assert m.link_code(a) == m.link_code(str(a))
    assert m.link_code(a) != m.link_code(b)
    assert m.GO_CODE.match(m.link_code(a))
    assert m.short_link(m.link_code(a)) == f'https://mysolutionist.app/go/{m.link_code(a)}'


# ── follow: the redirect's lookup ─────────────────────────────────────

@pytest.fixture
def rpc(monkeypatch):
    calls = []
    answer = {'value': 'https://mysolutionist.app/?utm_source=facebook&utm_content=x'}

    async def db(method, path, body=None):
        calls.append((method, path, body))
        if isinstance(answer['value'], Exception):
            raise answer['value']
        return answer['value']
    monkeypatch.setattr(m, 'db', db)
    return calls, answer


@pytest.mark.parametrize('code', ['', 'short', 'UPPERCAS', 'abcd1890', 'abcdefghi', '../../etc'])
def test_malformed_code_never_reaches_the_database(rpc, code):
    calls, _ = rpc
    assert run(m.follow(code, count_click=True)) is None
    assert calls == []


def test_follow_passes_the_click_decision_through(rpc):
    calls, _ = rpc
    url = run(m.follow('abcdefgh', count_click=False))
    assert url.startswith('https://mysolutionist.app/')
    assert calls == [('POST', '/rpc/platform_marketing_follow', {'code': 'abcdefgh', 'count_click': False})]


@pytest.mark.parametrize('stored', ['https://evil.test/', 'http://mysolutionist.app/',
    'https://mysolutionist.app.evil.test/', 'javascript:alert(1)', None, ['x']])
def test_follow_is_never_an_open_redirect(rpc, stored):
    _, answer = rpc
    answer['value'] = stored
    assert run(m.follow('abcdefgh', count_click=True)) is None


def test_a_storage_failure_is_a_miss_not_an_error(rpc):
    _, answer = rpc
    answer['value'] = HTTPException(503, 'down')
    assert run(m.follow('abcdefgh', count_click=True)) is None


# ── the /go route ─────────────────────────────────────────────────────

@pytest.fixture
def go(monkeypatch):
    import public_site
    seen = []

    async def follow(code, *, count_click):
        seen.append((code, count_click))
        return 'https://mysolutionist.app/?utm_content=post' if code == 'abcdefgh' else None

    async def platform_host(request):
        return None
    monkeypatch.setattr(m, 'follow', follow)
    monkeypatch.setattr(public_site, '_site_response_or_none', platform_host)
    app = FastAPI()
    app.include_router(public_site.router)
    return TestClient(app), seen


PERSON = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148'


def test_a_person_is_redirected_and_counted(go):
    client, seen = go
    r = client.get('/go/abcdefgh', headers={'user-agent': PERSON}, follow_redirects=False)
    assert r.status_code == 302 and r.headers['location'] == 'https://mysolutionist.app/?utm_content=post'
    assert r.headers['cache-control'] == 'no-store'
    assert seen == [('abcdefgh', True)]


@pytest.mark.parametrize('agent', ['facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)',
    'Twitterbot/1.0', 'LinkedInBot/1.0 (compatible; Mozilla/5.0)', 'WhatsApp/2.23.20.0', ''])
def test_link_previews_are_redirected_but_not_counted(go, agent):
    client, seen = go
    r = client.get('/go/abcdefgh', headers={'user-agent': agent}, follow_redirects=False)
    assert r.status_code == 302
    assert seen == [('abcdefgh', False)]


def test_do_not_track_is_not_counted(go):
    client, seen = go
    client.get('/go/abcdefgh', headers={'user-agent': PERSON, 'dnt': '1'}, follow_redirects=False)
    assert seen == [('abcdefgh', False)]


def test_unknown_code_lands_on_the_home_page(go):
    client, _ = go
    r = client.get('/go/zzzzzzzz', headers={'user-agent': PERSON}, follow_redirects=False)
    assert r.status_code == 302 and r.headers['location'] == 'https://mysolutionist.app/'


def test_a_practitioner_host_keeps_its_own_go_page(monkeypatch):
    import public_site
    from fastapi.responses import HTMLResponse

    async def site_host(request):
        return HTMLResponse('their page')

    async def follow(code, *, count_click):
        raise AssertionError('a practitioner host must never resolve a platform link')
    monkeypatch.setattr(public_site, '_site_response_or_none', site_host)
    monkeypatch.setattr(m, 'follow', follow)
    app = FastAPI()
    app.include_router(public_site.router)
    r = TestClient(app).get('/go/abcdefgh', follow_redirects=False)
    assert r.status_code == 200 and r.text == 'their page'


# ── the site scripts carry the tag to signup ──────────────────────────

def test_beacon_reports_which_post_a_visit_came_from():
    import marketing_home_v2
    import marketing_pages
    for scripts in (marketing_pages.SHELL_TEMPLATE, marketing_home_v2._analytics_scripts()):
        beacon = scripts[scripts.index('the session\'s campaign params'):]
        assert "'utm_content'" in beacon[:400]


def test_start_links_carry_the_session_tags():
    import marketing_home_v2
    scripts = marketing_home_v2._analytics_scripts()
    assert "url.pathname !== '/start'" in scripts
    assert 'searchParams.has(k)' in scripts          # never overwrite a param the link names
    assert "'referrer'" not in scripts[scripts.index('The signup door'):scripts.index('The signup door') + 1200]


# ── the join ──────────────────────────────────────────────────────────

@pytest.fixture
def tables(monkeypatch):
    a, b = str(uuid4()), str(uuid4())
    data = {
        'platform_marketing_link_clicks': [{'post_id': a, 'clicks': 4}, {'post_id': a, 'clicks': 2}, {'post_id': b, 'clicks': 1}],
        'site_events': [{'session_id': 's1', 'data': {'utm_content': a}}, {'session_id': 's1', 'data': {'utm_content': a}},
                        {'session_id': 's2', 'data': {'utm_content': a}}, {'session_id': None, 'data': {'utm_content': b}}],
        'marketing_leads': [{'id': 1, 'attribution': {'utm_content': a}}],
        'waitlist': [],
        'businesses': [{'id': 1, 'attribution': {'utm_content': a}, 'subscription_status': 'active'},
                       {'id': 2, 'attribution': {'utm_content': b}, 'subscription_status': 'trialing'}],
    }
    broken = set()
    paths = []

    async def db(method, path, body=None):
        table = path.split('?')[0].strip('/')
        paths.append(path)
        if table in broken:
            raise HTTPException(503, 'down')
        return data[table]
    monkeypatch.setattr(m, 'db', db)
    return a, b, broken, paths


def test_outcomes_count_what_came_through_each_link(tables):
    a, b, _, paths = tables
    out = run(outcomes.for_posts([{'id': a}, {'id': b}]))
    assert out['posts'][a] == {'clicks': 6, 'visits': 2, 'leads': 1, 'waitlist': 0, 'signups': 1, 'paying': 1}
    assert out['posts'][b] == {'clicks': 1, 'visits': 0, 'leads': 0, 'waitlist': 0, 'signups': 1, 'paying': 0}
    assert out['totals'] == {'clicks': 7, 'visits': 2, 'leads': 1, 'waitlist': 0, 'signups': 2, 'paying': 1}
    # Only the platform's own site traffic, joined on the exact post id.
    assert any('business_id=is.null' in p and 'data->>utm_content=in.(' in p for p in paths)


def test_a_failed_read_is_unavailable_never_zero(tables):
    a, _, broken, _ = tables
    broken.add('businesses')
    out = run(outcomes.for_posts([{'id': a}]))
    assert out['totals']['signups'] is None and out['totals']['paying'] is None
    assert out['posts'][a]['signups'] is None
    assert out['sources']['signups'] == 'unavailable' and out['totals']['clicks'] == 6
    assert 'could not be read' in outcomes.headline(out['totals'], 1)


def test_post_ids_are_validated_before_they_reach_a_filter(tables):
    with pytest.raises(ValueError):
        run(outcomes.for_posts([{'id': 'x),or=(id.gt.0'}]))


def test_headline_says_came_through_never_brought():
    totals = {'clicks': 7, 'visits': 2, 'leads': 1, 'waitlist': 0, 'signups': 2, 'paying': 1}
    line = outcomes.headline(totals, 3)
    assert line == '7 visits, 1 lead, 2 signups and 1 paying customer came through the links in your 3 published posts.'
    assert 'brought' not in line and 'caused' not in line
    assert outcomes.headline({**totals, 'clicks': 0, 'visits': 0}, 1) == 'No one has followed the links in your 1 published post yet.'
    assert outcomes.headline(totals, 0).startswith('Nothing has been published')


def test_campaign_performance_carries_outcomes_and_honest_note(tables):
    import platform_marketing_campaigns as pmc
    a, _, _, _ = tables
    out = run(outcomes.for_posts([{'id': a}]))
    perf = pmc.performance([{'id': a, 'status': 'published'}], [], out)
    assert perf['customer_outcomes']['signups'] == 1
    assert 'not proof the post persuaded them' in perf['outcome_note']
    assert pmc.performance([], [])['customer_outcomes'] is None
