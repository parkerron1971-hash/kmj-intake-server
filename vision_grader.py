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
    return (os.environ.get("SHIP_GATE") or "").strip().lower() == "enforce"


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
                    shots.append(page.screenshot(type="jpeg", quality=60))
                    page.close()
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"[vision] screenshot pass failed: {type(e).__name__}: {e}")
        return None
    return shots


def _grade_anthropic(shots: List[bytes]) -> Optional[str]:
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
        max_tokens=700, system=RUBRIC,
        messages=[{"role": "user", "content": content}], timeout=90.0)
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def _grade_moonshot(shots: List[bytes]) -> Optional[str]:
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
    r = httpx.post(f"{base}/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": (os.environ.get("SITE_BUILDER_MODEL") or "kimi-k3").strip(),
                         "max_tokens": 3700,
                         "messages": [{"role": "system", "content": RUBRIC},
                                       {"role": "user", "content": content}]},
                   timeout=120)
    if r.status_code >= 400:
        raise RuntimeError(f"moonshot vision {r.status_code}: {r.text[:200]}")
    return (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "")


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


def grade(html: str, business_id: str = "") -> Optional[Dict[str, Any]]:
    """Screenshot + grade. None = grader unavailable (never build-fatal)."""
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
        raw = _grade_moonshot(shots) if provider == "moonshot" else _grade_anthropic(shots)
        v = _parse_verdict(raw or "")
        if v is None and provider == "moonshot":
            # Judge fail-open mirrors the composer's: fall back to Claude.
            logger.warning("[vision] moonshot judge unusable — falling back to anthropic")
            v = _parse_verdict(_grade_anthropic(shots) or "")
        if v is not None:
            v["judge_provider"] = provider
            v["passes_gate"] = verdict_passes(v)
            logger.info(f"[vision] verdict for {(business_id or 'unknown')[:8]}: "
                        f"{json.dumps(v)[:400]}")
        return v
    except Exception as e:
        logger.warning(f"[vision] grading failed: {type(e).__name__}: {e}")
        return None
