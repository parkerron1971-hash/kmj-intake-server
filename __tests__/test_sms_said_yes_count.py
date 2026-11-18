"""How many people get a church's texts, and how many signed up this week
(sms_routing.said_yes_count; sms_alerts.said_yes_to_texts's `before`).

Kevin, 2026-11-17, approving it for the Office & Leadership admin: "check
how many people have signed up for texts each week". My week's weekly text
job says the count; this is where it comes from.

Pins:
  * the count is the whole-list announcement's own reach: the church's
    numbers that said yes (one a number), never the people with a phone
  * "this week" is who says yes now and had no yes before Monday: a
    consent, a keyword texted (a binding), or on its own registration a
    consent or a text in since it registered, each read before `before`
  * a read that fails is None (the count) or new None (the week), never a
    number
"""
from __future__ import annotations

import asyncio

import sms_alerts
import sms_routing

A, B, C, D = "+15550000001", "+15550000002", "+15550000003", "+15550000004"
MONDAY = "2026-11-16T05:00:00+00:00"


def _paths(monkeypatch, own=None):
    seen = []

    async def sb_get(client, path):
        seen.append(path)
        return []

    async def own_registration(client, business_id):
        return own

    monkeypatch.setattr(sms_alerts, "_sb_get", sb_get)
    monkeypatch.setattr(sms_alerts, "own_registration", own_registration)
    return seen


def test_before_reads_only_the_yeses_given_before_it(monkeypatch):
    seen = _paths(monkeypatch)
    asyncio.run(sms_alerts.said_yes_to_texts(None, "biz-1", [A], before=MONDAY))
    consents = next(p for p in seen if p.startswith("/sms_consents"))
    bindings = next(p for p in seen if p.startswith("/sms_bindings"))
    stops = next(p for p in seen if p.startswith("/sms_opt_outs"))
    assert "consented_at=lt.2026-11-16T05%3A00%3A00%2B00%3A00" in consents
    assert "bound_at=lt.2026-11-16T05%3A00%3A00%2B00%3A00" in bindings
    # STOP is as it stands now: someone who stopped isn't counted either way.
    assert "lt." not in stops
    # Without it, nothing changes.
    seen.clear()
    asyncio.run(sms_alerts.said_yes_to_texts(None, "biz-1", [A]))
    assert not any("=lt." in p for p in seen)


def test_on_its_own_registration_before_sits_inside_since(monkeypatch):
    seen = _paths(monkeypatch, own={"number": "+12165550000", "since": "2026-11-01T00:00:00+00:00"})
    asyncio.run(sms_alerts.said_yes_to_texts(None, "biz-1", [A], before=MONDAY))
    consents = next(p for p in seen if p.startswith("/sms_consents"))
    texted = next(p for p in seen if p.startswith("/sms_messages"))
    assert "consented_at=gte.2026-11-01" in consents and "consented_at=lt.2026-11-16" in consents
    assert "created_at=gte.2026-11-01" in texted and "created_at=lt.2026-11-16" in texted


def _world(monkeypatch, contacts, yes_now, yes_before, fail=None):
    asked = []

    async def sb_get(client, path):
        assert path.startswith("/contacts?business_id=eq.biz-1&phone=not.is.null")
        return None if fail == "contacts" else [dict(c) for c in contacts if c["id"] > (path.split("&id=gt.")[1] if "&id=gt." in path else "")]

    async def said_yes(client, business_id, phones, before=None):
        asked.append((sorted(phones), before))
        if before:
            return None if fail == "before" else {p for p in phones if p in yes_before}
        return {p for p in phones if p in yes_now}

    monkeypatch.setattr(sms_routing, "_sb_get", sb_get)
    monkeypatch.setattr(sms_alerts, "said_yes_to_texts", said_yes)
    return asked


BOOK = [{"id": "1", "phone": A}, {"id": "2", "phone": "(555) 000-0001"}, {"id": "3", "phone": B},
        {"id": "4", "phone": C}, {"id": "5", "phone": D}, {"id": "6", "phone": "nope"}]


def test_the_count_is_the_numbers_that_said_yes_and_who_joined_this_week(monkeypatch):
    asked = _world(monkeypatch, BOOK, yes_now={A, B, C}, yes_before={A})
    got = asyncio.run(sms_routing.said_yes_count("biz-1", MONDAY))
    assert got == {"said_yes": 3, "new": 2}
    # The week's read asks only about the numbers that say yes now.
    assert asked[-1] == ([A, B, C], MONDAY)


def test_without_a_week_it_counts_only(monkeypatch):
    asked = _world(monkeypatch, BOOK, yes_now={A}, yes_before=set())
    assert asyncio.run(sms_routing.said_yes_count("biz-1")) == {"said_yes": 1, "new": None}
    assert len(asked) == 1


def test_nobody_yet_is_zero_and_zero_new(monkeypatch):
    _world(monkeypatch, BOOK, yes_now=set(), yes_before=set())
    assert asyncio.run(sms_routing.said_yes_count("biz-1", MONDAY)) == {"said_yes": 0, "new": 0}


def test_a_failed_read_is_never_a_number(monkeypatch):
    _world(monkeypatch, BOOK, yes_now={A}, yes_before=set(), fail="contacts")
    assert asyncio.run(sms_routing.said_yes_count("biz-1", MONDAY)) is None
    _world(monkeypatch, BOOK, yes_now={A, B}, yes_before=set(), fail="before")
    assert asyncio.run(sms_routing.said_yes_count("biz-1", MONDAY)) == {"said_yes": 2, "new": None}
