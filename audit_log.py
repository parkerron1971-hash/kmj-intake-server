"""
audit_log.py — Rails Arc 4 — the unified audit log.

One append-only table answering "who did what, when — and did it
work". Unlike chief_activity (a recap feed that skips failures by
design), the audit log records EVERYTHING executed: successes,
failures, even navigation — because "Chief tried X and it failed" is
exactly what a practitioner reviewing their business needs to see, and
exactly what protects the platform when a number is disputed.

Writers call record() (best-effort, never raises). v1 wires the Chief
chat loop; scheduler/rules/agent writers adopt the same helper
opportunistically — one function, one table, no bespoke shapes.

Reads go through GET /audit (member+ via the seat ladder — history is
a trust surface for the whole team, not an owner secret). The table is
service-role insert only with no update/delete policies: an audit row
that can be edited is a diary, not an audit.

ACTOR NAMES: the table's actor_type CHECK allows only
('user','chief','agent','system'). Non-chat writers (the scheduler,
the trusted-autonomy sweep) therefore write actor_type='system' and
carry their real identity in actor_id ('scheduler', 'trust-track') —
the frontend renders actor_id as the display name when present.

THE ACTION LEDGER (2026-08-03, Stage 1). This table IS the ledger —
Kevin ruled we evolve it rather than start a fifth parallel history.
What the database now guarantees, not the application:
  * append-only for real — BEFORE UPDATE/DELETE triggers raise, so even
    service_role (which bypasses RLS) cannot rewrite a row. Deletion is
    possible only through ledger_erase_business(), which writes a
    ledger_tombstones row FIRST and leaves the sequence gap visible.
  * `sequence` is assigned per tenant under an advisory lock, and
    `prev_hash`/`row_hash` are reserved for Stage 2's chain. Python
    never sets any of the three.
The vocabulary lives in action_types, seeded by sync_action_types()
from action_registry — advisory rather than a foreign key, because
losing the record of an action is worse than recording an odd verb.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("audit_log")

router = APIRouter(prefix="/audit", tags=["audit"])

_RESULT_CAP = 2000  # jsonb result snippet cap (chars of serialized form)


def vocabulary() -> Dict[str, Dict[str, Any]]:
    """The ledger's controlled vocabulary, assembled from the registries
    that already exist rather than invented as a fourth naming scheme.

    Chief verbs keep their own names (action_registry is already
    drift-tested against ACTION_HANDLERS, so renaming 151 verbs into a
    dotted convention would break that pin for cosmetics). Everything
    else is namespaced so the origin is readable at a glance.
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        import action_registry
        for verb, cls in action_registry.REGISTRY.items():
            out[verb] = {"verb": verb, "namespace": "chief",
                         "effect": cls.get("effect"),
                         "reversibility": cls.get("reversibility"),
                         "bulk": bool(cls.get("bulk")),
                         "description": (cls.get("why") or "")[:400]}
    except Exception as e:
        logger.warning(f"[ledger] action_registry unavailable: {e}")
    try:
        import event_spine
        for et, meta in (event_spine.EVENT_CATALOG or {}).items():
            key = f"webhook:{et}"
            out[key] = {"verb": key, "namespace": "event", "effect": "write",
                        "description": str(meta)[:400]}
    except Exception as e:
        logger.warning(f"[ledger] event catalog unavailable: {e}")
    # Vocabularies with no registry of their own yet.
    for verb in ("rules:notify_practitioner", "rules:apply_tag",
                 "rules:create_task", "rules:send_template_email",
                 "job:rebuild_site", "job:compose_directions",
                 "job:refine_section", "ledger:erasure", "ledger:selftest"):
        out.setdefault(verb, {"verb": verb, "namespace": verb.split(":")[0],
                              "effect": "write"})
    for table in ("invoices", "bills", "business_expenses", "contacts",
                  "sessions", "module_entries", "orders"):
        for op in ("insert", "update", "delete"):
            key = f"db:{table}_{op}"
            out[key] = {"verb": key, "namespace": "db", "effect": "write",
                        "description": f"direct {op} on {table} (DB trigger)"}
    return out


def sync_action_types() -> int:
    """Upsert the vocabulary into action_types. Idempotent; safe to call
    at every boot. Returns the number of verbs published."""
    vocab = list(vocabulary().values())
    if not vocab:
        return 0
    try:
        sb_clients.sb_post_as_service(
            "/action_types?on_conflict=verb", vocab,
            prefer="resolution=merge-duplicates")
        return len(vocab)
    except Exception as e:
        logger.warning(f"[ledger] action_types sync failed: {e}")
        return 0


def _cap_json(value: Any) -> Dict[str, Any]:
    """Coerce any handler result into a small jsonb-safe dict."""
    if value is None:
        return {}
    if isinstance(value, dict):
        try:
            s = json.dumps(value, default=str)
            if len(s) <= _RESULT_CAP:
                return value
            return {"truncated": s[:_RESULT_CAP]}
        except Exception:
            return {"repr": repr(value)[:_RESULT_CAP]}
    return {"text": str(value)[:_RESULT_CAP]}


def record(business_id: Optional[str], *, actor_type: str, verb: str,
           actor_id: Optional[str] = None, ok: bool = True,
           error: Optional[str] = None, summary: Optional[str] = None,
           payload: Optional[Dict[str, Any]] = None,
           result: Any = None,
           target_type: Optional[str] = None, target_id: Optional[str] = None,
           source: Optional[str] = None,
           authorized_by: Optional[str] = None,
           subject_refs: Optional[List[Dict[str, Any]]] = None,
           display_timezone: Optional[str] = None) -> bool:
    """Append one ledger row. Best-effort: never raises into the caller.

    ACTION LEDGER (2026-08-03): `sequence`, `prev_hash` and `row_hash` are
    assigned by the database, not here — a BEFORE INSERT trigger takes a
    per-tenant advisory lock so concurrent writers can't fork the chain.
    Never set them from Python.

    authorized_by is the spec's sixth field: the permission tier or policy
    rule that allowed this action, not merely who ran it.
    """
    if not business_id or not verb:
        return False
    refs = subject_refs if isinstance(subject_refs, list) else []
    # Field 5 stays queryable ("everything that happened to this client"),
    # so keep the shape strict: [{type, id}] with both present.
    refs = [{"type": str(r.get("type"))[:40], "id": str(r.get("id"))[:80]}
            for r in refs if isinstance(r, dict) and r.get("type") and r.get("id")][:25]
    if not refs and target_type and target_id:
        refs = [{"type": str(target_type)[:40], "id": str(target_id)[:80]}]
    row = {
        "business_id": business_id,
        "actor_type": actor_type if actor_type in ("user", "chief", "agent", "system") else "system",
        "actor_id": str(actor_id) if actor_id else None,
        "verb": str(verb)[:80],
        "target_type": target_type,
        "target_id": str(target_id)[:80] if target_id else None,
        "ok": bool(ok),
        "error": (str(error)[:500] if error else None),
        "summary": (str(summary)[:240] if summary else None),
        "payload": _cap_json(payload),
        "result": _cap_json(result),
        "source": source,
        "authorized_by": (str(authorized_by)[:120] if authorized_by else None),
        "subject_refs": refs,
        "display_timezone": display_timezone,
    }
    try:
        sb_clients.sb_post_as_service("/audit_log", row, prefer=None)
        return True
    except Exception as e:
        logger.warning(f"[audit] record({verb}) failed: {e}")
        return False


def record_chief_turn(*, user_id: Optional[str], business_id: Optional[str],
                      source: Optional[str], taken: List[Dict[str, Any]],
                      action_failed) -> int:
    """Audit every action a Chief chat turn executed — including
    failures and navigation (the two things chief_activity skips).
    `action_failed` is chief_of_staff's own failure predicate, passed
    in to keep one source of truth for what 'failed' means."""
    if not business_id or not taken:
        return 0
    n = 0
    for t in taken:
        if not isinstance(t, dict):
            continue
        verb = t.get("type") or "unknown"
        failed = bool(action_failed(t))
        wrote = record(
            business_id,
            actor_type="chief",
            actor_id=user_id,
            verb=verb,
            ok=not failed,
            error=(str(t.get("error") or t.get("result"))[:500] if failed else None),
            summary=t.get("label") or verb,
            payload={k: t.get(k) for k in ("label", "nav") if t.get(k)},
            result=t.get("result"),
            source=source if source in ("mobile", "desktop", "voice", "system") else "desktop",
        )
        n += 1 if wrote else 0
    return n


@router.get("")
def read_audit(biz: str, limit: int = 100, failed_only: bool = False,
               verb: Optional[str] = None,
               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The team's view of the business audit trail.

    Seat visibility (S11): owner-only reads left invited seats staring
    at an empty History panel. Same require_role ladder as the other
    routers — any working seat (member+) can read; roles are enforced
    server-side here regardless of what the client renders."""
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    from business_users_router import require_role
    require_role(biz, str(user.id), "member")

    limit = min(max(limit, 1), 500)
    q = (f"/audit_log?business_id=eq.{biz}"
         f"&select=id,actor_type,actor_id,verb,ok,error,summary,source,created_at,target_type,target_id"
         f"&order=created_at.desc&limit={limit}")
    if failed_only:
        q += "&ok=eq.false"
    if verb:
        safe = "".join(ch for ch in verb if ch.isalnum() or ch == "_")[:80]
        q += f"&verb=eq.{safe}"
    entries = sb_clients.sb_get_as_service(q) or []
    return {"ok": True, "entries": entries, "count": len(entries)}
