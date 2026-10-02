# __tests__/test_sms_numbers_inbound.py
#
# Dedicated SMS numbers, phase B (2026-09-02): the To number IS the
# routing, and the business's own line is what it sends from.
#
#   1. A text to a business's own number routes straight to that
#      business — no keyword, no disambiguation, no reply.
#   2. STOP / START / HELP on an own number scope to that business
#      (sms_opt_outs.business_id), never platform-wide.
#   3. A To number nobody claims falls through to the shared path;
#      nothing is dropped.
#   4. sender_for prefers the own active line, else the platform number.
#   5. is_opted_out honors both the platform-wide row and the scoped one.
#   6. The webhook hands To to the router (source-pinned).

from __future__ import annotations

import asyncio
import inspect
import pathlib

import pytest

import sms_routing
import sms_service
import twilio_sms

BIZ_A = "aaaaaaaa-0000-0000-0000-000000000001"
OWN_A = "+15557770001"
PLATFORM = "+15550000000"
CUSTOMER = "+15559998888"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def routed(monkeypatch):
    """A router whose DB is in memory: BIZ_A owns OWN_A; nothing else
    is bound or claimed. Records every side effect."""
    calls = {"bind": [], "contact": [], "inbound": [], "post": [], "keyword": [], "bindings": []}

    async def business_for_number(client, to):
        return {"business_id": BIZ_A, "status": "active"} if to == OWN_A else None

    async def _bind(client, phone, business_id):
        calls["bind"].append((phone, business_id))

    async def _ensure_contact(client, business_id, phone):
        calls["contact"].append((business_id, phone))

    async def record_inbound_sms(client, **kw):
        calls["inbound"].append(kw)
        return {"id": "m1"}

    async def _sb_post(client, path, body):
        calls["post"].append((path, body))
        return [body]

    async def _biz_name(client, business_id):
        return "Glow Studio"

    async def _keyword_lookup(client, word):
        calls["keyword"].append(word)
        return None

    async def _bindings_for(client, phone):
        calls["bindings"].append(phone)
        return []

    for name, fn in {
        "business_for_number": business_for_number, "_bind": _bind,
        "_ensure_contact": _ensure_contact, "record_inbound_sms": record_inbound_sms,
        "_sb_post": _sb_post, "_biz_name": _biz_name,
        "_keyword_lookup": _keyword_lookup, "_bindings_for": _bindings_for,
    }.items():
        monkeypatch.setattr(sms_routing, name, fn)
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", PLATFORM)
    return calls


# ─── 1. own number → direct ───────────────────────────────────────────

def test_text_to_own_number_routes_direct(routed):
    res = _run(sms_routing.route_inbound(
        from_number=CUSTOMER, text="hey are you open saturday", to_number=OWN_A))
    assert res == {"action": "routed_direct", "business_id": BIZ_A, "reply": None}
    assert routed["inbound"][0]["business_id"] == BIZ_A
    assert routed["inbound"][0]["text"] == "hey are you open saturday"
    # Bound + contact ensured, so the shared number finds them later too.
    assert routed["bind"] == [(CUSTOMER, BIZ_A)]
    assert routed["contact"] == [(BIZ_A, CUSTOMER)]
    # The keyword/binding machinery never ran.
    assert routed["keyword"] == [] and routed["bindings"] == []


def test_a_keyword_shaped_first_word_still_routes_direct(routed):
    """'GLOW hi' to an own number is a message, not a keyword claim."""
    res = _run(sms_routing.route_inbound(
        from_number=CUSTOMER, text="GLOW hi", to_number=OWN_A))
    assert res["action"] == "routed_direct"
    assert routed["keyword"] == []


# ─── 2. consent words scope to the business ───────────────────────────

def test_stop_on_own_number_is_scoped(routed):
    res = _run(sms_routing.route_inbound(
        from_number=CUSTOMER, text="STOP", to_number=OWN_A))
    assert res["action"] == "opt_out" and res["business_id"] == BIZ_A
    path, body = routed["post"][0]
    assert path.startswith("/sms_opt_outs")
    assert body == {"phone": CUSTOMER, "business_id": BIZ_A}   # NOT null
    assert routed["inbound"] == []


def test_help_on_own_number_names_the_business(routed):
    res = _run(sms_routing.route_inbound(
        from_number=CUSTOMER, text="HELP", to_number=OWN_A))
    assert res["action"] == "help" and res["business_id"] == BIZ_A
    assert "Glow Studio" in res["reply"]
    assert res["reply"].startswith(sms_routing.sender_brand())   # Direct model: platform is the sender
    assert "STOP" in res["reply"]


# ─── 3. unknown To falls through ──────────────────────────────────────

def test_unclaimed_to_number_falls_through_to_shared_path(routed, caplog):
    with caplog.at_level("WARNING", logger="sms_routing"):
        res = _run(sms_routing.route_inbound(
            from_number=CUSTOMER, text="hello", to_number="+15557779999"))
    # Shared path ran: keyword looked up, bindings checked, prompt returned.
    assert res["action"] == "prompt_keyword"
    assert routed["keyword"] == ["HELLO"]
    assert routed["bindings"] == [CUSTOMER]
    assert any("unknown To" in r.message for r in caplog.records)


def test_platform_number_takes_the_shared_path_quietly(routed, caplog):
    with caplog.at_level("WARNING", logger="sms_routing"):
        res = _run(sms_routing.route_inbound(
            from_number=CUSTOMER, text="hello", to_number=PLATFORM))
    assert res["action"] == "prompt_keyword"
    assert not any("unknown To" in r.message for r in caplog.records)


def test_no_to_number_is_the_old_path_exactly(routed):
    """Callers that predate To (tests, tools) see no change."""
    res = _run(sms_routing.route_inbound(from_number=CUSTOMER, text="hello"))
    assert res["action"] == "prompt_keyword"


# ─── 4. sender_for prefers the own line ───────────────────────────────

def test_sender_for_prefers_own_active_number(monkeypatch):
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", PLATFORM)

    async def active_number_for(client, business_id):
        return OWN_A if business_id == BIZ_A else None

    monkeypatch.setattr(sms_service, "active_number_for", active_number_for)
    assert _run(sms_service.sender_for(None, BIZ_A)) == OWN_A
    assert _run(sms_service.sender_for(None, "someone-else")) == PLATFORM
    assert _run(sms_service.sender_for(None, None)) == PLATFORM


def test_sender_for_degrades_to_platform_on_db_blip(monkeypatch):
    monkeypatch.setenv("TWILIO_PLATFORM_NUMBER", PLATFORM)

    async def _sb_get(client, path):
        return None   # what _sb_get returns on any 4xx/5xx or network error

    monkeypatch.setattr(sms_service, "_sb_get", _sb_get)
    assert _run(sms_service.sender_for(None, BIZ_A)) == PLATFORM


# ─── 5. is_opted_out honors the scoped row ────────────────────────────

def test_is_opted_out_query_scopes_to_business(monkeypatch):
    seen = []

    async def _sb_get(client, path):
        seen.append(path)
        return []

    monkeypatch.setattr(sms_service, "_sb_get", _sb_get)
    _run(sms_service.is_opted_out(None, CUSTOMER))
    _run(sms_service.is_opted_out(None, CUSTOMER, BIZ_A))
    assert "business_id=is.null" in seen[0] and "or=(" not in seen[0]
    assert f"or=(business_id.is.null,business_id.eq.{BIZ_A})" in seen[1]


@pytest.mark.parametrize("module, fn", [
    (sms_service, "send_sms_core"),
    (sms_routing, "broadcast"),
])
def test_outbound_gates_pass_the_business_to_is_opted_out(module, fn):
    src = inspect.getsource(getattr(module, fn))
    assert "is_opted_out(client, " in src
    line = next(l for l in src.splitlines() if "is_opted_out(client, " in l)
    assert line.rstrip(":").rstrip(")").count(",") >= 2, (
        f"{module.__name__}.{fn} checks opt-out without the business — a "
        f"STOP texted to the business's own number would not be honored:\n  {line.strip()}")


# ─── 6. the webhook hands To to the router ────────────────────────────

def test_webhook_passes_to_number():
    src = inspect.getsource(twilio_sms.twilio_inbound_sms)
    assert 'to_number=params.get("To"' in src


def test_migration_is_filed_and_in_the_ledger():
    root = pathlib.Path(__file__).resolve().parent.parent
    sql = (root / "supabase" / "APPLY-2026-09-02-sms-numbers.sql").read_text(encoding="utf-8")
    assert "create table if not exists public.sms_numbers" in sql
    assert "sms_numbers_one_live_per_business" in sql
    ledger = (root / "docs" / "MIGRATIONS.md").read_text(encoding="utf-8")
    assert "APPLY-2026-09-02-sms-numbers.sql" in ledger
