"""Church threads (church_threads.py, member_portal_threads.py; Kevin,
2026-11-17: notes in the member app should feel like texts, members can
write back, and groups hear their own news). Pins:

  1. which notes are kept, and in which conversation
  2. one row per person, every row with the same keys (PostgREST drops a
     chunk with mixed keys), or one row for everyone
  3. the switch: off | owner | on, owner by default; a sample church and
     missing tables keep it quiet, and a push always still goes
  4. the lock screen reads like a text and opens the conversation; quiet
     hours and the morning delivery still work
  5. the member's pages: the inbox, the church conversation, a group's
     (its members only), Home's card and Me's line
  6. writing to the office: length, 20 a day, 5 seconds apart, screened
     (held, crisis, screen down), never for a sample church
  7. the office API: who may call it, and its fixed shapes
"""
import json
import pathlib
import sys
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import church_threads as ct
import member_asks as ma
import member_portal as mp
import member_portal_threads as mpt
import member_push
import push_notifications as pn
import sb_clients

BIZ = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
HOST = "love-city.mysolutionist.app"
ORIGIN = {"origin": f"https://{HOST}"}
ADULT = "1980-05-01"


def cid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


ANA, BEN, CAL, DEE = cid(1), cid(2), cid(3), cid(4)
GROUP, GROUP2 = cid(31), cid(32)
OWNER, CLERK, OFFICER, STRANGER = "owner-user", "clerk-user", "officer-user", "stranger-user"


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


NOW = datetime.now(timezone.utc)


# ─── a PostgREST-shaped fake ─────────────────────────────────────────


def _parse(s):
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _cmp(have, want):
    a, b = _parse(have), _parse(want)
    if a is not None and b is not None and len(str(have)) >= 10 and len(str(want)) >= 10:
        return (a > b) - (a < b)
    return (str(have) > str(want)) - (str(have) < str(want))


def _one(row, key, op):
    v = row.get(key)
    if op.startswith("eq."):
        want = op[3:]
        if isinstance(v, bool):
            return str(v).lower() == want
        return v is not None and str(v) == want
    if op.startswith("in.("):
        return str(v) in op[4:-1].split(",")
    if op == "is.null":
        return v is None
    if op == "not.is.null":
        return v is not None
    if op.startswith(("gt.", "gte.", "lt.", "lte.")):
        name, want = op.split(".", 1)
        if v is None:
            return False
        c = _cmp(v, want)
        return {"gt": c > 0, "gte": c >= 0, "lt": c < 0, "lte": c <= 0}[name]
    raise AssertionError(f"filter not faked: {key}={op}")


def _match(row, key, op):
    if key == "or":
        parts = op.strip("()").split(",")
        return any(_one(row, p.split(".", 1)[0], p.split(".", 1)[1]) for p in parts)
    return _one(row, key, op)


SKIP = ("select", "order", "limit", "on_conflict")


class Fake:
    TABLES = ("church_thread_notes", "church_thread_reads", "contacts", "group_members", "groups",
              "member_push_subscriptions", "member_push_prefs", "member_push_sends", "member_push_held",
              "business_users", "msg_safety_officers", "ministry_care_requests", "msg_members",
              "sms_messages", "sms_consents")

    def __init__(self):
        self.t = {k: [] for k in self.TABLES}
        self.biz = {
            BIZ: {"id": BIZ, "name": "Love City Church", "type": "church", "owner_id": OWNER, "is_sample": False,
                  "settings": {"member_portal": {"enabled": True, "notifications": {
                      k: True for k in member_push.KIND_KEYS}}}},
            OTHER: {"id": OTHER, "name": "Other Church", "type": "church", "owner_id": "other-owner",
                    "is_sample": False, "settings": {"member_portal": {"enabled": True}}},
        }
        self.writes = []
        self.down = set()
        self.gets = []

    def add(self, table, **row):
        row.setdefault("id", str(uuid.uuid4()))
        self.t[table].append(row)
        return row

    def person(self, i, name, *, biz=BIZ, birthdate=ADULT):
        return self.add("contacts", id=i, business_id=biz, name=name, email=f"{name.split()[0].lower()}@example.com",
                        phone="555 010 2030", birthdate=birthdate, status="active", tags=[], metadata={})

    def note(self, **row):
        base = {"business_id": BIZ, "contact_id": None, "thread": "church", "direction": "church", "kind": "announcements",
                "title": None, "body": None, "url": None, "ref_id": None, "author_user_id": None, "author_name": None,
                "held": False, "created_at": iso(NOW), "read_at": None}
        base.update(row)
        return self.add("church_thread_notes", **base)

    def _split(self, path):
        table, _, qs = path.lstrip("/").partition("?")
        return table, urllib.parse.parse_qsl(qs, keep_blank_values=True)

    def get(self, path, **kw):
        self.gets.append(path)
        table, params = self._split(path)
        if table in self.down:
            return None
        if table == "businesses":
            want = dict(params).get("id", "")
            ids = want[4:-1].split(",") if want.startswith("in.(") else [want.removeprefix("eq.")]
            return [json.loads(json.dumps(self.biz[i])) for i in ids if i in self.biz]
        if table not in self.t:
            return []
        rows = [r for r in self.t[table] if all(_match(r, k, v) for k, v in params if k not in SKIP)]
        order = dict(params).get("order")
        if order:
            key, _, how = order.split(",")[0].partition(".")
            rows.sort(key=lambda r: str(r.get(key) or ""), reverse=how.startswith("desc"))
        limit = dict(params).get("limit")
        if limit:
            rows = rows[:int(limit)]
        return json.loads(json.dumps(rows))

    def post(self, path, body, prefer=None, **kw):
        table, params = self._split(path)
        if table in self.down:
            return None
        rows = body if isinstance(body, list) else [body]
        # PostgREST: a bulk insert whose rows don't all carry the same keys
        # is refused as a whole (PGRST102).
        if len({tuple(sorted(r)) for r in rows}) > 1:
            self.writes.append(("refused", table, rows))
            return None
        out = []
        conflict = dict(params).get("on_conflict")
        for r in rows:
            r = json.loads(json.dumps(r))
            if conflict:
                keys = conflict.split(",")
                hit = next((x for x in self.t.setdefault(table, []) if all(str(x.get(k)) == str(r.get(k)) for k in keys)),
                           None)
                if hit is not None:
                    if prefer and "ignore-duplicates" in prefer:
                        continue
                    hit.update(r)
                    out.append(hit)
                    continue
            r.setdefault("id", str(uuid.uuid4()))
            r.setdefault("created_at", iso(datetime.now(timezone.utc)))
            if table == "church_thread_notes":
                r.setdefault("read_at", None)
            self.t.setdefault(table, []).append(r)
            out.append(r)
        self.writes.append(("post", table, out))
        return json.loads(json.dumps(out))

    def patch(self, path, body, **kw):
        table, params = self._split(path)
        if table in self.down:
            return None
        rows = [r for r in self.t.get(table, []) if all(_match(r, k, v) for k, v in params if k not in SKIP)]
        for r in rows:
            r.update(json.loads(json.dumps(body)))
        self.writes.append(("patch", table, rows))
        return json.loads(json.dumps(rows))

    def delete(self, path, **kw):
        table, params = self._split(path)
        keep = [r for r in self.t.get(table, []) if not all(_match(r, k, v) for k, v in params if k not in SKIP)]
        self.t[table] = keep
        return True

    def written(self, table):
        return [w for w in self.writes if w[1] == table]

    def business(self, b=BIZ):
        return json.loads(json.dumps(self.biz[b]))


@pytest.fixture
def fake(monkeypatch):
    f = Fake()
    monkeypatch.setattr(sb_clients, "sb_get_as_service", f.get)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", f.post)
    monkeypatch.setattr(sb_clients, "sb_patch_as_service", f.patch)
    monkeypatch.setattr(sb_clients, "sb_delete_as_service", f.delete)
    monkeypatch.setenv("CHURCH_THREADS", "on")
    monkeypatch.setenv("MEMBER_QUIET_HOURS", "off")
    ct._READY.update(at=0.0, ok=None)
    ma._OWNER_CACHE.clear()
    monkeypatch.setattr(pn, "VAPID_PRIVATE_KEY", "priv")
    monkeypatch.setattr(pn, "VAPID_PUBLIC_KEY", "pub-key")
    f.pushed = []
    monkeypatch.setattr(pn, "_send_one", lambda row, payload, table="push_subscriptions":
                        f.pushed.append((row.get("contact_id") or row.get("user_id"), payload, table)) or True)
    # Alerts run off the request in a thread; here they run at once.
    monkeypatch.setattr(ct, "_later", lambda fn, *a: fn(*a))
    f.staff = []
    monkeypatch.setattr(pn, "send_to_user", lambda uid, **kw: f.staff.append((uid, kw)) or 1)
    monkeypatch.setattr(ma, "recipients", lambda biz, area: {OWNER, CLERK})
    monkeypatch.setattr(mpt, "_zone", lambda biz: timezone.utc)
    f.person(ANA, "Ana Rivers")
    f.person(BEN, "Ben Stone")
    f.person(CAL, "Cal Moss")
    f.add("groups", id=GROUP, business_id=BIZ, name="Tuesday Night Group", active=True, chat_on=True, kind="small_group",
          join_mode="ask", name_display="full")
    f.add("groups", id=GROUP2, business_id=BIZ, name="Choir", active=True, chat_on=False, kind="team",
          join_mode="ask", name_display="full")
    for c in (ANA, BEN):
        f.add("group_members", group_id=GROUP, business_id=BIZ, contact_id=c, role="member")
    f.add("group_members", group_id=GROUP, business_id=BIZ, contact_id=CAL, role="leader")
    return f


def sub(c, n=1):
    return {"id": f"s-{c}-{n}", "business_id": BIZ, "contact_id": c, "endpoint": f"https://push.example/{c}/{n}",
            "subscription": {"endpoint": f"https://push.example/{c}/{n}"}}


def notes(fake, **want):
    return [r for r in fake.t["church_thread_notes"] if all(r.get(k) == v for k, v in want.items())]


# ─── 1. which notes, which conversation ──────────────────────────────


def test_a_group_url_is_that_groups_thread_everything_else_the_churchs():
    assert ct.thread_for(f"/my/groups/{GROUP}/board") == f"group:{GROUP}"
    assert ct.thread_for(f"/my/groups/{GROUP.upper()}") == f"group:{GROUP}"
    assert ct.thread_for(f"/my/groups/{GROUP}?x=1") == f"group:{GROUP}"
    for url in ("/my/groups", "/my/groups/leaders", "/my/live", "/my", "", None, f"/my/groups/{GROUP}x"):
        assert ct.thread_for(url) == "church", url
    assert ct.inbox_url("church") == "/my/inbox/church"
    assert ct.inbox_url(f"group:{GROUP}") == f"/my/inbox/group/{GROUP}"
    assert ct.is_inbox_url("/my/inbox/church") and not ct.is_inbox_url("/my/inboxes")
    assert "messages" not in ct.THREAD_KINDS and "youth" not in ct.THREAD_KINDS


def test_a_church_wide_note_is_one_row_for_everyone(fake):
    fake.add("member_push_subscriptions", **sub(ANA))
    n = member_push.send(fake.business(), "announcements", title="Picnic Sunday", body="Bring a chair.",
                         url="/my/events", ref_id="ann-1")
    assert n == 1
    rows = notes(fake, kind="announcements")
    assert len(rows) == 1 and rows[0]["contact_id"] is None and rows[0]["thread"] == "church"
    assert rows[0]["direction"] == "church" and rows[0]["title"] == "Picnic Sunday" and rows[0]["url"] == "/my/events"
    assert rows[0]["ref_id"] == "ann-1"


def test_named_people_get_a_row_each_even_without_a_phone(fake):
    fake.add("member_push_subscriptions", **sub(ANA))
    member_push.send(fake.business(), "events", title="Tomorrow: Picnic", body="You said you're coming.",
                     url="/my/events", contact_ids=iter([ANA, BEN, CAL]), ref_id="ev-1")
    rows = notes(fake, kind="events")
    assert sorted(r["contact_id"] for r in rows) == sorted([ANA, BEN, CAL])
    # The push still reached the one phone: the iterator was read twice safely.
    assert [c for c, _, _ in fake.pushed] == [ANA]


def test_a_leaders_board_post_is_its_groups_and_only_its_members(fake):
    for c in (ANA, BEN, CAL):
        fake.add("member_push_subscriptions", **sub(c))
    member_push._tell_group_post(fake.business(), {"id": GROUP, "name": "Tuesday Night Group"}, "post-1",
                                 {"id": CAL, "name": "Cal Moss"}, title="Bring a friend")
    rows = notes(fake, kind="groups")
    assert {r["thread"] for r in rows} == {f"group:{GROUP}"}
    assert sorted(r["contact_id"] for r in rows) == sorted([ANA, BEN])     # never the leader who posted
    payload = fake.pushed[0][1]
    assert payload["title"] == "Tuesday Night Group" and payload["url"] == f"/my/inbox/group/{GROUP}"
    assert payload["body"] == "Cal posted: Bring a friend"


def test_what_isnt_kept(fake):
    fake.add("member_push_subscriptions", **sub(ANA))
    b = fake.business()
    member_push.send(b, "groups", title="Love City Church", body="From your pastors", url="/my/groups",
                     contact_ids=[ANA])                                    # no group url
    member_push.send(b, "messages", title="New message", body="Open the app to read it.",
                     url=f"/my/groups/{GROUP}/chat", contact_ids=[ANA])
    member_push.send(b, "youth", title="Youth", body="New post", url="/my/space?to=youth", contact_ids=[ANA])
    assert fake.t["church_thread_notes"] == []
    # Their lock screens are what they always were.
    assert [p["url"] for _, p, _ in fake.pushed] == ["/my/groups", f"/my/groups/{GROUP}/chat", "/my/space?to=youth"]


# ─── 2. bulk rows ────────────────────────────────────────────────────


def test_every_row_carries_the_same_keys_and_big_lists_go_in_chunks(fake):
    people = [cid(1000 + i) for i in range(1201)]
    member_push.send(fake.business(), "news", title="Love City Church", body="Important: Service at 10",
                     url="/my/news/abc", contact_ids=people, ref_id="news-1")
    posts = [w for w in fake.written("church_thread_notes") if w[0] == "post"]
    assert [len(w[2]) for w in posts] == [500, 500, 201]
    assert not [w for w in fake.writes if w[0] == "refused"]
    keys = {tuple(sorted(k for k in r if k not in ("id", "created_at", "read_at"))) for w in posts for r in w[2]}
    assert len(keys) == 1


def test_a_refused_chunk_never_stops_the_push(fake, monkeypatch):
    fake.add("member_push_subscriptions", **sub(ANA))
    real = fake.post

    def post(path, body, **kw):
        if path.startswith("/church_thread_notes"):
            raise RuntimeError("boom")
        return real(path, body, **kw)
    monkeypatch.setattr(sb_clients, "sb_post_as_service", post)
    assert member_push.send(fake.business(), "live", title="Love City Church is live", url="/my/live") == 1
    assert fake.pushed[0][1]["url"] == "/my/live"           # not recorded: the old lock screen


# ─── 3. the switch ───────────────────────────────────────────────────


def test_the_switch(fake, monkeypatch):
    monkeypatch.delenv("CHURCH_THREADS")
    assert ct.mode() == "owner"
    monkeypatch.setenv("CHURCH_THREADS", "nonsense")
    assert ct.mode() == "off" and not ct.switch_open(BIZ)
    monkeypatch.setenv("CHURCH_THREADS", "owner")
    monkeypatch.setattr(ma, "platform_church", lambda b: b == BIZ)
    assert ct.switch_open(BIZ) and not ct.switch_open(OTHER)
    monkeypatch.setenv("CHURCH_THREADS", "on")
    assert ct.switch_open(OTHER)
    # A sample church is never open.
    fake.biz[BIZ]["is_sample"] = True
    assert not ct.open_for(fake.business())


def test_closed_records_nothing_and_the_note_still_goes(fake, monkeypatch):
    fake.add("member_push_subscriptions", **sub(ANA))
    monkeypatch.setenv("CHURCH_THREADS", "owner")
    monkeypatch.setattr(ma, "platform_church", lambda b: False)
    assert member_push.send(fake.business(), "announcements", title="Picnic", body="Sunday", url="/my/events") == 1
    assert fake.t["church_thread_notes"] == []
    assert fake.pushed[0][1] == {"title": "Picnic", "body": "Sunday", "url": "/my/events", "tag": "announcements-"}
    monkeypatch.setenv("CHURCH_THREADS", "off")
    member_push.send(fake.business(), "announcements", title="Picnic 2", url="/my/events")
    assert fake.t["church_thread_notes"] == []


def test_missing_tables_keep_it_quiet(fake):
    fake.add("member_push_subscriptions", **sub(ANA))
    fake.down |= {"church_thread_notes", "church_thread_reads"}
    assert member_push.send(fake.business(), "live", title="Love City Church is live", url="/my/live") == 1
    assert fake.pushed[0][1]["url"] == "/my/live"


def test_a_ref_already_sent_records_nothing(fake):
    fake.add("member_push_sends", business_id=BIZ, kind="sermons", ref_id="sermon:1")
    assert member_push.send(fake.business(), "sermons", title="New: Hope", url="/my/sermons/1", ref_id="sermon:1") == 0
    assert fake.t["church_thread_notes"] == []


# ─── 4. the lock screen ──────────────────────────────────────────────


def test_a_church_note_reads_like_a_text_from_the_church(fake):
    fake.add("member_push_subscriptions", **sub(ANA))
    b = fake.business()
    member_push.send(b, "events", title="Tomorrow: Picnic", body="You said you're coming.", url="/my/events",
                     contact_ids=[ANA], ref_id="ev-2", tag="ev")
    assert fake.pushed[-1][1] == {"title": "Love City Church", "body": "Tomorrow: Picnic — You said you're coming.",
                                  "url": "/my/inbox/church", "tag": "ev"}
    # A title that is the church's name already isn't said twice.
    member_push.send(b, "news", title="Love City Church", body="Important: Service at 10", url="/my/news/9",
                     contact_ids=[ANA], ref_id="n-9")
    assert fake.pushed[-1][1]["body"] == "Important: Service at 10"
    # Long words are cut to the lock screen's length.
    member_push.send(b, "announcements", title="T" * 60, body="x" * 400, url="/my", ref_id="a-long")
    assert len(fake.pushed[-1][1]["body"]) == member_push.BODY_MAX
    # The church's name is read when the row in hand has none.
    member_push.send({k: v for k, v in b.items() if k != "name"}, "announcements", title="Hi", url="/my",
                     ref_id="a-noname")
    assert fake.pushed[-1][1]["title"] == "Love City Church"


def test_quiet_hours_hold_the_texted_note_and_the_morning_opens_the_inbox(fake, monkeypatch):
    fake.add("member_push_subscriptions", **sub(ANA))
    monkeypatch.setattr(member_push, "quiet_hour", lambda business, now=None: True)
    member_push.send(fake.business(), "groups", title="Tuesday Night Group", body="Cal asked the group to pray",
                     url=f"/my/groups/{GROUP}/prayer", contact_ids=[ANA], ref_id="gp-1", tag=f"group-prayer-{GROUP}")
    member_push.send(fake.business(), "news", title="Love City Church", body="Happy birthday, Ben", url="/my",
                     contact_ids=[ANA], ref_id="bd-1", tag="news-bd")
    held = fake.t["member_push_held"]
    assert [h["url"] for h in held] == [f"/my/inbox/group/{GROUP}", "/my/inbox/church"]
    assert held[0]["title"] == "Tuesday Night Group" and held[1]["title"] == "Love City Church"
    assert fake.pushed == []
    # An after-hours alert rings now, and still reads like a text.
    member_push.send(fake.business(), "groups", title="Tuesday Night Group", body="Cal posted: Pray tonight",
                     url=f"/my/groups/{GROUP}/board", contact_ids=[ANA], ref_id="gp-2", ring=True)
    assert fake.pushed[-1][1]["title"] == "After-hours alert · Tuesday Night Group"
    assert fake.pushed[-1][1]["url"] == f"/my/inbox/group/{GROUP}"
    fake.pushed.clear()
    # The morning: two inbox notes open the inbox.
    monkeypatch.setattr(member_push, "quiet_hour", lambda business, now=None: False)
    for h in held:
        h["created_at"] = iso(NOW)
    assert member_push.sweep_held() == 1
    assert fake.pushed[-1][1]["url"] == "/my/inbox" and fake.pushed[-1][1]["title"] == "While you were resting"


# ─── 5. the member's pages ───────────────────────────────────────────


def _app(fake, monkeypatch, me_id, space=""):
    monkeypatch.setenv("CUSTOMER_TOKEN_SECRET", "test-root-secret")
    monkeypatch.setattr(mp, "_church_for_request", lambda req: {"business": {
        k: v for k, v in fake.business().items() if k != "owner_id"}, "site": {}})
    import rate_limit
    monkeypatch.setattr(rate_limit, "allow_strict", lambda b, k, **kw: True)

    def session(request, church):
        if not me_id:
            return None
        row = next(dict(c) for c in fake.t["contacts"] if c["id"] == me_id)
        return {"claims": {}, "people": [row], "me": row}
    monkeypatch.setattr(mp, "_session_for", session)
    import member_spaces as msp

    async def resolve(b, me, wanted=""):
        return msp._placed(me, space, {"youth": {}} if space == "youth" else {}, space == "kids")
    monkeypatch.setattr(msp, "resolve_async", resolve)

    async def leads(*a, **kw):
        return False
    monkeypatch.setattr(mp, "_leads", leads)
    app = FastAPI()
    app.include_router(mpt.router)

    @app.get("/my/{rest:path}")
    async def page(request: Request, rest: str):
        return await mp.serve(request, "/my/" + rest)
    return TestClient(app, base_url=f"https://{HOST}")


def _seed_conversation(fake):
    fake.note(contact_id=None, kind="live", title="Love City Church is live", body="Sunday service",
              url="/my/live", created_at=iso(NOW - timedelta(days=1, hours=2)))
    fake.note(contact_id=None, kind="announcements", title="Old news", body="From last spring",
              created_at=iso(NOW - timedelta(days=90)))
    fake.note(contact_id=ANA, kind="events", title="Tomorrow: Picnic", body="You said you're coming.",
              url="/my/events", created_at=iso(NOW - timedelta(hours=5)))
    fake.note(contact_id=ANA, direction="member", kind="message", body="Can I bring my sister?",
              author_name="Ana", created_at=iso(NOW - timedelta(hours=4)))
    fake.note(contact_id=ANA, direction="member", kind="message", body="something held", held=True,
              author_name="Ana", created_at=iso(NOW - timedelta(hours=3, minutes=30)))
    fake.note(contact_id=ANA, kind="reply", body="Of course! See you there.", author_name="Maria",
              author_user_id=CLERK, created_at=iso(NOW - timedelta(hours=3)))
    fake.note(contact_id=BEN, kind="events", title="Ben's own note", body="not Ana's",
              created_at=iso(NOW - timedelta(hours=2)))
    fake.note(contact_id=ANA, thread=f"group:{GROUP}", kind="groups", title="Tuesday Night Group",
              body="Cal posted: Bring a friend", url=f"/my/groups/{GROUP}/board", created_at=iso(NOW - timedelta(hours=1)))
    fake.note(contact_id=ANA, thread=f"group:{GROUP2}", kind="groups", title="Choir", body="Left this group",
              url=f"/my/groups/{GROUP2}/board", created_at=iso(NOW - timedelta(minutes=30)))


def test_the_inbox_lists_the_church_first_then_my_groups(fake, monkeypatch):
    _seed_conversation(fake)
    page = _app(fake, monkeypatch, ANA).get("/my/inbox")
    assert page.status_code == 200
    html = page.text
    assert "From your church" in html
    church_at, group_at = html.index('href="/my/inbox/church"'), html.index(f'href="/my/inbox/group/{GROUP}"')
    assert church_at < group_at
    assert "Love City Church" in html and "Tuesday Night Group" in html
    assert "Maria: Of course! See you there." in html          # the church row's newest line
    assert "Cal posted: Bring a friend" in html and "Tuesday Night Group — Cal" not in html   # the name isn't said twice
    assert "Choir" not in html                                  # a group Ana isn't in
    assert "Ben&#x27;s own note" not in html and "Ben's own note" not in html


def test_the_church_conversation(fake, monkeypatch):
    _seed_conversation(fake)
    c = _app(fake, monkeypatch, ANA)
    html = c.get("/my/inbox/church").text
    # In time order, with day separators.
    order = [html.index(s) for s in ("Love City Church is live", "Tomorrow: Picnic", "Can I bring my sister?",
                                     "Of course! See you there.")]
    assert order == sorted(order)
    assert "Yesterday" in html and "Today" in html
    assert "Old news" not in html                               # church-wide, older than 60 days
    assert "not Ana" not in html and "Bring a friend" not in html
    # The church's notes on the left with a way to what they're about; mine on the right; the office's reply named.
    assert 'class="ct-open" href="/my/live">Watch' in html and 'href="/my/events">See the event' in html
    assert '<li class="mb-msg mb-mine"><span class="mb-msg-body">Can I bring my sister?' in html
    assert "Held for review. Only you can see it." in html
    assert '<span class="mb-msg-who">Maria</span>' in html
    # The box at the foot.
    assert 'action="/my/inbox/church/send"' in html and 'placeholder="Message the church office"' in html
    # Opening it marks it read.
    reads = fake.t["church_thread_reads"]
    assert len(reads) == 1 and reads[0]["contact_id"] == ANA and reads[0]["thread"] == "church"


def test_a_groups_conversation_is_for_its_members_only(fake, monkeypatch):
    _seed_conversation(fake)
    ana = _app(fake, monkeypatch, ANA)
    page = ana.get(f"/my/inbox/group/{GROUP}")
    assert page.status_code == 200
    assert "Cal posted: Bring a friend" in page.text and 'href="/my/groups/' + GROUP + '/board">Open the group' in page.text
    assert "/my/inbox/church/send" not in page.text             # no box
    # Messaging is off at this church: no chat link. On, with the group's chat on: there is.
    assert "Open the group chat" not in page.text
    fake.biz[BIZ]["settings"]["messaging"] = {"enabled": True}
    page = _app(fake, monkeypatch, ANA).get(f"/my/inbox/group/{GROUP}")
    assert f'href="/my/groups/{GROUP}/chat"' in page.text and "Open the group chat" in page.text
    assert any(r["thread"] == f"group:{GROUP}" for r in fake.t["church_thread_reads"])
    # Not in the group: 404, and nothing is read out.
    assert ana.get(f"/my/inbox/group/{GROUP2}").status_code == 404
    dee = fake.person(DEE, "Dee Lane")
    r = _app(fake, monkeypatch, DEE).get(f"/my/inbox/group/{GROUP}")
    assert r.status_code == 404 and "Bring a friend" not in r.text
    assert _app(fake, monkeypatch, ANA).get("/my/inbox/group/not-a-uuid").status_code == 404


def test_closed_or_kids_goes_back_to_my(fake, monkeypatch):
    monkeypatch.setenv("CHURCH_THREADS", "off")
    for path in ("/my/inbox", "/my/inbox/church", f"/my/inbox/group/{GROUP}"):
        r = _app(fake, monkeypatch, ANA).get(path, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/my", path
    assert "From your church" not in _app(fake, monkeypatch, ANA).get("/my/me").text
    monkeypatch.setenv("CHURCH_THREADS", "on")
    for space in ("kids", "youth"):
        r = _app(fake, monkeypatch, ANA, space).get("/my/inbox", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/my", space
    # Missing tables: quiet too.
    fake.down.add("church_thread_notes")
    ct._READY.update(at=0.0, ok=None)
    assert _app(fake, monkeypatch, ANA).get("/my/inbox", follow_redirects=False).headers["location"] == "/my"


def test_me_has_the_line_and_home_has_the_card_while_something_is_new(fake, monkeypatch):
    me = _app(fake, monkeypatch, ANA).get("/my/me").text
    assert 'href="/my/inbox"' in me and "From your church" in me
    assert mpt.home_card(fake.business(), {"id": ANA, "name": "Ana Rivers"}) == ""     # nothing yet
    _seed_conversation(fake)
    card = mpt.home_card(fake.business(), {"id": ANA, "name": "Ana Rivers"})
    assert 'href="/my/inbox"' in card and "Love City Church" in card
    assert "4 new" in card                                      # live, picnic, reply, the group's post
    assert "Cal posted: Bring a friend" in card                 # the newest one
    for t in ("church", f"group:{GROUP}"):
        ct.mark_read(BIZ, ANA, t)
    assert mpt.home_card(fake.business(), {"id": ANA, "name": "Ana Rivers"}) == ""
    html = mp.render_home(fake.business(), {}, me={"id": ANA, "name": "Ana Rivers"}, occasions=[], groups=[],
                          library=None, give_url="", inbox='<a class="ct-home" href="/my/inbox">x</a>')
    assert 'class="ct-home" href="/my/inbox"' in html


def test_a_teen_can_write_to_the_church(fake, monkeypatch):
    teen = f"{NOW.year - 15}-01-01"
    fake.person(DEE, "Dee Lane", birthdate=teen)
    r = _app(fake, monkeypatch, DEE).get("/my/inbox/church")
    assert r.status_code == 200 and 'action="/my/inbox/church/send"' in r.text


# ─── 6. writing to the office ────────────────────────────────────────


@pytest.fixture
def screen(monkeypatch):
    import msg_screen
    said = {"verdict": "ok"}

    async def fake_screen(biz, text):
        if said["verdict"] == "down":
            raise msg_screen.ScreenUnavailable("down")
        return said["verdict"]
    monkeypatch.setattr(msg_screen, "screen", fake_screen)
    return said


def _send(c, body):
    return c.post("/my/inbox/church/send", data={"body": body}, headers=ORIGIN, follow_redirects=False)


def test_a_message_reaches_the_office(fake, monkeypatch, screen):
    c = _app(fake, monkeypatch, ANA)
    r = _send(c, "  Can I bring\r\n\r\n\r\nmy sister?  ")
    assert r.headers["location"] == "/my/inbox/church?done=ct_sent"
    rows = notes(fake, direction="member")
    assert len(rows) == 1
    row = rows[0]
    assert row["contact_id"] == ANA and row["thread"] == "church" and row["kind"] == "message"
    assert row["body"] == "Can I bring\n\nmy sister?" and row["held"] is False and row["author_name"] == "Ana"
    # The office hears by the staff path: a first name, never the words.
    assert sorted(u for u, _ in fake.staff) == sorted([OWNER, CLERK])
    kw = fake.staff[0][1]
    assert kw["title"] == "New message in the app" and kw["body"] == "Ana wrote to the church."
    assert "sister" not in json.dumps(fake.staff)
    assert kw["business_id"] == BIZ and kw["nav"] == ct.OFFICE_NAV
    assert fake.pushed == []                                    # nothing on any member's phone
    assert fake.t["sms_messages"] == [] and fake.t["sms_consents"] == []


def test_length_and_pace(fake, monkeypatch, screen):
    c = _app(fake, monkeypatch, ANA)
    assert _send(c, "   ").headers["location"] == "/my/inbox/church?err=ct_empty"
    assert _send(c, "x" * (ct.BODY_MAX + 1)).headers["location"] == "/my/inbox/church?err=ct_long"
    assert _send(c, "first").headers["location"].endswith("done=ct_sent")
    assert _send(c, "too quick").headers["location"].endswith("err=ct_gap")
    for r in notes(fake, direction="member"):
        r["created_at"] = iso(NOW - timedelta(minutes=10))
    for i in range(ct.DAY_MAX - 1):
        fake.note(contact_id=ANA, direction="member", kind="message", body=f"m{i}",
                  created_at=iso(NOW - timedelta(hours=1, minutes=i)))
    assert _send(c, "one more").headers["location"].endswith("err=ct_day")
    assert len(notes(fake, direction="member")) == ct.DAY_MAX
    # Yesterday's don't count.
    for r in notes(fake, direction="member"):
        r["created_at"] = iso(NOW - timedelta(days=2))
    assert _send(c, "a new day").headers["location"].endswith("done=ct_sent")


def test_screen_down_saves_nothing(fake, monkeypatch, screen):
    screen["verdict"] = "down"
    r = _send(_app(fake, monkeypatch, ANA), "Hello")
    assert r.headers["location"] == "/my/inbox/church?err=screen_off"
    assert notes(fake, direction="member") == [] and fake.staff == []


def test_harm_is_held_and_the_reviewers_are_told(fake, monkeypatch, screen):
    screen["verdict"] = "harm"
    fake.add("msg_safety_officers", business_id=BIZ, user_id=OFFICER)
    r = _send(_app(fake, monkeypatch, ANA), "something harmful")
    assert r.headers["location"] == "/my/inbox/church?done=held"
    row = notes(fake, direction="member")[0]
    assert row["held"] is True
    assert [u for u, _ in fake.staff] == [OFFICER]              # the officers, not the office
    assert "harmful" not in json.dumps(fake.staff) and "Ana" not in json.dumps(fake.staff)
    # With no officers named, the owner reviews.
    fake.t["msg_safety_officers"].clear()
    fake.staff.clear()
    row["created_at"] = iso(NOW - timedelta(minutes=5))
    _send(_app(fake, monkeypatch, ANA), "again")
    assert [u for u, _ in fake.staff] == [OWNER]


def test_crisis_words_deliver_with_988_and_the_pastors_note(fake, monkeypatch, screen):
    screen["verdict"] = "self_harm"
    c = _app(fake, monkeypatch, ANA)
    r = _send(c, "I want to die")
    assert r.headers["location"] == "/my/inbox/church?done=care"
    assert notes(fake, direction="member")[0]["held"] is False
    care = fake.t["ministry_care_requests"]
    assert len(care) == 1 and care[0]["contact_id"] == ANA and "want to die" not in json.dumps(care)
    assert "988" in c.get("/my/inbox/church?done=care").text


def test_a_sample_church_records_and_sends_nothing(fake, monkeypatch, screen):
    import asyncio
    fake.biz[BIZ]["is_sample"] = True
    ok, code = asyncio.run(mpt.send_message(fake.business(), {"id": ANA, "name": "Ana Rivers"}, "Hello"))
    assert not ok and notes(fake, direction="member") == [] and fake.staff == []
    r = _send(_app(fake, monkeypatch, ANA), "Hello")
    assert r.headers["location"] == "/my"
    fake.add("member_push_subscriptions", **sub(ANA))
    member_push.send(fake.business(), "announcements", title="Hi", url="/my")
    assert fake.t["church_thread_notes"] == [] and fake.pushed == []


def test_another_site_cant_post_and_a_preview_saves_nothing(fake, monkeypatch, screen):
    c = _app(fake, monkeypatch, ANA)
    r = c.post("/my/inbox/church/send", data={"body": "hi"}, headers={"origin": "https://evil.example"},
               follow_redirects=False)
    assert r.status_code == 403
    r = c.post("/my/inbox/church/send", data={"body": "hi"}, follow_redirects=False)   # no origin
    assert r.status_code == 303 and r.headers["location"].endswith("done=ct_sent")
    assert len(notes(fake, direction="member")) == 1


# ─── 7. the office API ───────────────────────────────────────────────


def _office(fake, monkeypatch, user_id, roles=None):
    import business_access
    from auth_supabase import AuthedUser, require_user
    roles = roles if roles is not None else {(BIZ, OWNER): "owner", (BIZ, CLERK): "member", (BIZ, OFFICER): "viewer",
                                             (OTHER, STRANGER): "owner"}
    monkeypatch.setattr(business_access, "_resolve_role", lambda b, u: roles.get((b, u)))
    app = FastAPI()
    app.include_router(ct.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id=user_id, email=f"{user_id}@example.com",
                                                                role="authenticated")
    return TestClient(app)


def test_another_church_and_a_viewer_who_writes_are_refused(fake, monkeypatch):
    s = _office(fake, monkeypatch, STRANGER)
    for path in (f"/church-threads/{BIZ}/status", f"/church-threads/{BIZ}", f"/church-threads/{BIZ}/{ANA}"):
        assert s.get(path).status_code == 403, path
    assert s.post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "hi"}).status_code == 403
    v = _office(fake, monkeypatch, OFFICER)
    assert v.get(f"/church-threads/{BIZ}/status").status_code == 200
    assert v.post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "hi"}).status_code == 403
    assert v.get("/church-threads/not-a-uuid/status").status_code == 400


def test_status_is_open_only_with_the_switch_and_the_tables(fake, monkeypatch):
    c = _office(fake, monkeypatch, OWNER)
    assert c.get(f"/church-threads/{BIZ}/status").json() == {"open": True}
    fake.down.add("church_thread_reads")
    assert c.get(f"/church-threads/{BIZ}/status").json() == {"open": False}
    fake.down.clear()
    monkeypatch.setenv("CHURCH_THREADS", "owner")
    monkeypatch.setattr(ma, "platform_church", lambda b: False)
    assert c.get(f"/church-threads/{BIZ}/status").json() == {"open": False}
    assert c.get(f"/church-threads/{BIZ}").json()["threads"] == []
    assert c.post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "hi"}).status_code == 409


def test_the_office_list(fake, monkeypatch):
    _seed_conversation(fake)
    fake.note(contact_id=BEN, direction="member", kind="message", body="Ben here", author_name="Ben",
              created_at=iso(NOW - timedelta(minutes=10)), read_at=iso(NOW - timedelta(minutes=5)))
    fake.note(contact_id=CAL, direction="member", kind="message", body="only held", held=True,
              created_at=iso(NOW - timedelta(minutes=1)))
    got = _office(fake, monkeypatch, CLERK).get(f"/church-threads/{BIZ}").json()
    assert list(got) == ["threads"]
    threads = got["threads"]
    assert [t["contact_id"] for t in threads] == [BEN, ANA]     # newest first; Cal's only message is held
    ben, ana = threads
    assert set(ben) == {"contact_id", "name", "last", "unread"}
    assert ben == {"contact_id": BEN, "name": "Ben Stone", "unread": 0,
                   "last": {"direction": "member", "body": "Ben here", "created_at": ben["last"]["created_at"]}}
    assert ana["name"] == "Ana Rivers" and ana["unread"] == 1   # the held one doesn't count
    assert ana["last"]["direction"] == "church" and ana["last"]["body"] == "Of course! See you there."
    # An officer sees the held ones too.
    fake.add("msg_safety_officers", business_id=BIZ, user_id=OFFICER)
    officer = _office(fake, monkeypatch, OFFICER).get(f"/church-threads/{BIZ}").json()["threads"]
    assert officer[0]["contact_id"] == CAL and officer[0]["unread"] == 0


def test_one_persons_conversation(fake, monkeypatch):
    _seed_conversation(fake)
    got = _office(fake, monkeypatch, CLERK).get(f"/church-threads/{BIZ}/{ANA}").json()
    assert set(got) == {"contact", "notes"}
    assert got["contact"] == {"id": ANA, "name": "Ana Rivers"}
    bodies = [n["body"] for n in got["notes"]]
    assert bodies == ["You said you're coming.", "Can I bring my sister?", "Of course! See you there."]  # oldest first
    assert set(got["notes"][0]) == {"id", "direction", "kind", "title", "body", "url", "author_name", "created_at", "held"}
    # Reading it marks Ana's messages read (not the held one).
    ana_msgs = notes(fake, contact_id=ANA, direction="member")
    assert [bool(r["read_at"]) for r in ana_msgs] == [True, False]
    # The owner (no officers named) reviews, so sees the held one.
    owner = _office(fake, monkeypatch, OWNER).get(f"/church-threads/{BIZ}/{ANA}").json()["notes"]
    assert [n["held"] for n in owner].count(True) == 1
    # Someone not in the church's records.
    assert _office(fake, monkeypatch, CLERK).get(f"/church-threads/{BIZ}/{cid(99)}").status_code == 404


def test_a_reply_reaches_the_members_phone_like_a_text(fake, monkeypatch):
    fake.add("member_push_subscriptions", **sub(ANA))
    fake.add("business_users", business_id=BIZ, user_id=CLERK, status="active", name="Maria Lopez", role="member")
    c = _office(fake, monkeypatch, CLERK)
    r = c.post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "  Of course!\n See you there. "})
    assert r.status_code == 200
    got = r.json()
    assert got["ok"] is True and set(got["note"]) == {"id", "direction", "kind", "title", "body", "url", "author_name",
                                                       "created_at", "held"}
    assert got["note"]["direction"] == "church" and got["note"]["kind"] == "reply"
    assert got["note"]["author_name"] == "Maria" and got["note"]["body"] == "Of course!\nSee you there."
    row = notes(fake, kind="reply")[0]
    assert row["author_user_id"] == CLERK and row["thread"] == "church" and row["contact_id"] == ANA
    assert fake.pushed == [(ANA, {"title": "Love City Church", "body": "Of course! See you there.",
                                  "url": "/my/inbox/church", "tag": "church-thread"}, "member_push_subscriptions")]
    assert fake.t["sms_messages"] == [] and fake.t["sms_consents"] == []
    # The church's own "messages" switch isn't needed; the member's own off is respected.
    fake.biz[BIZ]["settings"]["member_portal"]["notifications"] = {}
    c.post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "still reaches you"})
    assert len(fake.pushed) == 2
    fake.add("member_push_prefs", business_id=BIZ, contact_id=ANA, off=["messages"])
    c.post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "quiet"})
    assert len(fake.pushed) == 2 and len(notes(fake, kind="reply")) == 3
    # The owner's name comes from the church's settings.
    fake.biz[BIZ]["settings"]["practitioner_name"] = "Kevin Parker"
    o = _office(fake, monkeypatch, OWNER).post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "hi"}).json()
    assert o["note"]["author_name"] == "Kevin"


def test_a_reply_must_be_one_to_a_thousand_characters(fake, monkeypatch):
    c = _office(fake, monkeypatch, CLERK)
    assert c.post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "  "}).status_code == 400
    assert c.post(f"/church-threads/{BIZ}/{ANA}/reply", json={"body": "x" * 1001}).status_code == 400
    assert c.post(f"/church-threads/{BIZ}/{cid(99)}/reply", json={"body": "hi"}).status_code == 404
    assert fake.t["church_thread_notes"] == []


def test_the_routes_are_mounted_before_the_catch_all():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    last = src.index("app.include_router(public_site_router)")
    assert src.index("app.include_router(church_threads_router)") < last
    assert src.index("app.include_router(member_portal_threads_router)") < last
    assert src.rstrip().splitlines()[-1] != ""
