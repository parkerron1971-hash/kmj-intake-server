"""Layer-two scheduling capability: complete evidence, no writes, one tool round."""
import asyncio
from functools import wraps
from copy import deepcopy
from datetime import datetime, timezone
import json
from urllib.parse import parse_qs, urlsplit

import pytest
from pydantic import ValidationError

import booking_rehearsal as br


def run_async(test):
    """Use the repository's stdlib event-loop runner, with no pytest plugin."""
    @wraps(test)
    def run(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))
    return run

BID = "11111111-1111-4111-8111-111111111111"
OID = "22222222-2222-4222-8222-222222222222"
OTHER = "33333333-3333-4333-8333-333333333333"
OWNER = "44444444-4444-4444-8444-444444444444"
NOW = datetime(2030, 1, 7, 12, tzinfo=timezone.utc)  # Monday, before NYC opening
HOURS = {"timezone": "America/New_York", "weekly": {
    "mon": [{"start": "09:00", "end": "17:00"}],
    "tue": [{"start": "09:00", "end": "17:00"}]},
    "slot_granularity_min": 30, "lead_time_min": 0}
SERVICE = {"id": OID, "business_id": BID, "is_active": True, "duration_min": 60}


def plan(*starts):
    return br.BookingPlan(appointments=[{"offering_id": OID, "start": s} for s in starts])


def booking(start="2030-01-07T14:00:00Z", duration=60, id="bk1", **extra):
    return {"id": id, "business_id": BID, "status": "active", "appointment_at": start,
            "duration_min_at_booking": duration, **extra}


def check(p=None, **changes):
    inputs = dict(business_id=BID, availability=deepcopy(HOURS), practitioner_tz=None,
                  offerings=[deepcopy(SERVICE)], bookings=[], now=NOW)
    inputs.update(changes)
    return br.rehearse(p or plan("2030-01-07T09:00:00-05:00"), **inputs)


def test_rehearses_plan_together_and_never_mutates_inputs():
    bookings = []
    p = plan("2030-01-07T09:00:00-05:00", "2030-01-07T09:30:00-05:00",
             "2030-01-07T10:00:00-05:00")
    result = check(p, bookings=bookings)
    assert [a["status"] for a in result["appointments"]] == ["fits", "conflict", "fits"]
    assert bookings == []
    assert result["appointments"][1]["alternatives"][0]["start_local"] == "2030-01-07T10:00:00-05:00"
    assert result["status"] == "conflicts"
    assert "Nothing reserved" in result["execution_required"]


def test_current_bookings_and_capacity_are_used():
    hours = deepcopy(HOURS)
    hours["concurrent_capacity"] = 2
    result = check(plan("2030-01-07T14:00:00Z", "2030-01-07T14:00:00Z"),
                   availability=hours, bookings=[booking()])
    assert [a["status"] for a in result["appointments"]] == ["fits", "conflict"]
    assert "bk1" not in json.dumps(result)  # occupancy evidence, not customer records


@pytest.mark.parametrize("changes", [
    {"lead_time_min": 180},
    {"blocks": [{"start": "2030-01-07", "end": "2030-01-07"}]},
    {"overrides": [{"date": "2030-01-07", "hours": []}]},
])
def test_respects_lead_time_blocks_and_overrides(changes):
    assert check(availability={**deepcopy(HOURS), **changes})["status"] == "conflicts"


def test_dependency_fingerprints_change_only_for_relevant_inputs():
    baseline = check()
    unrelated = check(availability={**HOURS, "unrelated_theme": "blue"})
    assert baseline["dependencies"] == unrelated["dependencies"]
    later = check(now=NOW.replace(minute=1))
    assert baseline["snapshot_fingerprint"] == later["snapshot_fingerprint"]
    assert baseline["checked_at"] != later["checked_at"]
    changed = check(bookings=[booking()])
    assert baseline["dependencies"]["bookings"] != changed["dependencies"]["bookings"]
    assert baseline["dependencies"]["offerings"] == changed["dependencies"]["offerings"]
    assert baseline["snapshot_fingerprint"] != changed["snapshot_fingerprint"]


def test_fingerprints_ignore_database_row_order():
    rows = [booking(), booking("2030-01-07T16:00:00Z", id="bk2")]
    assert check(bookings=rows)["dependencies"] == check(bookings=list(reversed(rows)))["dependencies"]


@pytest.mark.parametrize("changes", [
    {"availability": {}},
    {"availability": {**HOURS, "timezone": "bad/timezone"}},
    {"availability": {**HOURS, "weekly": {"mon": [{"start": "bad", "end": "17:00"}]}}},
    {"offerings": []},
    {"offerings": [{**SERVICE, "business_id": OTHER}]},
    {"offerings": [{**SERVICE, "is_active": False}]},
    {"offerings": [{**SERVICE, "duration_min": None}]},
    {"bookings": [booking(duration=None)]},
    {"bookings": [booking(start="not a date")]},
    {"bookings": [booking(business_id=OTHER)]},
    {"bookings": [booking(duration=0, duration_min=60)]},
])
def test_missing_or_malformed_evidence_never_means_free(changes):
    with pytest.raises((br.RehearsalUnavailable, ValidationError)):
        check(**changes)


@pytest.mark.parametrize("payload", [
    {"appointments": []},
    {"appointments": [{"offering_id": OID, "start": "2030-01-07T09:00:00"}]},
    {"appointments": [{"offering_id": "x)&business_id=eq.other", "start": "2030-01-07T14:00:00Z"}]},
    {"appointments": [{"offering_id": OID, "start": "2030-01-07T14:00:00Z", "staff_id": "x"}]},
    {"appointments": [{"offering_id": OID, "start": "2030-01-07T14:00:00Z", "booking_id": "x"}]},
    {"appointments": [{"offering_id": OID, "start": 1894010400}]},
    {"appointments": [{"offering_id": OID, "start": "1894010400"}]},
    {"appointments": [{"offering_id": OID, "start": "1894010400000"}]},
    {"appointments": [{"offering_id": OID, "start": "2030-01-07T14:00:00Z"}] * 9},
])
def test_plan_rejects_ambiguous_or_unsupported_requests(payload):
    with pytest.raises(ValidationError):
        br.BookingPlan.model_validate(payload)


def test_long_span_is_bounded():
    with pytest.raises(br.RehearsalUnavailable):
        check(plan("2030-01-07T14:00:00Z", "2030-03-07T14:00:00Z"))


def test_invalid_block_cannot_silently_open_calendar():
    with pytest.raises(ValueError):
        check(availability={**HOURS, "blocks": [{"start": "2030-02-31", "end": "2030-03-01"}]})


def test_timezone_is_not_guessed(monkeypatch):
    monkeypatch.delenv("PLATFORM_DEFAULT_TZ", raising=False)
    with pytest.raises(br.RehearsalUnavailable, match="timezone"):
        check(availability={**HOURS, "timezone": None})


def test_dst_alternatives_are_real_local_instants():
    hours = {"timezone": "America/New_York", "weekly": {
        "sun": [{"start": "01:00", "end": "05:00"}]}, "slot_granularity_min": 30}
    result = check(plan("2030-03-10T01:30:00-05:00"), availability=hours,
                   now=datetime(2030, 3, 9, tzinfo=timezone.utc))
    assert result["status"] == "conflicts"  # duration crosses DST; defer conservatively
    for slot in result["appointments"][0]["alternatives"]:
        utc = datetime.fromisoformat(slot["start_utc"])
        local = datetime.fromisoformat(slot["start_local"])
        assert utc == local
        assert local.hour != 2


def fake_reads(monkeypatch, *, rows=None, override=None):
    calls = []
    rows = rows or []
    async def read(client, method, path):
        calls.append((method, path))
        assert method == "GET", "rehearsal must never write"
        parsed = urlsplit(path)
        query = parse_qs(parsed.query)
        if parsed.path == "/businesses":
            result = [{"id": BID, "owner_id": OWNER, "settings": {"availability": deepcopy(HOURS)}}]
            assert query["id"] == ["eq." + BID]
        else:
            assert query["business_id"] == ["eq." + BID]
            if parsed.path == "/offerings":
                result = [deepcopy(SERVICE)]
            elif parsed.path == "/calendar_busy_blocks":
                result = []
            else:
                assert parsed.path == "/module_entries"
                assert query["select"] == ["id,business_id,status,appointment_at,duration_min_at_booking"]
                offset = int(query["offset"][0])
                # Simulate a server returning short pages; loader must continue.
                result = rows[offset:offset + 1]
        return override(parsed.path, result) if override else result
    monkeypatch.setattr(br, "_sb", read)
    monkeypatch.setattr(br, "_busy_get", read)
    return calls


@run_async
async def test_handler_pages_to_exhaustion_and_ignores_stale_context(monkeypatch):
    calls = fake_reads(monkeypatch, rows=[booking(), booking("2030-01-07T16:00:00Z", id="bk2")])
    result = await br.handle_rehearse_booking_plan(None, {"id": BID, "owner_id": OWNER, "settings": {}},
        {"type": br.VERB, **plan("2030-01-07T14:00:00Z").model_dump(mode="json")})
    assert result["status"] == "conflicts"
    assert len([p for _, p in calls if p.startswith("/module_entries")]) == 3


@run_async
async def test_grouped_plan_loads_one_snapshot_instead_of_eight(monkeypatch):
    calls = fake_reads(monkeypatch)
    args = plan(*(["2030-01-07T14:00:00Z"] * 8)).model_dump(mode="json")
    result = await br.handle_rehearse_booking_plan(None, {"id": BID, "owner_id": OWNER}, args)
    assert len(result["appointments"]) == 8
    assert len(calls) == 4  # business, offerings, empty bookings and busy blocks
    calls.clear()
    for appointment in args["appointments"]:
        await br.handle_rehearse_booking_plan(None, {"id": BID, "owner_id": OWNER}, {"appointments": [appointment]})
    assert len(calls) == 32  # controlled empty-calendar comparison, not production savings


@run_async
@pytest.mark.parametrize("bad_path", ["/businesses", "/offerings", "/module_entries", "/calendar_busy_blocks"])
async def test_read_failure_is_unavailable_not_empty(monkeypatch, bad_path):
    fake_reads(monkeypatch, override=lambda path, result: None if path == bad_path else result)
    result = await br.handle_rehearse_booking_plan(None, {"id": BID, "owner_id": OWNER}, plan("2030-01-07T14:00:00Z").model_dump(mode="json"))
    assert result["failed"] is True
    assert result["status"] == "needs_review"
    assert "appointments" not in result


@run_async
async def test_caller_cannot_override_business(monkeypatch):
    calls = fake_reads(monkeypatch)
    result = await br.handle_rehearse_booking_plan(None, {"id": BID, "owner_id": OWNER}, {
        **plan("2030-01-07T14:00:00Z").model_dump(mode="json"), "business_id": OTHER})
    assert result["failed"]
    assert calls == []


@run_async
async def test_inspection_limit_returns_review(monkeypatch):
    fake_reads(monkeypatch, rows=[booking(id=str(i)) for i in range(3)])
    monkeypatch.setattr(br, "MAX_BOOKINGS", 2)
    result = await br.handle_rehearse_booking_plan(None, {"id": BID, "owner_id": OWNER}, plan("2030-01-07T14:00:00Z").model_dump(mode="json"))
    assert result["status"] == "needs_review"


@run_async
async def test_chief_tool_path_returns_complete_evidence_without_model_calls(monkeypatch):
    import chief_of_staff as cos
    import chief_tool_loop as loop
    import llm_call
    import mcp_server
    fake_reads(monkeypatch)
    async def forbidden(*args, **kwargs):
        pytest.fail("rehearsal must not call a model")
    monkeypatch.setattr(llm_call, "apost", forbidden)
    assert cos.ACTION_HANDLERS[br.VERB] is br.handle_rehearse_booking_plan
    assert br.VERB in {t["name"] for t in mcp_server.tool_definitions()}
    assert br.VERB in {t["name"] for t in loop.read_tool_definitions()}
    error, text = await loop.execute_tool_use(None, {"id": BID, "owner_id": OWNER}, br.VERB,
        plan(*(["2030-01-07T14:00:00Z"] * 8)).model_dump(mode="json"))
    result = json.loads(text)
    assert not error
    assert not result.get("truncated")
    assert len(result["appointments"]) == 8
    assert result["dependencies"]


def test_result_fits_existing_tool_budget():
    import chief_tool_loop as loop
    result = check(plan(*(["2030-01-07T14:00:00Z"] * 8)), bookings=[booking()])
    assert len(json.dumps(result)) < loop.MAX_RESULT_CHARS


def test_outside_calendar_blocks_override_shared_capacity_and_change_fingerprint():
    busy = [{"business_id": BID, "starts_at": "2030-01-07T14:00:00Z", "ends_at": "2030-01-07T15:00:00Z"}]
    result = check(availability={**HOURS, "concurrent_capacity": 3}, busy=busy)
    assert result["status"] == "conflicts"
    assert result["dependencies"]["outside_calendar"] != check()["dependencies"]["outside_calendar"]
    assert all(datetime.fromisoformat(a["start_utc"]).hour >= 15 for a in result["appointments"][0]["alternatives"])


@pytest.mark.parametrize("busy", [
    [{"business_id": OTHER, "starts_at": "2030-01-07T14:00:00Z", "ends_at": "2030-01-07T15:00:00Z"}],
    [{"business_id": BID, "starts_at": "2030-01-07T14:00:00Z", "ends_at": "2030-01-07T13:00:00Z"}],
])
def test_unverified_outside_calendar_never_means_free(busy):
    with pytest.raises(br.RehearsalUnavailable):
        check(busy=busy)


@run_async
async def test_owner_change_blocks_server_owned_calendar_read(monkeypatch):
    calls = fake_reads(monkeypatch, override=lambda path, rows:
                       [{**rows[0], "owner_id": OTHER}] if path == "/businesses" else rows)
    result = await br.handle_rehearse_booking_plan(None, {"id": BID, "owner_id": OWNER},
                                                 plan("2030-01-07T14:00:00Z").model_dump(mode="json"))
    assert result["failed"]
    assert len(calls) == 1 and calls[0][1].startswith("/businesses?")


@run_async
async def test_timeout_cancels_read_without_returning_partial_availability(monkeypatch):
    import asyncio
    finished = []
    async def slow(*args):
        try:
            await asyncio.sleep(10)
        finally:
            finished.append(True)
    monkeypatch.setattr(br, "_sb", slow)
    monkeypatch.setattr(br, "CHECK_BUDGET_S", 0.01)
    result = await br.handle_rehearse_booking_plan(None, {"id": BID, "owner_id": OWNER},
                                                 plan("2030-01-07T14:00:00Z").model_dump(mode="json"))
    assert result["status"] == "needs_review" and result["failed"]
    assert finished == [True] and "appointments" not in result


@run_async
async def test_live_schema_and_credential_selection_with_http_transport(monkeypatch):
    import httpx
    import sb_clients
    monkeypatch.setenv("SUPABASE_URL", "https://database.example")
    monkeypatch.setenv("SUPABASE_ANON", "fixture-anon")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "fixture-service")
    calls = []
    tables = {"businesses": [{"id": BID, "owner_id": OWNER, "settings": {"availability": HOURS}}],
              "offerings": [SERVICE], "module_entries": [], "calendar_busy_blocks": [
                  {"id": "busy", "business_id": BID, "starts_at": "2030-01-07T14:00:00Z", "ends_at": "2030-01-07T15:00:00Z"}]}
    def respond(request):
        assert request.method == "GET" and not request.content
        table = request.url.path.rsplit("/", 1)[-1]
        calls.append(table)
        assert request.headers["authorization"] == ("Bearer fixture-service" if table == "calendar_busy_blocks" else "Bearer fixture-user")
        query = request.url.params
        assert query["id" if table == "businesses" else "business_id"] == "eq." + BID
        if table == "module_entries":
            assert query["select"] == "id,business_id,status,appointment_at,duration_min_at_booking"
        if table == "calendar_busy_blocks":
            assert query["select"] == "id,business_id,starts_at,ends_at"
            assert datetime.fromisoformat(query["starts_at"][3:]) > datetime.fromisoformat(query["ends_at"][3:])
        offset = int(query.get("offset", "0"))
        return httpx.Response(200, json=tables[table][offset:offset+100])
    with sb_clients.with_user_jwt("fixture-user"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            result = await br.handle_rehearse_booking_plan(client, {"id": BID, "owner_id": OWNER},
                plan("2030-01-07T14:00:00Z").model_dump(mode="json"))
    assert result["status"] == "conflicts"
    assert calls.count("calendar_busy_blocks") == 2


@run_async
async def test_repeated_rehearsal_refreshes_changed_state_in_same_turn(monkeypatch):
    import chief_tool_loop as loop
    calls = fake_reads(monkeypatch)
    args = plan("2030-01-07T14:00:00Z").model_dump(mode="json")
    error, first = await loop.execute_tool_use(None, {"id": BID, "owner_id": OWNER}, br.VERB, args)
    assert not error and json.loads(first)["status"] == "fits"
    changed_calls = fake_reads(monkeypatch, rows=[booking()])
    error, second = await loop.execute_tool_use(None, {"id": BID, "owner_id": OWNER}, br.VERB, args)
    assert not error and json.loads(second)["status"] == "conflicts"
    assert calls and changed_calls
    assert json.loads(first)["dependencies"]["bookings"] != json.loads(second)["dependencies"]["bookings"]


def test_randomized_plans_never_claim_over_capacity():
    """Independent minute-interval oracle; 200 calendars, 1,600 proposals."""
    import random
    from datetime import timedelta
    rng = random.Random(20261001)
    opening = NOW.replace(hour=14)
    for _ in range(200):
        capacity = rng.randint(1, 4)
        duration = rng.choice([30, 60, 90])
        existing = [(rng.randrange(16) * 30, rng.choice([30, 60, 90])) for _ in range(rng.randrange(10))]
        starts = [rng.randrange(-2, 19) * 30 for _ in range(8)]
        rows = [booking((opening + timedelta(minutes=s)).isoformat(), d, str(i))
                for i, (s, d) in enumerate(existing)]
        result = check(plan(*[(opening + timedelta(minutes=s)).isoformat() for s in starts]),
                       availability={**HOURS, "concurrent_capacity": capacity},
                       offerings=[{**SERVICE, "duration_min": duration}], bookings=rows)
        occupied = list(existing)
        def valid(start):
            if start < 0 or start + duration > 480:
                return False
            return all(sum(s <= minute < s + d for s, d in occupied) < capacity
                       for minute in range(start, start + duration))
        for start, item in zip(starts, result["appointments"]):
            if item["status"] == "fits":
                assert valid(start), (occupied, start, duration, capacity)
                occupied.append((start, duration))
            elif capacity == 1:
                assert not valid(start), "Single-capacity results should match the independent oracle exactly"
            for alternative in item.get("alternatives", []):
                alt_start = int((datetime.fromisoformat(alternative["start_utc"]) - opening).total_seconds() / 60)
                assert valid(alt_start)


@run_async
@pytest.mark.parametrize("policy_allowed,read_failed", [(True, False), (False, False), (True, True)])
async def test_mcp_dispatch_honors_policy_and_records_actual_outcome(monkeypatch, policy_allowed, read_failed):
    from types import SimpleNamespace
    import mcp_server as mcp
    import policy_engine
    calls = fake_reads(monkeypatch, override=lambda path, result: None if read_failed else result)
    async def resolve(client, caller):
        return {"id": BID, "owner_id": OWNER, "settings": {}}
    monkeypatch.setattr(mcp, "_resolve_business", resolve)
    monkeypatch.setattr(mcp, "_tier_allows", lambda biz: True)
    monkeypatch.setattr(policy_engine, "evaluate", lambda *a, **k: SimpleNamespace(allowed=policy_allowed, reason="test-policy"))
    ledger = []
    monkeypatch.setattr(mcp, "_ledger", lambda *a, **k: ledger.append(k))
    caller = mcp.Caller("token", "test-token", business_id=BID, scopes=["read"])
    allowed, ok, result, business = await mcp._call_tool(br.VERB,
        plan("2030-01-07T14:00:00Z").model_dump(mode="json"), caller)
    assert business == BID
    assert allowed is policy_allowed
    assert ok is (policy_allowed and not read_failed)
    assert ledger[-1]["ok"] is ok
    if not policy_allowed:
        assert calls == []
    elif read_failed:
        assert result["status"] == "needs_review"
    else:
        assert result["status"] == "fits"


@run_async
@pytest.mark.parametrize("streaming", [False, True])
async def test_complete_model_tool_round_with_real_rehearsal(monkeypatch, streaming):
    """Scripted model, real Chief loop and capability; proves transport, not model judgment."""
    from contextlib import asynccontextmanager
    from __tests__.test_tool_loop import _FakeResp, _StreamResp, _sse_final, _final_response
    import chief_of_staff as cos
    import chief_tool_loop as loop
    import llm_call
    fake_reads(monkeypatch)
    payloads = []
    args = plan("2030-01-07T14:00:00Z", "2030-01-07T14:30:00Z").model_dump(mode="json")
    final = "The first appointment fits. The second overlaps it. Nothing has been booked."
    async def noop(*a, **k):
        pass
    monkeypatch.setattr(cos, "log_api_usage", noop)
    monkeypatch.setattr(cos, "_anthropic_key", lambda: "scripted-test-key")
    def inspect_payload(payload):
        payloads.append(deepcopy(payload))
        if len(payloads) == 2:
            content = payload["messages"][-1]["content"][0]
            assert content["type"] == "tool_result" and not content.get("is_error")
            evidence = json.loads(content["content"])
            assert [a["status"] for a in evidence["appointments"]] == ["fits", "conflict"]
    async def post(client, payload, **kwargs):
        inspect_payload(payload)
        if len(payloads) == 1:
            return _FakeResp({"stop_reason": "tool_use", "usage": {}, "content": [
                {"type": "tool_use", "id": "rehearsal-1", "name": br.VERB, "input": args}]})
        return _FakeResp(_final_response(final))
    @asynccontextmanager
    async def stream(client, payload, **kwargs):
        inspect_payload(payload)
        if len(payloads) == 1:
            argument_json = json.dumps(args)
            chunks = [argument_json[:57], argument_json[57:]]
            events = [
                {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
                {"type": "content_block_start", "index": 0, "content_block": {
                    "type": "tool_use", "id": "rehearsal-1", "name": br.VERB}},
                *[{"type": "content_block_delta", "index": 0, "delta": {
                    "type": "input_json_delta", "partial_json": chunk}} for chunk in chunks],
                {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 5}},
            ]
            yield _StreamResp(["data: " + json.dumps(event) for event in events])
        else:
            yield _StreamResp(_sse_final(final))
    monkeypatch.setattr(llm_call, "apost", post)
    monkeypatch.setattr(llm_call, "astream", stream)
    sunk = []
    out = await cos._call_claude(None, "SYSTEM", [{"role": "user", "content": "Check these two appointments without booking."}],
        enable_web_search=False, read_tools=loop.read_tool_definitions(), tool_biz={"id": BID, "owner_id": OWNER},
        stream_sink=sunk.append if streaming else None)
    assert out == final
    assert len(payloads) == 2
    assert loop.calls_this_turn() == 1
    assert loop.writes_this_turn() == []
    if streaming:
        assert "".join(sunk) == final
