"""
business_profile_agent.py — Business Profile data layer for the Solutionist System.

Captures what kind of business each practitioner runs (coach / consultant /
creative / fitness_wellness / financial_educator / course_creator /
service_provider / custom) plus how they deliver, how they price, what
sensitive areas apply, and which jurisdiction they operate in.

Downstream systems (Contracts, Client Portal, Chief, Email Marketing,
Privacy Policy generator, etc.) read from business_profiles +
business_type_archetypes to produce business-type-appropriate output
instead of generic content.

Tables:
  business_profiles         — one row per business
  business_type_archetypes  — 8 archetype defaults (seeded in migration)
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("business_profile_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] business_profile: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


HTTP_TIMEOUT = 15.0

REQUIRED_FIELDS = (
    "business_type",
    "service_models",
    "pricing_models",
    "governing_state",
    "brand_voice",
)
OPTIONAL_FIELDS = (
    "business_subtype",
    "deliverables_description",
    "sensitive_areas",
)


# ──────────────────────────────────────────────────────────────
# Supabase REST helpers (mirrors foundation_agent.py pattern)
# ──────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────
# Archetype lookup
# ──────────────────────────────────────────────────────────────

def get_archetype(business_type: str) -> Optional[Dict[str, Any]]:
    """Fetch one archetype row by business_type, or None."""
    if not business_type:
        return None
    rows = _sb_get(f"/business_type_archetypes?business_type=eq.{business_type}") or []
    return rows[0] if rows else None


def list_archetypes() -> List[Dict[str, Any]]:
    """Return all archetypes (used by the wizard's first step)."""
    return _sb_get("/business_type_archetypes?order=display_name.asc") or []


# ──────────────────────────────────────────────────────────────
# Profile CRUD
# ──────────────────────────────────────────────────────────────

def get_profile(business_id: str) -> Optional[Dict[str, Any]]:
    """Fetch the business_profiles row for a business, or None."""
    if not business_id:
        return None
    rows = _sb_get(f"/business_profiles?business_id=eq.{business_id}") or []
    return rows[0] if rows else None


def upsert_profile(business_id: str, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Insert or update the profile. Recomputes profile_completeness and sets
    completed_at when completeness hits 1.0. Returns the resulting row.
    """
    if not business_id:
        return None

    existing = get_profile(business_id) or {}
    merged: Dict[str, Any] = {**existing, **{k: v for k, v in (data or {}).items() if v is not None}}
    merged["business_id"] = business_id
    merged.pop("created_at", None)
    merged["updated_at"] = datetime.now(timezone.utc).isoformat()

    completeness = calculate_completeness(merged)
    merged["profile_completeness"] = completeness
    if completeness >= 1.0:
        merged.setdefault("completed_at", merged["updated_at"])
    else:
        merged["completed_at"] = None

    if existing:
        result = _sb_patch(f"/business_profiles?business_id=eq.{business_id}", merged)
    else:
        merged.setdefault("business_type", merged.get("business_type") or "custom")
        merged.setdefault("service_models", merged.get("service_models") or [])
        merged.setdefault("pricing_models", merged.get("pricing_models") or [])
        result = _sb_post("/business_profiles", merged)

    if isinstance(result, list) and result:
        return result[0]
    return result if isinstance(result, dict) else get_profile(business_id)


TONE_TO_BRAND_VOICE = {
    "warm": "warm",
    "professional": "formal",
    "bold": "direct",
    "inspirational": "warm",
    "educational": "formal",
}


def _tones_to_brand_voice(tones: Optional[List[Any]]) -> Optional[str]:
    """Map onboarding tone selections to a single brand_voice. First mappable
    tone wins. Returns None when nothing maps so the Chief asks later."""
    if not tones:
        return None
    if isinstance(tones, str):
        tones = [tones]
    if not isinstance(tones, list):
        return None
    for t in tones:
        if not t:
            continue
        key = str(t).strip().lower()
        if key in TONE_TO_BRAND_VOICE:
            return TONE_TO_BRAND_VOICE[key]
    return None


def seed_from_onboarding(
    business_id: str,
    business_type: str,
    tones: Optional[List[Any]] = None,
    voice_profile: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Idempotent seed called from OnboardingFlow.handleLaunch. Maps tones to
    brand_voice, applies archetype defaults, and marks the row auto_seeded.

    If a row already exists for this business, only NULL/empty fields are
    filled. Never overwrites user-confirmed answers.
    """
    if not business_id:
        return None

    arche = get_archetype(business_type) or {}
    brand_voice = _tones_to_brand_voice(tones)

    # Build a "we know this much" baseline from the archetype.
    seed: Dict[str, Any] = {
        "business_type": business_type or "custom",
        "service_models": arche.get("default_service_models") or [],
        "pricing_models": arche.get("default_pricing_models") or [],
        "typical_engagement_length": arche.get("default_engagement_length"),
        "produces_deliverables": bool(arche.get("default_produces_deliverables")),
        "sensitive_areas": arche.get("default_sensitive_areas") or {},
        "auto_seeded": True,
        "auto_seeded_at": datetime.now(timezone.utc).isoformat(),
        "auto_seeded_source": "onboarding-flow",
    }
    if brand_voice:
        seed["brand_voice"] = brand_voice

    existing = get_profile(business_id)
    if not existing:
        return upsert_profile(business_id, seed)

    # Idempotent fill: only set fields the existing row hasn't filled.
    patch: Dict[str, Any] = {}
    for k, v in seed.items():
        if k in ("auto_seeded", "auto_seeded_at", "auto_seeded_source"):
            continue
        cur = existing.get(k)
        is_empty = (
            cur is None
            or (isinstance(cur, str) and not cur.strip())
            or (isinstance(cur, list) and len(cur) == 0)
            or (isinstance(cur, dict) and not any(bool(x) for x in cur.values()))
        )
        if is_empty and v not in (None, "", [], {}):
            patch[k] = v
    if not patch:
        return existing
    # Stamp the audit columns even on partial fills so we know we touched the row.
    patch["auto_seeded"] = True
    patch.setdefault("auto_seeded_at", seed["auto_seeded_at"])
    patch.setdefault("auto_seeded_source", "onboarding-flow")
    return upsert_profile(business_id, patch)


def import_from_strategy_track(business_id: str) -> Optional[Dict[str, Any]]:
    """
    Pull service_models / pricing_models from strategy_tracks into the
    business_profiles row. Called when complete_strategy_track fires.

    Maps:
      service_packages[].delivery_format -> service_models[]
      pricing_strategy.tiers (any) -> pricing_models = ['package']

    Idempotent: never overwrites a non-empty service_models/pricing_models
    list. Returns the resulting profile or None if there's nothing to import.
    """
    if not business_id:
        return None

    tracks = _sb_get(
        f"/strategy_tracks?business_id=eq.{business_id}"
        f"&order=created_at.desc&limit=1"
    ) or []
    if not tracks:
        return None
    track = tracks[0]

    packages = track.get("service_packages") or []
    pricing = track.get("pricing_strategy") or {}

    derived_service_models: List[str] = []
    seen: set = set()
    for pkg in packages:
        if not isinstance(pkg, dict):
            continue
        df = (pkg.get("delivery_format") or "").lower()
        if "group" in df:
            tag = "group_program"
        elif "course" in df or "digital" in df:
            tag = "course_digital"
        elif "retainer" in df:
            tag = "retainer"
        elif "done-for-you" in df or "dfy" in df:
            tag = "done_for_you"
        else:
            tag = "one_on_one"
        if tag not in seen:
            derived_service_models.append(tag)
            seen.add(tag)

    derived_pricing_models: List[str] = []
    if isinstance(pricing, dict) and pricing.get("tiers"):
        derived_pricing_models = ["package"]

    if not derived_service_models and not derived_pricing_models:
        return None

    profile = get_profile(business_id) or {}
    patch: Dict[str, Any] = {}
    if derived_service_models and not (profile.get("service_models") or []):
        patch["service_models"] = derived_service_models
    if derived_pricing_models and not (profile.get("pricing_models") or []):
        patch["pricing_models"] = derived_pricing_models

    if not patch:
        return profile or None
    return upsert_profile(business_id, patch)


def apply_archetype_defaults(business_id: str, business_type: str) -> Optional[Dict[str, Any]]:
    """
    Pre-fill the profile from an archetype when the user first picks a type.
    Subsequent wizard steps let them confirm or override these defaults.
    """
    arche = get_archetype(business_type)
    if not arche:
        logger.warning(f"apply_archetype_defaults: unknown archetype {business_type}")
        return None

    seed = {
        "business_type": business_type,
        "service_models": arche.get("default_service_models") or [],
        "pricing_models": arche.get("default_pricing_models") or [],
        "typical_engagement_length": arche.get("default_engagement_length"),
        "produces_deliverables": bool(arche.get("default_produces_deliverables")),
        "sensitive_areas": arche.get("default_sensitive_areas") or {},
    }
    return upsert_profile(business_id, seed)


# ──────────────────────────────────────────────────────────────
# Completeness + disclaimers
# ──────────────────────────────────────────────────────────────

def calculate_completeness(profile: Dict[str, Any]) -> float:
    """
    0.0 to 1.0 based on filled fields.
    Required fields each contribute 1/(len(REQUIRED_FIELDS)+1).
    Optional fields contribute the remaining fraction proportionally
    when at least one is present, so a fully-required profile that
    skips all optional fields lands at ~0.83 — incomplete by design.
    """
    if not profile:
        return 0.0

    req_score = 0
    for f in REQUIRED_FIELDS:
        v = profile.get(f)
        if isinstance(v, list):
            if v:
                req_score += 1
        elif isinstance(v, str):
            if v.strip():
                req_score += 1
        elif v not in (None, ""):
            req_score += 1
    req_pct = req_score / len(REQUIRED_FIELDS)

    opt_score = 0
    for f in OPTIONAL_FIELDS:
        v = profile.get(f)
        if isinstance(v, dict):
            if any(bool(x) for x in v.values()):
                opt_score += 1
        elif isinstance(v, str):
            if v.strip():
                opt_score += 1
        elif v not in (None, "", [], {}):
            opt_score += 1
    opt_pct = opt_score / len(OPTIONAL_FIELDS)

    score = (req_pct * 0.85) + (opt_pct * 0.15)
    return round(min(score, 1.0), 4)


def get_required_disclaimers(business_id: str) -> List[str]:
    """
    Union of:
      - The archetype's required_disclaimers
      - Disclaimers triggered by sensitive_areas overrides on the profile
    Used by Contracts engine, policy generators, etc.
    """
    profile = get_profile(business_id)
    if not profile:
        return []

    disclaimers: List[str] = []
    arche = get_archetype(profile.get("business_type") or "")
    if arche:
        disclaimers.extend(arche.get("required_disclaimers") or [])

    sa = profile.get("sensitive_areas") or {}
    if isinstance(sa, dict):
        if sa.get("physical_activity"):
            disclaimers.extend(["liability_waiver", "medical_clearance", "not_medical"])
        if sa.get("health_advice"):
            disclaimers.append("not_medical")
        if sa.get("financial_advice"):
            disclaimers.extend(["not_financial_advice", "no_fiduciary"])
        if sa.get("financial_education"):
            disclaimers.extend(["sec_education_only", "past_results_disclaimer"])
        if sa.get("legal_adjacent"):
            disclaimers.append("not_legal_counsel")
        if sa.get("session_recording"):
            disclaimers.append("recording_consent")
        if sa.get("group_confidentiality"):
            disclaimers.append("group_confidentiality")
        if sa.get("minors_possible"):
            disclaimers.append("parental_consent")

    seen: List[str] = []
    for d in disclaimers:
        if d and d not in seen:
            seen.append(d)
    return seen


def is_complete(business_id: str) -> bool:
    profile = get_profile(business_id)
    if not profile:
        return False
    try:
        return float(profile.get("profile_completeness") or 0) >= 1.0
    except (TypeError, ValueError):
        return False


# ──────────────────────────────────────────────────────────────
# Chief context block
# ──────────────────────────────────────────────────────────────

def chief_context_block(business_id: str) -> str:
    """
    Markdown block describing this business's profile, injected into the
    Chief system prompt. Returns empty string when no profile exists,
    so the Chief simply doesn't reference it (rather than crashing).
    """
    if not business_id:
        return ""

    try:
        profile = get_profile(business_id)
    except Exception as e:
        logger.warning(f"chief_context_block fetch failed: {e}")
        return ""
    if not profile:
        return ""

    arche = get_archetype(profile.get("business_type") or "") or {}

    lines: List[str] = ["## Business Profile"]

    bt = profile.get("business_type") or "unspecified"
    display = arche.get("display_name") or bt
    subtype = (profile.get("business_subtype") or "").strip()
    if subtype:
        lines.append(f"Type: {display} ({subtype})")
    else:
        lines.append(f"Type: {display}")

    if profile.get("service_models"):
        lines.append("Service models: " + ", ".join(profile["service_models"]))
    if profile.get("pricing_models"):
        lines.append("Pricing models: " + ", ".join(profile["pricing_models"]))
    if profile.get("typical_engagement_length"):
        lines.append(f"Typical engagement: {profile['typical_engagement_length']}")

    if profile.get("produces_deliverables"):
        deliv = (profile.get("deliverables_description") or "").strip()
        if deliv:
            lines.append(f"Deliverables: {deliv}")
        else:
            lines.append("Produces transferable deliverables.")
    else:
        lines.append("Service IS the value (no transferable deliverables).")

    sensitive = profile.get("sensitive_areas") or {}
    flagged = [k for k, v in sensitive.items() if v]
    if flagged:
        lines.append("Sensitive areas: " + ", ".join(flagged))

    if profile.get("brand_voice"):
        lines.append(f"Brand voice: {profile['brand_voice']}")
    if profile.get("governing_state"):
        lines.append(f"Governing state: {profile['governing_state']}")
    if profile.get("international_clients"):
        lines.append("Has international clients.")

    completeness = profile.get("profile_completeness")
    try:
        pct = round(float(completeness or 0) * 100)
    except (TypeError, ValueError):
        pct = 0
    lines.append(f"Profile completeness: {pct}%")

    type_steer = {
        "coach":
            "When advising, frame in terms of client transformation, packages, "
            "retainers, and confidentiality. Don't recommend transferable deliverables.",
        "consultant":
            "When advising, frame in terms of scope, milestones, IP-on-payment, "
            "and reports/recommendations as deliverables.",
        "creative":
            "When advising, frame in terms of deliverables, revisions, kill fees, "
            "and IP transfer. Always assume client owns final work upon payment.",
        "fitness_wellness":
            "When advising, surface liability waiver and medical-clearance considerations. "
            "Treat in-person logistics and photo/video releases as standard.",
        "financial_educator":
            "When advising, hold the SEC line: education-only, no fiduciary, no specific "
            "investment advice. All examples must carry past-results-don't-guarantee language.",
        "course_creator":
            "When advising, frame in terms of refund windows, redistribution prohibitions, "
            "access duration, and cohort logistics.",
        "service_provider":
            "When advising, frame in terms of scope-of-work, cancellation policies, and "
            "general liability. Recurring service contracts are common.",
        "custom":
            "Profile is custom — ask clarifying questions before assuming standard structures.",
    }
    steer = type_steer.get(bt)
    if steer:
        lines.append(steer)

    return "\n".join(lines)
