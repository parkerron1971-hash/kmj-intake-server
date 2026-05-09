"""Pass 4.0b.5 — Slot persistence on business_sites.site_config.slots.

Read/modify/write helpers backed by the existing Supabase REST surface
(brand_engine._sb_get + _sb_patch). Each write fetches the current
site_config first so we don't clobber concurrent writes (mirrors the
pattern at public_site.py:2682-2727).

Slot record shape persisted under site_config["slots"][slot_name]:

  {
    "default_url": str | None,        # populated by populate_slots_for_site
    "default_source": "unsplash" | "dalle" | None,
    "default_credit": {                # only when default_source == "unsplash"
      "name": str,
      "url": str,
      "username": str
    } | None,
    "custom_url": str | None,         # set by /slots/upload
    "custom_uploaded_at": str | None, # ISO8601 UTC
    "reroll_count_today": int,        # 0 each new UTC date
    "reroll_last_at": str | None      # ISO8601 UTC of most recent reroll
  }
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Per the spec: max 3 rerolls per slot per day per business, regardless
# of who's clicking. Daily window is the UTC date.
MAX_REROLLS_PER_DAY = 3


def _now_utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_date_today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


def _utc_date_of(iso_str: Optional[str]) -> Optional[str]:
    """Extract the YYYY-MM-DD portion of a stored ISO8601 timestamp.
    Returns None when input is falsy or doesn't look like an ISO date."""
    if not iso_str or not isinstance(iso_str, str) or len(iso_str) < 10:
        return None
    return iso_str[:10]


def _fetch_site_row(business_id: str) -> Tuple[Optional[str], Dict[str, Any]]:
    """Fetch (site_id, site_config) for the business, or (None, {}) when
    the row doesn't exist. Imports brand_engine lazily so this module
    stays importable in test contexts without Supabase env vars."""
    try:
        from brand_engine import _sb_get as be_get
    except Exception as e:
        logger.warning(f"[slot_storage] brand_engine import failed: {e}")
        return None, {}

    rows = be_get(
        f"/business_sites?business_id=eq.{business_id}"
        "&select=id,site_config&limit=1"
    ) or []
    if not rows:
        return None, {}
    return rows[0].get("id"), (rows[0].get("site_config") or {})


def _patch_site_config(site_id: str, site_config: Dict[str, Any]) -> bool:
    try:
        from brand_engine import _sb_patch as be_patch
    except Exception as e:
        logger.warning(f"[slot_storage] brand_engine import failed: {e}")
        return False
    try:
        be_patch(
            f"/business_sites?id=eq.{site_id}",
            {"site_config": site_config},
        )
        return True
    except Exception as e:
        logger.warning(f"[slot_storage] patch failed for {site_id}: {e}")
        return False


def _empty_slot_record() -> Dict[str, Any]:
    return {
        "default_url": None,
        "default_source": None,
        "default_credit": None,
        # Pass 4.0b.5 PART 5: reroll context. populate_slots_for_site
        # caches the original Unsplash query and DALL-E prompt at
        # populate time so /slots/{id}/{slot}/reroll can re-fire the
        # same retrieval without re-running enrichment + designer.
        "default_query": None,           # Unsplash search string
        "default_dalle_prompt": None,    # DALL-E prompt
        "custom_url": None,
        "custom_uploaded_at": None,
        "reroll_count_today": 0,
        "reroll_last_at": None,
    }


# ─── Read ────────────────────────────────────────────────────────────

def get_slot(business_id: str, slot_name: str) -> Optional[Dict[str, Any]]:
    """Return the persisted slot record, or None if the row / slots
    map / slot_name doesn't exist yet. None means 'unset, render
    placeholder' — slot_resolver handles that case explicitly."""
    _, cfg = _fetch_site_row(business_id)
    slots = cfg.get("slots") or {}
    return slots.get(slot_name)


def get_all_slots(business_id: str) -> Dict[str, Dict[str, Any]]:
    """Return every persisted slot record for this business. Empty dict
    when the row exists but has no slots, or when the row is missing."""
    _, cfg = _fetch_site_row(business_id)
    return dict(cfg.get("slots") or {})


# ─── Write — defaults (populated by builder pipeline) ───────────────

def set_slot_default(
    business_id: str,
    slot_name: str,
    url: str,
    source: str,
    credit: Optional[Dict[str, Any]] = None,
    query: Optional[str] = None,
    dalle_prompt: Optional[str] = None,
) -> bool:
    """Set the default (auto-suggested) URL for a slot. Custom uploads
    are NOT touched — they continue to win in resolution. Source must
    be 'unsplash' or 'dalle' (the two non-placeholder strategies).

    `query` and `dalle_prompt` are the reroll-context cache (PART 5).
    Pass `query` for Unsplash sources so /reroll can re-fire the same
    search; pass `dalle_prompt` for DALL-E sources so /reroll can
    re-generate against the same brief. Existing values are preserved
    when None is passed — to clear, pass an empty string."""
    site_id, cfg = _fetch_site_row(business_id)
    if not site_id:
        return False
    slots = dict(cfg.get("slots") or {})
    record = dict(slots.get(slot_name) or _empty_slot_record())
    record["default_url"] = url
    record["default_source"] = source
    record["default_credit"] = credit
    if query is not None:
        record["default_query"] = query or None
    if dalle_prompt is not None:
        record["default_dalle_prompt"] = dalle_prompt or None
    slots[slot_name] = record
    cfg["slots"] = slots
    return _patch_site_config(site_id, cfg)


# ─── Write — custom uploads (practitioner-supplied) ─────────────────

def set_slot_custom(
    business_id: str,
    slot_name: str,
    url: str,
) -> bool:
    """Set the practitioner-uploaded URL for a slot. Stamps
    custom_uploaded_at. Default record stays intact so /clear can
    revert without re-querying Unsplash."""
    site_id, cfg = _fetch_site_row(business_id)
    if not site_id:
        return False
    slots = dict(cfg.get("slots") or {})
    record = dict(slots.get(slot_name) or _empty_slot_record())
    record["custom_url"] = url
    record["custom_uploaded_at"] = _now_utc_iso()
    slots[slot_name] = record
    cfg["slots"] = slots
    return _patch_site_config(site_id, cfg)


def clear_slot_custom(business_id: str, slot_name: str) -> bool:
    """Revert a slot from custom upload back to default suggestion.
    Does NOT delete the file from Supabase Storage — keep around for
    undo / audit. Resolution falls through to default_url."""
    site_id, cfg = _fetch_site_row(business_id)
    if not site_id:
        return False
    slots = dict(cfg.get("slots") or {})
    record = dict(slots.get(slot_name) or _empty_slot_record())
    record["custom_url"] = None
    record["custom_uploaded_at"] = None
    slots[slot_name] = record
    cfg["slots"] = slots
    return _patch_site_config(site_id, cfg)


# ─── Write — reroll counter ─────────────────────────────────────────

def reset_rerolls_if_new_day(
    business_id: str,
    slot_name: str,
) -> bool:
    """Reset reroll_count_today to 0 when the most recent reroll was on
    a UTC date different from today. Returns True when a reset
    happened, False when no reset was needed (or when there's nothing
    to reset because the slot has never been rerolled)."""
    site_id, cfg = _fetch_site_row(business_id)
    if not site_id:
        return False
    slots = dict(cfg.get("slots") or {})
    record = dict(slots.get(slot_name) or _empty_slot_record())
    last_date = _utc_date_of(record.get("reroll_last_at"))
    today = _utc_date_today()
    if last_date and last_date != today:
        record["reroll_count_today"] = 0
        slots[slot_name] = record
        cfg["slots"] = slots
        _patch_site_config(site_id, cfg)
        return True
    return False


def increment_reroll(business_id: str, slot_name: str) -> int:
    """Bump the reroll counter and stamp reroll_last_at. Auto-resets
    when crossing a UTC date boundary. Returns the new count after
    the increment. Caller should check can_reroll() BEFORE invoking
    a paid retrieval — this only updates the counter."""
    site_id, cfg = _fetch_site_row(business_id)
    if not site_id:
        return 0
    slots = dict(cfg.get("slots") or {})
    record = dict(slots.get(slot_name) or _empty_slot_record())

    last_date = _utc_date_of(record.get("reroll_last_at"))
    today = _utc_date_today()
    current = int(record.get("reroll_count_today") or 0)
    if last_date and last_date != today:
        current = 0  # silent reset on day rollover

    current += 1
    record["reroll_count_today"] = current
    record["reroll_last_at"] = _now_utc_iso()
    slots[slot_name] = record
    cfg["slots"] = slots
    _patch_site_config(site_id, cfg)
    return current


def can_reroll(business_id: str, slot_name: str) -> Tuple[bool, int]:
    """Returns (allowed, current_count_today). Considers the daily
    rollover reset so a slot rerolled 3× yesterday is fresh today."""
    record = get_slot(business_id, slot_name) or {}
    last_date = _utc_date_of(record.get("reroll_last_at"))
    today = _utc_date_today()
    current = int(record.get("reroll_count_today") or 0)
    if last_date and last_date != today:
        current = 0
    return (current < MAX_REROLLS_PER_DAY, current)
