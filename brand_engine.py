"""
brand_engine.py — Brand Engine v1.

Single canonical read/write authority for everything a downstream artifact
needs to render the practitioner's brand: colors, fonts, voice, legal copy,
practitioner display info, footer, signature block.

Reads from:
  businesses                  — name, type, settings.brand_kit, voice_profile, in_the_clear
  business_profiles           — business_type, brand_voice, governing_state, sensitive_areas
  practitioner_profiles       — full_legal_name, preferred_title, timezone
  business_sites              — slug
  business_type_archetypes    — required_disclaimers, default_*

Writes to:
  businesses.settings.brand_kit       (always BOTH nested AND flat shape)
  businesses.brand_kit_history        (snapshot array, capped at 2)

Public API:
  get_bundle(business_id) -> dict
  save_brand_kit(business_id, kit) -> dict
  restore_snapshot(business_id, idx) -> dict
  generate_from_context(business_id) -> dict   # Claude-backed, not yet saved
  learn_from_url(business_id, url) -> dict     # Claude-backed, not yet saved
  chief_context_block(business_id) -> str
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("brand_engine")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] brand_engine: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


HTTP_TIMEOUT = 15.0
ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"


# ─────────────────────────────────────────────────────────────
# Defaults + maps
# ─────────────────────────────────────────────────────────────

DEFAULT_DESIGN: Dict[str, str] = {
    "primary_color": "#1a1a1a",
    "secondary_color": "#666666",
    "accent_color": "#d4af37",
    "background_color": "#ffffff",
    "text_color": "#1a1a1a",
    "font_heading": "Inter",
    "font_body": "Inter",
}

VIBE_FAMILY_MAP: Dict[str, str] = {
    "warm": "warm",
    "ministry": "warm",
    "casual": "warm",
    "formal": "formal",
    "corporate": "formal",
    "direct": "bold",
}

# Practitioner-affirmed sensitive flags → archetype-style disclaimer strings.
EXTRA_DISCLAIMERS_BY_FLAG: Dict[str, str] = {
    "health_advice": "not_medical",
    "physical_activity": "liability_waiver",
    "session_recording": "recording_consent",
    "financial_advice": "not_financial_advice",
}

DISCLAIMER_PHRASES: Dict[str, str] = {
    "not_medical": "Information provided is not medical advice.",
    "not_therapy": "Services are not a substitute for licensed therapy.",
    "not_legal_counsel": "Information provided is not legal advice.",
    "not_financial_advice": "Educational content only; not financial, investment, or tax advice.",
    "no_fiduciary": "No fiduciary relationship is created by use of these services.",
    "sec_education_only": "All content is for educational purposes only.",
    "results_not_guaranteed": "Results vary; outcomes are not guaranteed.",
    "liability_waiver": "Participants assume all risk of physical injury.",
    "medical_clearance": "Consult your physician before beginning any program.",
    "recording_consent": "Sessions may be recorded; consent required.",
    "ip_transfer_on_payment": "Deliverables transfer to the client upon final payment.",
    "scope_change_terms": "Changes to scope require written approval from both parties.",
    "kill_fee": "A kill fee applies for terminated engagements; see contract.",
    "revisions_limit": "Revisions limited as specified in the contract.",
    "portfolio_rights": "Provider retains rights to display work in portfolio unless otherwise agreed.",
    "no_redistribution": "Course content may not be redistributed.",
    "refund_policy": "Refund policy as stated in the enrollment agreement.",
    "access_terms": "Access terms as stated in the enrollment agreement.",
    "scope_of_work": "Services as defined in the scope of work.",
    "liability_general": "Limited liability as defined in the service agreement.",
    "cancellation_policy": "Cancellation policy as stated in the agreement.",
    "past_results_disclaimer": "Past performance does not guarantee future results.",
    "photo_release_optional": "Photo and video release optional; consent confirmed in writing.",
}


# ─────────────────────────────────────────────────────────────
# Supabase REST helpers (mirror business_profile_agent pattern)
# ─────────────────────────────────────────────────────────────

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


def _safe_get_one(table: str, eq_col: str, eq_val: str) -> Optional[Dict[str, Any]]:
    if not eq_val:
        return None
    rows = _sb_get(f"/{table}?{eq_col}=eq.{eq_val}&limit=1") or []
    return rows[0] if rows else None


def _anthropic_key() -> str:
    return os.environ.get("ANTHROPIC_API_KEY", "")


# ─────────────────────────────────────────────────────────────
# Brand kit shape normalization (transitional both-shapes write)
# ─────────────────────────────────────────────────────────────

def _normalize_brand_kit(kit: Dict[str, Any]) -> Dict[str, Any]:
    """
    Idempotent. Ensures both modern nested keys (colors.primary,
    font_pair.heading, font_pair.body) AND legacy flat keys (primary_color,
    font_heading, font_body) are present so all readers (old + new) resolve
    to the same value. Both shapes coexist transitionally; v2 cleanup
    drops the flat shape after audit confirms no readers remain.
    """
    if not isinstance(kit, dict):
        return kit
    out: Dict[str, Any] = dict(kit)
    colors = out.get("colors") or {}
    font_pair = out.get("font_pair") or {}

    # nested → flat
    if colors.get("primary") and not out.get("primary_color"):
        out["primary_color"] = colors["primary"]
    if font_pair.get("heading") and not out.get("font_heading"):
        out["font_heading"] = font_pair["heading"]
    if font_pair.get("body") and not out.get("font_body"):
        out["font_body"] = font_pair["body"]

    # flat → nested (covers rows where only legacy was written by older code)
    if out.get("primary_color") and not colors.get("primary"):
        out.setdefault("colors", {})["primary"] = out["primary_color"]
    if out.get("font_heading") and not font_pair.get("heading"):
        out.setdefault("font_pair", {})["heading"] = out["font_heading"]
    if out.get("font_body") and not font_pair.get("body"):
        out.setdefault("font_pair", {})["body"] = out["font_body"]

    # Asset registry (Pass 2.5a): mirror assets.primary <-> logo_url so
    # legacy single-logo readers and the new variant-aware bundle stay
    # in lockstep on every save. Idempotent.
    assets = out.get("assets")
    if not isinstance(assets, dict):
        assets = {}
    if out.get("logo_url") and not assets.get("primary"):
        assets["primary"] = out["logo_url"]
    if assets.get("primary") and not out.get("logo_url"):
        out["logo_url"] = assets["primary"]
    out["assets"] = assets

    return out


# ─────────────────────────────────────────────────────────────
# Bundle composition
# ─────────────────────────────────────────────────────────────

def _compose_design(business: Dict[str, Any]) -> Dict[str, Any]:
    brand_kit = (business.get("settings") or {}).get("brand_kit") or {}
    colors = brand_kit.get("colors") or {}
    font_pair = brand_kit.get("font_pair") or {}
    return {
        "primary_color": colors.get("primary") or brand_kit.get("primary_color") or DEFAULT_DESIGN["primary_color"],
        "secondary_color": colors.get("secondary") or DEFAULT_DESIGN["secondary_color"],
        "accent_color": colors.get("accent") or DEFAULT_DESIGN["accent_color"],
        "background_color": colors.get("background") or DEFAULT_DESIGN["background_color"],
        "text_color": colors.get("text") or DEFAULT_DESIGN["text_color"],
        "font_heading": font_pair.get("heading") or brand_kit.get("font_heading") or DEFAULT_DESIGN["font_heading"],
        "font_body": font_pair.get("body") or brand_kit.get("font_body") or DEFAULT_DESIGN["font_body"],
    }


def _compose_voice(
    business: Dict[str, Any],
    profile: Optional[Dict[str, Any]],
    practitioner: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose the bundle's voice section.

    Pass 2.5b additions:
      - Surface `audience` and `tone_original` (already captured but not
        previously exposed in the bundle).
      - Pull practitioner-level voice depth fields (samples, do's/don'ts,
        greeting/sign-off styles) so artifact paths can read them off
        the same canonical bundle.
    """
    voice_profile = business.get("voice_profile") or {}
    canonical_voice = (profile or {}).get("brand_voice") if profile else None
    practitioner = practitioner or {}

    tones_raw = voice_profile.get("communication_style")
    if isinstance(tones_raw, list):
        tones = tones_raw
    elif voice_profile.get("tone"):
        tones = [voice_profile.get("tone")]
    else:
        tones = []

    return {
        "brand_voice": canonical_voice or voice_profile.get("tone") or "warm",
        "tones": tones,
        "personality": voice_profile.get("personality"),
        "communication_style": voice_profile.get("communication_style"),
        # Surfaced (Pass 2.5b)
        "audience": voice_profile.get("audience"),
        "tone_original": voice_profile.get("tone_original"),
        # Voice depth — practitioner-level (Pass 2.5b)
        "voice_samples": practitioner.get("voice_samples") or {},
        "voice_dos": practitioner.get("voice_dos") or [],
        "voice_donts": practitioner.get("voice_donts") or [],
        "greeting_style": practitioner.get("greeting_style"),
        "signoff_style": practitioner.get("signoff_style"),
    }


def _compose_legal(
    profile: Optional[Dict[str, Any]],
    archetype_row: Optional[Dict[str, Any]],
    foundation_complete: bool,
) -> Dict[str, Any]:
    profile = profile or {}
    sensitive_areas = profile.get("sensitive_areas") or {}
    archetype_disclaimers = (archetype_row or {}).get("required_disclaimers") or []
    extra = [v for k, v in EXTRA_DISCLAIMERS_BY_FLAG.items() if sensitive_areas.get(k)]
    seen: List[str] = []
    for d in (list(archetype_disclaimers) + extra):
        if d and d not in seen:
            seen.append(d)
    return {
        "governing_state": profile.get("governing_state"),
        "international_clients": bool(profile.get("international_clients")),
        "produces_deliverables": bool(profile.get("produces_deliverables")),
        "required_disclaimers": seen,
        "in_the_clear": foundation_complete,
    }


def _compose_practitioner(practitioner: Optional[Dict[str, Any]], business: Dict[str, Any]) -> Dict[str, Any]:
    practitioner = practitioner or {}
    settings = business.get("settings") or {}
    full_legal_name = practitioner.get("full_legal_name")
    fallback_name = settings.get("practitioner_name")
    display_name = full_legal_name or fallback_name or "The Practitioner"
    return {
        "owner_id": practitioner.get("owner_id") or business.get("owner_id"),
        "full_legal_name": full_legal_name,
        "preferred_title": practitioner.get("preferred_title"),
        "display_name": display_name,
        "timezone": practitioner.get("timezone"),
        "working_hours_start": practitioner.get("working_hours_start"),
        "working_hours_end": practitioner.get("working_hours_end"),
    }


def _compose_footer(
    business: Dict[str, Any],
    practitioner_section: Dict[str, Any],
    legal_section: Dict[str, Any],
    site_slug: Optional[str],
) -> Dict[str, Any]:
    year = datetime.now(timezone.utc).year
    legal_name = practitioner_section.get("full_legal_name") or business.get("name") or "The Practitioner"
    copyright_line = f"© {year} {legal_name}. All rights reserved."
    disclaimer_lines = [DISCLAIMER_PHRASES[d] for d in legal_section.get("required_disclaimers") or [] if d in DISCLAIMER_PHRASES]
    state_line = f"Governing law: {legal_section['governing_state']}." if legal_section.get("governing_state") else ""
    legal_footer = " ".join(p for p in [state_line] + disclaimer_lines if p)
    site_url = f"https://{site_slug}.mysolutionist.app" if site_slug else None
    contact_email = (business.get("settings") or {}).get("contact_email")
    return {
        "copyright_line": copyright_line,
        "legal_footer": legal_footer,
        "site_url": site_url,
        "contact_email": contact_email,
    }


def _compose_signature(
    practitioner_section: Dict[str, Any],
    business: Dict[str, Any],
    site_slug: Optional[str],
) -> Dict[str, Any]:
    name = practitioner_section.get("full_legal_name") or practitioner_section.get("display_name")
    site_url = f"https://{site_slug}.mysolutionist.app" if site_slug else None
    return {
        "name": name,
        "title": practitioner_section.get("preferred_title"),
        "business_name": business.get("name"),
        "site_url": site_url,
    }


def _compute_completeness(bundle: Dict[str, Any]) -> Tuple[float, List[str]]:
    important = [
        ("business.name", bool(bundle["business"]["name"])),
        ("business.type", bool(bundle["business"]["type"])),
        ("business.slug", bool(bundle["business"]["slug"])),
        ("practitioner.full_legal_name", bool(bundle["practitioner"]["full_legal_name"])),
        ("practitioner.preferred_title", bool(bundle["practitioner"]["preferred_title"])),
        ("practitioner.timezone", bool(bundle["practitioner"]["timezone"])),
        ("voice.brand_voice", bool(bundle["voice"]["brand_voice"])),
        ("design.primary_color", bundle["design"]["primary_color"] != DEFAULT_DESIGN["primary_color"]),
        ("legal.governing_state", bool(bundle["legal"]["governing_state"])),
    ]
    filled = sum(1 for _, v in important if v)
    missing = [name for name, v in important if not v]
    return round(filled / len(important), 2), missing


def _empty_bundle(business_id: str) -> Dict[str, Any]:
    design = dict(DEFAULT_DESIGN)
    design.update({"vibe_family": "warm", "tone_words": [], "visual_style": None})
    return {
        "business": {"id": business_id, "name": "Unknown", "type": "custom",
                     "subtype": None, "slug": None, "tagline": None,
                     "elevator_pitch": None, "logo_url": None},
        "practitioner": {"owner_id": None, "full_legal_name": None,
                         "preferred_title": None, "display_name": "The Practitioner",
                         "timezone": None, "working_hours_start": None,
                         "working_hours_end": None},
        "voice": {"brand_voice": "warm", "tones": [], "personality": None,
                  "communication_style": None},
        "design": design,
        "legal": {"governing_state": None, "international_clients": False,
                  "produces_deliverables": False, "required_disclaimers": [],
                  "in_the_clear": False},
        "footer": {"copyright_line": "", "legal_footer": "", "site_url": None,
                   "contact_email": None},
        "signature_block": {"name": "The Practitioner", "title": None,
                            "business_name": "Unknown", "site_url": None},
        "assets": {"primary": None, "logo_light": None, "logo_dark": None,
                   "square": None, "favicon": None, "social_card": None},
        "snapshot_count": 0,
        "meta": {"completeness": 0.0, "missing_fields": ["business.id"],
                 "has_brand_kit": False},
    }


def get_bundle(business_id: str) -> Dict[str, Any]:
    """Compose the canonical brand bundle. Single source of truth for every
    downstream artifact (email, invoice, PDF, public site, Stripe page)."""
    if not business_id:
        return _empty_bundle("")

    business = _safe_get_one("businesses", "id", business_id)
    if not business or not business.get("id"):
        return _empty_bundle(business_id)

    profile = _safe_get_one("business_profiles", "business_id", business_id) or {}
    archetype_row = None
    if profile.get("business_type"):
        archetype_row = _safe_get_one(
            "business_type_archetypes", "business_type", profile["business_type"]
        )

    practitioner = None
    if business.get("owner_id"):
        practitioner = _safe_get_one("practitioner_profiles", "owner_id", business["owner_id"])

    site = _safe_get_one("business_sites", "business_id", business_id) or {}
    site_slug = site.get("slug")

    foundation_complete = bool(business.get("in_the_clear"))

    settings = business.get("settings") or {}
    brand_kit = settings.get("brand_kit") or {}

    business_section = {
        "id": business.get("id"),
        "name": business.get("name"),
        "type": profile.get("business_type") or business.get("type"),
        "subtype": profile.get("business_subtype"),
        "slug": site_slug,
        "tagline": brand_kit.get("tagline"),
        "elevator_pitch": brand_kit.get("elevator_pitch"),
        "logo_url": brand_kit.get("logo_url"),
    }
    practitioner_section = _compose_practitioner(practitioner, business)
    voice_section = _compose_voice(business, profile, practitioner)
    design_section = _compose_design(business)
    design_section["vibe_family"] = VIBE_FAMILY_MAP.get(voice_section["brand_voice"], "warm")
    design_section["tone_words"] = brand_kit.get("tone_words") or []
    design_section["visual_style"] = brand_kit.get("visual_style")
    legal_section = _compose_legal(profile, archetype_row, foundation_complete)
    footer_section = _compose_footer(business, practitioner_section, legal_section, site_slug)
    signature_section = _compose_signature(practitioner_section, business, site_slug)

    # Asset registry (Pass 2.5a). Six variants. Missing variants fall
    # back to primary; primary falls back to legacy logo_url; both fall
    # back to None. Smart Sites (Pass 3) and downstream rendering pick
    # the right variant per surface.
    assets_raw = brand_kit.get("assets") or {}
    primary_logo = assets_raw.get("primary") or brand_kit.get("logo_url")
    assets_section = {
        "primary": primary_logo,
        "logo_light": assets_raw.get("logo_light") or primary_logo,
        "logo_dark": assets_raw.get("logo_dark") or primary_logo,
        "square": assets_raw.get("square") or primary_logo,
        "favicon": assets_raw.get("favicon"),
        "social_card": assets_raw.get("social_card"),
    }

    bundle = {
        "business": business_section,
        "practitioner": practitioner_section,
        "voice": voice_section,
        "design": design_section,
        "legal": legal_section,
        "footer": footer_section,
        "signature_block": signature_section,
        "assets": assets_section,
        "snapshot_count": len(business.get("brand_kit_history") or []),
    }
    completeness, missing = _compute_completeness(bundle)
    bundle["meta"] = {
        "completeness": completeness,
        "missing_fields": missing,
        "has_brand_kit": bool(brand_kit),
    }
    return bundle


# ─────────────────────────────────────────────────────────────
# Save path with snapshot history (cap 2)
# ─────────────────────────────────────────────────────────────

def save_brand_kit(business_id: str, new_kit: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical save. Pushes current kit to history (cap 2). Normalizes
    both nested and flat shapes. Updates settings.brand_kit AND
    brand_kit_history in one PATCH."""
    business = _safe_get_one("businesses", "id", business_id)
    if not business:
        return _empty_bundle(business_id)

    current_kit = (business.get("settings") or {}).get("brand_kit")
    history = list(business.get("brand_kit_history") or [])

    if current_kit:
        history.insert(0, {
            "kit": current_kit,
            "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        })
        history = history[:2]  # hard cap

    normalized = _normalize_brand_kit(new_kit or {})
    new_settings = dict(business.get("settings") or {})
    new_settings["brand_kit"] = normalized

    _sb_patch(
        f"/businesses?id=eq.{business_id}",
        {
            "settings": new_settings,
            "brand_kit_history": history,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    return get_bundle(business_id)


def restore_snapshot(business_id: str, snapshot_idx: int = 0) -> Dict[str, Any]:
    """Restore a previous snapshot. snapshot_idx 0 = most recent prior version.
    The current state is pushed to history first via save_brand_kit, so the
    user can always re-restore what they had before clicking Restore."""
    business = _safe_get_one("businesses", "id", business_id)
    if not business:
        return _empty_bundle(business_id)
    history = list(business.get("brand_kit_history") or [])
    if snapshot_idx < 0 or snapshot_idx >= len(history):
        return get_bundle(business_id)
    target_kit = (history[snapshot_idx] or {}).get("kit")
    if not target_kit:
        return get_bundle(business_id)
    return save_brand_kit(business_id, target_kit)


# ─────────────────────────────────────────────────────────────
# Generation paths (Claude-backed; do NOT save — frontend confirms)
# ─────────────────────────────────────────────────────────────

_GEN_SYSTEM_PROMPT = """You are a brand designer producing a complete starter brand kit for a practitioner.
Output ONLY valid JSON matching this exact schema, no other text:
{
  "tagline": "punchy one-line tagline (max 8 words)",
  "elevator_pitch": "2-3 sentence elevator pitch in the practitioner's voice",
  "colors": {
    "primary": "#hex",
    "secondary": "#hex",
    "accent": "#hex",
    "background": "#hex",
    "text": "#hex"
  },
  "font_pair": {
    "heading": "Google Font name",
    "body": "Google Font name"
  },
  "tone_words": ["adjective1", "adjective2", "adjective3", "adjective4", "adjective5"],
  "visual_style": "one sentence describing the visual aesthetic"
}

Rules:
- Use 5 colors total. Primary should be the brand-defining color. Background is light/neutral.
- Choose Google Fonts that pair well. Heading often serif or distinctive; body often sans-serif and readable.
- Tone words match the practitioner's brand voice and archetype.
- If archetype is financial_educator, the kit should look authoritative and trustworthy.
- If archetype is coach, the kit should feel warm and aspirational.
- If archetype is creative, the kit should feel bold and modern.
- If archetype is fitness_wellness, the kit should feel energetic and grounded.
- If brand_voice is ministry, the kit should feel sacred but warm.
- Match the practitioner's existing voice — don't invent a personality they didn't describe."""


def _strip_code_fences(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        # remove first fence (with optional language tag) and trailing fence
        parts = text.split("```", 2)
        if len(parts) >= 2:
            text = parts[1]
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
            if text.endswith("```"):
                text = text[:-3].strip()
    return text


def _call_claude_for_kit(system_prompt: str, user_message: str) -> Dict[str, Any]:
    api_key = _anthropic_key()
    if not api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not configured"}
    try:
        with httpx.Client(timeout=60.0) as client:
            r = client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": ANTHROPIC_MODEL,
                    "max_tokens": 2000,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}],
                },
            )
        if r.status_code != 200:
            logger.warning(f"Anthropic error {r.status_code}: {r.text[:200]}")
            return {"ok": False, "error": f"Anthropic API error: {r.status_code}"}
        body = r.json()
        text_chunks = [c.get("text", "") for c in body.get("content", []) if c.get("type") == "text"]
        text = _strip_code_fences("".join(text_chunks))
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                parsed = json.loads(text[start : end + 1])
            else:
                return {"ok": False, "error": "Could not parse JSON from model"}
        return {"ok": True, "kit": parsed}
    except Exception as e:
        logger.warning(f"_call_claude_for_kit failed: {e}")
        return {"ok": False, "error": str(e)}


def generate_from_context(business_id: str) -> Dict[str, Any]:
    """Rich generation using FULL context: business name, archetype,
    voice_profile, brand_voice, Strategy Track outputs, Practitioner Profile.
    Returns a brand kit dict (not yet saved). Frontend confirms then calls save."""
    business = _safe_get_one("businesses", "id", business_id) or {}
    if not business or not business.get("id"):
        return {"ok": False, "error": "Business not found"}

    profile = _safe_get_one("business_profiles", "business_id", business_id) or {}
    archetype = _safe_get_one(
        "business_type_archetypes",
        "business_type",
        profile.get("business_type") or "custom",
    ) or {}

    strategy = None
    rows = _sb_get(
        f"/strategy_tracks?business_id=eq.{business_id}&order=created_at.desc&limit=1"
    ) or []
    if rows:
        strategy = rows[0]

    voice_profile = business.get("voice_profile") or {}

    parts: List[str] = [
        f"Business name: {business.get('name')}",
        f"Archetype: {profile.get('business_type') or 'custom'} ({archetype.get('display_name', '')})",
        f"Subtype: {profile.get('business_subtype') or 'not specified'}",
        f"Brand voice: {profile.get('brand_voice') or voice_profile.get('tone') or 'warm'}",
    ]
    if voice_profile.get("personality"):
        parts.append(f"Personality: {voice_profile['personality']}")
    if voice_profile.get("audience"):
        parts.append(f"Target audience: {voice_profile['audience']}")
    if strategy and isinstance(strategy.get("phases"), dict):
        disc = (strategy.get("phases") or {}).get("discovery") or {}
        if disc.get("unique_value_proposition"):
            parts.append(f"Unique value: {disc['unique_value_proposition']}")
        if disc.get("target_audience"):
            parts.append(f"Audience detail: {disc['target_audience']}")

    user_message = "Generate a brand kit for:\n\n" + "\n".join(parts)
    return _call_claude_for_kit(_GEN_SYSTEM_PROMPT, user_message)


_LEARN_SYSTEM_PROMPT = """Analyze the HTML and extract a brand kit. Output ONLY valid JSON:
{
  "tagline": "...",
  "elevator_pitch": "...",
  "colors": {"primary": "#hex", "secondary": "#hex", "accent": "#hex", "background": "#hex", "text": "#hex"},
  "font_pair": {"heading": "...", "body": "..."},
  "tone_words": ["...", "..."],
  "visual_style": "..."
}
- Extract hex colors from CSS, inline styles, theme-color meta, brand-related vars
- Identify fonts from @import, link rel=stylesheet href containing fonts.googleapis.com, font-family declarations
- Tagline from <meta property="og:title">, <h1>, or page title
- Elevator pitch from <meta name="description"> or <meta property="og:description">
- Tone words inferred from the site's overall language
- Visual style: one sentence describing what the site looks like"""


def learn_from_url(business_id: str, url: str) -> Dict[str, Any]:
    """Fetches the URL HTML server-side and asks Claude to extract a brand kit
    proposal. Returns the kit (not yet saved). Frontend confirms then calls save."""
    if not url or not url.startswith(("http://", "https://")):
        return {"ok": False, "error": "Invalid URL"}
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            page = client.get(url)
        if page.status_code != 200:
            return {"ok": False, "error": f"Could not fetch URL: {page.status_code}"}
        html_snippet = page.text[:8000]
    except Exception as e:
        return {"ok": False, "error": f"Fetch failed: {e}"}

    user_message = f"URL: {url}\n\nHTML:\n{html_snippet}"
    result = _call_claude_for_kit(_LEARN_SYSTEM_PROMPT, user_message)
    if result.get("ok"):
        result["source_url"] = url
    return result


# ─────────────────────────────────────────────────────────────
# Chief context block
# ─────────────────────────────────────────────────────────────

def chief_context_block(business_id: str) -> str:
    """Markdown block injected into the Chief system prompt between the
    practitioner block and the business profile block. Returns empty
    string when there's effectively nothing to say."""
    if not business_id:
        return ""
    try:
        bundle = get_bundle(business_id)
    except Exception as e:
        logger.warning(f"chief_context_block failed: {e}")
        return ""

    has_kit = bundle.get("meta", {}).get("has_brand_kit")
    completeness = float(bundle.get("meta", {}).get("completeness") or 0)
    if not has_kit and completeness == 0.0:
        return ""

    lines: List[str] = ["## Brand Bundle (used by all output paths)"]
    if not has_kit:
        lines.append("  Brand kit: NOT YET CONFIGURED. Suggest the user generate one (Generate / Learn from URL / Customize Manually).")
    voice = bundle.get("voice") or {}
    design = bundle.get("design") or {}
    legal = bundle.get("legal") or {}
    practitioner = bundle.get("practitioner") or {}

    lines.append(f"  Brand voice: {voice.get('brand_voice') or 'warm'}")
    lines.append(f"  Vibe family: {design.get('vibe_family') or 'warm'}")
    tone_words = design.get("tone_words") or []
    if tone_words:
        lines.append(f"  Tone words: {', '.join(tone_words[:5])}")
    # Pass 2.5b: surface previously-captured-but-hidden fields
    if voice.get("personality"):
        lines.append(f"  Personality: {voice['personality']}")
    if voice.get("audience"):
        lines.append(f"  Audience: {voice['audience']}")
    lines.append(f"  Practitioner display name: {practitioner.get('display_name') or 'The Practitioner'}")
    if practitioner.get("preferred_title"):
        lines.append(f"  Title: {practitioner['preferred_title']}")
    if legal.get("governing_state"):
        lines.append(f"  Governing state: {legal['governing_state']}")
    if legal.get("required_disclaimers"):
        lines.append("  Required disclaimers: " + ", ".join(legal["required_disclaimers"]))
    if legal.get("in_the_clear"):
        lines.append("  Foundation: COMPLETE (eligible for In The Clear badge)")
    lines.append(f"  Bundle completeness: {int(round(completeness * 100))}%")
    snap_count = bundle.get("snapshot_count") or 0
    if snap_count:
        lines.append(f"  Brand history snapshots available: {snap_count}")

    # Asset coverage (Pass 2.5a)
    assets = bundle.get("assets") or {}
    if assets:
        configured = sum(1 for v in assets.values() if v)
        total_variants = len(assets)
        if configured == total_variants:
            lines.append(f"  Brand assets: all {total_variants} variants configured")
        elif configured > 0:
            missing_variants = [k for k, v in assets.items() if not v]
            lines.append(
                f"  Brand assets: {configured}/{total_variants} variants set. "
                f"Missing: {', '.join(missing_variants)}"
            )
        else:
            lines.append("  Brand assets: NONE configured. Suggest uploading a primary logo first.")

    lines.append(
        "When drafting any client-facing output (email, invoice, contract, page), "
        "prefer the bundle for signature, footer, colors, and required disclaimers. "
        "If the user asks 'what does the system know about my brand', summarize this section."
    )
    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────
# Asset registry (Pass 2.5a)
# ─────────────────────────────────────────────────────────────

ASSET_VARIANTS: Dict[str, Dict[str, Any]] = {
    "primary":     {"max_size_mb": 5, "preferred_format": "png"},
    "logo_light":  {"max_size_mb": 5, "preferred_format": "png"},
    "logo_dark":   {"max_size_mb": 5, "preferred_format": "png"},
    "square":      {"max_size_mb": 5, "preferred_format": "png"},
    "favicon":     {"max_size_mb": 1, "preferred_format": "png"},
    "social_card": {"max_size_mb": 5, "preferred_format": "png"},
}

_ALLOWED_ASSET_EXTS = {"png", "jpg", "jpeg", "svg", "webp", "gif", "ico"}
_STORAGE_BUCKET = "business-assets"


def _storage_upload(storage_path: str, file_bytes: bytes, content_type: str) -> Optional[str]:
    """POST raw bytes to Supabase Storage REST. Returns the public URL on
    success, None on failure. Uses the same anon key the rest of the
    codebase uses; the bucket's RLS policy must allow uploads (existing
    permissive policy on business-assets does)."""
    base = _sb_url()
    if not base:
        logger.warning("storage_upload: SUPABASE_URL not configured")
        return None
    url = f"{base}/storage/v1/object/{_STORAGE_BUCKET}/{storage_path}"
    headers = {
        "apikey": _sb_anon(),
        "Authorization": f"Bearer {_sb_anon()}",
        "Content-Type": content_type or "application/octet-stream",
        # `x-upsert: true` lets re-uploading the same path replace the object.
        "x-upsert": "true",
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.post(url, content=file_bytes, headers=headers)
        if r.status_code >= 400:
            logger.warning(f"storage upload {storage_path}: {r.status_code} {r.text[:200]}")
            return None
    except httpx.HTTPError as e:
        logger.warning(f"storage upload {storage_path} failed: {e}")
        return None
    # Public URL — bucket has public read RLS already in place.
    return f"{base}/storage/v1/object/public/{_STORAGE_BUCKET}/{storage_path}"


def upload_asset(
    business_id: str,
    variant: str,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> Dict[str, Any]:
    """Upload an asset to Supabase Storage and update brand_kit.assets[variant].
    Returns {ok, url?, variant?, error?}."""
    if not business_id:
        return {"ok": False, "error": "business_id required"}
    if variant not in ASSET_VARIANTS:
        return {"ok": False, "error": f"Unknown variant: {variant}"}

    max_size = ASSET_VARIANTS[variant]["max_size_mb"] * 1024 * 1024
    if len(file_bytes) > max_size:
        return {
            "ok": False,
            "error": f"File exceeds {ASSET_VARIANTS[variant]['max_size_mb']}MB limit",
        }

    if not (content_type or "").startswith("image/"):
        return {"ok": False, "error": f"Content type must be an image, got {content_type}"}

    ext = (filename.rsplit(".", 1)[-1] if "." in (filename or "") else "png").lower()
    if ext not in _ALLOWED_ASSET_EXTS:
        return {"ok": False, "error": f"Unsupported file extension: {ext}"}

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    storage_path = f"brand/{business_id}/{variant}-{timestamp}.{ext}"

    public_url = _storage_upload(storage_path, file_bytes, content_type)
    if not public_url:
        return {"ok": False, "error": "Storage upload failed"}

    # Update brand_kit.assets[variant] in the businesses row.
    business = _safe_get_one("businesses", "id", business_id)
    if not business:
        return {"ok": False, "error": "Business not found"}

    settings = dict(business.get("settings") or {})
    brand_kit = dict(settings.get("brand_kit") or {})
    assets = dict(brand_kit.get("assets") or {})
    assets[variant] = public_url
    brand_kit["assets"] = assets
    if variant == "primary":
        # Mirror to legacy logo_url so existing readers (MediaLibrary,
        # OnboardingChecklist, etc.) keep resolving.
        brand_kit["logo_url"] = public_url
    settings["brand_kit"] = brand_kit

    res = _sb_patch(
        f"/businesses?id=eq.{business_id}",
        {"settings": settings, "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    if res is None:
        return {"ok": False, "error": "Database update failed"}

    return {"ok": True, "url": public_url, "variant": variant}


def remove_asset(business_id: str, variant: str) -> Dict[str, Any]:
    """Clear a variant from the asset registry. Does NOT delete the
    underlying storage object — storage cleanup is a v2 lifecycle job
    so reverts can re-link the previous URL if needed."""
    if not business_id:
        return {"ok": False, "error": "business_id required"}
    if variant not in ASSET_VARIANTS:
        return {"ok": False, "error": f"Unknown variant: {variant}"}

    business = _safe_get_one("businesses", "id", business_id)
    if not business:
        return {"ok": False, "error": "Business not found"}

    settings = dict(business.get("settings") or {})
    brand_kit = dict(settings.get("brand_kit") or {})
    assets = dict(brand_kit.get("assets") or {})

    if variant in assets:
        del assets[variant]
    brand_kit["assets"] = assets

    if variant == "primary":
        # Removing primary also clears legacy logo_url; the asset_section
        # composer will fall back through to None.
        brand_kit.pop("logo_url", None)

    settings["brand_kit"] = brand_kit

    res = _sb_patch(
        f"/businesses?id=eq.{business_id}",
        {"settings": settings, "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    if res is None:
        return {"ok": False, "error": "Database update failed"}

    return {"ok": True, "variant": variant}
