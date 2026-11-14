"""New here (2026-11-14): a guest texts the church's word to its own number.

Kevin: "the new here for guest is very important" → the canvas "New Here Guest
Texts" → "build this". Pinned here:
  1. The church's words: defaults, tidying, the word, the first name, the link.
  2. When the texts go: thank-you after church (never late), Monday 10 AM,
     the Thursday before the next Sunday, on the church's clock.
  3. A guest texts the word: a guest is made, a code kept, three texts
     scheduled once per visit, the welcome back with the card's link.
     Anything else (not a church, off, not its word, STOP) is an ordinary text.
  4. The scheduled texts read everything again at send time.
  5. The card: names the guest, keeps a prayer for the pastors only, hands
     the follow-up to a leader without the prayer, never puts a name or a
     number in the address.
  6. The room: who reads, who changes it, what a saved setting must keep.
  7. The wiring: sms_routing, chief_scheduler, public_site, the app.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import new_here as nh  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
GUEST = "9a000000-0000-4000-8000-000000000001"
PHONE = "+12315550142"
ET = ZoneInfo("America/New_York")
ON = {"new_here": {"on": True}}
CHURCH = {"id": BIZ, "name": "Grace Hill Church", "type": "church", "settings": ON, "owner_id": "o1"}


def run(x):
    return asyncio.run(x)


def at(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


# ── 1. the church's words ─────────────────────────────────────────────

def test_the_defaults_and_what_a_saved_setting_can_be():
    s = nh.settings_of({"settings": {}})
    assert s["on"] is False and s["word"] == "NEW" and s["thanks"]["hours"] == 3
    assert nh.CARD_LINK in s["welcome"] and "STOP" in s["welcome"]
    assert all(s[step]["on"] for step in nh.STEPS)
    bad = nh.settings_of({"settings": {"new_here": {"on": True, "word": "STOP", "thanks": {"hours": 40},
                                                    "monday": {"on": False}, "invite": "nope"}}})
    assert bad["on"] and bad["word"] == "NEW"                     # a reserved word is never the church's
    assert bad["thanks"]["hours"] == 6 and bad["monday"]["on"] is False and bad["invite"]["on"] is True
    assert nh.settings_of({"settings": {"new_here": {"word": "hello"}}})["word"] == "HELLO"


def test_the_word_and_the_fill():
    s = {"word": "NEW"}
    assert [nh.is_word(s, w) for w in ("NEW", "new!", " New. ", "new here", "news", "")] == [
        True, True, True, False, False, False]
    assert nh.fill("Hi {first name}, welcome", name="Dana") == "Hi Dana, welcome"
    assert nh.fill("Hi {first name}, welcome") == "Hi, welcome"
    assert nh.fill("Thank you for coming today, {first name}! Bye") == "Thank you for coming today! Bye"
    assert nh.fill("Card: {card link} STOP", link="https://g.church/new/ABC") == "Card: https://g.church/new/ABC STOP"
    assert nh.first_name("Dana Reyes") == "Dana" and nh.first_name("+12315550142") == ""


# ── 2. when the texts go ──────────────────────────────────────────────

@pytest.fixture
def eastern(monkeypatch):
    monkeypatch.setattr(nh, "tz_of", lambda business: ET)


def test_a_sunday_morning_guest(eastern):
    s = nh.settings_of({"settings": ON})
    got = {k: v.astimezone(ET) for k, v in nh.plan_times(CHURCH, at(2026, 11, 15, 10, 42), s).items()}
    assert got["thanks"] == at(2026, 11, 15, 13, 42)              # 3 hours after their text
    assert got["monday"] == at(2026, 11, 16, 10)                  # the next morning
    assert got["invite"] == at(2026, 11, 19, 18)                  # Thursday before next Sunday


def test_never_late_never_today_for_monday(eastern):
    s = nh.settings_of({"settings": {"new_here": {"on": True, "thanks": {"hours": 6}}}})
    got = nh.plan_times(CHURCH, at(2026, 11, 15, 16, 0), s)
    assert got["thanks"].astimezone(ET) == at(2026, 11, 15, 19, 45)      # held to 7:45 PM
    assert "thanks" not in nh.plan_times(CHURCH, at(2026, 11, 15, 19, 30), s)   # too late: no thank-you
    wed = nh.plan_times(CHURCH, at(2026, 11, 18, 19, 0), s)               # a Wednesday night service
    assert wed["monday"].astimezone(ET) == at(2026, 11, 23, 10)
    assert wed["invite"].astimezone(ET) == at(2026, 11, 26, 18)           # not the next day
    mon = nh.plan_times(CHURCH, at(2026, 11, 16, 9, 0), s)
    assert mon["monday"].astimezone(ET) == at(2026, 11, 23, 10)           # never the same day
    off = nh.settings_of({"settings": {"new_here": {"on": True, "monday": {"on": False}}}})
    assert "monday" not in nh.plan_times(CHURCH, at(2026, 11, 15, 10), off)


# ── 3. a guest texts the word ─────────────────────────────────────────

@pytest.fixture
def db(monkeypatch, eastern):
    state = {"biz": dict(CHURCH), "contacts": [], "opt_outs": [], "posts": [], "patches": [], "switched": True}

    def rows(path):
        if path.startswith("/businesses"):
            return [state["biz"]]
        if path.startswith("/sms_opt_outs"):
            return list(state["opt_outs"])
        if path.startswith("/contacts"):
            found = [dict(c) for c in state["contacts"]]
            if "metadata->new_here->>code=eq." in path:
                code = path.split("metadata->new_here->>code=eq.")[1].split("&")[0]
                found = [c for c in found if ((c.get("metadata") or {}).get("new_here") or {}).get("code") == code]
            return found
        if path.startswith("/sms_numbers"):
            return [{"phone_number": "+12315550199"}]
        if path.startswith("/attendance"):
            return list(state.get("attendance", []))
        if path.startswith("/church_follow_ups"):
            return list(state.get("follows", []))
        raise AssertionError(path)

    def post(path, row, prefer="return=representation", **kw):
        state["posts"].append((path, row))
        if path == "/contacts":
            made = {"id": GUEST, "metadata": {}, **row}
            state["contacts"].append(made)
            return [made]
        return [{"id": "row", **row}]

    def patch(path, row, **kw):
        state["patches"].append((path, row))
        if path.startswith("/contacts") and state["contacts"]:
            state["contacts"][0].update(row)
        return [row]

    monkeypatch.setattr(nh, "_rows", rows)
    monkeypatch.setattr(nh.sb_clients, "sb_post_as_service", post)
    monkeypatch.setattr(nh.sb_clients, "sb_patch_as_service", patch)
    monkeypatch.setattr(nh, "switched_on", lambda bid: state["switched"])
    monkeypatch.setattr(nh, "card_link", lambda bid, code: f"https://gracehill.church/new/{code}")
    return state


def _scheduled(state):
    return [r for p, r in state["posts"] if p == "/chief_scheduled_actions"]


def test_a_guest_texts_new(db):
    hit = nh.on_text(BIZ, PHONE, "New")
    assert hit["name"] == "Grace Hill Church"
    assert hit["text"].startswith("Welcome! So glad you're here. Tell us about you: https://gracehill.church/new/")
    assert "STOP" in hit["text"] and "{" not in hit["text"]
    made = [r for p, r in db["posts"] if p == "/contacts"][0]
    assert made == {"business_id": BIZ, "name": PHONE, "phone": PHONE, "status": "lead", "source": "new_here"}
    mine = db["contacts"][0]["metadata"]["new_here"]
    assert len(mine["code"]) == nh.CODE_LEN and mine["visits"] == 1 and mine["texted_at"]
    assert mine["code"] in hit["text"]
    rows = _scheduled(db)
    assert sorted(r["action"]["step"] for r in rows) == ["invite", "monday", "thanks"]
    assert all(r["action"]["type"] == nh.KIND and r["action"]["contact_id"] == GUEST and r["action"]["phone"] == PHONE
               and r["business_id"] == BIZ for r in rows)


def test_texting_it_again_this_week_is_the_same_visit(db):
    first = nh.on_text(BIZ, PHONE, "NEW")
    second = nh.on_text(BIZ, PHONE, "new!")
    assert len(_scheduled(db)) == 3                                # nothing scheduled twice
    assert db["contacts"][0]["metadata"]["new_here"]["visits"] == 1
    assert first["text"] == second["text"]                         # the same card


def test_anything_else_is_an_ordinary_text(db):
    assert nh.on_text(BIZ, PHONE, "new here, is there parking?") is None   # not one word: no read at all
    assert nh.on_text(BIZ, PHONE, "HELLO") is None                       # not its word
    db["biz"]["settings"] = {"new_here": {"on": False}}
    assert nh.on_text(BIZ, PHONE, "NEW") is None                         # the church hasn't turned it on
    db["biz"]["settings"] = ON
    db["switched"] = False
    assert nh.on_text(BIZ, PHONE, "NEW") is None                         # not switched on for the church
    db["switched"] = True
    db["opt_outs"] = [{"phone": PHONE}]
    assert nh.on_text(BIZ, PHONE, "NEW") is None                         # they said STOP
    db["opt_outs"] = []
    db["biz"] = {**CHURCH, "type": "salon"}
    assert nh.on_text(BIZ, PHONE, "NEW") is None                         # churches only
    assert db["posts"] == []


def test_a_church_can_pick_its_word(db):
    db["biz"]["settings"] = {"new_here": {"on": True, "word": "HELLO"}}
    assert nh.on_text(BIZ, PHONE, "NEW") is None
    assert nh.on_text(BIZ, PHONE, "hello")["name"] == "Grace Hill Church"


# ── 4. the scheduled texts ────────────────────────────────────────────

@pytest.fixture
def sender(db, monkeypatch):
    import sms_alerts
    import sms_routing
    import sms_service
    sent = {"texts": [], "stored": [], "stopped": False, "now": at(2026, 11, 16, 10)}
    db["contacts"].append({"id": GUEST, "name": "Dana Reyes", "phone": PHONE, "metadata": {}})

    async def send(phone, body, business_id=None, client=None):
        sent["texts"].append((phone, body, business_id))
        return "SM1"

    async def store(client, *a, **kw):
        sent["stored"].append((a, kw))

    async def stopped(client, phone, business_id=None):
        return sent["stopped"]

    monkeypatch.setattr(sms_routing, "_send_platform_sms", send)
    monkeypatch.setattr(sms_service, "_store_sms", store)
    monkeypatch.setattr(sms_service, "is_opted_out", stopped)
    monkeypatch.setattr(sms_alerts, "alerts_enabled", lambda: True)
    monkeypatch.setattr(nh, "_now", lambda: sent["now"].astimezone(timezone.utc))
    return sent


def action(step="monday"):
    return {"type": nh.KIND, "step": step, "contact_id": GUEST, "phone": PHONE, "texted_at": "2026-11-15T15:42:00Z"}


def test_a_scheduled_text_goes_in_the_churchs_words(sender, db):
    ok, what = run(nh.run_scheduled(CHURCH, action("monday")))
    assert ok and "monday" in what
    [(phone, body, bid)] = sender["texts"]
    assert phone == PHONE and bid == BIZ
    assert body.startswith("Grace Hill Church: Hi Dana, is there anything we can pray with you about")
    (args, kw), = sender["stored"]
    assert args[1] == GUEST and kw["sent_by"] == "system"


def test_a_scheduled_text_reads_everything_again(sender, db):
    db["biz"]["settings"] = {"new_here": {"on": True, "monday": {"on": False}}}
    assert run(nh.run_scheduled(CHURCH, action("monday")))[0] is True and sender["texts"] == []   # turned off
    db["biz"]["settings"] = ON
    sender["stopped"] = True
    assert "STOP" in run(nh.run_scheduled(CHURCH, action("monday")))[1] and sender["texts"] == []
    sender["stopped"] = False
    sender["now"] = at(2026, 11, 16, 21)
    assert "Quiet hours" in run(nh.run_scheduled(CHURCH, action("monday")))[1] and sender["texts"] == []
    sender["now"] = at(2026, 11, 19, 18)
    db["attendance"] = [{"id": "a1"}]
    assert "came back" in run(nh.run_scheduled(CHURCH, action("invite")))[1] and sender["texts"] == []
    db["attendance"] = []
    db["contacts"].clear()
    assert "no longer" in run(nh.run_scheduled(CHURCH, action("invite")))[1] and sender["texts"] == []


def test_without_a_name_the_text_still_reads_right(sender, db):
    db["contacts"][0]["name"] = PHONE
    sender["now"] = at(2026, 11, 15, 13, 42)
    run(nh.run_scheduled(CHURCH, action("thanks")))
    assert sender["texts"][0][1].startswith("Grace Hill Church: Thank you for worshiping with us today! It was a joy")


# ── 5. the card ───────────────────────────────────────────────────────

@pytest.fixture
def card(db, monkeypatch):
    import church_follow_up
    import church_prayer
    got = {"follow": [], "prayer_new": []}
    db["contacts"].append({"id": GUEST, "name": PHONE, "phone": PHONE, "email": None, "tags": [],
                           "metadata": {"other": 1, "new_here": {"code": "ABCDEFGH", "texted_at": "2026-11-15T15:42:00Z"}}})
    monkeypatch.setattr(church_follow_up, "start", lambda *a, **kw: got["follow"].append((a, kw)) or {"id": "f1"})
    monkeypatch.setattr(church_prayer, "on_new", lambda biz, row: got["prayer_new"].append(row))
    return got


FORM = {"name": "Dana  Reyes", "email": "Dana@Example.com", "first": "yes", "heard": "A friend or family",
        "kids": "2", "prayer": "My mom's surgery is Wednesday."}


def test_the_card_names_the_guest_and_hands_them_on(card, db):
    guest = dict(db["contacts"][0])
    assert nh.save_card(CHURCH, guest, FORM) is True
    (path, row), = [(p, r) for p, r in db["patches"] if p.startswith("/contacts")]
    assert row["name"] == "Dana Reyes" and row["email"] == "dana@example.com" and row["tags"] == ["first-time guest"]
    assert row["metadata"]["other"] == 1                                      # the rest of metadata kept
    kept = row["metadata"]["new_here"]
    assert kept["code"] == "ABCDEFGH" and kept["card_at"]
    assert kept["card"] == {"first_time": True, "heard": "A friend or family", "kids": "2", "prayer": True}
    # The prayer is the pastors': a care request kept confidential.
    (prayer,), = [[r for p, r in db["posts"] if p == "/ministry_care_requests"]]
    assert prayer["submission"]["confidential"] == "yes" and prayer["submission"]["source"] == "New here card"
    assert prayer["contact_id"] == GUEST and card["prayer_new"]
    # The leader is handed the card, never the prayer.
    (args, kw), = card["follow"]
    assert args[:2] == (BIZ, GUEST) and kw["card_key"] == nh.CARD_KEY and kw["kind"] == "connect"
    assert "surgery" not in str(kw["answers"]) and {"q": "Kids with them", "a": "2"} in kw["answers"]
    assert kw["source_event"] == f"new-here:{GUEST}:2026-11-15"


def test_a_named_guest_keeps_their_name_and_a_regular_isnt_tagged(card, db):
    db["contacts"][0].update(name="Dana R.", email="old@example.com")
    nh.save_card(CHURCH, dict(db["contacts"][0]), {**FORM, "first": "no", "prayer": ""})
    (path, row), = [(p, r) for p, r in db["patches"] if p.startswith("/contacts")]
    assert "name" not in row and "email" not in row and "tags" not in row
    assert not [p for p, r in db["posts"] if p == "/ministry_care_requests"]


def test_the_card_page(card, db):
    page, status = run(nh.page_for(BIZ, "/new/abcdefgh"))
    assert status == 200 and 'action="/new/ABCDEFGH"' in page and 'name="website"' in page
    assert 'value=""' in page                                                 # a number isn't a name
    assert "Only our pastors see this." in page and "Reply STOP anytime" in page
    thanks, _ = run(nh.page_for(BIZ, "/new/ABCDEFGH", "done=1"))
    assert "Thank you!" in thanks
    lost, status = run(nh.page_for(BIZ, "/new/ZZZZZZZZ"))
    assert status == 404 and "(231) 555-0199" in lost
    home, status = run(nh.page_for(BIZ, "/new"))
    assert status == 200 and "(231) 555-0199" in home
    db["switched"] = False
    assert run(nh.page_for(BIZ, "/new/ABCDEFGH")) is None                    # served as the site would anyway


@pytest.fixture
def client(card, db, monkeypatch):
    import rate_limit
    state = {"allow": True}
    monkeypatch.setattr(nh, "_church", lambda request: {"business": db["biz"], "site": {}})
    monkeypatch.setattr(rate_limit, "allow_strict", lambda bucket, key, **kw: state["allow"])
    app = FastAPI()
    app.include_router(nh.router)
    return TestClient(app, follow_redirects=False), state


def test_sending_the_card(client, db, card):
    c, state = client
    r = c.post("/new/ABCDEFGH", data=FORM)
    assert r.status_code == 303 and r.headers["location"] == "/new/ABCDEFGH?done=1"
    assert "Dana" not in r.headers["location"] and "0142" not in r.headers["location"]
    assert card["follow"]
    assert c.post("/new/ABCDEFGH", data={**FORM, "name": " "}).headers["location"].endswith("note=name")
    assert c.post("/new/ABCDEFGH", data={**FORM, "email": "nope"}).headers["location"].endswith("note=email")
    assert c.post("/new/ZZZZZZZZ", data=FORM).status_code == 404
    before = len(db["patches"])
    assert c.post("/new/ABCDEFGH", data={**FORM, "website": "x"}).headers["location"].endswith("done=1")
    state["allow"] = False
    assert c.post("/new/ABCDEFGH", data=FORM).headers["location"].endswith("note=busy")
    assert len(db["patches"]) == before                                       # a bot and the limit save nothing


# ── 6. the room ───────────────────────────────────────────────────────

def _body(**over):
    base = {"on": True, "word": "new", "welcome": nh.DEFAULTS["welcome"],
            "thanks": {"on": True, "text": "Thanks {first name}!", "hours": 2},
            "monday": {"on": True, "text": "Hi"}, "invite": {"on": False, "text": "Come back"}}
    return nh.NewHereIn(**{**base, **over})


def test_what_a_saved_setting_must_keep():
    saved = nh.clean(_body())
    assert saved["word"] == "NEW" and saved["thanks"] == {"on": True, "text": "Thanks {first name}!", "hours": 2}
    assert saved["invite"]["on"] is False
    for bad, why in ((_body(word="STOP"), "Pick another word"), (_body(word="give"), "Pick another word"),
                     (_body(word="x"), "2 to 12 letters"),
                     (_body(welcome="Welcome! STOP to end."), "{card link}"),
                     (_body(welcome="Welcome {card link}"), "STOP"),
                     (_body(monday={"on": True, "text": "card {card link}"}), "Only the welcome")):
        with pytest.raises(HTTPException) as e:
            nh.clean(bad)
        assert e.value.status_code == 400 and why in e.value.detail, why


@pytest.fixture
def room(db, monkeypatch):
    import business_access
    who = {"edit": True, "read": True}

    def assert_access(biz, user, role):
        if not who["read"]:
            raise HTTPException(404, "Not found")
        return "admin"

    monkeypatch.setattr(business_access, "assert_access", assert_access)
    monkeypatch.setattr(nh, "_may_edit", lambda biz, user: who["edit"])
    from auth_supabase import AuthedUser, require_user
    app = FastAPI()
    app.include_router(nh.router)
    app.dependency_overrides[require_user] = lambda: AuthedUser(id="u1", email="o@x.test", role="authenticated")
    return TestClient(app), who


def test_the_room_reads_and_saves(room, db):
    c, who = room
    db["contacts"].append({"id": GUEST, "name": "Dana Reyes", "phone": PHONE, "metadata": {"new_here": {
        "texted_at": nh._iso(nh._now()), "card_at": nh._iso(nh._now()), "card": {"first_time": True}}}})
    db["follows"] = [{"contact_id": GUEST, "status": "open", "step": 1, "leader_contact_id": None}]
    got = c.get(f"/new-here/{BIZ}").json()
    assert got["number_pretty"] == "(231) 555-0199" and got["sms_link"] == "sms:+12315550199?&body=NEW"
    assert got["can_edit"] is True and got["texts_per_guest"] == 4
    (g,) = got["guests"]
    assert g["name"] == "Dana Reyes" and g["phone_last4"] == "0142" and g["follow_up"]["reached"] is True
    r = c.put(f"/new-here/{BIZ}", json=_body().model_dump())
    assert r.status_code == 200 and r.json()["settings"]["invite"]["on"] is False
    (path, row), = [(p, r) for p, r in db["patches"] if p.startswith("/businesses")]
    assert row["settings"]["new_here"]["word"] == "NEW" and row["settings"]["new_here"]["on"] is True
    who["edit"] = False
    assert c.put(f"/new-here/{BIZ}", json=_body().model_dump()).status_code == 403
    who["read"] = False
    assert c.get(f"/new-here/{BIZ}").status_code == 404
    db["biz"] = {**CHURCH, "type": "salon"}
    who["read"] = True
    assert c.get(f"/new-here/{BIZ}").status_code == 404


# ── 7. the wiring ─────────────────────────────────────────────────────

def _src(name):
    return (pathlib.Path(nh.__file__).parent / name).read_text(encoding="utf-8")


def test_the_wiring():
    routing = _src("sms_routing.py")
    daily, new, direct = (routing.index('"action": "daily_join"'), routing.index("new_here.on_text"),
                          routing.index("own-number {phone} → biz"))
    assert daily < new < direct                                     # beside GIVE and DAILY, before the inbox
    assert 'f"{sender_brand()} for {hit[\'name\']}: "' in routing    # the platform's name until its own is approved
    sched = _src("chief_scheduler.py")
    assert 'new_here_text = atype == "new_here_text"' in sched and "new_here.run_scheduled(biz, action)" in sched
    site = _src("public_site.py")
    assert site.index("manual_page = (secondary_pages") < site.index("new_here.is_card_path(normalized_path)")
    assert "from new_here import router as new_here_router" in _src("kmj_intake_automation.py")
    assert '"new_here_card"' in _src("rate_limit.py")
