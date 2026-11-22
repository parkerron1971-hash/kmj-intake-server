# __tests__/test_member_plan_prefs.py
#
# Read a plan with your group, and a reminder at your hour (member_plan_prefs),
# the last step of Kevin's approved Plans design. Pins:
#   - before supabase/APPLY-2026-11-21-member-plan-prefs.sql is applied the
#     table isn't there: no row, no button, no line, kept so the next page
#     doesn't ask again, every page still 200;
#   - the plan's page: Remind me with only the quarter hours outside the
#     church's quiet hours, who you read with (On my own and the member's
#     groups whose chat is open to them), as forms that work without script;
#   - the writes: the member's session, same-site, the rate limit, a group of
#     theirs, a time that's offered; only their own row;
#   - the tab's line under Continue and how many of the group read it; the
#     day's "Send to <group>": the group's chat with the question in the box,
#     nothing posted;
#   - the reminder sweep: once a day, at the member's time on the church's
#     clock, only while the plan runs and today's day isn't read, never in
#     quiet hours, never to a member who turned every alert off, never for a
#     sample church, PLAN_REMINDERS=off stops it.

import pathlib
import re
import sys
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import test_church_threads as tct
from test_church_threads import fake  # noqa: F401  (the fixture)
from test_member_lumen_pages import church, _client  # noqa: F401  (church is a fixture)
from test_member_lumen_bible import bible, D1, D2  # noqa: F401  (bible is a fixture)

TODAY = date.today()
GROUP, OTHER_GROUP = tct.GROUP, tct.cid(77)


@pytest.fixture
def groups(bible, fake):  # noqa: F811
    """Ana in Tuesday Night Group (the shared fake's; its chat open), messaging on; a group she isn't in."""
    fake.biz[tct.BIZ]["settings"]["messaging"] = {"enabled": True}
    for t in ("groups", "group_members", "member_plan_prefs", "reading_progress", "member_push_subscriptions",
              "member_push_prefs"):
        fake.t.setdefault(t, [])
    fake.add("groups", id=OTHER_GROUP, business_id=tct.BIZ, name="Worship Team", active=True, chat_on=True, chat_writers="all")
    fake.add("member_plan_starts", business_id=tct.BIZ, contact_id=tct.ANA, plan="reading:topic-anxiety",
             started_on=(TODAY - timedelta(days=1)).isoformat())
    return bible


def _app(fake, monkeypatch):  # noqa: F811
    import member_plan_prefs as mpp
    import member_portal_devotionals as mpd
    import member_portal_reading as mpr
    c = _client(fake, monkeypatch)
    for r in (mpd.router, mpr.router, mpp.router):
        c.app.include_router(r)
    return c


# ─── before the file is applied ──────────────────────────────────────


def test_before_the_table_is_there_everything_is_as_it_was(groups, fake, monkeypatch):  # noqa: F811
    import sb_clients
    fake.down.add("member_plan_prefs")
    monkeypatch.setattr(sb_clients, "last_error", lambda: {"code": "PGRST205", "status": 404,
                                                           "message": "Could not find the table"}, raising=False)
    c = _app(fake, monkeypatch)
    page = c.get("/my/bible/plans/topic-anxiety")
    assert page.status_code == 200 and "Remind me" not in page.text and "Read it with" not in page.text
    tab = c.get("/my/bible?tab=plans")
    assert tab.status_code == 200 and "lm-pl-tog" not in tab.text
    day = c.get(f"/my/bible/plans/{D1}/3")
    assert day.status_code == 200 and "lm-dy-send" not in day.text
    fake.gets.clear()
    c.get("/my/bible/plans/topic-anxiety")
    assert not [g for g in fake.gets if g.startswith("/member_plan_prefs")]              # "not there" is kept
    # and a write says it didn't save
    r = c.post("/my/bible/plans/remind", data={"plan": "reading:topic-anxiety", "at": "19:30"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-anxiety?err=error"


# ─── the plan's page ─────────────────────────────────────────────────


def test_the_plan_page_offers_a_reminder_and_who_to_read_with(groups, fake, monkeypatch):  # noqa: F811
    html = _app(fake, monkeypatch).get("/my/bible/plans/topic-anxiety").text
    rem = html[html.index('<form class="lm-pp-opt"'):]
    rem = rem[:rem.index("</form>")]
    assert 'action="/my/bible/plans/remind"' in rem and 'name="plan" value="reading:topic-anxiety"' in rem
    times = re.findall(r'<option value="(\d\d:\d\d)"', rem)
    assert times[0] == "07:00" and times[-1] == "20:45" and len(times) == 14 * 4             # quiet 9 PM to 7 AM left out
    assert '<option value="" selected>Off</option>' in rem
    chips = html[html.index('<form class="lm-pp-with"'):]
    chips = chips[:chips.index("</form>")]
    assert re.findall(r'name="group" value="([^"]*)" aria-pressed="(\w+)">([^<]+)<', chips) == [
        ("", "true", "On my own"), (GROUP, "false", "Tuesday Night Group")]                 # not Worship Team: not hers


def test_a_plan_not_started_offers_who_to_read_with_but_no_reminder(groups, fake, monkeypatch):  # noqa: F811
    html = _app(fake, monkeypatch).get("/my/bible/plans/topic-grief").text
    assert "lm-pp-opt" not in html and "lm-pp-with" in html


def test_read_with_and_remind_save_her_own_row(groups, fake, monkeypatch):  # noqa: F811
    import member_lumen_plans as mlp
    c = _app(fake, monkeypatch)
    r = c.post("/my/bible/plans/with", data={"plan": "reading:topic-anxiety", "group": GROUP}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-anxiety?done=with"
    assert f"{mlp.VERSION_COOKIE}=" in r.headers["set-cookie"]
    r = c.post("/my/bible/plans/remind", data={"plan": "reading:topic-anxiety", "at": "19:30"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-anxiety?done=remind"
    rows = fake.t["member_plan_prefs"]
    assert len(rows) == 1 and rows[0]["contact_id"] == tct.ANA and rows[0]["group_id"] == GROUP
    assert rows[0]["remind_at"] == "19:30" and rows[0]["plan"] == "reading:topic-anxiety"
    html = c.get("/my/bible/plans/topic-anxiety?done=remind").text
    assert "Your reminder is set." in html and "Every day at 7:30 PM" in html
    assert f'name="group" value="{GROUP}" aria-pressed="true">Tuesday Night Group<' in html
    # off again, and on my own: the other choice stays
    c.post("/my/bible/plans/remind", data={"plan": "reading:topic-anxiety", "at": ""})
    assert fake.t["member_plan_prefs"][0]["remind_at"] is None and fake.t["member_plan_prefs"][0]["group_id"] == GROUP
    c.post("/my/bible/plans/with", data={"plan": "reading:topic-anxiety", "group": ""})
    assert fake.t["member_plan_prefs"][0]["group_id"] is None


def test_the_writes_refuse_what_isnt_hers_or_isnt_offered(groups, fake, monkeypatch):  # noqa: F811
    import member_portal_church as mpc
    c = _app(fake, monkeypatch)
    for data in ({"plan": "reading:topic-anxiety", "group": OTHER_GROUP},              # a group that isn't hers
                 {"plan": "reading:topic-anxiety", "group": "nope"}):
        r = c.post("/my/bible/plans/with", data=data, follow_redirects=False)
        assert r.headers["location"] == "/my/bible/plans/topic-anxiety?err=error"
    for at in ("21:30", "06:45", "19:20", "7pm"):                                       # quiet hours, not a quarter
        r = c.post("/my/bible/plans/remind", data={"plan": "reading:topic-anxiety", "at": at}, follow_redirects=False)
        assert r.headers["location"] == "/my/bible/plans/topic-anxiety?err=error", at
    r = c.post("/my/bible/plans/remind", data={"plan": "reading:nope", "at": "19:30"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible?tab=plans"
    r = c.post("/my/bible/plans/remind", data={"plan": "reading:topic-anxiety", "at": "19:30"},
               headers={"origin": "https://evil.example"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-anxiety?err=error"
    monkeypatch.setattr(mpc, "_allowed", lambda church, me: False)
    r = c.post("/my/bible/plans/remind", data={"plan": "reading:topic-anxiety", "at": "19:30"}, follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-anxiety?err=slow"
    assert fake.t["member_plan_prefs"] == []


def test_the_preview_saves_nothing(groups, fake, monkeypatch):  # noqa: F811
    import member_portal_church as mpc

    async def preview(request):
        return {"business": fake.business()}, None, "preview"
    monkeypatch.setattr(mpc, "_signed_in", preview)
    r = _app(fake, monkeypatch).post("/my/bible/plans/with", data={"plan": "reading:topic-anxiety", "group": GROUP},
                                     follow_redirects=False)
    assert r.headers["location"] == "/my/bible/plans/topic-anxiety?err=preview" and fake.t["member_plan_prefs"] == []


# ─── the tab and the day ─────────────────────────────────────────────


def test_the_tab_says_who_she_reads_it_with_and_the_day_sends_the_question(groups, fake, monkeypatch):  # noqa: F811
    for who in (tct.ANA, tct.BEN):
        fake.add("member_plan_prefs", business_id=tct.BIZ, contact_id=who, plan=f"devotional:{D1}", group_id=GROUP,
                 remind_at=None, reminded_on=None)
    c = _app(fake, monkeypatch)
    tab = c.get("/my/bible?tab=plans").text
    line = tab[tab.index('<a class="lm-pl-tog"'):]
    line = line[:line.index("</a>")]
    assert f'href="/my/groups/{GROUP}/chat"' in line and "Tuesday Night Group is reading this · 2 of you" in line
    dev = next(r for r in fake.t["devotionals"] if r["id"] == D1)
    dev["days"][2]["together"] = "Text one person the verse."
    day = c.get(f"/my/bible/plans/{D1}/3").text
    assert (f'<a class="lm-dy-send" href="/my/groups/{GROUP}/chat?say=Text%20one%20person%20the%20verse.">') in day
    assert "Send to Tuesday Night Group" in day
    assert not [w for w in fake.writes if w[1] in ("msg_messages", "msg_threads")]       # nothing posted


# ─── the reminder sweep ──────────────────────────────────────────────


@pytest.fixture
def sweep(groups, fake, monkeypatch):  # noqa: F811
    import business_marketing
    import push_notifications as pn
    sent = []
    monkeypatch.setattr(business_marketing, "business_tz", lambda row: ZoneInfo("UTC"))
    monkeypatch.setattr(pn, "_send_one", lambda s, payload, table=None: sent.append((s["id"], payload)) or True)
    fake.add("member_push_subscriptions", id="sub1", business_id=tct.BIZ, contact_id=tct.ANA, endpoint="https://push.example/1",
             subscription={})
    fake.add("member_plan_prefs", business_id=tct.BIZ, contact_id=tct.ANA, plan="reading:topic-anxiety", group_id=None,
             remind_at="19:30:00", reminded_on=None)
    return sent


def _at(h, m, day=None):
    return datetime.combine(day or TODAY, datetime.min.time()).replace(hour=h, minute=m, tzinfo=timezone.utc)


def test_the_reminder_goes_once_at_her_time(sweep, fake):  # noqa: F811
    import member_plan_prefs as mpp
    assert mpp.remind_tick(_at(19, 15)) == {"due": 0, "sent": 0}                         # not yet
    got = mpp.remind_tick(_at(19, 30))
    assert got == {"due": 1, "sent": 1}
    sub, payload = sweep[0]
    assert sub == "sub1" and payload["url"] == "/my/bible/plans/topic-anxiety/2"
    assert payload["body"] == "Day 2 of When you're anxious is ready: Do not worry about tomorrow"
    assert payload["title"] == "Grace Fellowship"
    assert fake.t["member_plan_prefs"][0]["reminded_on"] == TODAY.isoformat()
    assert mpp.remind_tick(_at(19, 45)) == {"due": 0, "sent": 0} and len(sweep) == 1        # once a day


def test_no_reminder_when_the_day_is_read_or_the_plan_isnt_running(sweep, fake):  # noqa: F811
    import member_plan_prefs as mpp
    fake.add("reading_progress", business_id=tct.BIZ, contact_id=tct.ANA, plan_key="topic-anxiety",
             start_date=(TODAY - timedelta(days=1)).isoformat(), day=2)
    assert mpp.remind_tick(_at(19, 30))["sent"] == 0
    fake.t["reading_progress"] = []
    fake.t["member_plan_starts"] = [r for r in fake.t["member_plan_starts"] if r["plan"] != "reading:topic-anxiety"]
    assert mpp.remind_tick(_at(19, 30))["sent"] == 0 and not sweep


def test_no_reminder_in_quiet_hours_or_when_every_alert_is_off(sweep, fake, monkeypatch):  # noqa: F811
    import member_plan_prefs as mpp
    import member_push
    fake.t["member_plan_prefs"][0]["remind_at"] = "21:30:00"                              # set before quiet hours moved
    assert mpp.remind_tick(_at(21, 30))["sent"] == 0
    fake.t["member_plan_prefs"][0]["remind_at"] = "19:30:00"
    fake.add("member_push_prefs", business_id=tct.BIZ, contact_id=tct.ANA,
             off=sorted(member_push.church_kinds(fake.biz[tct.BIZ]["settings"])), quiet=True, after_hours=True)
    assert mpp.remind_tick(_at(19, 30))["sent"] == 0 and not sweep


def test_no_reminder_for_a_sample_church_or_with_the_switch_off(sweep, fake, monkeypatch):  # noqa: F811
    import member_plan_prefs as mpp
    monkeypatch.setenv("PLAN_REMINDERS", "off")
    assert mpp.remind_tick(_at(19, 30)) == {"due": 0, "sent": 0}
    monkeypatch.setenv("PLAN_REMINDERS", "on")
    fake.biz[tct.BIZ]["is_sample"] = True
    assert mpp.remind_tick(_at(19, 30))["sent"] == 0 and not sweep


def test_a_devotionals_reminder(sweep, fake):  # noqa: F811
    import member_plan_prefs as mpp
    fake.t["member_plan_prefs"] = []
    fake.add("member_plan_prefs", business_id=tct.BIZ, contact_id=tct.ANA, plan=f"devotional:{D1}", group_id=None,
             remind_at="07:00:00", reminded_on=None)
    got = mpp.remind_tick(_at(7, 10))
    assert got["sent"] == 1 and sweep[0][1]["body"] == "Day 3 of Seven Days of Rest is ready: Unhurried"
    assert sweep[0][1]["url"] == f"/my/bible/plans/{D1}/3"


def test_the_sweep_is_on_the_clock_every_quarter_hour():
    src = (pathlib.Path(__file__).resolve().parent.parent / "kmj_intake_automation.py").read_text(encoding="utf-8")
    assert 'g("plan_reminders", _plan_prefs.remind_tick), "cron", minute="0,15,30,45"' in src
    assert "from member_plan_prefs import router as member_plan_prefs_router" in src


def test_no_reminder_for_a_devotional_thats_gone(sweep, fake):  # noqa: F811
    import member_plan_prefs as mpp
    fake.t["member_plan_prefs"] = []
    fake.add("member_plan_prefs", business_id=tct.BIZ, contact_id=tct.ANA,
             plan="devotional:00000000-0000-4000-8000-0000000009ff", group_id=None, remind_at="07:00:00", reminded_on=None)
    assert mpp.remind_tick(_at(7, 10)) == {"due": 1, "sent": 0} and not sweep
