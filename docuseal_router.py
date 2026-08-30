"""
docuseal_router.py — Rails demand-driven arc — e-sign, adapter #2.

The ruling stands: connect, don't build. Legally valid signatures carry
ESIGN Act compliance, audit trails, and tamper-evidence — DocuSeal owns
that engine. We own the chain that makes it matter: proposal →
signature → payment, without the moment ever leaving the system.

WHY THIS REPLACED BOLDSIGN (2026-08-30). Cost and shape. BoldSign's
Enterprise API tier starts around $30/mo; DocuSeal Cloud Pro is $20 a
seat with unlimited signature requests and webhooks included. The
switch was cheap because the seam was already here — adapter #1 kept
everything provider-specific inside six functions, and this file
changes those six. The completion chain below (status → spine event →
audit row → two emails) is untouched, which is the whole point of
having had a seam.

Surface (all owner-gated, and IDENTICAL to adapter #1 — the frontend
never learned which provider was behind it and did not have to change):
  POST /esign/send            — send a PDF (by URL — the contract
                                agent's pdf_url) to one signer.
                                DocuSeal emails them; nothing embedded
                                in v1.
  GET  /esign/list?biz=       — the business's sent documents.
  POST /esign/{id}/refresh    — pull live status from DocuSeal; a
                                newly-completed document emits
                                contract_signed on the event spine.
  POST /esign/webhook         — DocuSeal calls this when a document is
                                signed, declined, or expires. PUBLIC by
                                necessity (the provider has no login),
                                so it authenticates two ways: the
                                X-Docuseal-Signature HMAC, and looking
                                the document up on OUR side — a payload
                                naming an unknown submission is ignored,
                                never inserted.

WHY A WEBHOOK AND NOT JUST REFRESH. Refresh only tells the truth when
somebody is looking at the panel. A signature that lands on a Sunday
sat invisible until the next visit, and the confirmation email that
depends on it never went. The webhook makes completion an event that
happens TO the system rather than one it has to go and check for; the
refresh endpoint stays as the manual fallback for a missed delivery.

WHAT WE STORE AS document_id IS DOCUSEAL'S **SUBMISSION** ID. Said
plainly here because DocuSeal hands out two integer id sequences —
submissions and submitters — and they collide freely. A webhook body
carries both. Reading the wrong one looks up a document that either
does not exist or, worse, belongs to somebody else's agreement. See
_document_id_from_webhook, which branches on event_type rather than
hunting for the first thing that looks like an id.

ONE THING THAT GOT BETTER. BoldSign fetched the PDF from us BY URL, so
every send minted a signed storage link and handed it to a third
party's servers. DocuSeal takes the bytes inline (base64), and we were
already downloading them to hand over anyway — so the signed URL now
never leaves our network at all.

Env: DOCUSEAL_API_KEY (Railway). DOCUSEAL_API_BASE optionally points at
the EU host or a self-hosted instance. DOCUSEAL_WEBHOOK_SECRET is the
whsec_... value from the webhook's Security → HMAC tab.

v1 placement honesty, carried over unchanged: the signature field lands
at the bottom of page one (a signer needs at least one field, and our
generated proposal PDFs carry no DocuSeal text tags). Good enough for
real agreements; per-template placement is the day-two refinement.

COORDINATES ARE PIXELS, PAGE IS 1-INDEXED. The page index is documented
("Starts from 1"); the units are not, and DocuSeal's own pages say both
"exact pixel coordinates" and, elsewhere, imply 0-1 fractions. Pixels
is the safe reading to ship on, because the two guesses fail in very
different ways: pixel values handed to a fraction API are wildly
out of range and fail LOUDLY on the first send, while fractions handed
to a pixel API silently park a sub-pixel box in a corner and produce a
document that looks fine until someone tries to sign it. Verified on
the first live send; see SIGNATURE_AREA.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("docuseal_router")

router = APIRouter(prefix="/esign", tags=["esign"])

DOCUSEAL_BASE = (os.environ.get("DOCUSEAL_API_BASE")
                 or "https://api.docuseal.com").rstrip("/")
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)

# DocuSeal submission status → our vocabulary. Our words did not change
# when the provider did, which is why nothing downstream (the panel's
# status colours, the spine, the FE) needed touching.
#
# There is no DocuSeal equivalent of "revoked" — cancelling a submission
# archives it rather than moving it to a status of its own. The word
# stays in our vocabulary because rows written under adapter #1 still
# carry it; nothing emits it any more.
_STATUS_MAP = {
    "pending": "sent",
    "completed": "completed",
    "declined": "declined",
    "expired": "expired",
}

# Bottom of page one, matching adapter #1's geometry exactly so the
# switch is invisible on the paper. Page is 1-indexed per the spec.
SIGNATURE_AREA = {"x": 60, "y": 700, "w": 220, "h": 50, "page": 1}

# What we stamp on rows we write, and the only provider we can ask
# about a document. One constant so the insert and the refresh guard
# can never disagree about which adapter is current.
PROVIDER = "docuseal"


def _api_key() -> str:
    key = (os.environ.get("DOCUSEAL_API_KEY") or "").strip()
    if not key:
        raise HTTPException(503, "e-sign isn't configured (DOCUSEAL_API_KEY missing)")
    return key


def _auth_headers() -> Dict[str, str]:
    return {"X-Auth-Token": _api_key()}


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,name,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def map_provider_status(raw: Optional[str]) -> Optional[str]:
    """DocuSeal's status string → ours; None when unrecognized (keep
    the stored status rather than guessing)."""
    return _STATUS_MAP.get((raw or "").strip().lower())


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def submission_id_from_send(data: Any) -> str:
    """The submission id out of a POST /submissions/pdf response.

    Two shapes are in the wild — the submission object, and a bare list
    of the submitters it created — and both carry the submission id
    unambiguously (a submitter row names its `submission_id`). Reading
    whichever is in front of us costs four lines and removes a whole
    class of "it worked in the sandbox" surprise.

    Deliberately does NOT fall back to a submitter's own `id`: that is
    a different sequence and would give us a plausible-looking number
    that matches the wrong document forever."""
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and row.get("submission_id"):
                return str(row["submission_id"])
        return ""
    if isinstance(data, dict):
        if data.get("id"):
            return str(data["id"])
        for row in (data.get("submitters") or []):
            if isinstance(row, dict) and row.get("submission_id"):
                return str(row["submission_id"])
    return ""


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
    # See doc_guard: a blocked document can still be sent, deliberately,
    # and the override is recorded rather than silent.
    override_blockers: bool = False


@router.post("/send")
async def esign_send(body: SendBody,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    biz = _owner(body.business_id, user)
    headers = _auth_headers()
    email = (body.signer_email or "").strip().lower()
    if "@" not in email:
        raise HTTPException(400, "signer_email required")
    title = (body.title or "Agreement").strip()[:120]

    # The last door, and the one that matters most: after this the
    # document is in front of somebody being asked to sign it. When the
    # caller names the queue row it came from, the auditor reads the
    # CURRENT body — catching an edit made after generation. A send with
    # no source_ref is an upload we never wrote and cannot vouch for, so
    # there is nothing to check and nothing is claimed.
    if (body.source_ref or "").strip():
        import doc_guard
        try:
            row = doc_guard.load_document(body.source_ref.strip(), body.business_id)
        except HTTPException:
            row = None
        if row:
            doc_guard.require_sendable(
                row, business_id=body.business_id, actor_id=str(user.id),
                override=bool(body.override_blockers), door="esign")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        pdf = await c.get(body.pdf_url)
        if pdf.status_code >= 400 or not pdf.content:
            raise HTTPException(400, "couldn't fetch the PDF to send")

        # DocuSeal /submissions/pdf — a one-off submission, no template
        # left behind in the account. One signer, one signature field at
        # the bottom of page 1 (v1 honesty above).
        payload = {
            "name": title,
            "send_email": True,
            "message": {
                "subject": f"{biz.get('name') or 'We'} sent you {title} to sign",
                "body": (body.message
                         or f"{biz.get('name') or 'We'} sent this for your signature.")[:500],
            },
            "documents": [{
                "name": f"{title[:60]}.pdf",
                "file": base64.b64encode(pdf.content).decode(),
                "fields": [{
                    "name": "Signature",
                    "type": "signature",
                    "role": "Signer",
                    "required": True,
                    "areas": [dict(SIGNATURE_AREA)],
                }],
            }],
            "submitters": [{
                "name": (body.signer_name or email.split("@")[0])[:100],
                "email": email,
                "role": "Signer",
            }],
        }
        r = await c.post(f"{DOCUSEAL_BASE}/submissions/pdf",
                         headers=headers, json=payload)
    if r.status_code >= 400:
        logger.error(f"[esign] send failed {r.status_code}: {r.text[:400]}")
        raise HTTPException(502, f"e-sign send failed: {r.text[:200]}")

    try:
        doc_id = submission_id_from_send(r.json())
    except ValueError:
        doc_id = ""
    if not doc_id:
        raise HTTPException(502, "e-sign provider returned no submission id")

    inserted = sb_clients.sb_post_as_service("/esign_documents", {
        "business_id": body.business_id,
        "provider": PROVIDER,
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

    DocuSeal exposes `combined_document_url` on a completed submission —
    the signed PDF with the audit log bound in, which is a slightly
    better artefact to put in someone's inbox than the bare document
    adapter #1 attached. Falls back to the per-document list when the
    combined file is not built yet.

    Best-effort throughout: a confirmation that arrives without the PDF
    still tells both sides the thing is done, so a download failure
    downgrades the email rather than cancelling it."""
    if not document_id:
        return None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            r = await c.get(f"{DOCUSEAL_BASE}/submissions/{document_id}",
                            headers=_auth_headers())
            if r.status_code >= 400:
                logger.warning(f"[esign] submission read failed {r.status_code} "
                               f"for {document_id}")
                return None
            body = r.json() or {}
            url = body.get("combined_document_url")
            if not url:
                docs = await c.get(
                    f"{DOCUSEAL_BASE}/submissions/{document_id}/documents",
                    headers=_auth_headers())
                if docs.status_code < 400:
                    for d in ((docs.json() or {}).get("documents") or []):
                        if isinstance(d, dict) and d.get("url"):
                            url = d["url"]
                            break
            if not url:
                logger.warning(f"[esign] no signed file url for {document_id}")
                return None

            # The file URL is pre-signed storage, not an API route — it
            # takes no auth header and must not be sent one.
            f = await c.get(url)
        if f.status_code >= 400 or not f.content:
            logger.warning(f"[esign] download failed {f.status_code} for {document_id}")
            return None
        return base64.b64encode(f.content).decode()
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
    """Ask DocuSeal what the submission's status actually is."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        r = await c.get(f"{DOCUSEAL_BASE}/submissions/{document_id}",
                        headers=_auth_headers())
    if r.status_code >= 400:
        logger.warning(f"[esign] submission read failed {r.status_code}: {r.text[:200]}")
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

    # A row written by a retired adapter carries THAT provider's id, and
    # DocuSeal has never heard of it. Asking anyway 404s, which this
    # endpoint would dress up as "couldn't reach the e-sign provider" —
    # a frightening and completely wrong thing to say about a provider
    # that is fine. Answer honestly instead and leave the stored status
    # alone: it is the last status that was ever true for this document.
    provider = (doc.get("provider") or PROVIDER).strip().lower()
    if provider != PROVIDER:
        logger.info(f"[esign] refresh skipped: {esign_id} belongs to {provider}")
        return {"ok": True, "status": doc.get("status"), "changed": False,
                "retired_provider": provider,
                "note": (f"This document was sent with {provider}, which the "
                         f"system no longer uses. The status shown is the last "
                         f"one recorded for it.")}

    new_status = await _live_status(doc["document_id"])
    if new_status is None:
        raise HTTPException(502, "couldn't reach the e-sign provider")

    result = await _apply_status(doc, biz_row, new_status)
    return {"ok": True, **result}


# ── Webhook signature ────────────────────────────────────────────────
#
# DocuSeal signs each delivery:
#
#   X-Docuseal-Signature: <unix timestamp>.<hex hmac>
#
# where the HMAC is SHA-256 over the literal string "{t}.{raw body
# bytes}", keyed by the whsec_... value from the webhook's Security →
# HMAC tab. That is the same construction BoldSign used, in a different
# wrapper, so the hardened verifier from adapter #1 survives with only
# its parser swapped.
#
# THE RAW BODY IS THE MESSAGE. Re-serialising the parsed JSON changes
# whitespace and key order and the signature stops matching, which is
# why the handler below takes a Request and reads bytes rather than
# letting FastAPI hand it a dict.
#
# WE ALSO ACCEPT A PLAIN SHARED SECRET, and that is not sloppiness.
# DocuSeal offers two mutually exclusive ways to secure a webhook: the
# HMAC above, and a custom secret header whose value is the secret
# itself. A practitioner who configures the second one on a verifier
# that only understands the first gets every genuine delivery rejected
# and no error anywhere — which is precisely the silent-conditional-drop
# bug the signature test file was written to catch, re-introduced from
# the other side. Both are checked in constant time.
#
# ON THE TIMESTAMP. The documented advice is to reject deliveries older
# than five minutes, to stop replay. We log a stale timestamp and carry
# on instead, deliberately: a replay here is already inert. The handler
# does not believe the payload — it re-reads the real status from
# DocuSeal and _apply_status is idempotent — so replaying a genuine
# "form.completed" delivery either re-applies a status the row already
# has (a no-op) or is contradicted by the provider. Rejecting on age
# would buy nothing and would silently drop a legitimate late retry,
# which is the failure that actually costs a confirmation email.

SIGNATURE_HEADER = "X-Docuseal-Signature"
STALE_AFTER_SECONDS = 300


def _parse_signature_header(raw_header: str) -> tuple:
    """-> (timestamp:str|None, signature:str|None) from '<t>.<hex>'.

    A header with no '.' is the shared-secret form and carries no
    timestamp; it comes back as (None, <the whole value>) and the
    verifier compares it against the secret directly."""
    header = (raw_header or "").strip()
    if not header:
        return None, None
    ts, sep, sig = header.partition(".")
    if not sep:
        return None, header
    ts, sig = ts.strip(), sig.strip()
    return (ts or None), (sig or None)


def verify_webhook_signature(raw_body: bytes, header: str, secret: str) -> bool:
    """True when the delivery really came from DocuSeal.

    Constant-time throughout: a comparison that returns early leaks the
    signature one byte at a time."""
    if not secret:
        return True                      # unconfigured — see the handler
    ts, sig = _parse_signature_header(header)
    if not sig:
        return False

    # Shared-secret form: the header value IS the secret. Compared
    # against the WHOLE raw header rather than the parsed half, because
    # a secret that happens to contain a '.' would otherwise be split by
    # the parser and could never match — which is this file's own bug
    # class (a guard whose condition is never true) re-introduced one
    # layer down.
    if hmac.compare_digest(secret, (header or "").strip()):
        return True
    if ts is None:
        return False

    signed = ts.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig.lower())


def _timestamp_age(header: str) -> Optional[int]:
    ts, _ = _parse_signature_header(header)
    try:
        return int(time.time()) - int(ts)
    except (TypeError, ValueError):
        return None


def _document_id_from_webhook(payload: Dict[str, Any]) -> str:
    """The SUBMISSION id out of a delivery, chosen by event type.

    This is the sharpest edge in the whole adapter. DocuSeal sends two
    families of event:

      form.*        — the data object is a SUBMITTER. Its `id` is a
                      submitter id, and the submission is nested at
                      data.submission.id.
      submission.*  — the data object IS the submission, so data.id is
                      the one we want.

    Both ids are plain integers from separate sequences, so submitter 42
    and submission 42 both exist and neither looks wrong. Grabbing "the
    first field called id" therefore does not fail loudly — it quietly
    reads a number that matches some other business's agreement or
    nothing at all, forever. Branching on event_type is the only honest
    way to tell them apart, so that is what this does; anything it
    cannot classify falls through to the explicit submission fields and
    never to a bare `id`."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    event = str(payload.get("event_type") or payload.get("event") or "").strip().lower()

    submission = data.get("submission") if isinstance(data.get("submission"), dict) else {}

    if event.startswith("submission."):
        candidate = data.get("id")
    elif event.startswith("form."):
        candidate = submission.get("id")
    else:
        # Unknown event family: only ever trust fields that name a
        # submission explicitly.
        candidate = submission.get("id") or data.get("submission_id")

    if not candidate:
        candidate = submission.get("id") or data.get("submission_id")

    return str(candidate).strip() if candidate is not None else ""


@router.post("/webhook")
async def esign_webhook(request: Request) -> Dict[str, Any]:
    """DocuSeal tells us a submission moved. PUBLIC by necessity.

    TWO INDEPENDENT CHECKS, and the second is the one that matters.

    First, the X-Docuseal-Signature HMAC, when DOCUSEAL_WEBHOOK_SECRET
    is configured. That proves the delivery came from DocuSeal.

    Second, and regardless of the first: THE PAYLOAD IS NEVER BELIEVED.
    The only field read from it is a submission id, which is looked up
    in OUR table, and the status comes from asking DocuSeal directly. So
    the webhook is a NUDGE TO GO CHECK, not a source of truth. Even with
    no secret set, the worst an anonymous caller achieves is making us
    re-poll a document we already own — a rate-limit question, not a
    security one. That is why signatures still work before the secret is
    configured, rather than the feature appearing broken until someone
    finds the right dashboard page.

    Always 200. A webhook endpoint that returns errors gets retried,
    then throttled, then disabled by the provider; an unknown document
    is a fact to log, not a failure to advertise."""
    raw_body = await request.body()
    sig_header = request.headers.get(SIGNATURE_HEADER, "")
    secret = (os.environ.get("DOCUSEAL_WEBHOOK_SECRET") or "").strip()

    if secret:
        if not verify_webhook_signature(raw_body, sig_header, secret):
            logger.warning("[esign] webhook rejected: bad signature")
            return {"ok": True, "ignored": "bad_signature"}
        age = _timestamp_age(sig_header)
        if age is not None and age > STALE_AFTER_SECONDS:
            # Logged, not rejected — see the note above the verifier.
            logger.info(f"[esign] webhook signature is {age}s old (replay is inert here)")
    else:
        logger.info("[esign] webhook unsigned — DOCUSEAL_WEBHOOK_SECRET not set")

    try:
        payload = json.loads(raw_body or b"{}")
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        logger.info("[esign] webhook body was not JSON — ignored")
        return {"ok": True, "ignored": "bad_json"}

    document_id = _document_id_from_webhook(payload)
    if not document_id:
        logger.info("[esign] webhook with no submission id — ignored")
        return {"ok": True, "ignored": "no_document_id"}

    rows = sb_clients.sb_get_as_service(
        f"/esign_documents?document_id=eq.{document_id}&select=*&limit=1") or []
    if not rows:
        logger.info(f"[esign] webhook for unknown submission {document_id} — ignored")
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
