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


@router.post("/{esign_id}/refresh")
async def esign_refresh(esign_id: str, biz: str,
                        user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Pull live status. A newly-completed document emits
    contract_signed — the spine event that finally has its emitter."""
    _owner(biz, user)
    rows = sb_clients.sb_get_as_service(
        f"/esign_documents?id=eq.{esign_id}&business_id=eq.{biz}&select=*&limit=1") or []
    if not rows:
        raise HTTPException(404, "document not found")
    doc = rows[0]

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(f"{BOLDSIGN_BASE}/v1/document/properties",
                        headers={"X-API-KEY": _api_key()},
                        params={"documentId": doc["document_id"]})
    if r.status_code >= 400:
        logger.warning(f"[esign] refresh failed {r.status_code}: {r.text[:200]}")
        raise HTTPException(502, "couldn't reach the e-sign provider")

    new_status = map_provider_status((r.json() or {}).get("status"))
    if not new_status or new_status == doc["status"]:
        return {"ok": True, "status": doc["status"], "changed": False}

    patch: Dict[str, Any] = {"status": new_status, "updated_at": _now_iso()}
    if new_status == "completed":
        patch["completed_at"] = _now_iso()
    sb_clients.sb_patch_as_service(f"/esign_documents?id=eq.{esign_id}", patch)

    if new_status == "completed":
        import event_spine
        event_spine.emit("contract_signed", biz, {
            "contract_ref": doc["document_id"],
            "title": doc.get("title"),
            "signer_email": doc.get("signer_email"),
        }, source="esign")
        import audit_log
        audit_log.record(biz, actor_type="system", verb="esign_completed",
                         summary=f"Signed: {doc.get('title')}",
                         target_type="esign_document", target_id=doc["document_id"],
                         source="esign")

    return {"ok": True, "status": new_status, "changed": True}
