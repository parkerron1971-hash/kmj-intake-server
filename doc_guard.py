"""
doc_guard.py — the half of the auditor that has teeth.

WHY THIS EXISTS

  doc_audit.py has been running on every generated document for a
  while, and stopping nothing. `blocking_count()` had no callers. The
  three doors a document leaves through — approve-and-send, the branded
  PDF, and DocuSeal e-signature — never audited at all, and a body
  edited by hand on the way through the approval queue was never looked
  at a second time.

  So a document could be generated, flagged with three blockers, edited
  into something worse, approved, printed and signed, and every one of
  those steps behaved exactly as it would for clean paper. Rules that
  stop nothing are documentation.

WHAT IT DOES NOT DO

  It does not stop a document being GENERATED. That was right and stays
  right: a practitioner needs to see the draft to fix it, and a
  generator that refuses to produce anything teaches nobody anything.
  The gate is on the way OUT, where the client is.

  It cannot be a wall, either. A deterministic rule can still be wrong
  about a particular document, and a practitioner who cannot send their
  own paper will find another way to send it — outside the system, where
  nothing is checked at all. So every gate here can be overridden by the
  owner, and an override is RECORDED as an event rather than being a
  silent bypass. The audit trail is the point; the wall is not.

RE-AUDIT, NOT REPLAY

  The verdict stamped at generation describes the body as generated. By
  the time a document reaches a door, that body may have been edited.
  So the guard re-runs the audit against the CURRENT body every time,
  using the template's declared contract and the original field values
  stashed alongside it — which is how a hand edit that deletes the
  signature block, or renumbers past the end, gets caught at the door
  rather than at the client's desk.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

import doc_audit
import sb_clients

logger = logging.getLogger("doc_guard")

# Where the generator stashes what a later re-audit needs. Lives on the
# agent_queue row's existing `data` jsonb — no new table, and it means
# every document already in the queue can be re-verified in place.
DATA_KEY = "verification"


def _marker(section: Dict[str, Any]) -> str:
    """A short string whose presence in the body means this clause is
    still there. The heading when there is one; otherwise the opening
    of the clause itself, which is what the signature block has."""
    heading = (section.get("heading") or "").strip()
    if heading:
        return heading
    return " ".join((section.get("text") or "").split())[:40]


def stash(template: Dict[str, Any], variables: Dict[str, str],
          audit: Dict[str, Any],
          rendered: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """The `data` payload for a freshly generated document."""
    shape = []
    for s in (rendered or []):
        if s.get("article"):
            shape.append({"article": s["article"], "marker": _marker(s)})
    return {
        "template_id": template.get("id"),
        "numbered": bool(template.get("numbered")),
        "contract": list(template.get("contract") or []),
        # Which articles rendered, and how to tell they are still there.
        # Without this a re-audit has a contract to check and no
        # sections to check it against, so EVERY declared article reads
        # as missing and every stored document is blocked. Caught by
        # test_a_clean_document_passes_and_is_restamped.
        "articles": shape,
        "highest_clause": max(
            [s.get("number") or 0 for s in (rendered or [])] or [0]),
        # Field values only — the same facts the body already prints,
        # kept so a re-audit can police invented figures against what
        # the practitioner actually supplied.
        "variables": {k: str(v) for k, v in (variables or {}).items()
                      if isinstance(v, (str, int, float))},
        "audit": audit,
    }


def summarize(audit: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The shape the Documents room reads: a verdict and three counts.
    A document with no stored verdict is 'unchecked', never 'clean' —
    the two must not look alike."""
    if not isinstance(audit, dict) or not audit.get("ok"):
        return {"verdict": "unchecked", "blockers": 0, "high": 0, "notes": 0,
                "clauses": 0}
    counts = audit.get("counts") or {}
    b = int(counts.get(doc_audit.BLOCKER, 0) or 0)
    h = int(counts.get(doc_audit.HIGH, 0) or 0)
    n = int(counts.get(doc_audit.NOTE, 0) or 0)
    return {
        "verdict": "blocked" if b else "flagged" if h else "verified",
        "blockers": b, "high": h, "notes": n,
        "clauses": int(audit.get("clauses_checked") or 0),
        "checked_at": audit.get("checked_at"),
        "degraded": audit.get("degraded"),
    }


def audit_stored_body(row: Dict[str, Any]) -> Dict[str, Any]:
    """Re-run every rule against the row's CURRENT body.

    An article counts as present only if its marker is still in the
    text — so a clause deleted while editing in the approval queue is
    exactly what this catches."""
    data = row.get("data") if isinstance(row.get("data"), dict) else {}
    stashed = (data or {}).get(DATA_KEY) or {}
    body = row.get("body") or ""
    if not stashed:
        # Generated before verification was stashed. The body-only rules
        # still apply; the structural ones stay inert rather than
        # guessing at a contract this row never declared.
        return doc_audit.audit_document(
            body, numbered="ACCEPTED AND AGREED" in body.upper())

    # Markers are stored whitespace-collapsed (a signature block's is
    # taken from its text, which is full of newlines), so the haystack
    # is collapsed the same way before matching.
    flat = " ".join(body.split())
    surviving: List[Dict[str, Any]] = []
    for entry in (stashed.get("articles") or []):
        marker = " ".join((entry.get("marker") or "").split())
        if marker and marker in flat:
            surviving.append({"article": entry.get("article"), "text": "",
                              "heading": marker})
    # One pseudo-section carries the body so the money rule still has
    # something to read; the clause-scoped precision of generation-time
    # auditing cannot be recovered from stored text alone, and claiming
    # otherwise would be worse than saying so here.
    highest = int(stashed.get("highest_clause") or 0)
    if highest:
        surviving.append({"article": None, "text": body, "number": highest})
    else:
        surviving.append({"article": None, "text": body})
    return doc_audit.audit_document(
        body, sections=surviving, numbered=bool(stashed.get("numbered")),
        contract=stashed.get("contract") or None,
        variables=stashed.get("variables") or None)


def restash(row: Dict[str, Any], audit: Dict[str, Any]) -> None:
    """Persist a fresh verdict onto the row. Best-effort: a failed write
    must never be the reason a document cannot be sent."""
    try:
        data = dict(row.get("data") or {}) if isinstance(row.get("data"), dict) else {}
        block = dict(data.get(DATA_KEY) or {})
        block["audit"] = audit
        data[DATA_KEY] = block
        sb_clients.sb_patch_as_service(
            f"/agent_queue?id=eq.{row['id']}", {"data": data})
        row["data"] = data
    except Exception as e:
        logger.warning(f"verification restash failed (non-fatal): {e}")


def load_document(queue_id: str, business_id: str) -> Dict[str, Any]:
    """A document row, double-scoped by business the way every other
    read in this codebase is."""
    rows = sb_clients.sb_get_as_service(
        f"/agent_queue?id=eq.{queue_id}&business_id=eq.{business_id}"
        "&select=id,business_id,contact_id,subject,body,status,priority,"
        "action_type,channel,data,ai_model,created_at,reviewed_at,sent_at"
        "&limit=1") or []
    if not rows:
        raise HTTPException(404, "document not found")
    return rows[0]


def require_sendable(row: Dict[str, Any], *, business_id: str,
                     actor_id: str, override: bool = False,
                     door: str = "send") -> Dict[str, Any]:
    """The gate. Returns the fresh audit; raises 409 when the document
    has blockers and the caller has not explicitly overridden.

    Only ever gates on BLOCKERS — the severity reserved for defects that
    are provably wrong AND visible to the client. A `high` is worth
    reading and is never worth stopping paper for; a practitioner who is
    stopped by a maybe stops believing the ones that are certain.
    """
    if (row.get("action_type") or "") != "document":
        # Not our paper. Every other action_type leaves through these
        # same doors and must be unaffected.
        return {}
    try:
        audit = audit_stored_body(row)
    except Exception as e:
        # An auditor that breaks a document is worse than no auditor —
        # the same posture doc_audit takes internally, restated here
        # because this is the layer that can actually refuse.
        logger.warning(f"doc_guard audit failed open: {e}")
        return {}
    restash(row, audit)
    blockers = doc_audit.blocking_count(audit)
    if not blockers:
        return audit
    if override:
        _record_override(row, business_id=business_id, actor_id=actor_id,
                         door=door, audit=audit)
        return audit
    detail = _refusal(audit, blockers)
    raise HTTPException(status_code=409, detail=detail)


def _refusal(audit: Dict[str, Any], blockers: int) -> Dict[str, Any]:
    worst = [f for f in (audit.get("findings") or [])
             if f.get("severity") == doc_audit.BLOCKER]
    lead = worst[0]["title"] if worst else "This document has a problem"
    return {
        "error": "document_blocked",
        "message": (f"{lead}. "
                    f"{blockers} thing{'s' if blockers != 1 else ''} in this "
                    "document would be wrong in front of the client. Fix "
                    "them, or send anyway if you know better."),
        "blockers": blockers,
        "findings": worst,
        "can_override": True,
    }


def _record_override(row: Dict[str, Any], *, business_id: str, actor_id: str,
                     door: str, audit: Dict[str, Any]) -> None:
    """An override is a decision somebody made, so it leaves a mark.
    Never a silent bypass — that would make the gate worse than absent,
    because it would look like the document had passed."""
    try:
        sb_clients.sb_post_as_service("/events", {
            "business_id": business_id,
            "contact_id": row.get("contact_id"),
            "event_type": "document_override",
            "data": {
                "queue_id": row.get("id"),
                "door": door,
                "actor_id": actor_id,
                "blockers": doc_audit.blocking_count(audit),
                "codes": sorted({f.get("code") for f in
                                 (audit.get("findings") or [])
                                 if f.get("severity") == doc_audit.BLOCKER}),
            },
            "source": "doc_guard"})
    except Exception as e:
        logger.warning(f"override event failed (non-fatal): {e}")


def guard_queue_id(queue_id: str, business_id: str, *, actor_id: str,
                   override: bool = False, door: str = "send") -> Dict[str, Any]:
    """Convenience for the doors that hold an id rather than a row."""
    row = load_document(queue_id, business_id)
    return require_sendable(row, business_id=business_id, actor_id=actor_id,
                            override=override, door=door)
