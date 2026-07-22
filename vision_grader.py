# vision_grader.py
# ─────────────────────────────────────────────────────────────────────
# Phase 2, §3-J (Kevin's Kimi Design Integration spec): the system
# finally LOOKS at what it decided. Headless-Chromium screenshots at
# 390 / 900 / 1440px, graded by a vision-capable judge against the
# §4-E rubric. The judge provider is PINNED (K5 — SHIP_JUDGE_PROVIDER,
# default Claude) and never follows the composer.
#
# Dependency posture (fail-open): playwright is imported lazily. When
# it isn't installed (or VISION_GRADER=off), grading returns None with
# ONE clear log line and the build proceeds exactly as today. To arm
# it on Railway:  pip install playwright && playwright install chromium
#
# Ship gate posture: verdicts are recorded + logged on every build.
# SHIP_GATE=enforce turns a failing verdict into a build failure; the
# default is observe-only so a grader outage can never brick composing.
# ─────────────────────────────────────────────────────────────────────

import base64
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("vision_grader")

BREAKPOINTS = (390, 900, 1440)

RUBRIC = """You are grading rendered screenshots of a generated website at three
breakpoints (390 / 900 / 1440). Score each 0-10:
1. FIRST-VIEWPORT IMPACT — does the hero have one clear oversized moment,
   atmosphere (glow/texture/grid), and a composed (non-generic) nav?
2. BALANCE & COLLISION — any overlaps, crowding, dead zones, orphans?
   (10 = perfectly composed, 0 = colliding mess)
3. MOTIF VISIBILITY — do accents live in materials (glows, rules, tags,
   hovers), not only in type? (Doctrine D3)
4. RHYTHM — does vertical spacing feel systematic, with one deliberately
   quiet section?
5. TEMPLATE SMELL (0 = none, 10 = reeks) — gradient-purple hero, three-
   icon generic feature row, builder monotony, cold blue on dark.
Also answer: DOES ANY SECTION LOOK BROKEN? (y/n + which)
Output verdict JSON ONLY:
{"first_viewport_impact": n, "balance": n, "motif_visibility": n,
 "rhythm": n, "template_smell": n, "broken": "y"|"n",
 "broken_where": "...", "notes": ["actionable note", ...]}"""


def _enabled() -> bool:
    return (os.environ.get("VISION_GRADER") or "on").strip().lower() not in ("off", "0", "false")


def gate_enforced() -> bool:
    """Arc C2 (2026-07-21): the ship gate ENFORCES by default — a failing
    vision verdict blocks the build and the bounded quality regen retries
    with the judge's notes. SHIP_GATE=observe is the explicit relax valve.
    (When the grader can't run at all — no playwright, judge outage — it
    returns None upstream and the gate never fires: enforcement only
    applies to a verdict actually rendered.)"""
    return (os.environ.get("SHIP_GATE") or "").strip().lower() not in (
        "observe", "off", "0", "false")


def _meter(business_id: str, model: str, input_tokens: int,
           output_tokens: int) -> None:
    """Meter the judge call (2026-07-18): the grader runs a 3-screenshot
    judge on EVERY render — self-heal recursions, refine re-renders, and
    the bounded quality regen included — and until now none of it was
    visible to usage tracking or spend_guard. Never raises."""
    try:
        from api_usage_logger import log_api_usage_sync
        log_api_usage_sync(
            endpoint="/vision/grade", model=model or "unknown",
            input_tokens=input_tokens or 0, output_tokens=output_tokens or 0,
            business_id=business_id or "unknown", task_type="vision-grade")
    except Exception:
        pass


# Fast-forward entrance animations before judging: set_content fires the
# screenshot the moment the network settles, which catches staggered hero
# reveals mid-flight (the 07-20 KMJ build was graded broken=y because only
# "The leap of" had animated in). Judge the final state, not the entrance.
_ANIMATION_SETTLE_CSS = (
    "*,*::before,*::after{"
    "animation-delay:0s !important;"
    "animation-duration:0.01s !important;"
    "transition-duration:0.01s !important;"
    "transition-delay:0s !important;}"
)


def _screenshot(html: str) -> Optional[List[bytes]]:
    """Render the html at each breakpoint; return JPEG bytes (above the
    fold). None when playwright is unavailable."""
    try:
        from playwright.sync_api import sync_playwright  # lazy — optional dep
    except Exception:
        logger.info("[vision] playwright not installed — grading skipped "
                    "(pip install playwright && playwright install chromium)")
        return None
    shots: List[bytes] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width in BREAKPOINTS:
                    page = browser.new_page(viewport={"width": width, "height": 900})
                    page.set_content(html, wait_until="networkidle", timeout=20000)
                    try:
                        page.add_style_tag(content=_ANIMATION_SETTLE_CSS)
                        page.wait_for_timeout(200)
                    except Exception:
                        pass  # settle best-effort; screenshot regardless
                    shots.append(page.screenshot(type="jpeg", quality=60))
                    page.close()
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"[vision] screenshot pass failed: {type(e).__name__}: {e}")
        return None
    return shots


def _rubric(standard: Optional[str]) -> str:
    """Arc D (2026-07-21): the judge grades AGAINST A BAR, not in a
    vacuum. When a reference standard rides along, it is appended with
    teeth — a page that would look amateur beside the standard cannot
    score top marks."""
    if not (standard or "").strip():
        return RUBRIC
    # Ratchet calibration (2026-07-21): the original clause hard-capped
    # scores ("cannot exceed 6") which clustered every real build into
    # rejection — a practitioner paid for a rebuild and got nothing,
    # twice. The standard ANCHORS judgment now; it never dictates caps.
    return (RUBRIC
            + "\n\nTHE STANDARD — the craft bar for this page's direction. "
              "Grade against it, not in a vacuum; score honestly on each "
              "axis and let the numbers land where they land:\n"
            + standard.strip())


def _grade_anthropic(shots: List[bytes], business_id: str = "",
                     standard: Optional[str] = None) -> Optional[str]:
    from anthropic import Anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    content: List[Dict[str, Any]] = []
    for i, (width, shot) in enumerate(zip(BREAKPOINTS, shots)):
        content.append({"type": "text", "text": f"Breakpoint {width}px:"})
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": "image/jpeg",
            "data": base64.b64encode(shot).decode()}})
    content.append({"type": "text", "text": "Grade per the rubric. Verdict JSON only."})
    client = Anthropic(api_key=key)
    msg = client.messages.create(
        model=(os.environ.get("VISION_JUDGE_MODEL") or "claude-sonnet-4-5-20250929").strip(),
        max_tokens=700, system=_rubric(standard),
        messages=[{"role": "user", "content": content}], timeout=90.0)
    _meter(business_id, getattr(msg, "model", "") or "",
           getattr(getattr(msg, "usage", None), "input_tokens", 0) or 0,
           getattr(getattr(msg, "usage", None), "output_tokens", 0) or 0)
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def _grade_moonshot(shots: List[bytes], business_id: str = "",
                    standard: Optional[str] = None) -> Optional[str]:
    import httpx
    key = (os.environ.get("MOONSHOT_API_KEY") or "").strip()
    if not key:
        return None
    base = (os.environ.get("MOONSHOT_BASE_URL") or "https://api.moonshot.ai/v1").rstrip("/")
    content: List[Dict[str, Any]] = []
    for width, shot in zip(BREAKPOINTS, shots):
        content.append({"type": "text", "text": f"Breakpoint {width}px:"})
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/jpeg;base64," + base64.b64encode(shot).decode()}})
    content.append({"type": "text", "text": "Grade per the rubric. Verdict JSON only."})
    model = (os.environ.get("SITE_BUILDER_MODEL") or "kimi-k3").strip()
    r = httpx.post(f"{base}/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model,
                         "max_tokens": 3700,
                         "messages": [{"role": "system", "content": _rubric(standard)},
                                       {"role": "user", "content": content}]},
                   timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"moonshot vision {r.status_code}: {r.text[:200]}")
    data = r.json()
    usage = data.get("usage") or {}
    _meter(business_id, data.get("model") or model,
           int(usage.get("prompt_tokens") or 0),
           int(usage.get("completion_tokens") or 0))
    return (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")


def _parse_verdict(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        v = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(v, dict):
        return None
    out: Dict[str, Any] = {}
    for k in ("first_viewport_impact", "balance", "motif_visibility", "rhythm", "template_smell"):
        try:
            out[k] = max(0, min(10, int(v.get(k))))
        except Exception:
            return None
    out["broken"] = "y" if str(v.get("broken", "n")).strip().lower().startswith("y") else "n"
    out["broken_where"] = str(v.get("broken_where") or "")[:200]
    notes = v.get("notes")
    out["notes"] = [str(n)[:240] for n in notes[:6]] if isinstance(notes, list) else []
    return out


def verdict_passes(v: Dict[str, Any]) -> bool:
    """The §3-J ship gate: impact >= 7, smell < 4, nothing broken."""
    return (v.get("first_viewport_impact", 0) >= 7
            and v.get("template_smell", 10) < 4
            and v.get("broken") != "y")


# Bumped whenever the grading rubric or reference standards change
# meaningfully. The ratchet refuses to compare verdicts across eras — a
# live verdict stamped with an older (or missing) rubric gets re-graded
# under today's standard before it may defend the live site.
RUBRIC_VERSION = "arcD-1"


def verdict_composite(v: Optional[Dict[str, Any]]) -> int:
    """One comparable quality number (higher = better): the four craft
    axes minus smell. Used by the never-downgrade ratchet."""
    if not isinstance(v, dict):
        return -999
    try:
        return (int(v.get("first_viewport_impact", 0))
                + int(v.get("balance", 0))
                + int(v.get("motif_visibility", 0))
                + int(v.get("rhythm", 0))
                - int(v.get("template_smell", 10)))
    except (TypeError, ValueError):
        return -999


def grade(html: str, business_id: str = "",
          standard: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Screenshot + grade. None = grader unavailable (never build-fatal).
    `standard` (Arc D) = the authored reference bar for this build's
    direction (reference_standards.standard_for) — the judge scores
    against it instead of grading in a vacuum."""
    if not _enabled():
        return None
    shots = _screenshot(html)
    if not shots:
        return None
    try:
        import site_llm
        provider = site_llm.judge_provider()
    except Exception:
        provider = "anthropic"
    try:
        # Acceptance-run finding (2026-07-18): _grade_moonshot RAISES on
        # transport/auth errors (401, timeout), which jumped past the
        # fallback below straight to the outer except — Claude only
        # covered "moonshot answered junk", not "moonshot unreachable".
        # Contain the moonshot leg so ANY failure falls to Claude, and
        # label the verdict with the judge that actually produced it.
        raw = None
        if provider == "moonshot":
            try:
                raw = _grade_moonshot(shots, business_id, standard)
            except Exception as e:
                logger.warning(f"[vision] moonshot judge failed "
                               f"({type(e).__name__}: {e}) — falling back to anthropic")
        else:
            raw = _grade_anthropic(shots, business_id, standard)
        v = _parse_verdict(raw or "")
        if v is None and provider == "moonshot":
            # Judge fail-open mirrors the composer's: fall back to Claude.
            logger.warning("[vision] moonshot judge unusable — falling back to anthropic")
            v = _parse_verdict(_grade_anthropic(shots, business_id, standard) or "")
            if v is not None:
                provider = "anthropic"
        if v is not None:
            v["judge_provider"] = provider
            v["passes_gate"] = verdict_passes(v)
            v["rubric"] = RUBRIC_VERSION
            logger.info(f"[vision] verdict for {(business_id or 'unknown')[:8]}: "
                        f"{json.dumps(v)[:400]}")
        return v
    except Exception as e:
        logger.warning(f"[vision] grading failed: {type(e).__name__}: {e}")
        return None
