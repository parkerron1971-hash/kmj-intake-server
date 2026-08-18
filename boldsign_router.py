"""
boldsign_router.py — Rails demand-driven arc — e-sign, adapter #1.

The ruling: connect, don't build. Legally valid signatures carry
ESIGN Act compliance, audit trails, and tamper-evidence — BoldSign
owns that engine. We own the chain that makes it matter: proposal →
signature → payment, without the moment ever leaving the system.

Surface (all owner-gated):
  POST /esign/send            — send a PDF (by URL — the contract
                                agent's pdf_url) to one signer.
                                BoldSign emails them; nothing embedded
                                in v1.
  GET  /esign/list?biz=       — the business's sent documents.
  POST /esign/{id}/refresh    — pull live status from BoldSign; a
                                newly-completed document emits
                                contract_signed on the event spine
                                (the catalog entry that waited a month
                                for a real emitter).
  POST /esign/webhook         — BoldSign calls this when a document is
                                signed, declined, or expires. PUBLIC by
                                necessity (the provider has no login),
                                so it authenticates by shared secret and
                                by looking the document up on OUR side —
                                a payload naming an unknown document is
                                ignored, never inserted.

WHY A WEBHOOK AND NOT JUST REFRESH. Refresh only tells the truth when
somebody is looking at the panel. A signature that lands on a Sunday
sat invisible until the next visit, and the confirmation email that
depends on it never went. The webhook makes completion an event that
happens TO the system rather than one it has to go and check for; the
refresh endpoint stays as the manual fallback for a missed delivery.

Env: BOLDSIGN_API_KEY (Railway, validated live 7/30). Trial now,
free-sandbox later — the key is the only coupling.

v1 placement honesty: the signature field lands at the bottom of page
one (BoldSign requires at least one field per signer; our generated
proposal PDFs carry no text tags). Good enough for real agreements;
per-template placement is the day-two refinement.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("boldsign_router")

router = APIRouter(prefix="/esign", tags=["esign"])

BOLDSIGN_BASE = "https://api.boldsign.com"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)

# BoldSign document status → our vocabulary.
_STATUS_MAP = {
    "inprogress": "sent",
    "completed": "completed",
    "declined": "declined",
    "expired": "expired",
    "revoked": "revoked",
}


def _api_key() -> str:
    key = (os.environ.get("BOLDSIGN_API_KEY") or "").strip()
    if not key:
        raise HTTPException(503, "e-sign isn't configured (BOLDSIGN_API_KEY missing)")
    return key


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def map_provider_status(raw: Optional[str]) -> Optional[str]:
    """BoldSign's status string → ours; None when unrecognized (keep
    the stored status rather than guessing)."""
    return _STATUS_MAP.get((raw or "").strip().lower())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SendBody(BaseModel):
    business_id: str
    pdf_url: str                 # the contract agent's generated PDF
    title: str
    signer_name: str
    signer_email: str
    message: str = ""
    source_ref: str = ""         # e.g. the agent_queue proposal id
    # The matter / project / job this document belongs to. Optional
    # because a general engagement letter belongs to the client, not to
    # one matter — and because a business with no work pipeline (a
    # salon) has nothing to attach it to.
    module_entry_id: Optional[str] = None


@router.post("/send")
async def esign_send(body: SendBody,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _owner(body.business_id, user)
    key = _api_key()
    email = (body.signer_email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(400, "signer_email required")
    title = (body.title or "Agreement").strip()[:120]

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        pdf = await c.get(body.pdf_url)
        if pdf.status_code >= 400 or not pdf.content:
            raise HTTPException(400, "couldn't fetch the PDF to send")

        # BoldSign /v1/document/send — multipart; one signer, one
        # signature field at the bottom of page 1 (v1 honesty above).
        form = {
            "Title": title,
            "Message": (body.message or f"{biz.get('name') or 'We'} sent this for your signature.")[:500],
            "Signers[0][Name]": (body.signer_name or email.split("@")[0])[:100],
            "Signers[0][EmailAddress]": email,
            "Signers[0][SignerType]": "Signer",
            "Signers[0][FormFields][0][FieldType]": "Signature",
            "Signers[0][FormFields][0][PageNumber]": "1",
            "Signers[0][FormFields][0][IsRequired]": "true",
            "Signers[0][FormFields][0][Bounds][X]": "60",
            "Signers[0][FormFields][0][Bounds][Y]": "700",
            "Signers[0][FormFields][0][Bounds][Width]": "220",
            "Signers[0][FormFields][0][Bounds][Height]": "50",
        }
        r = await c.post(
            f"{BOLDSIGN_BASE}/v1/document/send",
            headers={"X-API-KEY": key},
            data=form,
            files={"Files": (f"{title[:60]}.pdf", pdf.content, "application/pdf")},
        )
    if r.status_code >= 400:
        logger.error(f"[esign] send failed {r.status_code}: {r.text[:400]}")
        raise HTTPException(502, f"e-sign send failed: {r.text[:200]}")
    doc_id = (r.json() or {}).get("documentId") or ""
    if not doc_id:
        raise HTTPException(502, "e-sign provider returned no document id")

    inserted = sb_clients.sb_post_as_service("/esign_documents", {
        "business_id": body.business_id,
        "provider": "boldsign",
        "document_id": doc_id,
        "title": title,
        "signer_name": (body.signer_name or "")[:100],
        "signer_email": email,
        "status": "sent",
        "source_ref": (body.source_ref or None),
        **({"module_entry_id": body.module_entry_id} if body.module_entry_id else {}),
    })
    row_id = (inserted[0].get("id") if isinstance(inserted, list) and inserted
              else (inserted or {}).get("id"))

    import audit_log
    audit_log.record(body.business_id, actor_type="user", actor_id=str(user.id),
                     verb="esign_send", summary=f"Sent for signature: {title}",
                     payload={"signer": email, "document_id": doc_id},
                     target_type="esign_document", target_id=doc_id,
                     source="desktop")

    logger.info(f"[esign] sent '{title}' to {email} biz={body.business_id[:8]} doc={doc_id}")
    return {"ok": True, "id": row_id, "document_id": doc_id, "status": "sent"}


@router.get("/list")
def esign_list(biz: str, user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/esign_documents?business_id=eq.{biz}"
        f"&select=id,title,signer_name,signer_email,status,sent_at,completed_at"
        f"&order=sent_at.desc&limit=100") or []
    return {"ok": True, "documents": rows}


# ══════════════════════════════════════════════════════════════════
# Completion — one path, two callers
#
# A signature finishes exactly once, and everything that follows from
# it (the status, the spine event, the audit row, the two emails) has
# to happen exactly once too. Refresh and the webhook are two ways of
# NOTICING the same fact, so they share the code below instead of each
# carrying half of it. The guard is the stored status: a row that
# already says completed returns without re-emitting, which makes the
# duplicate webhook delivery every provider eventually sends harmless.
# ══════════════════════════════════════════════════════════════════

APP_URL = "https://system.mysolutionist.app"


def _esc(v: Optional[str]) -> str:
    import html as _h
    return _h.escape(str(v or ""))


async def _owner_email(owner_id: str) -> Optional[str]:
    """The practitioner's login email, via auth.users. None if unknown."""
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not base or not service_key or not owner_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{base}/auth/v1/admin/users/{owner_id}",
                            headers={"apikey": service_key,
                                     "Authorization": f"Bearer {service_key}"})
        if r.status_code >= 400:
            return None
        return (r.json() or {}).get("email") or None
    except Exception as e:
        logger.warning(f"[esign] owner email lookup failed: {e}")
        return None


async def _signed_pdf_b64(document_id: str) -> Optional[str]:
    """The executed copy, base64 for a Resend attachment.

    Best-effort: a confirmation that arrives without the PDF still tells
    both sides the thing is done, so a download failure downgrades the
    email rather than cancelling it."""
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{BOLDSIGN_BASE}/v1/document/download",
                            headers={"X-API-KEY": _api_key()},
                            params={"documentId": document_id})
        if r.status_code >= 400 or not r.content:
            logger.warning(f"[esign] download failed {r.status_code} for {document_id}")
            return None
        import base64
        return base64.b64encode(r.content).decode()
    except Exception as e:
        logger.warning(f"[esign] download raised for {document_id}: {e}")
        return None


def _completion_html(*, title: str, biz_name: str, signer_name: str,
                     signer_email: str, for_signer: bool) -> str:
    """Short and plain. Nobody reads a confirmation twice."""
    who = signer_name or signer_email
    if for_signer:
        lead = (f"Thank you — your signed copy of <strong>{_esc(title)}</strong> "
                f"is attached for your records.")
        tail = (f'<p style="margin:18px 0 0;color:#555">Sent by {_esc(biz_name)}. '
                f"Keep this email; the attachment is the executed agreement.</p>")
    else:
        lead = (f"<strong>{_esc(who)}</strong> signed "
                f"<strong>{_esc(title)}</strong>.")
        tail = (f'<p style="margin:18px 0 0;color:#555">The executed copy is '
                f"attached, and the document now shows as signed in your "
                f'<a href="{APP_URL}" style="color:#2E7DFF">Documents</a> panel.</p>')
    return ('<div style="font-family:-apple-system,Segoe UI,Roboto,sans-serif;'
            'font-size:15px;line-height:1.6;color:#14161a;max-width:560px">'
            f'<p style="margin:0 0 14px">{lead}</p>'
            f"{tail}</div>")


async def _send_completion_emails(biz: Dict[str, Any], doc: Dict[str, Any]) -> None:
    """Tell both sides it is done, with the executed copy attached.

    Best-effort in the strongest sense: the signature is a real event
    that already happened and is already recorded. An email provider
    having a bad afternoon must never turn that into a failed request or
    a status left stale, so every path here swallows."""
    try:
        from email_sender import send_via_resend
    except Exception as e:
        logger.warning(f"[esign] email_sender unavailable: {e}")
        return

    title = doc.get("title") or "Agreement"
    biz_name = biz.get("name") or "Your business"
    signer_email = (doc.get("signer_email") or "").strip()
    signer_name = doc.get("signer_name") or ""
    from_email = os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app"

    pdf_b64 = await _signed_pdf_b64(doc.get("document_id") or "")
    attachments = ([{"filename": f"{title[:60]}.pdf", "content": pdf_b64,
                     "content_type": "application/pdf"}] if pdf_b64 else None)

    owner_email = await _owner_email(str(biz.get("owner_id") or ""))

    # The practitioner first — they are the one waiting on it. The signer
    # is skipped when they ARE the practitioner (Kevin signing his own
    # paperwork), so nobody gets the same mail twice.
    targets = []
    if owner_email:
        targets.append((owner_email, biz_name, False))
    if (signer_email and "@" in signer_email
            and signer_email.lower() != (owner_email or "").lower()):
        targets.append((signer_email, signer_name, True))

    for to_email, to_name, for_signer in targets:
        try:
            await send_via_resend(
                to_email=to_email,
                to_name=to_name or None,
                from_email=from_email,
                from_name=biz_name,
                subject=(f"Signed: {title}" if for_signer
                         else f"{signer_name or signer_email} signed {title}"),
                body=_completion_html(title=title, biz_name=biz_name,
                                      signer_name=signer_name,
                                      signer_email=signer_email,
                                      for_signer=for_signer),
                reply_to=None,
                attachments=attachments,
                business_id=str(biz.get("id") or "") or None,
            )
            logger.info(f"[esign] confirmation sent to {to_email} for {title!r}")
        except Exception as e:
            logger.warning(f"[esign] confirmation to {to_email} failed: {e}")


async def _apply_status(doc: Dict[str, Any], biz: Dict[str, Any],
                        new_status: Optional[str]) -> Dict[str, Any]:
    """Persist a provider status and fire everything a completion owes.

    Idempotent: an unchanged status is a no-op, so a redelivery costs
    one comparison and nothing else."""
    biz_id = str(biz.get("id") or "")
    if not new_status or new_status == doc.get("status"):
        return {"status": doc.get("status"), "changed": False}

    patch: Dict[str, Any] = {"status": new_status, "updated_at": _now_iso()}
    if new_status == "completed":
        patch["completed_at"] = _now_iso()
    sb_clients.sb_patch_as_service(f"/esign_documents?id=eq.{doc['id']}", patch)

    if new_status == "completed":
        import event_spine
        event_spine.emit("contract_signed", biz_id, {
            "contract_ref": doc["document_id"],
            "title": doc.get("title"),
            "signer_email": doc.get("signer_email"),
        }, source="esign")
        import audit_log
        audit_log.record(biz_id, actor_type="system", verb="esign_completed",
                         summary=f"Signed: {doc.get('title')}",
                         target_type="esign_document", target_id=doc["document_id"],
                         source="esign")
        await _send_completion_emails(biz, doc)

    return {"status": new_status, "changed": True}


async def _live_status(document_id: str) -> Optional[str]:
    """Ask BoldSign what the document's status actually is."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(f"{BOLDSIGN_BASE}/v1/document/properties",
                        headers={"X-API-KEY": _api_key()},
                        params={"documentId": document_id})
    if r.status_code >= 400:
        logger.warning(f"[esign] properties failed {r.status_code}: {r.text[:200]}")
        return None
    return map_provider_status((r.json() or {}).get("status"))


@router.post("/{esign_id}/refresh")
async def esign_refresh(esign_id: str, biz: str,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Pull live status on demand — the manual fallback for a webhook
    that never arrived. The work of a completion lives in _apply_status
    so this and the webhook can never drift apart."""
    biz_row = _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/esign_documents?id=eq.{esign_id}&business_id=eq.{biz}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "document not found")
    doc = rows[0]

    new_status = await _live_status(doc["document_id"])
    if new_status is None:
        raise HTTPException(502, "couldn't reach the e-sign provider")

    result = await _apply_status(doc, biz_row, new_status)
    return {"ok": True, **result}


@router.post("/webhook")
async def esign_webhook(payload: Dict[str, Any]) -> Dict[str, Any]:
    """BoldSign tells us a document moved. PUBLIC by necessity.

    THE PAYLOAD IS NEVER TRUSTED. It names a document id and nothing
    else is read from it — we look that id up in OUR table, and then ask
    BoldSign directly what the status is. So the webhook is a NUDGE TO
    GO CHECK, not a source of truth, and the worst an unauthenticated
    caller achieves is making us re-poll a document we already own. That
    is a rate-limit question, not a security one, which is why this
    endpoint does not depend on a shared secret being configured
    correctly before signatures start working.

    BOLDSIGN_WEBHOOK_SECRET is honoured when set — as a cheap filter
    against noise, not as the thing standing between an attacker and a
    forged completion. Nothing here can forge a completion.

    Always 200. A webhook endpoint that returns errors gets retried,
    then throttled, then disabled by the provider; an unknown document
    is a fact to log, not a failure to advertise."""
    secret = (os.environ.get("BOLDSIGN_WEBHOOK_SECRET") or "").strip()
    if secret:
        got = str(payload.get("secret") or "").strip()
        if got != secret:
            logger.warning("[esign] webhook rejected: secret mismatch")
            return {"ok": True, "ignored": "auth"}

    # BoldSign nests the id differently across event shapes; take the
    # first one that looks like an id rather than pinning one path.
    data = payload.get("data") or {}
    doc_obj = data.get("documentId") or data.get("document") or {}
    document_id = (
        payload.get("documentId")
        or data.get("documentId")
        or (doc_obj.get("documentId") if isinstance(doc_obj, dict) else None)
        or ""
    )
    document_id = str(document_id).strip()
    if not document_id:
        logger.info("[esign] webhook with no document id — ignored")
        return {"ok": True, "ignored": "no_document_id"}

    rows = sb_clients.sb_get_as_service(
        f"/esign_documents?document_id=eq.{document_id}&select=*&limit=1") or []
    if not rows:
        logger.info(f"[esign] webhook for unknown document {document_id} — ignored")
        return {"ok": True, "ignored": "unknown_document"}
    doc = rows[0]

    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{doc['business_id']}&select=id,name,owner_id&limit=1") or []
    if not biz_rows:
        logger.warning(f"[esign] webhook: business missing for {document_id}")
        return {"ok": True, "ignored": "business_missing"}

    try:
        new_status = await _live_status(document_id)
    except HTTPException:
        # Provider unreachable or key unset. Refresh remains the fallback.
        logger.warning(f"[esign] webhook could not verify {document_id}")
        return {"ok": True, "ignored": "unverified"}
    if new_status is None:
        return {"ok": True, "ignored": "unverified"}

    result = await _apply_status(doc, biz_rows[0], new_status)
    if result.get("changed"):
        logger.info(f"[esign] webhook applied {result['status']} to {document_id}")
    return {"ok": True, **result}
