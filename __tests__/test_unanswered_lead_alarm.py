"""
test_unanswered_lead_alarm.py — THE LEAD ARC PR 5.

PR 4 gave the system a clock. This is the thing that reads it out loud.

Rehearsed end to end, with the negative controls that prove the
rehearsal can fail — an alarm that has never been seen to fire and an
alarm that fires for everything are equally useless.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import notification_engine as ne  # noqa: E402


# 4pm UTC — inside waking hours, so the quiet-hours gate is not what
# any of these tests is measuring.
NOON = datetime(2026, 8, 14, 16, 0, tzinfo=timezone.utc)


def z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def lead(name="Dana Reyes", hours_ago=9, cid="c-1", biz="biz-1", score=None):
    return {"id": cid, "name": name, "business_id": biz,
            "created_at": z(NOON - timedelta(hours=hours_ago)),
            "lead_score": score, "source": "website_contact_form"}


def _sweep(waiting, settings=None, active=("biz-1",), already_alerted=False,
           now=NOON):
    posted, gets = [], []

    async def sb(client, method, path, body=None):
        if method == "POST":
            posted.append((path, body))
            return [dict(body or {}, id="n-1")]
        gets.append(path)
        if path.startswith("/contacts"):
            return list(waiting)
        if path.startswith("/businesses?is_active"):
            return [{"id": b} for b in active]
        if path.startswith("/businesses"):
            return [{"id": "biz-1", "name": "Test Co",
                     "settings": settings or {}}]
        if path.startswith("/chief_notifications"):
            return [{"id": "old"}] if already_alerted else []
        return []

    with mock.patch.object(ne, "_sb", side_effect=sb):
        out = asyncio.run(ne.unanswered_lead_sweep(now=now))
    return out, posted, gets


def _alerts(posted):
    return [b for p, b in posted if p == "/chief_notifications"]


# ═══════════════════════════════════════════════════════════════════════
# It fires
# ═══════════════════════════════════════════════════════════════════════

def test_a_lead_left_waiting_raises_an_alert():
    out, posted, _ = _sweep([lead(hours_ago=9)])
    alerts = _alerts(posted)
    assert len(alerts) == 1, f"nothing was raised: {posted}"
    a = alerts[0]
    assert a["type"] == "urgent_alert"
    assert "Dana Reyes" in a["title"]
    assert "9 hours" in a["body"]
    assert a["related_contact_id"] == "c-1"
    assert out["alerts"] == 1


def test_the_alert_can_be_acted_on():
    """A notification that names a problem and offers no way to it is a
    guilt generator, not a tool."""
    _, posted, _ = _sweep([lead()])
    a = _alerts(posted)[0]
    assert a["suggested_action"] == "Open Dana Reyes"
    assert a["action_payload"]["contact_id"] == "c-1"
    assert a["action_payload"]["type"] == "navigate"


def test_a_long_wait_is_told_in_days_not_hours():
    """'73 hours' makes a reader do arithmetic to feel bad."""
    _, posted, _ = _sweep([lead(hours_ago=73)])
    assert "3 days" in _alerts(posted)[0]["body"]


def test_a_hot_lead_says_so():
    _, posted, _ = _sweep([lead(score=88)])
    assert "88" in _alerts(posted)[0]["body"]


def test_a_middling_score_is_not_mentioned():
    """Noise. The point of the alert is the waiting, not the score."""
    _, posted, _ = _sweep([lead(score=41)])
    assert "41" not in _alerts(posted)[0]["body"]


# ═══════════════════════════════════════════════════════════════════════
# It does not fire — the controls
# ═══════════════════════════════════════════════════════════════════════

def test_nothing_waiting_raises_nothing():
    out, posted, _ = _sweep([])
    assert out == {"businesses": 0, "alerts": 0}
    assert not posted


def test_a_lead_inside_the_threshold_is_left_alone():
    """The default is four hours. Two hours old is not a failure — it
    is a Tuesday."""
    out, posted, _ = _sweep([lead(hours_ago=2)])
    assert out["alerts"] == 0
    assert not _alerts(posted)


def test_the_business_can_move_its_own_threshold():
    settings = {"notifications": {"lead_response_hours": 24}}
    out, posted, _ = _sweep([lead(hours_ago=9)], settings=settings)
    assert out["alerts"] == 0, "a 9h wait alerted under a 24h threshold"
    out, posted, _ = _sweep([lead(hours_ago=30)], settings=settings)
    assert out["alerts"] == 1


def test_a_nonsense_threshold_falls_back_to_the_default():
    """Settings are user-editable JSON. A string where a number belongs
    must not silence the alarm."""
    out, _, _ = _sweep([lead(hours_ago=9)],
                       settings={"notifications": {"lead_response_hours": "soon"}})
    assert out["alerts"] == 1


def test_nobody_is_woken_at_three_in_the_morning():
    """Businesses do not store a timezone, so this uses the same UTC
    compromise as the briefs. An alarm that goes off at 3am is an alarm
    that gets turned off."""
    out, posted, _ = _sweep([lead(hours_ago=20)],
                            now=NOON.replace(hour=4))
    assert out["skipped"] == "quiet_hours"
    assert not posted


def test_waking_hours_still_fire():
    """The other half of the gate — otherwise 'quiet hours' could mean
    'always'."""
    for hour in (13, 17, 22):
        out, posted, _ = _sweep([lead(hours_ago=9)], now=NOON.replace(hour=hour))
        assert out.get("alerts") == 1, hour


def test_a_business_is_told_once_a_day_not_once_an_hour():
    """The sweep runs hourly so the FIRST alert lands soon after the
    threshold. Re-raising a standing condition every hour is how a
    notification surface gets muted."""
    assert ne.LEAD_WAIT_DEDUP_HOURS == 24
    out, posted, _ = _sweep([lead()], already_alerted=True)
    assert out["alerts"] == 0
    assert not _alerts(posted)


def test_an_inactive_business_is_skipped():
    out, posted, _ = _sweep([lead()], active=("biz-other",))
    assert out["alerts"] == 0
    assert not _alerts(posted)


def test_a_business_that_turned_urgent_alerts_off_is_respected():
    out, posted, _ = _sweep(
        [lead()], settings={"notifications": {"urgent_alerts": False}})
    assert out["alerts"] == 0
    assert not _alerts(posted)


# ═══════════════════════════════════════════════════════════════════════
# One alert per business, not one per lead
# ═══════════════════════════════════════════════════════════════════════

def test_thirty_waiting_leads_produce_one_notification():
    """A business with thirty leads waiting does not need thirty
    notifications. It needs to be told there are thirty, and which one
    has waited longest."""
    leads = [lead(name=f"Person {i}", hours_ago=5 + i, cid=f"c-{i}")
             for i in range(30)]
    out, posted, _ = _sweep(leads)
    alerts = _alerts(posted)
    assert len(alerts) == 1, f"raised {len(alerts)} alerts for one business"
    assert out["alerts"] == 1
    assert "30 leads are still waiting" in alerts[0]["title"]


def test_the_summary_names_the_longest_wait():
    leads = [lead(name="Recent", hours_ago=5, cid="c-a"),
             lead(name="Forgotten", hours_ago=40, cid="c-b")]
    _, posted, _ = _sweep(leads)
    a = _alerts(posted)[0]
    assert "Forgotten" in a["body"]
    assert a["related_contact_id"] == "c-b"


def test_the_count_is_of_OVERDUE_leads_not_everything_returned():
    """The platform query uses a one-hour floor and per-business
    thresholds are applied afterwards. If the count came from the query
    it would report leads that are not actually late."""
    leads = [lead(name="Late", hours_ago=9, cid="c-a"),
             lead(name="Fresh", hours_ago=2, cid="c-b"),
             lead(name="Fresh2", hours_ago=1.5, cid="c-c")]
    _, posted, _ = _sweep(leads)
    a = _alerts(posted)[0]
    assert "Late" in a["title"] or "Late" in a["body"]
    assert "3 leads" not in a["body"]


def test_one_business_failing_does_not_stop_the_others():
    posted = []
    calls = {"n": 0}

    async def sb(client, method, path, body=None):
        if method == "POST":
            posted.append(body)
            return [dict(body or {}, id="n-1")]
        if path.startswith("/contacts"):
            return [lead(cid="c-1", biz="biz-1"),
                    lead(cid="c-2", biz="biz-2", name="Other")]
        if path.startswith("/businesses?is_active"):
            return [{"id": "biz-1"}, {"id": "biz-2"}]
        if path.startswith("/businesses?id=eq.biz-1"):
            calls["n"] += 1
            raise RuntimeError("biz-1 is having a bad day")
        if path.startswith("/businesses"):
            return [{"id": "biz-2", "settings": {}}]
        return []

    with mock.patch.object(ne, "_sb", side_effect=sb):
        out = asyncio.run(ne.unanswered_lead_sweep(now=NOON))
    assert calls["n"] == 1
    assert out["alerts"] == 1, "the healthy business lost its alert too"


# ═══════════════════════════════════════════════════════════════════════
# It reads the clock, and it is scheduled
# ═══════════════════════════════════════════════════════════════════════

def test_it_reads_first_response_at_not_last_interaction():
    """last_interaction moves when THEY touch us — a lead who chases
    twice would look attended to. first_response_at only moves when we
    reply."""
    _, _, gets = _sweep([])
    q = [g for g in gets if g.startswith("/contacts")][0]
    assert "first_response_at=is.null" in q
    assert "status=eq.lead" in q
    assert "last_interaction" not in q
    assert "+00:00" not in q


def test_the_sweep_is_scheduled_and_gated():
    import ast
    import inspect
    import textwrap

    import kmj_intake_automation as kia
    tree = ast.parse(textwrap.dedent(inspect.getsource(kia.startup)))
    found = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_job"):
            kw = {k.arg: k.value for k in node.keywords}
            jid = kw.get("id")
            if isinstance(jid, ast.Constant) and jid.value == "notif_unanswered_leads":
                found = (ast.unparse(node.args[0]), node.args[1].value,
                         kw["hours"].value)
    assert found, "notif_unanswered_leads is not registered"
    target, trigger, hours = found
    assert "unanswered_lead_sweep" in target
    assert target.startswith("g("), "not gated to the leader lease"
    assert trigger == "interval" and hours == 1
