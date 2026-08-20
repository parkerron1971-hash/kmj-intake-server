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

THE WRONG-ITEM GUARD (expect_offering_id)
  During a tally the practitioner is often adding to ONE named product —
  "six of these" — and the failure that costs them is grabbing the wrong
  bottle off the shelf. Pass the product they think they are scanning as
  `expect_offering_id` and a scan that resolves to something else comes
  back as result="mismatch", naming BOTH products, instead of quietly
  tallying onto the wrong row.

  It is free: both sides are already known, so the check is a string
  compare and never costs a model call.

THE PUBLIC DATABASES (product_lookup)
  A barcode is a global id, so when a public database already knows it,
  a scan fills the name, brand, size and photo for free. Coverage is
  good for food and drink and thin for everything else, so it is an
  ENRICHMENT that runs before the vision read, never a replacement for
  it. A miss costs a fraction of a second and then the camera reads the
  actual label, which works on anything.

REPLACEMENT, NOT JUST RECOGNITION
  The question a scan can answer is "have I seen this exact thing
  before?" The question a shop actually asks is bigger: "is this the
  thing that goes in that spot on the shelf?" A shop that switches from
  Layrite pomade to Suavecito pomade has not gained a product; it has
  replaced one. Treated as a brand-new item, the reorder point, the
  supplier and the alert threshold all have to be typed again, and the
  discontinued one sits in the catalog forever looking in stock.

  So a scan that finds nothing ALSO looks for a predecessor: something
  already carried that fills the same role. The test is deliberately a
  rubric rather than a table of product types — shared meaning-carrying
  words, minus brand, minus size — because a table of categories is
  wrong the first time somebody sells something nobody thought of.

  It is a QUESTION, never an action. Replacing carries the shelf logic
  across and offers to retire the old one; the practitioner decides.

THE STOCK-ONLY PRODUCT (why a manager can create one)
  POST /offerings is owner-gated, and rightly: it publishes a PRICED
  item to the practitioner's public storefront. That is a pricing and
  publishing decision, not a stock one. But a manager unpacking a box
  and finding something the catalog has never seen was dead-ended by
  that gate, in the exact flow this arc exists to make fast.

  So the split is by CONSEQUENCE rather than by table: a manager can
  create a product with NO PRICE. It is fully countable, scannable and
  receivable, and it is invisible to customers — _sellable_offerings in
  store_router already skips anything priced at or below zero, so a
  price-less product cannot appear in the store or be checked out. The
  owner sets a price when they want to sell it, and that one act is the
  publishing decision, made by the person whose decision it is.

Endpoints (all manager+, the same ladder as every other stock write):
  POST /store/inventory/{business_id}/scan             — identify (read-only)
  POST /store/inventory/{business_id}/{offering_id}/barcode — teach the code
  POST /store/inventory/{business_id}/product          — stock-only create

Env: PRODUCT_SCAN_MODEL (default claude-haiku-4-5-20251001 — reading a
label is not a design review).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

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


# Words that carry no meaning about what a product IS. Kept tiny on
# purpose: a long stopword list is a lookup table wearing a disguise,
# and it will delete the one word that mattered for somebody's vertical.
_NOISE = {"the", "and", "for", "with", "size", "new", "pack", "of"}

# A size token tells you how much, not what. "4oz" must not be the thing
# two products have in common, or every 4oz item on the shelf becomes a
# candidate to replace every other one.
_SIZE_RE = re.compile(r"^\d+(\.\d+)?(oz|ml|g|kg|l|lb|ct|pk|ea|x)?$")

# The same units standing alone, because "4 oz" tokenizes to "4" and
# "oz" and the unit would otherwise survive as if it described the
# product. Without this, every 4 oz item on the shelf shares a word
# with every other one.
_UNITS = {"oz", "ml", "kg", "lb", "ct", "pk", "ea", "fl", "gal", "qt", "pt"}

# A shared word only means something if the word does. Two products
# matching on "oil" alone are not obviously the same role — beard oil
# does not replace coconut oil — while "pomade" or "shampoo" carries
# real meaning. Length is a blunt proxy for specificity, and a blunt
# proxy is the right instrument here: the alternative is a category
# table, which is wrong the first time somebody stocks something nobody
# thought of.
_SPECIFIC_LEN = 4

def role_tokens(name: Optional[str], brand: Optional[str] = None) -> List[str]:
    """What a product IS, with the brand and the size stripped out.

    "Layrite Superhold Pomade 4oz" → ["superhold", "pomade"]

    Brand goes because a replacement is BY DEFINITION a different brand.
    Size goes because it says how much, not what.
    """
    brand_words = set(_tokens(brand)) if brand else set()
    out: List[str] = []
    for t in _tokens(name):
        if (t in brand_words or t in _NOISE or t in _UNITS
                or _SIZE_RE.match(t)):
            continue
        out.append(t)
    return out


def _leading_word(name: Optional[str]) -> Optional[str]:
    """The first meaning-carrying word of a product name — which, for
    most of retail, is the brand."""
    t = _tokens(name)
    return t[0] if t else None


def shared_role_words(a_tokens: List[str], b_tokens: List[str]) -> List[str]:
    """The meaning-carrying words two products have in common.

    Only words of real length count. Two products matching on "oil"
    alone are not the same role — beard oil does not replace coconut
    oil — while "pomade" or "shampoo" carries actual meaning. Length is
    a blunt proxy for specificity, and blunt is right here: the
    alternative is a table of product categories, which is wrong the
    first time somebody stocks something nobody thought of.
    """
    return sorted(
        {t for t in (set(a_tokens) & set(b_tokens)) if len(t) >= _SPECIFIC_LEN},
        key=len, reverse=True)


def replacement_candidates(extracted: Dict[str, Any],
                           offerings: List[Dict[str, Any]],
                           limit: int = 3) -> List[Dict[str, Any]]:
    """Products already carried that this new one plausibly replaces.

    The test is: do they share a specific, meaning-carrying word once
    brand and size are stripped out? Deliberately NOT a ratio over token
    counts — a catalog name carries its brand and we cannot always tell
    which word that is, so a verbose brand would sink a real match
    ("Layrite Superhold Pomade" vs "Firme Hold Pomade" share the only
    word that matters and almost nothing else).

    Anything scoring as the SAME product is excluded: that is a match,
    and offering to replace a thing with itself is how somebody archives
    the row they just scanned.

    Ranked by emptiness first — a product sitting at zero is far likelier
    to be the one being replaced than a full shelf, and it is the most
    useful signal available without asking — then by how specific the
    shared word is.
    """
    cand_name = f"{extracted.get('brand') or ''} {extracted.get('name') or ''}".strip()
    if not cand_name:
        return []
    brand = extracted.get("brand")
    mine = role_tokens(extracted.get("name"), brand)
    if not mine:
        return []

    scored: List[Dict[str, Any]] = []
    for o in offerings:
        if name_score(cand_name, o.get("name")) >= _MATCH_FLOOR:
            continue
        # The scanned brand comes off the shelf name too, for the rare
        # case where it survived in `mine` (a brand written differently
        # in the name than in the brand field). The brand-only match is
        # caught properly by the leading-word guard just below — this
        # alone does NOT prevent it.
        theirs = role_tokens(o.get("name"), brand)
        shared = shared_role_words(mine, theirs)
        if not shared:
            continue
        # A single shared word that LEADS both names is a brand, not a
        # role. "Suave Body Wash" is not a replacement for "Suave
        # Conditioner" — they share a maker, not a job. This bites when
        # no brand field came back at all (the databases missed and the
        # label gave none), so the brand is still sitting in the name
        # where nothing has stripped it.
        #
        # Two or more shared words survive: that is a real signal
        # whatever the first one happens to be.
        if (len(shared) == 1
                and shared[0] == _leading_word(extracted.get("name"))
                and shared[0] == _leading_word(o.get("name"))):
            continue
        inv = o.get("inventory_qty")
        empty = inv is not None and int(inv) == 0
        scored.append({"offering": o, "shared": shared,
                       "because": shared[0], "empty": empty})

    scored.sort(key=lambda c: (c["empty"], len(c["because"]), len(c["shared"])),
                reverse=True)
    return scored[:limit]


def _shape_candidates(cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Replacement candidates, with the REASON attached. A suggestion
    that cannot say why it is suggesting something is a guess wearing a
    confident face — "both of these are a pomade" is checkable by the
    person holding the bottle."""
    return [{"offering": _shape(c["offering"]),
             "because": c["because"],
             "out_of_stock": c["empty"]} for c in cands]


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


def apply_expectation(result: Dict[str, Any],
                      expected: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """THE WRONG-ITEM GUARD. Pure.

    `expected` is the product the practitioner believes they are
    scanning (they pinned it, or they are adding "six of these"). When
    the scan resolves to a DIFFERENT known product, the answer stops
    being "here is what you scanned" and becomes "that is not the one" —
    naming both, because "wrong item" without saying which is a dead end
    at the exact moment somebody is holding two similar bottles.

    Three deliberate non-behaviours:
      • No expectation set → the result passes through untouched, so the
        one-off scan path is unaffected.
      • The expected product itself → passes through as the normal
        exact/likely answer. Confirming your own pin is the happy path.
      • An UNRECOGNISED scan (new/unreadable) is NOT relabelled a
        mismatch. We genuinely do not know what it is, and claiming "not
        the one" implies we identified it. `matches_expected: false`
        carries the fact without the false certainty.
    """
    if not expected:
        return result
    out = dict(result)
    out["expected_offering"] = expected
    got = (result.get("offering") or {}).get("id")
    same = got is not None and str(got) == str(expected.get("id"))
    out["matches_expected"] = same
    if got is not None and not same:
        out["result"] = "mismatch"
    return out


def merge_known(extracted: Optional[Dict[str, Any]],
                known: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A public database's record + what the camera read off the label.

    The database wins on identity — name, brand, size, photo — because
    it is a catalog entry somebody curated, not an inference from a
    photograph of a curved bottle in shop lighting. The label wins on
    everything the database does not carry: the printed price, an item
    number, whatever the packaging says about the thing.

    Either side may be missing. Both missing returns None, and the
    practitioner types it themselves.
    """
    if not known and not extracted:
        return None
    if not known:
        return extracted
    out = dict(extracted or {})
    out["not_a_product"] = False
    out["name"] = known.get("name") or out.get("name") or ""
    out["brand"] = known.get("brand") or out.get("brand")
    out["barcode"] = known.get("barcode") or out.get("barcode")
    if known.get("image_url"):
        out["image_url"] = known["image_url"]
    if not (out.get("description") or "").strip():
        out["description"] = known.get("description") or ""
    out.setdefault("sku", None)
    out.setdefault("price", None)
    out["category"] = "product"
    out["found_in"] = known.get("source")
    return out


@router.post("/store/inventory/{business_id}/scan")
async def scan_product(
    business_id: str,
    barcode: Optional[str] = Form(default=None),
    expect_offering_id: Optional[str] = Form(default=None),
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
      mismatch — expect_offering_id was set and this is a DIFFERENT
               known product. Both are named. See apply_expectation.
    """
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")

    code = clean_barcode(barcode)
    offerings = _sellable_offerings(business_id)
    expected = None
    if expect_offering_id:
        expected = next((_shape(o) for o in offerings
                         if str(o.get("id")) == str(expect_offering_id)), None)

    def answer(payload: Dict[str, Any]) -> Dict[str, Any]:
        return apply_expectation(payload, expected)

    # 1) The free path. An exact barcode is not a guess.
    if code:
        for o in offerings:
            if clean_barcode(o.get("barcode")) == code:
                logger.info(f"[scan] exact biz={business_id[:8]} code={code}")
                return answer({"ok": True, "result": "exact", "barcode": code,
                               "offering": _shape(o), "extracted": None})
        # People type the UPC into the SKU box before this feature
        # existed — honour that as an exact hit and let the confirm
        # stamp the real column.
        for o in offerings:
            if (o.get("sku") or "").strip().upper() == code:
                logger.info(f"[scan] sku-hit biz={business_id[:8]} code={code}")
                return answer({"ok": True, "result": "exact", "barcode": code,
                               "offering": _shape(o), "extracted": None})

    # 2) No photo. The code alone is still worth something: a public
    #    database may already know what it is, for free.
    if file is None:
        if not code:
            raise HTTPException(400, "send a barcode, a photo, or both")
        import product_lookup
        known = await product_lookup.lookup(code)
        merged = merge_known(None, known)
        return answer({"ok": True, "result": "new", "barcode": code,
                       "extracted": merged, "offering": None,
                       "found_in": (known or {}).get("source"),
                       "replaces": _shape_candidates(
                           replacement_candidates(merged or {}, offerings))})

    media_type = (file.content_type or "").lower().split(";")[0]
    if media_type not in _MEDIA_TYPES:
        raise HTTPException(400, "send a JPEG, PNG, or WebP photo")
    blob = await file.read()
    if not blob:
        raise HTTPException(400, "empty file")
    if len(blob) > _MAX_BYTES:
        raise HTTPException(413, "photo is over 8 MB — retake at a lower resolution")

    # The camera read and the database lookup are independent, so they
    # run at once — asking the world about a barcode must not add a
    # second to a scan that was going to read the label anyway.
    import product_lookup
    extracted, known = await asyncio.gather(
        _read_label(blob, media_type),
        product_lookup.lookup(code or ""),
    )
    if extracted.get("not_a_product") or extracted.get("read_failed"):
        # The label was no help — but if the barcode is in a public
        # database we still know exactly what this is.
        merged = merge_known(None, known)
        if merged:
            return answer({"ok": True, "result": "new", "barcode": code,
                           "extracted": merged, "offering": None,
                           "found_in": (known or {}).get("source"),
                           "replaces": _shape_candidates(
                               replacement_candidates(merged, offerings))})
        return answer({"ok": True, "result": "unreadable", "barcode": code,
                       "extracted": None, "offering": None,
                       "note": ("That photo doesn't look like a product."
                                if extracted.get("not_a_product")
                                else "Couldn't read the label — fill it in yourself.")})

    extracted = merge_known(extracted, known) or extracted

    # 3) A barcode the MODEL read is still exact if it hits a row.
    seen = code or extracted.get("barcode")
    if not code and extracted.get("barcode"):
        for o in offerings:
            if clean_barcode(o.get("barcode")) == extracted["barcode"]:
                return answer({"ok": True, "result": "exact",
                               "barcode": extracted["barcode"],
                               "offering": _shape(o), "extracted": extracted})

    # 4) Fuzzy — a proposal, never a certainty.
    hit = best_match(extracted, offerings)
    if hit:
        logger.info(f"[scan] likely biz={business_id[:8]} "
                    f"score={hit['score']} name={extracted.get('name')!r}")
        return answer({"ok": True, "result": "likely", "barcode": seen,
                       "offering": _shape(hit["offering"]),
                       "score": hit["score"], "extracted": extracted})

    logger.info(f"[scan] new biz={business_id[:8]} name={extracted.get('name')!r}")
    return answer({"ok": True, "result": "new", "barcode": seen,
                   "offering": None, "extracted": extracted,
                   "found_in": (known or {}).get("source"),
                   "replaces": _shape_candidates(
                       replacement_candidates(extracted, offerings))})


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


# ─── The stock-only product ──────────────────────────────────────────


class StockProductBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    inventory_qty: Optional[int] = Field(default=0, ge=0)
    sku: Optional[str] = Field(default=None, max_length=80)
    barcode: Optional[str] = Field(default=None, max_length=48)
    description: Optional[str] = Field(default=None, max_length=500)
    image_url: Optional[str] = Field(default=None, max_length=600)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s[:60] or "product"


def free_slug(business_id: str, base: str) -> str:
    """A slug nobody is using. The catalog has a UNIQUE index on
    (business_id, lower(slug)), and a manager naming their second
    supplier's pomade "Pomade" should not have to think about that."""
    taken = {(r.get("slug") or "").lower() for r in (sb_clients.sb_get_as_service(
        f"/offerings?business_id=eq.{business_id}&slug=like.{base}*"
        "&select=slug&limit=50") or [])}
    if base not in taken:
        return base
    for n in range(2, 60):
        cand = f"{base}-{n}"
        if cand not in taken:
            return cand
    return f"{base}-{uuid.uuid4().hex[:6]}"


@router.post("/store/inventory/{business_id}/product")
def create_stock_product(business_id: str, body: StockProductBody,
                         user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """Add a product for STOCK purposes. Manager+, and deliberately
    price-less — see the module docstring. The owner turns it into
    something customers can buy by giving it a price.
    """
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")

    code = clean_barcode(body.barcode) if body.barcode else None
    if body.barcode and not code:
        raise HTTPException(400, "that doesn't look like a barcode")
    if code:
        clash = sb_clients.sb_get_as_service(
            f"/offerings?business_id=eq.{business_id}&barcode=eq.{code}"
            "&select=id,name&limit=1") or []
        if clash:
            raise HTTPException(
                409, f"that barcode already belongs to "
                     f"'{clash[0].get('name') or 'another product'}'")

    row = {
        "business_id": business_id,
        "name": body.name.strip(),
        "slug": free_slug(business_id, slugify(body.name)),
        "category": "product",
        "is_active": True,
        # No price ON PURPOSE. This is the whole gate: price-less means
        # the storefront filter skips it, so a manager cannot publish
        # something for sale — they can only make it countable.
        "current_price": None,
        "inventory_qty": int(body.inventory_qty or 0),
    }
    if body.sku:
        row["sku"] = body.sku.strip()[:80]
    if code:
        row["barcode"] = code
    if body.description:
        row["description"] = body.description.strip()[:500]
    if body.image_url:
        row["image_url"] = body.image_url.strip()[:600]

    created = sb_clients.sb_post_as_service("/offerings", row)
    if not (isinstance(created, list) and created):
        logger.warning(f"[scan] stock-product create failed biz={business_id[:8]}")
        raise HTTPException(500, "Something went wrong on our end — please try again.")

    off = created[0]
    _emit_created_stock_event(business_id, off, user)
    return {"ok": True, "offering": _shape(off),
            "sellable": False,
            "note": "Added for stock. Give it a price to sell it."}


def _emit_created_stock_event(business_id: str, off: Dict[str, Any],
                              user: AuthedUser) -> None:
    """The starting count is a stock movement like any other — without
    this, a product's history would begin with an unexplained number."""
    qty = off.get("inventory_qty")
    if qty is None:
        return
    try:
        from store_router import _emit_stock_event
        _emit_stock_event(business_id, str(off.get("id")), off.get("name") or "",
                          delta=int(qty), new_qty=int(qty),
                          reason="added by scan",
                          actor=(getattr(user, "email", None) or str(user.id)))
    except Exception as e:
        logger.warning(f"[scan] create stock event failed (non-fatal): {e}")


# ─── Replacement ─────────────────────────────────────────────────────


class ReplacesBody(BaseModel):
    predecessor_id: str
    # None = decide from the shelf: a product sitting at zero is
    # discontinued, one with units left is still being sold through.
    archive_predecessor: Optional[bool] = None


@router.post("/store/inventory/{business_id}/{offering_id}/replaces")
def mark_replacement(business_id: str, offering_id: str, body: ReplacesBody,
                     user: AuthedUser = Depends(require_user)) -> Dict[str, Any]:
    """This product takes over from that one.

    What carries is the SHELF LOGIC and nothing else: the reorder point,
    the order quantity, the supplier, the low-stock threshold. Those are
    facts about a slot on a shelf — how fast it empties, who fills it —
    and they survive a change of brand. That is the whole reason this
    exists: a shop that switches pomade should not have to re-derive how
    fast pomade sells.

    What does NOT carry:
      • price — a different product costs a different amount, and
        inheriting a price is how a wrong one reaches a storefront.
      • the outstanding-order stamp — an order placed for the old
        product is still an order for the OLD product.
      • stock — the new one starts at what actually arrived.

    Manager+, and reversible: archiving is a flag, so a predecessor
    retired by mistake comes back.
    """
    from business_users_router import require_role
    require_role(business_id, str(user.id), "manager")

    predecessor_guard(offering_id, body.predecessor_id)
    new = _inventory_offering_or_404_local(business_id, offering_id)
    old = _inventory_offering_or_404_local(business_id, body.predecessor_id)

    carried: Dict[str, Any] = {}
    for f in ("reorder_at", "reorder_qty", "supplier_name", "supplier_email"):
        if old.get(f) is not None:
            carried[f] = old[f]
    if carried:
        sb_clients.sb_patch_as_service(
            f"/offerings?id=eq.{offering_id}&business_id=eq.{business_id}", carried)

    # The alert threshold lives in the settings blob, keyed by offering.
    threshold = None
    biz_rows = sb_clients.sb_get_as_service(
        f"/businesses?id=eq.{business_id}&select=settings&limit=1") or []
    if biz_rows:
        settings = dict(biz_rows[0].get("settings") or {})
        store = dict(settings.get("store") or {})
        low = dict(store.get("low_stock") or {})
        if str(body.predecessor_id) in low:
            threshold = low[str(body.predecessor_id)]
            low[str(offering_id)] = threshold
            store["low_stock"] = low
            settings["store"] = store
            sb_clients.sb_patch_as_service(
                f"/businesses?id=eq.{business_id}", {"settings": settings})

    old_qty = old.get("inventory_qty")
    archive = body.archive_predecessor
    if archive is None:
        # Nothing left of it = discontinued. Units left = they are still
        # selling it through, and hiding it would strand real stock.
        archive = (old_qty is not None and int(old_qty) == 0)
    if archive:
        sb_clients.sb_patch_as_service(
            f"/offerings?id=eq.{body.predecessor_id}&business_id=eq.{business_id}",
            {"is_active": False, "archived_at": _now_iso()})

    try:
        import event_spine
        event_spine.emit("product_replaced", business_id, {
            "offering_id": str(offering_id),
            "offering_name": new.get("name") or "",
            "predecessor_id": str(body.predecessor_id),
            "predecessor_name": old.get("name") or "",
            "carried": sorted(carried.keys()) + (["threshold"] if threshold is not None else []),
            "archived_predecessor": bool(archive),
            "actor": (getattr(user, "email", None) or str(user.id))[:120],
        }, source="store")
    except Exception as e:
        logger.warning(f"[scan] replacement event failed (non-fatal): {e}")

    return {"ok": True,
            "carried": {**carried, **({"threshold": threshold} if threshold is not None else {})},
            "archived_predecessor": bool(archive),
            "predecessor_name": old.get("name") or ""}


def predecessor_guard(new_id: str, old_id: str) -> bool:
    """A product cannot replace itself — that would archive the row the
    practitioner just created and leave the shelf empty."""
    if str(new_id) == str(old_id):
        raise HTTPException(400, "a product can't replace itself")
    return True


def _inventory_offering_or_404_local(business_id: str, offering_id: str) -> Dict[str, Any]:
    from store_router import _inventory_offering_or_404
    return _inventory_offering_or_404(business_id, offering_id)


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
