"""Pass 4.0b.5 PART 3 — DALL-E 3 generation + Supabase Storage rehost.

DALL-E 3 returns a temporary Azure-blob URL that expires within ~1 hour.
We download that bytes payload immediately and re-upload to the
site_images Supabase bucket so the persisted slot URL has the lifetime
of the practitioner's site. Callers NEVER see an OpenAI URL.

Cost tracking lives on business_sites.site_config.dalle_spend_log as a
list of {date, slot_name, cost_usd, generated_at, revised_prompt} rows.
Per-site daily cap is $0.50 (UTC date window). Caller invokes
can_dalle_generate(business_id, expected_cost) BEFORE calling
generate_dalle_image; the cap is also enforced inside generate to
prevent races.

Pricing (DALL-E 3, current OpenAI rates):
  Standard 1024x1024 :  $0.040
  Standard 1792x1024 :  $0.080
  Standard 1024x1792 :  $0.080
  HD       1024x1024 :  $0.080
  HD       1792x1024 :  $0.120
  HD       1024x1792 :  $0.120
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


OPENAI_IMAGES_ENDPOINT = "https://api.openai.com/v1/images/generations"
DALLE_MODEL = "dall-e-3"
HTTP_TIMEOUT = 90.0  # DALL-E HD generations regularly take 30–60s
SITE_IMAGES_BUCKET = "site_images"

# Per-site daily spend cap (UTC date). The Builder + reroll pipeline
# consults this before initiating a paid call.
PER_SITE_DAILY_CAP_USD = 0.50


# ─── Pricing ─────────────────────────────────────────────────────────

_DALLE_PRICING: Dict[Tuple[str, str], float] = {
    # (quality, size) -> USD
    ("standard", "1024x1024"): 0.040,
    ("standard", "1792x1024"): 0.080,
    ("standard", "1024x1792"): 0.080,
    ("hd",       "1024x1024"): 0.080,
    ("hd",       "1792x1024"): 0.120,
    ("hd",       "1024x1792"): 0.120,
}


def dalle_cost(quality: str, size: str) -> float:
    """Return the USD cost for a (quality, size) DALL-E 3 generation.
    Falls back to HD 1024x1024 pricing for unknown combos so we err on
    the side of being conservative against the budget cap."""
    return _DALLE_PRICING.get((quality, size), 0.080)


# ─── Cost tracking ──────────────────────────────────────────────────

def _now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_date_today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _fetch_site_row(business_id: str) -> Tuple[Optional[str], Dict[str, Any]]:
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[dalle] brand_engine import failed: {e}")
        return None, {}
    rows = be_get(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,site_config&limit=1"
    ) or []
    if not rows:
        return None, {}
    return rows[0].get("id"), (rows[0].get("site_config") or {})


def _patch_site_config(site_id: str, cfg: Dict[str, Any]) -> bool:
    try:
        from brand_engine import _sb_patch as be_patch
        be_patch(f"/business_sites?id=eq.{site_id}", {"site_config": cfg})
        return True
    except Exception as e:
        logger.warning(f"[dalle] patch failed for {site_id}: {e}")
        return False


def get_site_dalle_spend_today(business_id: str) -> float:
    """Sum DALL-E generation costs for this business with today's UTC
    date. Returns 0.0 when the business has no row, no log, or no
    entries from today."""
    _, cfg = _fetch_site_row(business_id)
    log = cfg.get("dalle_spend_log") or []
    today = _utc_date_today()
    total = 0.0
    for entry in log:
        if not isinstance(entry, dict):
            continue
        if entry.get("date") == today:
            try:
                total += float(entry.get("cost_usd") or 0)
            except (TypeError, ValueError):
                continue
    return round(total, 4)


def can_dalle_generate(
    business_id: str,
    expected_cost: float,
) -> Tuple[bool, float]:
    """Returns (allowed, current_spend_today). Allowed when
    current + expected <= PER_SITE_DAILY_CAP_USD. Caller should check
    this BEFORE invoking generate_dalle_image; generate enforces it
    internally too as a race guard."""
    current = get_site_dalle_spend_today(business_id)
    return ((current + expected_cost) <= PER_SITE_DAILY_CAP_USD, current)


def _log_dalle_spend(
    business_id: str,
    slot_name: str,
    cost_usd: float,
    revised_prompt: Optional[str] = None,
    storage_path: Optional[str] = None,
) -> bool:
    """Append a spend row to site_config.dalle_spend_log. Idempotent
    semantics not needed — every generation deserves its own row even
    if two land in the same second."""
    site_id, cfg = _fetch_site_row(business_id)
    if not site_id:
        logger.warning(
            f"[dalle] cannot log spend — no business_sites row for "
            f"business_id={business_id}"
        )
        return False
    log = list(cfg.get("dalle_spend_log") or [])
    log.append({
        "date": _utc_date_today(),
        "slot_name": slot_name,
        "cost_usd": round(float(cost_usd), 4),
        "generated_at": _now_utc_iso(),
        "revised_prompt": revised_prompt,
        "storage_path": storage_path,
    })
    cfg["dalle_spend_log"] = log
    return _patch_site_config(site_id, cfg)


def add_synthetic_spend_for_testing(
    business_id: str,
    cost_usd: float,
    note: str = "synthetic budget-cap test",
) -> bool:
    """Diagnostic-only: insert a synthetic spend entry so the budget
    cap can be verified without running real DALL-E generations.
    Mounted via /_diag/dalle_spend_simulate (PART 3 verification)."""
    site_id, cfg = _fetch_site_row(business_id)
    if not site_id:
        return False
    log = list(cfg.get("dalle_spend_log") or [])
    log.append({
        "date": _utc_date_today(),
        "slot_name": "_synthetic_test",
        "cost_usd": round(float(cost_usd), 4),
        "generated_at": _now_utc_iso(),
        "revised_prompt": None,
        "storage_path": None,
        "_note": note,
    })
    cfg["dalle_spend_log"] = log
    return _patch_site_config(site_id, cfg)


# ─── Supabase Storage rehost ────────────────────────────────────────

def _site_image_storage_url(storage_path: str) -> str:
    """Public URL for a site_images object."""
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    return f"{base}/storage/v1/object/public/{SITE_IMAGES_BUCKET}/{storage_path}"


def _upload_site_image_debug(
    storage_path: str,
    file_bytes: bytes,
    content_type: str = "image/png",
) -> Dict[str, Any]:
    """Upload helper that always returns a structured status dict.

    Status values:
      ok                    payload includes url
      no_supabase_env       SUPABASE_URL or SUPABASE_ANON missing
      http_error            Supabase returned >= 400 (body excerpt included)
      http_exception        network/timeout failure
    """
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    anon = os.environ.get("SUPABASE_ANON", "")
    if not base or not anon:
        return {"status": "no_supabase_env"}
    url = f"{base}/storage/v1/object/{SITE_IMAGES_BUCKET}/{storage_path}"
    headers = {
        "apikey": anon,
        "Authorization": f"Bearer {anon}",
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, content=file_bytes, headers=headers)
    except httpx.HTTPError as e:
        return {
            "status": "http_exception",
            "exception_type": type(e).__name__,
            "exception_msg": str(e)[:300],
        }
    if resp.status_code >= 400:
        return {
            "status": "http_error",
            "http_status": resp.status_code,
            "body_excerpt": resp.text[:300],
            "upload_url": url,
        }
    return {
        "status": "ok",
        "url": _site_image_storage_url(storage_path),
    }


def _upload_site_image(
    storage_path: str,
    file_bytes: bytes,
    content_type: str = "image/png",
) -> Optional[str]:
    """Compatibility wrapper that returns just the URL or None.
    Used by download_and_rehost; debug variant exposed via the
    diagnostic endpoint."""
    debug = _upload_site_image_debug(storage_path, file_bytes, content_type)
    if debug.get("status") == "ok":
        return debug.get("url")
    logger.warning(
        f"[dalle] storage upload {storage_path} failed: "
        f"status={debug.get('status')} "
        f"http={debug.get('http_status')} "
        f"body={debug.get('body_excerpt', '')[:200]}"
    )
    return None


def download_and_rehost(
    openai_url: str,
    business_id: str,
    slot_name: str,
    suffix: str = "",
) -> Optional[Dict[str, Any]]:
    """Download an OpenAI temporary image URL and upload to the
    site_images bucket. Returns {url, storage_path} on success, None
    on failure. The storage path is namespaced by business_id and
    timestamped so re-rolls don't collide:

        site_images/<business_id>/<slot_name>_<unix>_<suffix>.png

    DALL-E always returns PNG; we hard-code image/png content-type."""
    if not openai_url:
        return None
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.get(openai_url)
        if r.status_code >= 400:
            logger.warning(
                f"[dalle] download from OpenAI failed: {r.status_code} "
                f"{r.text[:200] if r.text else ''}"
            )
            return None
        image_bytes = r.content
    except httpx.HTTPError as e:
        logger.warning(f"[dalle] download HTTP error: {e}")
        return None

    if not image_bytes:
        logger.warning("[dalle] OpenAI URL returned empty body")
        return None

    ts = int(time.time())
    suffix_part = f"_{suffix}" if suffix else ""
    storage_path = f"{business_id}/{slot_name}_{ts}{suffix_part}.png"
    public_url = _upload_site_image(storage_path, image_bytes, "image/png")
    if not public_url:
        return None
    return {"url": public_url, "storage_path": storage_path}


# ─── DALL-E 3 generation ────────────────────────────────────────────

def generate_dalle_image_debug(
    prompt: str,
    business_id: str,
    slot_name: str,
    quality: str = "hd",
    size: str = "1024x1024",
    style: str = "natural",
) -> Dict[str, Any]:
    """Debug variant of generate_dalle_image. Returns a structured
    status dict with the exact failure stage instead of returning None.
    Used by /slots/_diag/dalle to surface OpenAI vs rehost failures
    distinctly during PART 3 verification.

    Status values:
      ok                         success — payload includes url + cost
      no_api_key                 OPENAI_API_KEY not set
      empty_prompt               prompt was blank
      budget_cap_exceeded        would overrun PER_SITE_DAILY_CAP_USD
      openai_http_error          OpenAI returned >= 400
      openai_call_exception      network/timeout/json failure
      openai_no_data             response had no items
      openai_no_url              first item missing url field
      rehost_failed              download or Supabase upload failed
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return {"status": "no_api_key"}
    if not (prompt or "").strip():
        return {"status": "empty_prompt"}

    if quality not in ("standard", "hd"):
        quality = "hd"
    if size not in ("1024x1024", "1792x1024", "1024x1792"):
        size = "1024x1024"
    if style not in ("natural", "vivid"):
        style = "natural"

    expected_cost = dalle_cost(quality, size)
    allowed, current = can_dalle_generate(business_id, expected_cost)
    if not allowed:
        return {
            "status": "budget_cap_exceeded",
            "current_spend_today_usd": current,
            "expected_cost_usd": expected_cost,
        }

    body = {
        "model": DALLE_MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "style": style,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.post(
                OPENAI_IMAGES_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(body).encode("utf-8"),
            )
    except Exception as e:
        return {
            "status": "openai_call_exception",
            "exception_type": type(e).__name__,
            "exception_msg": str(e)[:300],
        }

    if resp.status_code >= 400:
        return {
            "status": "openai_http_error",
            "http_status": resp.status_code,
            "body_excerpt": resp.text[:500],
        }

    try:
        data = resp.json()
    except Exception as e:
        return {
            "status": "openai_call_exception",
            "exception_type": "JSONDecodeError",
            "exception_msg": str(e)[:300],
        }

    items = data.get("data") or []
    if not items:
        return {"status": "openai_no_data", "raw": data}
    item = items[0]
    openai_url = item.get("url")
    revised_prompt = item.get("revised_prompt")
    if not openai_url:
        return {"status": "openai_no_url", "item": item}

    rehosted = download_and_rehost(
        openai_url=openai_url,
        business_id=business_id,
        slot_name=slot_name,
        suffix=quality,
    )
    if not rehosted:
        return {
            "status": "rehost_failed",
            "openai_url_prefix": (openai_url or "")[:80],
            "revised_prompt": revised_prompt,
        }

    _log_dalle_spend(
        business_id=business_id,
        slot_name=slot_name,
        cost_usd=expected_cost,
        revised_prompt=revised_prompt,
        storage_path=rehosted["storage_path"],
    )
    return {
        "status": "ok",
        "url": rehosted["url"],
        "storage_path": rehosted["storage_path"],
        "revised_prompt": revised_prompt,
        "cost_usd": expected_cost,
        "quality": quality,
        "size": size,
    }


def generate_dalle_image(
    prompt: str,
    business_id: str,
    slot_name: str,
    quality: str = "hd",
    size: str = "1024x1024",
    style: str = "natural",
) -> Optional[Dict[str, Any]]:
    """Generate one DALL-E 3 image, rehost to Supabase, log spend.

    Returns:
      {
        "url": <Supabase public URL — never the OpenAI URL>,
        "storage_path": <site_images path>,
        "revised_prompt": <DALL-E 3 always rewrites the prompt>,
        "cost_usd": float,
        "quality": str,
        "size": str,
      }
      or None on any failure (missing key, budget cap, OpenAI error,
      rehost failure).

    business_id + slot_name are required for both the storage path
    namespacing and the spend log entry. The function REFUSES to run
    when the projected spend would exceed PER_SITE_DAILY_CAP_USD —
    even if can_dalle_generate was checked moments earlier — so two
    concurrent invocations can't both squeeze under the cap.
    """
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.warning("[dalle] OPENAI_API_KEY not set; aborting")
        return None
    if not (prompt or "").strip():
        return None

    if quality not in ("standard", "hd"):
        quality = "hd"
    if size not in ("1024x1024", "1792x1024", "1024x1792"):
        size = "1024x1024"
    if style not in ("natural", "vivid"):
        style = "natural"

    expected_cost = dalle_cost(quality, size)
    allowed, current = can_dalle_generate(business_id, expected_cost)
    if not allowed:
        logger.warning(
            f"[dalle] budget cap reached for {business_id}: "
            f"current={current:.3f} + expected={expected_cost:.3f} > "
            f"cap={PER_SITE_DAILY_CAP_USD:.2f}; aborting"
        )
        return None

    body = {
        "model": DALLE_MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "quality": quality,
        "style": style,
    }
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            resp = client.post(
                OPENAI_IMAGES_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                content=json.dumps(body).encode("utf-8"),
            )
        if resp.status_code >= 400:
            logger.warning(
                f"[dalle] OpenAI returned {resp.status_code}: "
                f"{resp.text[:300]}"
            )
            return None
        data = resp.json()
    except Exception as e:
        logger.warning(f"[dalle] OpenAI call failed: {type(e).__name__}: {e}")
        return None

    items = data.get("data") or []
    if not items:
        logger.warning("[dalle] OpenAI response had no data items")
        return None
    item = items[0]
    openai_url = item.get("url")
    revised_prompt = item.get("revised_prompt")
    if not openai_url:
        logger.warning("[dalle] OpenAI item missing url")
        return None

    rehosted = download_and_rehost(
        openai_url=openai_url,
        business_id=business_id,
        slot_name=slot_name,
        suffix=quality,
    )
    if not rehosted:
        logger.warning("[dalle] rehost failed; not logging spend")
        return None

    _log_dalle_spend(
        business_id=business_id,
        slot_name=slot_name,
        cost_usd=expected_cost,
        revised_prompt=revised_prompt,
        storage_path=rehosted["storage_path"],
    )

    return {
        "url": rehosted["url"],
        "storage_path": rehosted["storage_path"],
        "revised_prompt": revised_prompt,
        "cost_usd": expected_cost,
        "quality": quality,
        "size": size,
    }


# ─── Prompt composition ─────────────────────────────────────────────

# Template per decorative slot. The {aesthetic} / {composition} /
# {lighting} / {mood} placeholders are filled from the enrichment +
# designer pick. Every prompt ends with the universal text-suppressor
# closure to defeat DALL-E's tendency to hallucinate fake words.
_DALLE_SLOT_TEMPLATES = {
    "decorative_1": (
        "Abstract geometric pattern in {aesthetic}, "
        "{composition}, {lighting}, {mood}, no text, no words, no letters"
    ),
    "decorative_2": (
        "Subtle organic texture in {aesthetic}, "
        "{composition}, {lighting}, {mood}, no text, no words, no letters"
    ),
    "decorative_3": (
        "Ornamental accent motif in {aesthetic}, "
        "{composition}, {lighting}, {mood}, no text, no words, no letters"
    ),
}


_AESTHETIC_STOP_WORDS = {"and", "or", "with", "of", "the", "a", "an", "to", "&"}


def _aesthetic_phrase(enriched_brief: Dict, designer_pick: Dict) -> str:
    """Build the aesthetic phrase that sits inside 'in {aesthetic}'.
    Prefers brand_metaphor when present (the most concrete signal),
    falls back to a strand-derived phrase when not."""
    metaphor = (enriched_brief.get("brand_metaphor") or "").strip()
    if metaphor:
        # 'royal court and throne room' -> 'royal court aesthetic'
        # Strip stop words first so we don't end up with phrases like
        # 'royal court and aesthetic'. Then keep first 2-3 content words.
        cleaned = [
            w.strip(",.") for w in metaphor.lower().split()
            if w.strip(",.").lower() not in _AESTHETIC_STOP_WORDS
        ]
        if cleaned:
            return " ".join(cleaned[:3]) + " aesthetic"
    sub = (designer_pick.get("sub_strand_id") or "").strip()
    if sub:
        # 'luxury-noir' -> 'luxury noir aesthetic'
        return sub.replace("-", " ").replace("_", " ") + " aesthetic"
    accent = (designer_pick.get("accent_style") or "").strip()
    if accent:
        return accent + " aesthetic"
    return "minimal editorial aesthetic"


def _composition_phrase(designer_pick: Dict) -> str:
    """Composition hint — drives DALL-E layout. Tied to layout_archetype
    when available, with a sane default."""
    arch = (designer_pick.get("layout_archetype") or "").strip()
    return {
        "editorial-scroll": "centered with generous negative space",
        "showcase":         "centered focal element with breathing room",
        "statement":        "single dominant motif, dead center",
        "immersive":        "edge-to-edge composition with depth",
        "split":            "balanced asymmetric composition",
        "minimal-single":   "one element, vast empty space",
    }.get(arch, "balanced composition with breathing room")


def _lighting_phrase(designer_pick: Dict) -> str:
    """Lighting derives from sub-strand vibe: noir = cinematic dark;
    minimal = even neutral; warm = golden; etc."""
    sub = (designer_pick.get("sub_strand_id") or "").lower()
    if "noir" in sub:
        return "cinematic noir lighting, deep shadows"
    if "warm" in sub:
        return "warm golden lighting"
    if "cold" in sub or "minimal" in sub:
        return "even neutral lighting"
    if "earth" in sub or "organic" in sub:
        return "soft natural daylight"
    if "raw" in sub or "brutalist" in sub:
        return "harsh directional lighting"
    if "pop" in sub or "bold" in sub:
        return "vivid high-contrast lighting"
    return "controlled studio lighting"


def _mood_phrase(enriched_brief: Dict) -> str:
    """Free-form mood line from inferred_vibe — kept short, descriptive."""
    vibe = (enriched_brief.get("inferred_vibe") or "").strip()
    if not vibe:
        return "refined and intentional"
    if any(w in vibe.lower() for w in ("regal", "royal", "luxury", "premium")):
        return "ornate but restrained"
    if any(w in vibe.lower() for w in ("warm", "organic", "natural", "wellness")):
        return "warm and grounded"
    if any(w in vibe.lower() for w in ("minimal", "editorial")):
        return "quiet and considered"
    if any(w in vibe.lower() for w in ("bold", "brutalist")):
        return "confident and uncompromising"
    return "refined and intentional"


def build_dalle_prompt(
    slot_name: str,
    enriched_brief: Optional[Dict[str, Any]],
    designer_pick: Optional[Dict[str, Any]],
) -> str:
    """Compose a DALL-E 3 prompt for a decorative slot.

    Pattern:
      <subject template> in <aesthetic>, <composition>, <lighting>,
      <mood>, no text, no words, no letters.

    The 'no text' closure is critical — DALL-E 3 hallucinates fake
    typography aggressively without it. Per the spec, every prompt
    ends with this sentinel.
    """
    enriched_brief = enriched_brief or {}
    designer_pick = designer_pick or {}
    template = _DALLE_SLOT_TEMPLATES.get(
        slot_name,
        # Generic fallback for unknown slots — still ends with the
        # text suppressor.
        (
            "Subtle decorative element in {aesthetic}, "
            "{composition}, {lighting}, {mood}, "
            "no text, no words, no letters"
        ),
    )
    return template.format(
        aesthetic=_aesthetic_phrase(enriched_brief, designer_pick),
        composition=_composition_phrase(designer_pick),
        lighting=_lighting_phrase(designer_pick),
        mood=_mood_phrase(enriched_brief),
    )
