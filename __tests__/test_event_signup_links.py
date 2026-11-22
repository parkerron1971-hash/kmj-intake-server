"""An event's sign-up link (event_signup_links.py; docs/EVENT_SIGNUP_LINKS.md).
Kevin, 2026-11-22: "when the event is made there is no way for someone to sign
up with a link if there don't have the church app", then "yes to both".

Pins, each one broken on purpose once to see its test go red:
  * the code: 26 base32 characters from a keyed hash, never in the entry's
    data, never the same for another event or another key; a new link voids
    the old one; every candidate is compared with hmac.compare_digest, with no
    early exit; a wrong code is the same 404 as a missing, past or archived
    event, a sample church and a closed switch
  * church-only and invite events only by their code; a public event also by
    its own page, which shows only that event
  * a kids role is refused whatever is posted; a full role says so
  * a name and a phone or an email, normalized; via "link"; never a contact
    from what was typed
  * no hours until the office confirms, then counted; confirm only with this
    church's person
  * every office route's gate: a Viewer, another church, signed out
  * the switch off, owner and on; the rate limit first; the honeypot; no other
    names on the page; noindex; the email once"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import hmac
import json
import os
import re
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
for p in (ROOT, HERE):
    if p not in sys.path:
        sys.path.insert(0, p)

import church_serving as cs  # noqa: E402
import event_signup_links as esl  # noqa: E402
import events_rsvp_router as er  # noqa: E402
import member_asks  # noqa: E402
import sample_church  # noqa: E402
from auth_supabase import require_user  # noqa: E402
from test_event_volunteers import BIZ, E_LOCK, E_PAST, E_THEIRS, MOD, NOW, OTHER, PEOPLE, church  # noqa: E402,F401
from test_event_volunteers_roles_hours import hours, mine  # noqa: E402,F401
from test_sunday_planning import ANA, ELSEWHERE, JO  # noqa: E402

E_PUB, E_PRIV, E_INV, E_GONE = (f"e7000000-0000-4000-8000-{n:012d}" for n in range(1, 5))
SLUG = "lovecity"
SECRET = "a-made-up-root-for-tests"
REAL_MAIL = esl._mail


def _entry(eid, data, status="active", biz=BIZ):
    return {"id": eid, "business_id": biz, "module_id": MOD, "status": status, "data": data,
            "created_at": NOW.isoformat(), "updated_at": "2026-10-01T00:00:00+00:00"}


ROLES = [{"id": "drive", "label": "Drivers", "needed": 2, "open": False},
         {"id": "kitchen", "label": "Kitchen crew", "needed": 1},
         {"id": "cabin", "label": "Cabin leaders", "needed": 4, "kids": True}]


@pytest.fixture
def links(church, monkeypatch):
    c = church
    db = c.db
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", SECRET)
    monkeypatch.setenv("EVENT_SIGNUP_LINKS", "on")
    monkeypatch.setenv("RATE_LIMIT_SHARED", "off")
    import rate_limit
    rate_limit._buckets.clear()
    db.t["business_sites"] = [{"id": "s1", "business_id": BIZ, "slug": SLUG, "status": "published",
                               "html_content": "", "site_config": {}, "updated_at": NOW.isoformat()}]
    db.t.setdefault("events", [])
    db.t["module_entries"] += [
        _entry(E_PUB, {"title": "Fall Retreat", "date": "2026-12-02T17:00", "location": "Camp Wildwood",
                       "_roles": copy.deepcopy(ROLES),
                       "signups": [{"name": "Marcus Hill", "role": "drive", "status": "yes"},
                                   {"name": "Ruth Okafor", "status": "yes"}]}),
        _entry(E_PRIV, {"title": "Leaders dinner", "date": "2026-11-05T18:30", "location": "The hall",
                        "_visibility": "private", "_roles": copy.deepcopy(ROLES), "signups": []}),
        _entry(E_INV, {"title": "Planning lunch", "date": "2026-11-07T12:00", "_visibility": "invite",
                       "_roles": copy.deepcopy(ROLES), "signups": []}),
        _entry(E_GONE, {"title": "Old picnic", "date": "2026-11-20T12:00", "_roles": [], "signups": []},
               status="archived"),
    ]
    for e in db.t["module_entries"]:
        e.setdefault("updated_at", "2026-10-01T00:00:00+00:00")
    # zz_module_revision: every write moves updated_at on.
    plain_patch = db.patch
    tick = {"n": 0}

    def patch(path, body):
        got = plain_patch(path, body)
        if path.lstrip("/").startswith("module_entries"):
            for g in got:
                tick["n"] += 1
                row = next(r for r in db.t["module_entries"] if r["id"] == g["id"])
                row["updated_at"] = f"2026-10-21T15:00:{tick['n']:02d}.000001+00:00"
                g["updated_at"] = row["updated_at"]
        return got
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", patch)
    db.patch = patch
    # PostgREST's limit, which the fake database ignores.
    plain_get = db.get

    def get(path, **k):
        got = plain_get(path, **k)
        m = re.search(r"[?&]limit=(\d+)", path)
        return got[:int(m.group(1))] if m and isinstance(got, list) else got
    monkeypatch.setattr(sb_clients, "sb_get_as_service", get)
    db.get = get
    # Who reads Members as the roll does: the owner, an Admin and Laquesha.
    import church_roll
    monkeypatch.setattr(church_roll, "_areas_ok", lambda b, uid, role: role in ("owner", "admin") or uid == "u-laquesha")
    monkeypatch.setattr(sample_church, "is_sample", lambda b: False)
    er._rsvp_rate.clear()
    mails = []
    monkeypatch.setattr(esl, "_mail", lambda m: mails.append(m))
    who = {"user": PEOPLE["owner"]}
    app = FastAPI()
    app.include_router(esl.router)
    app.include_router(er.router)
    app.dependency_overrides[require_user] = lambda: who["user"]
    client = TestClient(app)

    def as_(name):
        who["user"] = PEOPLE[name]
        return client
    bare = FastAPI()
    bare.include_router(esl.router)
    return types.SimpleNamespace(c=c, db=db, as_=as_, client=client, mails=mails, anon=TestClient(bare))


def row(L, eid):
    return next(e for e in L.db.t["module_entries"] if e["id"] == eid)


def link(L, eid, who="owner"):
    r = L.as_(who).get(f"/church/event-links/{eid}", params={"business_id": BIZ})
    assert r.status_code == 200, r.text
    return r.json()


def code_of(L, eid):
    """The link's token, <entry_id>.<code>, as the office was given it."""
    return link(L, eid)["url"].rsplit("/e/", 1)[1]


def page(code, biz=BIZ, ip="203.0.113.7"):
    church = esl.church_row(biz)
    got = asyncio.run(esl.serve_page(church, code, ip=ip, api_origin="https://api.test",
                                     headers={"Cache-Control": "no-store"}))
    return got.status_code, got.body.decode(), dict(got.headers)


def sign(L, code, **kw):
    body = {"code": code, "name": "Dee Carter", "reach": "(616) 555-0142", **kw}
    return L.client.post("/public/event-link", json=body)


def mac_of(token):
    return token.split(".", 1)[1]


# ─── the code ────────────────────────────────────────────────────────

def test_a_link_is_a_long_keyed_code_never_stored(links):
    L = links
    out = link(L, E_PRIV)
    assert out["url"].startswith(f"https://{SLUG}.mysolutionist.app/e/{E_PRIV}.")
    token = out["url"].rsplit("/e/", 1)[1]
    assert esl.clean_token(token) == (E_PRIV, mac_of(token))
    code = mac_of(token)
    assert re.fullmatch(r"[a-z2-7]{26}", code), "130 bits, a-z2-7"
    data = row(L, E_PRIV)["data"]
    assert esl.link_of(data) and code not in json.dumps(data), "the row holds the nonce, never the code"
    assert code not in E_PRIV.replace("-", "")
    n = data["_link"]["n"]
    other = mac_of(code_of(L, E_INV))
    assert other != code, "another event, another code"
    assert esl.code_for(BIZ, E_PRIV, n) == code
    os.environ["CUSTOMER_TOKEN_SECRET"] = "another-root"
    try:
        assert esl.code_for(BIZ, E_PRIV, n) != code, "keyed: nobody without the server's key can work it out"
    finally:
        os.environ["CUSTOMER_TOKEN_SECRET"] = SECRET
    assert esl.code_for(OTHER, E_PRIV, n) != code, "each church its own key"
    assert link(L, E_PRIV)["url"] == out["url"], "asking again gives the same link"
    assert out["taking"] is True
    row(L, E_PRIV)["data"]["date"] = "2026-10-01T18:00"
    assert link(L, E_PRIV)["taking"] is False, "past: the office is told it isn't taking sign-ups"


def test_a_new_link_voids_the_old_one(links):
    L = links
    old = code_of(L, E_PRIV)
    assert page(old)[0] == 200
    r = L.as_("admin").post(f"/church/event-links/{E_PRIV}/new", json={"business_id": BIZ})
    assert r.status_code == 200, r.text
    new = r.json()["url"].rsplit("/e/", 1)[1]
    assert new != old and r.json()["data"]["_link"] == row(L, E_PRIV)["data"]["_link"]
    assert page(old)[0] == 404 and sign(L, old).status_code == 404
    assert page(new)[0] == 200 and sign(L, new).status_code == 200


def test_the_code_is_compared_in_constant_time(links, monkeypatch):
    L = links
    token = code_of(L, E_PUB)
    seen = []
    real = hmac.compare_digest

    def spy(a, b):
        seen.append((a, b))
        return real(a, b)
    monkeypatch.setattr(esl.hmac, "compare_digest", spy)
    assert esl.find_by_token(esl.clean_token(token))[0]["id"] == E_PUB
    assert esl.find_by_token((E_PUB, "a" * 26)) is None
    assert [b for _, b in seen] == [mac_of(token), "a" * 26], "every code through compare_digest"


def test_one_row_is_read_however_many_events_the_church_has(links, monkeypatch):
    """The link names its event: a church with years of events (more than one
    read's 200) finds its newest one's link."""
    L = links
    token = code_of(L, E_PRIV)
    older = [_entry(f"e8000000-0000-4000-8000-{n:012d}", {"title": f"Old {n}", "date": "2025-01-01T10:00",
                                                          "_link": esl.new_link()}) for n in range(300)]
    i = next(k for k, e in enumerate(L.db.t["module_entries"]) if e["id"] == E_PRIV)
    L.db.t["module_entries"][i:i] = older            # 300 events ahead of it
    reads = []
    import sb_clients
    plain = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: reads.append(p) or plain(p, **k))
    assert page(token)[0] == 200 and sign(L, token).status_code == 200
    entry_reads = [r for r in reads if r.startswith("/module_entries")]
    assert entry_reads and all(f"id=eq.{E_PRIV}" in r for r in entry_reads), "only its own row"


def test_a_wrong_code_is_the_same_404_as_a_missing_past_or_archived_event(links, monkeypatch):
    L = links
    code = code_of(L, E_PRIV)
    mac = mac_of(code)
    wrong = (f"{E_PRIV}.{'a' * 26}", "short", "a" * 26, "", f"{E_PRIV}.{mac[:-1]}{'b' if mac[-1] != 'b' else 'c'}",
             f"{E_INV}.{mac}", f"{E_THEIRS}.{mac}", f"e9999999-0000-4000-8000-000000000000.{mac}")
    pages = {page(w)[1] for w in wrong}
    statuses = {page(w)[0] for w in wrong}
    # The archived event, and a past one, with real links of their own.
    gone = row(L, E_GONE)
    gone["data"]["_link"] = esl.new_link()
    gone_code = esl.token_for(BIZ, E_GONE, gone["data"]["_link"]["n"])
    past = row(L, E_PAST)
    past["data"]["_link"] = esl.new_link()
    past_code = esl.token_for(BIZ, E_PAST, past["data"]["_link"]["n"])
    for c in (gone_code, past_code):
        s, html, _ = page(c)
        statuses.add(s)
        pages.add(html)
    assert statuses == {404} and len(pages) == 1, "one page for every way of not taking sign-ups"
    assert esl._e(esl.NOT_TAKING) in pages.pop()
    mod = L.db.t["custom_modules"][0]
    assert esl.event_view(BIZ, gone, mod) is None, "archived, whoever reads it"
    assert esl.event_view(BIZ, row(L, E_PRIV), {**mod, "is_active": False}) is None, "its room off"
    assert esl.event_view(BIZ, row(L, E_PRIV), mod) is not None
    answers = {(r.status_code, r.json()["detail"]) for r in (sign(L, w) for w in (*wrong[:2], gone_code, past_code))}
    assert answers == {(404, esl.NOT_TAKING)}


# ─── which events ────────────────────────────────────────────────────

def _events_page(L, monkeypatch, query=""):
    import public_site
    import church_event_signups

    async def service(client, path):
        return L.db.get(path)
    monkeypatch.setattr(public_site, "_sb_service", service)
    monkeypatch.setattr(church_event_signups, "annotate", lambda biz, occ, contact_id=None: occ)
    L.db.t["businesses"][0]["settings"] = {"events_public": {"enabled": True}}
    return asyncio.run(public_site._serve_events_page(None, BIZ, SLUG, query=query)).body.decode()


def test_church_only_and_invite_events_only_by_their_code(links, monkeypatch):
    L = links
    for eid, title in ((E_PRIV, "Leaders dinner"), (E_INV, "Planning lunch")):
        assert title not in _events_page(L, monkeypatch), "never on the public list"
        assert title not in _events_page(L, monkeypatch, f"event={eid}"), "nor its own public page"
        assert L.client.post(f"/public/events/{SLUG}/rsvp", json={
            "entry_id": eid, "name": "Dee", "email": "dee@example.org"}).status_code == 404
        s, html, _ = page(code_of(L, eid))
        assert s == 200 and title in html, "the link opens it"


def test_a_public_events_own_page_shows_only_it(links, monkeypatch):
    L = links
    from datetime import date, timedelta
    # The public page counts from the real day; the link's page from NOW.
    row(L, E_PUB)["data"]["date"] = (date.today() + timedelta(days=10)).isoformat() + "T17:00"
    row(L, E_LOCK)["data"]["date"] = (date.today() + timedelta(days=12)).isoformat() + "T18:00"
    full = _events_page(L, monkeypatch)
    assert "Fall Retreat" in full and "Youth Lock-in" in full
    one = _events_page(L, monkeypatch, f"event={E_PUB}")
    assert "Fall Retreat" in one and "Youth Lock-in" not in one, "only that event"
    assert "See everything coming up" in one and f'rel="canonical" href="https://{SLUG}.mysolutionist.app/events?event={E_PUB}"' in one
    assert "Drivers" not in one, "the public page's rules: open: false stays in the church"
    s, html, _ = page(code_of(L, E_PUB))
    assert s == 200 and "Drivers" in html and "Kitchen crew" in html, "the link takes every role that isn't a kids role"
    got = link(L, E_PUB)
    assert got["page_url"] == f"https://{SLUG}.mysolutionist.app/events?event={E_PUB}" and got["visibility"] == "public"
    assert link(L, E_PRIV)["page_url"] is None


def test_the_page_is_noindex_shows_counts_and_never_names(links):
    L = links
    s, html, hdrs = page(code_of(L, E_PUB))
    assert '<meta name="robots" content="noindex,nofollow">' in html and hdrs["x-robots-tag"] == "noindex, nofollow"
    assert hdrs["referrer-policy"] == "strict-origin" and hdrs["cache-control"] == "no-store"
    assert "Marcus Hill" not in html and "Ruth Okafor" not in html, "counts only"
    assert "1 needed" in html, "Drivers: 2 needed, Marcus on one"
    assert "Camp Wildwood" in html and "Wednesday, December 2 · 5:00 PM" in html
    assert 'name="website"' in html and "sl-hp" in html, "the honeypot"
    assert "Just coming" in html


# ─── signing up ──────────────────────────────────────────────────────

def test_a_kids_role_is_never_on_the_page_and_refused_whatever_is_posted(links):
    L = links
    code = code_of(L, E_PUB)
    s, html, _ = page(code)
    assert "Cabin leaders" not in html and 'value="cabin"' not in html, "a shared link is as good as public"
    before = copy.deepcopy(row(L, E_PUB)["data"]["signups"])
    r = sign(L, code, role="cabin")
    assert (r.status_code, r.json()["detail"]) == (400, esl.NO_ROLE), "the same as a role that isn't there"
    assert row(L, E_PUB)["data"]["signups"] == before and not L.mails


def test_a_full_role_says_so(links):
    L = links
    code = code_of(L, E_PUB)
    assert sign(L, code, role="kitchen", reach="pat@example.org", name="Pat Doe").status_code == 200
    r = sign(L, code, role="kitchen", reach="sam@example.org", name="Sam Roe")
    assert (r.status_code, r.json()["detail"]) == (409, "Kitchen crew just filled up.")
    assert ">Full<" in page(code)[1]
    assert sign(L, code, role="nope").status_code == 400
    row(L, E_PUB)["data"]["capacity"] = 3
    r = sign(L, code, reach="kim@example.org", name="Kim Lo")
    assert (r.status_code, r.json()["detail"]) == (409, esl.FULL), "Ruth, Marcus and Pat: three of three"


@pytest.mark.parametrize("reach,want", [("(616) 555-0142", ("phone", "+16165550142")),
                                        ("1-616-555-0142", ("phone", "+16165550142")),
                                        ("+44 20 7946 0958", ("phone", "+442079460958")),
                                        (" Dee@Example.org ", ("email", "dee@example.org"))])
def test_a_phone_or_an_email_normalized(reach, want):
    assert esl.clean_reach(reach) == want


@pytest.mark.parametrize("body,code,words", [
    ({"name": ""}, 400, esl.NO_NAME), ({"reach": ""}, 400, esl.NO_REACH),
    ({"reach": "dee@nowhere"}, 400, esl.BAD_EMAIL), ({"reach": "555-01"}, 400, esl.BAD_PHONE),
    ({"reach": "call me maybe"}, 400, esl.BAD_PHONE), ({"reach": "+1234"}, 400, esl.BAD_PHONE)])
def test_a_name_and_a_phone_or_an_email(links, body, code, words):
    L = links
    r = sign(L, code_of(L, E_PUB), **body)
    assert (r.status_code, r.json()["detail"]) == (code, words)


def test_a_sign_up_is_via_link_and_never_a_contact_from_what_was_typed(links):
    L = links
    next(p for p in L.db.t["contacts"] if p["id"] == ANA)["email"] = "ana@example.org"
    r = sign(L, code_of(L, E_PRIV), name="Ana Cruz", reach="Ana@Example.org", role="drive")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "role": "Drivers", "when": "Thursday, November 5 · 6:30 PM",
                        "place": "The hall"}
    s = row(L, E_PRIV)["data"]["signups"][-1]
    assert s["via"] == "link" and s["email"] == "ana@example.org" and s["role"] == "drive"
    assert "contact_id" not in s and esl.SID_RE.fullmatch(s["sid"])
    assert not row(L, E_PRIV)["data"].get("_registration_keys")
    r = sign(L, code_of(L, E_PRIV), name="Jo Park")
    assert r.status_code == 200 and "role" not in row(L, E_PRIV)["data"]["signups"][-1], "just coming"


def test_the_email_goes_once_and_only_when_one_was_given(links):
    L = links
    code = code_of(L, E_PRIV)
    first = sign(L, code, reach="dee@example.org", role="drive")
    r = sign(L, code, reach="DEE@example.org", role="drive")
    assert r.status_code == first.status_code == 200 and r.json() == first.json(), \
        "already on the list: the same answer, so nobody learns who signed up"
    import hashlib as _h
    row(L, E_PRIV)["data"]["_registration_keys"] = {_h.sha256(f"{BIZ}:{E_PRIV}:sam@example.org".encode()).hexdigest(): True}
    a = sign(L, code, reach="sam@example.org", role="drive", name="Sam Roe")
    b = sign(L, code, reach="kim@example.org", role="drive", name="Kim Lo")
    assert a.status_code == b.status_code and a.json() == b.json(), "a public registration reads the same as a new one"
    assert len(row(L, E_PRIV)["data"]["signups"]) == 2, "Dee once, Kim; nothing written twice"
    assert [m["to"] for m in L.mails] == ["dee@example.org", "kim@example.org"]
    del row(L, E_PRIV)["data"]["_registration_keys"]
    m = L.mails[0]
    sid = row(L, E_PRIV)["data"]["signups"][0]["sid"]
    assert m["to"] == "dee@example.org" and m["key"] == f"evlink-{E_PRIV}-{sid}" and m["biz"] == BIZ
    subject, body = esl.email_words(m)
    assert subject == "You're on the list for Leaders dinner"
    assert "Drivers · Thursday, November 5 · 6:30 PM · The hall" in body and "Love City Church" in body
    assert sign(L, code, reach="(616) 555-0142", name="Pat Doe").status_code == 200
    assert len(L.mails) == 2, "a phone gets no email, and no text (spec 7)"


def test_the_church_sender_is_the_one_used(monkeypatch):
    import church_event_signups as ces
    sent = []

    async def send(biz, to, name, subject, body, key):
        sent.append((biz, to, subject, key))
    monkeypatch.setattr(ces, "_send_email", send)
    monkeypatch.setattr(ces, "_run", lambda coro: asyncio.run(coro))
    REAL_MAIL({"biz": BIZ, "church": "Love City Church", "to": "dee@example.org", "name": "Dee Carter",
               "key": "evlink-x-y", "said": {"role": "Coming", "when": "Thursday", "place": "", "title": "Leaders dinner"}})
    assert sent == [(BIZ, "dee@example.org", "You're on the list for Leaders dinner", "evlink-x-y")]


def test_the_honeypot_writes_nothing_and_says_the_same(links):
    L = links
    code = code_of(L, E_PRIV)
    r = sign(L, code, website="http://spam.example", reach="bot@example.org")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert row(L, E_PRIV)["data"]["signups"] == [] and not L.mails


def test_the_rate_limit_comes_first(links, monkeypatch):
    L = links
    reads = []
    import sb_clients
    plain = sb_clients.sb_get_as_service
    monkeypatch.setattr(sb_clients, "sb_get_as_service", lambda p, **k: reads.append(p) or plain(p, **k))
    monkeypatch.setattr(er, "_check_rsvp_rate", lambda ip: False)
    r = sign(L, "a" * 26)
    assert r.status_code == 429 and reads == [], "before any read"


def test_the_same_limit_as_the_public_rsvp(links):
    L = links
    code = code_of(L, E_PRIV)
    got = [sign(L, code, name=f"Person {i}", reach=f"p{i}@example.org").status_code for i in range(er.RSVP_RATE_MAX_PER_MIN + 1)]
    assert got[:-1] == [200] * er.RSVP_RATE_MAX_PER_MIN and got[-1] == 429


def test_a_sample_church_takes_none(links, monkeypatch):
    L = links
    code = code_of(L, E_PRIV)
    monkeypatch.setattr(sample_church, "is_sample", lambda b: b == BIZ)
    assert page(code)[0] == 404
    assert (sign(L, code).status_code, sign(L, code).json()["detail"]) == (404, esl.NOT_TAKING)


def test_a_church_without_events_rooms_or_blocked_rsvp(links, monkeypatch):
    L = links
    code = code_of(L, E_PUB)
    import church_event_signups
    monkeypatch.setattr(church_event_signups, "blocks_free_rsvp", lambda b, e: True)
    assert "Just coming" not in page(code)[1]
    r = sign(L, code)
    assert (r.status_code, r.json()["detail"]) == (409, esl.TAKES_SIGNUPS)
    assert sign(L, code, role="kitchen").status_code == 200, "a role still works"


# ─── the switch ──────────────────────────────────────────────────────

def test_the_switch_off_owner_and_on(links, monkeypatch):
    L = links
    code = code_of(L, E_PRIV)
    monkeypatch.setenv("EVENT_SIGNUP_LINKS", "off")
    assert page(code)[0] == 404 and sign(L, code).status_code == 404
    assert L.as_("owner").get(f"/church/event-links/{E_PRIV}", params={"business_id": BIZ}).status_code == 404
    assert L.as_("owner").get("/church/event-links/status", params={"business_id": BIZ}).json()["enabled"] is False
    monkeypatch.delenv("EVENT_SIGNUP_LINKS")
    assert esl.mode() == "on", "on when unset: every church (Kevin, 2026-11-22)"
    assert page(code)[0] == 200
    monkeypatch.setenv("EVENT_SIGNUP_LINKS", "owner")
    assert page(code)[0] == 404, "owner: not the platform owner's church"
    assert L.as_("owner").get("/church/event-links/status", params={"business_id": BIZ}).json()["enabled"] is False, \
        "owner means the church, never who is signed in"
    monkeypatch.setattr(member_asks, "platform_church", lambda b: b == BIZ)
    assert page(code)[0] == 200 and sign(L, code).status_code == 200
    assert L.as_("admin").get("/church/event-links/status", params={"business_id": BIZ}).json() == {
        "enabled": True, "can_change": True}
    monkeypatch.setenv("EVENT_SIGNUP_LINKS", "typo")
    assert page(code)[0] == 404
    monkeypatch.setenv("EVENT_SIGNUP_LINKS", "on")
    monkeypatch.setenv("EVENT_VOLUNTEERS", "off")
    assert page(code)[0] == 404, "only where EVENT_VOLUNTEERS is open"
    monkeypatch.setenv("EVENT_VOLUNTEERS", "on")
    assert len(row(L, E_PRIV)["data"]["signups"]) == 1, "closed, what was made stays"


def test_no_key_is_a_503_and_never_a_link(links, monkeypatch):
    L = links
    monkeypatch.delenv("CUSTOMER_TOKEN_SECRET")
    r = L.as_("owner").get(f"/church/event-links/{E_PRIV}", params={"business_id": BIZ})
    assert (r.status_code, r.json()["detail"]) == (503, esl.NOT_READY)
    assert "_link" not in row(L, E_PRIV)["data"]
    assert page(f"{E_PRIV}.{'a' * 26}")[0] == 404


# ─── the office ──────────────────────────────────────────────────────

ROUTES = [("get", "/church/event-links/{e}", None), ("post", "/church/event-links/{e}/new", {}),
          ("post", "/church/event-links/{e}/signups/{s}/confirm", {"contact_id": ANA}),
          ("post", "/church/event-links/{e}/signups/{s}/add", {}),
          ("delete", "/church/event-links/{e}/signups/{s}", None)]


def _call(client, method, path, body, biz=BIZ, eid=E_PRIV, sid="0" * 16):
    url = path.format(e=eid, s=sid)
    if body is None:
        return getattr(client, method)(url, params={"business_id": biz})
    return client.post(url, json={"business_id": biz, **body})


def test_every_office_route_refuses_the_signed_out_another_church_and_a_viewer(links):
    L = links
    for method, path, body in ROUTES:
        assert _call(L.anon, method, path, body).status_code == 401, path
        assert _call(L.as_("stranger"), method, path, body).status_code == 404, ("no seat here", path)
        assert _call(L.as_("owner"), method, path, body, eid=E_THEIRS).status_code == 404, ("their event", path)
        assert _call(L.as_("owner"), method, path, body, biz=OTHER).status_code == 404, ("their church", path)
        assert _call(L.as_("outsider"), method, path, body).status_code == 403, ("not the office", path)
        want = 200 if method == "get" else 403
        assert _call(L.as_("viewer"), method, path, body).status_code == want, ("a Viewer reads", path)
    assert "_link" not in row(L, E_PRIV)["data"], "a Viewer's read never makes one"
    assert link(L, E_PRIV, "viewer")["url"] is None
    made = link(L, E_PRIV)["url"]
    assert link(L, E_PRIV, "viewer")["url"] == made and link(L, E_PRIV, "viewer")["can_change"] is False


def _signed(L, eid=E_PRIV, **kw):
    assert sign(L, code_of(L, eid), **kw).status_code == 200
    return row(L, eid)["data"]["signups"][-1]["sid"]


def test_the_office_sees_reach_only_where_it_reads_members(links):
    L = links
    next(p for p in L.db.t["contacts"] if p["id"] == ANA)["phone"] = "+16165550142"
    sid = _signed(L, name="Ana Cruz", role="kitchen")
    got = link(L, E_PRIV)["signups"]
    assert got == [{"sid": sid, "name": "Ana Cruz", "role_id": "kitchen", "role": "Kitchen crew",
                    "at": got[0]["at"], "confirmed": False, "phone": "+16165550142",
                    "maybe": {"contact_id": ANA, "name": "Ana Cruz"}}]
    for who in ("viewer", "shapretta"):
        seen = link(L, E_PRIV, who)["signups"][0]
        assert "phone" not in seen and "maybe" not in seen and seen["name"] == "Ana Cruz", who
    r = L.as_("shapretta").post(f"/church/event-links/{E_PRIV}/signups/{sid}/confirm",
                                json={"business_id": BIZ, "contact_id": ANA})
    assert (r.status_code, r.json()["detail"]) == (403, esl.CONFIRM_ONLY), "confirming follows the same rule"


def test_confirm_only_with_this_churchs_person(links):
    L = links
    sid = _signed(L, name="Dee Carter", role="kitchen")
    base = f"/church/event-links/{E_PRIV}/signups/{sid}/confirm"
    r = L.as_("laquesha").post(base, json={"business_id": BIZ, "contact_id": ELSEWHERE})
    assert (r.status_code, r.json()["detail"]) == (404, esl.NOT_MEMBER), "another church's person"
    assert L.as_("laquesha").post(base, json={"business_id": BIZ, "contact_id": "nope"}).status_code == 400
    s = row(L, E_PRIV)["data"]["signups"][-1]
    assert "contact_id" not in s and s.get("confirmed") is not True
    r = L.as_("laquesha").post(base, json={"business_id": BIZ, "contact_id": ANA})
    assert r.status_code == 200, r.text
    s = row(L, E_PRIV)["data"]["signups"][-1]
    assert (s["contact_id"], s["confirmed"], s["name"], s["typed_name"], s["confirmed_by"]) == (
        ANA, True, "Ana Cruz", "Dee Carter", "u-laquesha")
    assert r.json()["data"] == row(L, E_PRIV)["data"] and r.json()["updated_at"] == row(L, E_PRIV)["updated_at"]
    r = L.as_("laquesha").post(base, json={"business_id": BIZ, "contact_id": JO})
    assert r.status_code == 409, "already confirmed as someone else"
    bad = L.as_("laquesha").post(f"/church/event-links/{E_PRIV}/signups/{'f' * 16}/confirm",
                                 json={"business_id": BIZ, "contact_id": ANA})
    assert (bad.status_code, bad.json()["detail"]) == (404, esl.GONE_SIGNUP)


def test_add_to_members_makes_a_guest_and_confirms(links):
    L = links
    sid = _signed(L, name="Dee Carter", reach="dee@example.org", role="drive")
    r = L.as_("owner").post(f"/church/event-links/{E_PRIV}/signups/{sid}/add", json={"business_id": BIZ})
    assert r.status_code == 200, r.text
    made = next(p for p in L.db.t["contacts"] if p["id"] == r.json()["contact_id"])
    assert (made["name"], made["email"], made["status"], made["business_id"]) == ("Dee Carter", "dee@example.org",
                                                                                   "lead", BIZ)
    assert made["metadata"]["found_us"] == "An event" and "member_confirmed" not in made["metadata"]
    s = row(L, E_PRIV)["data"]["signups"][-1]
    assert s["contact_id"] == made["id"] and s["confirmed"] is True
    again = L.as_("owner").post(f"/church/event-links/{E_PRIV}/signups/{sid}/add", json={"business_id": BIZ})
    assert again.status_code == 409 and sum(1 for p in L.db.t["contacts"] if p.get("email") == "dee@example.org") == 1


def test_remove_takes_only_that_sign_up_off(links):
    L = links
    a = _signed(L, name="Dee Carter", reach="dee@example.org")
    b = _signed(L, name="Pat Doe", reach="pat@example.org")
    r = L.as_("laquesha").delete(f"/church/event-links/{E_PRIV}/signups/{a}", params={"business_id": BIZ})
    assert r.status_code == 200, r.text
    assert [s["sid"] for s in row(L, E_PRIV)["data"]["signups"]] == [b]
    assert L.as_("laquesha").delete(f"/church/event-links/{E_PRIV}/signups/{a}",
                                    params={"business_id": BIZ}).status_code == 404


def test_an_office_save_from_before_a_new_link_is_refused(links):
    """The revision guard every office save carries (internal.tsx): a save
    made before Make a new link can't bring the old link back."""
    L = links
    old = code_of(L, E_PRIV)
    stale = copy.deepcopy(row(L, E_PRIV))
    assert L.as_("owner").post(f"/church/event-links/{E_PRIV}/new", json={"business_id": BIZ}).status_code == 200
    from urllib.parse import quote
    got = L.db.patch(f"/module_entries?id=eq.{E_PRIV}&business_id=eq.{BIZ}&updated_at=eq.{quote(stale['updated_at'])}",
                     {"data": stale["data"]})
    assert got == [] and page(old)[0] == 404


# ─── hours ───────────────────────────────────────────────────────────

def test_no_hours_until_the_office_confirms(hours, monkeypatch):
    c = hours
    walk = c.walk["data"]
    walk["signups"] = [s for s in walk["signups"] if s.get("contact_id") != ANA]
    assert mine(c, ANA)["minutes"] == 0
    s = {"sid": "a" * 16, "name": "Ana Cruz", "status": "yes", "via": "link", "role": "walk", "email": "a@example.org"}
    walk["signups"].append(s)
    assert mine(c, ANA)["minutes"] == 0, "unconfirmed: nothing"
    s["contact_id"] = ANA
    assert mine(c, ANA)["minutes"] == 0, "a contact without the office's word still counts nothing"
    s["confirmed"] = True
    import hashlib as _h
    walk["_registration_keys"] = {_h.sha256(f"{BIZ}:{E_PAST}:a@example.org".encode()).hexdigest(): True}
    next(p for p in c.db.t["contacts"] if p["id"] == ANA)["email"] = "a@example.org"
    got = mine(c, ANA)
    assert (got["minutes"], got["events"], got["event_minutes"]) == (120, 1, 120), "confirmed: the event's minutes"
    walk["_serve_minutes"] = 180
    assert mine(c, ANA)["event_minutes"] == 180
    view = cs.overview({"biz": c.biz, "checks": False, "write": True, "record": False})
    ana = next(p for p in view["people"] if p["contact_id"] == ANA)
    assert (ana["events"], ana["event_minutes"]) == (1, 180), "the Serving page's Events column"


def test_the_pages_speak_in_the_voice(links):
    import brand_voice
    L = links
    for html in (page(code_of(L, E_PUB))[1], page(f"{E_PUB}.{'a' * 26}")[1]):
        assert not list(brand_voice.offenses(html))
        assert "GitHub" not in html and "Claude" not in html


@pytest.mark.parametrize("door", ["slug", "domain"])
def test_the_church_host_serves_the_link_even_with_the_site_offline(links, monkeypatch, door):
    import public_site
    L = links
    code = code_of(L, E_PRIV)
    site = {"business_id": BIZ, "slug": SLUG, "html_content": "<p>home</p>",
            "site_config": {"offline": True, "custom_domain": "lovecity.org"}}

    async def sb(client, path):
        return [dict(site)] if path.startswith("/business_sites?") else []
    monkeypatch.setattr(public_site, "_sb", sb)
    serve = (public_site._serve_site_by_slug(SLUG, f"/e/{code}") if door == "slug"
             else public_site._serve_site_by_custom_domain("lovecity.org", f"/e/{code}/"))
    got = asyncio.run(serve)
    assert got.status_code == 200 and "Leaders dinner" in got.body.decode()
    assert got.headers["cache-control"].startswith("no-store") and got.headers["x-robots-tag"] == "noindex, nofollow"
    bad = f"/e/{E_PRIV}.{'a' * 26}"
    wrong = (public_site._serve_site_by_slug(SLUG, bad) if door == "slug"
             else public_site._serve_site_by_custom_domain("lovecity.org", bad))
    assert asyncio.run(wrong).status_code == 404
    # Another kind of business keeps its own /e/ pages: the link isn't claimed.
    L.db.t["businesses"][0]["type"] = "coach"
    other = (public_site._serve_site_by_slug(SLUG, f"/e/{code}") if door == "slug"
             else public_site._serve_site_by_custom_domain("lovecity.org", f"/e/{code}"))
    assert "Leaders dinner" not in asyncio.run(other).body.decode()


def test_the_app_mounts_the_routes_before_the_catch_all():
    import kmj_intake_automation
    paths = [getattr(r, "path", "") for r in kmj_intake_automation.app.routes]
    for p in ("/public/event-link", "/church/event-links/status", "/church/event-links/{entry_id}",
              "/church/event-links/{entry_id}/signups/{sid}/confirm"):
        assert p in paths and paths.index(p) < paths.index("/{path:path}"), p
    assert paths.index("/church/event-links/status") < paths.index("/church/event-links/{entry_id}")


# ─── the review's fixes ──────────────────────────────────────────────

def test_the_page_has_its_own_limit_per_address(links, monkeypatch):
    import rate_limit
    L = links
    token = code_of(L, E_PRIV)
    monkeypatch.setitem(rate_limit._LIMITS, "event_link_page", (2, 60))
    assert [page(token, ip="198.51.100.1")[0] for _ in range(3)] == [200, 200, 429]
    assert page(token, ip="198.51.100.2")[0] == 200, "another address is its own"


def test_an_event_takes_so_many_sign_ups_an_hour_and_at_all(links, monkeypatch):
    L = links
    token = code_of(L, E_PRIV)
    now = datetime.now(timezone.utc)
    sig = lambda n, at: {"sid": f"{n:016x}", "name": f"P {n}", "status": "yes", "via": "link",
                         "email": f"p{n}@example.org", "at": at.isoformat()}
    data = row(L, E_PRIV)["data"]
    data["signups"] = [sig(n, now - timedelta(hours=2)) for n in range(40)]
    monkeypatch.setattr(er, "_check_rsvp_rate", lambda ip: True)
    assert sign(L, token, reach="new@example.org").status_code == 200, "older ones don't count this hour"
    data = row(L, E_PRIV)["data"]
    data["signups"] += [sig(100 + n, now - timedelta(minutes=5)) for n in range(esl.EVENT_HOURLY)]
    r = sign(L, token, reach="late@example.org")
    assert (r.status_code, r.json()["detail"]) == (429, esl.CAPPED) and not any(m["to"] == "late@example.org" for m in L.mails)
    data["signups"] = [sig(n, now - timedelta(days=1)) for n in range(esl.EVENT_TOTAL)]
    r = sign(L, token, reach="more@example.org")
    assert (r.status_code, r.json()["detail"]) == (429, esl.CAPPED), "and so many at all"


def test_a_church_takes_so_many_sign_ups_and_emails_an_hour(links, monkeypatch):
    import rate_limit
    L = links
    monkeypatch.setitem(rate_limit._LIMITS, "event_link_church", (3, 3600))
    monkeypatch.setitem(rate_limit._LIMITS, "event_link_mail", (1, 3600))
    a, b = code_of(L, E_PRIV), code_of(L, E_INV)
    assert sign(L, a, reach="one@example.org").status_code == 200
    assert sign(L, b, reach="two@example.org").status_code == 200
    assert [m["to"] for m in L.mails] == ["one@example.org"], "one email an hour here; the sign-up still stands"
    assert sign(L, a, reach="three@example.org").status_code == 200
    r = sign(L, b, reach="four@example.org")
    assert (r.status_code, r.json()["detail"]) == (429, esl.CAPPED), "the church's cap, across its events"


def test_the_sign_up_needs_no_slug_its_link_names_the_church(links):
    """A church on its own domain with no subdomain row still takes sign-ups:
    the church is the event's own."""
    L = links
    token = code_of(L, E_PRIV)
    L.db.t["business_sites"] = []
    assert sign(L, token).status_code == 200
    s, html, _ = page(token)
    assert "/public/event-link'" in html and SLUG not in html.split("<script>", 1)[1]


def test_a_church_only_link_carries_a_warning(links):
    L = links
    assert link(L, E_PRIV)["warning"] == "Anyone you send this link to can sign up, even for a church-only event."
    assert link(L, E_INV)["warning"] == "Anyone you send this link to can sign up, even for an invite-only event."
    assert link(L, E_PUB)["warning"] is None


def test_an_email_on_its_way_is_held_until_it_is_sent(monkeypatch):
    import church_event_signups as ces
    held = []

    async def send(biz, to, name, subject, body, key):
        held.append(len(esl._TASKS))
    monkeypatch.setattr(ces, "_send_email", send)

    async def go():
        REAL_MAIL({"biz": BIZ, "church": "Love City Church", "to": "dee@example.org", "name": "Dee", "key": "k",
                   "said": {"role": "Coming", "when": "Thursday", "place": "", "title": "Leaders dinner"}})
        assert len(esl._TASKS) == 1, "kept, so it isn't collected half-sent"
        await asyncio.sleep(0.01)
    asyncio.run(go())
    assert held == [1] and not esl._TASKS


def test_another_churchs_link_never_opens_on_this_churchs_site(links):
    L = links
    theirs = row(L, E_THEIRS)
    L.db.t["custom_modules"].append({"id": "57575757-5757-4575-8575-575757575757", "business_id": OTHER,
                                     "archetype": "event_roster", "is_active": True, "archetype_params": {}})
    theirs["module_id"] = "57575757-5757-4575-8575-575757575757"
    theirs["data"]["_link"] = esl.new_link()
    token = esl.token_for(OTHER, E_THEIRS, theirs["data"]["_link"]["n"])
    assert esl.find_by_token(esl.clean_token(token))[0]["id"] == E_THEIRS, "a real link of theirs"
    assert page(token, biz=BIZ)[0] == 404
    assert esl.page_state(esl.church_row(BIZ), token) is None, "never under this church's name"
