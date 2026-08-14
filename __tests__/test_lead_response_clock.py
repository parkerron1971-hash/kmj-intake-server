"""
test_lead_response_clock.py — THE LEAD ARC PR 4.

Nothing in either repo measured how long a lead waited. The nearest
thing flagged one at thirty days old plus fourteen silent.

The clock is DERIVED from records the outbound paths already leave,
rather than stamped at six send sites (one of which is the frontend).
So the tests are mostly about the derivation being right — because a
wrong derivation reads as "nobody ever answered this person", and a
false alarm is the fastest way to teach someone to ignore a real one.
"""
from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import lead_response as lr  # noqa: E402


BORN = datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)


def z(dt):
    return dt.isoformat().replace("+00:00", "Z")


def contact(cid="c-1", born=BORN, business="biz-1"):
    return {"id": cid, "business_id": business, "created_at": z(born)}


def _db(sms=None, queue=None, events=None, sessions=None, contacts=None):
    """A fake PostgREST keyed on the path prefix, plus the PATCHes."""
    patches = []
    gets = []

    def get(path):
        gets.append(path)
        if path.startswith("/sms_messages"):
            return sms or []
        if path.startswith("/agent_queue"):
            return queue or []
        if path.startswith("/events"):
            return events or []
        if path.startswith("/sessions"):
            return sessions or []
        if path.startswith("/contacts"):
            return contacts or []
        return []

    def patch(path, body):
        patches.append((path, body))
        return [{}]

    import sb_clients
    return (mock.patch.object(sb_clients, "sb_get_as_service", side_effect=get),
            mock.patch.object(sb_clients, "sb_patch_as_service", side_effect=patch),
            patches, gets)


def _derive(**kw):
    g, p, patches, gets = _db(**kw)
    with g, p:
        return lr.first_response_times([contact()]), gets


# ═══════════════════════════════════════════════════════════════════════
# What counts as a response
# ═══════════════════════════════════════════════════════════════════════

def test_an_outbound_sms_is_a_response():
    at = BORN + timedelta(minutes=42)
    found, _ = _derive(sms=[{"contact_id": "c-1", "created_at": z(at)}])
    assert found["c-1"] == at


def test_a_sent_queue_row_is_a_response():
    at = BORN + timedelta(hours=3)
    found, _ = _derive(queue=[{"contact_id": "c-1", "sent_at": z(at),
                               "created_at": z(BORN)}])
    assert found["c-1"] == at


def test_a_session_on_the_calendar_is_a_response():
    at = BORN + timedelta(hours=1)
    found, _ = _derive(sessions=[{"contact_id": "c-1", "created_at": z(at)}])
    assert found["c-1"] == at


def test_a_spine_message_event_is_a_response():
    at = BORN + timedelta(minutes=10)
    found, _ = _derive(events=[{"contact_id": "c-1",
                                "event_type": "agent_message_sent",
                                "created_at": z(at), "data": {}}])
    assert found["c-1"] == at


def test_triaging_a_lead_by_hand_is_a_response():
    """Moving somebody off 'lead' means a person looked and decided."""
    at = BORN + timedelta(hours=2)
    found, _ = _derive(events=[{"contact_id": "c-1",
                                "event_type": "contact_status_changed",
                                "created_at": z(at),
                                "data": {"from": "lead", "to": "active"}}])
    assert found["c-1"] == at


def test_both_status_event_payload_shapes_are_understood():
    """chief_of_staff writes from_status/to_status; ContactDetail.tsx
    writes from/to. Reading only one shape would silently miss half the
    triage in the system."""
    at = BORN + timedelta(hours=2)
    found, _ = _derive(events=[{"contact_id": "c-1",
                                "event_type": "contact_status_changed",
                                "created_at": z(at),
                                "data": {"from_status": "lead",
                                         "to_status": "vip"}}])
    assert found["c-1"] == at


def test_the_earliest_response_wins():
    early = BORN + timedelta(minutes=5)
    late = BORN + timedelta(days=2)
    found, _ = _derive(
        sms=[{"contact_id": "c-1", "created_at": z(late)}],
        sessions=[{"contact_id": "c-1", "created_at": z(early)}],
        queue=[{"contact_id": "c-1", "sent_at": z(late), "created_at": z(BORN)}])
    assert found["c-1"] == early


# ═══════════════════════════════════════════════════════════════════════
# What does NOT count
# ═══════════════════════════════════════════════════════════════════════

def test_a_draft_nobody_sent_is_not_a_response():
    """A draft sitting in the approval queue is the OPPOSITE of a
    response. Counting created_at here would mark every scored lead as
    answered the instant it arrived — the alarm would never fire."""
    found, _ = _derive(queue=[{"contact_id": "c-1", "sent_at": None,
                               "created_at": z(BORN + timedelta(minutes=1))}])
    assert found == {}


def test_an_inbound_message_is_not_a_response():
    """The query asks for direction=eq.outbound. If it ever stopped
    doing so, a lead who chased US would look answered."""
    _, gets = _derive()
    sms_query = [g for g in gets if g.startswith("/sms_messages")][0]
    assert "direction=eq.outbound" in sms_query


def test_moving_somebody_INTO_lead_is_not_a_response():
    found, _ = _derive(events=[{"contact_id": "c-1",
                                "event_type": "contact_status_changed",
                                "created_at": z(BORN + timedelta(hours=1)),
                                "data": {"from": "active", "to": "lead"}}])
    assert found == {}


def test_activity_from_before_they_arrived_is_not_a_response():
    """A long-standing client who fills in the website form would
    otherwise inherit last year's outbound SMS and read as answered
    instantly."""
    found, _ = _derive(sms=[{"contact_id": "c-1",
                             "created_at": z(BORN - timedelta(days=200))}])
    assert found == {}


def test_no_response_means_absent_not_null():
    """'Not yet' and 'unknown' are different facts. Mapping to None
    would let a caller write null over a real value, or treat a waiting
    lead as one it had already checked."""
    found, _ = _derive()
    assert found == {}
    assert "c-1" not in found


# ═══════════════════════════════════════════════════════════════════════
# The tick
# ═══════════════════════════════════════════════════════════════════════

def test_the_tick_stamps_what_it_finds():
    at = BORN + timedelta(minutes=30)
    g, p, patches, _ = _db(contacts=[contact()],
                           sms=[{"contact_id": "c-1", "created_at": z(at)}])
    with g, p:
        out = lr.reconcile_tick()
    assert out == {"scanned": 1, "stamped": 1, "still_waiting": 0}
    path, body = patches[0]
    assert "id=eq.c-1" in path and "business_id=eq.biz-1" in path
    assert body == {"first_response_at": z(at)}


def test_a_waiting_lead_is_left_null_and_rechecked():
    """NULL means 'not yet', not 'unknown'. Writing anything here would
    make the lead invisible to the alarm that is supposed to catch it."""
    g, p, patches, _ = _db(contacts=[contact()])
    with g, p:
        out = lr.reconcile_tick()
    assert out == {"scanned": 1, "stamped": 0, "still_waiting": 1}
    assert not patches


def test_the_tick_only_looks_at_contacts_missing_the_value():
    g, p, _, gets = _db(contacts=[])
    with g, p:
        lr.reconcile_tick()
    q = [x for x in gets if x.startswith("/contacts")][0]
    assert "first_response_at=is.null" in q
    assert "+00:00" not in q


def test_the_tick_is_not_limited_to_open_leads():
    """Somebody answered and converted still needs a response time, or
    the median is computed only over the ones nobody got back to."""
    g, p, _, gets = _db(contacts=[])
    with g, p:
        lr.reconcile_tick()
    q = [x for x in gets if x.startswith("/contacts")][0]
    assert "status=eq.lead" not in q


def test_the_tick_survives_a_database_that_is_down():
    import sb_clients
    with mock.patch.object(sb_clients, "sb_get_as_service",
                           side_effect=RuntimeError("boom")):
        out = lr.reconcile_tick()
    assert out["stamped"] == 0 and "error" in out


def test_a_failed_write_does_not_abandon_the_rest():
    import sb_clients
    at = BORN + timedelta(minutes=5)
    rows = [contact("c-1"), contact("c-2")]

    def get(path):
        if path.startswith("/contacts"):
            return rows
        if path.startswith("/sms_messages"):
            return [{"contact_id": "c-1", "created_at": z(at)},
                    {"contact_id": "c-2", "created_at": z(at)}]
        return []

    calls = []

    def patch(path, body):
        calls.append(path)
        if "c-1" in path:
            raise RuntimeError("transient")
        return [{}]

    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=get), \
         mock.patch.object(sb_clients, "sb_patch_as_service", side_effect=patch):
        out = lr.reconcile_tick()
    assert len(calls) == 2, "it gave up after the first failure"
    assert out["stamped"] == 1


def test_large_batches_are_chunked_into_the_url():
    """`in.(...)` lives in the query string. 500 uuids in one URL is a
    414 from the proxy, and a 414 here looks like 'no responses found'
    — every lead in the system marked unanswered at once."""
    import sb_clients
    rows = [contact(f"c-{i}") for i in range(250)]
    gets = []

    def get(path):
        gets.append(path)
        return rows if path.startswith("/contacts") else []

    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=get), \
         mock.patch.object(sb_clients, "sb_patch_as_service", return_value=[{}]):
        lr.reconcile_tick()
    import re
    sms = [g for g in gets if g.startswith("/sms_messages")]
    assert len(sms) == 3, f"expected 250/{lr.CHUNK} chunks, got {len(sms)}"
    per_call = [len(re.search(r"contact_id=in\.\(([^)]*)\)", g).group(1).split(","))
                for g in sms]
    assert max(per_call) <= lr.CHUNK, per_call
    assert sum(per_call) == 250, per_call


# ═══════════════════════════════════════════════════════════════════════
# Reading it back
# ═══════════════════════════════════════════════════════════════════════

def _stats(answered, waiting=()):
    import sb_clients

    def get(path):
        if "first_response_at=not.is.null" in path:
            return list(answered)
        if "first_response_at=is.null" in path:
            return list(waiting)
        return []

    with mock.patch.object(sb_clients, "sb_get_as_service", side_effect=get):
        return lr.response_stats("biz-1")


def answered_in(minutes, cid="c"):
    return {"id": cid, "name": cid, "created_at": z(BORN),
            "first_response_at": z(BORN + timedelta(minutes=minutes))}


def test_the_headline_is_a_median_not_a_mean():
    """One lead answered three weeks late must not make forty answered
    within the hour look like a two-day response time."""
    rows = [answered_in(m, f"c{i}") for i, m in
            enumerate([5, 8, 10, 12, 30240])]        # last = 21 days
    out = _stats(rows)
    assert out["median_minutes"] == 10
    assert out["slowest_minutes"] == 30240           # the outlier, named


def test_an_even_count_averages_the_middle_pair():
    out = _stats([answered_in(m, f"c{i}") for i, m in enumerate([10, 20, 30, 40])])
    assert out["median_minutes"] == 25


def test_no_answered_leads_reports_none_not_zero():
    """Zero would read as 'we answer instantly'. There is no median of
    nothing, and saying so is the honest empty state."""
    out = _stats([])
    assert out["median_minutes"] is None
    assert out["answered"] == 0


def test_the_reconciler_is_actually_scheduled():
    """A derived column with nothing deriving it is a column of nulls,
    and a column of nulls reads as 'nobody ever answers anyone'."""
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
            kwargs = {k.arg: k.value for k in node.keywords}
            jid = kwargs.get("id")
            if isinstance(jid, ast.Constant) and jid.value == "lead_response_reconcile":
                found = (ast.unparse(node.args[0]),
                         node.args[1].value,
                         kwargs["minutes"].value)
    assert found, "lead_response_reconcile is not registered"
    target, trigger, minutes = found
    assert "reconcile_tick" in target
    assert target.startswith("g("), "not gated to the leader lease"
    assert trigger == "interval" and minutes == 15


def test_the_oldest_wait_is_measured_from_the_front_of_the_queue():
    waiting = [{"id": "w1", "name": "First", "lead_score": 80,
                "created_at": z(datetime.now(timezone.utc) - timedelta(hours=30))}]
    out = _stats([], waiting)
    assert out["waiting"] == 1
    assert 29 < out["oldest_wait_hours"] < 31
