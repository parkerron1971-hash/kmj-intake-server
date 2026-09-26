"""
test_setup_brief.py — a new business's quiet morning is not "nothing".

The morning brief skipped every morning with nothing to report, and in a
business's first week that is every morning. These tests hold the new
rule in both directions: a launching business with setup still to do
gets ONE next step (no model call), and an established business with an
empty day is still skipped exactly as before. Around that, the rules the
brief has to keep: the opt-out, the once-a-day cap, the business's own
clock, and the day-three and day-seven emails, which carry the same ask
on their day and so get that day to themselves.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import business_track_actions as bta  # noqa: E402
import lifecycle_emails as le  # noqa: E402
import setup_brief as sbf  # noqa: E402

# A Thursday, 13:05 UTC: the morning tick. 9:05 in New York (EDT), 6:05
# in Los Angeles (PDT), 3:05 in Honolulu.
NOW = datetime(2026, 9, 24, 13, 5, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _biz(age_days: float = 1.5, *, status: str = "trialing", now: datetime = NOW,
         **settings):
    return {"id": "biz-1", "name": "Fade Room", "type": "barber", "owner_id": "u-1",
            "created_at": _iso(now - timedelta(days=age_days)),
            "subscription_status": status, "settings": dict(settings)}


KEYS = ("import_contacts", "offerings", "payments", "availability", "site", "quickbooks")


def _items(done=(), keys=KEYS):
    """The list as resolve_plugins shapes it, built from the real catalog."""
    out = []
    for k in keys:
        spec = bta.PLUGIN_CATALOG[k]
        out.append({"key": k, "title": spec["title"], "why": spec["why"],
                    "nav": spec["nav"], "done": k in done,
                    "blocked_by": [n for n in spec["needs"] if n not in done]})
    out.sort(key=lambda p: (p["done"], bool(p["blocked_by"])))
    return out


@pytest.fixture
def probes(monkeypatch):
    """No network: the arc read and the plug-in probes are the two I/O
    edges of setup_brief. Tests steer them through this handle."""
    state = {"items": _items(), "arc": None, "plugin_calls": 0, "arc_calls": 0}

    def plugins(biz):
        state["plugin_calls"] += 1
        return state["items"]

    def arc(bid):
        state["arc_calls"] += 1
        return state["arc"]

    monkeypatch.setattr(sbf, "_plugins", plugins)
    monkeypatch.setattr(sbf, "_arc", arc)
    monkeypatch.setattr(le, "_is_grandfathered", lambda _owner: False)
    monkeypatch.delenv("SETUP_BRIEF", raising=False)
    monkeypatch.delenv("SETUP_BRIEF_WINDOW_DAYS", raising=False)
    monkeypatch.delenv("LIFECYCLE_EMAILS", raising=False)
    return state


# ═══════════════════════════════════════════════════════════════════════
# Through the real morning brief
# ═══════════════════════════════════════════════════════════════════════

class _DB:
    """Just wide enough for _generate_morning_brief."""

    def __init__(self, biz, *, report=False, briefed_today=False):
        self.biz, self.report, self.briefed_today = biz, report, briefed_today
        self.posted, self.gets = [], []

    async def __call__(self, client, method, path, body=None):
        if method == "POST":
            self.posted.append((path, body))
            return [dict(body or {}, id="n-1")]
        self.gets.append(path)
        if path.startswith("/businesses"):
            return [self.biz]
        if path.startswith("/chief_notifications"):
            return [{"id": "n-0"}] if self.briefed_today else []
        if self.report and path.startswith("/contacts") and "created_at=gte" in path:
            return [{"id": "c-1", "name": "Dana", "lead_score": 81, "source": "site"}]
        return []

    def briefs(self):
        return [b for p, b in self.posted if p == "/chief_notifications"]


def _brief(db, **kw):
    import notification_engine as ne
    kw.setdefault("now", NOW)
    with mock.patch.object(ne, "_sb", side_effect=db.__call__), \
         mock.patch.object(ne, "_call_claude") as claude, \
         mock.patch("push_notifications.send_to_business", return_value=1) as push:
        out = asyncio.run(ne._generate_morning_brief(None, "biz-1", **kw))
    return out, claude, push


def test_a_new_business_with_nothing_to_report_gets_one_setup_step(probes):
    db = _DB(_biz(1.5))
    out, claude, push = _brief(db)

    assert out["created"] is True and out["setup_step"] == "import_contacts"
    claude.assert_not_called()   # no model call: an empty morning stays free
    [brief] = db.briefs()
    assert brief["type"] == "morning_brief"
    assert brief["title"] == "Today's one step: Bring your client list over"
    body = brief["body"]
    assert body.startswith("Day 2 of your first week.")
    assert "Nothing is plugged in yet" in body
    assert "the first domino." in body                    # the why, verbatim
    assert "let's do this one" in body                    # Chief does it in chat
    assert brief["suggested_action"] == "Take me there"
    assert brief["action_payload"] == {"type": "navigate", "tab": "operate",
                                       "sub": "contacts",
                                       "setup_step": "import_contacts"}
    # The same morning on the phone, deep-linked to the same door.
    push.assert_called_once()
    assert push.call_args.kwargs["nav"] == "operate:contacts"
    assert push.call_args.kwargs["tag"] == "morning-2026-09-24"
    assert "Bring your client list over" in push.call_args.kwargs["body"]


def test_an_established_business_with_nothing_to_report_is_still_skipped(probes):
    db = _DB(_biz(90, status="active"))
    out, claude, push = _brief(db)
    assert out == {"skipped": "nothing_to_report"}
    assert not db.posted
    claude.assert_not_called()
    push.assert_not_called()
    # Not even the probes: an old business costs what it always did.
    assert probes["plugin_calls"] == 0 and probes["arc_calls"] == 0


def test_a_new_business_with_something_to_report_gets_the_ordinary_brief(probes):
    db = _DB(_biz(1.5), report=True)
    import notification_engine as ne

    async def claude(client, system, user_msg, max_tokens=600, business_id=None):
        return '```json{"title":"Dana came in","body":"Call Dana first."}```'

    with mock.patch.object(ne, "_sb", side_effect=db.__call__), \
         mock.patch.object(ne, "_call_claude", side_effect=claude):
        out = asyncio.run(ne._generate_morning_brief(None, "biz-1", now=NOW))
    assert out["created"] is True and "setup_step" not in out
    assert db.briefs()[0]["title"] == "Dana came in"
    assert probes["plugin_calls"] == 0


def test_setup_done_goes_back_to_the_skip(probes):
    probes["items"] = _items(done=KEYS)
    db = _DB(_biz(1.5))
    out, _, _ = _brief(db)
    assert out == {"skipped": "nothing_to_report"}
    assert not db.posted


def test_quickbooks_never_leads(probes):
    """Chief is told never to push QuickBooks on someone without an
    accountant. A morning brief naming it would be pushing it."""
    probes["items"] = _items(done=[k for k in KEYS if k != "quickbooks"])
    assert sbf.plan(_biz(1.5), now=NOW)["reason"] == "setup_done"
    out, _, _ = _brief(_DB(_biz(1.5)))
    assert out == {"skipped": "nothing_to_report"}


def test_the_step_is_the_first_undone_unblocked_one(probes):
    probes["items"] = _items(done=("import_contacts",))
    p = sbf.plan(_biz(1.5), now=NOW)
    assert p["step"]["key"] == "offerings"
    assert "So far 1 of 6 pieces are plugged in." in p["notification"]["body"]

    # A door Chief cannot walk through for them: the button opens it.
    probes["items"] = _items(done=("import_contacts", "offerings"))
    p = sbf.plan(_biz(1.5), now=NOW)
    assert p["step"]["key"] == "payments"
    assert 'Tap "Take me there" to open the right page' in p["notification"]["body"]
    assert p["notification"]["action_payload"]["page"] == "integrations"


def test_a_blocked_step_is_never_offered(probes):
    """'Put your site up' before anything is on the shelf is a dead end."""
    probes["items"] = _items(done=("import_contacts", "payments"),
                             keys=("import_contacts", "payments", "site"))
    p = sbf.plan(_biz(1.5), now=NOW)
    assert p["send"] is False and p["reason"] == "setup_done"


def test_the_window_ends(probes):
    later = sbf.plan(_biz(10), now=NOW)
    assert later["send"] is True
    # Past the first week the copy stops counting days.
    assert later["notification"]["body"].startswith("Good morning.")
    assert "first week" not in later["notification"]["body"]

    out, _, _ = _brief(_DB(_biz(20)))
    assert out == {"skipped": "nothing_to_report"}


def test_the_window_is_a_dial(probes, monkeypatch):
    monkeypatch.setenv("SETUP_BRIEF_WINDOW_DAYS", "7")
    assert sbf.plan(_biz(10), now=NOW)["reason"] == "outside_window"
    monkeypatch.setenv("SETUP_BRIEF", "off")
    assert sbf.plan(_biz(1.5), now=NOW)["reason"] == "off"


def test_a_late_trial_counts_from_its_own_day_one(probes):
    """Signed up in August, subscribed this week: first_run_arc moved day
    one to the trial, and so does the brief."""
    probes["arc"] = {"started_at": _iso(NOW - timedelta(days=2.2))}
    p = sbf.plan(_biz(40, status="trialing"), now=NOW)
    assert p["send"] is True and p["day"] == 3
    assert p["notification"]["body"].startswith("Day 3 of your first week.")


# ═══════════════════════════════════════════════════════════════════════
# What the ordinary brief respects, the setup brief respects
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("key", ["morning_brief_enabled", "morning_brief"])
def test_the_opt_out_is_respected(probes, key):
    """morning_brief_enabled is what the Settings toggle writes; the bare
    key is what this engine used to read."""
    db = _DB(_biz(1.5, notifications={key: False}))
    out, claude, push = _brief(db)
    assert out == {"skipped": "disabled"}
    assert not db.posted
    push.assert_not_called()
    assert probes["plugin_calls"] == 0


def test_the_toggles_the_app_writes_now_reach_every_brief():
    import notification_engine as ne
    for key in ("morning_brief", "midday_ping", "evening_summary", "urgent_alerts"):
        off = {"settings": {"notifications": {f"{key}_enabled": False}}}
        assert asyncio.run(ne._settings_allow(None, off, key)) is False, key
        assert asyncio.run(ne._settings_allow(None, {"settings": {}}, key)) is True


def test_one_brief_a_day(probes):
    db = _DB(_biz(1.5), briefed_today=True)
    out, _, push = _brief(db)
    assert out == {"skipped": "already_sent_today"}
    assert not db.posted
    push.assert_not_called()


def test_a_dismissed_checklist_ends_the_setup_talk(probes):
    out, _, _ = _brief(_DB(_biz(1.5, checklist_dismissed=True)))
    assert out == {"skipped": "nothing_to_report"}
    assert probes["plugin_calls"] == 0


def test_the_first_hours_belong_to_chief(probes):
    db = _DB(_biz(0.2))
    out, _, _ = _brief(db)
    assert out == {"skipped": "nothing_to_report", "setup_brief": "just_started"}
    assert not db.posted


# ─── the business's clock ────────────────────────────────────────────

def _tz(name, **notif):
    extra = {"notifications": notif} if notif else {}
    return {"availability": {"timezone": name}, **extra}


def test_local_night_holds_the_brief(probes):
    """13:05 UTC is 3:05am in Honolulu. Nobody is woken for a setup tip."""
    db = _DB(_biz(1.5, **_tz("Pacific/Honolulu")))
    out, _, push = _brief(db)
    assert out == {"skipped": "nothing_to_report", "setup_brief": "not_local_morning"}
    assert not db.posted
    push.assert_not_called()


def test_the_brief_lands_in_the_business_morning(probes):
    la = _biz(1.5, **_tz("America/Los_Angeles"))
    assert sbf.plan(la, now=NOW)["reason"] == "not_local_morning"      # 6:05 PDT
    at_735 = NOW.replace(hour=14, minute=35)                            # 7:35 PDT
    assert sbf.plan(la, now=at_735)["send"] is True

    # Their own morning_brief_time moves the morning.
    late = _biz(1.5, **_tz("America/Los_Angeles", morning_brief_time="09:00"))
    assert sbf.plan(late, now=at_735)["reason"] == "not_local_morning"
    assert sbf.plan(late, now=NOW.replace(hour=16, minute=35))["send"] is True


def test_a_midnight_setting_is_still_a_morning(probes):
    odd = _biz(1.5, **_tz("America/Los_Angeles", morning_brief_time="00:00"))
    assert not sbf.is_local_morning(odd, NOW.replace(hour=7, minute=35))   # 00:35 PDT
    assert sbf.is_local_morning(odd, NOW.replace(hour=12, minute=35))      # 05:35 PDT


def test_no_timezone_rides_the_morning_tick(probes):
    assert sbf.local_tz(_biz(1.5)) is None
    assert sbf.is_local_morning(_biz(1.5), NOW)


def test_asking_for_it_overrules_the_clock_and_nothing_else(probes):
    db = _DB(_biz(1.5, **_tz("Pacific/Honolulu")))
    out, _, _ = _brief(db, on_demand=True)
    assert out["created"] is True
    out, _, _ = _brief(_DB(_biz(0.2)), on_demand=True)
    assert out["setup_brief"] == "just_started"


# ─── the day-three and day-seven emails ──────────────────────────────

def test_the_day_three_email_morning_holds_the_brief(probes):
    """At 14:45 this business is 2.57 days old: the week-beat sweep sends
    'one thing to do today' with the same step. That email is the nudge."""
    db = _DB(_biz(2.5))
    out, _, push = _brief(db)
    assert out == {"skipped": "nothing_to_report", "setup_brief": "day_three_email_today"}
    assert not db.posted
    push.assert_not_called()


def test_the_day_after_the_email_the_brief_resumes(probes):
    yesterday = NOW - timedelta(days=1) + timedelta(hours=1, minutes=40)
    biz = _biz(3.5, lifecycle_emails={"day_three_at": _iso(yesterday)})
    assert sbf.week_beat_today(biz, NOW) is None
    assert sbf.plan(biz, now=NOW)["send"] is True


def test_an_email_already_sent_today_holds_the_brief(probes):
    sent = NOW.replace(hour=14, minute=45)
    biz = _biz(2.6, lifecycle_emails={"day_three_at": _iso(sent)})
    assert sbf.week_beat_today(biz, NOW.replace(hour=16, minute=0)) == "day_three"


def test_the_day_seven_email_morning_holds_the_brief(probes):
    biz = _biz(6.5, lifecycle_emails={"day_three_at": _iso(NOW - timedelta(days=4))})
    assert sbf.plan(biz, now=NOW)["reason"] == "day_seven_email_today"


def test_no_email_means_no_hold(probes, monkeypatch):
    monkeypatch.setenv("LIFECYCLE_EMAILS", "off")
    assert sbf.plan(_biz(2.5), now=NOW)["send"] is True
    monkeypatch.delenv("LIFECYCLE_EMAILS")
    monkeypatch.setattr(le, "_is_grandfathered", lambda _owner: True)
    assert sbf.plan(_biz(2.5), now=NOW)["send"] is True


def test_the_email_day_is_the_business_local_day(probes):
    """London's morning is 06:35 UTC and the email lands at 15:45 BST:
    the same local day, so the brief holds. The next morning the stamp is
    yesterday's, and the brief resumes, not a second quiet day."""
    london = _tz("Europe/London")
    morning = NOW.replace(hour=6, minute=35)
    assert sbf.plan(_biz(2.6, now=morning, **london), now=morning)["reason"] \
        == "day_three_email_today"
    next_morning = morning + timedelta(days=1)
    sent = _iso(morning.replace(hour=14, minute=45))
    biz = _biz(3.6, now=next_morning, **london, lifecycle_emails={"day_three_at": sent})
    assert sbf.plan(biz, now=next_morning)["send"] is True


# ═══════════════════════════════════════════════════════════════════════
# The local-morning tick
# ═══════════════════════════════════════════════════════════════════════

def test_the_local_morning_tick_asks_only_businesses_on_their_own_clock(probes):
    import notification_engine as ne
    rows = [{"id": "biz-la", "settings": _tz("America/Los_Angeles")},
            {"id": "biz-none", "settings": {}},
            {"id": "biz-hnl", "settings": _tz("Pacific/Honolulu")}]
    gets, calls = [], []

    async def sb(client, method, path, body=None):
        gets.append(path)
        return rows

    async def brief(client, bid, **kw):
        calls.append((bid, kw))
        return {"created": True}

    at = NOW.replace(hour=14, minute=35)   # 7:35 LA, 4:35 Honolulu
    with mock.patch.object(ne, "_sb", side_effect=sb), \
         mock.patch.object(ne, "_generate_morning_brief", side_effect=brief):
        out = asyncio.run(ne.setup_brief_local_morning_tick(now=at))

    assert [c[0] for c in calls] == ["biz-la"]
    assert calls[0][1] == {"setup_only": True, "now": at}
    assert out["candidates"] == 3 and out["due"] == 1
    assert "or=(created_at.gte." in gets[0] and "subscription_status.eq.trialing" in gets[0]
    assert "+00:00" not in gets[0]


def test_the_local_morning_tick_leaves_a_busy_morning_to_the_ordinary_brief(probes):
    db = _DB(_biz(1.5, **_tz("America/Los_Angeles")), report=True)
    out, claude, _ = _brief(db, setup_only=True, now=NOW.replace(hour=14, minute=35))
    assert out == {"skipped": "left_to_the_morning_brief"}
    claude.assert_not_called()
    assert not db.posted


def test_the_tick_is_off_with_the_brief(probes, monkeypatch):
    import notification_engine as ne
    monkeypatch.setenv("SETUP_BRIEF", "off")
    with mock.patch.object(ne, "_sb") as sb:
        assert asyncio.run(ne.setup_brief_local_morning_tick(now=NOW)) == {"skipped": "disabled"}
    sb.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════
# The push brief
# ═══════════════════════════════════════════════════════════════════════

def _push_tick(biz_row):
    import push_notifications as pn
    sent = []

    def fake_get(path):
        if path.startswith("/push_subscriptions"):
            return [{"business_id": "biz-1"}]
        if path.startswith("/businesses"):
            return [biz_row]
        return []

    with mock.patch.object(pn, "push_enabled", return_value=True), \
         mock.patch.object(pn.sb_clients, "sb_get_as_service", side_effect=fake_get), \
         mock.patch.object(pn, "send_to_business",
                           side_effect=lambda *a, **k: sent.append(k)):
        asyncio.run(pn.morning_brief_tick())
    return sent


def test_the_push_brief_stops_saying_clear_runway_to_a_launching_business(probes):
    assert _push_tick(_biz(1.5, now=datetime.now(timezone.utc))) == []


def test_an_established_business_still_hears_clear_runway(probes):
    sent = _push_tick(_biz(90, status="active"))
    assert len(sent) == 1 and "clear runway" in sent[0]["body"]
    assert probes["plugin_calls"] == 0


def test_a_finished_setup_hears_clear_runway_again(probes):
    probes["items"] = _items(done=KEYS)
    sent = _push_tick(_biz(1.5, now=datetime.now(timezone.utc)))
    assert len(sent) == 1 and "clear runway" in sent[0]["body"]


# ═══════════════════════════════════════════════════════════════════════
# The words and the doors
# ═══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("key", sorted(bta.PLUGIN_CATALOG))
def test_every_step_is_short_plain_and_opens_a_real_door(key):
    import system_destinations
    spec = bta.PLUGIN_CATALOG[key]
    step = {"key": key, "title": spec["title"], "why": spec["why"], "nav": spec["nav"]}
    words = sbf.compose(day=3, step=step, done=2, total=10, now=NOW)
    n = words["notification"]
    assert len(n["body"].split()) <= 70, n["body"]
    for text in (n["title"], n["body"], words["push"]["body"]):
        low = text.lower()
        for banned in ("github", "claude code", "builder"):
            assert banned not in low, (banned, text)
    ap = n["action_payload"]
    system_destinations.destination(ap["tab"], ap.get("page") or ap.get("sub"))
    assert ":" in words["push"]["nav"]


# ═══════════════════════════════════════════════════════════════════════
# The schedule this depends on
# ═══════════════════════════════════════════════════════════════════════

def _jobs():
    """Every scheduler.add_job(...) in the entry point, read from source
    so the test does not import (and mount) seventy routers."""
    tree = ast.parse((ROOT / "kmj_intake_automation.py").read_text(encoding="utf-8"))
    jobs = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_job"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        if not isinstance(kw.get("id"), ast.Constant):
            continue
        jobs[kw["id"].value] = {
            "target": ast.unparse(node.args[0]) if node.args else "",
            "trigger": (node.args[1].value if len(node.args) > 1
                        and isinstance(node.args[1], ast.Constant) else None),
            "kw": {k: (v.value if isinstance(v, ast.Constant) else ast.unparse(v))
                   for k, v in kw.items()},
        }
    return jobs


def test_the_local_morning_tick_is_registered_on_the_half_hour():
    job = _jobs()["notif_setup_brief"]
    assert job["target"].startswith("g(") and "setup_brief_local_morning_tick" in job["target"]
    assert job["trigger"] == "cron"
    assert job["kw"]["minute"] == 35 and "hour" not in job["kw"]
    # Never on the morning tick's minute: the two must not race.
    assert _jobs()["notif_morning_brief"]["kw"]["minute"] != 35


def test_the_email_overlap_check_reads_the_email_schedule():
    job = _jobs()["week_beats"]
    assert (job["kw"]["hour"], job["kw"]["minute"]) == sbf.WEEK_BEATS_UTC
