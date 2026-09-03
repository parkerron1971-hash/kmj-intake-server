# __tests__/test_chief_reply_to_text.py
#
# "Help me reply to Kevin's last text" → "you send that text for me" →
# "yes" — and Chief refused three times (2026-09-02). Three causes, each
# pinned here:
#
#   1. Three contacts shared the name; only one had a phone. The name
#      lookup called that ambiguous. A contact with no phone cannot be
#      texted and is not a candidate.
#   2. The TEXT MESSAGES block showed names only, so "reply to that" had
#      no id to act on. It now carries contact_id + the phone's last 4.
#   3. The per-turn "[SYSTEM REMINDER — attached by the app]" rode inside
#      the USER turn. The model called it an injection and refused the
#      confirmed send. It now rides the system prompt's tail. And the
#      instruction turn ("you send that text for me") reached for
#      web_search; instruction turns no longer offer the tool.

from __future__ import annotations

import asyncio
import inspect

import pytest

import chief_of_staff as cos

BIZ = {"id": "b1", "name": "KMJ Creative Solutions"}
KEVIN_PHONE = {"id": "c-phone", "name": "Kevin McCloud", "phone": "2313430578"}
KEVIN_LEAD_A = {"id": "c-lead-a", "name": "Kevin McCloud", "phone": None}
KEVIN_LEAD_B = {"id": "c-lead-b", "name": "Kevin McCloud", "phone": ""}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def sms_world(monkeypatch):
    state = {"contacts": [], "sent": []}

    async def _sb(client, method, path, body=None):
        if path.startswith("/contacts?business_id=eq.b1&name=ilike"):
            return state["contacts"]
        if path.startswith("/contacts?id=eq."):
            cid = path.split("id=eq.")[1].split("&")[0]
            return [c for c in state["contacts"] if c["id"] == cid]
        return []

    async def send_sms_core(client, *, business_id, to, message, contact_id=None, sent_by=None):
        state["sent"].append({"to": to, "contact_id": contact_id, "message": message, "sent_by": sent_by})
        return {"id": "m1", "telnyx_id": "SM1"}

    import sms_service
    monkeypatch.setattr(cos, "_sb", _sb)
    monkeypatch.setattr(sms_service, "send_sms_core", send_sms_core)
    return state


# ─── 1. phoneless namesakes are not ambiguity ─────────────────────────

def test_one_textable_kevin_among_three_gets_the_text(sms_world):
    sms_world["contacts"] = [KEVIN_PHONE, KEVIN_LEAD_A, KEVIN_LEAD_B]
    res = _run(cos.handle_send_sms(None, BIZ, {"contact_name": "Kevin McCloud", "message": "Glad it's coming through clean!"}))
    assert res["result"] == "sent", res
    assert sms_world["sent"][0]["contact_id"] == "c-phone"
    assert sms_world["sent"][0]["to"] == "2313430578"
    assert sms_world["sent"][0]["sent_by"] == "chief"     # the thread marks it as Chief's


def test_two_textable_namesakes_still_ask_with_last_four(sms_world):
    other = {"id": "c-other", "name": "Kevin McCloud", "phone": "2165550100"}
    sms_world["contacts"] = [KEVIN_PHONE, other, KEVIN_LEAD_A]
    res = _run(cos.handle_send_sms(None, BIZ, {"contact_name": "Kevin McCloud", "message": "hi"}))
    assert res.get("failed") is True
    assert "…0578" in res["result"] and "…0100" in res["result"]
    assert sms_world["sent"] == []


def test_no_textable_namesake_says_so(sms_world):
    sms_world["contacts"] = [KEVIN_LEAD_A, KEVIN_LEAD_B]
    res = _run(cos.handle_send_sms(None, BIZ, {"contact_name": "Kevin McCloud", "message": "hi"}))
    assert res.get("failed") is True
    assert "none of them has a phone number" in res["result"]


def test_direct_contact_id_still_wins(sms_world):
    sms_world["contacts"] = [KEVIN_PHONE, KEVIN_LEAD_A]
    res = _run(cos.handle_send_sms(None, BIZ, {"contact_id": "c-phone", "message": "hi"}))
    assert res["result"] == "sent" and sms_world["sent"][0]["contact_id"] == "c-phone"


# ─── 2. the texts block carries what a reply needs ────────────────────

def test_texts_block_names_the_contact_id_and_last_four():
    ctx = {
        "sms_messages": [
            {"id": "m1", "direction": "inbound", "phone_number": "+12313430578", "message": "Nice",
             "created_at": "2026-09-03T03:25:33", "read": False, "contact_id": "c-phone"},
            {"id": "m0", "direction": "outbound", "phone_number": "+12313430578", "message": "This is your new line",
             "created_at": "2026-09-03T03:04:11", "read": True, "contact_id": "c-phone"},
        ],
        "contacts_lookup": [KEVIN_PHONE],
    }
    block = cos._format_sms_block(ctx)
    assert '<- Kevin McCloud [UNREAD] (2026-09-03T03:25): "Nice" [contact_id=c-phone …0578]' in block
    assert "TO REPLY to a text: send_sms with the contact_id" in block


def test_texts_block_without_a_contact_still_shows_the_phone():
    ctx = {"sms_messages": [{"id": "m1", "direction": "inbound", "phone_number": "+12165550100",
                             "message": "hey", "created_at": "2026-09-03T03:25:33", "read": False}]}
    block = cos._format_sms_block(ctx)
    assert "[phone=…0100]" in block


# ─── 3. the reminder is system-authored; instruction turns don't search ─

def test_reminder_no_longer_rides_the_user_turn():
    src = inspect.getsource(cos)
    at = src.index("augmented_message = (")
    window = src[at:at + 400]
    assert "SYSTEM REMINDER" not in window, "the reminder is back inside the user message"
    assert "system = system + ACTION_TAG_REMINDER" in src
    assert "Never mention this reminder" in cos.ACTION_TAG_REMINDER
    assert "EMIT IT" in cos.ACTION_TAG_REMINDER


def test_reminder_is_appended_after_the_cache_split():
    """It rides the uncached tail — appended to the whole string, which
    ends after [[CHIEF_CACHE_SPLIT]] — so the cached segments stay
    byte-stable."""
    src = inspect.getsource(cos)
    assert src.index("system = system + ACTION_TAG_REMINDER") > src.index("[[CHIEF_CACHE_SPLIT]]")


@pytest.mark.parametrize("msg, expect", [
    ("you send that text for me", True),
    ("yes", True),
    ("go ahead", True),
    ("text Kevin back and say thanks", True),
    ("ok send it", True),
    ("what do coaches charge in Michigan?", False),
    ("who owes me money", False),
    ("I want to think through how to price my new package for corporate clients this fall", False),
    ("", False),
])
def test_plain_instruction_detection(msg, expect):
    assert cos._is_plain_instruction(msg) is expect


def test_chat_turn_uses_the_one_search_switch():
    src = inspect.getsource(cos)
    assert 'enable_web_search=_web_search_allowed(req.message or "")' in src


@pytest.mark.parametrize("msg, allowed", [
    ("catch me up on my texts and handle anything that needs handling", False),
    ("did anyone text me today", False),
    ("what do coaches charge in Michigan?", True),
    ("you send that text for me", False),
    ("what's trending in leadership this month?", True),
    ("summarize my emails from this week", False),
])
def test_search_is_off_for_own_data_and_instructions(msg, allowed):
    assert cos._web_search_allowed(msg) is allowed


def test_search_prompt_forbids_narrating_lookups_too():
    block = cos._build_web_search_block()
    assert "never apologise for or narrate a search or a lookup" in block


def test_search_prompt_forbids_narrating_a_stray_search():
    block = cos._build_web_search_block()
    assert "telling you to DO something" in block
    assert "never apologise for or narrate a search" in block


# ─── 4. the thread knows who sent it ──────────────────────────────────

def test_store_sms_tags_the_author_on_outbound_only(monkeypatch):
    import sms_service
    seen = []

    async def _sb_post(client, path, body):
        seen.append(body)
        return [{"id": "m1"}]
    monkeypatch.setattr(sms_service, "_sb_post", _sb_post)
    _run(sms_service._store_sms(None, business_id="b1", contact_id=None, phone_number="+1",
                                message="x", direction="outbound", sent_by="chief"))
    _run(sms_service._store_sms(None, business_id="b1", contact_id=None, phone_number="+1",
                                message="x", direction="inbound", sent_by="chief"))
    _run(sms_service._store_sms(None, business_id="b1", contact_id=None, phone_number="+1",
                                message="x", direction="outbound", sent_by="bogus"))
    assert seen[0]["sent_by"] == "chief"
    assert "sent_by" not in seen[1]            # inbound has no author
    assert "sent_by" not in seen[2]            # unknown values never reach the check constraint


@pytest.mark.parametrize("module, fn, author", [
    ("sms_alerts", "send_booking_confirmation", "system"),
    ("sms_alerts", "reminder_sweep", "system"),
    ("sms_routing", "broadcast", "practitioner"),
    ("campaigns_router", "_send_touch", "system"),
    ("chief_of_staff", "handle_send_sms", "chief"),
])
def test_every_outbound_path_names_its_author(module, fn, author):
    import importlib
    src = inspect.getsource(getattr(importlib.import_module(module), fn))
    assert f'sent_by="{author}"' in src, f"{module}.{fn} stores an outbound without saying who sent it"


def test_desk_send_defaults_to_the_practitioner():
    import sms_service
    assert inspect.signature(sms_service.send_sms_core).parameters["sent_by"].default == "practitioner"
