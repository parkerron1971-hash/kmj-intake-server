"""
action_registry.py — what each Chief action DOES, as data (S1.1 steps 1-2).

WHY THIS EXISTS
  `chief_of_staff.ACTION_HANDLERS` is a bare {verb: handler} dict. Nothing in
  it says whether a verb reads or writes, whether a write can be undone, or
  whether it reaches the outside world. Three things need that answer and each
  currently invents its own:

    - Chief autonomy — "may Chief do this without asking?" (the A/B/C
      reversibility model in docs/extensibility_and_autonomy.md §2.4)
    - An agent-facing MCP surface — "which verbs may an outside agent call?"
      (docs/future_architecture.md §3, and PERSONAL_AGENT_ARCHITECTURE.md §4's
      open-on-read / closed-on-write rule in the frontend repo)
    - `chief_action_reasoner.SAFE_REMAP_ACTIONS` — a hand-maintained subset
      that a comment merely *asks* to stay in sync with the registry

WHY IT IS NOT DERIVED FROM THE CODE
  Static analysis was tried and is not merely imperfect, it is confidently
  wrong in the worst places. A detector keyed on `"POST"/"PATCH"/"DELETE"` in
  the handler body reports `send_sms` as read-only (it delegates to
  `/sms/send`), and `draft_and_send` as a pure read (the verb sends email).
  Roughly 44% of verbs contain no local write yet a majority of those still
  have effects, because handlers delegate to routers, services and
  `asyncio.to_thread`. So every entry here is a HUMAN judgment with a written
  reason, and a wrong entry is a security bug, not a lint failure.

THE TWO AXES
  `effect` answers "what kind of thing is this?"

    read   — returns information, changes nothing. The set an agent-facing
             read-only surface may expose.
    ui     — a client-side directive (navigate, open a panel, start a timer).
             Touches no business data and is MEANINGLESS off the app surface:
             these are excluded from any agent surface rather than exposed.
    write  — changes state. Carries a `reversibility` (below).

  `reversibility` answers "if this write was wrong, what then?" — the A/B/C
  model from extensibility_and_autonomy.md §2.4, applied only to writes:

    A — cleanly undoable. Records, drafts, soft-deletes, deactivations.
        A wrong one is an edit away from right. Auto-eligible.
    B — recall window. Leaves the system but not instantly (a delayed send).
        Auto-eligible only with an explicit granted scope.
    C — irreversible or money-touching. Hard deletes, sends, payments, GL
        posts, anything that leaves a compliance trail. PROPOSAL-ONLY,
        FOREVER. Not a tuning knob.

DEFAULT-DENY IS WHAT MAKES A PARTIAL REGISTRY SAFE
  80 of 128 verbs are still `UNCLASSIFIED` (S1.1 steps 3-4). Every accessor
  below returns the *refusing* answer for a verb it does not know: not
  exposable, not autonomy-eligible, reversibility None. So an unclassified
  verb behaves exactly like a class-C one until somebody rules on it, and
  this file is useful before it is complete. Never add a fallback that
  guesses — an unknown verb must stay unknown.

KEEPING IT HONEST
  `__tests__/test_action_registry.py` asserts the registry and
  `ACTION_HANDLERS` describe the same verb set. A verb added to Chief without
  a classification (or an UNCLASSIFIED note) fails there instead of silently
  defaulting to denied and quietly not working. Same discipline as
  `vertical_registry.KNOWN_GAPS` + `test_vertical_registry.py`.
"""
from __future__ import annotations

from typing import Dict, Optional, Set

# ── effect kinds ─────────────────────────────────────────────────────
READ = "read"
UI = "ui"
WRITE = "write"

EFFECTS = (READ, UI, WRITE)
REVERSIBILITY_CLASSES = ("A", "B", "C")


def _r(why: str) -> Dict[str, str]:
    return {"effect": READ, "why": why}


def _ui(why: str) -> Dict[str, str]:
    return {"effect": UI, "why": why}


def _w(rev: str, why: str) -> Dict[str, str]:
    return {"effect": WRITE, "reversibility": rev, "why": why}


# ─────────────────────────────────────────────────────────────────────
# REGISTRY — every entry verified against its handler, 2026-07-27.
# ─────────────────────────────────────────────────────────────────────

REGISTRY: Dict[str, Dict[str, str]] = {

    # ── reads ────────────────────────────────────────────────────────
    # Verified: each fetches and formats, and reaches nothing that writes.
    "catch_up":            _r("summarizes recent activity from reads only"),
    "check_goals":         _r("computes goal progress from business settings + live data"),
    "contact_deep_dive":   _r("assembles one contact's history"),
    "list_availability":   _r("reads the availability configuration"),
    "list_module_entries": _r("lists rows of a custom module"),
    "list_offerings":      _r("lists offerings"),
    "list_products":       _r("lists products"),
    "list_projects":       _r("lists projects"),
    "list_scheduled":      _r("reads queued chief_scheduled_actions"),
    "offering_readiness":  _r("offering_profiles.business_readiness — pure report"),
    "recall_conversation": _r("searches prior conversation"),
    "show_revenue":        _r("reads revenue figures"),
    "site_health":         _r("reads site + booking config and reports"),

    # ── UI directives ────────────────────────────────────────────────
    # Verified: pass-throughs the frontend acts on. No persistence.
    # Deliberately NOT exposable — an off-app caller has no UI to drive.
    "navigate":         _ui("tells the app which tab to open"),
    "open_calendar":    _ui("opens the calendar panel"),
    "open_documents":   _ui("opens the documents panel"),
    "set_chat_window":  _ui("opens/closes the chat window; voice keep-alive"),
    "set_timer":        _ui("returns timer metadata; timerManager runs it client-side"),

    # ── writes, class A ──────────────────────────────────────────────
    # The first 26 adopt chief_action_reasoner.SAFE_REMAP_ACTIONS, whose
    # own contract is "reversible + non-sending + non-financial". That is
    # a documented prior judgment; re-deriving it would only risk
    # disagreeing with the code that already relies on it.
    "create_contact":                _w("A", "creates an editable contact row"),
    "update_contact":                _w("A", "edits a contact; prior values re-enterable"),
    "update_contact_status":         _w("A", "sets a status field"),
    "create_note":                   _w("A", "creates a note"),
    "create_task":                   _w("A", "creates a task"),
    "complete_task":                 _w("A", "flips a task's done flag; re-openable"),
    "create_goal":                   _w("A", "creates a goal"),
    "add_reminder":                  _w("A", "creates a reminder"),
    "capture_idea":                  _w("A", "stores an idea"),
    "log_activity":                  _w("A", "appends an activity row"),
    "create_session":                _w("A", "inserts a /sessions row; verified to send nothing"),
    "update_session":                _w("A", "edits a session row"),
    "create_project":                _w("A", "creates a project"),
    "update_project":                _w("A", "edits a project"),
    "create_module_entry":           _w("A", "creates a module row"),
    "update_module_entry":           _w("A", "edits a module row"),
    "ensure_module":                 _w("A", "creates a module if absent"),
    "create_offering":               _w("A", "creates an offering"),
    "update_offering":               _w("A", "edits an offering"),
    "draft_email":                   _w("A", "queues a draft to /agent_queue — approval still required to send"),
    "draft_nurture":                 _w("A", "queues a check-in draft; not sent"),
    "set_business_policy":           _w("A", "records a policy value"),
    "add_faq":                       _w("A", "adds an FAQ entry"),
    "remember":                      _w("A", "writes a chief_memories row; deactivatable via forget"),
    "add_testimonial":               _w("A", "adds a testimonial"),
    "update_business_profile_field": _w("A", "sets one profile field"),

    # Verified individually beyond the adopted set.
    "forget":               _w("A", "deactivates a memory (is_active flip), does not delete"),
    "delete_module_entry":  _w("A", "SOFT delete — flips status to 'deleted', row survives"),
    "analyze_trends":       _w("A", "runs the insight engine now; writes insight memories + an "
                                    "activity row, both deactivatable. Note: invokes the model, "
                                    "so it is a spend vector on any metered surface"),

    # ── writes, class C ──────────────────────────────────────────────
    "delete_contact":       _w("C", "HARD delete — issues DELETE /contacts; `contacts` has no "
                                    "soft-delete column and no archive, so the row is gone. Now "
                                    "guarded: Chief refuses when anything is attached (sessions "
                                    "and academy_enrollments CASCADE, eight more tables orphan), "
                                    "so it can only reach a contact with no history. Stays C — "
                                    "the guard bounds the blast radius, it does not make the "
                                    "delete undoable"),
}


# ─────────────────────────────────────────────────────────────────────
# UNCLASSIFIED — known-pending, NOT unknown (S1.1 steps 3-4).
#
# Listed explicitly so the drift test can tell "we haven't ruled on this
# yet" apart from "somebody added a verb and skipped the decision". Every
# one behaves as denied until it moves into REGISTRY above.
#
# The entries carrying a specific note are the contested calls that need a
# ruling rather than an afternoon; the rest are simply not yet worked.
# ─────────────────────────────────────────────────────────────────────

_PENDING = "not yet classified"

UNCLASSIFIED: Dict[str, str] = {
    # --- contested: need a ruling, not just an audit ---
    "send_sms": "B or C? Telnyx sends immediately and there is no delayed-send "
                "outbox, so a recall window does not exist today. Recommend C "
                "until one does",
    "publish_post": "B or C? §2.4 offers 'unpublish' as a class-A example, but a "
                    "social post that was seen cannot be unseen. Recommend B",
    "create_invoice": "A or C? Creating is a record; sending is the money-facing "
                      "act. Recommend A here and C on send_invoice",
    "send_invoice": "C almost certainly — money-facing and leaves the system. "
                    "Paired with the create_invoice ruling",
    "mark_invoice_paid": "C almost certainly — has a ledger/GL effect",
    "run_agent": "meta-verb: dispatches other agents, so its class is whatever "
                 "they are. Recommend C, or exclude from the registry entirely "
                 "and classify what it dispatches",
    "generate_briefing": "delegates straight to run_agent('briefing') — inherits "
                         "whatever run_agent is ruled",
    "bulk_approve": "blast radius. Recommend: inherit the strictest class of what "
                    "it touches, and never autonomy-eligible regardless",
    "bulk_dismiss": "blast radius — same rule as bulk_approve",
    "batch_email": "blast radius over an outbound channel — same rule",
    "restore_previous_site": "its docstring claims fully reversible and symmetric, "
                             "which is plausible; unverified here because the "
                             "effect lives in site_composer.restore_previous_compose. "
                             "Adjacent to the canvas-overwrite incident class, so it "
                             "gets read before it gets classified",

    # --- not yet worked ---
    "accept_module_spec": _PENDING,
    "add_block_range": _PENDING,
    "add_voice_rule": _PENDING,
    "advance_phase": _PENDING,
    "approve_bookkeeping_proposal": _PENDING,
    "approve_draft": _PENDING,
    "archive_offering": _PENDING,
    "cancel_booking": _PENDING,
    "cancel_recurring_invoice": _PENDING,
    "cancel_scheduled": _PENDING,
    "complete_strategy_track": _PENDING,
    "contract_pdf": _PENDING,
    "create_booking": _PENDING,
    "create_course": _PENDING,
    "create_growth_objective": _PENDING,
    "create_product": _PENDING,
    "dismiss_draft": _PENDING,
    "draft_and_send": _PENDING,
    "draft_contract": _PENDING,
    "edit_draft": _PENDING,
    "enqueue_job": _PENDING,
    "enroll_student": _PENDING,
    "generate_insights": _PENDING,
    "generate_payment_link": _PENDING,
    "list_bookkeeping_proposals": _PENDING,
    "mark_reply_read": _PENDING,
    "mark_sms_read": _PENDING,
    "notify_practitioner": _PENDING,
    "plan_content": _PENDING,
    "propose_brand_kit_from_context": _PENDING,
    "propose_module_from_intake": _PENDING,
    "propose_voice_rule": _PENDING,
    "queue_build_request": _PENDING,
    "record_edit_pattern": _PENDING,
    "reject_bookkeeping_proposal": _PENDING,
    "reject_module_spec": _PENDING,
    "remove_block_range": _PENDING,
    "remove_testimonial": _PENDING,
    "remove_voice_rule": _PENDING,
    "reschedule_booking": _PENDING,
    "review_books": _PENDING,
    "rewrite_draft": _PENDING,
    "run_market_research": _PENDING,
    "save_business_model": _PENDING,
    "save_email_template": _PENDING,
    "save_launch_plan": _PENDING,
    "save_note": _PENDING,
    "save_packages": _PENDING,
    "save_phase": _PENDING,
    "save_pricing": _PENDING,
    "save_projections": _PENDING,
    "save_swot": _PENDING,
    "schedule_action": _PENDING,
    "send_report": _PENDING,
    "session_summary": _PENDING,
    "set_availability_day": _PENDING,
    "set_availability_override": _PENDING,
    "set_business_timezone": _PENDING,
    "set_lead_time": _PENDING,
    "set_site_capability": _PENDING,
    "set_slot_granularity": _PENDING,
    "setup_store": _PENDING,
    "update_contact_health": _PENDING,
    "update_practitioner_profile_field": _PENDING,
    "update_product": _PENDING,
    "update_voice_profile": _PENDING,
    "update_voice_sample": _PENDING,
    "update_voice_style": _PENDING,
    "upgrade_module_archetype": _PENDING,
}


# ─────────────────────────────────────────────────────────────────────
# Accessors. Every one denies on anything it does not know.
# ─────────────────────────────────────────────────────────────────────

def classification(verb: str) -> Optional[Dict[str, str]]:
    """The entry for `verb`, or None if unclassified/unknown. None is the
    honest answer, not an error — callers must treat it as denied."""
    return REGISTRY.get(verb)


def effect(verb: str) -> Optional[str]:
    """'read' | 'ui' | 'write', or None when unknown."""
    entry = REGISTRY.get(verb)
    return entry["effect"] if entry else None


def reversibility(verb: str) -> Optional[str]:
    """'A' | 'B' | 'C' for a classified write; None for reads, UI verbs,
    and anything unclassified."""
    entry = REGISTRY.get(verb)
    if not entry or entry["effect"] != WRITE:
        return None
    return entry.get("reversibility")


def is_read_only(verb: str) -> bool:
    """True only for a verb VERIFIED to change nothing. The gate for any
    read-only agent surface. Unknown → False."""
    return effect(verb) == READ


def may_expose_to_agent(verb: str, allow_writes: bool = False) -> bool:
    """May an outside agent call this verb?

    Default (`allow_writes=False`) is the read-mostly posture: reads only.
    UI verbs are never exposed — an off-app caller has no UI to drive, so
    exposing them would be noise at best. With `allow_writes=True` a
    granted-scope surface may additionally reach class A and B writes;
    class C never qualifies, and neither does anything unclassified."""
    kind = effect(verb)
    if kind == READ:
        return True
    if kind == WRITE and allow_writes:
        return reversibility(verb) in ("A", "B")
    return False


def is_autonomy_eligible(verb: str, granted_scope: bool = False) -> bool:
    """May Chief perform this without asking first?

    Class A yes. Class B only with an explicit granted scope. Class C never
    — that is the §2.4 rule and not a knob. Reads are not 'actions' in the
    autonomy sense and answer False; so does everything unclassified."""
    rev = reversibility(verb)
    if rev == "A":
        return True
    if rev == "B":
        return bool(granted_scope)
    return False


def classified_verbs() -> Set[str]:
    return set(REGISTRY)


def unclassified_verbs() -> Set[str]:
    return set(UNCLASSIFIED)


def known_verbs() -> Set[str]:
    """Every verb this module accounts for, classified or explicitly pending.
    The drift test compares this against ACTION_HANDLERS."""
    return set(REGISTRY) | set(UNCLASSIFIED)


def coverage() -> Dict[str, int]:
    """Progress, for the S1.1 build-out and for Mission Control if it ever
    wants to show it."""
    by_class = {"read": 0, "ui": 0, "A": 0, "B": 0, "C": 0}
    for entry in REGISTRY.values():
        if entry["effect"] == WRITE:
            by_class[entry.get("reversibility", "?")] += 1
        else:
            by_class[entry["effect"]] += 1
    return {
        "classified": len(REGISTRY),
        "unclassified": len(UNCLASSIFIED),
        "total": len(REGISTRY) + len(UNCLASSIFIED),
        **by_class,
    }
