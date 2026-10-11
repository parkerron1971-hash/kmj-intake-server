"""Chief makes offers and runs refer-a-friend (2026-10-11, chief_offer_actions).

Kevin, 2026-10-11: "continue to build the next steps that you just shared"
(a way for Chief to make an offer or switch on refer-a-friend). Pinned here:
  1. The owner only, asking in chat: no turn, a member, or an unattended run
     changes nothing.
  2. Through the Offers page's own functions, with their checks; their
     refusals come back in their own words with what didn't happen.
  3. Class C tags, never native write tools; schedule_action won't wrap them;
     a spoken hold names what it gives.
  4. The prompt teaches the tags and the rules; result and label, always.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import action_registry  # noqa: E402
import chief_of_staff as cos  # noqa: E402
import chief_offer_actions as coa  # noqa: E402
import mcp_server  # noqa: E402

BIZ = "0a1b2c3d-4e5f-4a6b-8c7d-8e9f0a1b2c3d"
OWNER = "u0000000-0000-4000-8000-000000000001"
BIZ_ROW = {"id": BIZ, "name": "Northside Cuts", "owner_id": OWNER, "settings": {}}
VERBS = ("make_offer", "change_offer", "set_refer_a_friend")
LINK = "https://northside.mysolutionist.app/go/a1b2c3"


def run(x):
    return asyncio.run(x)


@pytest.fixture
def world(monkeypatch):
    import business_marketing as bm
    import offers
    import refer_a_friend as rf
    w = {"user": OWNER, "made": [], "changed": [], "referral": [], "fail": None, "offers": {}}

    def owner_row(bid, uid):
        if uid != OWNER:
            raise HTTPException(403, "Only the owner.")
        return {"id": bid, "owner_id": OWNER}

    async def create_offer(business_id, body, biz):
        if w["fail"]:
            raise w["fail"]
        w["made"].append(body)
        code = body.code or "FIRST10"
        return {"ok": True, "payments_ready": True, "offers": [
            {"id": "o1", "code": code, "title": "$10 off your first visit", "who": body.who,
             "when": offers.when_words(body.model_dump(mode="json")), "one_per_person": body.one_per_person,
             "max_uses": body.max_uses, "link": LINK}]}

    async def change_offer(business_id, offer_id, body, biz):
        if w["fail"]:
            raise w["fail"]
        w["changed"].append((offer_id, body.model_dump(exclude_unset=True)))
        return {"ok": True, "offers": []}

    async def set_referral(business_id, body, biz):
        if w["fail"]:
            raise w["fail"]
        w["referral"].append(body)
        return {"ok": True, "referral": {"on": body.on, "friend_cents": body.friend_cents or 1000,
                                         "reward_cents": body.reward_cents or 1000, "in_notes": True,
                                         "rebook_on": True, "thanks_days": body.thanks_days or None}}

    monkeypatch.setattr(bm, "_owner_row", owner_row)
    monkeypatch.setattr(offers, "create_offer", create_offer)
    monkeypatch.setattr(offers, "change_offer", change_offer)
    monkeypatch.setattr(offers, "find", lambda bid, code: w["offers"].get(str(code).upper()))
    monkeypatch.setattr(rf, "set_referral", set_referral)
    token = cos._TURN_USER_ID.set(OWNER)
    yield w
    cos._TURN_USER_ID.reset(token)


def act(verb, **kw):
    return run(cos.ACTION_HANDLERS[verb](None, BIZ_ROW, {"type": verb, **kw}))


# ─── 1. who ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("verb", VERBS)
def test_the_owner_only_asking_in_chat(world, verb):
    token = cos._TURN_USER_ID.set("")
    try:
        out = act(verb, amount=10, on=True, code="FIRST10", status="paused")
        assert out["failed"] is True and "when the business owner asks me in chat" in out["result"]
    finally:
        cos._TURN_USER_ID.reset(token)
    token = cos._TURN_USER_ID.set("someone-else")
    try:
        out = act(verb, amount=10, on=True, code="FIRST10", status="paused")
        assert out["failed"] is True and out["result"].startswith("Only the business owner")
    finally:
        cos._TURN_USER_ID.reset(token)
    out = act(verb, amount=10, on=True, code="FIRST10", status="paused", _unattended=True)
    assert out["failed"] is True and "never on a scheduled or automatic run" in out["result"]
    assert world["made"] == world["changed"] == world["referral"] == []


# ─── 2. through the page's own functions ─────────────────────────────

def test_make_offer_says_what_it_made_and_the_link(world):
    out = act("make_offer", amount=10, who="first_visit", ends_on="2026-11-01")
    [body] = world["made"]
    assert body.kind == "amount_off" and body.amount_cents == 1000 and body.who == "first_visit"
    assert body.one_per_person is True and str(body.ends_on) == "2026-11-01"
    assert out["ok"] is True and out["code"] == "FIRST10" and out["link"] == LINK
    assert out["result"] == (f"Made FIRST10: $10 off your first visit (through Sun, Nov 1), once per person. Its link: "
                             f"{LINK}. Nothing goes out until you share it: copy the link, post it, or print its "
                             "counter card in Grow, Offers.")
    assert out["label"] == "Offer FIRST10 made" and out["nav"] == {"tab": "grow", "sub": "offers"}


def test_make_offer_reads_percent_free_items_and_slow_hours(world):
    act("make_offer", percent=15, who="regulars", days=["Tue", "wed", "THURSDAY"], start="14:00", end="17:00",
        code="slow15", one_per_person="false", max_uses=30)
    body = world["made"][-1]
    assert body.kind == "percent_off" and body.percent == 15 and body.code == "SLOW15"
    out = act("make_offer", percent=15, who="regulars", code="back15")
    assert out["result"].startswith("Made BACK15: $10 off your first visit, for regulars, any time, once per person.")
    assert body.hours.days == [2, 3, 4] and body.hours.start == "14:00" and body.one_per_person is False
    assert body.max_uses == 30
    act("make_offer", free_item="Beard line-up")
    assert world["made"][-1].kind == "free_item" and world["made"][-1].free_item == "Beard line-up"


def test_make_offer_refusals_in_plain_words(world):
    out = act("make_offer", who="anyone")
    assert out["failed"] and out["result"].startswith("Tell me what it gives")
    out = act("make_offer", amount="ten")
    assert out["failed"] and "as a number of dollars" in out["result"]
    out = act("make_offer", amount=10, days=["someday"], start="14:00", end="17:00")
    assert out["failed"] and "I didn't understand the day 'someday'" in out["result"]
    out = act("make_offer", amount=10, days=["tue"], start="17:00", end="14:00")
    assert out["failed"] and out["result"] == ("Choose a start time before the end time, like 14:00 to 17:00. "
                                               "Nothing was made.")
    world["fail"] = HTTPException(409, "Connect card payments in Payments first, so an offer can be taken off at booking.")
    out = act("make_offer", amount=10)
    assert out["failed"] and out["result"].startswith("Connect card payments in Payments first")
    assert out["result"].endswith("Nothing was made.") and out["label"] == "Offer not made"
    world["fail"] = HTTPException(503, "That offer didn't save. Nothing was made. Try again in a minute.")
    out = act("make_offer", amount=10)
    assert out["result"] == "That offer didn't save. Nothing was made. Try again in a minute."   # said once
    assert world["made"] == []


def test_change_offer_by_its_code(world):
    world["offers"] = {"FIRST10": {"id": "o1", "code": "FIRST10", "source": "owner"},
                       "REFER-A-FRIEND": {"id": "p1", "code": "REFER-A-FRIEND", "source": "referral"}}
    out = act("change_offer", code="first10", status="paused")
    assert world["changed"] == [("o1", {"status": "paused"})]
    assert out["result"] == "Paused FIRST10. Its link still opens your booking page, without the offer."
    out = act("change_offer", code="FIRST10", status="on", ends_on="2026-11-01")
    assert world["changed"][-1] == ("o1", {"status": "on", "ends_on": __import__("datetime").date(2026, 11, 1)})
    assert out["result"] == "FIRST10 is on again. FIRST10 now ends Sun, Nov 1."
    for code in ("NOPE", "REFER-A-FRIEND"):
        out = act("change_offer", code=code, status="paused")
        assert out["failed"] and out["result"] == f"You don't have an offer with the code {code}, so nothing was changed."
    out = act("change_offer", code="FIRST10")
    assert out["failed"] and out["result"].startswith("Tell me what to change")
    assert len(world["changed"]) == 2


def test_refer_a_friend_on_and_off(world):
    out = act("set_refer_a_friend", on=True, amount=15, good_for_days=60)
    [body] = world["referral"]
    assert body.on is True and body.friend_cents == body.reward_cents == 1500 and body.thanks_days == 60
    assert out["result"] == ("Refer a friend is on: a friend gets $15 off a first visit, and the client gets $15 off "
                             "their next one once the friend's visit is paid. Each client's own link rides on their "
                             "“Time for your next visit?” note. Thank-you codes are good for 60 days.")
    out = act("set_refer_a_friend", on="false")
    assert world["referral"][-1].on is False and out["label"] == "Refer a friend off"
    assert out["result"].startswith("Refer a friend is off.")
    out = act("set_refer_a_friend", amount=10)
    assert out["failed"] and out["result"].startswith("Tell me whether to turn Refer a friend on or off")
    world["fail"] = HTTPException(409, "Connect card payments in Payments first, so the friend's offer can be taken off at booking.")
    out = act("set_refer_a_friend", on=True)
    assert out["failed"] and out["result"].endswith("Nothing was changed.")


@pytest.mark.parametrize("verb", VERBS)
def test_result_and_label_always_even_when_it_breaks(world, verb, monkeypatch):
    world["fail"] = RuntimeError("kaput")
    world["offers"] = {"FIRST10": {"id": "o1", "code": "FIRST10", "source": "owner"}}
    out = act(verb, amount=10, on=True, code="FIRST10", status="paused")
    assert out["failed"] is True and out["type"] == verb and out["result"] and out["label"]


# ─── 3. class, surfaces, schedule, the spoken hold ───────────────────

def test_class_c_tags_never_tools():
    for verb in VERBS:
        assert action_registry.effect(verb) == "write" and action_registry.reversibility(verb) == "C", verb
        assert not action_registry.is_bulk(verb)
        assert not action_registry.is_autonomy_eligible(verb, granted_scope=True)
        assert not action_registry.may_expose_to_agent(verb, allow_writes=True)
        assert verb not in mcp_server.WRITE_TOOL_SCHEMAS
        handler = cos.ACTION_HANDLERS[verb]
        assert handler is getattr(cos, handler.__name__) is getattr(coa, handler.__name__)


def test_schedule_action_will_not_wrap_an_offer_change():
    for verb in VERBS:
        out = run(cos.ACTION_HANDLERS["schedule_action"](None, BIZ_ROW, {
            "type": "schedule_action", "in_minutes": 60, "action": {"type": verb, "amount": 10}}))
        assert cos._action_failed(out) and "offers change only when the owner asks in chat" in out["result"], verb


def test_a_spoken_hold_names_what_it_gives():
    assert cos._confirmation_subject({"type": "make_offer", "amount": 10, "who": "first_visit"}) == \
        "for first visit · $10.00"
    assert cos._confirmation_subject({"type": "make_offer", "percent": 15, "who": "regulars"}) == "15% off · for regulars"
    assert cos._confirmation_subject({"type": "set_refer_a_friend", "on": True, "amount": 15}) == \
        "refer a friend on · each way · $15.00"
    assert cos._confirmation_subject({"type": "change_offer", "code": "first10", "status": "paused"}) == "FIRST10 paused"


# ─── 4. the prompt ────────────────────────────────────────────────────

def test_the_prompt_teaches_the_tags_and_the_rules():
    import chief_prompt
    src = inspect.getsource(chief_prompt)
    for verb in VERBS:
        assert f'"type":"{verb}"' in src, verb
    rule = src[src.index("OFFERS' RULES"):][:2400]
    for must in ("never on your own", "say back what it gives and to whom and get their yes", "Nothing goes out",
                 "Owner only", "connect card payments in Payments", "Say made, paused or on only as the result says"):
        assert must in rule, must
