# __tests__/test_sms_reply_threads.py
#
# Replies on the shared number (2026-10-11, Kevin: "we need to make sure
# that is good"). A business that texted someone from the shared number
# (a confirmation, a reminder, a note) never made a binding, so the reply
# ("running 10 min late") was told to text a keyword. Now:
#
#   1. Someone one business has been texting with lately: the reply goes
#      there, with no keyword and no binding made.
#   2. Bound to one business, but another texted them today: the active
#      conversation wins.
#   3. Several businesses and no recent conversation: they choose ("Reply 1
#      for ..."), bound ones first; the choice for a business they were
#      only texting with is kept in that thread, never as a binding.
#   4. Nobody, or the thread read failing: the keyword prompt, as before.
#   5. A thread is never consent: nothing here writes sms_bindings for it.

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

import sms_routing

A = "aaaaaaaa-0000-0000-0000-000000000001"
B = "bbbbbbbb-0000-0000-0000-000000000002"
C = "cccccccc-0000-0000-0000-000000000003"
CUSTOMER = "+15559998888"
NAMES = {A: "Glow Studio", B: "Northside Cuts", C: "Grace Harbor"}


def _run(coro):
    return asyncio.run(coro)


def ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


@pytest.fixture
def world(monkeypatch):
    w = {"bindings": [], "threads": {}, "bind": [], "touch": [], "inbound": [], "stored": [], "posts": []}

    async def _bindings_for(client, phone):
        return list(w["bindings"])

    async def _recent_threads(client, phone):
        if w["threads"] == "fail":
            return {}
        return dict(w["threads"])

    async def _bind(client, phone, business_id):
        w["bind"].append(business_id)

    async def _touch_binding(client, phone, business_id):
        w["touch"].append(business_id)

    async def record_inbound_sms(client, **kw):
        w["inbound"].append(kw)
        return {"id": "m1"}

    async def _store_sms(client, business_id, contact_id, phone, message, direction, **kw):
        w["stored"].append((business_id, direction, message, kw.get("sent_by")))
        return "s1"

    async def _sb_post(client, path, body):
        w["posts"].append(path)
        return [body]

    async def _biz_name(client, business_id):
        return NAMES[business_id]

    async def _keyword_lookup(client, word):
        return None

    async def business_for_number(client, to):
        return None

    for name, fn in {"_bindings_for": _bindings_for, "_recent_threads": _recent_threads, "_bind": _bind,
                     "_touch_binding": _touch_binding, "record_inbound_sms": record_inbound_sms,
                     "_store_sms": _store_sms, "_sb_post": _sb_post, "_biz_name": _biz_name,
                     "_keyword_lookup": _keyword_lookup, "business_for_number": business_for_number}.items():
        monkeypatch.setattr(sms_routing, name, fn)
    return w


def reply(text="running 10 min late"):
    return _run(sms_routing.route_inbound(from_number=CUSTOMER, text=text))


def no_consent_written(w):
    assert w["bind"] == [] and not any("sms_bindings" in p for p in w["posts"])


def test_a_reply_reaches_the_business_that_texted_them(world):
    world["threads"] = {A: ago(30)}                                 # yesterday's reminder
    res = reply()
    assert res == {"action": "routed", "business_id": A, "reply": None}
    assert world["inbound"][0]["business_id"] == A and world["touch"] == []
    no_consent_written(world)


def test_the_active_conversation_wins_over_an_old_binding(world):
    world["bindings"] = [{"business_id": A, "bound_at": ago(2000), "last_routed_at": ago(2000)}]
    world["threads"] = {B: ago(3)}                                  # Northside texted them this morning
    assert reply()["business_id"] == B
    world["threads"] = {A: ago(1), B: ago(5)}                       # the bound one, most recent
    assert reply()["business_id"] == A and world["touch"] == [A]
    no_consent_written(world)


def test_several_and_nothing_recent_they_choose_and_the_choice_sticks_in_the_thread(world):
    world["bindings"] = [{"business_id": C, "bound_at": ago(5000), "last_routed_at": ago(5000)}]
    world["threads"] = {B: ago(300), A: ago(400)}
    res = reply()
    assert res["action"] == "disambiguate"
    assert res["reply"].endswith("Reply 1 for Grace Harbor, 2 for Glow Studio, 3 for Northside Cuts.")   # bound first, then by id
    res = reply("3")
    assert res["action"] == "selected" and res["business_id"] == B
    assert world["stored"] == [(B, "outbound", res["reply"], "system")] and world["touch"] == []
    res = reply("1")
    assert res["business_id"] == C and world["touch"] == [C]       # a bound one is refreshed as before
    assert reply("9")["action"] == "disambiguate"
    no_consent_written(world)


def test_nobody_or_an_unreadable_history_asks_for_the_keyword(world):
    assert reply()["action"] == "prompt_keyword"
    world["threads"] = "fail"
    assert reply()["action"] == "prompt_keyword"
    assert world["inbound"] == []


def test_stop_still_comes_first(world):
    world["threads"] = {A: ago(1)}
    res = reply("STOP")
    assert res["action"] == "opt_out" and world["inbound"] == []


def test_the_thread_read_is_this_phone_recent_and_named_businesses(monkeypatch):
    paths = []

    async def _sb_get(client, path):
        paths.append(path)
        return [{"business_id": B, "created_at": "2026-10-10T12:00:00+00:00"},
                {"business_id": B, "created_at": "2026-10-09T12:00:00+00:00"},
                {"business_id": A, "created_at": "2026-10-08T12:00:00+00:00"}]

    monkeypatch.setattr(sms_routing, "_sb_get", _sb_get)
    got = _run(sms_routing._recent_threads(None, CUSTOMER))
    assert got == {B: "2026-10-10T12:00:00+00:00", A: "2026-10-08T12:00:00+00:00"}
    assert paths[0].startswith("/sms_messages?phone_number=eq.%2B15559998888&business_id=not.is.null&created_at=gte.")
    assert "order=created_at.desc" in paths[0]


def test_threads_never_become_bindings():
    """has_sms_consent counts sms_bindings; the thread path must not write one."""
    import inspect
    src = inspect.getsource(sms_routing._recent_threads) + inspect.getsource(sms_routing._candidates)
    assert "sms_bindings" not in src and "_bind(" not in src
