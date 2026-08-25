"""
policy_engine.py — THE ACTION LEDGER, Stage 3.

One evaluator that answers, before an action runs: *is this actor allowed
to do this, for this business, right now — and under which rule?* The
answer becomes the ledger's sixth field (audit_log.authorized_by), which
is the difference between "Chief did this" and "Chief was permitted to do
this, here is the rule."

WHAT THIS REPLACES. The 8/03 audit found authorization scattered across
six mutually unaware subsystems with no chokepoint. For a single Chief
create_invoice the decision was made in five unrelated places across
three layers, and no two shared a vocabulary: the plan gate knew the plan
but not the verb; tenancy was expressed as a 404 from an empty result set
rather than a verdict; the class-C gate knew the verb but not the caller;
Postgres RLS knew the seat role but could only communicate by succeeding
or failing an insert; and the audit row saw none of it. Four verdict
strings already existed and were all discarded.

WHAT THIS DELIBERATELY DOES NOT DO. It is not a new gate that silently
changes what the product allows. Every existing block stays exactly as it
was, and the engine BLOCKS only four things:

  1. verbs the action registry does not classify (drift fails closed,
     matching _gate_class_c),
  2. bulk verbs running unattended (the registry's own standing rule,
     which the scheduler and workflow paths were quietly violating),
  3. client-facing actions running unattended for a REGULATED vertical
     whose owner never enabled that (see below),
  4. ANY unattended action for a business whose practitioner has paused
     automations (see is_paused — the switch that four of the five paths
     that act have never read).

Everything else is RECORDED, not refused — including class-C verbs on a
recurrence. Recurring invoices are a real feature; whether they should
keep firing unattended is Kevin's product ruling, and the ledger's job is
to make it visible rather than to decide it in a helper.

THE PROMISE THIS KEEPS. launch_access seeds
settings.autonomy.client_facing_autonomy = "disabled" for law / therapy /
counselling businesses at creation, with disabled_reason
"regulated_vertical_default". Nothing in the codebase has ever read it.
A therapist's account has been carrying a setting that says Chief may not
contact clients on its own, while Chief could do exactly that through the
autopilot sweep. This module is the first reader.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

import sb_clients

logger = logging.getLogger("policy_engine")

# Actions that REACH THE CLIENT — a message, a booking on their calendar,
# a bill, or something published where the public can see it.
#
# Curated by hand from action_registry's written reasons, deliberately.
# The registry's own load-bearing lesson is that this classification
# cannot be automated: a detector keyed on "does the handler POST" reports
# send_sms as read-only because it delegates. Every entry below was read.
#
# Not included, on purpose: create_invoice (creating a bill is a
# bookkeeping act — SENDING it is send_invoice, which is here) and
# generate_payment_link (creates an object; delivering it is a separate
# verb). Over-blocking a therapist's bookkeeping would teach them to
# switch the protection off.
CLIENT_FACING = frozenset({
    "approve_draft",              # approves AND sends
    "bulk_approve",               # approves and sends every match
    "batch_email",
    "draft_and_send",
    "send_sms",
    "send_report",
    "send_invoice",
    "create_booking",             # emails the client a confirmation
    "create_recurring_booking",   # writes a series onto a client's calendar
    "cancel_recurring_booking",   # removes appointments a client is holding
    "publish_post",               # public, via Meta
    "launch_campaign",            # arms sends to a whole audience
    "send_purchase_order",        # emails the supplier — leaves the app
})

_REGULATED_HINTS = ("law", "therap", "counsel")


@dataclass(frozen=True)
class Verdict:
    """The answer, plus the rule that produced it.

    `rule` is what lands in audit_log.authorized_by. It is a stable,
    greppable string — never a sentence — because it has to survive being
    queried a year from now. `reason` is the human sentence.
    """
    allowed: bool
    rule: str
    reason: str
    role: Optional[str] = None
    required_role: Optional[str] = None

    def as_error(self) -> Dict[str, Any]:
        """The refusal payload, shaped like the billing gates' 402s so the
        frontend has one thing to recognise."""
        return {"error": "policy_denied", "rule": self.rule,
                "message": self.reason, "required_role": self.required_role}


def _biz(business_id: str, biz_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    # A row without `type` and `settings` cannot answer the two
    # questions this module asks of it. Trusting a stub made a regulated
    # practice read as unregulated and quietly re-enabled unattended
    # client contact — re-fetch instead.
    if (isinstance(biz_row, dict) and biz_row.get("id")
            and "type" in biz_row and "settings" in biz_row):
        return biz_row
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=id,type,owner_id,settings&limit=1") or []
    return rows[0] if rows else {}


def is_regulated(biz: Dict[str, Any]) -> bool:
    return any(h in str(biz.get("type") or "").lower() for h in _REGULATED_HINTS)


def client_facing_autonomy(biz: Dict[str, Any]) -> str:
    """'enabled' | 'disabled'. Regulated verticals default to disabled even
    when the settings block is missing — a therapist created before the
    seeding shipped must not be less protected than one created after."""
    autonomy = ((biz.get("settings") or {}).get("autonomy") or {})
    raw = str(autonomy.get("client_facing_autonomy") or "").strip().lower()
    if raw in ("enabled", "disabled"):
        return raw
    return "disabled" if is_regulated(biz) else "enabled"


def is_paused(biz: Dict[str, Any]) -> bool:
    """Has the practitioner switched their own automations off?

    settings.automations_paused has existed since the rules arc and was
    read by exactly two call sites — rules_engine's trigger loop and the
    trusted-autonomy sweep. The scheduler, the workflow runner and the
    autopilot sweep never consulted it, so a practitioner who paused
    automations still had Chief executing scheduled actions, advancing
    workflows and sending auto-approved email. A switch that stops one
    automation in five is worse than no switch at all, because the person
    who flipped it believes they have stopped.

    Delegates to rules_engine, which has owned this predicate from the
    start — re-reading the same setting here is precisely the drift this
    module exists to end. Lazy import: rules_engine is heavy and this is
    on the hot path of every write.

    The fallback reads the flag off the row we are already holding rather
    than defaulting either way. Guessing "paused" on an import error
    would stop the platform; guessing "running" would silently discard
    the practitioner's instruction. Reading the row does neither.
    """
    try:
        from rules_engine import business_paused
        return bool(business_paused(biz))
    except Exception as e:
        logger.warning(f"[policy] pause predicate unavailable, reading directly: {e}")
        return bool(((biz or {}).get("settings") or {}).get("automations_paused"))


def role_of(business_id: str, user_id: Optional[str]) -> Optional[str]:
    """Best-effort seat role. Never raises: the engine records what it
    knows, and an unavailable role must not take an action down."""
    if not user_id:
        return None
    try:
        from business_users_router import role_of as _role_of
        return _role_of(business_id, str(user_id))
    except Exception as e:
        logger.warning(f"[policy] role lookup failed: {e}")
        return None


def evaluate(business_id: str, *, verb: str, surface: str,
             prompted: bool, user_id: Optional[str] = None,
             biz_row: Optional[Dict[str, Any]] = None) -> Verdict:
    """Evaluate one action.

    surface  — where it came from: chat | scheduler | workflow |
               notification | autopilot | trust-track | agent.
    prompted — did a human ask for THIS action, now? True on the chat and
               notification paths by construction; False for anything a
               sweep, schedule, or workflow decided on its own. There is
               no runtime flag for this anywhere in the codebase; it is a
               property of the call path, so callers state it.
    """
    if not business_id or not verb:
        return Verdict(False, "policy:invalid", "Missing business or verb.")

    role = role_of(business_id, user_id)

    try:
        import action_registry
        cls = action_registry.classification(verb)
    except Exception as e:
        logger.warning(f"[policy] registry unavailable for {verb}: {e}")
        return Verdict(False, "registry:unavailable",
                       "The action safety registry is unavailable.", role)

    # Drift fails closed — the same posture _gate_class_c already takes.
    if not cls:
        return Verdict(False, "registry:unclassified",
                       f"{verb} is not in the action registry.", role)

    effect = cls.get("effect")
    rev = cls.get("reversibility")
    bulk = bool(cls.get("bulk"))

    if effect in ("read", "ui"):
        return Verdict(True, f"{surface}:{effect}", "Read-only action.", role)

    # The business row is resolved BEFORE the unattended rules now, because
    # the pause check below needs it. Reads still return above without ever
    # touching the database, which is what kept this cheap.
    biz = _biz(business_id, biz_row)

    # THE PAUSE SWITCH, finally read on every path that acts.
    #
    # Checked here rather than at five call sites so that the sixth
    # unattended path — whatever it turns out to be — inherits it without
    # anyone remembering to add it. That is the same argument the bulk
    # rule lost on the scheduler and workflow paths before Stage 0.
    #
    # FIRST among the unattended rules, so the refusal names the reason
    # the practitioner will recognise. "You paused automations" is an
    # answer they can act on; "bulk verbs cannot run unattended" is a true
    # sentence about a state they already turned off.
    #
    # Prompted actions are deliberately untouched: pausing automations
    # pauses what runs on its own, not what the practitioner asks for by
    # hand. Someone who pauses their automations and then tells Chief to
    # send an invoice has not contradicted themselves.
    if not prompted and is_paused(biz):
        return Verdict(False, "business:automations_paused",
                       "Automations are paused for this business, so this "
                       "did not run. Turn them back on in Settings, or do "
                       "it yourself and it will go through.", role)

    # Bulk is never autonomy-eligible at any class — the registry's rule,
    # unenforced on the scheduler and workflow paths until Stage 0/1b.
    if bulk and not prompted:
        return Verdict(False, "bulk:never-unattended",
                       f"{verb} affects many records at once and cannot run "
                       "unattended. Open the screen and confirm the list.",
                       role)

    # THE PROMISE. A regulated business whose owner has not enabled
    # client-facing autonomy does not get Chief contacting clients on its
    # own. Prompted actions are untouched: the practitioner asking IS the
    # authorisation, and this must never block them doing their job.
    if verb in CLIENT_FACING and not prompted:
        if client_facing_autonomy(biz) == "disabled":
            return Verdict(
                False, "vertical:client_facing_disabled",
                f"{verb} reaches a client, and unattended client contact is "
                "turned off for this practice. Approve it yourself, or "
                "enable client-facing autonomy in Settings.",
                role)

    # Class C unattended is RECORDED, not refused. Recurring invoices are
    # a real feature; making the exposure visible is this stage's job,
    # deciding it is Kevin's.
    if rev == "C" and not prompted:
        return Verdict(True, f"{surface}:C:unattended",
                       f"{verb} is irreversible and ran without a prompt.",
                       role)

    # The rule string names RULES THAT RAN — nothing else. It used to
    # carry the seat role ("chat:viewer:B"), which reads in an auditor's
    # report as "permitted under the viewer rule" — except no role check
    # was ever evaluated; RLS remains the only gate. Putting an
    # unenforced role there stated something false inside an
    # append-only, uncorrectable record. The role is still resolved and
    # returned on the Verdict for the day it becomes load-bearing.
    return Verdict(True, f"{surface}:{rev or effect}", "Allowed.", role)
