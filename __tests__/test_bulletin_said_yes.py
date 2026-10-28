"""The bulletin texts only the people who said yes (Kevin, 2026-10-28).

/sms/broadcast (the Text screen's "All-points bulletin") used to text every
contact with a number and skip only STOP. At Love City that was 145 numbers,
about 30 of whom had ever said yes. Now it runs sms_alerts.said_yes_to_texts:
the consent rule for many on the shared number, the mixed rule (agreed under
the business's own name since it registered) on its own number, STOP always
winning, and nothing sent when that can't be checked.
"""
from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import pytest

import sms_alerts
import sms_routing

A, B, C, D = "+15550000001", "+15550000002", "+15550000003", "+15550000004"


def _db(monkeypatch, tables, own=None, fail=None):
    """A fake database: every read of a table returns its rows (the real
    filters live in the query string, which the tests read separately)."""
    seen = []

    async def sb_get(client, path):
        seen.append(path)
        table = path.split("?")[0].strip("/")
        if fail and table == fail:
            return None
        return [dict(r) for r in tables.get(table, [])]

    async def own_registration(client, business_id):
        return own

    monkeypatch.setattr(sms_alerts, "_sb_get", sb_get)
    monkeypatch.setattr(sms_alerts, "own_registration", own_registration)
    return seen


def _yes(phones):
    return asyncio.run(sms_alerts.said_yes_to_texts(None, "biz-1", phones))


def _tables(paths):
    return [p.split("?")[0].strip("/") for p in paths]


# ─── who said yes ────────────────────────────────────────────────────

def test_only_the_people_who_said_yes(monkeypatch):
    _db(monkeypatch, {"sms_consents": [{"phone": A}], "sms_bindings": [{"customer_phone": B}]})
    assert _yes([A, B, C]) == {A, B}


def test_stop_always_wins(monkeypatch):
    _db(monkeypatch, {"sms_consents": [{"phone": A}, {"phone": B}], "sms_opt_outs": [{"phone": B}]})
    assert _yes([A, B]) == {A}


def test_a_number_written_any_way_matches(monkeypatch):
    _db(monkeypatch, {"sms_consents": [{"phone": A}]})
    assert _yes(["(555) 000-0001", "555-000-0002"]) == {A}


def test_never_more_than_was_asked_about(monkeypatch):
    _db(monkeypatch, {"sms_consents": [{"phone": A}, {"phone": D}]})
    assert _yes([A]) == {A}


@pytest.mark.parametrize("table", ["sms_consents", "sms_bindings", "sms_opt_outs"])
def test_a_failed_read_sends_nothing(monkeypatch, table):
    _db(monkeypatch, {"sms_consents": [{"phone": A}]}, fail=table)
    assert _yes([A]) is None


def test_no_numbers_reads_nothing(monkeypatch):
    seen = _db(monkeypatch, {})
    assert _yes(["", None, "12"]) == set()
    assert seen == []


def test_the_shared_number_uses_the_consent_rule(monkeypatch):
    """The same filters has_sms_consent uses, one phone at a time."""
    seen = _db(monkeypatch, {})
    _yes([A])
    consents = next(p for p in seen if p.startswith("/sms_consents"))
    assert "or=(and(business_id.eq.biz-1,source.neq.booking_marketing),source.eq.web_form)" in consents
    assert "or=(and(business_id.eq.{business_id},source.neq.booking_marketing),source.eq.web_form)" \
        in inspect.getsource(sms_alerts._positive_consent)
    assert any(p.startswith("/sms_bindings") and "business_id=eq.biz-1" in p for p in seen)
    stops = next(p for p in seen if p.startswith("/sms_opt_outs"))
    assert "or=(business_id.is.null,business_id.eq.biz-1)" in stops


def test_a_plus_sign_is_encoded(monkeypatch):
    """A raw '+' in a query string reads as a space and matches nothing."""
    seen = _db(monkeypatch, {})
    _yes([A])
    assert all("%2B1555" in p and "+1555" not in p for p in seen)


def test_its_own_name_uses_the_mixed_rule(monkeypatch):
    """Agreed under its own name, or texted it, since it registered. An old
    keyword binding isn't enough (agreed_under_own_name, for many)."""
    since = "2026-10-11T00:00:00+00:00"
    seen = _db(monkeypatch, {"sms_consents": [{"phone": A}], "sms_messages": [{"phone_number": B}],
                             "sms_bindings": [{"customer_phone": C}]},
               own={"number": "+12165550000", "since": since})
    assert _yes([A, B, C]) == {A, B}
    assert "sms_bindings" not in _tables(seen)
    consents = next(p for p in seen if p.startswith("/sms_consents"))
    assert "business_id=eq.biz-1" in consents and "consented_at=gte.2026-10-11" in consents
    texted = next(p for p in seen if p.startswith("/sms_messages"))
    assert "direction=eq.inbound" in texted and "created_at=gte.2026-10-11" in texted


def test_long_lists_are_read_in_pieces(monkeypatch):
    seen = _db(monkeypatch, {})
    _yes([f"+1555{n:07d}" for n in range(250)])
    tables = _tables(seen)
    assert tables.count("sms_consents") == 3
    assert tables.count("sms_bindings") == 3
    assert tables.count("sms_opt_outs") == 3


# ─── the bulletin ────────────────────────────────────────────────────

def _broadcast(monkeypatch, contacts, yes):
    import billing_limits
    import business_access
    sent, events = [], []

    async def sb_get(client, path):
        assert path.startswith("/contacts?business_id=eq.biz-1")
        return contacts

    async def said_yes(client, business_id, phones):
        return yes

    async def biz_name(client, business_id):
        return "Love City Church"

    async def opted_out(client, phone, business_id=None):
        return False

    async def send(phone, body, *, business_id, client=None):
        sent.append((phone, body))
        return "SM1"

    async def store(client, **kw):
        return "row-1"

    async def log_event(client, business_id, contact_id, kind, data):
        events.append((kind, data))

    monkeypatch.setattr(business_access, "assert_access", lambda b, u, r: None)
    monkeypatch.setattr(billing_limits, "require_card", lambda b, k: None)
    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    monkeypatch.setattr(sms_alerts, "said_yes_to_texts", said_yes)
    monkeypatch.setattr(sms_routing, "_biz_name", biz_name)
    monkeypatch.setattr(sms_routing, "is_opted_out", opted_out)
    monkeypatch.setattr(sms_routing, "_send_platform_sms", send)
    monkeypatch.setattr(sms_routing, "_store_sms", store)
    monkeypatch.setattr(sms_routing, "_log_event", log_event)
    body = sms_routing.BroadcastBody(business_id="biz-1", message="Service moved to 10am.")
    out = asyncio.run(sms_routing.broadcast(body, user=SimpleNamespace(id="u1")))
    return out, sent, events


def test_the_bulletin_texts_only_the_yes(monkeypatch):
    contacts = [{"id": "1", "phone": A}, {"id": "2", "phone": B}, {"id": "3", "phone": C}]
    out, sent, events = _broadcast(monkeypatch, contacts, {A})
    assert [p for p, _ in sent] == [A]
    assert out["sent"] == 1 and out["not_yes"] == 2
    assert events[0][1]["not_yes"] == 2


def test_one_text_per_number(monkeypatch):
    contacts = [{"id": "1", "phone": A}, {"id": "2", "phone": "(555) 000-0001"}]
    out, sent, _ = _broadcast(monkeypatch, contacts, {A})
    assert len(sent) == 1 and out["skipped"] == 1


def test_nothing_goes_when_yes_cant_be_checked(monkeypatch):
    out, sent, events = _broadcast(monkeypatch, [{"id": "1", "phone": A}], None)
    assert sent == [] and events == []
    assert out.status_code == 503


def test_the_body_still_names_the_church_and_the_way_out(monkeypatch):
    _, sent, _ = _broadcast(monkeypatch, [{"id": "1", "phone": A}], {A})
    assert sent[0][1].startswith("Love City Church: ") and "STOP" in sent[0][1]


def test_the_reach_counts_numbers_not_rows(monkeypatch):
    import business_access

    async def sb_get(client, path):
        return [{"id": "1", "phone": A}, {"id": "2", "phone": "5550000001"}, {"id": "3", "phone": B},
                {"id": "4", "phone": "nope"}]

    async def said_yes(client, business_id, phones):
        return {A}

    monkeypatch.setattr(business_access, "assert_access", lambda b, u, r: None)
    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    monkeypatch.setattr(sms_alerts, "said_yes_to_texts", said_yes)
    out = asyncio.run(sms_routing.broadcast_reach("biz-1", user=SimpleNamespace(id="u1")))
    assert out == {"with_phone": 2, "said_yes": 1}
