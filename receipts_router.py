"""
receipts_router.py — Rails demand-driven arc — receipt capture.

The ruling: don't build the OCR — Chief reads the receipt. A vision
model extracts vendor, amount, date, tax, and the 5-bucket category
from a photo; the original image lands in the business-documents
bucket so the number always has its proof at tax time.

Flow (one endpoint, review-first by design):
  POST /receipts/scan  (owner-gated, multipart)
    → stores the image → Chief reads it → returns the extraction +
      storage path. The FRONTEND creates the expense after the human
      confirms — the model proposes, the practitioner disposes, and a
      misread never writes a book entry by itself.

Env: RECEIPT_MODEL (default claude-haiku-4-5-20251001 — cheap, vision-
capable; a receipt is not a design review).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import uuid
from typing import Any, Dict

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import llm_call
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("receipts_router")

router = APIRouter(prefix="/receipts", tags=["receipts"])

_BUCKET = "business-documents"
_MAX_BYTES = 8 * 1024 * 1024
_MEDIA_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
_BUCKETS_5 = ("tax", "owner_pay", "operating", "savings", "other")

_PROMPT = (
    "This is a photo of a purchase receipt. Extract the facts and answer "
    "with ONLY a JSON object — no prose, no markdown fence:\n"
    "{\n"
    '  "vendor": "merchant name as printed",\n'
    '  "amount": total charged as a number (the final total, after tax),\n'
    '  "tax_amount": sales tax as a number or null,\n'
    '  "date": "YYYY-MM-DD" or null if unreadable,\n'
    '  "category": one of "operating" | "tax" | "owner_pay" | "savings" | "other" '
    "— operating for business supplies/materials/services, other when unsure,\n"
    '  "description": one short line saying what was bought\n'
    "}\n"
    "If the image is not a receipt, answer {\"not_a_receipt\": true}."
)


def _owner(biz: str, user: AuthedUser) -> Dict[str, Any]:
    rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{biz}&select=id,owner_id&limit=1") or []
    if not rows:
        raise HTTPException(404, "business not found")
    if str(rows[0].get("owner_id")) != str(user.id):
        raise HTTPException(403, "not authorized")
    return rows[0]


def parse_extraction(text: str) -> Dict[str, Any]:
    """The model's reply → a clean dict. Tolerates fences and prose
    tails (the atelier fragment lesson); never raises."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"not_a_receipt": True}
    try:
        raw = json.loads(m.group(0))
    except Exception:
        return {"not_a_receipt": True}
    if raw.get("not_a_receipt"):
        return {"not_a_receipt": True}
    out: Dict[str, Any] = {"not_a_receipt": False}
    out["vendor"] = str(raw.get("vendor") or "")[:120]
    try:
        out["amount"] = round(float(raw.get("amount")), 2)
    except (TypeError, ValueError):
        out["amount"] = None
    try:
        out["tax_amount"] = round(float(raw.get("tax_amount")), 2)
    except (TypeError, ValueError):
        out["tax_amount"] = None
    date = str(raw.get("date") or "")
    out["date"] = date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else None
    cat = str(raw.get("category") or "").strip().lower()
    out["category"] = cat if cat in _BUCKETS_5 else "other"
    out["description"] = str(raw.get("description") or "")[:200]
    return out


@router.post("/scan")
async def scan_receipt(
    business_id: str = Form(...),
    file: UploadFile = File(...),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    _owner(business_id, user)

    media_type = (file.content_type or "").lower()
    ext = _MEDIA_TYPES.get(media_type)
    if not ext:
        raise HTTPException(400, "send a JPEG, PNG, or WebP photo of the receipt")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "empty file")
    if len(blob) > _MAX_BYTES:
        raise HTTPException(413, "receipt photo is over 8 MB — retake at a lower resolution")

    # 1) Store the original FIRST — the proof matters more than the parse.
    path = f"{business_id}/receipts/{uuid.uuid4().hex}.{ext}"
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as c:
        up = await c.post(
            f"{supabase_url}/storage/v1/object/{_BUCKET}/{path}",
            headers={"Authorization": f"Bearer {service_key}",
                     "apikey": service_key,
                     "Content-Type": media_type},
            content=blob,
        )
    if up.status_code >= 400:
        logger.error(f"[receipts] storage upload failed {up.status_code}: {up.text[:200]}")
        raise HTTPException(502, "couldn't store the receipt image")

    # 2) Chief reads it.
    model = os.environ.get("RECEIPT_MODEL", "claude-haiku-4-5-20251001")
    try:
        import asyncio
        resp = await asyncio.to_thread(llm_call.post, {
            "model": model,
            "max_tokens": 400,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {
                        "type": "base64", "media_type": media_type,
                        "data": base64.b64encode(blob).decode("ascii")}},
                    {"type": "text", "text": _PROMPT},
                ],
            }],
        }, task="receipt-scan", timeout=90.0)
        if resp.status_code >= 400:
            raise RuntimeError(f"vision {resp.status_code}: {resp.text[:200]}")
        extracted = parse_extraction(llm_call.text_of(resp.json()))
    except Exception as e:
        logger.warning(f"[receipts] vision read failed (image kept): {e}")
        # The image is stored — the practitioner can still attach it and
        # type the numbers; extraction failure must not lose the proof.
        extracted = {"not_a_receipt": False, "vendor": "", "amount": None,
                     "tax_amount": None, "date": None, "category": "other",
                     "description": "", "read_failed": True}

    logger.info(f"[receipts] scanned biz={business_id[:8]} "
                f"vendor={extracted.get('vendor') or '?'} amount={extracted.get('amount')}")
    return {"ok": True, "receipt_path": path, "bucket": _BUCKET,
            "extracted": extracted}
