# __tests__/test_member_stopwatch.py
#
# The member app's stopwatch (member_stopwatch.py, 2026-11-18). Kevin: "the
# members app move slow when send messages in chat, switching from one tab to
# another"; nothing timed member pages, so this measures them before the
# fixes land. Pins:
#   1. paths print as patterns (no id, number or query) and land in a kind
#   2. every /my request gets a Server-Timing header (total, church, session,
#      rest) and one log line; other paths and MEMBER_STOPWATCH=off get neither
#   3. only a signed-in member's page counts (never a sign-in page or the
#      owner's preview)
#   4. the phone's beacon: own address, own page, a signed-in member, never
#      the preview, plausible numbers, rate-limited; no read on a known host
#   5. a reading takes each sample once; Check now never moves the mark
#   6. the card adds the readings up in plain words
#   7. the phone script runs and sends only the pattern and two numbers

import asyncio
import json
import pathlib
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import member_portal as mp
import member_portal_preview as pv
import member_stopwatch as ms
import rate_limit
import sb_clients

BIZ = "11111111-1111-1111-1111-111111111111"
ME = {"id": "22222222-2222-2222-2222-222222222222", "name": "Ana Reyes", "email": "ana@example.com",
      "birthdate": "1980-05-01"}
BUSINESS = {"id": BIZ, "name": "First Light Church", "type": "church", "is_sample": False,
            "settings": {"member_portal": {"enabled": True}}, "stripe_account_id": None}
HOST = "first-light.mysolutionist.app"
THREAD = "9b2f3c4d-1111-2222-3333-444455556666"


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.delenv("MEMBER_STOPWATCH", raising=False)
    ms.forget()
    rate_limit._buckets.clear()
    yield
    ms.forget()
    rate_limit._buckets.clear()


@pytest.fixture
def reads(monkeypatch):
    """The database, faked: the church on its address and Ana's record."""
    asked = []

    def get(path, **k):
        asked.append(path)
        time.sleep(0.005)
        if path.startswith("/business_sites"):
            return [{"slug": "first-light", "business_id": BIZ, "site_config": {}, "business": dict(BUSINESS)}]
        if path.startswith("/contacts"):
            return [dict(ME)]
        return []
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    return asked


def _member_cookie():
    return {mp.SESSION_COOKIE: mp.mint_session(BIZ, ME["email"], ME["id"])}


def _app():
    """The real lookups (member_portal) behind the stopwatch, as on production:
    outside gzip, a page that reads the church and the member."""
    app = FastAPI()
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(ms.MemberStopwatch)
    app.include_router(ms.router)

    async def page(request: Request):
        church = await asyncio.to_thread(mp._church_for_request, request)
        sess = await asyncio.to_thread(mp._session_for, request, church) if church else None
        if request.query_params.get("boom"):
            raise RuntimeError("boom")
        status = 200 if sess and sess.get("me") else 303
        return HTMLResponse("<p>Welcome home</p>" * 200, status_code=status)

    app.add_api_route("/my", page, methods=["GET"])
    app.add_api_route("/my/{rest:path}", page, methods=["GET", "POST"])

    @app.get("/about")
    async def about():
        return HTMLResponse("<p>About</p>")
    return app


def _client(app=None):
    return TestClient(app or _app(), base_url=f"https://{HOST}", raise_server_exceptions=False)


# ── 1. patterns and kinds ─────────────────────────────────────────────

@pytest.mark.parametrize("path, pat", [
    ("/my", "/my"),
    (f"/my/messages/{THREAD}", "/my/messages/:id"),
    (f"/my/messages/{THREAD}/send", "/my/messages/:id/send"),
    ("/my/news/1234", "/my/news/:id"),
    ("/my/bible/john/3?plan=x", "/my/bible/john/:id"),
    ("/my/lead/assignments/abc_DEF.9/done", "/my/lead/assignments/:id/done"),
    ("/my/directory/Ana%20Reyes", "/my/directory/:id"),
    ("/my/icon-192.png", "/my/:id"),
])
def test_a_path_prints_as_a_pattern(path, pat):
    assert ms.pattern(path) == pat


@pytest.mark.parametrize("method, path, kind", [
    ("GET", "/my", "home"),
    ("GET", "/my/sermons", "watch"), ("GET", "/my/sermons/abc1", "watch"), ("GET", "/my/live", "watch"),
    ("GET", "/my/bible/john/3", "bible"),
    ("GET", "/my/give", "give"),
    ("GET", "/my/groups", "connect"), ("GET", "/my/classes", "connect"), ("GET", "/my/directory", "connect"),
    ("GET", "/my/messages", "messages"), ("GET", "/my/inbox", "messages"),
    ("GET", f"/my/messages/{THREAD}", "conversation"), ("GET", "/my/inbox/church", "conversation"),
    ("GET", f"/my/groups/{THREAD}/chat", "conversation"),
    ("GET", "/my/me", "me"),
    ("GET", f"/my/groups/{THREAD}", "page"), ("GET", "/my/events", "page"), ("GET", "/my/me/celebrations", "page"),
    ("POST", f"/my/messages/{THREAD}/send", "send"), ("POST", "/my/inbox/church/send", "send"),
    ("POST", "/my/rsvp", "save"),
    ("GET", f"/my/messages/feed/{THREAD}", "poll"), ("GET", "/my/live/feed", "poll"),
    ("GET", "/my/sw.js", "asset"), ("GET", "/my/icon-512.png", "asset"), ("GET", "/my/manifest.webmanifest", "asset"),
    ("GET", f"/my/photo/{THREAD}", "asset"),
    ("POST", "/my/timing", None), ("GET", "/my/preview", None),
])
def test_each_request_lands_in_its_kind(method, path, kind):
    assert ms.kind_of(method, path) == kind


# ── 2. the header and the log line ────────────────────────────────────

def _timing(resp):
    return {m.group(1): float(m.group(2))
            for m in re.finditer(r'(\w+);(?:desc="[^"]*";)?dur=([\d.]+)', resp.headers.get("server-timing", ""))}


def test_a_member_page_says_how_long_each_part_took(reads, capsys):
    c = _client()
    c.cookies.update(_member_cookie())
    r = c.get(f"/my/messages/{THREAD}?from=push", headers={"accept-encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("content-encoding") == "gzip"
    t = _timing(r)
    assert set(t) == {"total", "church", "session", "rest"}, r.headers.get("server-timing")
    assert t["church"] >= 4 and t["session"] >= 4          # each lookup made one faked 5 ms read
    assert t["total"] >= t["church"] + t["session"]
    assert t["rest"] == pytest.approx(t["total"] - t["church"] - t["session"], abs=0.2)
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("[member]")]
    assert len(line) == 1
    assert re.fullmatch(r"\[member\] GET /my/messages/:id 200 \d+ms church=\d+ session=\d+", line[0]), line
    assert THREAD not in line[0] and "push" not in line[0]


def test_a_post_is_timed_too(reads, capsys):
    c = _client()
    c.cookies.update(_member_cookie())
    r = c.post(f"/my/messages/{THREAD}/send", data={"body": "Running late, save me a seat"})
    assert r.status_code == 200 and "total" in _timing(r)
    out = capsys.readouterr().out
    assert "[member] POST /my/messages/:id/send 200" in out and "seat" not in out
    assert ms.numbers()["server"]["send"]["n"] == 1


def test_other_paths_are_not_timed(reads, capsys):
    r = _client().get("/about")
    assert "server-timing" not in r.headers and "[member]" not in capsys.readouterr().out


def test_switched_off_there_is_no_header_no_line_no_number(reads, capsys, monkeypatch):
    monkeypatch.setenv("MEMBER_STOPWATCH", "off")
    c = _client()
    c.cookies.update(_member_cookie())
    r = c.get("/my")
    assert r.status_code == 200 and "server-timing" not in r.headers
    assert "[member]" not in capsys.readouterr().out and ms.numbers() == {}
    assert ms.phone_js() == "" and ms.for_reading("manual") is None


def test_a_failing_page_still_prints_its_line(reads, capsys):
    c = _client()
    c.cookies.update(_member_cookie())
    assert c.get("/my?boom=1").status_code == 500
    assert "[member] GET /my 500 " in capsys.readouterr().out
    assert ms.numbers() == {}


def test_polls_and_icons_print_only_when_slow(reads, capsys):
    c = _client()
    c.cookies.update(_member_cookie())
    c.get(f"/my/messages/feed/{THREAD}")
    c.get("/my/sw.js")
    assert "[member]" not in capsys.readouterr().out
    w = ms._Watch()
    w.t0 -= 2.0                                             # two seconds ago
    assert ms.finish("GET", f"/my/messages/feed/{THREAD}", 200, w) .startswith(
        "[member] GET /my/messages/feed/:id 200 2")
    assert ms.numbers() == {}


# ── 3. what counts ────────────────────────────────────────────────────

def test_only_a_signed_in_members_page_counts(reads):
    c = _client()
    c.get("/my")                                            # the sign-in page
    c.get("/my/groups")                                     # sent to sign in
    assert ms.numbers() == {}
    c.cookies.update(_member_cookie())
    c.get("/my")
    c.get("/my/groups")
    c.get(f"/my/messages/feed/{THREAD}")                    # a poll never counts
    got = ms.numbers()["server"]
    assert set(got) == {"home", "connect"} and got["home"]["n"] == 1


def test_the_owners_preview_never_counts(reads, monkeypatch):
    monkeypatch.setattr(mp, "portal_eligible", lambda biz: True)
    monkeypatch.setattr(pv, "load_contact", lambda biz_id, cid: dict(ME))
    c = _client()
    c.cookies.update({pv.PREVIEW_COOKIE: pv.mint_session(BIZ, ME["id"], "owner-1")})
    r = c.get("/my")
    assert r.status_code == 200 and "session" in _timing(r)
    assert ms.numbers() == {}


# ── 4. the phone's beacon ─────────────────────────────────────────────

def _beacon(c, body=None, *, origin=f"https://{HOST}", site=None, cookies=True, host=None):
    headers = {"content-type": "text/plain;charset=UTF-8"}
    if origin is not None:
        headers["origin"] = origin
    if site is not None:
        headers["sec-fetch-site"] = site
    if host:
        headers["host"] = host
    if cookies:
        c.cookies.update(_member_cookie())
    payload = body if body is not None else json.dumps({"p": "/my/messages/:id", "f": 180, "r": 640, "t": 0})
    return c.post("/my/timing", content=payload, headers=headers)


def test_the_phone_timing_is_kept(reads):
    r = _beacon(_client())
    assert r.status_code == 204
    got = ms.numbers()
    assert got["first_byte"]["conversation"] == {"n": 1, "p50": 180, "p90": 180}
    assert got["ready"]["conversation"] == {"n": 1, "p50": 640, "p90": 640}


def test_a_known_address_costs_no_read(reads):
    c = _client()
    c.cookies.update(_member_cookie())
    c.get("/my")
    before = len(reads)
    assert _beacon(c).status_code == 204
    assert len(reads) == before and ms.numbers()["ready"]["conversation"]["n"] == 1


def test_an_unknown_address_is_looked_up_once(reads):
    c = _client()
    assert _beacon(c).status_code == 204
    assert _beacon(c).status_code == 204
    assert sum(1 for p in reads if p.startswith("/business_sites")) == 1
    assert ms.numbers()["ready"]["conversation"]["n"] == 2


@pytest.mark.parametrize("kw, status", [
    ({"origin": "https://other-church.mysolutionist.app"}, 403),   # another church's page
    ({"origin": "https://evil.example"}, 403),
    ({"origin": None}, 403),                                       # no Origin, no Referer, no Sec-Fetch-Site
    ({"origin": "null", "site": "same-site"}, 403),
    ({"host": "kmj-intake-server-production.up.railway.app",
      "origin": "https://kmj-intake-server-production.up.railway.app"}, 404),  # the API host
])
def test_only_the_churchs_own_page_may_send(reads, kw, status):
    assert _beacon(_client(), **kw).status_code == status
    assert ms.numbers() == {}


def test_origin_null_from_its_own_page_is_taken(reads):
    """A page still under the old no-referrer header posts Origin: null; the
    browser's own Sec-Fetch-Site says it came from this address."""
    assert _beacon(_client(), origin="null", site="same-origin").status_code == 204
    assert ms.numbers()["ready"]["conversation"]["n"] == 1


def test_only_a_signed_in_member_counts(reads):
    c = _client()
    assert _beacon(c, cookies=False).status_code == 204                  # no session
    c.cookies.update({mp.SESSION_COOKIE: mp.mint_session("other-church", ME["email"], ME["id"])})
    assert _beacon(c, cookies=False).status_code == 204                  # another church's session
    c.cookies.clear()
    c.cookies.update({**_member_cookie(), pv.PREVIEW_COOKIE: "x"})
    assert _beacon(c, cookies=False).status_code == 204                  # the owner's preview
    assert ms.numbers() == {}


@pytest.mark.parametrize("body", [
    "not json", "[]", json.dumps({"p": "/about", "f": 1, "r": 2}),
    json.dumps({"p": "/my", "f": 900, "r": 300}),                         # first byte after ready
    json.dumps({"p": "/my", "f": 10, "r": 61000}),                        # over a minute
    json.dumps({"p": "/my", "f": True, "r": 300}),
    json.dumps({"p": "/my/sw.js", "f": 10, "r": 300}),                    # not a page
    json.dumps({"p": "/my", "f": 10, "r": 300, "x": "y" * 600}),          # too big
])
def test_nonsense_is_dropped(reads, body):
    assert _beacon(_client(), body).status_code == 400
    assert ms.numbers() == {}


def test_one_network_is_limited(reads, monkeypatch):
    monkeypatch.setitem(rate_limit._LIMITS, "member_timing", (3, 60))
    c = _client()
    codes = [_beacon(c).status_code for _ in range(5)]
    assert codes == [204, 204, 204, 429, 429]
    assert ms.numbers()["ready"]["conversation"]["n"] == 3


# ── 5. what a reading saves ───────────────────────────────────────────

def test_a_reading_takes_each_sample_once():
    now = time.time()
    for ms_ in (300, 500, 700):
        ms.record("server", "home", ms_, at=now - 600)
    ms.record("ready", "home", 900, at=now - 600)
    ms.record("server", "home", 9999, at=now - 3 * 3600)    # older than an hour: never
    got = ms.for_reading("sunday", now)
    assert got["server"]["home"]["n"] == 3 and got["server"]["home"]["p50"] == 500
    assert got["ready"]["home"]["n"] == 1 and sum(got["server"]["home"]["h"]) == 3
    assert ms.for_reading("sunday", now + 1) is None           # nothing new since
    ms.record("server", "home", 400, at=now + 5)
    assert ms.for_reading("sunday", now + 10)["server"]["home"]["n"] == 1


def test_check_now_never_steals_sundays_numbers():
    now = time.time()
    ms.record("server", "home", 300, at=now - 60)
    assert ms.for_reading("manual", now)["server"]["home"]["n"] == 1
    assert ms.for_reading("manual", now)["server"]["home"]["n"] == 1
    assert ms.for_reading("sunday", now)["server"]["home"]["n"] == 1


def test_histograms_add_up_and_read_back_close():
    vals = [300] * 50 + [900] * 40 + [2000] * 10
    h = ms.merge([ms.hist(vals[:30]), ms.hist(vals[30:])])
    assert h == ms.hist(vals) and sum(h) == 100
    assert 300 <= ms.from_hist(h, 0.5) <= 350
    assert 900 <= ms.from_hist(h, 0.9) <= 1000
    assert ms.from_hist([], 0.5) is None


# ── 6. the card ───────────────────────────────────────────────────────

def _row(kind, at, member):
    return {"kind": kind, "taken_at": at, "metrics": {"mem_total": 1.0, "member_app": member} if member else {}}


def _reading(ready, server, kind="home"):
    return {"v": 1, "ready": {kind: {"n": len(ready), "h": ms.hist(ready)}},
            "server": {kind: {"n": len(server), "h": ms.hist(server)}}}


def _words(dt):
    return "Wednesday at 3:04 PM" if dt.hour == 20 else "Sunday at 9:00 AM"


def test_the_card_adds_up_last_sundays_readings():
    # Read back from the buckets: 16 of 20 in 0.8-0.9 s, 4 in 1.6-1.8 s.
    sunday = [_row("sunday", "2026-11-22T14:00:00Z", _reading([800] * 8 + [1700] * 2, [300] * 7 + [800] * 3)),
              _row("sunday", "2026-11-22T14:15:00Z",
                   _reading([800] * 8 + [1700] * 2, [300] * 7 + [800] * 3, "connect")),
              _row("sunday", "2026-11-22T14:30:00Z", None)]
    got = ms.card(sunday, sunday, so_far=False, when_words=_words)
    assert got["headline"] == "Tabs open in 0.9 s typical, 1.7 s for the slowest 1 in 10 (last Sunday)."
    assert got["sunday"]["readings"] == 2 and got["sunday"]["ready"]["n"] == 20
    assert got["sunday"]["server_line"] == "The server's share of a page: 0.3 s typical, 0.9 s for the slowest 1 in 10."
    assert [p["label"] for p in got["sunday"]["pages"]] == ["Home", "Connect"]
    assert got["latest"] is None and got["has_numbers"]


def test_the_card_shows_a_newer_check_beside_sunday():
    sunday = [_row("sunday", "2026-11-22T14:00:00Z", _reading([800] * 10, [300] * 10))]
    check = _row("manual", "2026-11-25T20:04:00Z", _reading([460] * 10, [150] * 10))
    got = ms.card(sunday, sunday + [check], so_far=False, when_words=_words)
    assert got["headline"].endswith("(last Sunday).")
    assert got["latest"]["line"] == ("Tabs open in 0.5 s typical, 0.5 s for the slowest 1 in 10 "
                                     "(the hour before Wednesday at 3:04 PM).")
    assert got["latest"]["at"] == "2026-11-25T20:04:00Z"


def test_the_card_before_any_number():
    got = ms.card([], [_row("sunday", "2026-11-22T14:00:00Z", None)], so_far=False, when_words=_words)
    assert got["headline"].startswith("No member app timings yet") and not got["has_numbers"]


def test_the_card_without_phones_says_so():
    r = _row("manual", "2026-11-25T20:04:00Z", {"v": 1, "server": {"home": {"n": 4, "h": ms.hist([400] * 4)}}})
    got = ms.card([], [r], so_far=False, when_words=_words)
    assert got["headline"].startswith("The server answers member pages in 0.4 s typical")
    assert "No timings from phones came in." in got["headline"]


def test_card_words_never_name_the_builder():
    sunday = [_row("sunday", "2026-11-22T14:00:00Z", _reading([800] * 10, [300] * 10))]
    text = json.dumps(ms.card(sunday, sunday, so_far=True, when_words=_words)) + ms.NOTE + ms.EMPTY + ms.OFF
    for word in ("Claude", "GitHub", "p50", "p90", "median", "percentile", "replica", "TTFB"):
        assert word not in text, word
    assert "(this morning so far)" in text


# ── 7. the phone script ───────────────────────────────────────────────

def test_signed_in_pages_carry_the_script_and_sign_in_pages_dont(monkeypatch):
    signed_in = mp._shell(BUSINESS, None, "Home", "<p>x</p>", tab="home", who=dict(ME))
    door = mp._shell(BUSINESS, None, "Sign in", "<p>x</p>", door=True)
    assert "sendBeacon('/my/timing'" in signed_in and "sendBeacon" not in door
    monkeypatch.setenv("MEMBER_STOPWATCH", "off")
    assert "sendBeacon" not in mp._shell(BUSINESS, None, "Home", "<p>x</p>", tab="home", who=dict(ME))


@pytest.mark.skipif(not shutil.which("node"), reason="node isn't installed")
@pytest.mark.parametrize("nav_type, sent", [("navigate", True), ("reload", True), ("back_forward", False)])
def test_the_script_sends_the_pattern_and_two_numbers(nav_type, sent):
    js = ms._JS[len("<script>"):-len("</script>")]
    harness = """
const sent = [];
const listeners = {};
global.window = { performance: null };
// Node 21+ has a navigator of its own that plain assignment can't replace.
Object.defineProperty(globalThis, 'navigator', { configurable: true, writable: true,
  value: { sendBeacon: (url, body) => { sent.push([url, body]); return true; } } });
global.document = { readyState: 'loading', cookie: 'secret=1',
  addEventListener: (ev, fn) => { listeners[ev] = fn; } };
global.location = { pathname: '/my/messages/9b2f3c4d-1111-2222-3333-444455556666', search: '?from=push' };
global.setTimeout = (fn) => fn();
window.performance = { getEntriesByType: () => [{ type: '%s', responseStart: 212.4, domContentLoadedEventEnd: 811.6,
  activationStart: 0 }] };
%s
listeners.DOMContentLoaded();
console.log(JSON.stringify(sent));
""" % (nav_type, js)
    out = subprocess.run(["node", "-e", harness], capture_output=True, text=True, timeout=30)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    if not sent:
        assert got == []
        return
    assert len(got) == 1 and got[0][0] == "/my/timing"
    body = json.loads(got[0][1])
    assert body == {"p": "/my/messages/:id", "f": 212, "r": 812, "t": 1 if nav_type == "reload" else 0}
    assert "secret" not in got[0][1] and "push" not in got[0][1]


def test_the_app_mounts_the_stopwatch_outside_gzip():
    src = (ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8")
    adds = re.findall(r"^app\.add_middleware\(\s*(\w+)", src, flags=re.M)
    assert adds.index("MemberStopwatch") > adds.index("GZipMiddleware")
    assert adds[-1] == "NoSharedCacheForCustomDomains"
    assert src.index("include_router(member_stopwatch_router)") < src.index("include_router(public_site_router)")
