"""
voice_depth_agent.py — Pass 2.5b: Brand Voice Depth.

Practitioner-level voice capture: writing samples, do's/don'ts,
greeting/sign-off styles, and a passive edit-observation loop that
the Chief uses to propose voice rules with explicit user confirmation.

Mirrors the httpx + Supabase REST helper pattern used by
business_profile_agent / practitioner_profile_agent / brand_engine.
No supabase-py dependency.

Public API:
  get_voice_depth(owner_id) -> dict | None
  update_voice_sample(owner_id, slot, sample_text) -> dict
  update_voice_style(owner_id, field, value) -> dict
  add_voice_rule(owner_id, list_name, rule) -> dict
  remove_voice_rule(owner_id, list_name, idx) -> dict
  record_edit_observation(owner_id, original, edited, context, kind) -> dict
  get_observations_for_proposal(owner_id) -> list[dict]
  clear_observations_after_rule(owner_id) -> dict
  get_missing_voice_jit_fields(owner_id) -> list[str]
  get_voice_phrasing(field_path, brand_voice) -> str
  chief_voice_context_block(owner_id) -> str        # rich, for outer Chief
  voice_depth_payload_for_inner_call(owner_id) -> str  # compact, for _draft_short
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger("voice_depth_agent")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] voice_depth: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


HTTP_TIMEOUT = 15.0

# ─────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────

VOICE_SAMPLE_SLOTS = ("discovery_followup", "launch_announcement", "casual_nurture")
EDIT_OBSERVATION_THRESHOLD = 3  # observations needed before Chief proposes a rule
MAX_OBSERVATIONS = 50           # cap stored edit observations

_VALID_VOICE_FIELDS = {"greeting_style", "signoff_style"}
_VALID_RULE_LISTS = {"voice_dos", "voice_donts"}
_VALID_OBS_KINDS = {"do", "dont"}
_VALID_BRAND_VOICES = {"warm", "formal", "casual", "ministry", "corporate", "direct"}


# ─────────────────────────────────────────────────────────────
# Supabase REST helpers (mirrors business_profile_agent / brand_engine)
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


def _sb_post(path: str, body: Any) -> Optional[Any]:
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as client:
            r = client.post(
                f"{_sb_url()}/rest/v1{path}",
                headers=_sb_headers(),
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_exists(owner_id: str) -> bool:
    rows = _sb_get(f"/practitioner_profiles?owner_id=eq.{owner_id}&select=owner_id&limit=1") or []
    return len(rows) > 0


def _ensure_row(owner_id: str) -> bool:
    """Create a minimal practitioner_profiles row if one doesn't exist."""
    if _row_exists(owner_id):
        return True
    res = _sb_post("/practitioner_profiles", {"owner_id": owner_id})
    return res is not None


# ─────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────

def get_voice_depth(owner_id: str) -> Optional[Dict[str, Any]]:
    """Return the voice depth slice of a practitioner_profiles row.
    None when no row exists."""
    if not owner_id:
        return None
    cols = (
        "owner_id,voice_samples,voice_dos,voice_donts,"
        "greeting_style,signoff_style,edit_observations"
    )
    rows = _sb_get(
        f"/practitioner_profiles?owner_id=eq.{owner_id}&select={cols}&limit=1"
    ) or []
    if not rows:
        return None
    row = rows[0]
    # Defensive defaults in case columns are missing on stale rows
    row.setdefault("voice_samples", {})
    row.setdefault("voice_dos", [])
    row.setdefault("voice_donts", [])
    row.setdefault("edit_observations", [])
    return row


# ─────────────────────────────────────────────────────────────
# Writes
# ─────────────────────────────────────────────────────────────

def update_voice_sample(owner_id: str, slot: str, sample_text: str) -> Dict[str, Any]:
    if not owner_id:
        return {"ok": False, "error": "owner_id required"}
    if slot not in VOICE_SAMPLE_SLOTS:
        return {"ok": False, "error": f"Unknown slot: {slot}"}
    sample_text = (sample_text or "").strip()
    if not sample_text:
        return {"ok": False, "error": "Empty sample"}

    if not _ensure_row(owner_id):
        return {"ok": False, "error": "Could not create practitioner_profiles row"}

    current = get_voice_depth(owner_id) or {}
    samples = dict(current.get("voice_samples") or {})
    samples[slot] = sample_text

    res = _sb_patch(
        f"/practitioner_profiles?owner_id=eq.{owner_id}",
        {"voice_samples": samples, "updated_at": _now_iso()},
    )
    if res is None:
        return {"ok": False, "error": "Database update failed"}
    return {"ok": True, "slot": slot}


def update_voice_style(owner_id: str, field: str, value: str) -> Dict[str, Any]:
    if not owner_id:
        return {"ok": False, "error": "owner_id required"}
    if field not in _VALID_VOICE_FIELDS:
        return {"ok": False, "error": f"Unknown field: {field}"}
    value = (value or "").strip()
    if not value:
        return {"ok": False, "error": "Empty value"}

    if not _ensure_row(owner_id):
        return {"ok": False, "error": "Could not create practitioner_profiles row"}

    res = _sb_patch(
        f"/practitioner_profiles?owner_id=eq.{owner_id}",
        {field: value, "updated_at": _now_iso()},
    )
    if res is None:
        return {"ok": False, "error": "Database update failed"}
    return {"ok": True, "field": field}


def add_voice_rule(owner_id: str, list_name: str, rule: str) -> Dict[str, Any]:
    if not owner_id:
        return {"ok": False, "error": "owner_id required"}
    if list_name not in _VALID_RULE_LISTS:
        return {"ok": False, "error": f"Unknown list: {list_name}"}
    rule = (rule or "").strip()
    if not rule:
        return {"ok": False, "error": "Empty rule"}

    if not _ensure_row(owner_id):
        return {"ok": False, "error": "Could not create practitioner_profiles row"}

    current = get_voice_depth(owner_id) or {}
    existing = list(current.get(list_name) or [])
    if rule in existing:
        return {"ok": True, "duplicate": True, "list": list_name, "count": len(existing)}
    existing.append(rule)

    res = _sb_patch(
        f"/practitioner_profiles?owner_id=eq.{owner_id}",
        {list_name: existing, "updated_at": _now_iso()},
    )
    if res is None:
        return {"ok": False, "error": "Database update failed"}
    return {"ok": True, "list": list_name, "count": len(existing)}


def remove_voice_rule(owner_id: str, list_name: str, idx: int) -> Dict[str, Any]:
    if not owner_id:
        return {"ok": False, "error": "owner_id required"}
    if list_name not in _VALID_RULE_LISTS:
        return {"ok": False, "error": f"Unknown list: {list_name}"}

    current = get_voice_depth(owner_id) or {}
    existing = list(current.get(list_name) or [])
    if idx is None or idx < 0 or idx >= len(existing):
        return {"ok": False, "error": "Index out of range"}

    removed = existing.pop(idx)
    res = _sb_patch(
        f"/practitioner_profiles?owner_id=eq.{owner_id}",
        {list_name: existing, "updated_at": _now_iso()},
    )
    if res is None:
        return {"ok": False, "error": "Database update failed"}
    return {"ok": True, "removed": removed, "remaining": len(existing)}


def record_edit_observation(
    owner_id: str,
    original_pattern: str,
    edited_pattern: str,
    context: str,
    kind: str,
) -> Dict[str, Any]:
    """Silent passive observation. Caps at MAX_OBSERVATIONS (oldest rotate out)."""
    if not owner_id:
        return {"ok": False, "error": "owner_id required"}
    if kind not in _VALID_OBS_KINDS:
        kind = "dont"

    if not _ensure_row(owner_id):
        return {"ok": False, "error": "Could not create practitioner_profiles row"}

    current = get_voice_depth(owner_id) or {}
    obs = list(current.get("edit_observations") or [])
    obs.append({
        "observed_at": _now_iso(),
        "original_pattern": (original_pattern or "")[:500],
        "edited_pattern": (edited_pattern or "")[:500],
        "context": (context or "")[:200],
        "kind": kind,
    })
    obs = obs[-MAX_OBSERVATIONS:]

    res = _sb_patch(
        f"/practitioner_profiles?owner_id=eq.{owner_id}",
        {"edit_observations": obs, "updated_at": _now_iso()},
    )
    if res is None:
        return {"ok": False, "error": "Database update failed"}
    return {"ok": True, "count": len(obs)}


def get_observations_for_proposal(owner_id: str) -> List[Dict[str, Any]]:
    """Returns observations only when threshold is met. Empty otherwise.
    The Chief itself proposes a rule from these in the next conversation
    turn — we don't NLP-cluster server-side in v1."""
    current = get_voice_depth(owner_id) or {}
    obs = current.get("edit_observations") or []
    return obs if len(obs) >= EDIT_OBSERVATION_THRESHOLD else []


def clear_observations_after_rule(owner_id: str) -> Dict[str, Any]:
    """Clear observations after the user accepts a proposed rule, so Chief
    doesn't re-propose the same pattern."""
    if not _row_exists(owner_id):
        return {"ok": True, "skipped": True}
    res = _sb_patch(
        f"/practitioner_profiles?owner_id=eq.{owner_id}",
        {"edit_observations": [], "updated_at": _now_iso()},
    )
    if res is None:
        return {"ok": False, "error": "Database update failed"}
    return {"ok": True}


# ─────────────────────────────────────────────────────────────
# JIT (just-in-time capture) — voice namespace
# ─────────────────────────────────────────────────────────────

VOICE_PHRASING: Dict[str, Dict[str, str]] = {
    "voice_samples.discovery_followup": {
        "warm":      "Quick thing — I don't have a sample of how you'd write a discovery follow-up. Could you paste a recent one (or jot a quick example)? It'll help me draft these in your real voice.",
        "formal":    "I lack a sample of your discovery follow-up writing. Please provide a recent example so I can match your voice accurately.",
        "casual":    "Hey, do you have a discovery follow-up I could see? I want to match your style.",
        "ministry":  "Quick check — do you have a recent discovery follow-up email I could see? I want my drafts to honor your voice.",
        "corporate": "Sample needed: discovery follow-up email. Please provide for voice matching.",
        "direct":    "Need a sample of your discovery follow-up writing. Paste one.",
    },
    "voice_samples.launch_announcement": {
        "warm":      "Before I draft this, could you share a sample of how you'd announce something — a launch, a new offering, a campaign? I want to write it in YOUR voice, not mine.",
        "formal":    "A sample announcement — launch, offering, or campaign — would help me match your voice. Please provide one.",
        "casual":    "Got a sample announcement I could see? Launch, offering, anything. Want to match your style.",
        "ministry":  "Could you share an example of how you'd announce something to your community? I want to honor your voice.",
        "corporate": "Sample needed: launch / announcement email. Please provide for voice matching.",
        "direct":    "Need a sample announcement. Paste one.",
    },
    "voice_samples.casual_nurture": {
        "warm":      "Quick one — do you have an example of how you'd casually check in with someone? A short note, no agenda. I want to match your tone there.",
        "formal":    "A sample of your casual check-in style would help me match your voice. Please provide one.",
        "casual":    "Got a casual check-in I could see? Just a friendly note. Want to match your style.",
        "ministry":  "Could you share an example of a casual check-in you'd send? Want to honor your voice.",
        "corporate": "Sample needed: casual check-in / nurture. Please provide for voice matching.",
        "direct":    "Need a casual check-in sample. Paste one.",
    },
    "greeting_style": {
        "warm":      "Quick one — how do you usually open emails? 'Hey friend', 'Hi [Name]', something else?",
        "formal":    "What is your preferred email greeting?",
        "casual":    "How do you start emails? Want to match your style.",
        "ministry":  "What greeting do you prefer for ministry emails?",
        "corporate": "Standard email greeting?",
        "direct":    "Email greeting?",
    },
    "signoff_style": {
        "warm":      "And how do you usually sign off? 'Talk soon', 'Shalom', 'Take care', something with your name?",
        "formal":    "Preferred email sign-off?",
        "casual":    "How do you sign off?",
        "ministry":  "Preferred ministry sign-off?",
        "corporate": "Standard email sign-off?",
        "direct":    "Email sign-off?",
    },
}

JIT_VOICE_FIELDS: List[str] = list(VOICE_PHRASING.keys())


def get_voice_phrasing(field_path: str, brand_voice: Optional[str]) -> str:
    voice = (brand_voice or "warm").lower()
    if voice not in _VALID_BRAND_VOICES:
        voice = "warm"
    field_map = VOICE_PHRASING.get(field_path) or {}
    return field_map.get(voice) or field_map.get("warm") or ""


def get_missing_voice_jit_fields(owner_id: str) -> List[str]:
    """Return the JIT_VOICE_FIELDS the practitioner hasn't filled yet."""
    if not owner_id:
        return list(JIT_VOICE_FIELDS)
    voice = get_voice_depth(owner_id) or {}
    samples = voice.get("voice_samples") or {}
    missing: List[str] = []
    for field_path in JIT_VOICE_FIELDS:
        if "." in field_path:
            parent, child = field_path.split(".", 1)
            if parent == "voice_samples":
                if not samples.get(child):
                    missing.append(field_path)
            else:
                # Defensive — no other parents in v1
                if not (voice.get(parent) or {}).get(child):
                    missing.append(field_path)
        else:
            if not voice.get(field_path):
                missing.append(field_path)
    return missing


# ─────────────────────────────────────────────────────────────
# Context blocks (outer rich + inner compact)
# ─────────────────────────────────────────────────────────────

def chief_voice_context_block(owner_id: str) -> str:
    """Rich voice context for the OUTER Chief system prompt. Includes
    pending observations + rule-proposal instruction when threshold met.
    Returns "" when nothing useful to surface."""
    if not owner_id:
        return ""

    try:
        voice = get_voice_depth(owner_id)
    except Exception as e:
        logger.warning(f"chief_voice_context_block fetch failed: {e}")
        return ""

    if not voice:
        return ""

    samples = voice.get("voice_samples") or {}
    dos = voice.get("voice_dos") or []
    donts = voice.get("voice_donts") or []
    greeting = voice.get("greeting_style")
    signoff = voice.get("signoff_style")
    obs = voice.get("edit_observations") or []

    has_any_sample = any(samples.get(s) for s in VOICE_SAMPLE_SLOTS)
    has_any_data = (
        has_any_sample or dos or donts or greeting or signoff
        or len(obs) >= EDIT_OBSERVATION_THRESHOLD
    )
    if not has_any_data:
        return ""

    lines: List[str] = []

    if has_any_sample:
        lines.append("VOICE SAMPLES (the practitioner's actual writing — match this voice exactly when drafting):")
        for slot in VOICE_SAMPLE_SLOTS:
            text = samples.get(slot)
            if text:
                pretty = slot.replace("_", " ").title()
                if len(text) > 1500:
                    text = text[:1500] + "...[truncated]"
                lines.append(f"  --- {pretty} ---")
                lines.append(f"  {text}")
                lines.append("")

    if dos:
        lines.append("VOICE DO'S (always follow when drafting):")
        for rule in dos:
            lines.append(f"  - {rule}")
        lines.append("")

    if donts:
        lines.append("VOICE DON'TS (never violate when drafting):")
        for rule in donts:
            lines.append(f"  - {rule}")
        lines.append("")

    if greeting:
        lines.append(f"GREETING STYLE: {greeting}")
    if signoff:
        lines.append(f"SIGN-OFF STYLE: {signoff}")

    # Pending edit observations (rule proposal pathway)
    if len(obs) >= EDIT_OBSERVATION_THRESHOLD:
        lines.append("")
        lines.append(f"PENDING VOICE OBSERVATIONS ({len(obs)} edits observed):")
        lines.append("The user has been editing your drafts in patterns. Sample edits:")
        for o in obs[-5:]:
            orig = (o.get("original_pattern") or "")[:100]
            edited = (o.get("edited_pattern") or "")[:100]
            ctx = o.get("context") or "?"
            lines.append(f"  Was: \"{orig}\"")
            lines.append(f"  Became: \"{edited}\" (context: {ctx})")
        lines.append(
            "If a clear pattern emerges (e.g., consistent removal/addition of a phrase, "
            "exclamation points, formality), propose a voice rule by emitting:"
        )
        lines.append(
            '[ACTION:{"type":"propose_voice_rule","list":"voice_dos","rule":"<plain-language rule>"}]'
        )
        lines.append(
            'or [ACTION:{"type":"propose_voice_rule","list":"voice_donts","rule":"<plain-language rule>"}].'
        )
        lines.append(
            "Only propose if confident. Wait for user to accept (frontend confirms) "
            "before the rule is stored."
        )

    return "\n".join(lines) + "\n"


def voice_depth_payload_for_inner_call(owner_id: str) -> str:
    """COMPACT voice payload for the inner _draft_short Claude call.

    Smaller than chief_voice_context_block: no pending observations, no
    proposal instructions — just the rules and styles that should bind
    the actual drafted text. Prepended to _draft_short's system prompt.

    Returns "" when no voice depth exists, so existing handlers
    fall back to current behavior (Voice: {tone} only).
    """
    if not owner_id:
        return ""

    try:
        voice = get_voice_depth(owner_id)
    except Exception as e:
        logger.warning(f"voice_depth_payload_for_inner_call failed: {e}")
        return ""

    if not voice:
        return ""

    samples = voice.get("voice_samples") or {}
    dos = voice.get("voice_dos") or []
    donts = voice.get("voice_donts") or []
    greeting = voice.get("greeting_style")
    signoff = voice.get("signoff_style")

    lines: List[str] = []

    if any(samples.get(s) for s in VOICE_SAMPLE_SLOTS):
        lines.append("MATCH THIS PRACTITIONER'S VOICE BASED ON THESE SAMPLES:")
        for slot in VOICE_SAMPLE_SLOTS:
            text = samples.get(slot)
            if text:
                pretty = slot.replace("_", " ").title()
                if len(text) > 800:
                    text = text[:800] + "...[truncated]"
                lines.append(f"  [{pretty}]: {text}")

    if dos:
        lines.append("ALWAYS: " + "; ".join(dos))
    if donts:
        lines.append("NEVER: " + "; ".join(donts))
    if greeting:
        lines.append(f"OPEN WITH: {greeting}")
    if signoff:
        lines.append(f"SIGN OFF WITH: {signoff}")

    if not lines:
        return ""
    return "\n".join(lines) + "\n"
