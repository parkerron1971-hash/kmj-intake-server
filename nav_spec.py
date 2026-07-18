# nav_spec.py
# ─────────────────────────────────────────────────────────────────────
# Model-AUTHORED navigation (2026-07-18, Kevin's creative-capture arc):
# "the menu in the generated website should be able to change... the
# models' instincts on top of the rules are freed to create."
#
# The discipline stays — the LLM never writes HTML. What changes is the
# creative unit: instead of PICKING one of four pre-built header
# variants, the model AUTHORS a spec across independent axes
# (architecture × logo treatment × CTA style × link style × accent
# detail × CTA wording ≈ 576+ combinations nobody pre-built). Hand-
# written CSS in site_modules/header.py renders every legal combination,
# so a broken menu is impossible.
#
# FALLBACK (Kevin's requirement): env SITE_NAV_SPEC=off disables
# authoring entirely; any authoring/parse/validation failure returns
# None. Both paths land on the #172 DNA-variant headers — today's
# behavior, untouched.
#
# One authoring call per build (in-process TTL cache keeps every page
# of a multi-page compose on the SAME menu and makes previews free).
# ─────────────────────────────────────────────────────────────────────

import json
import logging
import os
import re
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("nav_spec")

ALLOWED: Dict[str, list] = {
    "architecture":   ["classic", "split", "banner", "ghost"],
    "logo_treatment": ["wordmark", "monogram", "logo"],
    "cta_style":      ["pill", "sharp", "ghost", "text"],
    "link_style":     ["caps", "title", "lower"],
    "accent_detail":  ["underline", "dot", "frame", "none"],
}

_TTL_SECONDS = 900.0
_cache: Dict[str, tuple] = {}

_SYSTEM = """You are the navigation designer inside a website composer. You AUTHOR the menu bar's design spec — you do not write HTML.

THE CREATIVE CONTRACT: the practitioner's answers below are the FLOOR, not the ceiling. Honor every stated constraint (especially anything they said to avoid), then add taste ON TOP — pick a combination no template would ship. Menus across different businesses must not look like siblings.

Output ONLY a JSON object with exactly these keys and allowed values:
  architecture:   "classic" (brand left, links right) | "split" (links lead left, brand centered, hard edge) | "banner" (centered two-row masthead) | "ghost" (transparent over the hero, solidifies on scroll)
  logo_treatment: "wordmark" (styled business name) | "monogram" (brand mark + name) | "logo" (uploaded logo image when available)
  cta_style:      "pill" | "sharp" (square corners) | "ghost" (outlined) | "text" (bare accent link)
  link_style:     "caps" (small caps, wide tracking) | "title" (Title Case, quieter) | "lower" (all lowercase, modern)
  cta_label:      a short call-to-action in the business's own voice, max 20 characters (e.g. "Book a session", "Start a project", "Get the quote")
  accent_detail:  "underline" (accent sweep on hover) | "dot" (accent dot after the brand name) | "frame" (accent outline offset around the CTA) | "none" (silence)

Reason from the personality: bold+dark businesses can take split or banner with sharp CTAs; soft/warm ones suit ghost with title-case links; a "statement" type voice pairs with caps; "editorial" with title case. Never contradict the avoid-list. No commentary — JSON only."""


def _build_user(business: Dict[str, Any], dna: Dict[str, Any],
                site_prefs: Dict[str, Any]) -> str:
    prefs = site_prefs or {}
    story = prefs.get("story") or {}
    lines = [
        f"Business: {business.get('name') or 'Unknown'} ({business.get('type') or 'general'})",
        f"Design DNA: vibe={dna.get('vibe')}, intensity={dna.get('intensity')}, accent_style={dna.get('accent_style')}",
    ]
    if prefs.get("feel_words"):
        lines.append(f"Feel words: {', '.join(prefs['feel_words'][:3])}")
    if prefs.get("boldness"):
        lines.append(f"Boldness (1 quiet - 3 loud): {prefs['boldness']}")
    if prefs.get("type_personality"):
        lines.append(f"Type voice: {prefs['type_personality']}")
    if prefs.get("structure"):
        lines.append(f"Structure: {prefs['structure']}")
    if prefs.get("cta_goal"):
        lines.append(f"Primary goal: {prefs['cta_goal']}")
    if prefs.get("avoid"):
        lines.append(f"AVOID (hard constraints): {str(prefs['avoid'])[:300]}")
    atmosphere = story.get("atmosphere")
    if atmosphere:
        lines.append(f"Walking-in feeling: {str(atmosphere)[:200]}")
    return "\n".join(lines)


def validate_spec(raw: Any) -> Optional[Dict[str, Any]]:
    """Clamp a parsed spec to the schema. None when unusable."""
    if not isinstance(raw, dict):
        return None
    spec: Dict[str, Any] = {}
    for key, allowed in ALLOWED.items():
        v = raw.get(key)
        if isinstance(v, str) and v.strip().lower() in allowed:
            spec[key] = v.strip().lower()
    label = raw.get("cta_label")
    if isinstance(label, str):
        clean = re.sub(r"[<>{}\"`]", "", label).strip()[:20]
        if clean:
            spec["cta_label"] = clean
    # architecture is the one required axis — without it there is no spec.
    if "architecture" not in spec:
        return None
    return spec


def author_nav_spec(business_id: str, business: Dict[str, Any],
                    dna: Dict[str, Any], site_prefs: Dict[str, Any],
                    voice_profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Author (or return cached) nav spec. None → caller falls back to
    the DNA-variant headers. Never raises."""
    if (os.environ.get("SITE_NAV_SPEC") or "on").strip().lower() in ("off", "0", "false"):
        return None
    now = time.time()
    hit = _cache.get(business_id)
    if hit and now - hit[0] < _TTL_SECONDS:
        return hit[1]
    spec: Optional[Dict[str, Any]] = None
    # Stage F (Kevin's spec): the CTA wording is checked against the
    # voice profile's words-to-avoid list — in the prompt AND after.
    avoid_words = [w.strip().lower() for w in
                   str((voice_profile or {}).get("avoid") or "").replace(";", ",").split(",")
                   if w.strip()]
    try:
        import site_llm
        msg = site_llm.create_message(
            model=(os.environ.get("NAV_SPEC_MODEL") or "claude-sonnet-4-5-20250929").strip(),
            max_tokens=300,
            system=_SYSTEM,
            user_content=_build_user(business or {}, dna or {}, site_prefs or {})
            + (("\nVOICE - words to avoid in the CTA: " + ", ".join(avoid_words[:12]))
               if avoid_words else ""),
            timeout=45.0,
            task="nav_spec",
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        spec = validate_spec(json.loads(text))
        # An authored CTA label carrying an avoided word is dropped —
        # the default label takes over; it is never shipped.
        if spec and spec.get("cta_label") and avoid_words:
            _low = spec["cta_label"].lower()
            if any(w in _low for w in avoid_words):
                logger.warning(f"[nav_spec] cta_label dropped for {business_id[:8]} "
                               f"(contains a words-to-avoid term)")
                spec.pop("cta_label", None)
        if spec:
            logger.info(f"[nav_spec] authored for {business_id[:8]}: {json.dumps(spec)}")
        else:
            logger.warning(f"[nav_spec] unusable spec for {business_id[:8]} — DNA-variant fallback")
    except Exception as e:
        logger.warning(f"[nav_spec] authoring failed for {business_id[:8]} "
                       f"({type(e).__name__}: {e}) — DNA-variant fallback")
        spec = None
    _cache[business_id] = (now, spec)
    return spec
