# __tests__/test_member_messaging.py
#
# Member messaging end to end (member_portal_messaging.py +
# messaging_router.py) against a small in-memory church. Each test is one
# of Kevin's rules (2026-09-29 / 10-02).

import asyncio
import pathlib
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import member_portal as mp
import member_portal_messaging as mpm
import messaging_router as mr
import msg_screen

BIZ = "11111111-1111-1111-1111-111111111111"
OWNER = "99999999-9999-9999-9999-999999999999"
OFF1, OFF2 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1", "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2"
ANA, BEN, CARL = ("00000000-0000-4000-8000-0000000000a1", "00000000-0000-4000-8000-0000000000a2",
                  "00000000-0000-4000-8000-0000000000a3")          # adults
TEEN, TEEN2 = "00000000-0000-4000-8000-0000000000b1", "00000000-0000-4000-8000-0000000000b2"
PARENT = "00000000-0000-4000-8000-0000000000c1"
NOBIRTH = "00000000-0000-4000-8000-0000000000d1"
GRP = "00000000-0000-4000-8000-0000000000e1"        # adults' group
YOUTH = "00000000-0000-4000-8000-0000000000e2"      # a group with teens
HOST = "first-light.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}
JSON = {**ORIGIN, "accept": "application/json"}


def _filters(q):
    out = []
    for k, vals in q.items():
        if k in ("select", "order", "limit", "on_conflict", "or"):
            continue
        out.append((k, vals[0]))
    return out


def _ok(row, col, expr):
    v = row.get(col)
    if expr.startswith("eq."):
        return str(v).lower() == expr[3:].lower()
    if expr.startswith("neq."):
        return str(v).lower() != expr[4:].lower()
    if expr.startswith("in.("):
        return str(v) in expr[4:-1].split(",")
    if expr.startswith("not.in.("):
        return str(v) not in expr[8:-1].split(",")
    if expr == "is.null":
        return v is None
    if expr.startswith("lt."):
        return str(v) < expr[3:]
    if expr.startswith("gt."):
        return str(v) > expr[3:]
    return True


class DB:
    def __init__(self):
        born_adult, born_teen = "1985-01-01", "2011-01-01"
        self.t = {
            "contacts": [
                {"id": ANA, "business_id": BIZ, "name": "Ana Rivers", "birthdate": born_adult},
                {"id": BEN, "business_id": BIZ, "name": "Ben Cole", "birthdate": "1979-05-05"},
                {"id": CARL, "business_id": BIZ, "name": "Carl Moss", "birthdate": "1970-03-03"},
                {"id": TEEN, "business_id": BIZ, "name": "Tia Rivers", "birthdate": born_teen},
                {"id": TEEN2, "business_id": BIZ, "name": "Theo Hill", "birthdate": "2010-06-06"},
                {"id": PARENT, "business_id": BIZ, "name": "Pam Rivers", "birthdate": "1982-02-02"},
                {"id": NOBIRTH, "business_id": BIZ, "name": "Nora Lane", "birthdate": None},
            ],
            "msg_members": [{"contact_id": c, "business_id": BIZ, "enabled": True, "guidelines_at": "2026-10-01T00:00:00+00:00"}
                            for c in (ANA, BEN, CARL, TEEN, TEEN2, PARENT, NOBIRTH)],
            "msg_guardians": [{"teen_contact_id": TEEN, "guardian_contact_id": PARENT, "business_id": BIZ}],
            "group_members": [
                {"group_id": GRP, "contact_id": ANA, "business_id": BIZ, "role": "member"},
                {"group_id": GRP, "contact_id": BEN, "business_id": BIZ, "role": "leader"},
                {"group_id": YOUTH, "contact_id": TEEN, "business_id": BIZ, "role": "member"},
                {"group_id": YOUTH, "contact_id": TEEN2, "business_id": BIZ, "role": "member"},
                {"group_id": YOUTH, "contact_id": CARL, "business_id": BIZ, "role": "leader"},
            ],
            "groups": [{"id": GRP, "business_id": BIZ, "name": "Tuesday Night"}, {"id": YOUTH, "business_id": BIZ, "name": "Youth"}],
            "msg_threads": [], "msg_participants": [], "msg_messages": [], "msg_blocks": [], "msg_reports": [],
            "msg_staff_views": [], "ministry_care_requests": [],
            "msg_safety_officers": [], "business_users": [],
            "businesses": [{"id": BIZ, "owner_id": OWNER, "settings": {"messaging": {"enabled": True}}}],
        }
        self.n = 0

    def get(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        q = urllib.parse.parse_qs(qs, keep_blank_values=True)
        rows = [dict(r) for r in self.t.get(table, []) if all(_ok(r, c, e) for c, e in _filters(q))]
        order = q.get("order", [""])[0]
        if order:
            col = order.split(".")[0]
            rows.sort(key=lambda r: str(r.get(col)), reverse=order.endswith(".desc"))
        return rows[: int(q.get("limit", ["100000"])[0])]

    def post(self, path, body, prefer=None):
        table = path.lstrip("/").partition("?")[0]
        items = body if isinstance(body, list) else [body]
        out = []
        for b in items:
            self.n += 1
            row = {"id": f"00000000-0000-4000-9000-{self.n:012d}",
                   "created_at": (datetime(2026, 10, 2, tzinfo=timezone.utc) + timedelta(seconds=self.n)).isoformat(), **b}
            if table == "msg_messages":
                row.setdefault("status", "delivered")
                for th in self.t["msg_threads"]:
                    if th["id"] == row["thread_id"]:
                        th["last_message_at"] = row["created_at"]
            if table == "msg_participants" and "merge-duplicates" in (prefer or ""):
                hit = next((p for p in self.t[table] if p["thread_id"] == row["thread_id"] and p["contact_id"] == row["contact_id"]), None)
                if hit:
                    hit.update(b)
                    continue
                row.setdefault("state", "active")
            if table == "msg_blocks" and any(x["blocker_contact_id"] == row["blocker_contact_id"]
                                             and x["blocked_contact_id"] == row["blocked_contact_id"] for x in self.t[table]):
                continue
            self.t.setdefault(table, []).append(row)
            out.append(dict(row))
        return out

    def patch(self, path, body):
        table, _, qs = path.lstrip("/").partition("?")
        q = urllib.parse.parse_qs(qs, keep_blank_values=True)
        hit = [r for r in self.t.get(table, []) if all(_ok(r, c, e) for c, e in _filters(q))]
        for r in hit:
            r.update(body)
        return [dict(r) for r in hit]

    def delete(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        q = urllib.parse.parse_qs(qs, keep_blank_values=True)
        self.t[table] = [r for r in self.t.get(table, []) if not all(_ok(r, c, e) for c, e in _filters(q))]
        return True


@pytest.fixture
def env(monkeypatch):
    d = DB()
    import sb_clients
    monkeypatch.setattr(sb_clients, "sb_get_as_service", d.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", d.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", d.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", d.delete)
    biz = {"id": BIZ, "name": "First Light Church", "type": "church", "settings": d.t["businesses"][0]["settings"],
           "stripe_account_id": None}
    d.biz = biz
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": biz, "site": {"slug": "first-light"}})
    monkeypatch.setattr(mp, "portal_active", lambda b: True)
    d.who = {"id": ANA, "preview": False}

    def session(req, church):
        c = next(x for x in d.t["contacts"] if x["id"] == d.who["id"])
        return {"claims": {}, "people": [c], "me": dict(c), "preview": d.who["preview"]}
    monkeypatch.setattr(mp, "_session_for", session)
    # The two or= queries, in memory (PostgREST's or= isn't in the fake).
    monkeypatch.setattr(mpm, "guardians", lambda b, ids: {
        g["teen_contact_id"]: {x["guardian_contact_id"] for x in d.t["msg_guardians"] if x["teen_contact_id"] == g["teen_contact_id"]}
        for g in d.t["msg_guardians"]})
    monkeypatch.setattr(mpm, "blocks", lambda b, x, y: {
        (r["blocker_contact_id"], r["blocked_contact_id"]) for r in d.t["msg_blocks"]
        if {r["blocker_contact_id"], r["blocked_contact_id"]} == {x, y}})
    d.verdict = "ok"

    async def screen(b, text):
        if d.verdict == "down":
            raise msg_screen.ScreenUnavailable("down")
        return d.verdict
    monkeypatch.setattr(msg_screen, "screen", screen)
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k: True)
    import giving_router
    monkeypatch.setattr(giving_router, "giving_is_active", lambda b: False)
    return d


def _member(env, who):
    env.who["id"] = who
    app = FastAPI()
    app.include_router(mpm.router)

    @app.get("/my/messages{rest:path}")
    async def _page(rest: str, request: mp.Request):
        return await mp.serve(request, "/my/messages" + rest)
    return TestClient(app, base_url=f"https://{HOST}")


def _start(env, who, to):
    r = _member(env, who).get(f"/my/messages/to/{to}", follow_redirects=False)
    return r.headers["location"]


def _send(env, who, tid, text="hello"):
    return _member(env, who).post(f"/my/messages/{tid}/send", data={"body": text}, headers=JSON)


def _tid(loc):
    return loc.rsplit("/", 1)[-1]


# ─── who can message ─────────────────────────────────────────────────


def test_off_until_the_church_turns_it_on(env):
    env.biz["settings"]["messaging"]["enabled"] = False
    assert "isn't turned on" in _member(env, ANA).get("/my/messages").text
    assert _send(env, ANA, "00000000-0000-4000-8000-000000000999").status_code == 409


def test_needs_a_birthdate_and_the_switch_and_the_guidelines(env):
    assert "birthdate" in _member(env, NOBIRTH).get("/my/messages").text
    next(m for m in env.t["msg_members"] if m["contact_id"] == BEN)["enabled"] = False
    assert "turn on messaging for you" in _member(env, BEN).get("/my/messages").text
    next(m for m in env.t["msg_members"] if m["contact_id"] == CARL)["guidelines_at"] = None
    page = _member(env, CARL).get("/my/messages").text
    assert "Before you start" in page and "I agree" in page
    assert _member(env, CARL).post("/my/messages/guidelines", headers=ORIGIN, follow_redirects=False).status_code == 303
    assert next(m for m in env.t["msg_members"] if m["contact_id"] == CARL)["guidelines_at"]


def test_adults_who_share_a_group_chat_and_the_other_sees_it_unread(env):
    loc = _start(env, ANA, BEN)
    tid = _tid(loc)
    assert _send(env, ANA, tid, "See you Tuesday!").json() == {"ok": True}
    inbox = _member(env, BEN).get("/my/messages").text
    assert "See you Tuesday!" in inbox and 'aria-label="1 unread"' in inbox
    assert "See you Tuesday!" in _member(env, BEN).get(f"/my/messages/{tid}").text


def test_no_private_chat_between_a_teen_and_another_adult(env):
    assert _start(env, CARL, TEEN).endswith("err=teen_adult")      # her group leader
    assert _start(env, TEEN, CARL).endswith("err=teen_adult")
    assert not env.t["msg_threads"]


def test_teens_chat_with_teens_and_with_their_own_parent(env):
    t1 = _tid(_start(env, TEEN, TEEN2))
    assert _send(env, TEEN, t1, "hey").json()["ok"]
    t2 = _tid(_start(env, PARENT, TEEN))
    assert _send(env, PARENT, t2, "dinner at 6").json()["ok"]
    page = _member(env, TEEN).get(f"/my/messages/{t1}").text
    assert "Your linked parents can read this chat." in page


def test_a_parent_reads_their_teens_chats_but_cant_post(env):
    t1 = _tid(_start(env, TEEN, TEEN2))
    _send(env, TEEN, t1, "did you finish the reading?")
    fam = _member(env, PARENT).get(f"/my/messages/family/{TEEN}").text
    assert f"/my/messages/{t1}" in fam
    chat = _member(env, PARENT).get(f"/my/messages/{t1}").text
    assert "did you finish the reading?" in chat and "as their parent" in chat and 'id="mb-compose"' not in chat
    assert _send(env, PARENT, t1, "hi kids").status_code == 403
    assert _member(env, ANA).get(f"/my/messages/{t1}").status_code == 404          # not her teen
    assert _member(env, ANA).get(f"/my/messages/family/{TEEN}").status_code == 404


def test_a_group_chat_with_a_teen_waits_for_two_adult_leaders(env):
    tid = _tid(_member(env, TEEN).get(f"/my/messages/group/{YOUTH}", follow_redirects=False).headers["location"])
    r = _send(env, TEEN, tid, "hi all")
    assert r.status_code == 403 and "two adult leaders" in r.json()["error"]
    env.t["group_members"].append({"group_id": YOUTH, "contact_id": BEN, "business_id": BIZ, "role": "leader"})
    assert _send(env, TEEN, tid, "hi all").json()["ok"]


# ─── the check ───────────────────────────────────────────────────────


def test_a_harmful_message_is_held_and_only_its_sender_sees_it(env):
    tid = _tid(_start(env, ANA, BEN))
    env.verdict = "harm"
    _send(env, ANA, tid, "something cruel")
    assert env.t["msg_messages"][0]["status"] == "held"
    assert "Held for review" in _member(env, ANA).get(f"/my/messages/{tid}").text
    assert "something cruel" not in _member(env, BEN).get(f"/my/messages/{tid}").text


def test_crisis_words_deliver_show_988_and_tell_the_pastor_privately(env):
    tid = _tid(_start(env, ANA, BEN))
    env.verdict = "self_harm"
    r = _send(env, ANA, tid, "I want to disappear")
    assert r.json() == {"ok": True, "care": True}
    assert env.t["msg_messages"][0]["status"] == "delivered"
    care = env.t["ministry_care_requests"][0]
    assert care["contact_id"] == ANA and care["submission"]["confidential"] == "yes"
    assert "I want to disappear" not in str(care)                         # the message isn't copied
    assert "988" in _member(env, ANA).get(f"/my/messages/{tid}?done=care").text


def test_if_the_check_cant_run_nothing_is_sent(env):
    tid = _tid(_start(env, ANA, BEN))
    env.verdict = "down"
    r = _send(env, ANA, tid)
    assert r.status_code == 503 and "nothing was sent" in r.json()["error"] and not env.t["msg_messages"]


# ─── block, report, staff looks, preview ─────────────────────────────


def test_a_block_stops_messages_and_isnt_revealed(env):
    tid = _tid(_start(env, ANA, BEN))
    assert _member(env, BEN).post(f"/my/messages/{tid}/block", headers=ORIGIN, follow_redirects=False).status_code == 303
    r = _send(env, ANA, tid)
    assert r.status_code == 403 and r.json()["error"] == "You can't message this person right now."


def test_a_report_reaches_the_officers_and_a_staff_look_is_shown(env):
    tid = _tid(_start(env, ANA, BEN))
    _send(env, ANA, tid, "rude thing")
    mid = env.t["msg_messages"][0]["id"]
    assert _member(env, BEN).post("/my/messages/report", data={"message_id": mid}, headers=ORIGIN,
                                  follow_redirects=False).headers["location"].endswith("done=reported")
    assert env.t["msg_reports"][0]["reporter_contact_id"] == BEN
    env.t["msg_staff_views"].append({"id": "v1", "business_id": BIZ, "thread_id": tid, "user_id": OFF1,
                                     "reason": "report", "created_at": "2026-10-02T15:00:00+00:00"})
    assert "safety officer reviewed this chat on Oct 2" in _member(env, ANA).get(f"/my/messages/{tid}").text


def test_the_owners_preview_never_sends(env):
    tid = _tid(_start(env, ANA, BEN))
    env.who["preview"] = True
    r = _member(env, ANA).post(f"/my/messages/{tid}/send", data={"body": "hi"}, headers=JSON)
    assert r.status_code == 403 and not env.t["msg_messages"]


# ─── the team: settings and the Safety room ──────────────────────────


class _User:
    def __init__(self, uid):
        self.id, self.email = uid, None


def _team(env, uid):
    from auth_supabase import require_user
    app = FastAPI()
    app.include_router(mr.router)
    app.dependency_overrides[require_user] = lambda: _User(uid)
    env.t["business_users"] = [{"business_id": BIZ, "user_id": u, "role": "member", "status": "active"} for u in (OFF1, OFF2)]
    return TestClient(app)


def test_turning_messaging_on_needs_two_officers_and_the_owner(env):
    env.biz["settings"]["messaging"]["enabled"] = False
    owner = _team(env, OWNER)
    r = owner.patch("/messaging/settings", json={"business_id": BIZ, "enabled": True})
    assert r.status_code == 409 and "2 safety officers" in r.json()["detail"]
    env.t["msg_safety_officers"] = [{"business_id": BIZ, "user_id": OFF1}, {"business_id": BIZ, "user_id": OFF2}]
    assert _team(env, OFF1).patch("/messaging/settings", json={"business_id": BIZ, "enabled": True}).status_code == 403
    assert owner.patch("/messaging/settings", json={"business_id": BIZ, "enabled": True}).status_code == 200


def test_only_officers_open_the_safety_room_and_every_look_is_logged(env):
    tid = _tid(_start(env, ANA, BEN))
    env.verdict = "harm"
    _send(env, ANA, tid, "held one")
    env.t["msg_safety_officers"] = [{"business_id": BIZ, "user_id": OFF1}, {"business_id": BIZ, "user_id": OFF2}]
    assert _team(env, OWNER).get("/messaging/safety", params={"business_id": BIZ}).status_code == 403
    officer = _team(env, OFF1)
    q = officer.get("/messaging/safety", params={"business_id": BIZ}).json()
    assert q["held"][0]["body"] == "held one" and q["held"][0]["sender"] == "Ana Rivers"
    r = officer.post("/messaging/safety/open", json={"business_id": BIZ, "thread_id": tid, "reason": "held message"})
    assert r.status_code == 200 and env.t["msg_staff_views"][0]["user_id"] == OFF1
    mid = env.t["msg_messages"][0]["id"]
    assert officer.post("/messaging/safety/message", json={"business_id": BIZ, "message_id": mid, "action": "remove"}).json()["status"] == "removed"
    assert officer.post("/messaging/safety/pause", json={"business_id": BIZ, "contact_id": ANA}).status_code == 200
    assert not next(m for m in env.t["msg_members"] if m["contact_id"] == ANA)["enabled"]


def test_retention_keeps_held_and_reported_messages(env):
    old = "2025-01-01T00:00:00+00:00"
    env.t["msg_messages"] = [
        {"id": "m1", "business_id": BIZ, "thread_id": "t", "status": "delivered", "created_at": old},
        {"id": "m2", "business_id": BIZ, "thread_id": "t", "status": "held", "created_at": old},
        {"id": "m3", "business_id": BIZ, "thread_id": "t", "status": "delivered", "created_at": old},
        {"id": "m4", "business_id": BIZ, "thread_id": "t", "status": "delivered", "created_at": "2026-10-01T00:00:00+00:00"},
    ]
    env.t["msg_reports"] = [{"id": "r1", "business_id": BIZ, "message_id": "m3", "status": "open"}]
    env.t["businesses"][0]["settings"] = {"messaging": {"enabled": True}}
    import sb_clients
    real_get = sb_clients.sb_get_as_service
    sb_clients.sb_get_as_service = lambda p: env.t["businesses"] if p.startswith("/businesses") else real_get(p)
    try:
        mpm.retention_tick()
    finally:
        sb_clients.sb_get_as_service = real_get
    assert sorted(m["id"] for m in env.t["msg_messages"]) == ["m2", "m3", "m4"]


def test_the_owner_names_safety_officers_and_never_drops_below_two_while_on(env):
    owner = _team(env, OWNER)
    s = owner.get("/messaging/settings", params={"business_id": BIZ}).json()
    assert s["you_are_owner"] and {p["user_id"] for p in s["team"]} == {OWNER, OFF1, OFF2}
    assert "team" not in _team(env, OFF1).get("/messaging/settings", params={"business_id": BIZ}).json()
    assert _team(env, OFF1).post("/messaging/officers", json={"business_id": BIZ, "user_id": OFF1, "officer": True}).status_code == 403
    stranger = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert owner.post("/messaging/officers", json={"business_id": BIZ, "user_id": stranger, "officer": True}).status_code == 404
    for u in (OFF1, OFF2):
        assert owner.post("/messaging/officers", json={"business_id": BIZ, "user_id": u, "officer": True}).status_code == 200
    assert {r["user_id"] for r in env.t["msg_safety_officers"]} == {OFF1, OFF2}
    r = owner.post("/messaging/officers", json={"business_id": BIZ, "user_id": OFF2, "officer": False})
    assert r.status_code == 409 and len(env.t["msg_safety_officers"]) == 2        # messaging is on
    env.biz["settings"]["messaging"]["enabled"] = False
    assert owner.post("/messaging/officers", json={"business_id": BIZ, "user_id": OFF2, "officer": False}).json() == {"officers": [OFF1]}
