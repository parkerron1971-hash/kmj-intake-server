"""Needs a look: a held card waits for a person, and the three taps.

Runs the real contact-submit route, inbound_hold and Chief's verbs over a small
in-memory PostgREST (the filters these paths use), with the two campaign cards
from 2026-11-22/26 (made-up details) and a real guest.
"""
import asyncio
import copy
import fnmatch
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import unquote

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import inbound_hold as H
import inbound_risk as R
import sb_clients

A = "11111111-1111-4111-8111-111111111111"     # the church (Love City's place in these tests)
B = "22222222-2222-4222-8222-222222222222"
C = "33333333-3333-4333-8333-333333333333"
OWNER = "aaaaaaaa-1111-4111-8111-111111111111"
VIEWER = "aaaaaaaa-2222-4222-8222-222222222222"


# ─── A small PostgREST ────────────────────────────────────────────────

PKS = {"inbound_senders": ("business_id", "kind", "hash"), "inbound_shared_list": ("kind", "hash")}


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _split(s, sep=","):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _get(row, col):
    m = re.match(r"^(\w+)(?:->>?(\w+))?$", col)
    base, key = m.group(1), m.group(2)
    v = row.get(base)
    if key:
        v = v.get(key) if isinstance(v, dict) else None
        if "->>" in col and v is not None and not isinstance(v, str):
            v = str(v)
    return v


def _match(v, opval):
    op, _, val = opval.partition(".")
    val = unquote(val)
    if op == "eq":
        return v is not None and str(v).lower() == val.lower() if isinstance(v, bool) else v is not None and str(v) == val
    if op == "neq":
        return v is None or str(v) != val
    if op == "in":
        return v is not None and str(v) in [unquote(x).strip('"') for x in val.strip("()").split(",")]
    if op == "is":
        return (v is None) if val == "null" else (v is (val == "true"))
    if op in ("gte", "gt", "lte", "lt"):
        if v is None:
            return False
        a, b = str(v), val
        try:
            a, b = float(a), float(b)
        except ValueError:
            pass
        return {"gte": a >= b, "gt": a > b, "lte": a <= b, "lt": a < b}[op]
    if op == "ilike":
        return v is not None and fnmatch.fnmatch(str(v).lower(), val.lower().replace("\\", ""))
    raise AssertionError(f"unsupported op {opval}")


class FakeDB:
    def __init__(self):
        self.t = {}
        self.fail_tables = set()
        self.log = []

    def rows(self, table):
        return self.t.setdefault(table, [])

    def _parse(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        params = [p for p in qs.split("&") if p] if qs else []
        return table, params

    def _filter(self, table, params):
        rows = self.rows(table)
        out = []
        for r in rows:
            ok = True
            for p in params:
                k, _, v = p.partition("=")
                if k in ("select", "order", "limit", "on_conflict"):
                    continue
                if k == "or":
                    alts = _split(unquote(v)[1:-1])
                    if not any(_match(_get(r, a.split(".", 1)[0]), a.split(".", 1)[1]) for a in alts):
                        ok = False
                    continue
                if not _match(_get(r, unquote(k)), v):
                    ok = False
            if ok:
                out.append(r)
        return out

    def _select(self, rows, params):
        sel = next((unquote(p.split("=", 1)[1]) for p in params if p.startswith("select=")), "*")
        order = next((unquote(p.split("=", 1)[1]) for p in params if p.startswith("order=")), "")
        limit = next((int(p.split("=", 1)[1]) for p in params if p.startswith("limit=")), None)
        rows = list(rows)
        for o in reversed([x for x in order.split(",") if x]):
            col, _, d = o.partition(".")
            rows.sort(key=lambda r: str(_get(r, col) or ""), reverse=d.startswith("desc"))
        if limit is not None:
            rows = rows[:limit]
        out = []
        for r in rows:
            if sel.strip() == "*" or "*" in _split(sel):
                out.append(copy.deepcopy(r))
                continue
            d = {}
            for item in _split(sel):
                if "(" in item:
                    continue
                alias, _, expr = item.partition(":") if ":" in item else (None, None, item)
                expr = expr or item
                d[alias or re.split(r"->>?", expr)[-1]] = copy.deepcopy(_get(r, expr))
            out.append(d)
        return out

    def get(self, path, **kw):
        table, params = self._parse(path)
        if table in self.fail_tables:
            return None
        return self._select(self._filter(table, params), params)

    def post(self, path, payload, prefer="return=representation", **kw):
        table, params = self._parse(path)
        self.log.append(("POST", table, copy.deepcopy(payload)))
        if table in self.fail_tables:
            return None
        items = payload if isinstance(payload, list) else [payload]
        pk = PKS.get(table, ("id",))
        out = []
        for item in items:
            item = dict(item)
            if "id" in pk and not item.get("id"):
                item["id"] = str(uuid.uuid4())
            item.setdefault("created_at", _now())
            existing = [r for r in self.rows(table) if all(str(r.get(k)) == str(item.get(k)) for k in pk)]
            if existing:
                if "merge-duplicates" in (prefer or ""):
                    existing[0].update(item)
                    out.append(copy.deepcopy(existing[0]))
                continue
            self.rows(table).append(item)
            out.append(copy.deepcopy(item))
        return out

    def patch(self, path, body, **kw):
        table, params = self._parse(path)
        self.log.append(("PATCH", table, copy.deepcopy(body)))
        if table in self.fail_tables:
            return None
        hit = self._filter(table, params)
        for r in hit:
            r.update(copy.deepcopy(body))
        return [copy.deepcopy(r) for r in hit]

    def delete(self, path):
        table, params = self._parse(path)
        hit = self._filter(table, params)
        self.t[table] = [r for r in self.rows(table) if r not in hit]
        return True


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", d.delete)
    monkeypatch.setenv("INBOUND_HASH_SALT", "test-salt")
    monkeypatch.setenv("INBOUND_SAFETY", "on")
    monkeypatch.setenv("INBOUND_RDAP", "off")
    monkeypatch.setenv("INBOUND_SECOND_OPINION", "off")
    import sample_church
    monkeypatch.setattr(sample_church, "is_sample", lambda b: False)

    async def not_sample(b):
        return False
    monkeypatch.setattr(sample_church, "is_sample_async", not_sample)
    monkeypatch.setattr(R, "domain_facts", lambda domain: (False, None))
    import audit_log
    monkeypatch.setattr(audit_log, "record", lambda *a, **kw: d.log.append(("AUDIT", kw.get("verb"), kw)) or True)
    for biz in (A, B, C):
        d.rows("businesses").append({"id": biz, "owner_id": OWNER, "type": "ministry", "name": "Church",
                                     "settings": {"email_domain": {"status": "verified", "domain": "gracechurch-test.org",
                                                                   "from_local_part": "hello"}}})
    return d


SOFIA = dict(name="Sara Moreno", email="sara@tourist-sector.example.com", phone="1000000000",
             form="connect_card", message="", submission_id="s-1",
             fields={"visits": "This is my first time", "heard_from": "Facebook", "notes": (
                 "Hello, I wrote to you a few days ago through your contact form. We would like to add "
                 "gracechurch-test.org to Tourist, a catalogue of travel offers, free of charge. Write 'yes' to "
                 "sara@tourist-sector.example.com. You can also register yourself: tourist-sector.example.com.")})
JULIEN = dict(name="Jules Marchand", email="jules@tourist-europe.example.net", phone="1000000000",
              form="connect_card", message="", submission_id="j-1",
              fields={"visits": "This is my first time", "heard_from": "Facebook", "notes": (
                  "Earlier I sent you an offer to add you to the Tourist catalog. The registration link is "
                  "tourist-europe.example.net and it is free!")})
GUEST = dict(name="Dana Rivers", email="dana.rivers@gmail.com", phone="(704) 555-0182", form="connect_card",
             message="", submission_id="g-1",
             fields={"visits": "This is my first time", "heard_from": "A friend",
                     "notes": "Loved the worship, my kids want to come back. My cousin invited me."})


@pytest.fixture
def site(db, monkeypatch):
    """The real public route, with the pieces it hands off to watched."""
    import brand_engine
    import church_follow_up
    import public_site
    import website_forms
    got = SimpleNamespace(connect=[], alerts=[], mail=[], scores=[], nudges=[], signals=[], prayer=[])
    monkeypatch.setattr(church_follow_up, "on_connect_card",
                        lambda biz, cid, data, receipt="", texts_ok=False: got.connect.append(
                            (biz, cid, receipt, texts_ok)) or {"id": f"fu-{len(got.connect)}"})

    async def alert(biz, kind, receipt):
        got.alerts.append((biz, kind))
    monkeypatch.setattr(website_forms, "alert_church", alert)

    async def signal(biz, church=True):
        got.signals.append((biz, church))
    monkeypatch.setattr(H, "signal", signal)
    import lead_scoring
    import chief_agent
    import church_prayer
    monkeypatch.setattr(lead_scoring, "score_in_background", lambda *a, **kw: got.scores.append(a))
    monkeypatch.setattr(chief_agent, "nudge", lambda *a, **kw: got.nudges.append(a))
    monkeypatch.setattr(church_prayer, "on_new", lambda biz, row: got.prayer.append(row))
    monkeypatch.setattr(public_site, "_check_contact_rate", lambda ip: True)
    monkeypatch.setattr(brand_engine, "get_bundle", lambda b: {"business": {"name": "Church"},
                                                               "footer": {"contact_email": "office@shop-test.org"}})
    monkeypatch.setattr(brand_engine, "_sb_get", lambda p: [])
    monkeypatch.setenv("RESEND_API_KEY", "test")

    class Mail:
        def __init__(self, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, **kw):
            got.mail.append(kw["json"])
            return SimpleNamespace(status_code=200)
    monkeypatch.setattr(public_site.httpx, "AsyncClient", Mail)
    app = FastAPI()
    app.include_router(public_site.router)
    got.client = TestClient(app)

    def send(card, biz=A, **changes):
        body = dict(card, **changes)
        return got.client.post(f"/sites/{biz}/contact-submit", json=body)
    got.send = send
    return got


def contact(db, email):
    return next(r for r in db.rows("contacts") if r["email"] == email)


def check_of(db, cid):
    return [r for r in db.rows("inbound_checks") if r.get("contact_id") == cid]


# ─── A card comes in ──────────────────────────────────────────────────

def test_a_campaign_card_is_saved_marked_and_starts_nothing(db, site):
    r = site.send(SOFIA, sms_consent=False)
    assert r.json() == {"ok": True, "notification_sent": True}           # the same thank-you
    c = contact(db, SOFIA["email"])
    mark = c["metadata"]["inbound_hold"]
    assert mark["state"] == "needs_look" and "The phone number isn't real" in mark["reasons"]
    assert c["metadata"]["website_form_messages"][0]["fields"]["notes"] == SOFIA["fields"]["notes"]
    assert any(e["event_type"] == "contact_note" for e in db.rows("events"))   # the card is readable
    assert site.connect == [] and site.alerts == []                    # no follow-up, path, or guest alert
    assert site.signals == [(A, True)]                                 # one quiet line instead
    (chk,) = check_of(db, c["id"])
    assert chk["state"] == H.HELD and chk["verdict"] == R.NEEDS_LOOK and chk["pending"]["receipt"]
    # No words, names or addresses in the check row: hashes and reasons only.
    blob = repr({k: v for k, v in chk.items() if k != "reasons"})
    assert "sara" not in blob.lower() and "catalogue" not in blob
    mail = site.mail[0]
    assert mail["subject"].startswith("[Needs a look] ") and "reply_to" not in mail
    assert "This card needs a look" in mail["html"] and "Asks you to visit" in mail["html"]


def test_a_real_guest_runs_as_always(db, site):
    site.send(GUEST, sms_consent=False)
    c = contact(db, GUEST["email"])
    assert "inbound_hold" not in c["metadata"]
    assert len(site.connect) == 1 and site.alerts == [(A, "connect_card")] and site.signals == []
    assert check_of(db, c["id"])[0]["state"] == H.CLEAR
    assert site.mail[0]["reply_to"] == GUEST["email"] and not site.mail[0]["subject"].startswith("[Needs")


def test_the_second_campaign_card_is_matched_to_nothing_on_file_and_held(db, site):
    site.send(JULIEN)
    site.send(SOFIA)
    held = H.held(A)
    assert {p["name"] for p in held} == {"Sara Moreno", "Jules Marchand"}
    sara = next(p for p in held if p["name"] == "Sara Moreno")
    assert "catalogue of travel offers" in sara["preview"] and sara["cards"] == 1
    assert H.held_count(A) == 2


def test_switch_off_checks_nothing(db, site, monkeypatch):
    monkeypatch.setenv("INBOUND_SAFETY", "off")
    site.send(SOFIA)
    assert db.rows("inbound_checks") == [] and len(site.connect) == 1 and site.alerts


def test_watch_mode_records_but_holds_nothing(db, site, monkeypatch):
    monkeypatch.setenv("INBOUND_SAFETY", "watch")
    site.send(SOFIA)
    (chk,) = db.rows("inbound_checks")
    assert chk["state"] == H.WATCHED and chk["verdict"] == R.NEEDS_LOOK
    assert len(site.connect) == 1 and "inbound_hold" not in contact(db, SOFIA["email"])["metadata"]


def test_a_hold_that_cannot_be_recorded_never_holds(db, site):
    db.fail_tables.add("inbound_checks")       # before the APPLY file, say
    r = site.send(SOFIA)
    assert r.json()["ok"] is True
    assert len(site.connect) == 1 and site.alerts and "inbound_hold" not in contact(db, SOFIA["email"])["metadata"]


def test_a_contact_form_pitch_skips_scoring_and_the_nudge(db, site):
    site.send(dict(name="Seo Team", email="growth@rank-fast.example.com", phone="",
                   message="We can get your website traffic to the first page of google. Click here: rank-fast.example.com",
                   submission_id="cf-1"))
    assert site.scores == [] and site.nudges == [] and site.signals == [(A, False)]
    site.send(dict(name="Dana Rivers", email="dana@gmail.com", phone="", message="Do you have openings Friday?",
                   submission_id="cf-2"))
    assert len(site.scores) == 1 and len(site.nudges) == 1


def test_a_prayer_request_is_never_held_and_carries_a_mark(db, site):
    r = site.send(dict(name="Sara Moreno", email="sara@tourist-sector.example.com", phone="1000000000",
                       form="prayer_request", message="", submission_id="p-1",
                       fields={"request": "Pray for our catalogue listing business, register at tourist-sector.example.com",
                               "share": "team"}))
    assert r.json()["ok"] is True
    (care,) = db.rows("ministry_care_requests")
    assert care["submission"]["needs_a_look"]["label"] == "May not be genuine"
    assert len(site.prayer) == 1                       # handed to the people who pray, as always
    assert db.rows("inbound_checks")[0]["state"] == H.FLAGGED and site.signals == []


# ─── The taps ─────────────────────────────────────────────────────────

def test_real_person_runs_what_was_held_and_remembers_them(db, site):
    site.send(SOFIA, sms_consent=False)
    c = contact(db, SOFIA["email"])
    out = H.decide(A, c["id"], H.REAL, by_user=OWNER, by_name="kevin")
    assert out["released"] == 1 and out["follow_ups_opened"] == 1
    assert site.connect and site.connect[0][1] == c["id"] and site.connect[0][3] is False
    c = contact(db, SOFIA["email"])
    assert "inbound_hold" not in c["metadata"] and c["metadata"]["inbound_decision"]["verdict"] == "real"
    assert check_of(db, c["id"])[0]["state"] == H.RELEASED
    assert {s["verdict"] for s in db.rows("inbound_senders")} == {"real"}
    assert "domain" not in {s["kind"] for s in db.rows("inbound_senders")}
    # Their next card goes straight through.
    site.connect.clear()
    site.send(dict(SOFIA, submission_id="s-2"))
    assert len(site.connect) == 1 and "inbound_hold" not in contact(db, SOFIA["email"])["metadata"]
    assert any(e[1] == "inbound:real" for e in db.log if e[0] == "AUDIT")


def test_not_a_guest_closes_follow_ups_and_texts_and_undo_puts_it_all_back(db, site, monkeypatch):
    import church_follow_up as cfu
    monkeypatch.delattr(cfu, "close_for_contact", raising=False)
    site.send(GUEST)          # a guest who ran as usual (the 11-22 card, before any hold existed)
    c = contact(db, GUEST["email"])
    db.rows("church_follow_ups").append({"id": "fu-a", "business_id": A, "contact_id": c["id"], "status": "open"})
    later = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    db.rows("chief_scheduled_actions").append({"id": "t-1", "business_id": A, "status": "queued", "run_at": later,
                                               "action": {"type": "new_here_text", "contact_id": c["id"]}})
    closed = []
    monkeypatch.setattr(cfu, "close", lambda biz, fid, by_user, by_name="": closed.append(fid) or next(
        r for r in db.rows("church_follow_ups") if r["id"] == fid).update(status="closed"))
    out = H.decide(A, c["id"], H.NOT_A_GUEST, by_user=OWNER)
    assert closed == ["fu-a"] and out["follow_ups_closed"] == 1 and out["texts_cancelled"] == 1
    c2 = contact(db, GUEST["email"])
    assert c2["status"] == "inactive" and c2["metadata"]["inbound_decision"]["verdict"] == "not_a_guest"
    assert db.rows("chief_scheduled_actions")[0]["status"] == "cancelled"
    assert db.rows("inbound_senders") == []                 # Not a guest names nobody to other churches
    back = H.undo(A, out["decision_id"], by_user=OWNER)
    assert back["ok"]
    assert db.rows("church_follow_ups")[0]["status"] == "open"
    assert db.rows("chief_scheduled_actions")[0]["status"] == "queued"
    assert contact(db, GUEST["email"])["status"] == c["status"]
    with pytest.raises(Exception):
        H.undo(A, out["decision_id"], by_user=OWNER)        # once


def test_the_shared_helper_is_used_when_it_exists(db, site, monkeypatch):
    import church_follow_up as cfu
    calls = []
    monkeypatch.setattr(cfu, "close_for_contact", lambda biz, cid, **kw: calls.append((biz, cid, kw)) or ["x"],
                        raising=False)
    site.send(SOFIA)
    c = contact(db, SOFIA["email"])
    out = H.decide(A, c["id"], H.NOT_A_GUEST, by_user=OWNER, by_name="kevin")
    assert calls and calls[0][1] == c["id"] and out["follow_ups_closed"] == 1


def test_undoing_real_closes_what_it_opened_and_holds_again(db, site):
    site.send(SOFIA)
    c = contact(db, SOFIA["email"])
    db.rows("church_follow_ups").append({"id": "fu-1", "business_id": A, "contact_id": c["id"], "status": "open"})
    out = H.decide(A, c["id"], H.REAL, by_user=OWNER)
    H.undo(A, out["decision_id"], by_user=OWNER)
    assert db.rows("church_follow_ups")[0]["status"] == "closed"
    assert contact(db, SOFIA["email"])["metadata"]["inbound_hold"]["state"] == "needs_look"
    assert check_of(db, c["id"])[0]["state"] == H.HELD and db.rows("inbound_senders") == []


def test_two_churches_saying_scam_puts_a_sender_on_the_shared_list(db, site, monkeypatch):
    import church_follow_up as cfu
    monkeypatch.setattr(cfu, "close_for_contact", lambda *a, **kw: [], raising=False)
    site.send(SOFIA, biz=A)
    H.decide(A, contact_list(db, A)[0]["id"], H.SCAM, by_user=OWNER)
    assert db.rows("inbound_shared_list") == []          # one church's tap counts only there
    site.send(dict(SOFIA, submission_id="s-b"), biz=B)
    out_b = H.decide(B, contact_list(db, B)[0]["id"], H.SCAM, by_user=OWNER)
    listed = db.rows("inbound_shared_list")
    assert listed and {r["source"] for r in listed} == {"churches"} and all(r["churches"] == 2 for r in listed)
    assert all(len(r["hash"]) == 64 for r in listed)
    # A third church sees the hit as a reason, never a block: the card is saved.
    plain = dict(name="Sara Moreno", email=SOFIA["email"], phone="", form="connect_card", message="",
                 submission_id="s-c", fields={"notes": "Hi"})
    site.send(plain, biz=C)
    held_c = H.held(C)
    assert held_c and "Other churches marked this sender as a scam" in held_c[0]["reasons"]
    # Its own Real wins there.
    site.connect.clear()
    H.decide(C, contact_list(db, C)[0]["id"], H.REAL, by_user=OWNER)
    assert len(site.connect) == 1           # what was held runs
    site.send(dict(plain, submission_id="s-c2"), biz=C)
    assert len(site.connect) == 2           # and the next card goes straight through
    # One church taking its Scam back leaves one: off the list.
    H.undo(B, out_b["decision_id"], by_user=OWNER)
    assert db.rows("inbound_shared_list") == []


def test_the_shared_list_ages_out(db, site):
    old = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    h = R.salted("email", SOFIA["email"])
    db.rows("inbound_shared_list").append({"kind": "email", "hash": h, "source": "churches", "churches": 2,
                                          "expires_at": old})
    f = R.gather(A, R.Card(door="connect_card", name="x", email=SOFIA["email"]))
    assert f.shared_hit is False


def test_the_platform_owner_can_share_one_sender_at_once(db, site, monkeypatch):
    import church_follow_up as cfu
    monkeypatch.setattr(cfu, "close_for_contact", lambda *a, **kw: [], raising=False)
    site.send(SOFIA)
    H.decide(A, contact(db, SOFIA["email"])["id"], H.SCAM, by_user=OWNER, share=True)
    assert {r["source"] for r in db.rows("inbound_shared_list")} == {"platform"}


def contact_list(db, biz):
    return [r for r in db.rows("contacts") if r["business_id"] == biz]


# ─── The office's routes ──────────────────────────────────────────────

@pytest.fixture
def office(db, site, monkeypatch):
    import auth_supabase
    import business_access
    who = SimpleNamespace(id=OWNER, email="kevin@example.org")
    monkeypatch.setattr(business_access, "_resolve_role",
                        lambda biz, uid: {OWNER: "owner", VIEWER: "viewer"}.get(uid))
    app = FastAPI()
    app.include_router(H.router)
    app.dependency_overrides[auth_supabase.require_user_session] = lambda: SimpleNamespace(user=who, token="t")
    return SimpleNamespace(client=TestClient(app), who=who)


def test_the_queue_and_the_buttons(db, site, office):
    site.send(SOFIA)
    q = office.client.get(f"/inbound/{A}/needs-a-look").json()
    assert q["on"] is True and q["count"] == 1
    p = q["people"][0]
    assert set(p) >= {"contact_id", "name", "door", "score", "reasons", "at", "cards", "preview"}
    r = office.client.post(f"/inbound/{A}/people/{p['contact_id']}/real")
    assert r.status_code == 200 and r.json()["verdict"] == "real" and "decision_id" in r.json()
    assert office.client.get(f"/inbound/{A}/needs-a-look").json()["count"] == 0
    u = office.client.post(f"/inbound/{A}/decisions/{r.json()['decision_id']}/undo")
    assert u.json()["needs_look"] is True
    assert office.client.post(f"/inbound/{A}/people/{p['contact_id']}/maybe").status_code == 404


def test_a_viewer_cannot_tap_and_only_the_platform_owner_shares(db, site, office, monkeypatch):
    site.send(SOFIA)
    cid = contact(db, SOFIA["email"])["id"]
    office.who.id = VIEWER
    assert office.client.post(f"/inbound/{A}/people/{cid}/scam").status_code == 404
    assert office.client.get(f"/inbound/{A}/needs-a-look").status_code == 404
    office.who.id = OWNER
    import church_follow_up as cfu
    monkeypatch.setattr(cfu, "close_for_contact", lambda *a, **kw: [], raising=False)
    office.client.post(f"/inbound/{A}/people/{cid}/scam", json={"share": True})
    assert db.rows("inbound_shared_list") == []               # not the platform owner: share is ignored
    assert office.client.get("/platform/inbound/shared-list").status_code == 403


# ─── Chief ────────────────────────────────────────────────────────────

def _chief(monkeypatch, uid=OWNER):
    import business_users_router as bur
    import chief_duties
    import chief_inbound
    monkeypatch.setattr(chief_duties, "_turn_user", lambda: uid)
    monkeypatch.setattr(bur, "role_of", lambda biz, u: {OWNER: "owner", VIEWER: "viewer"}.get(u))
    return chief_inbound


def test_chief_marks_not_a_guest_and_undo_is_its_inverse(db, site, monkeypatch):
    import action_inverse
    import church_follow_up as cfu
    monkeypatch.setattr(cfu, "close_for_contact", lambda *a, **kw: [], raising=False)
    ci = _chief(monkeypatch)
    site.send(SOFIA)
    cid = contact(db, SOFIA["email"])["id"]
    out = asyncio.run(ci.HANDLERS["mark_not_a_guest"](None, {"id": A}, {"name": "Sara Moreno"}))
    assert not out.get("failed") and out["result"] and out["label"] and out["contact_id"] == cid
    assert contact(db, SOFIA["email"])["status"] == "inactive"
    inv = action_inverse.build_inverse("mark_not_a_guest", {"name": "Sara Moreno"}, out)
    assert inv == {"type": "undo_inbound_decision", "decision_id": out["decision_id"]}
    back = asyncio.run(ci.HANDLERS["undo_inbound_decision"](None, {"id": A}, inv))
    assert not back.get("failed") and contact(db, SOFIA["email"])["metadata"]["inbound_hold"]


def test_chief_refuses_a_viewer_unattended_runs_and_a_name_that_names_two(db, site, monkeypatch):
    ci = _chief(monkeypatch, uid=VIEWER)
    site.send(SOFIA)
    out = asyncio.run(ci.HANDLERS["mark_real_person"](None, {"id": A}, {"name": "Sara Moreno"}))
    assert out["failed"] and "Manager" in out["result"]
    ci = _chief(monkeypatch)
    out = asyncio.run(ci.HANDLERS["mark_real_person"](None, {"id": A}, {"name": "Sara", "_unattended": True}))
    assert out["failed"]
    site.send(dict(SOFIA, name="Sara Moreno-Diaz", email="other@x.example.com", phone="", submission_id="s-9"))
    out = asyncio.run(ci.HANDLERS["mark_real_person"](None, {"id": A}, {"name": "Sara"}))
    assert out["failed"] and "More than one" in out["result"]
    out = asyncio.run(ci.HANDLERS["mark_real_person"](None, {"id": A}, {"name": "Sara Moreno"}))
    assert not out.get("failed")                      # the exact name names one


def test_chiefs_block_names_who_waits_and_why_never_their_words(db, site):
    site.send(SOFIA)
    line = H.turn_line({"id": A, "type": "ministry"}, OWNER)
    assert line.startswith("NEEDS A LOOK (1 connect cards held") and "Sara Moreno" in line
    assert "The phone number isn't real" in line and "mark_real_person" in line and "mark_not_a_guest" in line
    assert "Never suggest welcoming" in line and "Scam is the office's own tap" in line
    assert "catalogue of travel offers" not in line and "sara@" not in line
    assert H.turn_line({"id": B, "type": "ministry"}, OWNER) == ""        # nobody waits there


def test_a_send_to_a_flagged_person_needs_fresh_words(db, site, monkeypatch):
    site.send(SOFIA)
    site.send(GUEST)
    sara, dana = contact(db, SOFIA["email"])["id"], contact(db, GUEST["email"])["id"]
    assert H.flagged_recipient(A, {"contact_id": sara}) == "Sara Moreno's card is waiting for a look"
    assert H.flagged_recipient(A, {"contact_id": dana}) is None
    assert H.flagged_recipient(A, {"to": "+17045550182"}) is None          # Dana's phone: clear
    assert H.flagged_recipient(A, {"contact_name": "sara moreno"}) == "Sara Moreno's card is waiting for a look"
    assert H.flagged_recipient(A, {"to": SOFIA["email"].upper()}) == "Sara Moreno's card is waiting for a look"
    assert H.flagged_recipient(A, {"contact_name": "Dana Rivers"}) is None
    monkeypatch.setenv("INBOUND_SAFETY", "off")
    assert H.flagged_recipient(A, {"contact_id": sara}) is None


def test_the_send_gate_holds_a_send_to_a_held_person(db, site, monkeypatch):
    import chief_of_staff as cos
    site.send(SOFIA)
    sara = contact(db, SOFIA["email"])["id"]
    src = open(cos.__file__, encoding="utf-8").read()
    gate = src[src.index("_flag = await asyncio.to_thread(_inbound_hold.flagged_recipient"):]
    # After the go-ahead release (fresh words send it) and before the taint hold.
    assert src.index("chief_holds.release(_hold_user, _hold_biz, atype, action)") < src.index(
        "_inbound_hold.flagged_recipient") < src.index("if untrusted_taint():\n            logger.warning(\n"
                                                       "                f\"[gate] holding single-target")
    assert "needs_confirmation" in gate[:1500]
    assert H.flagged_recipient(A, {"contact_id": sara})


# ─── The brief and the roll ───────────────────────────────────────────

def test_the_morning_brief_says_how_many_wait_and_never_names_them(db, site, monkeypatch):
    import notification_engine as ne
    site.send(SOFIA)
    site.send(GUEST)

    async def sbget(client, method, path, body=None, **kw):
        return sb_clients.sb_get_as_service(path)
    monkeypatch.setattr(ne, "_sb", sbget)
    for r in db.rows("contacts"):
        r["status"] = "lead"
    data = asyncio.run(ne._gather_morning_data(None, A))
    names = [r["name"] for r in data["new_leads_24h"]]
    assert "Dana Rivers" in names and "Sara Moreno" not in names
    assert data["needs_a_look"].startswith("1 card needs a look") and "never name them" in data["needs_a_look"]
    monkeypatch.setenv("INBOUND_SAFETY", "off")
    data = asyncio.run(ne._gather_morning_data(None, A))
    assert "needs_a_look" not in data


def test_the_roll_reads_the_mark():
    import church_roll
    src = open(church_roll.__file__, encoding="utf-8").read()
    assert "needs_look:metadata->inbound_hold" in src and '"needs_look": isinstance(c.get("needs_look"), dict)' in src


def test_signal_words():
    assert H.signal_words(1) == ("1 card needs a look", H.signal_words(1)[1])
    assert H.signal_words(3)[0] == "3 cards need a look"
    assert H.signal_words(2, church=False)[0] == "2 messages need a look"
    assert "Sara" not in H.signal_words(1)[1]
