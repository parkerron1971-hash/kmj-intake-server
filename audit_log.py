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
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

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
                 "job:refine_section", "ledger:erasure", "ledger:selftest",
                 # The ledger's OWN verbs. Missing these meant the
                 # feature's own rows landed with verb_registered=false
                 # — the vocabulary out of sync on ship day, with itself.
                 "ledger:searched", "ledger:link_minted",
                 "ledger:link_revoked", "ledger:viewed_by_auditor"):
        out.setdefault(verb, {"verb": verb, "namespace": verb.split(":")[0],
                              "effect": "write"})
    # MUST match the trigger list in APPLY-2026-08-03-ledger-coverage.sql.
    # outbound_transfers was missing here, so every payout row landed
    # verb_registered=false — the highest-consequence writes flagged as
    # unrecognised vocabulary.
    for table in ("invoices", "bills", "business_expenses", "contacts",
                  "sessions", "module_entries", "orders",
                  "outbound_transfers"):
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


def _error_text(t: Dict[str, Any]) -> str:
    """A failure MESSAGE, never a failure payload.

    The result dict is deliberately not consulted: it is the thing that
    holds record contents, and `error` is a column that leaves the
    building. When a handler failed without saying why, say exactly
    that rather than reaching for the nearest available text.
    """
    err = t.get("error")
    if isinstance(err, str) and err.strip():
        return err[:500]
    # A STRING result is the handler's own human-readable failure
    # message ("error: recipient suppressed") — the same class of thing
    # as `error`, and what the practitioner needs to see in History.
    #
    # A DICT or LIST result is the payload, and that is where the leak
    # was: a half-failed create_invoice returns {"ok": False,
    # "contact": {...}}, and str()-ing it put contact PII into `error`,
    # which travels all the way to an external auditor's CSV. Never
    # stringify a structure; it stays in `result`, which no surface
    # selects.
    res = t.get("result")
    if isinstance(res, str) and res.strip():
        return res[:500]
    label = t.get("label")
    if isinstance(label, str) and label.strip():
        return f"failed: {label}"[:500]
    return "action failed with no error message"


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
            # NEVER fold `result` into `error`. `error` is in
            # LEDGER_SELECT and therefore reaches viewers, accountants
            # and — through an auditor link — people outside the
            # business entirely. A handler's result dict routinely
            # carries contact PII and invoice bodies. The result stays
            # in `result`, which no surface selects.
            error=(_error_text(t) if failed else None),
            summary=t.get("label") or verb,
            payload={k: t.get(k) for k in ("label", "nav") if t.get(k)},
            result=t.get("result"),
            source=source if source in ("mobile", "desktop", "voice", "system") else "desktop",
            # Stage 3: the policy verdict _execute_actions stamped on the
            # result. Field 6 stops being empty on the busiest path.
            authorized_by=t.get("_authorized_by"),
        )
        n += 1 if wrote else 0
    return n


def _require_ledger_read(biz: str, user: AuthedUser) -> Dict[str, Any]:
    """The ledger's read gate: owner, any ACTIVE seat (viewer included),
    or an active accountant collaborator.

    History is a trust surface, not an owner secret — and an accountant
    who cannot see what happened to the books they are reviewing is the
    one person the surface exists for. Returns the business row.
    """
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    row = rows[0]
    if str(row.get("owner_id")) == str(user.id):
        return row
    try:
        from business_collaborators_router import is_active_accountant
        if is_active_accountant(biz, str(user.id)):
            return row
    except Exception as e:
        logger.warning(f"[audit] accountant check failed: {e}")
    from business_users_router import require_role
    require_role(biz, str(user.id), "viewer")
    return row


@router.get("")
def read_audit(biz: str, limit: int = 100, failed_only: bool = False,
               verb: Optional[str] = None, include_db: bool = False,
               user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """The team's view of the business audit trail.

    Seat visibility (S11): owner-only reads left invited seats staring
    at an empty History panel. Same require_role ladder as the other
    routers — roles are enforced server-side here regardless of what the
    client renders.

    LEDGER ACCESS (2026-08-03): the read floor drops to VIEWER and active
    accountant collaborators are admitted. Two dead ends made that
    necessary. The sidebar showed every team seat a History leaf while
    this endpoint demanded member+, so a viewer clicking it met a 403 —
    a clickable thing that dead-ends. And an accountant collaborator, the
    single audience most likely to be handed an audit trail, could not
    reach it at all.

    Safe because of what this query SELECTS: verb, actor, ok/error,
    summary, timing, sequence, authorized_by, subject_refs. It never
    returns `payload` or `result`, so the db-trigger tier's before/after
    record contents are not exposed by widening the audience. Anything
    that would expose row CONTENTS must re-gate."""
    _require_ledger_read(biz, user)
    entries = ledger_entries(biz, limit=limit, failed_only=failed_only,
                             verb=verb, include_db=include_db)
    return {"ok": True, "entries": entries, "count": len(entries),
            "tier": "all" if include_db else "application"}


# The ONE definition of which ledger columns leave the building. The
# export, the auditor link and this endpoint all read through it, so a
# column can never be widened for one surface and forgotten on another.
LEDGER_SELECT = ("id,actor_type,actor_id,verb,ok,error,summary,source,"
                 "created_at,target_type,target_id,sequence,authorized_by,"
                 "subject_refs,verb_registered")


def ledger_entries(biz: str, *, limit: int = 100, failed_only: bool = False,
                   verb: Optional[str] = None, include_db: bool = False,
                   since: Optional[str] = None,
                   until: Optional[str] = None) -> List[Dict[str, Any]]:
    """Ledger rows for a business. No auth gate — every caller gates first.

    NOTE the select list: it never contains `payload` or `result`, so
    record CONTENTS are not exposed by any surface built on this. That
    invariant is what made widening the audience (viewers, accountants,
    auditor links) safe, and it is pinned by a test.
    """
    limit = min(max(int(limit or 100), 1), 500)
    q = (f"/audit_log?business_id=eq.{biz}&select={LEDGER_SELECT}"
         f"&order=created_at.desc&limit={limit}")
    if failed_only:
        q += "&ok=eq.false"
    if verb:
        # ':' is legal — namespaced verbs (db:, rules:, webhook:).
        safe = "".join(ch for ch in verb if ch.isalnum() or ch in "_:")[:80]
        q += f"&verb=eq.{safe}"
    # PostgREST timestamp class: the Z form ALWAYS. An isoformat +00:00
    # in a query string silently returns empty.
    z_since, z_until = _z(since), _z(until)
    if z_since:
        q += f"&created_at=gte.{z_since}"
    if z_until:
        q += f"&created_at=lte.{z_until}"
    # Two tiers, one table. db_trigger rows are the PROVABLE tier and
    # they double up with the application row for the same action, so a
    # practitioner's History reads the intent tier by default. A proof
    # passes include_db=true — the provable tier is never hidden from a
    # proof, only from a summary.
    if not include_db:
        q += "&source=not.eq.db_trigger"
    return sb_clients.sb_get_as_service(q) or []


def count_in_range(biz: str, *, include_db: bool = False,
                   since: Optional[str] = None,
                   until: Optional[str] = None) -> int:
    """How many rows actually MATCH — not how many we returned.

    ledger_entries hard-caps at 500. An exported report that shows 500
    and says nothing implies a completeness it does not have, which for
    an evidentiary document is the worst kind of quiet. Counts up to a
    ceiling rather than scanning forever; at the ceiling the caller
    still learns "more than this".
    """
    q = (f"/audit_log?business_id=eq.{biz}&select=id"
         f"{'' if include_db else '&source=not.eq.db_trigger'}")
    z_since, z_until = _z(since), _z(until)
    if z_since:
        q += f"&created_at=gte.{z_since}"
    if z_until:
        q += f"&created_at=lte.{z_until}"
    try:
        return len(sb_clients.sb_get_as_service(q + "&limit=5000") or [])
    except Exception as e:
        logger.warning(f"[ledger] range count failed for {biz}: {e}")
        return 0


_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})"
    r"(?:[T ](\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?))?"
    r"(?:Z|[+-]\d{2}:?\d{2})?$")


def _z(ts: Optional[str]) -> Optional[str]:
    """A validated, canonical UTC timestamp — or nothing.

    This value is concatenated into a PostgREST query string, and it
    arrives from three places: raw query params on /audit/export, the
    signed window on an auditor link, and the NAVIGATOR, whose input is
    an LLM reading a user's free text. The old version only rewrote
    +00:00 to Z, so `2026-01-01&select=id,payload,result` sailed
    through — one prompt away from widening the very select list this
    design exists to keep narrow.

    Anything that is not a plain ISO date/time is dropped rather than
    passed on: a filter we cannot parse is not a filter we should
    silently honour.
    """
    if not ts:
        return None
    m = _TS_RE.match(str(ts).strip())
    if not m:
        logger.warning("[ledger] rejected malformed timestamp filter")
        return None
    day, clock = m.group(1), m.group(2)
    return f"{day}T{clock}Z" if clock else f"{day}T00:00:00Z"


class _NavBody(BaseModel):
    business_id: str
    question: str


@router.post("/navigate")
def navigate(body: _NavBody, user: AuthedUser = Depends(require_user)):
    """Turn a question into a FILTER over real rows, and return the rows.

    The portal agent. It GUIDES — resolves "the invoices for that client
    last July" into a filter and walks the reader to those records. It
    does NOT narrate: no summary, no interpretation, no verdict on what
    the records mean. The only sentence it produces is a description of
    the FILTER it applied.

    The model never sees row contents (see ledger_navigator), so the
    restraint is structural rather than a prompt instruction someone
    could talk their way past.

    The search is itself recorded. Who went looking for what, and when,
    belongs in the record — especially when the reader is an auditor.
    """
    _require_ledger_read(body.business_id, user)
    # This endpoint spends money (an Anthropic call) and grows an
    # append-only table on every request. chief_chat and ai_proxy are
    # both metered; this was not, so any active seat could loop it.
    try:
        import rate_limit
        if not rate_limit.allow("ledger_nav", str(user.id)):
            raise HTTPException(
                429, "That's a lot of searches at once — give it a moment.",
                headers={"Retry-After": str(rate_limit.retry_after("ledger_nav"))})
    except HTTPException:
        raise
    except Exception:
        pass
    import ledger_navigator
    nav = ledger_navigator.resolve(body.question)
    f = nav["filter"]

    entries = ledger_entries(
        body.business_id, limit=int(f.get("limit") or 200),
        failed_only=bool(f.get("failed_only")), verb=f.get("verb"),
        include_db=bool(f.get("include_db")),
        since=f.get("since"), until=f.get("until"))

    # Filters PostgREST can't express cleanly, applied to the rows we
    # already hold rather than by widening the query.
    if f.get("actor"):
        a = f["actor"]
        entries = [e for e in entries
                   if e.get("actor_id") == a or e.get("actor_type") == a]
    if f.get("subject_id"):
        sid = f["subject_id"]
        entries = [e for e in entries
                   if any(sid in str(r.get("id") or "")
                          for r in (e.get("subject_refs") or [])
                          if isinstance(r, dict))
                   or sid in str(e.get("target_id") or "")]

    try:
        record(body.business_id, actor_type="user", actor_id=str(user.id),
               verb="ledger:searched", summary=str(body.question)[:240],
               payload={"filter": f, "matches": len(entries)},
               source="audit", authorized_by="ledger_read")
    except Exception:
        pass

    return {"ok": True, "filter": f, "description": nav["description"],
            "entries": entries, "count": len(entries)}


@router.get("/export")
def export_ledger(biz: str, format: str = "pdf", limit: int = 500,
                  since: Optional[str] = None, until: Optional[str] = None,
                  user: AuthedUser = Depends(require_user)):
    """The artifact — a verification report that leaves the building.

    A licensing board, an insurer or opposing counsel will never have a
    Solutionist login, so a portal they cannot open is not a proof. This
    is the document a practitioner hands them.

    include_db is forced TRUE: an auditor wants the provable tier (the
    database's own before/after record of every change), not the
    readable summary the History screen shows.
    """
    biz_row = _require_ledger_read(biz, user)
    import ledger_report
    data = ledger_report.build(biz_row, limit=limit, since=since,
                               until=until, include_db=True)
    fmt = (format or "pdf").lower()
    stamp = data["generated_at"][:10]
    base = f"ledger-verification-{stamp}"

    if fmt == "json":
        return data
    if fmt == "csv":
        from fastapi.responses import Response
        return Response(
            content=ledger_report.to_csv(data), media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})
    try:
        pdf = ledger_report.to_pdf(
            data, biz_row, generated_by=(user.email or str(user.id)))
    except ImportError:
        # House pattern: PDF is optional, CSV is the floor.
        raise HTTPException(503, "PDF export unavailable. Use format=csv.")
    from fastapi.responses import Response
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{base}.pdf"'})


@router.get("/verify")
def verify_chain(biz: str,
                 user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Re-walk this business's hash chain and report whether it holds.

    Stage 2. Each row's hash covers its own contents plus the previous
    row's hash, so altering any historical row breaks every hash after
    it. The check runs in the database (ledger_verify) because that is
    where the canonical serialization lives — recomputing the bytes in
    Python would be a second, drifting definition of the truth.

    Deliberately plain output. This endpoint reports; it does not
    reassure. A gap is reported as a gap, with the tombstone that
    explains it, and the practitioner draws their own conclusion.
    """
    _require_ledger_read(biz, user)
    return verification_report(biz)


def verification_report(biz: str) -> Dict[str, Any]:
    """The verification payload, without the auth gate.

    Extracted so the endpoint, the exportable report, and the auditor
    link all render the SAME numbers. A second implementation of "is
    this chain intact" would eventually disagree with the first, and a
    proof that disagrees with itself is worse than no proof.
    """
    try:
        res = sb_clients.sb_post_as_service(
            "/rpc/ledger_verify", {"p_business_id": biz}) or []
        report = (res[0] if isinstance(res, list) and res else {}) or {}
    except Exception as e:
        logger.warning(f"[ledger] verify failed for {biz}: {e}")
        raise HTTPException(503, "Verification is unavailable right now")

    tombstones = sb_clients.sb_get_as_service(
        f"/ledger_tombstones?business_id=eq.{biz}"
        f"&select=erased_at,rows_erased,first_sequence,last_sequence,reason"
        f"&order=erased_at.desc&limit=50") or []

    # Rows written before Stage 2 carry no hash. Saying "intact" about
    # them would be the one dishonest thing this endpoint could do.
    unhashed = sb_clients.sb_get_as_service(
        f"/audit_log?business_id=eq.{biz}&row_hash=is.null&select=id&limit=1000") or []

    return {
        "ok": True,
        "intact": bool(report.get("intact")),
        "checked": report.get("checked", 0),
        # Found by running the verifier against production: every real
        # chain said "intact" while carrying ZERO hashes, because
        # pre-Stage-2 rows are skipped. "Verified" must never quietly
        # mean "there was nothing to verify".
        "hashed": report.get("hashed", 0),
        "first_sequence": report.get("first_sequence"),
        "last_sequence": report.get("last_sequence"),
        "broken_at": report.get("broken_at"),
        "reason": report.get("reason"),
        "gaps": report.get("gaps") or [],
        "erasures": tombstones,
        "unverifiable_rows": len(unhashed),
        "note": ("Rows recorded before the hash chain began carry no hash "
                 "and cannot be proven either way.") if unhashed else None,
    }
