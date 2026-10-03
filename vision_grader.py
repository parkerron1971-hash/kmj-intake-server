# vision_grader.py
# ─────────────────────────────────────────────────────────────────────
# Phase 2, §3-J (Kevin's Kimi Design Integration spec): the system
# finally LOOKS at what it decided. Headless-Chromium screenshots at
# 390 / 900 / 1440px (the first screen) plus views further down the page
# at 1440 and 390 (2026-10-03), graded by a vision-capable judge against the
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
import llm_call
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("vision_grader")

BREAKPOINTS = (390, 900, 1440)

# THE WHOLE PAGE (2026-10-03). The grader used to see only the first 900px
# at each breakpoint, so a page was scored on its hero alone: the real
# test build's letterboard, gallery and hours never reached the judge,
# and a page whose gallery was all placeholder boxes outscored it on a
# lovely first screen. Now a few views FURTHER DOWN ride along at the
# desktop and phone widths. Impact is still judged on the first screen
# only, so the ship gate (impact >= 7) and the composite stay comparable.
SCROLL_WIDTHS = (1440, 390)
SCROLL_STOPS = {1440: 4, 390: 3}     # most views per width below the first screen
VIEWPORT_H = 900

RUBRIC = """You are grading rendered screenshots of a generated website. You get
the FIRST SCREEN at three breakpoints (390 / 900 / 1440), then a few views
FURTHER DOWN the same page at 1440 and 390 (each labeled with where it
sits). Score each 0-10:
1. FIRST-VIEWPORT IMPACT — judged ONLY from the first-screen images: does
   the hero have one clear oversized moment, atmosphere (glow/texture/
   grid), and a composed (non-generic) nav?
2. BALANCE & COLLISION — across the WHOLE page: any overlaps, crowding,
   dead zones, orphans? (10 = perfectly composed, 0 = colliding mess)
3. MOTIF VISIBILITY — across the whole page: do accents live in materials
   (glows, rules, tags, washes, objects), not only in type? (Doctrine D3)
4. RHYTHM — across the whole page: does vertical spacing feel systematic,
   with one deliberately quiet section, and does the page keep its
   quality below the first screen?
5. TEMPLATE SMELL (0 = none, 10 = reeks) — gradient-purple hero, three-
   icon generic feature row, builder monotony, cold blue on dark, and
   boxes or captions standing in for photos that are not there.
You are looking at STATIC screenshots. NEVER penalize for interactive
behavior you cannot observe — hover states, animations, transitions,
scroll effects all exist in the CSS but cannot show in a still image.
Judge only what is visible. A sticky bar repeating at the top or bottom
of several views is one bar, not a repeat.
Also answer: DOES ANY SECTION LOOK BROKEN, anywhere on the page? (y/n + which)
Output verdict JSON ONLY:
{"first_viewport_impact": n, "balance": n, "motif_visibility": n,
 "rhythm": n, "template_smell": n, "broken": "y"|"n",
 "broken_where": "...", "below_fold_note": "one sentence on the page below the first screen",
 "notes": ["actionable note", ...]}"""


def _enabled() -> bool:
    return (os.environ.get("VISION_GRADER") or "on").strip().lower() not in ("off", "0", "false")


def judge_effort() -> str:
    """How hard the vision judge thinks before answering, on models that
    think (VISION_JUDGE_EFFORT: low / medium / high; default medium).

    2026-10-03: Sonnet 5.5 thinks adaptively at HIGH unless told
    otherwise, and the thinking counts against the call's max_tokens. An
    unbounded judge can spend a small cap thinking and hand back no text,
    which every caller reads as "nothing wrong" (no verdict, no findings,
    SHIP). Every call that reads VISION_JUDGE_MODEL rides this."""
    e = (os.environ.get("VISION_JUDGE_EFFORT") or "medium").strip().lower()
    return e if e in ("low", "medium", "high") else "medium"


def judge_kwargs(model: str) -> Dict[str, Any]:
    """The effort field for one judge call, only where the model takes it
    (Sonnet 4.5 400s on it, so it gets nothing)."""
    import model_ladder
    return model_ladder.effort_kwargs(model, judge_effort())


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


# Walk the page top to bottom before the views further down are taken, so
# reveal-on-scroll content (an IntersectionObserver or a scroll handler
# adding the "in" class) has arrived. Returns the page height. Capped so a
# runaway page can't hold the browser.
# A page with html{scroll-behavior:smooth} animates every scrollTo, and a
# screenshot taken mid-glide shows a displaced sticky nav over a blank page
# (seen on the first real run). Scrolling is made instant before the walk.
_SCROLL_SETTLE_CSS = "html,body{scroll-behavior:auto !important}"

_SLOW_SCROLL_JS = """async () => {
  const H = () => Math.max(document.documentElement.scrollHeight,
                           document.body ? document.body.scrollHeight : 0);
  for (let y = 0, i = 0; y < H() && i < 80; y += 500, i++) {
    window.scrollTo({top: y, behavior: 'instant'});
    await new Promise(r => setTimeout(r, 40));
  }
  window.scrollTo({top: H(), behavior: 'instant'});
  await new Promise(r => setTimeout(r, 120));
  window.scrollTo({top: 0, behavior: 'instant'});
  await new Promise(r => setTimeout(r, 80));
  return H();
}"""


def scroll_stops(page_height: int, max_stops: int,
                 viewport_h: int = VIEWPORT_H) -> List[int]:
    """Where the views further down sit: evenly spaced from just below the
    first screen to the last screen (the footer), at most `max_stops`, and
    none when the page is barely taller than one screen. Pure."""
    h = int(page_height or 0)
    last = h - viewport_h
    if max_stops <= 0 or last < viewport_h * 0.15:
        return []
    first = min(viewport_h, last)
    # stops at least three quarters of a screen apart: a page just over two
    # screens tall gets one view further down, not two of the same thing
    n = max(1, min(max_stops, 1 + int((last - first) // (viewport_h * 0.75))))
    if n == 1:
        return [last]
    step = (last - first) / (n - 1)
    return [int(round(first + i * step)) for i in range(n)]


def _capture(html: str, below: bool = True
             ) -> Optional[Tuple[List[bytes], List[Tuple[str, bytes]]]]:
    """Render the html at each breakpoint. Returns (first-screen JPEGs in
    BREAKPOINTS order, [(label, JPEG)] views further down at SCROLL_WIDTHS).
    None when playwright is unavailable or the first screens fail. A
    failure further down only shortens the second list."""
    try:
        from playwright.sync_api import sync_playwright  # lazy — optional dep
    except Exception:
        logger.info("[vision] playwright not installed — grading skipped "
                    "(pip install playwright && playwright install chromium)")
        return None
    shots: List[bytes] = []
    further: Dict[int, List[Tuple[str, bytes]]] = {}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width in BREAKPOINTS:
                    page = browser.new_page(viewport={"width": width, "height": VIEWPORT_H})
                    page.set_content(html, wait_until="networkidle", timeout=20000)
                    try:
                        page.add_style_tag(content=_ANIMATION_SETTLE_CSS)
                        page.wait_for_timeout(200)
                    except Exception:
                        pass  # settle best-effort; screenshot regardless
                    shots.append(page.screenshot(type="jpeg", quality=60))
                    if below and width in SCROLL_WIDTHS:
                        try:
                            further[width] = _views_further_down(page, width)
                        except Exception as e:
                            logger.info(f"[vision] views below the first screen "
                                        f"skipped at {width}px: {type(e).__name__}: {e}")
                    page.close()
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"[vision] screenshot pass failed: {type(e).__name__}: {e}")
        return None
    if len(shots) != len(BREAKPOINTS):
        return None
    ordered = [v for w in SCROLL_WIDTHS for v in further.get(w, [])]
    return shots, ordered


def _views_further_down(page: Any, width: int) -> List[Tuple[str, bytes]]:
    try:
        page.add_style_tag(content=_SCROLL_SETTLE_CSS)
    except Exception:
        pass
    height = int(page.evaluate(_SLOW_SCROLL_JS) or 0)
    stops = scroll_stops(height, SCROLL_STOPS.get(width, 0))
    views: List[Tuple[str, bytes]] = []
    for i, y in enumerate(stops):
        page.evaluate(f"window.scrollTo({{top: {y}, behavior: 'instant'}})")
        page.wait_for_timeout(250)
        views.append((f"{width}px, further down {i + 1} of {len(stops)} "
                      f"(from {y:,}px on a {height:,}px page)",
                      page.screenshot(type="jpeg", quality=60)))
    return views


def _screenshot(html: str) -> Optional[List[bytes]]:
    """Render the html at each breakpoint; return JPEG bytes (the first
    screen only). None when playwright is unavailable. canvas.py's self-
    review reads this contract; the grader itself uses _capture."""
    got = _capture(html, below=False)
    return got[0] if got else None


def _content(shots: List[bytes], below: Optional[List[Tuple[str, bytes]]],
             image_block: Any) -> List[Dict[str, Any]]:
    """The judge's message: the first screens, then the views further down,
    each labeled so impact is read from the first and the rest from all."""
    content: List[Dict[str, Any]] = []
    for width, shot in zip(BREAKPOINTS, shots):
        content.append({"type": "text", "text": f"FIRST SCREEN — breakpoint {width}px:"})
        content.append(image_block(shot))
    for label, shot in (below or []):
        content.append({"type": "text", "text": f"FURTHER DOWN — {label}:"})
        content.append(image_block(shot))
    content.append({"type": "text", "text": "Grade per the rubric. Verdict JSON only."})
    return content


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
                     standard: Optional[str] = None,
                     below: Optional[List[Tuple[str, bytes]]] = None) -> Optional[str]:
    from anthropic import Anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    content = _content(shots, below, lambda shot: {"type": "image", "source": {
        "type": "base64", "media_type": "image/jpeg",
        "data": base64.b64encode(shot).decode()}})
    client = llm_call.sdk_client(key=key)
    model = (os.environ.get("VISION_JUDGE_MODEL") or "claude-sonnet-4-5-20250929").strip()
    msg = client.messages.create(
        model=model,
        # 800 → 2000 (2026-10-03): Sonnet 5.5 thinks adaptively and the
        # thinking counts against this cap; the whole-page verdict is longer
        # than the first-screen one was.
        max_tokens=2000, system=_rubric(standard),
        messages=[{"role": "user", "content": content}], timeout=90.0,
        **judge_kwargs(model))
    _meter(business_id, getattr(msg, "model", "") or "",
           getattr(getattr(msg, "usage", None), "input_tokens", 0) or 0,
           getattr(getattr(msg, "usage", None), "output_tokens", 0) or 0)
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")


def _grade_moonshot(shots: List[bytes], business_id: str = "",
                    standard: Optional[str] = None,
                    below: Optional[List[Tuple[str, bytes]]] = None) -> Optional[str]:
    import httpx
    key = (os.environ.get("MOONSHOT_API_KEY") or "").strip()
    if not key:
        return None
    base = (os.environ.get("MOONSHOT_BASE_URL") or "https://api.moonshot.ai/v1").rstrip("/")
    content = _content(shots, below, lambda shot: {"type": "image_url", "image_url": {
        "url": "data:image/jpeg;base64," + base64.b64encode(shot).decode()}})
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
    below = str(v.get("below_fold_note") or "").strip()
    if below:
        out["below_fold_note"] = below[:240]
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
# arcD-2 (2026-07-23): static-screenshot rule — the judge was docking
# every build's motif score for "no hover states visible", an axis a
# still image can never show.
# page-1 (2026-10-03): the judge sees the whole page — views further down
# at 1440 and 390 — so balance, motif, rhythm and smell are the page's,
# not the hero's. Old-era live verdicts get re-graded before they defend.
RUBRIC_VERSION = "page-1"


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
          standard: Optional[str] = None,
          standard_key: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Screenshot + grade. None = grader unavailable (never build-fatal).
    `standard` (Arc D) = the authored reference bar for this build's
    direction (reference_standards.standard_for) — the judge scores
    against it instead of grading in a vacuum.
    `standard_key` (judge fairness, 2026-07-23) names which bar the
    verdict was earned under; the ratchet refuses to compare composites
    across different bars (a build judged against the Nike-campaign
    standard must not have to beat a live score earned on a softer
    default bar)."""
    if not _enabled():
        return None
    got = _capture(html)
    if not got or not got[0]:
        return None
    shots, below = got
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
                raw = _grade_moonshot(shots, business_id, standard, below)
            except Exception as e:
                logger.warning(f"[vision] moonshot judge failed "
                               f"({type(e).__name__}: {e}) — falling back to anthropic")
        else:
            raw = _grade_anthropic(shots, business_id, standard, below)
        v = _parse_verdict(raw or "")
        if v is None and provider == "moonshot":
            # Judge fail-open mirrors the composer's: fall back to Claude.
            logger.warning("[vision] moonshot judge unusable — falling back to anthropic")
            v = _parse_verdict(_grade_anthropic(shots, business_id, standard, below) or "")
            if v is not None:
                provider = "anthropic"
        if v is not None:
            v["judge_provider"] = provider
            v["passes_gate"] = verdict_passes(v)
            v["rubric"] = RUBRIC_VERSION
            v["standard_key"] = standard_key or "default"
            logger.info(f"[vision] verdict for {(business_id or 'unknown')[:8]}: "
                        f"{json.dumps(v)[:400]}")
        return v
    except Exception as e:
        logger.warning(f"[vision] grading failed: {type(e).__name__}: {e}")
        return None
