"""
rules_engine.py — Arc 20 Phase B Part 2/4 — Tier 1 visual rule builder
(closed grammar) + the rule→proposal convergence.

THE GRAMMAR (closed by construction — no practitioner code ever executes):
    WHEN  <trigger from TRIGGERS>            (catalog, not free-form)
    IF    <conditions over the event payload> (fixed operator set)
    THEN  <1-3 actions from VERBS>            (allow-list; params validated)

Direct verbs are reversibility-class A (annotations, tasks, notifications)
or B (template email). Anything heavier is a PROPOSAL verb — it lands in
chief_proposals and waits for the practitioner, exactly like Chief's own
suggestions (the Phase A convergence: a rule's "ask me first" IS a Chief
proposal; same approval flow, same audit, same learning signals).

SAFETY RAILS:
  - Cross-business access unrepresentable: execution context closes over
    the rule row's business_id; no verb takes a business parameter.
  - Loop protection: events carry _provenance {origin_rule, depth}; an
    event caused by rule R never re-triggers R, and chains cap at depth 3.
  - Kill switches: RULES_ENGINE env (platform) > settings.automations_paused
    (business) > per-rule enabled flag.
  - Every run logged to rule_runs (trigger snapshot + condition trace +
    action results) — the trust-layer "why did this happen" answer.
  - Fail-soft everywhere: a broken rule logs and skips; it never breaks
    the business event that triggered it.

METERING (Arc 19 ruling): Tier 1 is free at all tiers; v1 verbs are
deterministic (zero LLM calls). Any future rule verb that invokes Claude
must log api_usage with task_type="rule_engine" so it meters as weighted
Chief interactions under the 2× cap.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import sb_clients

logger = logging.getLogger("rules_engine")

MAX_CHAIN_DEPTH = 3
MAX_ACTIONS_PER_RULE = 3
MAX_RULES_PER_BUSINESS = 50

# ─── Trigger catalog (v1 — additive; UI is data-driven off /rules/catalog) ─

TRIGGERS: Dict[str, Dict[str, Any]] = {
    "booking_created": {
        "label": "A new booking is made",
        "fields": ["contact_name", "contact_email", "offering", "starts_at", "notes"],
    },
    "contact_created": {
        "label": "A new contact is added",
        "fields": ["name", "email", "phone", "source", "notes"],
    },
    "invoice_overdue": {
        "label": "An invoice becomes overdue",
        "config": {"days_overdue": {"type": "number", "default": 7, "min": 1, "max": 90}},
        "fields": ["invoice_number", "total", "due_date", "days_overdue",
                   "contact_name", "contact_email"],
    },
}

CONDITION_OPS = ("equals", "not_equals", "contains", "not_contains",
                 "greater_than", "less_than", "is_empty", "is_not_empty")

# ─── Verb allow-list (v1) ────────────────────────────────────────────
# kind: direct (executes now) | proposal (lands in chief_proposals).

VERBS: Dict[str, Dict[str, Any]] = {
    "notify_practitioner": {
        "kind": "direct", "reversibility": "A",
        "label": "Notify me",
        "params": {"message": {"type": "template", "required": True}},
    },
    "apply_tag": {
        "kind": "direct", "reversibility": "A",
        "label": "Tag the contact",
        "params": {"tag": {"type": "string", "required": True, "max": 40}},
    },
    "create_task": {
        "kind": "direct", "reversibility": "A",
        "label": "Create a task for me",
        "params": {"title": {"type": "template", "required": True},
                   "due_in_days": {"type": "number", "default": 1, "min": 0, "max": 90}},
    },
    "send_template_email": {
        "kind": "direct", "reversibility": "B",
        "label": "Send a template email to the contact",
        "params": {"subject": {"type": "template", "required": True},
                   "body": {"type": "template", "required": True}},
    },
    "propose_followup_email": {
        "kind": "proposal", "proposal_type": "propose_followup_email",
        "label": "Draft a follow-up email for my approval",
        "params": {"subject": {"type": "template", "required": True},
                   "body": {"type": "template", "required": True}},
    },
    "propose_task": {
        "kind": "proposal", "proposal_type": "propose_task",
        "label": "Suggest a task for my approval",
        "params": {"title": {"type": "template", "required": True},
                   "due_in_days": {"type": "number", "default": 1, "min": 0, "max": 90}},
    },
    "propose_contact_tag": {
        "kind": "proposal", "proposal_type": "propose_contact_tag",
        "label": "Suggest tagging the contact",
        "params": {"tag": {"type": "string", "required": True, "max": 40}},
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def engine_enabled() -> bool:
    return (os.environ.get("RULES_ENGINE") or "on").lower() != "off"


def business_paused(biz_row: Optional[Dict[str, Any]]) -> bool:
    return bool(((biz_row or {}).get("settings") or {}).get("automations_paused"))


# ─── Validation (closed grammar enforced at save) ────────────────────

def validate_rule(rule: Dict[str, Any]) -> List[str]:
    """Returns a list of human-readable problems; empty = valid."""
    errs: List[str] = []
    if not (rule.get("name") or "").strip():
        errs.append("Give the rule a name.")
    if not (rule.get("rationale") or "").strip():
        errs.append("Say what this automation is for (one sentence) — it's the audit answer.")
    if rule.get("trigger_type") not in TRIGGERS:
        errs.append(f"Unknown trigger '{rule.get('trigger_type')}'.")
    conds = rule.get("conditions") or []
    if not isinstance(conds, list) or len(conds) > 5:
        errs.append("Conditions must be a list of at most 5.")
    else:
        for c in conds:
            if not isinstance(c, dict) or c.get("op") not in CONDITION_OPS:
                errs.append(f"Unknown condition operator '{(c or {}).get('op')}'.")
            if not (c or {}).get("field"):
                errs.append("Every condition needs a field.")
    actions = rule.get("actions") or []
    if not isinstance(actions, list) or not (1 <= len(actions) <= MAX_ACTIONS_PER_RULE):
        errs.append(f"Use 1-{MAX_ACTIONS_PER_RULE} actions.")
    else:
        for a in actions:
            verb = (a or {}).get("verb")
            spec = VERBS.get(verb)
            if not spec:
                errs.append(f"Unknown action '{verb}'.")
                continue
            params = (a or {}).get("params") or {}
            for pname, pspec in spec["params"].items():
                if pspec.get("required") and not str(params.get(pname) or "").strip():
                    errs.append(f"Action '{verb}' needs '{pname}'.")
                if pspec.get("max") and isinstance(params.get(pname), str) \
                        and len(params[pname]) > pspec["max"]:
                    errs.append(f"'{pname}' is too long (max {pspec['max']}).")
            for pname in params:
                if pname not in spec["params"]:
                    errs.append(f"Action '{verb}' has unknown parameter '{pname}'.")
    return errs


# ─── Condition evaluation + template interpolation (data-only) ───────

def _conditions_match(conditions: List[Dict[str, Any]],
                      payload: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
    trace: List[Dict[str, Any]] = []
    for c in conditions or []:
        field, op = c.get("field"), c.get("op")
        expect = c.get("value")
        actual = payload.get(field)
        a_s = "" if actual is None else str(actual)
        e_s = "" if expect is None else str(expect)
        if op == "equals":
            ok = a_s.strip().lower() == e_s.strip().lower()
        elif op == "not_equals":
            ok = a_s.strip().lower() != e_s.strip().lower()
        elif op == "contains":
            ok = e_s.strip().lower() in a_s.lower()
        elif op == "not_contains":
            ok = e_s.strip().lower() not in a_s.lower()
        elif op == "greater_than":
            try: ok = float(actual) > float(expect)
            except Exception: ok = False
        elif op == "less_than":
            try: ok = float(actual) < float(expect)
            except Exception: ok = False
        elif op == "is_empty":
            ok = not a_s.strip()
        elif op == "is_not_empty":
            ok = bool(a_s.strip())
        else:
            ok = False
        trace.append({"field": field, "op": op, "value": expect,
                      "actual": (a_s[:120] or None), "matched": ok})
        if not ok:
            return False, trace
    return True, trace


_TPL_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _interpolate(template: str, payload: Dict[str, Any]) -> str:
    """Data-only {{field}} substitution. NO expressions, NO code — the
    closed-grammar line that keeps Tier 1 categorically safe."""
    def sub(m):
        v = payload.get(m.group(1))
        return "" if v is None else str(v)[:300]
    return _TPL_RE.sub(sub, template or "")[:2000]


# ─── Executors (each closes over ONE business_id) ────────────────────

def _exec_notify(biz_id: str, params: Dict, payload: Dict) -> Dict[str, Any]:
    sb_clients.sb_post_as_service("/chief_notifications", {
        "business_id": biz_id,
        "type": "rule_notification",
        "title": "Automation",
        "body": _interpolate(params.get("message", ""), payload),
        "priority": "medium",
        "created_at": _now_iso(),
    }, prefer=None)
    return {"ok": True}


def _exec_apply_tag(biz_id: str, params: Dict, payload: Dict) -> Dict[str, Any]:
    cid = payload.get("contact_id")
    if not cid:
        return {"ok": False, "error": "event has no contact"}
    rows = sb_clients.sb_get_as_service(
        f"/contacts?id=eq.{cid}&business_id=eq.{biz_id}&select=id,tags&limit=1") or []
    if not rows:
        return {"ok": False, "error": "contact not found in this business"}
    tags = list(rows[0].get("tags") or [])
    tag = str(params.get("tag") or "").strip()[:40]
    if tag and tag not in tags:
        tags.append(tag)
        sb_clients.sb_patch_as_service(
            f"/contacts?id=eq.{cid}&business_id=eq.{biz_id}", {"tags": tags})
    return {"ok": True, "tag": tag}


def _exec_create_task(biz_id: str, params: Dict, payload: Dict) -> Dict[str, Any]:
    due_days = int(params.get("due_in_days") or 1)
    due = (datetime.now(timezone.utc) + timedelta(days=max(0, min(90, due_days)))).date()
    sb_clients.sb_post_as_service("/tasks", {
        "business_id": biz_id,
        "title": _interpolate(params.get("title", ""), payload)[:200],
        "priority": "medium",
        "due_date": due.isoformat(),
        "source": "rule_engine",
        "created_at": _now_iso(),
    }, prefer=None)
    return {"ok": True, "due_date": due.isoformat()}


def _exec_send_template_email(biz_id: str, params: Dict, payload: Dict) -> Dict[str, Any]:
    to_email = (payload.get("contact_email") or "").strip()
    if not to_email or "@" not in to_email:
        return {"ok": False, "error": "event has no contact email"}
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz_id}&select=name&limit=1") or []
    biz_name = (rows[0].get("name") if rows else None) or "Your practitioner"
    try:
        import asyncio
        from email_sender import send_via_resend
        coro = send_via_resend(
            to_email=to_email, to_name=payload.get("contact_name"),
            from_email="hello@mysolutionist.app", from_name=biz_name,
            reply_to=None,
            subject=_interpolate(params.get("subject", ""), payload)[:200],
            body=_interpolate(params.get("body", ""), payload))
        try:
            asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            asyncio.run(coro)
        return {"ok": True, "to": to_email}
    except Exception as e:
        return {"ok": False, "error": f"email failed: {e}"}


def _exec_proposal(biz_id: str, rule: Dict, verb_spec: Dict,
                   params: Dict, payload: Dict) -> Dict[str, Any]:
    """The convergence: a rule's ask-me-first action IS a Chief proposal —
    same table, same approval flow, same learning capture (chief_proposals)."""
    proposed = {k: (_interpolate(v, payload) if isinstance(v, str) else v)
                for k, v in (params or {}).items()}
    if payload.get("contact_id"):
        proposed["contact_id"] = payload["contact_id"]
    if payload.get("contact_email"):
        proposed["contact_email"] = payload["contact_email"]
    if payload.get("contact_name"):
        proposed["contact_name"] = payload["contact_name"]
    res = sb_clients.sb_post_as_service("/chief_proposals", {
        "business_id": biz_id,
        "proposal_type": verb_spec["proposal_type"],
        "source": f"rule:{rule.get('id')}",
        "proposed": proposed,
        "confidence": 1.0,   # rules are deterministic; the practitioner wrote them
        "reasoning": f"Your automation \"{(rule.get('name') or '')[:80]}\" "
                     f"triggered: {(rule.get('rationale') or '')[:200]}",
        "status": "pending",
        "created_at": _now_iso(),
    })
    row = (res or [None])[0] if isinstance(res, list) else res
    # Chief-in-your-pocket - an ask-me-first action reaches the
    # practitioner's pocket the moment it's created. Guarded no-op when
    # VAPID keys are unset or the import is unavailable (tests).
    if row:
        try:
            import push_notifications as _push
            _push.send_to_business(
                biz_id,
                title="Chief needs a yes ✦",
                body=(f"Your automation \"{(rule.get('name') or 'rule')[:60]}\" "
                      f"proposed: {verb_spec['proposal_type'].replace('_', ' ')}."),
                nav="operate:queue",
                tag=f"proposal-{(row or {}).get('id')}",
            )
        except Exception:
            pass
    return {"ok": bool(row), "proposal_id": (row or {}).get("id")}


_DIRECT_EXECUTORS = {
    "notify_practitioner": _exec_notify,
    "apply_tag": _exec_apply_tag,
    "create_task": _exec_create_task,
    "send_template_email": _exec_send_template_email,
}


# ─── The event entry point ───────────────────────────────────────────

def on_event(business_id: str, event_type: str, payload: Dict[str, Any],
             _provenance: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Evaluate every enabled rule for (business, event). Fail-soft: this
    is called from live business flows (booking creation etc.) and must
    NEVER break them. Returns run summaries (for tests/telemetry)."""
    try:
        if not engine_enabled() or event_type not in TRIGGERS:
            return []
        depth = int((_provenance or {}).get("depth") or 0)
        if depth >= MAX_CHAIN_DEPTH:
            logger.warning(f"[rules] chain depth cap hit for {business_id}/{event_type}")
            return []
        biz_rows = sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{business_id}&select=id,settings&limit=1") or []
        if not biz_rows or business_paused(biz_rows[0]):
            return []
        rules = sb_clients.sb_get_as_service(
            f"/practitioner_rules?business_id=eq.{business_id}"
            f"&enabled=is.true&trigger_type=eq.{event_type}"
            f"&select=*&limit={MAX_RULES_PER_BUSINESS}") or []
        out: List[Dict[str, Any]] = []
        origin_rule = (_provenance or {}).get("origin_rule")
        for rule in rules:
            if origin_rule and str(rule.get("id")) == str(origin_rule):
                continue  # a rule never re-triggers itself through its own effects
            out.append(_run_rule(business_id, rule, event_type, payload, depth))
        return out
    except Exception as e:
        logger.warning(f"[rules] on_event failed soft for {business_id}/{event_type}: {e}")
        return []


def _run_rule(biz_id: str, rule: Dict[str, Any], event_type: str,
              payload: Dict[str, Any], depth: int) -> Dict[str, Any]:
    matched, trace = _conditions_match(rule.get("conditions") or [], payload)
    results: List[Dict[str, Any]] = []
    status = "skipped_conditions"
    if matched:
        status = "executed"
        for a in (rule.get("actions") or [])[:MAX_ACTIONS_PER_RULE]:
            verb = (a or {}).get("verb")
            spec = VERBS.get(verb)
            try:
                if not spec:
                    results.append({"verb": verb, "ok": False, "error": "unknown verb"})
                elif spec["kind"] == "proposal":
                    results.append({"verb": verb,
                                    **_exec_proposal(biz_id, rule, spec,
                                                     a.get("params") or {}, payload)})
                else:
                    results.append({"verb": verb,
                                    **_DIRECT_EXECUTORS[verb](biz_id,
                                                              a.get("params") or {},
                                                              payload)})
            except Exception as e:
                results.append({"verb": verb, "ok": False, "error": str(e)[:200]})
        if any(not r.get("ok", True) for r in results):
            status = "executed_with_errors"
    try:
        sb_clients.sb_post_as_service("/rule_runs", {
            "business_id": biz_id, "rule_id": rule.get("id"),
            "rule_version": rule.get("version") or 1,
            "event_type": event_type,
            "event": {k: (str(v)[:300] if v is not None else None)
                      for k, v in (payload or {}).items() if not k.startswith("_")},
            "condition_trace": trace, "results": results,
            "status": status, "chain_depth": depth,
            "created_at": _now_iso(),
        }, prefer=None)
    except Exception as e:
        logger.warning(f"[rules] run log failed: {e}")
    return {"rule_id": rule.get("id"), "status": status, "results": results}


# ─── invoice_overdue daily tick ──────────────────────────────────────

async def overdue_tick() -> None:
    """Daily: fire invoice_overdue events for invoices crossing each rule's
    configured days_overdue today (exactly-once via the day-window check)."""
    try:
        if not engine_enabled():
            return
        rules = sb_clients.sb_get_as_service(
            "/practitioner_rules?enabled=is.true&trigger_type=eq.invoice_overdue"
            "&select=*&limit=500") or []
        today = datetime.now(timezone.utc).date()
        for rule in rules:
            days = int(((rule.get("trigger_config") or {}).get("days_overdue")) or 7)
            target_due = (today - timedelta(days=days)).isoformat()
            biz = rule["business_id"]
            invoices = sb_clients.sb_get_as_service(
                f"/invoices?business_id=eq.{biz}&paid_at=is.null"
                f"&status=in.(sent,viewed,overdue)&due_date=eq.{target_due}"
                f"&select=id,invoice_number,total,due_date,contact_id,"
                f"contacts(name,email)&limit=200") or []
            for inv in invoices:
                c = (inv.get("contacts") or {}) or {}
                on_event(biz, "invoice_overdue", {
                    "invoice_id": inv.get("id"),
                    "invoice_number": inv.get("invoice_number"),
                    "total": inv.get("total"),
                    "due_date": inv.get("due_date"),
                    "days_overdue": days,
                    "contact_id": inv.get("contact_id"),
                    "contact_name": c.get("name"),
                    "contact_email": c.get("email"),
                })
    except Exception as e:
        logger.warning(f"[rules] overdue tick failed: {e}")
