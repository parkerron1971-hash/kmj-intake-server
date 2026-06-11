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
