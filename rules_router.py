"""
rules_router.py — Arc 20 Phase B — Tier 1 rule builder API + generic
Chief proposals (list/approve/reject across BOTH proposal tables).

Owner-gated. The catalog endpoint makes the visual builder data-driven —
adding a trigger or verb server-side lights up in the UI with no
frontend change.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
import rules_engine
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("rules_router")

router = APIRouter(prefix="/rules", tags=["rules"])
proposals_router = APIRouter(prefix="/chief-proposals", tags=["chief_proposals"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id,settings&limit=1") or []
    if not rows or str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not your business")
    return rows[0]


# ─── Catalog (drives the visual builder) ─────────────────────────────

@router.get("/catalog")
def catalog(user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    return {
        "ok": True,
        "triggers": [{"key": k, "label": v["label"],
                      "fields": v.get("fields") or [],
                      "config": v.get("config") or {}}
                     for k, v in rules_engine.TRIGGERS.items()],
        "condition_ops": list(rules_engine.CONDITION_OPS),
        "verbs": [{"key": k, "label": v["label"], "kind": v["kind"],
                   "params": {p: {kk: vv for kk, vv in ps.items()}
                              for p, ps in v["params"].items()}}
                  for k, v in rules_engine.VERBS.items()],
        "limits": {"max_actions": rules_engine.MAX_ACTIONS_PER_RULE,
                   "max_rules": rules_engine.MAX_RULES_PER_BUSINESS},
    }


# ─── Rules CRUD ──────────────────────────────────────────────────────

class RuleBody(BaseModel):
    name: str
    rationale: str
    trigger_type: str
    trigger_config: Dict[str, Any] = {}
    conditions: List[Dict[str, Any]] = []
    actions: List[Dict[str, Any]] = []
    enabled: bool = True


@router.get("")
def list_rules(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/practitioner_rules?business_id=eq.{biz}&order=created_at.desc&select=*") or []
    paused = rules_engine.business_paused(
        (sb_clients.sb_get_as_service(
            f"/businesses?id=eq.{biz}&select=settings&limit=1") or [{}])[0])
    return {"ok": True, "rules": rows, "automations_paused": paused,
            "engine_enabled": rules_engine.engine_enabled()}


@router.post("")
def create_rule(biz: str, body: RuleBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rule = body.model_dump()
    errs = rules_engine.validate_rule(rule)
    if errs:
        raise HTTPException(400, {"error": "invalid_rule", "problems": errs})
    existing = sb_clients.sb_get_as_service(
        f"/practitioner_rules?business_id=eq.{biz}&select=id&limit=100") or []
    if len(existing) >= rules_engine.MAX_RULES_PER_BUSINESS:
        raise HTTPException(409, f"rule limit reached ({rules_engine.MAX_RULES_PER_BUSINESS})")
    res = sb_clients.sb_post_as_service("/practitioner_rules", {
        "business_id": biz, **rule, "created_by": str(user.id),
        "created_at": _now_iso(), "updated_at": _now_iso()})
    row = (res or [None])[0] if isinstance(res, list) else res
    return {"ok": True, "rule": row}


@router.patch("/{rule_id}")
def update_rule(rule_id: str, biz: str, body: RuleBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rule = body.model_dump()
    errs = rules_engine.validate_rule(rule)
    if errs:
        raise HTTPException(400, {"error": "invalid_rule", "problems": errs})
    cur = sb_clients.sb_get_as_service(
        f"/practitioner_rules?id=eq.{rule_id}&business_id=eq.{biz}&select=version&limit=1") or []
    if not cur:
        raise HTTPException(404, "rule not found")
    sb_clients.sb_patch_as_service(
        f"/practitioner_rules?id=eq.{rule_id}&business_id=eq.{biz}",
        {**rule, "version": int(cur[0].get("version") or 1) + 1,
         "updated_at": _now_iso()})
    return {"ok": True}


@router.post("/{rule_id}/toggle")
def toggle_rule(rule_id: str, biz: str, enabled: bool,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    sb_clients.sb_patch_as_service(
        f"/practitioner_rules?id=eq.{rule_id}&business_id=eq.{biz}",
        {"enabled": bool(enabled), "updated_at": _now_iso()})
    return {"ok": True, "enabled": bool(enabled)}


@router.delete("/{rule_id}")
def delete_rule(rule_id: str, biz: str,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    sb_clients.sb_delete_as_service(
        f"/practitioner_rules?id=eq.{rule_id}&business_id=eq.{biz}")
    return {"ok": True}


@router.post("/pause-all")
def pause_all(biz: str, paused: bool,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The business-level kill switch."""
    biz_row = _owner(biz, user)
    settings = dict(biz_row.get("settings") or {})
    settings["automations_paused"] = bool(paused)
    sb_clients.sb_patch_as_service(f"/businesses?id=eq.{biz}", {"settings": settings})
    return {"ok": True, "automations_paused": bool(paused)}


class TestBody(BaseModel):
    rule: Dict[str, Any]
    sample_event: Dict[str, Any] = {}


@router.post("/test")
def dry_run(biz: str, body: TestBody,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Dry-run: validate + evaluate conditions against a sample payload.
    NO actions execute — pure preview."""
    _owner(biz, user)
    errs = rules_engine.validate_rule(body.rule)
    if errs:
        return {"ok": True, "valid": False, "problems": errs}
    matched, trace = rules_engine._conditions_match(
        body.rule.get("conditions") or [], body.sample_event or {})
    preview = []
    for a in (body.rule.get("actions") or []):
        spec = rules_engine.VERBS.get(a.get("verb")) or {}
        params = {k: (rules_engine._interpolate(v, body.sample_event or {})
                      if isinstance(v, str) else v)
                  for k, v in (a.get("params") or {}).items()}
        preview.append({"verb": a.get("verb"), "kind": spec.get("kind"),
                        "rendered_params": params})
    return {"ok": True, "valid": True, "would_fire": matched,
            "condition_trace": trace, "action_preview": preview}


@router.get("/runs")
def list_runs(biz: str, limit: int = 50,
              user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/rule_runs?business_id=eq.{biz}&order=created_at.desc"
        f"&limit={min(int(limit), 200)}&select=*") or []
    return {"ok": True, "runs": rows}


# ═════════════════════════════════════════════════════════════════════
# Generic Chief proposals (the convergence's approval surface)
# ═════════════════════════════════════════════════════════════════════

def _capture_signal(biz: str, ptype: str, original: Dict[str, Any],
                    override: Optional[Dict[str, Any]], reason: Optional[str]) -> None:
    try:
        import chief_bookkeeping
        chief_bookkeeping.capture_learning_signal(biz, ptype, original, override, reason)
    except Exception as e:
        logger.warning(f"[proposals] signal capture failed: {e}")


def _execute_proposal(biz: str, p: Dict[str, Any]) -> Dict[str, Any]:
    ptype = p.get("proposal_type")
    proposed = p.get("proposed") or {}
    payload = {"contact_id": proposed.get("contact_id"),
               "contact_email": proposed.get("contact_email"),
               "contact_name": proposed.get("contact_name")}
    if ptype == "propose_followup_email":
        return rules_engine._exec_send_template_email(
            biz, {"subject": proposed.get("subject", ""),
                  "body": proposed.get("body", "")}, payload)
    if ptype == "propose_task" or ptype == "propose_schedule_followup":
        return rules_engine._exec_create_task(
            biz, {"title": proposed.get("title", "Follow up"),
                  "due_in_days": proposed.get("due_in_days", 1)}, payload)
    if ptype == "propose_contact_tag":
        return rules_engine._exec_apply_tag(
            biz, {"tag": proposed.get("tag", "")}, payload)
    if ptype == "propose_content_draft":
        # v1: approval files the draft as a task carrying the content —
        # the practitioner posts from their content surface. (Direct
        # publish is an autonomy-scope decision — Phase C.)
        return rules_engine._exec_create_task(
            biz, {"title": f"Post draft ready: {str(proposed.get('topic') or '')[:80]}",
                  "due_in_days": 1}, payload)
    raise HTTPException(400, f"unknown proposal_type {ptype}")


@proposals_router.get("")
def list_proposals(biz: str, status: str = "pending",
                   user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/chief_proposals?business_id=eq.{biz}&status=eq.{status}"
        f"&order=created_at.desc&limit=100&select=*") or []
    return {"ok": True, "proposals": rows}


@proposals_router.post("/analyze/{biz}")
def analyze_ops(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Arc 20B Part 3 — Chief-initiated proposals in the NEW domains.
    v1 analyzer (deterministic, Phase-G style; trust-layer 4 questions in
    the proposal reasoning): overdue-invoice follow-up emails. The other
    new domains (tasks, tags, scheduling, content) are fully live as
    proposal types + executors — rules and future analyzers feed them."""
    _owner(biz, user)
    created: List[Dict[str, Any]] = []
    invoices = sb_clients.sb_get_as_service(
        f"/invoices?business_id=eq.{biz}&paid_at=is.null"
        f"&status=in.(sent,viewed,overdue)"
        f"&select=id,invoice_number,total,due_date,contact_id,contacts(name,email)"
        f"&limit=100") or []
    today = datetime.now(timezone.utc).date()
    pending = sb_clients.sb_get_as_service(
        f"/chief_proposals?business_id=eq.{biz}&status=eq.pending"
        f"&proposal_type=eq.propose_followup_email&select=proposed&limit=100") or []
    already = {(p0.get("proposed") or {}).get("invoice_id") for p0 in pending}
    for inv in invoices:
        due = inv.get("due_date")
        if not due:
            continue
        try:
            d = datetime.fromisoformat(str(due)[:10]).date()
        except Exception:
            continue
        days = (today - d).days
        if days < 7 or inv.get("id") in already:
            continue
        c = (inv.get("contacts") or {}) or {}
        if not c.get("email"):
            continue
        res = sb_clients.sb_post_as_service("/chief_proposals", {
            "business_id": biz,
            "proposal_type": "propose_followup_email",
            "source": "chief",
            "proposed": {
                "invoice_id": inv.get("id"),
                "contact_id": inv.get("contact_id"),
                "contact_name": c.get("name"),
                "contact_email": c.get("email"),
                "subject": f"Friendly nudge — invoice {inv.get('invoice_number')}",
                "body": (f"Hi {c.get('name') or 'there'},\n\nJust a gentle "
                         f"reminder that invoice {inv.get('invoice_number')} "
                         f"(${float(inv.get('total') or 0):,.2f}) was due on "
                         f"{due}. The payment link is on the invoice — and if "
                         f"anything's off, just reply here.\n\nThank you!"),
            },
            "confidence": 0.85,
            "reasoning": (f"Invoice {inv.get('invoice_number')} is {days} days "
                          f"overdue and {c.get('name') or 'the client'} hasn't "
                          "been nudged. Approve to send this reminder — nothing "
                          "sends until you say so."),
            "status": "pending",
            "created_at": _now_iso(),
        })
        row = (res or [None])[0] if isinstance(res, list) else res
        if row:
            created.append(row)
    return {"ok": True, "created": created}


GRADUATION_MIN_RESOLVED = 20
GRADUATION_MIN_RATIO = 0.8

# Proposal types _execute_proposal knows how to run. Trust grants are
# limited to this set — bookkeeping proposals have their own approval
# machinery and are NOT grantable here (v1).
EXECUTABLE_PROPOSAL_TYPES = {
    "propose_followup_email", "propose_task",
    "propose_schedule_followup", "propose_contact_tag",
    "propose_content_draft",
}


def _trust_stats(biz: str) -> Dict[str, Dict[str, Any]]:
    """Per proposal-type approval tallies across BOTH proposal tables,
    with the graduation flag computed. Shared by the trust-track view,
    the grant endpoint, and the trusted sweep's safety recheck."""
    cats: Dict[str, Dict[str, int]] = {}

    def _tally(rows):
        for r in rows:
            t = r.get("proposal_type") or "?"
            c = cats.setdefault(t, {"approved": 0, "rejected": 0, "pending": 0})
            st = r.get("status")
            if st in c:
                c[st] += 1

    _tally(sb_clients.sb_get_as_service(
        f"/chief_proposals?business_id=eq.{biz}&select=proposal_type,status&limit=2000") or [])
    _tally(sb_clients.sb_get_as_service(
        f"/chief_bookkeeping_proposals?business_id=eq.{biz}"
        f"&select=proposal_type,status&limit=2000") or [])

    out: Dict[str, Dict[str, Any]] = {}
    for t, c in cats.items():
        resolved = c["approved"] + c["rejected"]
        ratio = round(c["approved"] / resolved, 3) if resolved else None
        out[t] = {
            **c, "resolved": resolved, "approval_ratio": ratio,
            "graduation_candidate": bool(
                resolved >= GRADUATION_MIN_RESOLVED and ratio is not None
                and ratio >= GRADUATION_MIN_RATIO),
        }
    return out


def _trusted_types(biz_row: Dict[str, Any]) -> List[str]:
    ap = ((biz_row.get("settings") or {}).get("autopilot") or {})
    lst = ap.get("trusted_proposal_types")
    return [str(t) for t in lst] if isinstance(lst, list) else []


@proposals_router.get("/trust-track")
def trust_track(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Arc 20B Part 5 + Chief Layers arc (Phase C): per proposal-category
    approval ratios across BOTH proposal tables. Categories at >=80%
    approval over >=20 resolved are GRADUATION CANDIDATES; the
    practitioner can now GRANT trust per category (POST
    /trust-track/grant), after which the trusted sweep executes that
    category's pending proposals autonomously — with an audit trail and
    one-click revoke."""
    biz_row = _owner(biz, user)
    trusted = set(_trusted_types(biz_row))
    stats = _trust_stats(biz)
    out = [{"proposal_type": t, **s, "trusted": t in trusted,
            "grantable": bool(s["graduation_candidate"]
                              and t in EXECUTABLE_PROPOSAL_TYPES)}
           for t, s in sorted(stats.items())]
    return {"ok": True, "categories": out,
            "graduation_rule": (f">={int(GRADUATION_MIN_RATIO * 100)}% approval "
                                f"over >={GRADUATION_MIN_RESOLVED} resolved proposals"),
            "note": "Graduated categories can be granted trust — Chief then "
                    "executes those proposals autonomously, every action is "
                    "logged to your activity rail, and you can revoke at any "
                    "time. Nothing acts without your explicit grant."}


class TrustGrantBody(BaseModel):
    business_id: str
    proposal_type: str


@proposals_router.post("/trust-track/grant")
def trust_grant(body: TrustGrantBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Grant Chief autonomy for ONE earned proposal category.

    Trust-layer discipline: the grant is explicit (never inferred),
    only available once the category has actually graduated on this
    business's own approval history, limited to executor-known types,
    audited (chief_activity), and instantly revocable."""
    biz_row = _owner(body.business_id, user)
    ptype = (body.proposal_type or "").strip()
    if ptype not in EXECUTABLE_PROPOSAL_TYPES:
        raise HTTPException(400, f"'{ptype}' cannot be granted — no autonomous executor")
    stats = _trust_stats(body.business_id).get(ptype)
    if not stats or not stats["graduation_candidate"]:
        raise HTTPException(409, "category has not graduated yet — keep approving/rejecting "
                                 "proposals and it will earn trust")
    settings = dict(biz_row.get("settings") or {})
    ap = dict(settings.get("autopilot") or {})
    trusted = set(_trusted_types(biz_row))
    trusted.add(ptype)
    ap["trusted_proposal_types"] = sorted(trusted)
    settings["autopilot"] = ap
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{body.business_id}", {"settings": settings})
    try:
        sb_clients.sb_post_as_service("/chief_activity", {
            "user_id": str(user.id), "business_id": body.business_id,
            "source": "system", "action_type": "trust_granted",
            "label": f"Trust granted: {ptype}",
            "summary": (f"Chief will now handle {ptype} proposals autonomously "
                        f"(earned at {stats['approval_ratio']:.0%} approval over "
                        f"{stats['resolved']} decisions). Revoke anytime."),
        })
    except Exception as e:
        logger.warning(f"[trust] grant activity log failed: {e}")
    return {"ok": True, "trusted": sorted(trusted)}


@proposals_router.post("/trust-track/revoke")
def trust_revoke(body: TrustGrantBody,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz_row = _owner(body.business_id, user)
    settings = dict(biz_row.get("settings") or {})
    ap = dict(settings.get("autopilot") or {})
    trusted = set(_trusted_types(biz_row))
    trusted.discard((body.proposal_type or "").strip())
    ap["trusted_proposal_types"] = sorted(trusted)
    settings["autopilot"] = ap
    sb_clients.sb_patch_as_service(
        f"/businesses?id=eq.{body.business_id}", {"settings": settings})
    return {"ok": True, "trusted": sorted(trusted)}


class ResolveBody(BaseModel):
    business_id: str
    override: Optional[Dict[str, Any]] = None
    override_reason: Optional[str] = None


@proposals_router.post("/{proposal_id}/approve")
def approve(proposal_id: str, body: ResolveBody,
            user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(body.business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/chief_proposals?id=eq.{proposal_id}&business_id=eq.{body.business_id}"
        f"&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "proposal not found")
    p = rows[0]
    if p.get("status") != "pending":
        return {"ok": True, "already": p.get("status")}
    result = _execute_proposal(body.business_id, p)
    sb_clients.sb_patch_as_service(
        f"/chief_proposals?id=eq.{proposal_id}",
        {"status": "approved", "resolved_at": _now_iso(),
         "approved_by": str(user.id)})
    _capture_signal(body.business_id, p.get("proposal_type"),
                    p.get("proposed") or {}, None, "approved")
    return {"ok": True, "executed": p.get("proposal_type"), "result": result}


@proposals_router.post("/{proposal_id}/reject")
def reject(proposal_id: str, body: ResolveBody,
           user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(body.business_id, user)
    rows = sb_clients.sb_get_as_service(
        f"/chief_proposals?id=eq.{proposal_id}&business_id=eq.{body.business_id}"
        f"&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "proposal not found")
    p = rows[0]
    if p.get("status") == "pending" and (body.override or body.override_reason):
        _capture_signal(body.business_id, p.get("proposal_type"),
                        p.get("proposed") or {}, body.override, body.override_reason)
    sb_clients.sb_patch_as_service(
        f"/chief_proposals?id=eq.{proposal_id}",
        {"status": "rejected", "resolved_at": _now_iso()})
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════
# Trusted autonomy sweep (Chief Layers arc — the Phase C execution leg)
# ═════════════════════════════════════════════════════════════════════

TRUSTED_SWEEP_CAP = 10  # max autonomous executions per business per sweep


def _run_trusted_sweep_sync() -> None:
    import os as _os
    if (_os.environ.get("TRUSTED_AUTONOMY") or "on").lower() == "off":
        return
    businesses = sb_clients.sb_get_as_service(
        "/businesses?select=id,name,owner_id,settings&limit=500") or []
    for biz_row in businesses:
        trusted = _trusted_types(biz_row)
        if not trusted:
            continue
        if rules_engine.business_paused(biz_row):
            continue  # the business-level kill switch pauses trust too
        biz = biz_row["id"]
        # Safety recheck at execution time: if a category's live approval
        # ratio slips below the graduation bar (recent rejects), the sweep
        # stands down for it — the grant stays, only execution pauses.
        stats = _trust_stats(biz)
        executed_labels: List[str] = []
        budget = TRUSTED_SWEEP_CAP
        for ptype in trusted:
            if budget <= 0:
                break
            if ptype not in EXECUTABLE_PROPOSAL_TYPES:
                continue
            s = stats.get(ptype)
            if not s or (s["approval_ratio"] or 0) < GRADUATION_MIN_RATIO:
                logger.info(f"[trusted] {biz} {ptype}: ratio below bar — standing down")
                continue
            pending = sb_clients.sb_get_as_service(
                f"/chief_proposals?business_id=eq.{biz}&status=eq.pending"
                f"&proposal_type=eq.{ptype}&order=created_at.asc"
                f"&select=*&limit={budget}") or []
            for p in pending:
                try:
                    _execute_proposal(biz, p)
                except Exception as e:
                    # Leaves the proposal pending for manual review —
                    # autonomy never force-fails work through.
                    logger.warning(f"[trusted] execute failed {biz}/{ptype}: {e}")
                    continue
                sb_clients.sb_patch_as_service(
                    f"/chief_proposals?id=eq.{p['id']}",
                    {"status": "approved", "resolved_at": _now_iso(),
                     "approved_by": "chief:trusted-autonomy"})
                _capture_signal(biz, ptype, p.get("proposed") or {}, None, "approved")
                budget -= 1
                label = ((p.get("proposed") or {}).get("subject")
                         or (p.get("proposed") or {}).get("title") or ptype)
                executed_labels.append(str(label)[:80])
                if biz_row.get("owner_id"):
                    try:
                        sb_clients.sb_post_as_service("/chief_activity", {
                            "user_id": str(biz_row["owner_id"]),
                            "business_id": biz,
                            "source": "system",
                            "action_type": f"trusted_{ptype}",
                            "label": f"Handled autonomously: {str(label)[:90]}",
                            "summary": (f"Executed under your standing trust grant "
                                        f"for {ptype}. Revoke anytime in Trust Track."),
                        })
                    except Exception as e:
                        logger.warning(f"[trusted] activity log failed: {e}")
        if executed_labels:
            print(f"[Trusted sweep] {biz_row.get('name') or biz}: "
                  f"executed {len(executed_labels)} — {', '.join(executed_labels[:3])}",
                  flush=True)


async def trusted_sweep_tick() -> None:
    """Scheduler tick (leader-gated, every 10 min): execute pending
    proposals in categories the practitioner has explicitly granted.
    Kill switch: TRUSTED_AUTONOMY=off."""
    import asyncio
    try:
        await asyncio.to_thread(_run_trusted_sweep_sync)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[trusted] sweep tick failed: {e}")
