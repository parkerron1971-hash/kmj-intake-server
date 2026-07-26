# builder_v2.py
# ─────────────────────────────────────────────────────────────────────
# REVAMP PHASE 2 — BUILDER V2 (docs/REVAMP_TARGET.md Layer 4, signed).
#
# ONE mind, ONE call, the whole page — the claude.ai/Emergent mechanism
# proven in the local renders — executing the APPROVED SPEC as law.
# The contract armor runs AFTER authorship, never fighting it:
#
#   MECHANICAL (deterministic, zero model calls — Amendment 1):
#     - THE ANNOTATOR: a real DOM walk injects any missing
#       data-override-target stamps so Edit Mode always works.
#       Editability is the platform's guarantee, not the model's job.
#     - JS ARMOR: scripts scanned against the banned list; a bad
#       script is dropped, never fatal.
#     - EXTERNAL-REQUEST ARMOR: only Google-Fonts links and https
#       images survive; everything else is stripped.
#   AUTHORSHIP LAWS (repair-worthy — deterministic):
#     - TRUTH: every digit-run in visible text must trace to the data.
#     - COVERAGE: every inventory image present by url; nav, contact
#       form (posting to the real endpoint), and footer present.
#     - DASH LAW / HEAD+SHARE / INTERACTION GRAMMAR / REVEAL SAFETY
#       (Kevin's review, 2026-07-25): no dash-spliced copy; real
#       title/description/og:image; galleries open closer (lightbox);
#       no IntersectionObserver-only reveals (the reveal-skip bug).
#     - ONE surgical law repair; repair fails again → fallback (None)
#       and the old path takes over, wearing the spec's tokens via the
#       bridge.
#   THE EYES (Arc 2 — the vision loop, SITE_V2_VISION_LOOP, default on):
#     - The builder WALKS its own render (scroll top/middle/bottom at
#       390 + 1440, one ultrawide look) and measures the screenshots
#       against the spec + the standing checklist (alignment, blank
#       sections, caption truth, grammar, legibility, spec fidelity).
#     - ONE vision repair, surgical. Quality is never fatal: eyes
#       unavailable or repair breaks a law → the law-passing document
#       ships and the report says exactly what happened.
#
# Gated on SITE_BUILDER_V2=on (default OFF). The v2 document joins
# render_and_persist at the same seam the canvas uses (_canvas_html),
# so slot population, overrides, the token bridge, the easel step and
# the judge all apply unchanged. Model-portable by construction: the
# prompt carries no model-specific syntax; model/limits live in env
# (BUILDER_V2_MODEL / BUILDER_V2_MAX_TOKENS) and every call rides the
# model_ladder.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import llm_call
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("builder_v2")

V2_MAX_TOKENS_DEFAULT = 28000
V2_TEMPERATURE = 0.8
DOC_MAX_BYTES = 300 * 1024

_ALLOWED_LINK_HOSTS = ("fonts.googleapis.com", "fonts.gstatic.com")
# AUDIT FIX (flight one): the 2-digit rule attacked the DESIGN — the
# spec's own section numerals (01, 02…) and the copyright year were
# flagged as invented facts, firing repairs that pressured the author
# to strip its own design language. CLAIMS are 3+ digit runs; 1-2
# digit ordinals are layout, and the current year is a date, not a
# claim. (Trade-off accepted: an invented 2-digit stat now passes the
# automated trace — the judge and the owner remain its referees.)
_DIGIT_RUN_RE = re.compile(r"\d{3,}")
_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)

_JS_BANNED = (
    "eval(", "new Function", "fetch(", "XMLHttpRequest", "import(",
    "WebSocket", "document.write", "localStorage", "sessionStorage",
)


def contact_endpoint(business_id: str) -> str:
    """The one url the page's script is allowed to fetch: the platform's
    own contact-submit endpoint (a JSON POST — a native form post can't
    reach it, so the script MUST carry this call for the form to work)."""
    return (f"https://kmj-intake-server-production.up.railway.app"
            f"/sites/{business_id}/contact-submit")


def enabled() -> bool:
    return (os.environ.get("SITE_BUILDER_V2") or "").strip().lower() in (
        "on", "1", "true", "yes")


def _model() -> str:
    m = (os.environ.get("BUILDER_V2_MODEL") or "").strip()
    if m:
        return m
    try:
        import canvas
        return canvas._model()
    except Exception:
        return "claude-sonnet-4-5-20250929"


def _max_tokens() -> int:
    try:
        return max(8000, int(os.environ.get("BUILDER_V2_MAX_TOKENS")
                             or V2_MAX_TOKENS_DEFAULT))
    except ValueError:
        return V2_MAX_TOKENS_DEFAULT


# ─── the prompt (model-portable: plain instructions, no syntax) ──────

_SYSTEM = """You are a master web designer-craftsperson building ONE complete production web page in a single pass. You hold the whole page in mind at once — every decision coherent with every other. You were chosen because one sighted mind beats a pipeline of blind stages.

THE LAW OF THE PAGE is the approved design specification the owner has read and signed. Execute it exactly: its sections, its written copy, its named signature move, its color and font roles. Where the spec is silent, decide with craft in the spec's spirit — never retreat to a generic median.

HARD RULES (a validator checks each; violations cost a repair round):
1. Output ONE complete HTML document: <!DOCTYPE html> through </html>. Inline <style>. At most one <script> (a single IIFE, DOM-only: class toggles, listeners on elements you rendered; the page must stay fully coherent with JS disabled). THE SCRIPT'S ONE NETWORK CALL: the contact-form submit of rule 9 is the only fetch permitted, written with the endpoint url inline as a string literal — fetch("<the given endpoint>", …). A security pass strips the ENTIRE script if it contains any other fetch, XMLHttpRequest, eval, storage, or dynamic import — and with the script go your reveals, lightbox, and filters. Nothing else on the page may touch the network.
2. TRUTH: every fact, number, price, and claim on the page appears in the REAL DATA below. Nothing invented — a stat the data doesn't prove renders as a clearly-marked editable placeholder, never a made-up figure.
3. COVERAGE: every listed image appears (exact url in src); a fixed navigation; a working contact form posting to the given endpoint (method="POST", the given action url, name/email fields at minimum); a footer. Every real service/offering has a home.
4. EXTERNAL REQUESTS: Google Fonts stylesheet links, the provided https image urls, and the one contact-form fetch of rule 9 ONLY. No other external scripts, styles, frames, or calls.
5. EDITABILITY: stamp data-override-target="v2/f1", "v2/f2", … on headings, paragraphs, and captions as you write them (a platform pass guarantees any you miss — stamping well keeps the labels meaningful).
6. MOBILE: a real responsive pass in the same document — media queries so every section holds at 390px. What breaks on a phone fails the whole page. The page must also hold on wide screens (1900px+): content keeps an intentional measure, backgrounds and motifs extend, nothing stretches thin or drifts off-grid.
7. The spec's color hexes and font names are law — write them directly in your CSS (:root custom properties named as the spec names them, then var() references).
8. COPY GRAMMAR (the DASH LAW): never splice a sentence with a dash. No em dashes, no " - " splices in headings, paragraphs, or list copy — rewrite with a period, comma, or colon. A dash may appear only inside a proper title supplied by the data (an artwork or event name).
9. INTERACTION GRAMMAR — controls do what they promise: a gallery of images opens each piece larger on click (a lightbox: element id="lightbox", dimmed backdrop, the artwork with its title, closes on backdrop click, a close button, and Escape); category filters actually filter and an empty result states so in words, never blank space; the contact form intercepts submit and POSTs JSON {name, email, phone, message} via fetch to the given endpoint (the url inline as a string literal — the endpoint reads JSON, so a bare native form post cannot reach it), disables the button while sending, then shows a visible confirmation state in place; every clickable element answers hover AND keyboard focus; anything that opens can be closed.
10. REVEAL SAFETY: if content starts hidden for a scroll reveal, the reveal must be scroll-position driven (on scroll, anything whose top has passed the reveal line becomes visible), so fast scrolling can NEVER leave a section invisible. Never rely on an IntersectionObserver alone. Honor prefers-reduced-motion by showing everything.
11. INVENTORY-SHAPED LAYOUT: compose the gallery/grid to the number of images that actually exist. Two images get a two-image composition; never a grid with holes, never a repeated image as filler.
11b. ART-DIRECTED DROP SLOTS: when the composition WANTS an image the inventory doesn't have (a hero portrait, a third gallery piece), author a placeholder the owner can fill: <div class="sx-drop" data-sx-slot="short_name">…</div> containing ONE line of shot direction in plain words ("You at the chair, mid-cut, warm light" — you are telling them what to photograph). Style: a dashed 1px frame in the accent color at low opacity, the design's crop and position already decided, so a dropped-in photo inherits your intention. Your CSS MUST include `.sx-drop{display:none}` and `body.sx-studio .sx-drop{display:flex;…}` — the public page never shows an empty frame; the owner's Studio reveals them. Never fake an image, never leave a hole: real, or an art-directed drop slot.
12. ALIGNMENT LAW: photographic subjects fill their frames (cover-fit, deliberate crop anchor); edges align to the type they sit beside; nothing floats small inside an oversized border.
13. HEAD + SHARE: a real <title>, a meta description written from the data, and og:title / og:description / og:image (the strongest image url from the data) so a shared link looks intentional.
14. CONNECTED DOORS: the data's CONNECTED SYSTEMS block lists working doors the owner turned on (booking, store) with their exact urls — each appears on the page as a REAL link twice over: in the navigation, and as a devoted moment styled to the spec (a Book action, a shop section). Use the exact url given. Never invent a door the block doesn't carry; never render a dead placeholder for one it does.
15. FILLED SPACE: the hero's off-axis half holds a presence (real work in the light, a ghost word, the signature motif) — never bare ground beside the headline. Gaps between sections carry the page's connective architecture; no featureless band taller than half a viewport. Execution notes: staggered cascades via transition-delay stepped by item index on the same scroll-driven reveal class; sequential fills (steps, thread stations) keyed to scroll position; ghost type is aria-hidden and never traps selection; a marquee is CSS-only, slow, and frozen under prefers-reduced-motion; a cursor-following glow is desktop-only, subtle, transform-based.

CRAFT FLOOR: generous, complete pages beat austere concepts; restraint disciplines color and motion, never content. Light the stage (glow, texture, gradient depth) — never a flat rectangle. One signature moment, executed exactly as the spec draws it. POLISH: a themed ::selection color, :focus-visible states, honest alt text on every image, aspect-ratio reserved on media so nothing jumps while loading, loading="lazy" below the fold.

OUTPUT: the HTML document only. No commentary, no code fences."""


def build_user_prompt(spec_text: str, real_data: str,
                      violations: Optional[List[str]] = None,
                      prior_doc: str = "") -> str:
    """Pure prompt assembly (testable). With violations + prior_doc it
    becomes the ONE surgical repair prompt (Amendment 1: minimal edits,
    never a fresh re-roll)."""
    if violations:
        return "\n".join([
            "SURGICAL REPAIR — your page failed validation on these exact "
            "points. Fix ONLY what each violation requires; every other "
            "byte of the document stays as you wrote it. Do not redesign, "
            "do not rewrite unaffected sections.",
            "",
            "VIOLATIONS:",
            *[f"- {v}" for v in violations[:12]],
            "",
            "THE REAL DATA (the only source of facts):",
            real_data.strip()[:12000],
            "",
            "YOUR DOCUMENT:",
            prior_doc,
            "",
            "Output the corrected complete HTML document only.",
        ])
    return "\n".join([
        "== THE APPROVED SPEC (the law of the page — the owner read and "
        "approved this document) ==",
        spec_text.strip(),
        "",
        "== THE REAL DATA (the only facts you may render; every image url "
        "listed here must appear on the page) ==",
        real_data.strip()[:16000],
        "",
        "Build the complete page now.",
    ])


# ─── real data assembly ──────────────────────────────────────────────

def assemble_real_data(ctx: Dict[str, Any], business_id: str) -> str:
    """Everything true, in one block: business facts, offerings,
    testimonials, contact endpoint + channels, every image url, the
    discovery dossier digest."""
    parts: List[str] = []
    biz = ctx.get("business") or {}
    parts.append(f"BUSINESS: {biz.get('name') or ''} — type: "
                 f"{biz.get('type') or ''}")
    contact = ctx.get("contact") if isinstance(ctx.get("contact"), dict) else {}
    ch = {k: v for k, v in contact.items()
          if isinstance(v, str) and v.strip()}
    if ch:
        parts.append("CONTACT CHANNELS: " + json.dumps(ch, ensure_ascii=False))
    parts.append("CONTACT FORM ENDPOINT (the form's action): "
                 + contact_endpoint(business_id))
    try:
        import atelier
        for mid in ("offerings", "testimonials", "statband", "faq", "store"):
            try:
                data = atelier._section_data(mid, {}, ctx)
            except Exception:
                continue
            if data:
                parts.append(f"[{mid}]\n"
                             + json.dumps(data, ensure_ascii=False)[:3000])
    except Exception as e:
        logger.info(f"[v2] section data skipped: {e}")
    # every image, by url
    imgs: List[str] = []
    slots = (((ctx.get("site") or {}).get("site_config") or {})
             .get("slots") or {})
    for name, rec in sorted(slots.items()):
        if isinstance(rec, dict) and not rec.get("removed") \
                and (rec.get("custom_url") or "").strip():
            imgs.append(f"- {rec['custom_url'].strip()} (owner upload: {name})")
    for g in (ctx.get("gallery") or []):
        if isinstance(g, dict) and (g.get("url") or "").strip():
            note = g.get("alt") or g.get("caption") or ""
            imgs.append(f"- {g['url'].strip()}"
                        + (f" ({note})" if note else ""))
    if imgs:
        parts.append("IMAGES (every one appears on the page, exact urls):\n"
                     + "\n".join(dict.fromkeys(imgs)))
    try:
        import discovery
        dd = (((ctx.get("site") or {}).get("site_config") or {})
              .get("discovery_dossier"))
        digest = discovery.dossier_digest(dd)
        if digest:
            parts.append("DISCOVERY DOSSIER (the owner's confirmed answers):\n"
                         + digest)
    except Exception:
        pass
    block = connected_systems_block(business_id, ctx)
    if block:
        parts.append(block)
    return "\n\n".join(parts)


_CONNECTED_LINE_RE = re.compile(
    r"^- (BOOKING|STORE): ON — .*?(https://\S+)", re.MULTILINE)


def connected_systems_block(business_id: str,
                            ctx: Optional[Dict[str, Any]] = None) -> str:
    """THE WIRED-SITE CONTRACT: the working doors the page MUST carry.
    A door is ON when the platform has it live AND the owner hasn't
    turned it off in the dossier (silence defaults to wired — a working
    system unreachable from the site is the dead-weight rule violated
    at platform scale). Format is law: check_connected parses these
    exact lines."""
    try:
        import offering_profiles
        state = offering_profiles.business_state(business_id)
    except Exception as e:
        logger.info(f"[v2] connected-systems probe skipped: {e}")
        return ""
    caps: Dict[str, Any] = {}
    try:
        dd = ((((ctx or {}).get("site") or {}).get("site_config") or {})
              .get("discovery_dossier")) or {}
        caps = dd.get("capabilities") or {}
    except Exception:
        caps = {}

    def _off(name: str) -> bool:
        leaf = caps.get(name)
        return isinstance(leaf, dict) and \
            str(leaf.get("value")).strip().lower() == "off"

    lines: List[str] = []
    if state.get("booking_enabled") and state.get("booking_url") \
            and not _off("booking"):
        lines.append(f"- BOOKING: ON — every book/schedule action links "
                     f"to {state['booking_url']}")
    if state.get("store_url") and not _off("store") \
            and _store_has_products(ctx):
        lines.append(f"- STORE: ON — the shop moment links to "
                     f"{state['store_url']}")
    if not lines:
        return ""
    return ("CONNECTED SYSTEMS (working doors the owner turned on — "
            "each url below MUST appear on the page as a real link; "
            "never invent a door not listed here):\n" + "\n".join(lines))


def _store_has_products(ctx: Optional[Dict[str, Any]]) -> bool:
    """A store door only counts when something is actually in it — an
    empty shop page linked from the site is its own dead end."""
    try:
        import atelier
        data = atelier._section_data("store", {}, ctx or {})
        return bool(data)
    except Exception:
        return False


def check_connected(html: str, real_data: str) -> List[str]:
    """Deterministic contract check: every ON door's url appears in the
    document. A missing door costs a repair round, exactly like a
    missing image (the coverage law's sibling)."""
    problems: List[str] = []
    for name, url in _CONNECTED_LINE_RE.findall(real_data):
        if url not in html:
            problems.append(
                f"CONNECTED DOOR MISSING: {name} is ON but its url "
                f"({url}) appears nowhere on the page — add it as a "
                "real link in the nav and as a devoted moment.")
    return problems


# ─── mechanical armor (deterministic, zero model calls) ─────────────

_ANNOT_TAG_RE = re.compile(
    r"<(h1|h2|h3|h4|p|li|blockquote|figcaption)(\s[^>]*)?>",
    re.IGNORECASE)


def annotate_editability(html: str) -> Tuple[str, int]:
    """THE ANNOTATOR (Amendment 1): guarantee data-override-target on
    every text-bearing element the model missed. Returns (html, added).

    AUDIT FIX (2026-07-24, flight one): the first version re-serialized
    the WHOLE document through bs4, which lowercases case-sensitive SVG
    attributes (viewBox, preserveAspectRatio) — silently breaking any
    inline-SVG signature move (the spec's DOTS line) before the judge
    ever saw it. Now a surgical regex injects the attribute into the
    matched opening tags ONLY — every other byte of the document is
    untouched."""
    try:
        existing = set(re.findall(r'data-override-target\s*=\s*["\']([^"\']+)',
                                  html))
        state = {"n": 0, "counter": 0}

        def _inject(m: re.Match) -> str:
            tag_open = m.group(0)
            if "data-override-target" in tag_open:
                return tag_open
            state["counter"] += 1
            target = f"v2/auto_{state['counter']}"
            while target in existing:
                state["counter"] += 1
                target = f"v2/auto_{state['counter']}"
            existing.add(target)
            state["n"] += 1
            return (tag_open[:-1]
                    + f' data-override-target="{target}">')

        out = _ANNOT_TAG_RE.sub(_inject, html)
        return out, state["n"]
    except Exception as e:
        logger.warning(f"[v2] annotator skipped: {e}")
        return html, 0


def armor_scripts(html: str,
                  allowed_fetch: str = "") -> Tuple[str, List[str]]:
    """Drop any <script> containing a banned call; report what fell.

    allowed_fetch: the ONE url a fetch( may target — the platform's own
    contact-submit endpoint (a JSON endpoint; the form is dead without
    it). Only the inline string-literal form is permitted, so the probe
    can verify the target without executing anything: fetch("<url>" or
    fetch('<url>'. Any other fetch — variable, template, other url —
    still drops the whole script."""
    dropped: List[str] = []

    def _check(m: re.Match) -> str:
        body = m.group(1) or ""
        probe = body
        if allowed_fetch:
            for quote in ('"', "'"):
                probe = probe.replace(
                    f"fetch({quote}{allowed_fetch}{quote}", "")
        for ban in _JS_BANNED:
            if ban in probe:
                dropped.append(ban)
                return ""
        return m.group(0)

    out = re.sub(r"<script[^>]*>(.*?)</script>", _check, html,
                 flags=re.DOTALL | re.IGNORECASE)
    return out, dropped


def armor_violations(dropped: List[str], endpoint: str) -> List[str]:
    """A dropped script is a LAW violation, not a silent event — the
    page's reveal states orphan into permanent invisibility when the
    runtime falls (the 2026-07-25 blank-page bug). The violation carries
    the reason so the surgical repair fixes the cause, not a symptom."""
    return [
        f'SCRIPT REMOVED BY THE SECURITY ARMOR: your <script> used "{ban}", '
        "which is banned, so the ENTIRE script was stripped — the page "
        "shipped with no JavaScript, and every hidden-for-reveal element "
        "stays invisible forever. Rewrite the single script without it. "
        "The ONLY permitted network call is the contact form submit: "
        f'fetch("{endpoint}", …) with the url written inline exactly as '
        "that string literal. Everything else must be DOM-only."
        for ban in dropped
    ]


def armor_external(html: str) -> Tuple[str, List[str]]:
    """Strip non-whitelisted external <link>/<iframe>/external <script
    src>. Google Fonts links survive; https images are untouched (img
    tags aren't requests we initiate logic through)."""
    stripped: List[str] = []

    def _link(m: re.Match) -> str:
        tag = m.group(0)
        href = (re.search(r'href\s*=\s*["\']([^"\']+)', tag) or [None, ""])[1]
        if any(h in href for h in _ALLOWED_LINK_HOSTS) or href.startswith("#") \
                or not href.startswith("http"):
            return tag
        stripped.append(href[:80])
        return ""

    out = re.sub(r"<link\b[^>]*>", _link, html, flags=re.IGNORECASE)

    def _script_src(m: re.Match) -> str:
        stripped.append("external script")
        return ""
    out = re.sub(r"<script\b[^>]*\bsrc\s*=[^>]*>\s*</script>", _script_src,
                 out, flags=re.IGNORECASE)

    def _iframe(m: re.Match) -> str:
        stripped.append("iframe")
        return ""
    out = re.sub(r"<iframe\b.*?</iframe>", _iframe, out,
                 flags=re.DOTALL | re.IGNORECASE)
    return out, stripped


# ─── authorship checks (truth + coverage) ────────────────────────────

def _visible_text(html: str) -> str:
    t = re.sub(r"<script.*?</script>|<style.*?</style>", " ", html,
               flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r"<[^>]+>", " ", t)


def check_truth(html: str, real_data: str) -> List[str]:
    """Every 3+ digit run in visible text must appear in the data (the
    fact-trace, page-wide) — with the current year exempt (a copyright
    line is a date, not a claim)."""
    from datetime import datetime, timezone
    data_runs = set(_DIGIT_RUN_RE.findall(real_data))
    year = str(datetime.now(timezone.utc).year)
    problems: List[str] = []
    for run in dict.fromkeys(_DIGIT_RUN_RE.findall(_visible_text(html))):
        if run == year:
            continue
        if run not in data_runs:
            problems.append(f"number '{run}' on the page but not in the "
                            f"REAL DATA — real or removed")
        if len(problems) >= 6:
            break
    return problems


def check_coverage(html: str, real_data: str) -> List[str]:
    problems: List[str] = []
    for m in re.finditer(r"^- (https://\S+)", real_data, re.MULTILINE):
        url = m.group(1)
        if url not in html:
            problems.append(f"required image missing: {url}")
    if not re.search(r"<nav\b", html, re.IGNORECASE):
        problems.append("no <nav> — a fixed navigation is required")
    endpoint = re.search(r"CONTACT FORM ENDPOINT[^\n]*:\s*(\S+)", real_data)
    if endpoint and endpoint.group(1) not in html:
        problems.append(f"contact form must post to {endpoint.group(1)}")
    if not re.search(r"<form\b", html, re.IGNORECASE):
        problems.append("no <form> — the working inquiry form is required")
    if not re.search(r"<footer\b", html, re.IGNORECASE):
        problems.append("no <footer>")
    return problems[:12]


_COPY_TAG_RE = re.compile(
    r"<(h1|h2|h3|h4|p|li|blockquote)(?:\s[^>]*)?>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL)


def check_grammar(html: str) -> List[str]:
    """THE DASH LAW (Kevin's review, 2026-07-25): dash-spliced sentences
    are a defect, not a style. Em dashes (and spaced hyphen splices) in
    headings/paragraph/list copy are flagged with the exact sentence so
    the repair is surgical. figcaption is exempt — artwork/event titles
    carry dashes as titles, not sentences."""
    problems: List[str] = []
    for m in _COPY_TAG_RE.finditer(html):
        text = re.sub(r"<[^>]+>", " ", m.group(2))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if "—" in text or re.search(r"\w\s[-–]\s\w", text):
            problems.append(
                "DASH LAW: copy uses a dash splice — rewrite with a "
                f"period, comma, or colon: \"{text[:90]}\"")
        if len(problems) >= 5:
            break
    return problems


def check_head(html: str) -> List[str]:
    """HEAD + SHARE: a shared link must look intentional."""
    problems: List[str] = []
    title = re.search(r"<title[^>]*>([^<]*)</title>", html, re.IGNORECASE)
    if not title or not title.group(1).strip():
        problems.append("no <title> — a real page title is required")
    if not re.search(r'<meta\s[^>]*name=["\']description["\']', html,
                     re.IGNORECASE):
        problems.append("no meta description — write one from the data")
    if not re.search(r'<meta\s[^>]*property=["\']og:image["\']', html,
                     re.IGNORECASE):
        problems.append("no og:image — promote the strongest image url "
                        "so a shared link shows the work")
    return problems


def check_interactions(html: str) -> List[str]:
    """INTERACTION GRAMMAR, the deterministically checkable half:
    a page carrying a real gallery (5+ content images) must let each
    piece be seen closer (id=\"lightbox\" or a <dialog>); hidden-until-
    reveal content driven by IntersectionObserver alone is the reveal-
    skip bug class — a scroll fallback is required."""
    problems: List[str] = []
    imgs = len(re.findall(r"<img\b", html, re.IGNORECASE))
    if imgs >= 5 and not (
            re.search(r'id=["\']lightbox["\']', html, re.IGNORECASE)
            or re.search(r"<dialog\b", html, re.IGNORECASE)):
        problems.append(
            "gallery present but no way to see a piece closer — add a "
            'lightbox (id="lightbox": click a gallery image to open it '
            "large with its title; closes on backdrop click, a close "
            "button, and Escape)")
    if "IntersectionObserver" in html and "opacity:0" in html.replace(" ", "") \
            and not re.search(r"addEventListener\(\s*['\"]scroll", html):
        problems.append(
            "REVEAL SAFETY: hidden-for-reveal content is driven by an "
            "IntersectionObserver with no scroll fallback — fast "
            "scrolling can skip sections forever. Reveal on scroll "
            "position (anything whose top passed the reveal line becomes "
            "visible), or drop the hidden state.")
    has_runtime = bool(re.search(r"<script[^>]*>\s*\S", html,
                                 re.IGNORECASE | re.DOTALL))
    if not has_runtime and "opacity:0" in html.replace(" ", ""):
        problems.append(
            "REVEAL SAFETY: the stylesheet sets reveal states to "
            "opacity:0 but no script exists on the page to add the "
            "shown class, so those sections never appear. Include the "
            "runtime script, or author the page with every section "
            "visible by default.")
    return problems


def _parse_doc(raw: str) -> Optional[str]:
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw).strip()
    i = text.lower().find("<!doctype")
    if i < 0:
        i = text.lower().find("<html")
    if i < 0:
        return None
    j = text.lower().rfind("</html>")
    if j < 0:
        return None
    doc = text[i:j + len("</html>")]
    return doc if len(doc.encode()) <= DOC_MAX_BYTES else None


# ─── THE EYES (Director's Cut Arc 2 — the vision loop) ──────────────
# The builder looks at its own rendered work BEFORE anyone else does:
# screenshots taken the way a visitor would see them (scrolled through,
# not teleported), measured against the spec and the standing checklist
# of non-negotiables, then ONE surgical repair. The loop is the last
# line of defense, never the teacher — everything teachable lives in
# the system prompt and the deterministic checks above.

VISION_WALK_WIDTHS = (390, 1440)     # full walk: top / middle / bottom
VISION_WIDE_WIDTH = 2560             # ultrawide: above the fold only


def eyes_enabled() -> bool:
    return (os.environ.get("SITE_V2_VISION_LOOP") or "on").strip().lower() \
        in ("on", "1", "true", "yes")


def _screenshot_walk(html: str) -> Optional[List[Tuple[str, bytes]]]:
    """Render and WALK the page like a visitor: for each width, scroll
    top → middle → bottom (firing the page's own scroll handlers, so a
    reveal-skip bug shows up as a blank section) and shoot each stop.
    Plus one ultrawide above-the-fold shot. Returns [(label, jpeg)] or
    None when playwright is unavailable."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        logger.info("[v2:eyes] playwright not installed — vision loop "
                    "skipped")
        return None
    shots: List[Tuple[str, bytes]] = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for width in VISION_WALK_WIDTHS:
                    page = browser.new_page(
                        viewport={"width": width, "height": 900})
                    page.set_content(html, wait_until="networkidle",
                                     timeout=25000)
                    total = page.evaluate(
                        "document.documentElement.scrollHeight")
                    stops = [0, max(0, total // 2 - 450),
                             max(0, total - 900)]
                    names = ("top", "middle", "bottom")
                    for name, y in zip(names, stops):
                        page.evaluate(f"window.scrollTo(0, {y})")
                        page.wait_for_timeout(700)   # reveals settle
                        shots.append((f"{width}px {name}",
                                      page.screenshot(type="jpeg",
                                                      quality=55)))
                    page.close()
                page = browser.new_page(
                    viewport={"width": VISION_WIDE_WIDTH, "height": 1000})
                page.set_content(html, wait_until="networkidle",
                                 timeout=25000)
                page.wait_for_timeout(500)
                shots.append((f"{VISION_WIDE_WIDTH}px top (ultrawide)",
                              page.screenshot(type="jpeg", quality=55)))
                page.close()
            finally:
                browser.close()
    except Exception as e:
        logger.warning(f"[v2:eyes] screenshot walk failed: "
                       f"{type(e).__name__}: {e}")
        return None
    return shots


_INSPECTOR = """You are the builder of this page inspecting your own rendered work before it ships. You are looking for DEFECTS a paying owner would see, not restating taste. Screenshots show the page as a visitor scrolls it, at phone and desktop widths plus one ultrawide look.

Measure against THE CHECKLIST (each item is a law, not a suggestion):
- ALIGNMENT: photographic subjects fill their frames; nothing floats small inside an oversized border; edges line up with neighboring type; nothing overlaps, collides, or gets cut off.
- COMPLETENESS: no blank/empty sections at any scroll stop (a section that never appeared = the reveal-skip bug). No grid holes, no dead space where content should be.
- FILLED SPACE: the hero's off-axis half holds a designed presence, not bare ground beside the headline; no scroll stop shows a featureless band taller than half the viewport between sections.
- CAPTION TRUTH: every caption/title visibly matches the artwork it sits under.
- COPY GRAMMAR: no dash-spliced sentences visible in headings or body copy.
- LEGIBILITY: text readable against its ground at every width; small type not lost.
- MOBILE (390px): nothing crowded, cropped, or broken; rhythm holds.
- ULTRAWIDE: the page keeps an intentional measure; nothing stretches thin or drifts.
- SPEC FIDELITY: the named signature move is visible and executed; the spec's palette and type are what actually rendered.

Output STRICT JSON only:
{"verdict":"ship"|"repair","violations":[{"where":"<section/breakpoint>","what":"<the defect, concrete>","fix":"<the minimal surgical fix>"}]}
Rules: at most 6 violations, ranked by owner-visible damage. Cosmetic taste differences are NOT violations. An empty violations list means verdict "ship". JSON only, no commentary."""


def _parse_inspector(raw: str) -> Optional[Dict[str, Any]]:
    """Parse the inspector's strict-JSON verdict; tolerant of fences."""
    if not raw:
        return None
    text = _FENCE_RE.sub("", raw).strip()
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        return None
    try:
        out = json.loads(text[i:j + 1])
    except Exception:
        return None
    if not isinstance(out, dict) or out.get("verdict") not in ("ship",
                                                               "repair"):
        return None
    vs = out.get("violations")
    out["violations"] = [v for v in (vs if isinstance(vs, list) else [])
                         if isinstance(v, dict) and v.get("what")][:6]
    if not out["violations"]:
        out["verdict"] = "ship"
    return out


def inspect_with_eyes(doc: str, spec_text: str,
                      business_id: str) -> Optional[Dict[str, Any]]:
    """Screenshot walk → one vision call → verdict dict, or None when
    the eyes can't run (no playwright / no key / unparseable) — never
    fatal, never a second look."""
    shots = _screenshot_walk(doc)
    if not shots:
        return None
    try:
        import base64
        from anthropic import Anthropic
        import model_ladder
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        content: List[Dict[str, Any]] = [
            {"type": "text", "text": "THE APPROVED SPEC (what the page "
             "promised):\n" + (spec_text or "").strip()[:2400]}]
        for label, shot in shots:
            content.append({"type": "text", "text": f"View — {label}:"})
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg",
                "data": base64.b64encode(shot).decode()}})
        content.append({"type": "text",
                        "text": "Inspect per the checklist. JSON only."})
        client = llm_call.sdk_client(key=key, timeout=180.0, max_retries=1)

        def _do(model: str, max_tokens: int, timeout: float):
            return client.messages.create(
                model=model, max_tokens=max_tokens, system=_INSPECTOR,
                messages=[{"role": "user", "content": content}],
                timeout=max(timeout, 180.0),
                **model_ladder.sampling_kwargs(model, 0.2))

        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_model(), task="builder_v2_eyes",
            business_id=business_id, max_tokens=1200)
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/builder-v2-eyes",
                model=used_model or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type="builder_v2_eyes")
        except Exception:
            pass
        raw = "".join(b.text for b in msg.content
                      if getattr(b, "type", None) == "text")
        return _parse_inspector(raw)
    except Exception as e:
        logger.warning(f"[v2:eyes] inspection failed (non-fatal): "
                       f"{type(e).__name__}: {e}")
        return None


# ─── the run ─────────────────────────────────────────────────────────

def _call(system: str, user: str, business_id: str) -> Optional[str]:
    try:
        from anthropic import Anthropic
        import model_ladder
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            return None
        # Flight one lesson: the full-page pass is ONE giant generation;
        # a tight timeout forced the ladder's reduced-tokens retry and
        # shipped a SQUEEZED page ("headline feels compressed"). Give
        # the first attempt real room — a slow masterpiece beats a fast
        # miniature.
        client = llm_call.sdk_client(key=key, timeout=900.0, max_retries=1)

        def _do(model: str, max_tokens: int, timeout: float):
            return client.messages.create(
                model=model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}],
                timeout=max(timeout, 900.0),
                **model_ladder.sampling_kwargs(model, V2_TEMPERATURE))

        msg, used_model = model_ladder.call_with_ladder(
            _do, model=_model(), task="builder_v2",
            business_id=business_id, max_tokens=_max_tokens())
        try:
            from api_usage_logger import log_api_usage_sync
            u = getattr(msg, "usage", None)
            log_api_usage_sync(
                endpoint="/composer/builder-v2", model=used_model or "",
                input_tokens=getattr(u, "input_tokens", 0) or 0,
                output_tokens=getattr(u, "output_tokens", 0) or 0,
                business_id=business_id, task_type="builder_v2")
        except Exception:
            pass
        return "".join(b.text for b in msg.content
                       if getattr(b, "type", None) == "text")
    except Exception as e:
        logger.error(f"[v2] build call failed on every rung: "
                     f"{type(e).__name__}: {e}")
        return None


def run_builder_v2(spec_text: str, ctx: Dict[str, Any], business_id: str,
                   progress_cb=None) -> Dict[str, Any]:
    """ONE call → armor → (one scoped repair) → document or None.
    None = the old path takes over (and still wears the spec's tokens
    via the bridge). The report always returns — loud failures."""
    report: Dict[str, Any] = {"engine": "builder_v2", "model": _model(),
                              "mechanical": {}, "violations": [],
                              "repaired": False, "fallbacks": []}

    def _progress(pct: int, stage: str):
        try:
            if progress_cb:
                progress_cb(pct, stage)
        except Exception:
            pass

    real_data = assemble_real_data(ctx, business_id)
    _progress(48, "One mind builds the whole page")
    raw = _call(_SYSTEM, build_user_prompt(spec_text, real_data), business_id)
    doc = _parse_doc(raw or "")
    if not doc:
        report["fallbacks"].append({"stage": "author",
                                    "detail": "no parseable document"})
        return {"html": None, "report": report}

    endpoint = contact_endpoint(business_id)

    def _mechanical(d: str) -> str:
        d, dropped = armor_scripts(d, allowed_fetch=endpoint)
        d, stripped = armor_external(d)
        d, added = annotate_editability(d)
        report["mechanical"] = {"scripts_dropped": dropped,
                                "externals_stripped": stripped,
                                "override_targets_added": added}
        return d

    def _laws(d: str) -> List[str]:
        # armor_violations reads the drops _mechanical just recorded for
        # this same doc — a dropped script must fail the law gate loudly
        # (silently shipping it is the 2026-07-25 blank-sections bug).
        return (check_truth(d, real_data) + check_coverage(d, real_data)
                + check_grammar(d) + check_head(d) + check_interactions(d)
                + check_connected(d, real_data)
                + armor_violations(
                    report["mechanical"].get("scripts_dropped") or [],
                    endpoint))

    doc = _mechanical(doc)
    violations = _laws(doc)
    if violations:
        report["violations"] = violations
        _progress(56, "Surgical repair")
        raw2 = _call(_SYSTEM,
                     build_user_prompt(spec_text, real_data,
                                       violations=violations, prior_doc=doc),
                     business_id)
        doc2 = _parse_doc(raw2 or "")
        if doc2:
            doc2 = _mechanical(doc2)
            v2 = _laws(doc2)
            if not v2:
                report["repaired"] = True
                doc = doc2
            else:
                report["fallbacks"].append({
                    "stage": "repair",
                    "detail": "still failing after one repair: "
                              + "; ".join(v2[:4])})
                return {"html": None, "report": report}
        else:
            report["fallbacks"].append({"stage": "repair",
                                        "detail": "repair unparseable"})
            return {"html": None, "report": report}

    # THE EYES (Arc 2): the builder looks at its own rendered work and
    # gets ONE surgical pass to fix what it sees. Quality violations are
    # never fatal — if the eyes can't run, or the vision repair breaks a
    # law, the law-passing document ships and the report says so.
    report["vision"] = {"ran": False, "verdict": None, "violations": []}
    if eyes_enabled():
        _progress(62, "The builder inspects its own work")
        verdict = inspect_with_eyes(doc, spec_text, business_id)
        if verdict:
            report["vision"]["ran"] = True
            report["vision"]["verdict"] = verdict.get("verdict")
            report["vision"]["violations"] = verdict.get("violations", [])
            if verdict.get("verdict") == "repair":
                _progress(68, "Vision repair: fixing what the eyes found")
                seen = [f"SEEN IN THE RENDER ({v.get('where', 'page')}): "
                        f"{v.get('what')} — FIX: {v.get('fix', 'minimal edit')}"
                        for v in verdict["violations"]]
                raw3 = _call(_SYSTEM,
                             build_user_prompt(spec_text, real_data,
                                               violations=seen,
                                               prior_doc=doc),
                             business_id)
                doc3 = _parse_doc(raw3 or "")
                if doc3:
                    doc3 = _mechanical(doc3)
                    if not _laws(doc3):
                        doc = doc3
                        report["vision"]["repaired"] = True
                    else:
                        report["fallbacks"].append({
                            "stage": "vision-repair",
                            "detail": "vision repair broke a law — "
                                      "keeping the law-passing document"})
                else:
                    report["fallbacks"].append({
                        "stage": "vision-repair",
                        "detail": "vision repair unparseable — keeping "
                                  "the law-passing document"})
    return {"html": doc, "report": report}
