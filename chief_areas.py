"""chief_areas.py — Chief keeps to a church login's lane.

Kevin, 2026-10-28: "lets build the board tab and so we can add the lanes for
chief". The office lanes (church_areas.LANES: Office & Leadership, People &
Care, Sunday & Serving, Media & Communications) set which parts of the
church an office login works in, and its menu follows. Until now Chief
didn't: the People & Care admin could ask it who gave what, or have it
change the website.

Sister Carla has the People & Care lane. She asks Chief to check on the
families who missed three Sundays, to draft a note to the Hendersons, to
add a task for the hospital visit: all hers. She asks what came in last
week, or to change the home page: Chief says that's Giving & money, or
Website & outreach, and who handles it, and does nothing. Her Chief never
sees gifts, invoices, the bank or the books, the owner's own memories and
past chats, or another lane's inbox.

Who: a non-owner login on a church whose areas are limited
(church_areas.my_areas: picked, or Chief's guess, with CHURCH_AREAS on). The
owner and admins keep everything, and so does every login of a business
that isn't a church: scope_for() says None and nothing here changes.

    the VERBS ........ each Chief verb (action or mid-turn read) and the
                       areas it belongs to; "*" is every office login's
                       (tasks, notes, the calendar, messages to people).
                       A verb not listed is the owner's and admins': a new
                       verb is refused to a lane until someone places it
                       (a test lists every handler)
    the gate ......... chief_of_staff._execute_actions and
                       chief_tool_loop.execute_tool_use ask refusal()
                       before a handler runs. A scheduled action is checked
                       by the action it schedules
    the context ...... trim_context() takes out what isn't theirs before
                       the prompt is built: money of every kind (open
                       invoices, products and prices, gifts and payments in
                       the events, the bank and the books, the forecast),
                       the owner's memories (their standing instructions
                       stay: they still bind), the bell, insights, plans
                       and missions, and the inbox unless the lane works
                       with people (People & care or Office)
    the prompt ....... block() tells Chief whose login this is and which
                       areas it works in, so it answers within them and
                       says who handles the rest

Switched by CHIEF_AREAS: on (the default) | off.
"""
from __future__ import annotations

import contextvars
import logging
import os
import re
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger("chief_areas")

# The turn's scope (scope_for), set once per Chief turn. None: everything.
TURN: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("chief_area_scope", default=None)

ALL = "*"
PEOPLE = ("people_care",)
MONEY = ("giving_money",)
SITE = ("website_outreach",)
MEDIA = ("worship_media",)
CLASSES = ("groups_classes",)
OFFICE = ("office",)
# Who works with the church's people, its inbox and its drafts.
WITH_PEOPLE = ("people_care", "office", "messages_safety")
# Who writes to the congregation in bulk.
BULK = ("people_care", "office", "website_outreach")

VERBS: Dict[str, Tuple[str, ...]] = {
    # Every office login's own work: tasks, notes, reminders, goals,
    # projects, the calendar, finding their way around, and writing to people.
    **{v: (ALL,) for v in (
        "create_task", "delete_task", "complete_task", "list_tasks", "create_note", "save_note", "add_reminder",
        "set_timer", "create_goal", "check_goals", "create_project", "update_project", "list_projects",
        "create_session", "update_session", "create_booking", "reschedule_booking", "cancel_booking",
        "create_recurring_booking", "cancel_recurring_booking", "list_availability", "open_calendar",
        "rehearse_booking_plan", "open_documents", "navigate", "show_plan", "show_readout", "close_view",
        "set_chat_window", "get_dashboard_layout", "set_dashboard_focus", "set_start_page", "get_weather",
        "show_view", "notify_practitioner", "recall_business_knowledge", "schedule_action", "cancel_scheduled",
        "list_scheduled", "create_module_entry", "update_module_entry", "delete_module_entry",
        "list_module_entries", "inspect_module", "summarize_module", "draft_email", "draft_and_send", "send_sms",
        "save_draft", "generate_document")},
    # People & care: the church's people, their care and their follow-up.
    **{v: PEOPLE for v in (
        "create_contact", "update_contact", "update_contact_status", "update_contact_health", "delete_contact",
        "log_activity", "draft_nurture", "draft_shepherd_moves")},
    "contact_deep_dive": PEOPLE + ("kids_youth", "groups_classes"),
    "church_people": PEOPLE + ("kids_youth", "groups_classes", "office"),
    # The drafts waiting for a yes, the inbox, and bulk mail.
    **{v: WITH_PEOPLE for v in (
        "approve_draft", "dismiss_draft", "edit_draft", "rewrite_draft", "bulk_approve", "bulk_dismiss",
        "mark_reply_read", "mark_sms_read")},
    "batch_email": BULK,
    # Groups & classes.
    **{v: CLASSES for v in (
        "create_course", "inspect_course", "save_course_content", "save_lesson_slides", "enroll_student",
        "publish_course")},
    # Worship & media.
    **{v: MEDIA for v in ("create_video", "inspect_video", "revise_video", "render_video", "publish_sermon")},
    **{v: MEDIA + SITE for v in ("generate_image", "find_images", "design_flyer")},
    # Website & outreach: the site, its forms, the marketing desk, campaigns.
    **{v: SITE for v in (
        "edit_site_text", "revert_site_text", "check_site", "site_health", "publish_to_site", "add_testimonial",
        "remove_testimonial", "add_faq", "view_website", "study_website", "capture_website_references",
        "create_client_form", "update_client_form", "list_client_forms", "marketing_desk", "marketing_new_post",
        "marketing_edit_post", "marketing_skip_post", "marketing_replan", "marketing_post_now", "plan_campaign",
        "launch_campaign", "pause_campaign", "campaign_status", "plan_content", "capture_idea", "publish_post",
        "post_image", "post_clip")},
    # Office: the phone and email setup's state, the calendar's hours,
    # documents and templates, the church's roles.
    **{v: OFFICE for v in (
        "sms_status", "email_setup_status", "set_availability_day", "set_availability_override",
        "add_block_range", "remove_block_range", "set_slot_granularity", "set_lead_time", "draft_contract",
        "contract_pdf", "save_email_template", "compose_template", "adjust_template", "draft_church_role")},
    # Giving & money: gifts, invoices, payments, the books, prices and stock.
    **{v: MONEY for v in (
        "giving_statement", "giving_statements_run", "growth_report", "save_growth_record", "create_invoice",
        "send_invoice", "mark_invoice_paid", "delete_invoice", "void_invoice", "archive_invoice", "restore_invoice",
        "cancel_recurring_invoice", "generate_payment_link", "show_revenue", "send_report", "review_books",
        "list_bookkeeping_proposals", "approve_bookkeeping_proposal", "reject_bookkeeping_proposal",
        "log_expense", "list_expenses", "update_expense", "delete_expense", "grant_balance", "consume_balance",
        "check_balance", "log_time", "bill_time_to_retainer", "unbilled_time", "write_off_time", "create_product",
        "update_product", "list_products", "create_offering", "update_offering", "archive_offering",
        "list_offerings", "offering_readiness", "setup_store", "check_inventory", "adjust_stock",
        "set_reorder_plan", "draft_purchase_order", "send_purchase_order")},
}
# The owner's and admins' alone: the business's settings, strategy and
# knowledge, Chief's own memory and recall, missions and agents that run
# later as the owner, the phone number and payments setup, builds and
# errands. Listed so that a new verb is placed on purpose: a test fails
# until every verb Chief has is in VERBS or here.
OWNERS = frozenset({
    "abandon_mission", "accept_module_spec", "acknowledge_follow_up", "add_module_field", "add_voice_rule",
    "adopt_business_rule", "advance_business_phase", "advance_mission", "advance_phase", "agentcard_wallet",
    "analyze_trends", "approve_errand", "assignment_status", "business_session_summary",
    "capture_business_knowledge", "catch_up", "change_offer", "check_module", "choose_workspace", "close_case",
    "complete_business_track", "complete_strategy_track", "confirm_workflow_step",
    "connected_agent_assignments", "correct_business_knowledge", "create_assignment", "create_growth_objective",
    "delegate_to_agent", "enqueue_job", "ensure_module", "errand_status", "forget", "generate_briefing",
    "generate_insights", "grant_standing_permission", "lane_wallet", "learn_business", "link_wallet_pilot",
    "list_connected_agents", "make_offer", "mission_status", "open_case", "plan_errand",
    "propose_brand_kit_from_context", "propose_business_from_idea", "propose_mission",
    "propose_module_from_intake", "propose_voice_rule", "provision_sms_number", "publish_booking_page",
    "queue_build_request", "recall_conversation", "record_edit_pattern", "reject_module_spec",
    "release_sms_number", "remember", "remove_business_rule", "remove_voice_rule", "rename_term",
    "respond_work_order", "responsibility_status", "restore_previous_site", "restore_sms_number",
    "revoke_standing_permission", "run_agent", "run_market_research", "save_business_model",
    "save_business_phase", "save_launch_plan", "save_packages", "save_phase", "save_pricing",
    "save_projections", "save_swot", "search_ledger", "session_summary", "set_business_policy",
    "set_business_timezone", "set_giving", "set_member_app", "set_module_feel", "set_refer_a_friend",
    "set_site_capability", "set_sms_alerts", "set_sms_keyword", "show_blueprint",
    "start_business_responsibility", "start_design_session", "start_mission", "stop_assignment", "stop_errand",
    "submit_work_order", "switch_layout", "switch_workspace", "undo_last", "update_business_profile_field",
    "update_practitioner_profile_field", "update_voice_profile", "update_voice_sample", "update_voice_style",
    "upgrade_module_archetype", "use_browser_hand", "what_undo"
})
# The views of show_view that are money.
MONEY_VIEWS = {"invoices", "products"}

# Events and timeline entries that are money.
MONEY_EVENT = re.compile(r"^(giv|gift|donat|pledge|invoice|payment|paid|pay_|payout|refund|charge|order|product_sold|"
                         r"stripe|expense|subscription|balance|purchase|revenue|recurring_gift)", re.I)
MONEY_ENTRY_KINDS = {"invoice", "order", "balance", "time"}
MONEY_SUMMARY = ("open_invoices", "open_invoice_total", "unbilled_minutes", "balances")
MONEY_TEXT = re.compile(r"(\$\s?\d|\bgift|\bgave\b|\bdonat|\binvoice|\bpayment|\bpaid\b|\brefund|\bpayout|"
                        r"\bgiving\b|\btith|\boffering)", re.I)


def mode() -> str:
    m = (os.environ.get("CHIEF_AREAS") or "on").strip().lower()
    return m if m in ("off", "on") else "on"


# ─── Whose login, and which areas ─────────────────────────────────────

CACHE_SECONDS = 60
_CACHE: Dict[Tuple[str, str], Tuple[float, Optional[Dict[str, Any]]]] = {}


def scope_for(business_id: Any, user_id: Any, owner_id: Any = None) -> Optional[Dict[str, Any]]:
    """{areas, role, lane} for a login Chief keeps to its areas, or None for
    everything: the owner, an admin, a business that isn't a church, a
    login nothing places yet, the switch off, or no login at all (the
    scheduler). Kept a minute a replica, the way the menu's view is."""
    if mode() == "off" or not business_id or not user_id or (owner_id and str(owner_id) == str(user_id)):
        return None
    key = (str(business_id), str(user_id))
    hit = _CACHE.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
        return hit[1]
    try:
        scope = _read_scope(*key)
    except Exception:  # noqa: BLE001 — a failed read keeps today's Chief, for the menu's reason
        logger.warning("chief areas: scope read failed (business %s)", key[0][:8])
        return None
    _CACHE[key] = (time.monotonic(), scope)
    return scope


def _read_scope(business_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    import church_areas
    import business_users_router
    try:
        role = business_users_router.role_of(business_id, user_id)
    except Exception:  # noqa: BLE001 — a failed read keeps today's Chief
        logger.warning("chief areas: role read failed (business %s)", business_id[:8])
        return None
    if not role or role == "owner" or role in church_areas.KEEPS_ALL:
        return None
    view = church_areas.my_areas(business_id, user_id, role)
    areas = (view or {}).get("areas")
    if not isinstance(areas, list):
        return None
    areas = [a for a in church_areas.AREA_ORDER if a in areas]
    return {"areas": areas, "role": role, "lane": church_areas.lane_of(role, areas)}


def forget(business_id: Any = None) -> None:
    """Drop the kept scopes (a test, or a pick just saved)."""
    for k in [k for k in _CACHE if business_id is None or k[0] == str(business_id)]:
        _CACHE.pop(k, None)


def has(scope: Optional[Dict[str, Any]], *areas: str) -> bool:
    """Whether this login works in any of these areas (everything, with no
    scope)."""
    return scope is None or any(a in scope["areas"] for a in areas)


# ─── Words ────────────────────────────────────────────────────────────

def label(area: str) -> str:
    import church_areas
    return (church_areas.AREAS.get(area) or {}).get("label") or area


def _list(words: List[str]) -> str:
    if len(words) < 2:
        return "".join(words)
    return ", ".join(words[:-1]) + " and " + words[-1]


def lane_words(scope: Dict[str, Any]) -> str:
    import church_areas
    lane = church_areas.LANES.get(scope.get("lane") or "") or {}
    return lane.get("label") or ""


def areas_words(scope: Dict[str, Any]) -> str:
    return _list([label(a) for a in scope["areas"]])


# ─── The gate ─────────────────────────────────────────────────────────

def areas_of(verb: str, action: Optional[Dict[str, Any]] = None) -> Optional[Tuple[str, ...]]:
    """The areas a verb (with its arguments) belongs to; None: the owner's
    and admins'."""
    needs = VERBS.get(verb or "")
    if needs is None and (verb or "").startswith("propose_"):
        import action_proposals   # a proposal is the verb it proposes
        inner = action_proposals.PROPOSALS.get(verb)
        needs = VERBS.get(inner[0]) if inner else None
    if needs and verb == "show_view" and str((action or {}).get("view") or "").strip().lower() in MONEY_VIEWS:
        return MONEY
    return needs


def refusal(verb: str, action: Optional[Dict[str, Any]], scope: Optional[Dict[str, Any]]) -> Optional[str]:
    """Why this login's Chief won't do this, in words it can pass on; None
    when it may."""
    if scope is None:
        return None
    needs = areas_of(verb, action)
    if needs and (ALL in needs or has(scope, *needs)):
        if verb == "schedule_action":
            inner = (action or {}).get("action")
            if isinstance(inner, dict):
                return refusal(str(inner.get("type") or ""), inner, scope)
        return None
    mine = areas_words(scope)
    if not needs:
        return (f"That's for the church's owner or an admin, not this login. This login works in {mine}. "
                "Ask the owner or an admin to do it.")
    theirs = _list([label(a) for a in needs])
    if needs == MONEY:
        return (f"That's {theirs}: the owner, an admin or the treasurer handles it. This login works in {mine}, "
                "and Chief doesn't read or change money for it.")
    return (f"That's {theirs}, outside this login's areas ({mine}). Ask whoever has {theirs}, the owner or "
            "an admin.")


def current() -> Optional[Dict[str, Any]]:
    return TURN.get()


# ─── What the prompt sees ─────────────────────────────────────────────

def _money_event(e: Dict[str, Any]) -> bool:
    if not isinstance(e, dict):
        return False
    kind = str(e.get("event_type") or e.get("type") or e.get("kind") or "")
    if MONEY_EVENT.match(kind):
        return True
    data = e.get("data") if isinstance(e.get("data"), dict) else {}
    return any(k in data for k in ("amount", "amount_cents", "total", "gift_id", "invoice_id", "payment_id"))


def _moneyish(row: Any) -> bool:
    """A draft, a notification or a line whose words are about money."""
    if not isinstance(row, dict):
        return bool(MONEY_TEXT.search(str(row or "")))
    text = " ".join(str(row.get(k) or "") for k in ("type", "kind", "action_type", "draft_type", "category",
                                                    "subject", "title", "message", "body", "label"))
    return bool(MONEY_TEXT.search(text) or MONEY_EVENT.match(str(row.get("type") or row.get("action_type") or "")))


def trim_context(ctx: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The context with only what this login's Chief may read. Unchanged
    with no scope."""
    if scope is None or not isinstance(ctx, dict):
        return ctx
    out = dict(ctx)
    money = has(scope, *MONEY)
    people = has(scope, *WITH_PEOPLE)
    if not money:
        for k in ("open_invoices", "products", "offerings"):
            out[k] = []
            out[f"{k}_complete"] = False
        out["events"] = [e for e in out.get("events") or [] if not _money_event(e)]
        out["projects"] = [{**p, "value": 0} for p in out.get("projects") or [] if isinstance(p, dict)]
        for k in ("strategy_track", "business_track"):
            out[k] = None
    # The owner's own memory and the owner's desk: their standing
    # instructions still bind every login, the rest is theirs.
    import chief_of_staff
    out["memories"] = [m for m in out.get("memories") or [] if chief_of_staff._is_owner_standing_instruction(m)]
    out["memories_for_message"] = []
    for k in ("notifications", "insights", "open_missions", "open_assignments", "open_cases", "learning_lines",
              "recent_queue_24h", "auto_recent"):
        if k in out:
            out[k] = [] if isinstance(out[k], list) else None
    if people:
        queue = [q for q in out.get("queue") or [] if money or not _moneyish(q)]
    else:
        queue = []
        out["email_replies"] = []
        out["email_replies_withheld"] = 0
        out["sms_messages"] = []
    if len(queue) != len(out.get("queue") or []) or not people:
        out["queue_total"] = len(queue)
        out["queue_kinds"] = None
    out["queue"] = queue
    if not has(scope, *PEOPLE):
        out["at_risk"] = []
    out["chief_area_scope"] = scope
    return out


def trim_sources(vals: Dict[str, Any], scope: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The turn's extra sources (chief_of_staff._context_sources), trimmed
    the same way: no bank or forecast without Giving, none of the owner's
    habits or time, the people the owner is drifting from only for People &
    care."""
    if scope is None:
        return vals
    out = dict(vals)
    if not has(scope, *MONEY):
        out["bookkeeping_block"] = ""
        out["forecast"] = None
    for k, empty in (("habit_block", ""), ("time_block", ""), ("mentor_active", False)):
        if k in out:
            out[k] = empty
    if not has(scope, *PEOPLE) and "relationship_insights" in out:
        out["relationship_insights"] = []
    return out


def trim_view(view_detail: Any, scope: Optional[Dict[str, Any]]) -> Any:
    """The record on screen, without its money for a login with no Giving."""
    if scope is None or has(scope, *MONEY) or not isinstance(view_detail, dict):
        return view_detail
    out = dict(view_detail)
    for k, v in view_detail.items():
        if isinstance(v, list) and k.endswith("events"):
            out[k] = [e for e in v if not _money_event(e)]
        elif isinstance(v, list) and k.endswith("queue"):
            out[k] = [q for q in v if not _moneyish(q)]
        elif k in ("invoices", "contact_invoices", "orders", "payments", "ledger", "balances"):
            out[k] = []
    return out


def trim_result(verb: str, result: Any, scope: Optional[Dict[str, Any]]) -> Any:
    """A read's result, without money for a login with no Giving: a person's
    deep dive shows their care, never what they gave."""
    if scope is None or has(scope, *MONEY) or not isinstance(result, dict) or verb != "contact_deep_dive":
        return result
    out = dict(result)
    entries = [e for e in result.get("timeline") or [] if (e or {}).get("kind") not in MONEY_ENTRY_KINDS]
    summary = {k: v for k, v in (result.get("summary") or {}).items() if k not in MONEY_SUMMARY}
    if isinstance(summary.get("by_kind"), dict):
        summary["by_kind"] = {k: v for k, v in summary["by_kind"].items() if k not in MONEY_ENTRY_KINDS}
    out.update(timeline=entries, summary=summary,
               events=[e for e in result.get("events") or [] if not _money_event(e)],
               queue_history=[q for q in result.get("queue_history") or [] if not _moneyish(q)])
    try:
        import client_timeline
        out["timeline_text"] = client_timeline.narrate({"contact": result.get("contact") or {}, "summary": summary,
                                                       "entries": entries})
    except Exception:  # noqa: BLE001 — no narration rather than one with money in it
        out["timeline_text"] = ""
    return out


def block(scope: Optional[Dict[str, Any]]) -> str:
    """The prompt's word on whose login this is. Rides the turn's tail: it
    differs by login, so it never sits in a cached segment."""
    if scope is None:
        return ""
    lane = lane_words(scope)
    mine = areas_words(scope)
    money = has(scope, *MONEY)
    lines = [
        "THIS LOGIN — not the owner. " + (f"It has the {lane} lane: " if lane else "It works in: ") + mine + ".",
        "Answer and act within those areas, and with everyone's own work (tasks, notes, the calendar, writing to "
        "people). For any other part of the church, say which area it is and that the owner, an admin or whoever "
        "has that area handles it; don't take it on, and don't guess at what you can't see.",
    ]
    if not money:
        lines.append("Money isn't this login's: you don't see gifts, giving, invoices, payments, the bank or the "
                     "books, and you never say what anyone gave, what came in or what anything costs. If asked, "
                     "say the owner, an admin or the treasurer can answer.")
    lines.append("The owner's own memories and past conversations aren't shown to this login; don't mention them.")
    return "\n".join(lines) + "\n"
