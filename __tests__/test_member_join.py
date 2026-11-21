# __tests__/test_member_join.py
#
# "New here? Join" (member_join.py): someone the church doesn't have on file
# gets into the member app by themselves. Pins:
#   1. the door: "Join here" shows on sign-in only where joining is open
#      (a church, page on, sign-in open, MEMBER_JOIN not off, the church
#      hasn't closed it); /my/join answers the form or goes back to /my
#   2. the record is made only once the right code comes back: a wrong code,
#      a pass for another address or church, a tampered or old pass, or no
#      pass at all makes nothing
#   3. nothing says who is on the list: joining with an address the church
#      has sends the ordinary code, signs in as that person and changes
#      nothing; the code page reads the same either way
#   4. the form: names, an address, US/Canada numbers only, new or already
#      coming, 13 or older; the hidden field a bot fills sends nothing
#   5. the church hears: welcome() runs with new/attend; the day's cap on
#      new records says "try again" and makes nothing

import pathlib
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_join as mj
import member_portal as mp

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
HOST = "first-light.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.setenv("RESEND_API_KEY", "test")
    monkeypatch.delenv("MEMBER_JOIN", raising=False)
    import member_cache
    member_cache.people._items.clear()


def _biz(**over):
    b = {"id": BIZ, "name": "First Light Church", "type": "church",
         "settings": {"member_portal": {"enabled": True}}, "stripe_account_id": None}
    b.update(over)
    return b


def _param(path, name):
    q = urllib.parse.parse_qs(path.split("?", 1)[1]) if "?" in path else {}
    return q.get(name, [None])[0]


class Fake:
    def __init__(self):
        self.contacts = [{"id": "c1", "business_id": BIZ, "name": "Ana Rivers", "email": "ana@example.com"}]
        self.codes = []
        self.mailed = []
        self.made = []

    def get(self, path):
        biz = (_param(path, "business_id") or "").removeprefix("eq.")
        if path.startswith("/contacts"):
            raw = (_param(path, "email") or "").removeprefix("ilike.")
            want = raw.replace("\\", "").lower()
            return [dict(c) for c in self.contacts
                    if c["business_id"] == biz and (c.get("email") or "").lower() == want]
        if path.startswith("/member_login_codes"):
            em = (_param(path, "email") or "").removeprefix("eq.")
            mine = [c for c in self.codes if c["business_id"] == biz and c["email"] == em]
            if "consumed_at=is.null" in path:
                live = [c for c in mine if c["consumed_at"] is None]
                return [dict(live[-1])] if live else []
            return [dict(c) for c in mine]
        return []

    def post(self, path, body, prefer=None):
        if path == "/contacts":
            row = {**body, "id": f"new{len(self.contacts)}"}
            self.contacts.append(row)
            self.made.append(row)
            return [row]
        row = {**body, "id": f"code{len(self.codes)}", "attempts": 0, "consumed_at": None, "succeeded": False}
        self.codes.append(row)
        return [row]

    def patch(self, path, body):
        if not path.split("?", 1)[1].startswith("id=eq."):
            biz = (_param(path, "business_id") or "").removeprefix("eq.")
            em = (_param(path, "email") or "").removeprefix("eq.")
            hit = [c for c in self.codes if c["business_id"] == biz and c["email"] == em and c["consumed_at"] is None]
            for c in hit:
                c.update(body)
            return hit
        row = next(c for c in self.codes if f"id=eq.{c['id']}" in path)
        if "attempts=eq." in path and f"attempts=eq.{row['attempts']}" not in path:
            return []
        if "consumed_at=is.null" in path and row["consumed_at"] is not None:
            return []
        row.update(body)
        return [row]


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    f.biz = _biz()
    f.welcomed = []
    f.allow = {}
    monkeypatch.setattr(mp.sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(mp.sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(mp.sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(mp.sb_clients, "sb_delete_as_service", lambda p: True)
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": f.biz, "site": {"slug": "first-light"}})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: f.allow.get(b, True))

    async def _mail(biz, email, name, code):
        f.mailed.append((email, code, name))
    monkeypatch.setattr(mp, "_send_code_email", _mail)
    monkeypatch.setattr(mj, "welcome", lambda biz, person, visit: f.welcomed.append((person["id"], visit)))
    monkeypatch.setattr(mp, "gifts_for", lambda b, c, y: [])
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    import events_rsvp_router
    monkeypatch.setattr(events_rsvp_router, "roster_modules_for", lambda b: [])
    return f


def _client():
    app = FastAPI()
    app.include_router(mp.router)

    @app.get("/my")
    async def _my(request: mp.Request):
        return await mp.serve(request, "/my")

    @app.get("/my/join")
    async def _join(request: mp.Request):
        return await mp.serve(request, "/my/join")
    return TestClient(app, base_url=f"https://{HOST}")


FORM = {"first": "Marcus", "last": "Hill", "email": "marcus@example.com", "visit": "new", "adult": "yes"}


def _token(html):
    marker = 'name="join" value="'
    i = html.index(marker) + len(marker)
    return html[i:html.index('"', i)]


def _join(c, **over):
    return c.post("/my/join", data={**FORM, **over}, headers=ORIGIN)


def _verify(c, code, token, email="marcus@example.com"):
    return c.post("/my/verify", data={"email": email, "code": code, "join": token},
                  headers=ORIGIN, follow_redirects=False)


# ─── 1. the door ─────────────────────────────────────────────────────


def test_sign_in_offers_join_where_it_is_open(fake, monkeypatch):
    c = _client()
    assert 'href="/my/join"' in c.get("/my").text
    monkeypatch.setenv("MEMBER_JOIN", "off")
    assert 'href="/my/join"' not in c.get("/my").text
    monkeypatch.delenv("MEMBER_JOIN")
    fake.biz = _biz(settings={"member_portal": {"enabled": True, "join": False}})
    assert 'href="/my/join"' not in c.get("/my").text


def test_join_page_answers_only_where_open(fake, monkeypatch):
    c = _client()
    r = c.get("/my/join", follow_redirects=False)
    assert r.status_code == 200 and 'action="/my/join"' in r.text and "13 or older" in r.text
    monkeypatch.setenv("MEMBER_JOIN", "off")
    r = c.get("/my/join", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/my"
    r = _join(c)
    assert r.status_code in (303, 200) and not fake.mailed


def test_only_churches_take_joiners(fake):
    assert mj.join_open(_biz())
    assert not mj.join_open(_biz(type="nonprofit"))


def test_paused_sign_in_takes_no_joiners(fake):
    fake.biz = _biz(settings={"member_portal": {"enabled": True, "sign_in": False}})
    r = _join(_client())
    assert "paused" in r.text.lower() and not fake.mailed


# ─── 2. the record waits for the right code ──────────────────────────


def test_a_new_person_joins_with_the_right_code(fake):
    c = _client()
    r = _join(c)
    assert r.status_code == 200 and "on its way to" in r.text
    assert fake.mailed and fake.mailed[-1][0] == "marcus@example.com" and fake.mailed[-1][2] == "Marcus Hill"
    assert not fake.made                                   # nothing made before the code
    r = _verify(c, fake.mailed[-1][1], _token(r.text))
    assert r.status_code == 303 and r.headers["location"] == "/my"
    assert r.headers["set-cookie"].lower().startswith("__host-sol_member=")
    assert len(fake.made) == 1
    row = fake.made[0]
    assert row["name"] == "Marcus Hill" and row["email"] == "marcus@example.com"
    assert row["status"] == "lead" and row["source"] == mj.SOURCE and mj.JOINED_TAG in row["tags"]
    assert fake.welcomed == [(row["id"], "new")]
    home = c.get("/my")
    assert "Marcus" in home.text


def test_already_coming_is_handed_on_as_such(fake):
    c = _client()
    r = _join(c, visit="attend")
    _verify(c, fake.mailed[-1][1], _token(r.text))
    assert fake.welcomed and fake.welcomed[0][1] == "attend"


def test_a_wrong_code_makes_nothing(fake):
    c = _client()
    r = _join(c)
    code = fake.mailed[-1][1]
    wrong = "000000" if code != "000000" else "111111"
    r2 = _verify(c, wrong, _token(r.text))
    assert r2.status_code == 400 and not fake.made and not fake.welcomed
    assert 'name="join"' in r2.text                        # can still try the right one


def test_no_pass_makes_nothing(fake):
    c = _client()
    _join(c)
    r = c.post("/my/verify", data={"email": "marcus@example.com", "code": fake.mailed[-1][1]},
               headers=ORIGIN, follow_redirects=False)
    assert r.status_code == 400 and not fake.made


def test_a_pass_is_bound_to_its_address_and_church():
    vals = {"first": "Marcus", "last": "Hill", "ident": "marcus@example.com", "visit": "new"}
    t = mj.mint_pass(BIZ, vals)
    assert mj.read_pass(t, BIZ, "Marcus@Example.com")["first"] == "Marcus"
    assert mj.read_pass(t, BIZ, "someone@example.com") is None
    assert mj.read_pass(t, OTHER, "marcus@example.com") is None
    payload, sig = t.split(".")
    assert mj.read_pass(payload + "." + ("A" if sig[0] != "A" else "B") + sig[1:], BIZ, "marcus@example.com") is None
    old = mj.mint_pass(BIZ, vals, now=int(time.time()) - mj.PASS_SECONDS - 5)
    assert mj.read_pass(old, BIZ, "marcus@example.com") is None
    assert mj.read_pass("garbage", BIZ, "marcus@example.com") is None
    # a member-session token is not a pass
    assert mj.read_pass(mp.mint_session(BIZ, "marcus@example.com", "c1"), BIZ, "marcus@example.com") is None


def test_the_days_cap_on_new_records_makes_nothing(fake):
    c = _client()
    r = _join(c)
    fake.allow["member_join_made_day"] = False
    r = _verify(c, fake.mailed[-1][1], _token(r.text))
    assert r.status_code == 503 and not fake.made


def test_the_days_cap_on_codes_to_new_addresses_sends_nothing(fake):
    fake.allow["member_join_sent_day"] = False
    _join(_client())
    assert not fake.mailed


# ─── 3. nothing says who is on the list ──────────────────────────────


def test_joining_with_a_known_address_signs_in_as_that_person(fake):
    c = _client()
    known = _join(c, email="ana@example.com")
    assert fake.mailed[-1][0] == "ana@example.com" and fake.mailed[-1][2] == "Ana Rivers"
    r = _verify(c, fake.mailed[-1][1], _token(known.text), email="ana@example.com")
    assert r.status_code == 303 and not fake.made and not fake.welcomed
    assert fake.contacts[0]["name"] == "Ana Rivers"
    assert "Ana" in c.get("/my").text


def test_the_code_page_reads_the_same_for_known_and_new(fake):
    c = _client()
    known = _join(c, email="ana@example.com")
    new = _join(c, email="marcus@example.com")
    strip = lambda r, e: r.text.replace(e, "EMAIL").replace(_token(r.text), "TOKEN")
    assert known.status_code == new.status_code == 200
    assert strip(known, "ana@example.com") == strip(new, "marcus@example.com")


# ─── 4. the form ─────────────────────────────────────────────────────


@pytest.mark.parametrize("over,words", [
    ({"first": ""}, "first and last name"),
    ({"last": "http://spam.example"}, "first and last name"),
    ({"email": "not an address"}, "email or mobile number"),
    ({"email": "+44 20 7946 0958"}, "US or Canadian"),
    ({"visit": ""}, "new here or already come"),
    ({"adult": ""}, "13 or older"),
])
def test_the_form_refuses_what_is_missing(fake, over, words):
    r = _join(_client(), **over)
    assert r.status_code == 400 and words in r.text and not fake.mailed


def test_a_us_mobile_number_is_taken():
    vals, err = mj.clean({**FORM, "email": "(555) 010-2030"})
    assert err == "" and vals["ident"] == "+15550102030"


def test_the_bot_field_sends_nothing(fake):
    r = _join(_client(), website="http://spam.example")
    assert r.status_code == 200 and "on its way" in r.text and not fake.mailed


def test_a_cross_site_join_is_refused(fake):
    r = _client().post("/my/join", data=FORM, headers={"origin": "https://evil.example"})
    assert r.status_code == 403 and not fake.mailed
