"""
practitioner_profile_agent.py — Practitioner (human) profile data layer.

Mirrors business_profile_agent.py shape but keyed on owner_id, not
business_id. One row per practitioner — follows the human across every
business they run, so timezone / legal name / working hours / key
relationships don't reset when they switch context.

JIT capture pattern (from Build 2) is reused: PHRASING dict for
brand-voice-matched asks, update_field for single-field writes,
get_missing_jit_fields for the directive injector.

TODO(auth-migration): currently keyed on the hardcoded OWNER_ID. When
real auth ships, every new auth.users row needs a matching practitioner_profiles
row (or upsert_profile lazily creates one on first JIT write).
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("practitioner_profile_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] practitioner_profile: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


HTTP_TIMEOUT = 15.0


# ─── JIT capture (Build 3) ────────────────────────────────────

JIT_FIELDS_V1 = [
    "full_legal_name",
    "preferred_title",
    "timezone",
    "working_hours_start",
    "working_hours_end",
    "primary_accountant_name",
]


PHRASING: Dict[str, Dict[str, str]] = {
    "full_legal_name": {
        "warm":      "Quick thing — what's your full legal name? I want to make sure your contracts and legal docs use the right name, not a nickname.",
        "formal":    "For contracts and legal documents, please confirm your full legal name.",
        "casual":    "What's the full legal name on your stuff? Need it for contracts.",
        "ministry":  "Quick check — what's your full legal name? I want to make sure ministry contracts and agreements use the right name.",
        "corporate": "Required for legal documents: full legal name as it appears on official records.",
        "direct":    "Full legal name? Need it for contracts.",
    },
    "preferred_title": {
        "warm":      "How would you like to be addressed in formal communication? Pastor, Coach, Founder, something else?",
        "formal":    "For professional correspondence, what title do you prefer? (Pastor, Coach, Founder, Dr., etc.)",
        "casual":    "What title do you go by? Pastor, Coach, just your name?",
        "ministry":  "What title should I use in ministry communications? Pastor, Lead Pastor, Reverend?",
        "corporate": "Preferred professional title for correspondence?",
        "direct":    "What title? Pastor, Coach, Founder?",
    },
    "timezone": {
        "warm":      "What timezone are you in? I want to schedule sessions and send messages at the right time for you.",
        "formal":    "Please confirm your timezone for scheduling and time-sensitive communications.",
        "casual":    "What timezone are you in?",
        "ministry":  "What timezone do you operate from? Affects how I schedule and time things.",
        "corporate": "Operating timezone for scheduling?",
        "direct":    "Timezone?",
    },
    "working_hours_start": {
        "warm":      "When does your work day usually start? I'll respect that when scheduling and queuing things up.",
        "formal":    "Please confirm your typical work-day start time.",
        "casual":    "What time you usually start the day?",
        "ministry":  "When does your work day typically begin? I'll honor that for scheduling.",
        "corporate": "Standard work-day start time?",
        "direct":    "Work day starts at?",
    },
    "working_hours_end": {
        "warm":      "And when do you typically wrap up? I'll avoid scheduling things after that unless you tell me otherwise.",
        "formal":    "Typical work-day end time?",
        "casual":    "When you usually done?",
        "ministry":  "When does your work day usually end? I'll respect that.",
        "corporate": "Standard work-day end time?",
        "direct":    "Work day ends at?",
    },
    "primary_accountant_name": {
        "warm":      "Quick one — who's your accountant? I'll save their name so I can refer to them when finance stuff comes up.",
        "formal":    "Please provide the name of your primary accountant for reference in financial communications.",
        "casual":    "Who's your accountant?",
        "ministry":  "Who handles your accounting? I'll save their name for when financial matters come up.",
        "corporate": "Primary accountant's name?",
        "direct":    "Accountant's name?",
    },
}

_VALID_VOICES = {"warm", "formal", "casual", "ministry", "corporate", "direct"}


# ─── Supabase REST helpers (mirrors business_profile_agent.py) ──

def _sb_url() -> str:
    return os.environ.get("SUPABASE_URL", "").rstrip("/")


def _sb_anon() -> str:
    return os.environ.get("SUPABASE_ANON", "")


def _sb_headers() -> Dict[str, str]:
    return {
        "apikey": _sb_anon(),
        "Authorization": f"Bearer {_sb_anon()}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _sb_get(path: str) -> Optional[Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.get(f"{_sb_url()}/rest/v1{path}", headers=_sb_headers())
        if r.status_code >= 400:
            logger.warning(f"sb GET {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb GET {path} failed: {e}")
        return None


def _sb_post(path: str, body: Any) -> Optional[Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(
                f"{_sb_url()}/rest/v1{path}",
                headers={**_sb_headers(), "Prefer": "return=representation,resolution=merge-duplicates"},
                content=json.dumps(body),
            )
        if r.status_code >= 400:
            logger.warning(f"sb POST {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb POST {path} failed: {e}")
        return None


def _sb_patch(path: str, body: Dict[str, Any]) -> Optional[Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.patch(
                f"{_sb_url()}/rest/v1{path}",
                headers=_sb_headers(),
                content=json.dumps(body),
            )
        if r.status_code >= 400:
            logger.warning(f"sb PATCH {path}: {r.status_code} {r.text[:200]}")
            return None
        return r.json() if r.text else None
    except httpx.HTTPError as e:
        logger.warning(f"sb PATCH {path} failed: {e}")
        return None


# ─── Phrasing ──────────────────────────────────────────────────

def get_phrasing(field_path: str, brand_voice: Optional[str]) -> str:
    voice = (brand_voice or "warm").lower()
    if voice not in _VALID_VOICES:
        voice = "warm"
    field_map = PHRASING.get(field_path) or {}
    return field_map.get(voice) or field_map.get("warm") or ""


# ─── Profile CRUD ──────────────────────────────────────────────

def get_profile(owner_id: str) -> Optional[Dict[str, Any]]:
    if not owner_id:
        return None
    rows = _sb_get(f"/practitioner_profiles?owner_id=eq.{owner_id}") or []
    return rows[0] if rows else None


def _calculate_completeness(profile: Dict[str, Any]) -> float:
    """0.0..1.0. Core identity + working hours weighted 0.7,
    relationship fields weighted 0.3."""
    core_fields = [
        "full_legal_name", "preferred_title", "timezone",
        "working_hours_start", "working_hours_end",
    ]
    relationship_fields = [
        "primary_accountant_name", "primary_attorney_name",
        "primary_mentor_name", "primary_partner_name",
    ]
    core_filled = sum(1 for f in core_fields if profile.get(f))
    rel_filled = sum(1 for f in relationship_fields if profile.get(f))
    score = (core_filled / len(core_fields)) * 0.7 + (rel_filled / len(relationship_fields)) * 0.3
    return round(min(score, 1.0), 4)


def upsert_profile(owner_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not owner_id:
        return None

    existing = get_profile(owner_id) or {}
    merged: Dict[str, Any] = {**existing, **{k: v for k, v in (data or {}).items() if v is not None}}
    merged["owner_id"] = owner_id
    merged.pop("created_at", None)
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()
    merged["profile_completeness"] = _calculate_completeness(merged)

    if existing:
        result = _sb_patch(f"/practitioner_profiles?owner_id=eq.{owner_id}", merged)
    else:
        result = _sb_post("/practitioner_profiles", merged)

    if isinstance(result, list) and result:
        return result[0]
    return result if isinstance(result, dict) else get_profile(owner_id)


def update_field(owner_id: str, field_path: str, new_value: Any) -> Optional[Dict[str, Any]]:
    """Update a single practitioner_profiles field. Flat schema in v1
    (no dotted paths). Bumps profile_completeness +0.1, capped at 1.0."""
    if not owner_id or not field_path:
        return None

    current = get_profile(owner_id) or {"owner_id": owner_id}
    update_payload: Dict[str, Any] = {
        field_path: new_value,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        new_completeness = min(1.0, float(current.get("profile_completeness") or 0) + 0.1)
    except (TypeError, ValueError):
        new_completeness = float(current.get("profile_completeness") or 0)
    update_payload["profile_completeness"] = round(new_completeness, 4)

    if get_profile(owner_id):
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.patch(
                f"{_sb_url()}/rest/v1/practitioner_profiles?owner_id=eq.{owner_id}",
                headers=_sb_headers(),
                content=json.dumps(update_payload),
            )
            if r.status_code >= 400:
                logger.warning(f"update_field PATCH failed: {r.status_code} {r.text[:200]}")
                return None
    else:
        # Edge case: row doesn't exist yet. Create it on first write.
        body = {"owner_id": owner_id, **update_payload}
        _sb_post("/practitioner_profiles", body)

    return get_profile(owner_id)


def get_missing_jit_fields(owner_id: str) -> List[str]:
    profile = get_profile(owner_id) or {}
    missing: List[str] = []
    for field_path in JIT_FIELDS_V1:
        if not profile.get(field_path):
            missing.append(field_path)
    return missing


def is_complete(owner_id: str) -> bool:
    p = get_profile(owner_id) or {}
    try:
        return float(p.get("profile_completeness") or 0) >= 1.0
    except (TypeError, ValueError):
        return False


# ─── Chief context block ──────────────────────────────────────

def chief_context_block(owner_id: str) -> str:
    """Markdown block describing the practitioner. Injected into the
    Chief system prompt above the business profile block — the Chief
    reads about the human first, then the business they're running."""
    if not owner_id:
        return ""

    try:
        profile = get_profile(owner_id)
    except Exception as e:
        logger.warning(f"chief_context_block fetch failed: {e}")
        return ""

    if not profile:
        return "## Practitioner\n(No practitioner profile yet — treat the user generically until they share details.)\n"

    lines: List[str] = ["## Practitioner (the human running these businesses)"]
    if profile.get("full_legal_name"):
        lines.append(f"  Full legal name: {profile['full_legal_name']}")
    if profile.get("preferred_title"):
        lines.append(f"  Preferred title: {profile['preferred_title']}")
    if profile.get("pronouns"):
        lines.append(f"  Pronouns: {profile['pronouns']}")
    if profile.get("timezone"):
        lines.append(f"  Timezone: {profile['timezone']}")
    if profile.get("working_hours_start") or profile.get("working_hours_end"):
        s = profile.get("working_hours_start") or "?"
        e = profile.get("working_hours_end") or "?"
        lines.append(f"  Working hours: {s} - {e}")
    if profile.get("primary_accountant_name"):
        lines.append(f"  Accountant: {profile['primary_accountant_name']}")
    if profile.get("primary_attorney_name"):
        lines.append(f"  Attorney: {profile['primary_attorney_name']}")
    if profile.get("primary_mentor_name"):
        lines.append(f"  Mentor: {profile['primary_mentor_name']}")
    if profile.get("primary_partner_name"):
        lines.append(f"  Partner: {profile['primary_partner_name']}")
    completeness = int(round(float(profile.get("profile_completeness") or 0) * 100))
    lines.append(f"  Profile completeness: {completeness}%")
    if profile.get("proactive_capture_enabled"):
        lines.append("  (User has opted into proactive practitioner-profile asks.)")
    return "\n".join(lines) + "\n"
