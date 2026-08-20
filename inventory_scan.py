"""
inventory_scan.py — SCAN THE SHELF, rung one (2026-08-20).

THE GAP THIS CLOSES
  Stock tracking exists (offerings.inventory_qty, the Stock tab, the
  reorder brain that drafts the PO). What did not exist was a cheap way
  to say WHICH product you are holding. Every restock and every count
  started with a human typing a name into a form, so it didn't happen,
  so the number on file rotted away from the number on the shelf.

THE RULING THAT SHAPES THE WHOLE THING
  A photo is an excellent instrument for IDENTITY and a bad one for
  QUANTITY. A vision model will tell you reliably that this is "Layrite
  Superhold Pomade, 4 oz". It will NOT reliably tell you there are
  fourteen of them, and a confident wrong count is worse than no
  feature — the UI would look certain while the number drifted.

  So: the camera identifies, the human counts. This endpoint READS.
  It writes no stock, creates no product, and returns a proposal the
  practitioner confirms — the same review-first contract as
  receipts_router (the model proposes, the practitioner disposes).

THE BARCODE IS THE PAYLOAD, NOT THE PIXELS
  A barcode is an exact key, and the browser decodes one for free
  (BarcodeDetector, native in Chromium and the Android WebView). So the
  frontend decodes locally and sends the digits; an exact hit on
  offerings.barcode costs ZERO tokens and cannot be wrong. Vision is the
  fallback for unlabeled goods, torn packaging, and iOS Safari.

  offerings.barcode is stamped the FIRST time a practitioner confirms a
  match (POST .../{offering_id}/barcode below). That is the learning
  loop: scan #1 pays for a vision read, scans #2..#400 are free and
  exact. Without it the catalog never gets sharper and fuzzy matching
  quietly breeds duplicate products.

WHAT IT REFUSES TO DO
  • Count from a photo.
  • Write anything during a scan.
  • Propose a NEW product without first checking what they already
    carry — a scanner that silently creates a second "Fade Pomade 4oz"
    is a shadow catalog with a camera on it.

Endpoints (both manager+, the same ladder as every other stock write):
  POST /store/inventory/{business_id}/scan             — identify (read-only)
  POST /store/inventory/{business_id}/{offering_id}/barcode — teach the code

Env: PRODUCT_SCAN_MODEL (default claude-haiku-4-5-20251001 — reading a
label is not a design review).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

import llm_call
import sb_clients
from auth_supabase import AuthedUser, require_user

logger = logging.getLogger("inventory_scan")

router = APIRouter(tags=["store"])

_MAX_BYTES = 8 * 1024 * 1024
_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}

# A barcode is digits (UPC-A 12, EAN-13 13, EAN-8 8) or, for CODE_128 /
# CODE_39 shelf labels, an alphanumeric run. Anything with whitespace or
# punctuation is a misread, not a code — reject rather than store junk
# that will never match again.
_BARCODE_RE = re.compile(r"^[A-Za-z0-9\-]{6,48}$")

# Fuzzy-match floor. Below this we propose a NEW product rather than
# claim a match: a wrong "this is it" writes stock onto the wrong row,
# which is a silent corruption, while a spurious "new product" is a
# visible one the practitioner cancels.
_MATCH_FLOOR = 0.72

_SELLABLE = {"product", "course", "package"}

_SCAN_FIELDS = ("id,name,sku,barcode,category,current_price,inventory_qty,"
                "image_url,description")

_PROMPT = (
    "This is a photo of a single retail product a small business sells. "
    "Read what is PRINTED on it. Answer with ONLY a JSON object — no "
    "prose, no markdown fence:\n"
    "{\n"
    '  "name": "product name as printed, including size if shown '
    '(e.g. \\"Layrite Superhold Pomade 4oz\\")",\n'
    '  "brand": "brand name or null",\n'
    '  "barcode": "the digits under the barcode if legible, else null",\n'
    '  "sku": "a printed SKU/item number if shown, else null",\n'
    '  "price": the printed retail price as a number, or null if no price '
    "is printed,\n"
    '  "description": "one short line a shopper would understand",\n'
    '  "category": "product" always — this catalog only stocks goods\n'
    "}\n"
    "Do NOT guess how many units are present and do NOT invent a barcode "
    "you cannot read — null is the correct answer when it is unreadable. "
    'If the image is not a product, answer {"not_a_product": true}.'
)


# ─── Pure helpers (unit-tested; no network) ──────────────────────────


def clean_barcode(raw: Optional[str]) -> Optional[str]:
    """A scanned code we are willing to store. None for junk — a barcode
    we cannot trust is worse than none, because it becomes a permanent
    key that matches the wrong thing forever."""
    s = (raw or "").strip().upper()
    if not s or not _BARCODE_RE.match(s):
        return None
    return s


def parse_product(text: str) -> Dict[str, Any]:
    """The model's reply → a clean dict. Tolerates fences and prose tails
    (the atelier fragment lesson); never raises."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {"not_a_product": True}
    try:
        raw = json.loads(m.group(0))
    except Exception:
        return {"not_a_product": True}
    if not isinstance(raw, dict) or raw.get("not_a_product"):
        return {"not_a_product": True}

    out: Dict[str, Any] = {"not_a_product": False}
    out["name"] = str(raw.get("name") or "").strip()[:200]
    out["brand"] = (str(raw.get("brand")).strip()[:120]
                    if raw.get("brand") else None)
    out["barcode"] = clean_barcode(
        str(raw.get("barcode")) if raw.get("barcode") else None)
    out["sku"] = (str(raw.get("sku")).strip()[:80] if raw.get("sku") else None)
    try:
        price = round(float(raw.get("price")), 2)
        out["price"] = price if price > 0 else None
    except (TypeError, ValueError):
        out["price"] = None
    out["description"] = str(raw.get("description") or "").strip()[:500]
    # Category is fixed: this door only stocks goods. Letting the model
    # pick would let it answer "course" for a boxed DVD and drop the row
    # into a category the store checkout treats differently.
    out["category"] = "product"
    if not out["name"]:
        return {"not_a_product": True}
    return out


def _norm(s: Optional[str]) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _tokens(s: Optional[str]) -> List[str]:
    return [t for t in _norm(s).split() if len(t) > 1]


def name_score(a: Optional[str], b: Optional[str]) -> float:
    """How much two product names look like the same thing. Blends
    whole-string similarity with token containment, because "Layrite
    Superhold 4oz" vs "Superhold Pomade" shares every meaningful word
    while scoring poorly as raw strings."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ratio = SequenceMatcher(None, na, nb).ratio()
    ta, tb = set(_tokens(a)), set(_tokens(b))
    if ta and tb:
        contained = len(ta & tb) / min(len(ta), len(tb))
    else:
        contained = 0.0
    return max(ratio, (ratio + contained) / 2)


def best_match(extracted: Dict[str, Any],
               offerings: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The offering this photo most likely IS, or None. Pure."""
    cand = f"{extracted.get('brand') or ''} {extracted.get('name') or ''}"
    sku = _norm(extracted.get("sku"))
    best, best_s = None, 0.0
    for o in offerings:
        s = max(name_score(cand, o.get("name")),
                name_score(extracted.get("name"), o.get("name")))
        if sku and _norm(o.get("sku")) == sku:
            s = max(s, 0.95)
        if s > best_s:
            best, best_s = o, s
    if best is None or best_s < _MATCH_FLOOR:
        return None
    return {"offering": best, "score": round(best_s, 3)}


def _shape(o: Dict[str, Any]) -> Dict[str, Any]:
    """The offering fields the scan drawer renders."""
    inv = o.get("inventory_qty")
    return {"id": o.get("id"), "name": o.get("name"), "sku": o.get("sku"),
            "barcode": o.get("barcode"), "category": o.get("category"),
            "current_price": o.get("current_price"),
            "inventory_qty": (int(inv) if inv is not None else None),
            "tracked": inv is not None,
            "image_url": o.get("image_url")}


# ─── The scan ────────────────────────────────────────────────────────


def _sellable_offerings(business_id: str) -> List[Dict[str, Any]]:
    rows = sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&is_active=eq.true"
        f"&select={_SCAN_FIELDS}&order=created_at.asc&limit=500") or []
    return [o for o in rows if (o.get("category") or "") in _SELLABLE]


async def _read_label(blob: bytes, media_type: str) -> Dict[str, Any]:
    """Chief reads the packaging. Never raises — a failed read still has
    to leave the practitioner a usable form."""
    model = os.environ.get("PRODUCT_SCAN_MODEL", "claude-haiku-4-5-20251001")
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
        }, task="product-scan", timeout=90.0)
        if resp.status_code >= 400:
            raise RuntimeError(f"vision {resp.status_code}: {resp.text[:200]}")
        return parse_product(llm_call.text_of(resp.json()))
    except Exception as e:
        logger.warning(f"[scan] vision read failed: {e}")
        return {"not_a_product": False, "name": "", "brand": None,
                "barcode": None, "sku": None, "price": None,
                "description": "", "category": "product", "read_failed": True}


@router.post("/store/inventory/{business_id}/scan")
async def scan_product(
    business_id: str,
    barcode: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    user: AuthedUser = Depends(require_user),
) -> Dict[str, Any]:
    """Identify the product in front of the camera. READ-ONLY.

    Returns one of four results, and the drawer renders a different
    confirmation for each:

      exact  — barcode hit an offering. Free, certain. Adjust stock.
      likely — the label reads like something they already carry.
               Confirming stamps the barcode (the learning loop).
      new    — nothing matched; here is a prefilled create form.
      unreadable — we could not read it; the form opens anyway.
    """
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")

    code = clean_barcode(barcode)
    offerings = _sellable_offerings(business_id)

    # 1) The free path. An exact barcode is not a guess.
    if code:
        for o in offerings:
            if clean_barcode(o.get("barcode")) == code:
                logger.info(f"[scan] exact biz={business_id[:8]} code={code}")
                return {"ok": True, "result": "exact", "barcode": code,
                        "offering": _shape(o), "extracted": None}
        # People type the UPC into the SKU box before this feature
        # existed — honour that as an exact hit and let the confirm
        # stamp the real column.
        for o in offerings:
            if (o.get("sku") or "").strip().upper() == code:
                logger.info(f"[scan] sku-hit biz={business_id[:8]} code={code}")
                return {"ok": True, "result": "exact", "barcode": code,
                        "offering": _shape(o), "extracted": None}

    # 2) No photo to fall back on — say so plainly rather than guessing.
    if file is None:
        if not code:
            raise HTTPException(400, "send a barcode, a photo, or both")
        return {"ok": True, "result": "new", "barcode": code,
                "extracted": None, "offering": None}

    media_type = (file.content_type or "").lower().split(";")[0]
    if media_type not in _MEDIA_TYPES:
        raise HTTPException(400, "send a JPEG, PNG, or WebP photo")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "empty file")
    if len(blob) > _MAX_BYTES:
        raise HTTPException(413, "photo is over 8 MB — retake at a lower resolution")

    extracted = await _read_label(blob, media_type)
    if extracted.get("not_a_product"):
        return {"ok": True, "result": "unreadable", "barcode": code,
                "extracted": None, "offering": None,
                "note": "That photo doesn't look like a product."}
    if extracted.get("read_failed"):
        return {"ok": True, "result": "unreadable", "barcode": code,
                "extracted": None, "offering": None,
                "note": "Couldn't read the label — fill it in yourself."}

    # 3) A barcode the MODEL read is still exact if it hits a row.
    seen = code or extracted.get("barcode")
    if not code and extracted.get("barcode"):
        for o in offerings:
            if clean_barcode(o.get("barcode")) == extracted["barcode"]:
                return {"ok": True, "result": "exact",
                        "barcode": extracted["barcode"],
                        "offering": _shape(o), "extracted": extracted}

    # 4) Fuzzy — a proposal, never a certainty.
    hit = best_match(extracted, offerings)
    if hit:
        logger.info(f"[scan] likely biz={business_id[:8]} "
                    f"score={hit['score']} name={extracted.get('name')!r}")
        return {"ok": True, "result": "likely", "barcode": seen,
                "offering": _shape(hit["offering"]),
                "score": hit["score"], "extracted": extracted}

    logger.info(f"[scan] new biz={business_id[:8]} name={extracted.get('name')!r}")
    return {"ok": True, "result": "new", "barcode": seen,
            "offering": None, "extracted": extracted}


# ─── The learning loop ───────────────────────────────────────────────


class BarcodeBody(BaseModel):
    barcode: Optional[str] = None   # null clears


@router.post("/store/inventory/{business_id}/{offering_id}/barcode")
def set_barcode(business_id: str, offering_id: str, body: BarcodeBody,
                user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Teach the system this product's code. Manager+, because it is an
    inventory attribute on the same ladder as a stock adjustment — the
    person doing the counting has to be able to do the teaching, or the
    catalog never gets sharper.

    One code = one product, per business (unique partial index). A
    conflict is answered by NAME so the practitioner can see which row
    already owns it instead of reading a Postgres error.
    """
    from business_users_router import require_role
    from store_router import _inventory_offering_or_404
    require_role(business_id, str(user.id), "manager")
    _inventory_offering_or_404(business_id, offering_id)

    code = clean_barcode(body.barcode) if body.barcode is not None else None
    if body.barcode and not code:
        raise HTTPException(400, "that doesn't look like a barcode")

    if code:
        clash = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&barcode=eq.{code}"
            "&select=id,name&limit=1") or []
        if clash and str(clash[0].get("id")) != str(offering_id):
            raise HTTPException(
                409, f"that barcode already belongs to "
                     f"'{clash[0].get('name') or 'another product'}'")

    sb_clients.sb_patch_as_service(
        f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}",
        {"barcode": code})
    return {"ok": True, "offering_id": offering_id, "barcode": code}
