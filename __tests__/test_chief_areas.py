"""Chief keeps to a church login's lane (chief_areas.py). Kevin 2026-10-28:
"lets build the board tab and so we can add the lanes for chief".

Pins:
  * whose: only a non-owner, non-admin login of a church whose areas are
    limited is kept to them; the owner, an admin, a login nothing places,
    another kind of business and the switch off keep today's Chief
  * every verb Chief has is placed: in a lane, everyone's, or the owner's
  * the gate: a verb outside the login's areas is refused before its
    handler runs, at the door and mid-turn, with words Chief can pass on;
    a scheduled action is the action it schedules, a proposal the verb it
    proposes, and a money view of show_view is money
  * the context: no money without Giving (invoices, products, gifts in the
    events, the bank, the forecast), none of the owner's memories but
    their standing instructions, no bell, no inbox for a lane that doesn't
    work with people; a person's deep dive keeps their care, not their gifts
  * the prompt names the lane and says money isn't theirs
"""
from __future__ import annotations

import asyncio
import os
import sys
from types import SimpleNamespace

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import chief_areas as ca  # noqa: E402

BIZ = "11111111-1111-4111-8111-111111111111"
OWNER = "00000000-0000-4000-8000-000000000001"
CARLA = "00000000-0000-4000-8000-000000000002"     # People & Care
JESS = "00000000-0000-4000-8000-000000000003"      # an admin
NEW = "00000000-0000-4000-8000-000000000004"       # nothing places her yet
MEDIA = "00000000-0000-4000-8000-000000000005"     # Media & Communications

CARE = {"areas": ["people_care", "kids_youth", "groups_classes"], "role": "manager", "lane": "people_care"}
COMMS = {"areas": ["worship_media", "website_outreach"], "role": "manager", "lane": "media_comms"}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.delenv("CHIEF_AREAS", raising=False)
    ca.forget()
    yield
    ca.forget()


@pytest.fixture
def logins(monkeypatch):
    import business_users_router
    import church_areas
    roles = {OWNER: "owner", CARLA: "manager", JESS: "admin", NEW: "manager", MEDIA: "manager"}
    views = {CARLA: {"areas": ["groups_classes", "people_care", "kids_youth"], "by": "picked"},
             NEW: {"areas": None, "by": "none"}, MEDIA: {"areas": ["website_outreach", "worship_media"], "by": "picked"}}
    reads = []
    monkeypatch.setattr(business_users_router, "role_of", lambda biz, uid: reads.append(uid) or roles.get(uid))
    monkeypatch.setattr(church_areas, "my_areas", lambda biz, uid, role: views.get(uid))
    return reads


# ─── Whose ────────────────────────────────────────────────────────────

def test_only_a_limited_church_login_is_kept_to_its_areas(logins, monkeypatch):
    got = ca.scope_for(BIZ, CARLA)
    assert got == {"areas": ["people_care", "kids_youth", "groups_classes"], "role": "manager", "lane": "people_care"}
    assert ca.scope_for(BIZ, MEDIA)["lane"] == "media_comms"
    for who in (OWNER, JESS, NEW, "00000000-0000-4000-8000-00000000dead"):
        assert ca.scope_for(BIZ, who) is None, who
    assert ca.scope_for(BIZ, None) is None and ca.scope_for(None, CARLA) is None
    n = len(logins)
    assert ca.scope_for(BIZ, OWNER, owner_id=OWNER) is None and len(logins) == n, "the owner costs no read"
    ca.scope_for(BIZ, CARLA)
    assert len(logins) == n, "kept a minute"
    monkeypatch.setenv("CHIEF_AREAS", "off")
    assert ca.scope_for(BIZ, MEDIA) is None


def test_a_failed_read_keeps_todays_chief(monkeypatch):
    import business_users_router

    def boom(biz, uid):
        raise RuntimeError("down")
    monkeypatch.setattr(business_users_router, "role_of", boom)
    assert ca.scope_for(BIZ, CARLA) is None


def test_every_verb_chief_has_is_placed():
    import action_proposals
    import chief_of_staff
    import mcp_server
    names = set(chief_of_staff.ACTION_HANDLERS) | {t["name"] for t in mcp_server.tool_definitions()}
    loose = sorted(n for n in names if n not in ca.VERBS and n not in ca.OWNERS)
    assert loose == [], f"place these in chief_areas.VERBS or OWNERS: {loose}"
    assert not set(ca.VERBS) & ca.OWNERS
    stale = sorted((set(ca.VERBS) | ca.OWNERS) - names)
    assert stale == [], f"no such verb any more: {stale}"
    for p, (verb, _, _) in action_proposals.PROPOSALS.items():
        assert verb in ca.VERBS or verb in ca.OWNERS, p
    import church_areas
    for verb, areas in ca.VERBS.items():
        assert all(a == ca.ALL or a in church_areas.AREAS for a in areas), verb


# ─── The gate ─────────────────────────────────────────────────────────

def test_what_a_lane_may_and_may_not_do():
    may = ("create_task", "list_tasks", "create_booking", "draft_email", "send_sms", "create_contact",
           "contact_deep_dive", "church_people", "approve_draft", "create_course", "propose_send_sms")
    for verb in may:
        assert ca.refusal(verb, {}, CARE) is None, verb
    assert ca.refusal("show_view", {"view": "contacts"}, CARE) is None
    site = ca.refusal("edit_site_text", {}, CARE)
    assert site.startswith("That's Website & outreach, outside this login's areas (People & care, Kids & youth "
                           "and Groups & classes)")
    for verb, args in (("show_revenue", {}), ("create_invoice", {}), ("giving_statement", {}),
                       ("show_view", {"view": "invoices"}), ("propose_send_invoice", {}), ("list_products", {})):
        assert ca.refusal(verb, args, CARE).startswith("That's Giving & money: the owner, an admin or the treasurer"), verb
    for verb in ("recall_conversation", "catch_up", "search_ledger", "remember", "forget", "undo_last",
                 "update_business_profile_field", "provision_sms_number", "propose_adopt_business_rule",
                 "a_verb_nobody_placed"):
        assert ca.refusal(verb, {}, CARE).startswith("That's for the church's owner or an admin"), verb
    # A scheduled action is the action it schedules.
    assert ca.refusal("schedule_action", {"action": {"type": "create_task"}}, CARE) is None
    assert "Giving & money" in ca.refusal("schedule_action", {"action": {"type": "send_invoice"}}, CARE)
    # The other lane's own work is theirs, and Carla's isn't.
    assert ca.refusal("edit_site_text", {}, COMMS) is None and ca.refusal("render_video", {}, COMMS) is None
    assert "People & care" in ca.refusal("create_contact", {}, COMMS)
    assert ca.refusal("approve_draft", {}, COMMS) is not None, "the drafts are for those who work with people"
    # No scope: everything, as today.
    for verb in ("show_revenue", "recall_conversation", "a_verb_nobody_placed"):
        assert ca.refusal(verb, {}, None) is None


def test_the_door_refuses_before_the_handler_runs(monkeypatch):
    import chief_of_staff as cos
    import policy_engine
    monkeypatch.setattr(policy_engine, "evaluate", lambda *a, **k: SimpleNamespace(allowed=True, rule="owner"))
    ran = []

    def handler(verb):
        async def h(client, biz, action):
            ran.append(verb)
            return {"type": verb, "result": "done", "label": verb}
        return h
    for verb in ("create_task", "show_revenue", "edit_site_text"):
        monkeypatch.setitem(cos.ACTION_HANDLERS, verb, handler(verb))
    biz = {"id": BIZ, "owner_id": OWNER}
    acts = [{"type": "create_task", "title": "Visit the Hendersons"}, {"type": "show_revenue"},
            {"type": "edit_site_text", "page": "home"}]
    token = ca.TURN.set(CARE)
    try:
        out = asyncio.run(cos._execute_actions(None, biz, acts, user_id=CARLA))
    finally:
        ca.TURN.reset(token)
    assert ran == ["create_task"]
    assert out[0]["result"] == "done"
    assert out[1]["failed"] and "Giving & money" in out[1]["result"] and out[1]["label"] == "show_revenue"
    assert out[2]["failed"] and "Website & outreach" in out[2]["result"]

    # A tap in the Approval Queue, outside a chat turn: looked up by login.
    ran.clear()
    monkeypatch.setattr(ca, "scope_for", lambda biz_id, uid, owner_id=None: CARE if uid == CARLA else None)
    out = asyncio.run(cos._execute_actions(None, biz, acts[1:2], user_id=CARLA, surface="approval"))
    assert ran == [] and out[0]["failed"]
    asyncio.run(cos._execute_actions(None, biz, acts, user_id=OWNER))
    assert ran == ["create_task", "show_revenue", "edit_site_text"], "the owner keeps everything"
    ran.clear()
    asyncio.run(cos._execute_actions(None, biz, acts[1:2], user_id=None, surface="agent", prompted=False))
    assert ran == ["show_revenue"], "no login: the scheduler, as today"


def test_mid_turn_reads_are_refused_and_trimmed(monkeypatch):
    import chief_of_staff as cos
    import chief_tool_loop as tl
    ran = []

    async def revenue(client, biz, action):
        ran.append("show_revenue")
        return {"type": "show_revenue", "result": "$4,200", "label": "x"}

    async def dive(client, biz, action):
        return {"type": "contact_deep_dive", "result": "data retrieved", "label": "Deep dive: Ruth",
                "contact": {"name": "Ruth"},
                "timeline": [{"kind": "note", "at": "2026-10-20", "title": "Hospital visit"},
                             {"kind": "invoice", "at": "2026-10-19", "title": "Gift $500"}],
                "summary": {"count": 2, "open_invoices": 1, "open_invoice_total": 500.0, "balances": {"money": 5},
                            "by_kind": {"note": 1, "invoice": 1}},
                "timeline_text": "Gift $500", "events": [{"event_type": "giving_received", "data": {"amount": 500}},
                                                         {"event_type": "note_added", "data": {}}]}
    monkeypatch.setitem(cos.ACTION_HANDLERS, "show_revenue", revenue)
    monkeypatch.setitem(cos.ACTION_HANDLERS, "contact_deep_dive", dive)
    token = ca.TURN.set(CARE)
    try:
        err, text = asyncio.run(tl.execute_tool_use(None, {"id": BIZ}, "show_revenue", {}))
        assert err and "Giving & money" in text and ran == []
        err, text = asyncio.run(tl.execute_tool_use(None, {"id": BIZ}, "propose_send_invoice", {}))
        assert err and "Giving & money" in text
        err, text = asyncio.run(tl.execute_tool_use(None, {"id": BIZ}, "contact_deep_dive", {"contact_id": "x"}))
        assert not err and "Hospital visit" in text and "Gift" not in text and "500" not in text
    finally:
        ca.TURN.reset(token)
    err, text = asyncio.run(tl.execute_tool_use(None, {"id": BIZ}, "show_revenue", {}))
    assert ran == ["show_revenue"], "no scope: as today"


# ─── What the prompt sees ─────────────────────────────────────────────

def _ctx():
    return {
        "business": {"id": BIZ, "name": "Love City Church"},
        "open_invoices": [{"id": "i1", "client": "Ruth", "total": 500.0}], "open_invoices_complete": True,
        "products": [{"name": "Retreat", "price": 50}], "offerings": [{"name": "Class", "price": 20}],
        "events": [{"event_type": "giving_received", "data": {"amount": 500, "contact_name": "Ruth"}},
                   {"event_type": "contact_created", "data": {"name": "Sam"}},
                   {"event_type": "note_added", "data": {"total": 3}}],
        "projects": [{"title": "Roof", "value": 18400}],
        "memories": [{"category": "standing_instruction", "source": "user_stated", "content": "Never text after 9pm"},
                     {"category": "personal", "source": "user_stated", "content": "My wife's birthday is May 2"}],
        "memories_for_message": [{"content": "something private"}],
        "notifications": [{"title": "Gift received — $500"}], "insights": [{"title": "Revenue up 12%"}],
        "open_missions": [{"title": "x"}], "recent_queue_24h": [{"x": 1}],
        "queue": [{"type": "nurture", "subject": "Checking in"}, {"type": "invoice_reminder", "subject": "Your invoice"},
                  {"type": "email", "subject": "Your 2026 giving statement"}],
        "queue_total": 3, "queue_kinds": [["nurture", 1]],
        "email_replies": [{"subject": "Prayer for my mother"}], "email_replies_withheld": 2,
        "sms_messages": [{"body": "Running late"}], "at_risk": [{"name": "Sam"}],
        "strategy_track": {"pricing": 1}, "business_track": {"swot": 1},
    }


def test_the_context_a_lane_reads():
    care = ca.trim_context(_ctx(), CARE)
    assert care["open_invoices"] == [] and care["open_invoices_complete"] is False
    assert care["products"] == [] and care["offerings"] == []
    assert [e["event_type"] for e in care["events"]] == ["contact_created"]
    assert care["projects"] == [{"title": "Roof", "value": 0}]
    assert [m["content"] for m in care["memories"]] == ["Never text after 9pm"], "standing instructions still bind"
    assert care["memories_for_message"] == [] and care["notifications"] == [] and care["insights"] == []
    assert care["open_missions"] == [] and care["recent_queue_24h"] == []
    assert [q["subject"] for q in care["queue"]] == ["Checking in"] and care["queue_total"] == 1
    assert care["email_replies"] and care["sms_messages"] and care["at_risk"], "People & care works with people"
    assert care["strategy_track"] is None and care["business_track"] is None
    comms = ca.trim_context(_ctx(), COMMS)
    assert comms["email_replies"] == [] and comms["email_replies_withheld"] == 0 and comms["sms_messages"] == []
    assert comms["queue"] == [] and comms["queue_total"] == 0 and comms["at_risk"] == []
    assert ca.trim_context(_ctx(), None) == _ctx(), "no scope: unchanged"

    vals = {"bookkeeping_block": "Cash: $9,000", "forecast": {"next": 1}, "habit_block": "h", "time_block": "t",
            "mentor_active": True, "relationship_insights": [{"name": "Sam"}], "voice_examples": "v"}
    got = ca.trim_sources(vals, COMMS)
    assert got["bookkeeping_block"] == "" and got["forecast"] is None and got["habit_block"] == ""
    assert got["relationship_insights"] == [] and got["voice_examples"] == "v"
    assert ca.trim_sources(vals, CARE)["relationship_insights"] == [{"name": "Sam"}]
    assert ca.trim_sources(vals, None) is vals

    view = {"contact": {"name": "Ruth"}, "contact_events": [{"event_type": "payment_received", "data": {}},
                                                            {"event_type": "note_added", "data": {}}]}
    assert [e["event_type"] for e in ca.trim_view(view, CARE)["contact_events"]] == ["note_added"]


def test_the_prompt_names_the_lane():
    text = ca.block(CARE)
    assert text.startswith("THIS LOGIN — not the owner. It has the People & Care lane: People & care, Kids & youth "
                           "and Groups & classes.")
    assert "never say what anyone gave" in text and "past conversations" in text
    assert ca.block(None) == ""
    odd = ca.block({"areas": ["office"], "role": "member", "lane": None})
    assert "It works in: Office." in odd


# ─── A whole turn ─────────────────────────────────────────────────────

from __tests__.test_chief_preparation_overlap import prep  # noqa: E402,F401


def test_a_lanes_turn_reads_and_is_told_only_its_own(prep, monkeypatch):
    import chief_of_staff as chief
    from fastapi import HTTPException
    biz = {"id": "biz", "owner_id": "owner", "name": "Love City Church", "type": "ministry",
           "created_at": "2026-01-01", "settings": {}}
    prep.context.return_value = {**_ctx(), "business": dict(biz), "contacts_total": 10, "sessions": []}
    monkeypatch.setattr(chief, "_sb", __import__("unittest.mock").mock.AsyncMock(return_value=[dict(biz)]))
    monkeypatch.setattr(ca, "scope_for", lambda b, uid, owner_id=None: CARE if uid == "carla" else None)
    monkeypatch.setattr(chief, "_format_setup_block", lambda _: "")
    sources = {"voice_examples": "", "session_context": "", "mentor_active": False, "forecast": None,
               "relationship_insights": [], "time_block": "", "habit_block": "", "bookkeeping_block": "Cash: $9,000"}

    def context_sources(client, b):
        async def value(v):
            return v
        return {k: (lambda v=v: value(v), v) for k, v in sources.items()}
    monkeypatch.setattr(chief, "_context_sources", context_sources)
    seen = {}

    def build(ctx, *a, **k):
        seen.update(ctx=ctx, kw=k, turn=ca.TURN.get())
        raise HTTPException(491, "the prompt was reached")
    monkeypatch.setattr(chief, "_build_system_prompt", build)

    async def turn(uid):
        token = chief._STREAM_SINK.set(lambda _: None)
        try:
            await chief.chief_chat(chief.ChatRequest(business_id="biz", message="How are the Hendersons doing?"),
                                   SimpleNamespace(token="jwt-" + uid, user=SimpleNamespace(id=uid)))
        finally:
            chief._STREAM_SINK.reset(token)
            seen["after"] = ca.TURN.get()

    with pytest.raises(HTTPException) as e:
        asyncio.run(turn("carla"))
    assert e.value.status_code == 491
    assert seen["turn"] == CARE
    assert seen["ctx"]["open_invoices"] == [] and [x["event_type"] for x in seen["ctx"]["events"]] == ["contact_created"]
    assert seen["kw"]["bookkeeping_block"] == ""
    assert seen["kw"]["growth_turn_block"].startswith("THIS LOGIN — not the owner. It has the People & Care lane")
    assert seen["after"] is None, "the scope ends with the turn"

    seen.clear()
    with pytest.raises(HTTPException):
        asyncio.run(turn("owner"))
    assert seen["turn"] is None and seen["ctx"]["open_invoices"] and seen["kw"]["bookkeeping_block"] == "Cash: $9,000"
    assert "THIS LOGIN" not in seen["kw"]["growth_turn_block"]
