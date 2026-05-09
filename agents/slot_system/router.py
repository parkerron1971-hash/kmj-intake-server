"""Pass 4.0b.5 — Slot system FastAPI router.

Mounts under `/slots`. Diagnostic endpoints (PART 2-3):

  GET  /slots/_diag/unsplash               — raw Unsplash query result
  GET  /slots/_diag/build_query            — query composition only
  POST /slots/_diag/dalle                  — live DALL-E generate + persist
  GET  /slots/_diag/dalle_spend            — today's spend + can-generate
  POST /slots/_diag/dalle_spend_simulate   — append synthetic spend entry
  POST /slots/_diag/dalle_spend_clear      — drop synthetic-only entries
  POST /slots/_diag/storage_probe          — Supabase upload probe

User-facing endpoints (PART 5):

  GET  /slots/{business_id}                       — full slot manifest
  POST /slots/{business_id}/{slot_name}/upload    — practitioner upload
  POST /slots/{business_id}/{slot_name}/clear     — revert to default
  POST /slots/{business_id}/{slot_name}/reroll    — re-query default

Owner gating: NONE at this layer. Matches the existing pattern across
practitioner_profile_router, voice_depth_agent, public_site.py — all
business mutations are gated only by Supabase anon-key access. A real
per-business JWT layer is planned for Pass 4.0c+ and will retrofit
across all mutation surfaces in one shot rather than per-router.

Registration order: BEFORE `public_site_router` in
`kmj_intake_automation.py`, alongside the other agent routers. The
literal /_diag/... paths register BEFORE /{business_id} so the dynamic
route never shadows a diagnostic.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from agents.slot_system.unsplash_client import (
    build_unsplash_query,
    query_unsplash,
)
from agents.slot_system.dalle_client import (
    PER_SITE_DAILY_CAP_USD,
    SITE_IMAGES_BUCKET,
    _upload_site_image,
    _upload_site_image_debug,
    add_synthetic_spend_for_testing,
    build_dalle_prompt,
    can_dalle_generate,
    clear_synthetic_spend,
    dalle_cost,
    generate_dalle_image,
    generate_dalle_image_debug,
    get_site_dalle_spend_today,
)
from agents.slot_system.slot_storage import MAX_REROLLS_PER_DAY
from agents.slot_system import slot_storage
from agents.slot_system.slot_definitions import (
    SLOT_DEFINITIONS,
    get_slot_definition,
)
from agents.slot_system.slot_resolver import resolve_slot_url
from agents.slot_system.unsplash_client import (
    build_unsplash_query,
    query_unsplash,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slots", tags=["slots"])


@router.get("/_diag/unsplash")
def diag_unsplash(
    q: str,
    orientation: str = "landscape",
    min_width: int = 1200,
) -> Dict[str, Any]:
    """Diagnostic: live Unsplash query, returns raw query_unsplash output.

    Used by Pass 4.0b.5 PART 2 verification curls. The endpoint is
    intentionally permissive — no auth, no rate limiting, returns the
    full credit dict so we can confirm attribution shape matches
    Unsplash's requirements. Persisting intentionally NOT done here;
    that happens in the build pipeline at PART 4.
    """
    result = query_unsplash(
        query=q,
        orientation=orientation,
        min_width=min_width,
    )
    return {
        "query": q,
        "orientation": orientation,
        "min_width": min_width,
        "result": result,
    }


@router.get("/_diag/build_query")
def diag_build_query(
    slot_name: str,
    business_name: str = "",
    description: str = "",
    inferred_vibe: str = "",
    brand_metaphor: str = "",
    content_archetype: str = "",
    accent_style: str = "",
    sub_strand_id: str = "",
) -> Dict[str, Any]:
    """Diagnostic: show the Unsplash query that build_unsplash_query
    would compose for the given slot + brief. Pure composition, no
    Unsplash call."""
    enriched_brief = {
        "inferred_vibe": inferred_vibe,
        "brand_metaphor": brand_metaphor,
        "content_archetype": content_archetype,
    }
    designer_pick = {
        "accent_style": accent_style,
        "sub_strand_id": sub_strand_id,
    }
    business = {"name": business_name, "elevator_pitch": description}
    composed = build_unsplash_query(
        slot_name=slot_name,
        enriched_brief=enriched_brief,
        designer_pick=designer_pick,
        business=business,
    )
    return {
        "slot_name": slot_name,
        "composed_query": composed,
    }


# ─── PART 3 — DALL-E diagnostic endpoints ──────────────────────────

class DiagDalleRequest(BaseModel):
    business_id: str
    slot_name: str
    quality: str = "hd"
    size: str = "1024x1024"
    style: str = "natural"
    # Optional: override the auto-composed prompt with a custom one
    # (used for ad-hoc verification queries).
    prompt: Optional[str] = None
    # Optional brief context for prompt composition; falls back to
    # build_dalle_prompt defaults if any field is missing.
    inferred_vibe: Optional[str] = None
    brand_metaphor: Optional[str] = None
    content_archetype: Optional[str] = None
    accent_style: Optional[str] = None
    sub_strand_id: Optional[str] = None
    layout_archetype: Optional[str] = None


@router.post("/_diag/dalle")
def diag_dalle_generate(req: DiagDalleRequest):
    """Diagnostic: generate one DALL-E image, rehost to Supabase, log
    spend, persist as the slot's default. Returns the Supabase URL +
    cost. Subject to PER_SITE_DAILY_CAP_USD ($0.50) — a request that
    would breach the cap returns 402 with the current spend.

    Used by PART 3 verification curls (Royal Palace HD generation +
    cost cap rejection test). The endpoint is intentionally permissive
    (no auth) since it requires a valid business_id and is gated by
    the spend cap."""
    enriched_brief = {
        "inferred_vibe": req.inferred_vibe or "",
        "brand_metaphor": req.brand_metaphor or "",
        "content_archetype": req.content_archetype or "",
    }
    designer_pick = {
        "accent_style": req.accent_style or "",
        "sub_strand_id": req.sub_strand_id or "",
        "layout_archetype": req.layout_archetype or "",
    }
    composed_prompt = req.prompt or build_dalle_prompt(
        slot_name=req.slot_name,
        enriched_brief=enriched_brief,
        designer_pick=designer_pick,
    )

    expected = dalle_cost(req.quality, req.size)
    allowed, current = can_dalle_generate(req.business_id, expected)
    if not allowed:
        # 402 Payment Required is the closest semantic; budget-cap
        # rejection is exactly this. PART 5 reroll endpoint will
        # surface this same response shape.
        raise HTTPException(
            status_code=402,
            detail={
                "error": "budget_cap_exceeded",
                "current_spend_today_usd": current,
                "expected_cost_usd": expected,
                "cap_usd": PER_SITE_DAILY_CAP_USD,
                "remaining_usd": round(PER_SITE_DAILY_CAP_USD - current, 4),
            },
        )

    debug = generate_dalle_image_debug(
        prompt=composed_prompt,
        business_id=req.business_id,
        slot_name=req.slot_name,
        quality=req.quality,
        size=req.size,
        style=req.style,
    )
    if debug.get("status") != "ok":
        # Surface the exact failure stage instead of a generic 502.
        # Maps cleanly to status codes per failure type.
        status_to_http = {
            "no_api_key": 503,
            "empty_prompt": 400,
            "budget_cap_exceeded": 402,
            "openai_http_error": 502,
            "openai_call_exception": 502,
            "openai_no_data": 502,
            "openai_no_url": 502,
            "rehost_failed": 502,
        }
        raise HTTPException(
            status_code=status_to_http.get(debug.get("status"), 502),
            detail=debug,
        )

    # Persist as the slot's default so /preview surfaces it.
    persisted = slot_storage.set_slot_default(
        business_id=req.business_id,
        slot_name=req.slot_name,
        url=debug["url"],
        source="dalle",
        credit=None,
    )

    return {
        "composed_prompt": composed_prompt,
        "result": debug,
        "persisted_to_slot": persisted,
        "spend_today_usd_after": get_site_dalle_spend_today(req.business_id),
    }


@router.get("/_diag/dalle_spend")
def diag_dalle_spend(business_id: str) -> Dict[str, Any]:
    """Diagnostic: report current DALL-E spend for a business, plus
    a sample-cost can-generate flag for HD 1024 ($0.08)."""
    current = get_site_dalle_spend_today(business_id)
    sample_cost = dalle_cost("hd", "1024x1024")
    allowed, _ = can_dalle_generate(business_id, sample_cost)
    return {
        "business_id": business_id,
        "spend_today_usd": current,
        "cap_usd": PER_SITE_DAILY_CAP_USD,
        "remaining_usd": round(PER_SITE_DAILY_CAP_USD - current, 4),
        "can_generate_hd_1024": allowed,
        "sample_cost_used_for_check_usd": sample_cost,
    }


class SimulateSpendRequest(BaseModel):
    business_id: str
    cost_usd: float
    note: Optional[str] = "synthetic budget-cap test"


@router.post("/_diag/storage_probe")
def diag_storage_probe(business_id: str) -> Dict[str, Any]:
    """Diagnostic: upload a 1KB synthetic PNG to the site_images bucket
    to isolate Supabase Storage failures from OpenAI download issues.
    Returns the structured status dict from _upload_site_image_debug
    plus the storage_path attempted. Used during PART 3 debugging."""
    import time as _time
    # Minimal valid 1x1 PNG (transparent)
    PNG_1X1 = bytes.fromhex(
        "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C4"
        "890000000D49444154789C636060606000000004000133D58E000000004945"
        "4E44AE426082"
    )
    storage_path = f"{business_id}/_diag_probe_{int(_time.time())}.png"
    debug = _upload_site_image_debug(storage_path, PNG_1X1, "image/png")
    return {
        "bucket": SITE_IMAGES_BUCKET,
        "storage_path": storage_path,
        "upload_status": debug,
    }


@router.post("/_diag/dalle_spend_simulate")
def diag_simulate_spend(req: SimulateSpendRequest) -> Dict[str, Any]:
    """Diagnostic: append a synthetic spend entry so the budget cap
    can be exercised without burning real DALL-E generations. The
    entry is tagged slot_name=_synthetic_test in the log so it's
    distinguishable from real spend.

    Used in PART 3 verification: pre-load $0.45, then attempt a real
    $0.08 generation, expect 402."""
    ok = add_synthetic_spend_for_testing(
        business_id=req.business_id,
        cost_usd=req.cost_usd,
        note=req.note or "synthetic budget-cap test",
    )
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"no business_sites row for business_id={req.business_id}",
        )
    return {
        "business_id": req.business_id,
        "added_cost_usd": req.cost_usd,
        "spend_today_usd_after": get_site_dalle_spend_today(req.business_id),
    }


@router.post("/_diag/dalle_spend_clear")
def diag_dalle_spend_clear(business_id: str) -> Dict[str, Any]:
    """Diagnostic: drop synthetic spend entries (slot_name=='_synthetic_test')
    so PART 5 verification can fire a real DALL-E reroll without the
    PART 3 budget-cap setup interfering. Real spend is preserved."""
    return clear_synthetic_spend(business_id)


# ─── PART 5 — Practitioner-facing endpoints ─────────────────────────
#
# Owner gating: NONE (matches existing single-tenant pattern across
# practitioner_profile_router, voice_depth_agent, public_site.py). A
# real per-business JWT layer is planned for Pass 4.0c+ to retrofit
# every mutation surface in one shot.

# Allowed MIME types for slot uploads. Must match the bucket's accepted
# types in Supabase Studio (image/jpeg, image/png, image/webp, image/avif).
_ALLOWED_UPLOAD_MIMES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/avif",
}
# Map MIME → file extension for the storage path.
_MIME_TO_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg",
    "image/png":  "png",
    "image/webp": "webp",
    "image/avif": "avif",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB


def _aspect_ratio_to_orientation(aspect_ratio: Optional[str]) -> str:
    """Map slot aspect_ratio to Unsplash orientation hint. Mirrors the
    logic in builder_post_process so reroll requests Unsplash with the
    same orientation as the original populate."""
    if not aspect_ratio:
        return "landscape"
    if aspect_ratio == "1:1":
        return "squarish"
    if ":" in aspect_ratio:
        try:
            w, h = aspect_ratio.split(":")
            if int(w) < int(h):
                return "portrait"
        except (ValueError, AttributeError):
            pass
    return "landscape"


def _validate_upload_dimensions(
    image_bytes: bytes,
    min_width: int,
    min_height: int,
) -> Tuple[bool, Optional[str], Optional[Tuple[int, int]]]:
    """Returns (ok, error_message, (width, height)). Reads only the
    image header via PIL — does not decode the full image."""
    import io
    try:
        from PIL import Image  # lazy import keeps test contexts unaffected
    except Exception as e:
        return False, f"Pillow unavailable: {e}", None
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            width, height = img.size
    except Exception as e:
        return False, f"image_unreadable: {type(e).__name__}: {e}", None
    if width < min_width or height < min_height:
        return False, (
            f"dimensions_too_small: image is {width}x{height}, "
            f"slot requires at least {min_width}x{min_height}"
        ), (width, height)
    return True, None, (width, height)


def _slot_record_for_response(
    business_id: str,
    slot_name: str,
) -> Dict[str, Any]:
    """Helper: assemble the per-slot response payload used by upload /
    clear / reroll / GET manifest. Uniform shape across all four."""
    record = slot_storage.get_slot(business_id, slot_name) or {}
    defn = SLOT_DEFINITIONS.get(slot_name)
    resolved = resolve_slot_url(record, slot_name)
    is_placeholder_strategy = (
        defn and defn.get("default_strategy") == "placeholder"
    )
    if is_placeholder_strategy:
        # Placeholder slots are uploads-only. Both flags are 0/False so
        # the UI can render the reroll button disabled with the "uploads
        # only" tooltip without further special-casing.
        can_reroll_now = False
        current_count = 0
        rerolls_remaining = 0
    else:
        can_reroll_now, current_count = slot_storage.can_reroll(
            business_id, slot_name
        )
        rerolls_remaining = max(0, MAX_REROLLS_PER_DAY - current_count)
    return {
        "slot_name": slot_name,
        "definition": defn,
        "current": record,
        "resolved": resolved,
        "reroll_count_today": current_count,
        "rerolls_remaining_today": rerolls_remaining,
        "can_reroll": can_reroll_now,
    }


@router.get("/{business_id}")
def get_slot_manifest(business_id: str) -> Dict[str, Any]:
    """Full slot manifest for a business. Returns ALL 11 slots from
    SLOT_DEFINITIONS (not just slots that have been populated), so the
    UI can render every slot card including unpopulated ones."""
    slots_out = [
        _slot_record_for_response(business_id, name)
        for name in SLOT_DEFINITIONS.keys()
    ]
    return {
        "business_id": business_id,
        "slots": slots_out,
    }


@router.post("/{business_id}/{slot_name}/upload")
async def upload_slot(
    business_id: str,
    slot_name: str,
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    """Practitioner upload endpoint. Validates size + MIME + dimensions,
    stores in Supabase site_images bucket, sets slot custom_url. Custom
    URL wins over default in resolve_slot_url precedence."""
    defn = get_slot_definition(slot_name)
    if not defn:
        raise HTTPException(404, f"unknown slot: {slot_name}")

    content_type = (file.content_type or "").lower()
    if content_type not in _ALLOWED_UPLOAD_MIMES:
        raise HTTPException(
            400,
            {
                "error": "unsupported_mime_type",
                "received": content_type,
                "allowed": sorted(_ALLOWED_UPLOAD_MIMES),
            },
        )

    image_bytes = await file.read()
    if len(image_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            400,
            {
                "error": "file_too_large",
                "received_bytes": len(image_bytes),
                "max_bytes": MAX_UPLOAD_BYTES,
            },
        )
    if not image_bytes:
        raise HTTPException(400, {"error": "empty_file"})

    min_dims = defn.get("min_dimensions") or {}
    ok, err, dims = _validate_upload_dimensions(
        image_bytes,
        min_width=int(min_dims.get("width", 0)),
        min_height=int(min_dims.get("height", 0)),
    )
    if not ok:
        raise HTTPException(
            400,
            {
                "error": err,
                "min_required": min_dims,
                "received": {"width": dims[0], "height": dims[1]} if dims else None,
            },
        )

    import time as _time
    ext = _MIME_TO_EXT.get(content_type, "png")
    ts = int(_time.time())
    storage_path = f"{business_id}/custom_{slot_name}_{ts}.{ext}"
    public_url = _upload_site_image(storage_path, image_bytes, content_type)
    if not public_url:
        raise HTTPException(
            502,
            {"error": "storage_upload_failed", "storage_path": storage_path},
        )

    persisted = slot_storage.set_slot_custom(
        business_id=business_id,
        slot_name=slot_name,
        url=public_url,
    )
    if not persisted:
        raise HTTPException(
            502,
            {"error": "slot_persist_failed", "uploaded_url": public_url},
        )

    return {
        "success": True,
        "custom_url": public_url,
        "storage_path": storage_path,
        "uploaded_dimensions": {"width": dims[0], "height": dims[1]},
        "slot": _slot_record_for_response(business_id, slot_name),
    }


@router.post("/{business_id}/{slot_name}/clear")
def clear_slot(business_id: str, slot_name: str) -> Dict[str, Any]:
    """Revert a slot from custom upload back to default suggestion.
    Does NOT delete the uploaded file from Supabase Storage — kept for
    potential undo. Resolution falls through to default_url (or
    placeholder if no default)."""
    defn = get_slot_definition(slot_name)
    if not defn:
        raise HTTPException(404, f"unknown slot: {slot_name}")

    ok = slot_storage.clear_slot_custom(business_id, slot_name)
    if not ok:
        raise HTTPException(
            502,
            {
                "error": "slot_clear_failed",
                "business_id": business_id,
                "slot_name": slot_name,
            },
        )
    return {
        "success": True,
        "slot": _slot_record_for_response(business_id, slot_name),
    }


class RerollRequest(BaseModel):
    quality: Optional[str] = None  # "standard" | "hd" — DALL-E only


@router.post("/{business_id}/{slot_name}/reroll")
def reroll_slot(
    business_id: str,
    slot_name: str,
    req: Optional[RerollRequest] = None,
) -> Dict[str, Any]:
    """Re-fire the slot's default-resolution strategy with stored context.

    Pre-flight:
      1. Reset reroll counter if past midnight UTC
      2. Reject 400 for placeholder-strategy slots (uploads only)
      3. Reject 429 if today's reroll counter is already at MAX

    Strategy execution (uses cached default_query / default_dalle_prompt
    from the original populate; falls back to re-composing from the
    persisted brief when not present, e.g. for slots populated by an
    earlier build that pre-dates the cache fields):
      - unsplash:                    queries with result_index=count+1 for variety
      - dalle:                        budget-cap check, generate, rehost
      - unsplash_with_dalle_fallback: tries unsplash; falls through to
                                      DALL-E if no qualifying result"""
    defn = get_slot_definition(slot_name)
    if not defn:
        raise HTTPException(404, f"unknown slot: {slot_name}")

    strategy = defn.get("default_strategy")
    if strategy == "placeholder":
        raise HTTPException(
            400,
            {
                "error": "placeholder_slots_cannot_be_rerolled",
                "advice": (
                    "Profile slots are uploads only. Use the Upload "
                    "button to set a custom photo."
                ),
            },
        )

    slot_storage.reset_rerolls_if_new_day(business_id, slot_name)
    can_reroll_now, current_count = slot_storage.can_reroll(
        business_id, slot_name
    )
    if not can_reroll_now:
        raise HTTPException(
            429,
            {
                "error": "reroll_limit_exceeded",
                "reroll_count_today": current_count,
                "max_per_day": MAX_REROLLS_PER_DAY,
                "advice": (
                    "Daily reroll limit reached for this slot. "
                    "Counter resets at midnight UTC."
                ),
            },
        )

    record = slot_storage.get_slot(business_id, slot_name) or {}
    requested_quality = (req.quality if req else None) or "hd"
    if requested_quality not in ("standard", "hd"):
        requested_quality = "hd"

    new_url: Optional[str] = None
    new_source: Optional[str] = None
    new_credit: Optional[Dict[str, Any]] = None
    cost_usd: float = 0.0

    # ── Unsplash path (or unsplash_with_dalle_fallback first leg) ──
    if strategy in ("unsplash", "unsplash_with_dalle_fallback"):
        cached_query = record.get("default_query")
        if not cached_query:
            # Legacy-slot fallback: this slot was populated by an older
            # build before the reroll-context cache fields existed.
            # Recompose a reasonable query from the business row's
            # available fields so the reroll still works. Quality may
            # drop slightly vs the original build's query (no
            # enriched_brief or designer_pick to flavor mood) but the
            # subject keyword still maps via _BUSINESS_TYPE_KEYWORDS.
            try:
                from brand_engine import _sb_get as be_get
                rows = be_get(
                    f"/businesses?id=eq.{business_id}"
                    "&select=name,settings,voice_profile&limit=1"
                ) or []
                biz = rows[0] if rows else {}
            except Exception:
                biz = {}
            cached_query = build_unsplash_query(
                slot_name=slot_name,
                enriched_brief={},
                designer_pick={},
                business={
                    "name": biz.get("name") or "",
                    "elevator_pitch": "",
                },
            )
            logger.info(
                f"[slot_reroll] legacy slot {slot_name} for {business_id}: "
                f"recomposed query={cached_query!r} from business row"
            )
        orientation = _aspect_ratio_to_orientation(defn.get("aspect_ratio"))
        min_w = (defn.get("min_dimensions") or {}).get("width", 1200)
        # result_index = current_count + 1 walks the qualifying results
        # list across rerolls (initial populate took index 0).
        result = query_unsplash(
            query=cached_query,
            orientation=orientation,
            min_width=min_w,
            result_index=current_count + 1,
        )
        if result and result.get("url"):
            new_url = result["url"]
            new_source = "unsplash"
            new_credit = result.get("credit")
        elif strategy == "unsplash":
            raise HTTPException(
                502,
                {
                    "error": "no_unsplash_result",
                    "advice": (
                        f"Unsplash returned no qualifying result for "
                        f"reroll #{current_count + 1} of query "
                        f"{cached_query!r}. Counter not incremented."
                    ),
                },
            )
        # else fall through to DALL-E fallback below

    # ── DALL-E path (direct or fallback) ────────────────────────
    if new_url is None and strategy in ("dalle", "unsplash_with_dalle_fallback"):
        cached_prompt = record.get("default_dalle_prompt")
        if not cached_prompt:
            # Recompose from defaults if no cache (legacy slots)
            cached_prompt = build_dalle_prompt(slot_name, {}, {})
        size = "1024x1024"
        expected = dalle_cost(requested_quality, size)
        allowed, current_spend = can_dalle_generate(business_id, expected)
        if not allowed:
            raise HTTPException(
                402,
                {
                    "error": "budget_cap_exceeded",
                    "current_spend_today_usd": current_spend,
                    "expected_cost_usd": expected,
                    "cap_usd": PER_SITE_DAILY_CAP_USD,
                    "remaining_usd": round(
                        PER_SITE_DAILY_CAP_USD - current_spend, 4
                    ),
                },
            )
        gen = generate_dalle_image(
            prompt=cached_prompt,
            business_id=business_id,
            slot_name=slot_name,
            quality=requested_quality,
            size=size,
            style="natural",
        )
        if not gen:
            raise HTTPException(
                502,
                {"error": "dalle_generation_failed"},
            )
        new_url = gen["url"]
        new_source = "dalle"
        new_credit = None
        cost_usd = float(gen.get("cost_usd") or expected)

    if not new_url or not new_source:
        # Defensive — every strategy branch should land before here.
        raise HTTPException(
            500, {"error": "reroll_resolution_fell_through"}
        )

    # Persist new default. Carry the cached query/prompt forward so
    # subsequent rerolls keep walking the variety axis.
    persist_kwargs: Dict[str, Any] = {
        "business_id": business_id,
        "slot_name": slot_name,
        "url": new_url,
        "source": new_source,
        "credit": new_credit,
    }
    if new_source == "unsplash":
        persist_kwargs["query"] = record.get("default_query")
    elif new_source == "dalle":
        persist_kwargs["dalle_prompt"] = record.get("default_dalle_prompt")
    slot_storage.set_slot_default(**persist_kwargs)

    # Increment counter AFTER the retrieval succeeds — so a failed
    # reroll attempt doesn't burn the daily budget.
    new_count = slot_storage.increment_reroll(business_id, slot_name)
    rerolls_remaining = max(0, MAX_REROLLS_PER_DAY - new_count)

    response: Dict[str, Any] = {
        "success": True,
        "new_default_url": new_url,
        "new_default_source": new_source,
        "new_default_credit": new_credit,
        "reroll_count_today": new_count,
        "rerolls_remaining_today": rerolls_remaining,
        "slot": _slot_record_for_response(business_id, slot_name),
    }
    if cost_usd > 0:
        response["cost_usd"] = cost_usd
    return response
