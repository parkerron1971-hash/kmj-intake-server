"""
test_notification_jobs_fire.py — THE LEAD ARC PR 2.

The notification engine was imported as a ROUTER ONLY. `check_urgent`,
`morning_brief`, `midday_ping` and `evening_summary` were reachable over
HTTP and called by nothing: no scheduled job, no frontend. Meanwhile
NotificationCenter.tsx shipped a settings toggle for all four.

A monitor nobody runs looks exactly like a monitor with nothing to
report. So this file REHEARSES THE ALARM — it drives a hot lead all the
way through to the notification row — and carries the negative control
that proves the rehearsal can fail.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import pathlib
import sys
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import notification_engine as ne  # noqa: E402


# ═══════════════════════════════════════════════════════════════════════
# A fake database just wide enough for the urgent path
# ═══════════════════════════════════════════════════════════════════════

def _fake_sb(events=None, sessions=None, businesses=None):
    posted = []
    gets = []

    async def sb(client, method, path, body=None):
        if method == "POST":
            posted.append((path, body))
            return [dict(body or {}, id="n-1")]
        gets.append(path)
        if path.startswith("/businesses"):
            return businesses if businesses is not None else [
                {"id": "biz-1", "name": "Test Co", "settings": {}}]
        if path.startswith("/events"):
            return events or []
        if path.startswith("/sessions"):
            return sessions or []
        if path.startswith("/chief_notifications"):
            return []          # nothing sent yet — dedup lookups miss
        return []

    return sb, posted, gets


def _lead_event(score, event_type="contact_form_submitted", name="Dana Reyes"):
    return [{
        "id": "e-1", "business_id": "biz-1", "contact_id": "c-1",
        "event_type": event_type,
        "contacts": {"name": name, "lead_score": score},
    }]


def _run_check(events=None, sessions=None):
    sb, posted, gets = _fake_sb(events=events, sessions=sessions)
    with mock.patch.object(ne, "_sb", side_effect=sb):
        out = asyncio.run(ne._check_urgent(None, "biz-1"))
    return out, posted, gets


# ═══════════════════════════════════════════════════════════════════════
# Rehearse the alarm
# ═══════════════════════════════════════════════════════════════════════

def test_a_hot_lead_actually_produces_a_notification():
    """The rehearsal. Not 'the code path exists' — an actual row."""
    out, posted, _ = _run_check(events=_lead_event(88))

    alerts = [b for p, b in posted if p == "/chief_notifications"]
    assert len(alerts) == 1, f"no notification was written: {posted}"
    alert = alerts[0]
    assert alert["type"] == "urgent_alert"
    assert "Dana Reyes" in alert["title"]
    assert "88" in alert["body"]
    assert alert["related_contact_id"] == "c-1"
    assert out["created"][0]["trigger"] == "hot_lead"


def test_the_negative_control_stays_silent():
    """If this ever fails, the test above is proving nothing: it would
    mean the alarm fires for every lead regardless of score."""
    out, posted, _ = _run_check(events=_lead_event(40))
    assert not [b for p, b in posted if p == "/chief_notifications"]
    assert out["created"] == []


def test_a_quiet_window_writes_nothing():
    out, posted, _ = _run_check()
    assert posted == []
    assert out["created"] == []


def test_the_alert_names_the_door_the_lead_came_through():
    """A practitioner with a site, a concierge widget and an embeddable
    form needs to know which one just rang."""
    doors = {
        "form_submit": "intake form",
        "contact_form_submitted": "contact form on your site",
        "concierge_lead_captured": "site concierge",
    }
    for event_type, phrase in doors.items():
        _, posted, _ = _run_check(events=_lead_event(90, event_type=event_type))
        body = [b for p, b in posted if p == "/chief_notifications"][0]["body"]
        assert phrase in body, f"{event_type} -> {body}"


def test_a_lead_with_no_score_does_not_alert():
    """Guards the pre-PR-1 world: a null score must never read as hot."""
    _, posted, _ = _run_check(events=_lead_event(None))
    assert not posted


# ═══════════════════════════════════════════════════════════════════════
# The tick is cheap when nothing is happening
# ═══════════════════════════════════════════════════════════════════════

def test_a_quiet_platform_costs_two_queries():
    """check_urgent_for_all runs every five minutes. On a quiet tick it
    must not touch a single tenant."""
    sb, posted, gets = _fake_sb()
    with mock.patch.object(ne, "_sb", side_effect=sb):
        out = asyncio.run(ne.check_urgent_for_all())
    assert out == {"candidates": 0, "checked": 0, "results": []}
    assert len(gets) == 2, gets
    assert not any(p.startswith("/businesses") for p in gets)
    assert not posted


def test_only_businesses_with_activity_are_checked():
    sb, _, _ = _fake_sb(
        events=[{"business_id": "biz-1"}, {"business_id": "biz-1"}],
        sessions=[{"business_id": "biz-2"}])
    with mock.patch.object(ne, "_sb", side_effect=sb):
        candidates = asyncio.run(ne.urgent_candidates(None))
    assert candidates == ["biz-1", "biz-2"]


def test_a_candidate_that_is_not_active_is_skipped():
    sb, posted, _ = _fake_sb(
        events=[{"business_id": "biz-gone"}],
        businesses=[{"id": "biz-1", "name": "Test Co", "settings": {}}])
    with mock.patch.object(ne, "_sb", side_effect=sb):
        out = asyncio.run(ne.check_urgent_for_all())
    assert out["candidates"] == 1 and out["checked"] == 0
    assert not posted


def test_the_urgent_window_uses_the_Z_form():
    """'+00:00' reads as a space in a PostgREST query string and returns
    silent empties — the classic way a filter stops filtering."""
    sb, _, gets = _fake_sb()
    with mock.patch.object(ne, "_sb", side_effect=sb):
        asyncio.run(ne.urgent_candidates(None))
    assert all("+00:00" not in p for p in gets), gets
    assert any("created_at=gte." in p and p.endswith("limit=500") for p in gets)


# ═══════════════════════════════════════════════════════════════════════
# A brief about nothing is not written, and not billed for
# ═══════════════════════════════════════════════════════════════════════

def test_has_anything_to_report():
    assert ne.has_anything_to_report({"a": [1], "b": []}) is True
    assert ne.has_anything_to_report({"a": [], "b": []}) is False
    assert ne.has_anything_to_report({}) is False


def test_an_empty_day_costs_no_model_call():
    sb, posted, _ = _fake_sb()
    with mock.patch.object(ne, "_sb", side_effect=sb), \
         mock.patch.object(ne, "_call_claude") as claude:
        out = asyncio.run(ne._generate_morning_brief(None, "biz-1"))
    assert out == {"skipped": "nothing_to_report"}
    claude.assert_not_called()
    assert not posted


def test_a_day_with_leads_does_get_a_brief():
    """The other half of the switch: skip-when-empty must not become
    skip-always."""
    sb, posted, _ = _fake_sb()

    async def with_leads(client, biz_id):
        return {"pending": [], "sessions_today": [], "at_risk": [],
                "urgent": [], "hot_leads": [],
                "new_leads_24h": [{"id": "c-1", "name": "Dana",
                                   "lead_score": 81, "source": "site"}]}

    async def claude(client, system, user_msg, max_tokens=600,
                     business_id=None):
        assert "NEW_LEADS_24H" in user_msg, user_msg
        return '```json{"title":"Two to call","body":"Dana came in at 81."}```'

    with mock.patch.object(ne, "_sb", side_effect=sb), \
         mock.patch.object(ne, "_gather_morning_data", side_effect=with_leads), \
         mock.patch.object(ne, "_call_claude", side_effect=claude):
        out = asyncio.run(ne._generate_morning_brief(None, "biz-1"))

    assert out["created"] is True
    brief = [b for p, b in posted if p == "/chief_notifications"][0]
    assert brief["type"] == "morning_brief"


def test_the_morning_gather_asks_about_leads():
    """A brief that reports drafts, sessions and invoices but never the
    people who just asked to become customers is reporting the wrong
    day."""
    sb, _, gets = _fake_sb()
    with mock.patch.object(ne, "_sb", side_effect=sb):
        data = asyncio.run(ne._gather_morning_data(None, "biz-1"))
    assert "new_leads_24h" in data and "hot_leads" in data
    lead_queries = [p for p in gets if "status=eq.lead" in p]
    assert len(lead_queries) == 2, gets
    assert any("lead_score=gte.70" in p for p in lead_queries)
    assert all("+00:00" not in p for p in gets)


def test_no_query_this_module_builds_carries_a_plus_offset():
    """The sweep, not the spot check. '+' decodes to a space in a query
    string, so a '+00:00' timestamp turns a filter into a filter that
    matches nothing — and returns 200 with an empty list, which reads as
    a quiet day. Every window this module opens goes through _z()."""
    sb, _, gets = _fake_sb()
    with mock.patch.object(ne, "_sb", side_effect=sb):
        for run in (
            lambda: ne._gather_morning_data(None, "biz-1"),
            lambda: ne._gather_midday_data(None, "biz-1"),
            lambda: ne._gather_evening_data(None, "biz-1"),
            lambda: ne._check_urgent(None, "biz-1"),
            lambda: ne.urgent_candidates(None),
            lambda: ne._existing_today(None, "biz-1", "morning_brief"),
            lambda: ne._existing_within(None, "biz-1", "midday_ping", 4),
            lambda: ne._dedup_key_exists(None, "biz-1", "k"),
        ):
            asyncio.run(run())
    assert gets, "nothing was queried — the sweep proves nothing"
    offenders = [p for p in gets if "+00:00" in p]
    assert not offenders, offenders


# ═══════════════════════════════════════════════════════════════════════
# The jobs are registered — the whole point of the PR
# ═══════════════════════════════════════════════════════════════════════

def _registered_jobs():
    """Every scheduler.add_job(...) in startup(), as {id: {kwargs}}.

    Reads the AST of the call rather than the file text, so the prose in
    this heavily-commented function cannot satisfy the assertion.
    """
    import kmj_intake_automation as kia
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(kia.startup)))
    jobs = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "add_job"):
            continue
        kwargs = {k.arg: k.value for k in node.keywords}
        job_id = kwargs.get("id")
        if not isinstance(job_id, ast.Constant):
            continue
        jobs[job_id.value] = {
            "kwargs": {k: (v.value if isinstance(v, ast.Constant)
                           else ast.unparse(v))
                       for k, v in kwargs.items()},
            "trigger": (node.args[1].value
                        if len(node.args) > 1 and isinstance(node.args[1], ast.Constant)
                        else None),
            "target": ast.unparse(node.args[0]) if node.args else "",
        }
    return jobs


NOTIF_JOBS = {
    "notif_urgent_check": "check_urgent_for_all",
    "notif_morning_brief": "generate_morning_brief_for_all",
    "notif_midday_ping": "generate_midday_ping_for_all",
    "notif_evening_summary": "generate_evening_summary_for_all",
}


def test_all_four_notification_ticks_are_scheduled():
    jobs = _registered_jobs()
    for job_id, fn in NOTIF_JOBS.items():
        assert job_id in jobs, f"{job_id} is not registered — the alarm cannot ring"
        assert fn in jobs[job_id]["target"], jobs[job_id]["target"]


def test_every_notification_job_runs_behind_the_leader_lease():
    """Unlogged double-sends: without the gate, every replica would
    write the same notification."""
    jobs = _registered_jobs()
    for job_id in NOTIF_JOBS:
        assert jobs[job_id]["target"].startswith("g("), jobs[job_id]["target"]


def test_the_urgent_check_runs_at_least_as_often_as_its_window():
    """URGENT_LOOKBACK_MINUTES is the window _check_urgent scans. A
    slower tick would let a lead arrive, age out, and never alert."""
    job = _registered_jobs()["notif_urgent_check"]
    assert job["trigger"] == "interval"
    assert job["kwargs"]["minutes"] == "_notif.URGENT_LOOKBACK_MINUTES"


def test_the_three_briefs_are_cron_not_interval():
    """An interval brief drifts with every deploy; these have to land at
    a time of day a person recognises."""
    jobs = _registered_jobs()
    hours = {}
    for job_id in ("notif_morning_brief", "notif_midday_ping",
                   "notif_evening_summary"):
        assert jobs[job_id]["trigger"] == "cron", job_id
        hours[job_id] = jobs[job_id]["kwargs"]["hour"]
    assert len(set(hours.values())) == 3, hours
    assert hours["notif_morning_brief"] < hours["notif_midday_ping"] \
        < hours["notif_evening_summary"], hours


def test_there_is_a_kill_switch():
    import kmj_intake_automation as kia
    src = inspect.getsource(kia.startup)
    assert 'os.environ.get("NOTIF_JOBS")' in src


def test_the_briefs_only_run_where_jobs_run():
    """PROCESS_ROLE=web must not send notifications; the worker does."""
    import kmj_intake_automation as kia
    with mock.patch.dict(os.environ, {"PROCESS_ROLE": "web"}):
        assert kia.runs_scheduled_jobs() is False
    with mock.patch.dict(os.environ, {"PROCESS_ROLE": "worker"}):
        assert kia.runs_scheduled_jobs() is True


# ═══════════════════════════════════════════════════════════════════════
# The push brief mentions leads
# ═══════════════════════════════════════════════════════════════════════

def test_the_push_morning_brief_leads_with_leads():
    import push_notifications as pn

    sent = {}

    def fake_get(path):
        if path.startswith("/push_subscriptions"):
            return [{"business_id": "biz-1"}]
        if path.startswith("/businesses"):
            return [{"name": "Test Co", "settings": {}}]
        if "status=eq.lead" in path and "lead_score=gte.70" in path:
            return [{"id": "c-1"}]
        if "status=eq.lead" in path:
            return [{"id": "c-1"}, {"id": "c-2"}]
        if path.startswith("/sessions"):
            return [{"id": "s-1"}]
        return []

    with mock.patch.object(pn, "push_enabled", return_value=True), \
         mock.patch.object(pn.sb_clients, "sb_get_as_service", side_effect=fake_get), \
         mock.patch.object(pn, "send_to_business",
                           side_effect=lambda *a, **k: sent.update(k)):
        asyncio.run(pn.morning_brief_tick())

    body = sent["body"]
    assert "2 new leads" in body
    assert "1 worth calling first" in body
    # Leads first: an enquiry from this morning outranks a draft that
    # has been sitting there a week.
    assert body.index("new leads") < body.index("session")
