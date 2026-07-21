# canvas.py
# ─────────────────────────────────────────────────────────────────────
# The Canvas Pass (Phase 1, docs/CANVAS_PASS.md) — whole-page authoring
# under platform contracts.
#
# After the spec/plan stage, the canvas planner splits the page into:
#   (a) data-bearing sections PRE-RENDERED by the deterministic module
#       registry into immutable blocks (truth — the model can position
#       their <!--SX_BLOCK:{module}--> tokens but never rewrite a byte);
#   (b) open creative sections authored directly as HTML/CSS by the LLM
#       in 2-3 chunked calls under the canvas contract (§4): tokens only
#       --sx-*, platform anatomy preserved, one ≤6KB JS IIFE (§6).
#
# A page-wide fact-checker (§7) validates the assembled page before it
# joins today's flow at slot population: fact trace (the atelier DATA
# FIDELITY digit-run check, page-wide over authored sections), immutable
# block byte-identity, the substance floor, and the anatomy census. One
# corrective retry, then the module path (the §9 degradation ladder).
#
# Gated on SITE_CANVAS=on (default OFF — canvas_enabled()). Modules and
# the atelier are untouched: they remain the floor the canvas falls
# back to (§12), and their contract/armor are reused wholesale here.
# ─────────────────────────────────────────────────────────────────────

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import atelier
import atelier_validator
import canvas_brief

logger = logging.getLogger("canvas")

CANVAS_MAX_TOKENS = 10000     # chunk output ceiling (§3.4: 8-12K band)
CANVAS_TEMPERATURE = 0.8      # creative latitude, same as the atelier
HTML_MAX_BYTES = 18 * 1024    # §4.8 — atelier's 14/10 scaled for chunks
CSS_MAX_BYTES = 14 * 1024
JS_MAX_BYTES = 6 * 1024       # §6 — the one page script
_CALL_TIMEOUT_S = 120.0       # constructor default; ladder overrides

_SECTION_TAG_RE = re.compile(r"<section\b[\s\S]*?</section>", re.IGNORECASE)
_DIGIT_RUN_RE = re.compile(r"\d+")
_WORD_RE = re.compile(r"[A-Za-z0-9][\w'’\-]*")


def canvas_enabled() -> bool:
    """Env gate, default OFF (spec §11: SITE_CANVAS=on enables, first
    for the KMJ business). When unset the deterministic module+atelier
    path runs byte-identically."""
    return (os.environ.get("SITE_CANVAS") or "").strip().lower() in (
        "on", "1", "true", "yes")


def _model() -> str:
    return (os.environ.get("CANVAS_MODEL") or "").strip() or atelier._model()


def _max_tokens() -> int:
    try:
        return max(1000, int(os.environ.get("CANVAS_MAX_TOKENS")
                               or CANVAS_MAX_TOKENS))
    except ValueError:
        return CANVAS_MAX_TOKENS


def _floor_words() -> int:
    try:
        return max(0, int(os.environ.get("CANVAS_FLOOR_WORDS") or 650))
    except ValueError:
        return 650


def _keyframe_cap() -> int:
    try:
        return max(1, int(os.environ.get("CANVAS_KEYFRAME_CAP") or 8))
    except ValueError:
        return 8


def _report(cb, pct: int, stage: str) -> None:
    """Fail-soft progress ping (the atelier's twin — a cb error must
    never break a compose)."""
    if cb is None:
        return
    try:
        cb(pct, stage)
    except Exception:
        pass


# ─── The plan (§3.2, deterministic) ─────────────────────────────────

# §10.2 — marquee owner-wiring: the loud motion moment the DRO calls
# for (owner loud_where=motion, or a marquee-like signature_move) makes
# the values marquee selectable by the PLAN, not only by the ceremony
# pass. Real tone words + non-stilled motion required, same discipline
# as the ceremony pass (4+ words, never stilled, never before contact).
_MARQUEE_MIN_WORDS = 4
_MARQUEE_SIG_WORDS = ("marquee", "ribbon", "ticker", "scroll")


def _wire_marquee(plan: Dict[str, Any], ctx: Dict[str, Any],
                  dro: Optional[Dict[str, Any]]) -> bool:
    """Insert one deterministic marquee interstitial (block role) when
    the DRO calls for the loud motion moment and none exists. Returns
    True when wired. Never invents words — the brand's real tone words
    only."""
    d = (dro or {}).get("decisions") or {}
    loud = str(d.get("_owner_loud_where") or "").strip().lower()
    sig = str((d.get("motion") or {}).get("signature_move") or "").strip().lower()
    if loud != "motion" and not any(w in sig for w in _MARQUEE_SIG_WORDS):
        return False
    secs = plan["sections"]
    if any(s["module"] == "interstitial"
           and str(s.get("variant") or "") == "marquee" for s in secs):
        return False
    words = [w[:1].upper() + w[1:] for w in canvas_brief._tone_words(ctx)]
    if len(words) < _MARQUEE_MIN_WORDS:
        return False
    if (ctx.get("dna") or {}).get("motion", "standard") in ("subtle", "entrance"):
        return False
    seam = {"module": "interstitial", "variant": "marquee",
            "content": {"words": " • ".join(words)},
            "role": "block", "index": -1, "wired": True}
    # placement: after the hero region (never first), never directly
    # before the contact exit (the ceremony pass's gap rule).
    pos = 2 if len(secs) >= 4 else max(1, len(secs) - 1)
    if pos < len(secs) and secs[pos]["module"] == "contact":
        pos = max(1, pos - 1)
    secs.insert(pos, seam)
    for i, s in enumerate(secs):
        s["index"] = i
    logger.info(f"[canvas] marquee wired by the plan (loud_where={loud or 'n/a'},"
                f" signature_move={'set' if sig else 'unset'})")
    return True


def canvas_plan(spec: List[Dict[str, Any]], ctx: Dict[str, Any],
                dro: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Section order + the authored-vs-block split (§3.2). Pure
    deterministic; _ensure_connections guarantees upstream mean every
    data-required block is in the spec regardless of any model."""
    sections: List[Dict[str, Any]] = []
    for i, sec in enumerate(spec or []):
        mid = str(sec.get("module") or "")
        if not mid:
            continue
        variant = str(sec.get("variant") or "")
        role = canvas_brief.section_role(mid, variant, ctx)
        entry: Dict[str, Any] = {"index": i, "module": mid, "variant": variant,
                                 "content": sec.get("content") or {},
                                 "role": role}
        if role == "authored":
            entry["uid"] = uuid4().hex[:8]
        sections.append(entry)
    for i, s in enumerate(sections):
        s["index"] = i
    plan: Dict[str, Any] = {"sections": sections}
    plan["marquee_wired"] = _wire_marquee(plan, ctx, dro)
    return plan


# ─── Pre-rendered blocks (§3.3 — truth, immutable) ──────────────────

def prerender_data_sections(plan: Dict[str, Any],
                            ctx: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """Render every block section through the existing module registry.
    Returns {plan_index: {module, variant, html, css, token}}. A module
    that renders empty (no real rows — the registry's self-drop rule)
    drops its section from the plan, exactly like render_page. Token
    form: <!--SX_BLOCK:{module}--> (a ':k' suffix disambiguates a
    pathological repeat of the same block module)."""
    import site_modules

    blocks: Dict[int, Dict[str, Any]] = {}
    occ: Dict[str, int] = {}
    kept: List[Dict[str, Any]] = []
    for s in plan["sections"]:
        if s["role"] != "block":
            kept.append(s)
            continue
        mid = s["module"]
        mspec = site_modules.MODULES.get(mid)
        if mspec is None:
            logger.info(f"[canvas] unknown module '{mid}' dropped")
            continue
        variant = s["variant"] if s["variant"] in mspec["variants"] \
            else mspec["variants"][0]
        try:
            html, css = mspec["render"](variant, s.get("content") or {}, ctx)
        except Exception as e:
            logger.warning(f"[canvas] block render crashed for {mid} "
                           f"(dropped): {type(e).__name__}: {e}")
            html, css = "", ""
        if not html:
            continue
        k = occ.get(mid, 0)
        occ[mid] = k + 1
        token = f"<!--SX_BLOCK:{mid}-->" if k == 0 else f"<!--SX_BLOCK:{mid}:{k}-->"
        s["variant"] = variant
        s["token"] = token
        blocks[s["index"]] = {"module": mid, "variant": variant,
                              "html": html, "css": css, "token": token}
        kept.append(s)
    plan["sections"] = kept
    return blocks


# ─── Chunking (§3.4: 2-3 calls, consecutive runs) ───────────────────

def _split_even(items: List[int], k: int) -> List[List[int]]:
    k = max(1, min(k, len(items)))
    base, extra = divmod(len(items), k)
    out, i = [], 0
    for g in range(k):
        n = base + (1 if g < extra else 0)
        out.append(items[i:i + n])
        i += n
    return out


def chunk_spans(plan: Dict[str, Any]) -> List[List[Dict[str, Any]]]:
    """Group the plan into 1-3 chunk spans: each span is a complete run
    of consecutive sections holding ≥1 authored section plus the block
    tokens that sit between them. 1 chunk for ≤2 authored sections,
    2 for ≤4, else 3 (the §3.4 2-3-call budget)."""
    sections = plan["sections"]
    authored_idx = [i for i, s in enumerate(sections)
                    if s["role"] == "authored"]
    if not authored_idx:
        return []
    n = len(authored_idx)
    k = 1 if n <= 2 else (2 if n <= 4 else 3)
    groups = _split_even(authored_idx, k)
    spans: List[List[Dict[str, Any]]] = []
    prev = 0
    for gi, g in enumerate(groups):
        end = (g[-1] + 1) if gi < len(groups) - 1 else len(sections)
        spans.append(sections[prev:end])
        prev = end
    return spans


# ─── LLM plumbing (the atelier idiom, canvas task family) ───────────

def _call_llm(system: str, user: str, business_id: str) -> Optional[str]:
    """One canvas chunk call under the model ladder (Site Arc 12):
    family-scaled timeout (canvas task: 120/240s), loud+breadcrumbed
    sonnet fallback on a model-identity error, reduced-tokens retry on
    a timeout. Returns raw text or None — a failed chunk degrades to
    module sections, never silently."""
    import model_ladder
    import site_llm

    client = None
    if site_llm.provider() != "moonshot":
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            logger.info("[canvas] no ANTHROPIC_API_KEY — skipping authoring")
            return None
        from anthropic import Anthropic
        client = Anthropic(api_key=key, timeout=_CALL_TIMEOUT_S, max_retries=1)
    logger.info(f"[canvas] authoring with model={_model()} for "
                f"{(business_id or 'unknown')[:8]}")

    def _do(model: str, max_tokens: int, timeout: float):
        return client.messages.create(
            model=model, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user}],
            timeout=timeout,
            **model_ladder.sampling_kwargs(model, CANVAS_TEMPERATURE))

    try:
        if site_llm.provider() == "moonshot":
            msg = site_llm.create_message(
                model=_model(), max_tokens=_max_tokens(),
                temperature=CANVAS_TEMPERATURE, system=system,
                user_content=user, timeout=90.0, task="canvas")
            used_model = getattr(msg, "model", "moonshot")
        else:
            msg, used_model = model_ladder.call_with_ladder(
                _do, model=_model(), task="canvas",
                business_id=business_id or "", max_tokens=_max_tokens())
    except Exception as e:
        logger.error(f"[canvas] LLM call failed on EVERY ladder rung for "
                     f"{(business_id or 'unknown')[:8]} "
                     f"(model={_model()}): {type(e).__name__}: {e}")
        model_ladder.record_model_fallback(
            business_id or "", task="canvas", from_model=_model(),
            to_model=None, reason=f"{type(e).__name__}: {e}")
        return None
    try:
        from api_usage_logger import log_api_usage_sync
        u = getattr(msg, "usage", None)
        log_api_usage_sync(
            endpoint="/composer/canvas", model=used_model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            business_id=business_id, task_type="canvas")
    except Exception:
        pass
    return "".join(b.text for b in msg.content
                   if getattr(b, "type", None) == "text")


# ─── The prompt (§3.4 + §4) ──────────────────────────────────────────

from design_doctrine import DOCTRINE as _DOCTRINE, CREATIVE_CONTRACT as _CONTRACT

_SYSTEM_PROMPT = _DOCTRINE + "\n\n" + _CONTRACT + "\n\n" + """You are a senior creative director and master frontend craftsperson working in a design atelier. You art-direct the CREATIVE sections of a production website page — not template slots, a composition — around the page's data sections, which the platform has ALREADY rendered as immutable truth blocks. You position those blocks (their tokens sit in your output); you never rewrite a byte of them.

The platform owns the page shell, the design tokens, the fonts, the header, and every data section. Your sections must sit inside that system flawlessly while feeling unmistakably art-directed. The difference between great and mediocre is specificity: great design encodes THIS business's actual character; mediocre design fills a layout with its data. The canvas brief below is the law of the page: it carries the rationale, the brand, the section plan, the interactions budget, and the do/don't rules.

WHAT GREAT LOOKS LIKE (the same craft bar as the atelier):
- A display headline anchored where the visitor's eyes land, exactly one accent-colored italic word carrying the emotional core.
- Editorial confidence: numbered offerings, hairline rules, right-aligned prices — never three cards with stock icons.
- A full-bleed color-blocked band on the authority ground as punctuation between chapters — braver than any gradient.
- Micro-caps (9-11px, 0.18-0.34em tracking) carrying every eyebrow, label, price and button — the whisper that makes the display monumental.
- Designed silence between chapters; sub-perceptual ornaments (0.04-0.08 opacity) the eye discovers on the second look.
- ONE signature interaction, owned and polished (a values marquee, a statement moment) — functional furniture (filter tabs that actually filter, a modal worth opening, an accordion) may ride along inside the JS budget, but never upstages the signature.

WHAT MEDIOCRE LOOKS LIKE (never do these):
- Centered "Welcome to [Business]" + generic value prop + "Get Started".
- Copy that could belong to any business in the category; caption-only sections; filler paragraphs.
- Motion spent on entrances instead of the signature moment.

You never invent facts, prices, testimonials, stats or credentials. You render ONLY the data you are given, in the concept's voice — the data sections are pre-rendered truth, and the fact-checker traces every number on the page back to the business data."""


def _canvas_contract(span: List[Dict[str, Any]], is_final: bool,
                     kf_budget: int) -> str:
    """The canvas HARD OUTPUT CONTRACT (§4) — the atelier's 11 clauses
    with the canvas deltas (block tokens, interactions, substance floor,
    chunk size caps)."""
    authored = [s for s in span if s["role"] == "authored"]
    uid_list = ", ".join(f"atl-{s['uid']} ({s['module']})" for s in authored)
    js_request = (
        " If your interaction needs JS, output it ONLY in the <!--JS--> part: "
        "ONE IIFE ≤ 6KB, DOM-only (class toggling, attribute flips, "
        "IntersectionObserver, addEventListener on elements YOU rendered). "
        "BANNED: eval, new Function, fetch, XMLHttpRequest, import, WebSocket, "
        "document.write, localStorage/sessionStorage, any http literal. The "
        "page MUST remain fully coherent with JS disabled (filters show "
        "everything, modals read inline)."
        if is_final else
        " Its JS (if any) ships with the final chunk — do not emit script.")
    js_format = ("\n<!--JS-->\n(function(){ … })();" if is_final else "")
    return f"""HARD OUTPUT CONTRACT — violations are rejected by a validator:
1. Exactly {len(authored)} root <section> element(s) — one per authored section: {uid_list}. Each root carries its own atl-uid class (on the root ONLY) and its stable id. Block tokens (<!--SX_BLOCK:…-->) sit BETWEEN sections at top level, each exactly once, never nested inside a section, never altered.
2. Every CSS selector is prefixed with the section's own .atl-uid; @keyframes names start with the same atl-uid. No bare element/class/#id selectors; @media allowed.
3. Colors ONLY: var(--sx-*), transparent, currentColor, rgba(0,0,0,X), rgba(255,255,255,X). NO hex, NO rgb()/hsl(), no named colors.
4. Fonts ONLY var(--sx-font-heading) / var(--sx-font-body) / var(--sx-font-accent).
5. Images ONLY as <img data-slot="…" src="" alt="specific, evocative alt"> with data-slot from the allowed list; each slot at most once. The platform fills src.
6. Every text element rendering a provided copy field carries data-override-target="{{module}}/{{field}}" (each provided field exactly once). TOTAL EDITABILITY: any ADDITIONAL display text you invent carries its own data-override-target="{{module}}/custom_1", custom_2, … — every visible word on the page must be editable.
7. Links: href is a #anchor or one of the provided hrefs. NO other URLs anywhere.
8. NO <script>, NO <style> tags in the HTML, NO inline event handlers, NO position:fixed, NO id selectors in CSS.
9. At least one @media (max-width: 760px) block that keeps every section intact on a phone.
10. Any animation respects @media (prefers-reduced-motion: reduce). Keyframes are precious: spend at most {kf_budget} new one(s) — the page cap is 8 total, shell included.
11. SUBSTANCE FLOOR: a hero headline is ≤ 9 words with a REAL subhead; an about section carries ≥ 60 words; no caption-only sections. Real paragraphs, real voice.
12. INTERACTIONS: ONE signature interaction, owned and polished; functional furniture (filter tabs, modal, accordion) may ride along inside the page-JS budget.{js_request}
13. Size: HTML ≤ 18KB, CSS ≤ 14KB.

OUTPUT FORMAT — exactly this, nothing else:
<!--HTML-->
<section id="…" class="atl-… …">…</section>
<!--SX_BLOCK:…-->
<section id="…" class="atl-… …">…</section>
<!--CSS-->
.atl-… {{ … }}{js_format}

After the final closing brace{''' of your last CSS rule (or the script's close)''' if is_final else ''}, output NOTHING — no closing tags, no commentary, no code fences."""


def _chunk_data(span: List[Dict[str, Any]],
                ctx: Dict[str, Any]) -> Dict[str, Any]:
    """{module: REAL DATA block} for the span's authored sections — the
    atelier's _section_data, the ONLY facts the model may render."""
    out: Dict[str, Any] = {}
    for s in span:
        if s["role"] != "authored":
            continue
        out[s["module"]] = atelier._section_data(
            s["module"], s.get("content") or {}, ctx)
    return out


def build_chunk_prompt(brief: str, span: List[Dict[str, Any]],
                       blocks: Dict[int, Dict[str, Any]],
                       ctx: Dict[str, Any], dro: Optional[Dict[str, Any]],
                       *, is_final: bool, prior_summary: str) -> str:
    """The user prompt for one chunk: the canvas brief + coherence
    summary + per-section REAL DATA and block tokens + the token system
    + the canvas contract."""
    parts: List[str] = [brief, ""]
    if prior_summary:
        parts += ["== COHERENCE — what the previous chunk built ==",
                  prior_summary, ""]
    parts.append("== YOUR CHUNK — the sections you author now ==")
    for s in span:
        if s["role"] == "block":
            parts.append(
                f"* BLOCK TOKEN {s['token']} — the pre-rendered {s['module']} "
                "data section (real rows, immutable). Place the token exactly "
                "once, on its own line BETWEEN your sections, where this "
                "chapter belongs in the flow.")
    data = _chunk_data(span, ctx)
    for s in span:
        if s["role"] != "authored":
            continue
        mid = s["module"]
        dom_id = atelier._SECTION_DOM_IDS.get(mid, mid)
        slots = atelier.ALLOWED_SLOTS.get(mid, ())
        parts.append(
            f"\n* AUTHOR <section id=\"{dom_id}\" class=\"atl-{s['uid']} …\">"
            f" — the {mid} section.")
        parts.append("  REAL DATA (the only facts you may render):\n"
                     + json.dumps(data.get(mid) or {}, ensure_ascii=False,
                                  indent=2))
        if slots:
            parts.append(f"  image slots allowed: {', '.join(slots)}")
    parts += ["", "== THE TOKEN SYSTEM (the only colors/fonts that exist) ==",
              atelier._token_block(), ""]
    # §7.3's keyframe cap, handed to the model as a budget: page cap
    # minus the shell's own keyframes and the blocks' (deduped).
    block_kf = sum(len(re.findall(r"@(?:-webkit-)?keyframes\b",
                                  (b or {}).get("css") or ""))
                   for b in (blocks or {}).values())
    kf_budget = max(1, _keyframe_cap() - 3 - block_kf)
    parts.append(_canvas_contract(span, is_final, kf_budget))
    return "\n".join(parts)


# ─── Response parse + the JS armor (§6) ──────────────────────────────

def _split_chunk(raw: str, uids: List[str]
                 ) -> Optional[Tuple[str, str, str]]:
    """Parse <!--HTML--> / <!--CSS--> / [<!--JS-->] — the atelier's
    _split_fragment generalized to multi-section chunks with an optional
    trailing script part. Sanitizes tail junk + child uid stamps."""
    if not raw:
        return None
    try:
        from agents.composer.hero_composer import _strip_code_fence
        raw = _strip_code_fence(raw)
    except Exception:
        pass
    m = re.search(r"<!--HTML-->(.*?)<!--CSS-->(.*)$", raw, re.DOTALL)
    if not m:
        return None
    html = m.group(1).strip()
    tail = m.group(2)
    css_part, _, js = tail.partition("<!--JS-->")
    css = atelier._strip_css_tail_junk(css_part)
    js = js.strip()
    if js:
        js = re.sub(r"^```[a-zA-Z]*\s*", "", js)
        js = re.sub(r"```+\s*$", "", js)
        # Trailing closing tags are junk, never JS (the CSS tail rule's twin)
        js = re.sub(r"(?:\s*</[A-Za-z][^>]*>)+\s*$", "", js).strip()
    if not html or not css:
        return None
    # The atelier's descope assumes ONE root (its regex finds the first
    # <section> and strips the uid token from every later element — on a
    # multi-section chunk that would eat the NEXT section's root class).
    # Descope inside each uid's own section span instead.
    for uid in uids:
        m = re.search(rf"<section\b[^>]*\batl-{re.escape(uid)}\b[^>]*>", html)
        if not m:
            continue
        sm = _SECTION_TAG_RE.search(html, m.start())
        if not sm:
            continue
        seg = atelier._descope_child_uids(sm.group(0), uid)
        html = html[:sm.start()] + seg + html[sm.end():]
    return html, css, js


# §6 — the ban list (regex + token scan). Protocol-relative URLs are
# NOT scanned (a '// …' line comment would false-positive); any real
# exfiltration needs a scheme, and 'https?://' catches it.
_JS_BANNED: Tuple[Tuple[re.Pattern, str], ...] = (
    (re.compile(r"\beval\s*\("), "eval("),
    (re.compile(r"\bnew\s+Function\b"), "new Function"),
    (re.compile(r"\bfetch\s*\("), "fetch("),
    (re.compile(r"\bXMLHttpRequest\b"), "XMLHttpRequest"),
    (re.compile(r"\bimport\s*\("), "import("),
    (re.compile(r"(?:^|[^\w.])import\s+[\w*{]", re.MULTILINE), "import statement"),
    (re.compile(r"\bWebSocket\b"), "WebSocket"),
    (re.compile(r"\bdocument\s*\.\s*write\b"), "document.write"),
    (re.compile(r"\blocalStorage\b"), "localStorage"),
    (re.compile(r"\bsessionStorage\b"), "sessionStorage"),
    (re.compile(r"https?://", re.IGNORECASE), "http literal"),
)
_IIFE_RE = re.compile(
    r"^\s*(?:\(\s*(?:async\s+)?function|!\s*function|~\s*function"
    r"|\(\s*(?:async\s*)?\()")


def scan_canvas_js(script: str) -> Tuple[bool, List[str]]:
    """The JS armor (§6): static scan of the ONE page script. Returns
    (ok, problems). An empty script is fine (interactions are optional).
    DOM-only: class toggling, attribute flips, IntersectionObserver,
    addEventListener — everything on the ban list is rejected."""
    problems: List[str] = []
    s = str(script or "").strip()
    if not s:
        return True, []
    if len(s.encode("utf-8")) > JS_MAX_BYTES:
        problems.append(f"page script exceeds {JS_MAX_BYTES // 1024}KB")
    if not _IIFE_RE.search(s):
        problems.append("page script must be IIFE-wrapped "
                        "(e.g. (function(){ … })();)")
    for rx, label in _JS_BANNED:
        if rx.search(s):
            problems.append(f"banned construct in page script: {label}")
    return (not problems), problems


# ─── Chunk validation (§4 — the atelier armor, canvas deltas) ────────

def _check_css_scoping_multi(css: str, uids: List[str],
                             problems: List[str]) -> None:
    """The atelier's brace-walking scoping check, generalized to the
    chunk's uid set: every selector starts with one of the .atl-{uid}
    prefixes; keyframes names start with one of the atl-{uid} prefixes;
    @media only; no #id selectors."""
    prefixes = tuple(f".atl-{u}" for u in uids)
    kf_prefixes = tuple(f"atl-{u}" for u in uids)
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    stack: List[str] = []
    buf: List[str] = []
    for ch in body:
        if ch == "{":
            prelude = "".join(buf).strip()
            buf = []
            low = prelude.lower()
            if low.startswith("@media"):
                stack.append("media")
            elif low.startswith(("@keyframes", "@-webkit-keyframes")):
                name = prelude.split(None, 1)[1].strip() if " " in prelude else ""
                if not name.startswith(kf_prefixes):
                    problems.append(
                        f"@keyframes name '{name or '(missing)'}' must start "
                        f"with one of: {', '.join(kf_prefixes)}")
                stack.append("keyframes")
            elif low.startswith("@"):
                problems.append(f"at-rule not allowed: '{prelude[:40]}'")
                stack.append("atrule")
            elif "keyframes" in stack:
                stack.append("frame")     # from/to/% — exempt
            else:
                for sel in prelude.split(","):
                    s = sel.strip()
                    if not s:
                        continue
                    if "#" in s:
                        problems.append(f"id selector banned: '{s[:60]}'")
                    if not s.startswith(prefixes):
                        problems.append(
                            f"unscoped selector (must start with one of: "
                            f"{', '.join(prefixes)}): '{s[:60]}'")
                stack.append("rule")
        elif ch == "}":
            if stack:
                stack.pop()
            else:
                problems.append("unbalanced braces in CSS (extra '}')")
            buf = []
        else:
            buf.append(ch)
    if stack:
        problems.append("unbalanced braces in CSS (unclosed block)")


def validate_chunk(html: str, css: str, js: str,
                   span: List[Dict[str, Any]],
                   blocks: Dict[int, Dict[str, Any]],
                   ctx: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Full canvas-contract inspection of one chunk (the atelier
    validator's clauses reused wholesale + §4 deltas: multiple scoped
    roots, block-token placement, the JS armor). Problems are written
    to paste straight into the repair prompt."""
    problems: List[str] = []
    html = str(html or "")
    css = str(css or "")
    authored = [s for s in span if s["role"] == "authored"]
    uids = [s["uid"] for s in authored]
    data = _chunk_data(span, ctx)
    allowed_slots = tuple(dict.fromkeys(
        sl for s in authored for sl in atelier.ALLOWED_SLOTS.get(s["module"], ())))
    allowed_hrefs = sorted({h for d in data.values()
                            for h in atelier._allowed_hrefs(d)})

    # §4.8 — size caps first
    if len(html.encode("utf-8")) > HTML_MAX_BYTES:
        problems.append(f"HTML exceeds {HTML_MAX_BYTES // 1024}KB")
    if len(css.encode("utf-8")) > CSS_MAX_BYTES:
        problems.append(f"CSS exceeds {CSS_MAX_BYTES // 1024}KB")

    # §4.1 — structure: one root <section> per authored section
    p = atelier_validator._FragmentParser()
    try:
        p.feed(html)
        p.close()
    except Exception as e:
        return False, problems + [f"HTML failed to parse: {e}"]
    if p.unbalanced or p.depth != 0:
        problems.append("unbalanced HTML tags")
    seen_uids: List[str] = []
    for t, a in [(t, a) for t, a in p.roots]:
        if t != "section":
            problems.append(f"only <section> roots allowed (found <{t}>)")
            continue
        classes = (a.get("class") or "").split()
        hit = [u for u in uids if f"atl-{u}" in classes]
        if len(hit) != 1:
            problems.append("each root <section> must carry exactly one of "
                            "the chunk's atl-uid classes")
        else:
            seen_uids.append(hit[0])
    missing = [u for u in uids if u not in seen_uids]
    if missing:
        problems.append(f"{len(missing)} authored section(s) missing "
                        f"(atl-{', atl-'.join(missing)})")
    for u in set(seen_uids):
        if seen_uids.count(u) > 1:
            problems.append(f"the uid atl-{u} roots {seen_uids.count(u)} "
                            "sections (exactly one each)")
    if p.stray_text:
        problems.append(f"text outside the root sections: {p.stray_text[:2]}")

    # §4.8/atelier-8 — banned tags, handlers, fixed positioning
    for t in p.banned:
        problems.append(f"banned tag <{t}>")
    for h in p.handlers:
        problems.append(f"inline event handler banned: {h}")
    if re.search(r"position\s*:\s*fixed", css + " ".join(p.style_attrs),
                 re.IGNORECASE):
        problems.append("position:fixed banned")

    # §4.5 — block tokens: exactly once each, never inside a section
    section_spans = [m.span() for m in _SECTION_TAG_RE.finditer(html)]
    for s in span:
        if s["role"] != "block":
            continue
        tok = s.get("token") or f"<!--SX_BLOCK:{s['module']}-->"
        n = html.count(tok)
        if n != 1:
            problems.append(f"block token {tok} must appear exactly once "
                            f"(found {n})")
            continue
        pos = html.find(tok)
        if any(a <= pos < b for a, b in section_spans):
            problems.append(f"block token {tok} nested inside a section — "
                            "tokens sit BETWEEN sections")

    # atelier-7 — external references + anchors
    for label, text in (("HTML", html), ("CSS", css)):
        for m in atelier_validator._EXTERNAL_RE.finditer(text):
            if m.group(0).lower().startswith("http") and any(
                    h and text[m.start():m.start() + len(h)] == h
                    for h in allowed_hrefs):
                continue
            problems.append(f"external reference banned in {label}: "
                            f"'{text[m.start():m.start() + 40]}…'")
            break
    for a in p.anchors:
        href = (a.get("href") or "").strip()
        if not href:
            problems.append("anchor with empty href (dead link)")
        elif not href.startswith("#") and href not in allowed_hrefs:
            problems.append(f"href not allowed: '{href[:80]}' "
                            "(#anchors or the provided hrefs only)")

    # atelier-5 — imagery
    seen_slots: List[str] = []
    for img in p.imgs:
        slot = (img.get("data-slot") or "").strip()
        if not slot:
            problems.append("every <img> must carry data-slot")
        elif slot not in allowed_slots:
            problems.append(f'data-slot "{slot}" not allowed here '
                            f"(allowed: {list(allowed_slots) or 'none'})")
        elif slot in seen_slots:
            problems.append(f'data-slot "{slot}" used more than once')
        else:
            seen_slots.append(slot)
        if str(img.get("src") or "").strip():
            problems.append("img src must be empty — the platform fills it")
        if not str(img.get("alt") or "").strip():
            problems.append(f'img (slot "{slot or "?"}") missing alt text')

    # atelier-6 — copy override paths (per authored section's module)
    known_fields: Dict[str, set] = {}
    for s in authored:
        d = data.get(s["module"]) or {}
        known_fields[s["module"]] = {
            f for f, v in (d.get("copy") or {}).items() if str(v or "").strip()
        } | set(atelier._module_fields(s["module"]))
        for f, v in (d.get("copy") or {}).items():
            if not str(v or "").strip():
                continue
            want = f"{s['module']}/{f}"
            n_t = p.targets.count(want)
            if n_t == 0:
                problems.append(f'missing data-override-target="{want}" for '
                                f"the provided copy field '{f}'")
            elif n_t > 1:
                problems.append(f'data-override-target="{want}" appears {n_t} '
                                "times (must be unique)")
    mid_set = {s["module"] for s in authored}
    for t in p.targets:
        if "/" not in t:
            problems.append(f'override target "{t}" malformed')
            continue
        mid, field = t.split("/", 1)
        if mid not in mid_set:
            problems.append(f'override target "{t}" must live under one of: '
                            f"{sorted(mid_set)}")
            continue
        if field in known_fields.get(mid, set()) or \
                atelier_validator._CUSTOM_TARGET_RE.fullmatch(field):
            continue
        problems.append(f'override target "{t}" not recognized — invented '
                        f'display text must use data-override-target='
                        f'"{mid}/custom_N" (N = 1, 2, …)')

    # atelier-14 — TOTAL EDITABILITY census
    try:
        from site_modules._base import (data_verbatim_strings,
                                        editability_coverage)
        _n_ed, _samples = editability_coverage(
            html, exempt_texts=data_verbatim_strings(data))
        if _n_ed:
            problems.append(f"total editability: {_n_ed} visible text node(s) "
                            "lack data-override-target — invented display text "
                            "needs its own custom_N target: "
                            f"{_samples[:3]}")
    except Exception:
        pass

    # atelier-2/3/4 — CSS scoping (multi-uid), colors, tokens/fonts
    _check_css_scoping_multi(css, uids, problems)
    atelier_validator._check_colors(css, p.style_attrs, problems)
    atelier_validator._check_tokens_and_fonts(css, p.style_attrs, problems)

    # atelier-9/10 — responsive + reduced motion
    preludes = re.findall(r"@media[^{]*", css, re.IGNORECASE)
    widths = [float(w) for pre in preludes
              for w in atelier_validator._MEDIA_MAXW_RE.findall(pre)]
    if not any(w <= 900 for w in widths):
        problems.append("no mobile @media (max-width: <=760px) block found")
    if re.search(r"animation|@keyframes", css, re.IGNORECASE) and \
            "prefers-reduced-motion" not in css:
        problems.append("animation present without a "
                        "prefers-reduced-motion guard")

    # atelier-13 — a11y floor
    if p.headings < 1:
        problems.append("no heading (h1-h3) in the chunk")

    # atelier-12 — DATA FIDELITY against the chunk's REAL DATA
    data_digits = set(_DIGIT_RUN_RE.findall(
        json.dumps(data, ensure_ascii=False)))
    for run in _DIGIT_RUN_RE.findall(" ".join(p.text_parts)):
        if run not in data_digits:
            problems.append(f"number '{run}' rendered but not present in the "
                            "provided data — never invent prices/figures")

    # atelier-14b — HEADLINE PLAIN-TEXT INTEGRITY
    for hm in re.finditer(r"<h[12][^>]*>([\s\S]*?)</h[12]>", html,
                          re.IGNORECASE):
        inner = hm.group(1)
        hidden_words: List[str] = []
        for ah in re.finditer(
                r"<[^>]+aria-hidden=[\"']true[\"'][^>]*>([\s\S]*?)</[^>]+>",
                inner, re.IGNORECASE):
            hidden_words += re.findall(r"[A-Za-z']{2,}",
                                       re.sub(r"<[^>]+>", " ", ah.group(1)))
        if hidden_words:
            problems.append("headline contains aria-hidden WORDS "
                            f"({', '.join(hidden_words[:4])}) — headings must "
                            "read as clean plain text (HEADLINE INTEGRITY)")
            break

    # atelier-15 — STYLESHEET PURITY
    css_body = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    jm = re.search(r"</[^\n]{0,30}", css_body)
    if jm:
        problems.append(f"markup junk inside CSS: '{jm.group(0)}'")

    # atelier-16/17/18/19 — scope-class discipline + Motion System
    for uid in uids:
        stamps = len(re.findall(rf"\batl-{re.escape(uid)}\b", html))
        if stamps > 1:
            problems.append(f"the scope class atl-{uid} appears on {stamps} "
                            "elements — it belongs ONLY on the root <section>")
    for uid in uids:
        atelier_validator._check_motion(css, uid, problems)

    # §6 — the JS contract (the script alone never sinks good HTML/CSS:
    # the caller retries validation with js="" and drops it)
    if str(js or "").strip():
        _js_ok, js_problems = scan_canvas_js(js)
        problems += js_problems

    # multi-uid motion checks repeat shared complaints — dedupe
    problems = list(dict.fromkeys(problems))
    return (not problems), problems


def _split_sections(html: str, uids: List[str]) -> Dict[str, str]:
    """Split a validated chunk's HTML into {uid: section_html} (chunk
    validation has already guaranteed one uid-scoped root per section)."""
    out: Dict[str, str] = {}
    for m in _SECTION_TAG_RE.finditer(html):
        sec = m.group(0)
        root_tag = sec.split(">", 1)[0]
        for uid in uids:
            if re.search(rf"\batl-{re.escape(uid)}\b", root_tag):
                out[uid] = sec
                break
    return out


def _summarize(sections: Dict[str, str],
               span: List[Dict[str, Any]]) -> str:
    """The one-paragraph prior-chunk summary (§3.4 — coherence without
    re-sending full markup): what was built, which motifs established."""
    bits: List[str] = []
    for s in span:
        if s["role"] != "authored":
            continue
        sec = sections.get(s["uid"], "")
        h = re.search(r"<h[1-3][^>]*>([\s\S]*?)</h[1-3]>", sec, re.IGNORECASE)
        head = " ".join(re.sub(r"<[^>]+>", " ", h.group(1)).split())[:90] if h else ""
        bits.append(s["module"] + (f' — headline "{head}"' if head else ""))
    return ("Built so far: " + "; ".join(bits) +
            ". Keep the motifs these sections established; do not repeat "
            "or contradict them.")


def _author_chunk(brief: str, span: List[Dict[str, Any]],
                  blocks: Dict[int, Dict[str, Any]], ctx: Dict[str, Any],
                  dro: Optional[Dict[str, Any]], *, is_final: bool,
                  prior_summary: str, business_id: str,
                  feedback: str = "") -> Optional[Dict[str, Any]]:
    """One chunk: ONE LLM call, deterministic validation, ONE repair
    attempt (the atelier's _attempt pattern), else None — the caller
    degrades the chunk's sections to module renders."""
    authored = [s for s in span if s["role"] == "authored"]
    if not authored:
        return {"sections": {}, "css": "", "js": "", "js_dropped": False,
                "summary": "", "repaired": False}
    uids = [s["uid"] for s in authored]
    prompt = build_chunk_prompt(brief, span, blocks, ctx, dro,
                                is_final=is_final,
                                prior_summary=prior_summary)
    if feedback:
        prompt += ("\n\nGRADER / FACT-CHECK FEEDBACK FROM THE PREVIOUS "
                   "ATTEMPT — address every point:\n" + feedback[:1500])

    def _attempt(extra: str = ""
                 ) -> Tuple[Optional[Tuple[str, str, str, bool]], List[str]]:
        raw = _call_llm(_SYSTEM_PROMPT, prompt + extra, business_id)
        if raw is None:
            return None, ["LLM call failed"]
        parsed = _split_chunk(raw, uids)
        if parsed is None:
            return None, ["response missing <!--HTML--> / <!--CSS--> "
                          "delimiters or an empty part"]
        html, css, js = parsed
        ok, problems = validate_chunk(html, css, js, span, blocks, ctx)
        if not ok and js.strip():
            # §6 — a script that can't be armored is DROPPED, never fatal
            # to good HTML/CSS (the no-JS-default clause keeps the page
            # coherent). Re-validate without it.
            ok_nojs, _ = validate_chunk(html, css, "", span, blocks, ctx)
            if ok_nojs:
                logger.warning(f"[canvas] page script dropped after armor "
                               f"for {(business_id or 'unknown')[:8]}")
                return (html, css, "", True), []
        return ((html, css, js, False) if ok else None), problems

    out, problems = _attempt()
    repaired = False
    if out is None and problems:
        repaired = True
        repair = ("\n\nYOUR PREVIOUS OUTPUT FAILED VALIDATION. Problems:\n- "
                  + "\n- ".join(problems[:12])
                  + "\n\nFix EVERY problem. Re-read the HARD OUTPUT CONTRACT. "
                    "Output ONLY the <!--HTML--> / <!--CSS-->"
                  + (" / <!--JS-->" if is_final else "") + " parts.")
        out, problems = _attempt(repair)
    if out is None:
        logger.warning(f"[canvas] chunk fell back: "
                       f"{[s['module'] for s in authored]} for "
                       f"{(business_id or 'unknown')[:8]} — {problems[:6]}")
        return None
    html, css, js, js_dropped = out
    sections = _split_sections(html, uids)
    logger.info(f"[canvas] chunk accepted for {(business_id or 'unknown')[:8]} "
                f"({[s['module'] for s in authored]}, html {len(html)}B "
                f"css {len(css)}B js {len(js)}B)")
    return {"sections": sections, "css": css,
            "js": js if is_final else "",
            "js_dropped": js_dropped, "repaired": repaired,
            "summary": _summarize(sections, span)}


# ─── Assembly (§3.5) ─────────────────────────────────────────────────

def _inject_canvas_css(doc: str, css: str) -> str:
    """The authored CSS rides its own <style id="sx-canvas"> appended
    after the shell's module <style> — the same cascade position as
    sx-atelier (later rules win at equal specificity; .atl- scoping
    wins anyway)."""
    block = f'<style id="sx-canvas">\n{css}\n</style>'
    if "</head>" in doc:
        return doc.replace("</head>", block + "\n</head>", 1)
    return doc + block


def assemble_canvas(plan: Dict[str, Any],
                    chunk_results: List[Dict[str, Any]],
                    blocks: Dict[int, Dict[str, Any]],
                    ctx: Dict[str, Any], title: str,
                    script: str = "") -> Tuple[str, List[str]]:
    """Splice authored sections and pre-rendered blocks in plan order;
    stamp the platform's section markers + DOM ids + sxm-stage; wrap in
    the SAME page_shell as render_page (fonts link, --sx-* :root, base
    CSS, reveal script, meta). Returns (document, module_fallbacks) —
    the authored modules that had to render from the registry instead
    (per-chunk degradation, §9)."""
    import site_modules
    from site_modules import _base as sx_base

    uid_html: Dict[str, str] = {}
    canvas_css: List[str] = []
    for cr in chunk_results:
        uid_html.update(cr.get("sections") or {})
        if cr.get("css"):
            canvas_css.append(cr["css"])

    body_parts: List[str] = []
    rendered_ids: List[str] = []
    is_block: List[bool] = []
    css_parts: List[str] = []
    seen_css: set = set()
    module_fallbacks: List[str] = []

    def _module_render(s: Dict[str, Any]) -> Tuple[str, str]:
        mspec = site_modules.MODULES.get(s["module"])
        if not mspec:
            return "", ""
        variant = s["variant"] if s["variant"] in mspec["variants"] \
            else mspec["variants"][0]
        try:
            return mspec["render"](variant, s.get("content") or {}, ctx)
        except Exception:
            return "", ""

    for s in plan["sections"]:
        mid = s["module"]
        html = ""
        block_part = False
        if s["role"] == "authored":
            html = uid_html.get(s.get("uid") or "", "")
            if html:
                html = atelier._stamp_stage(atelier._stamp_dom_id(html, mid))
            else:
                module_fallbacks.append(mid)
        if not html:
            # Block sections (immutable truth) and degraded authored
            # sections both render from the registry here.
            if s["role"] == "block":
                b = blocks.get(s["index"]) or {}
                html, css, variant = (b.get("html") or "", b.get("css") or "",
                                      b.get("variant") or s["variant"])
                block_part = bool(html)
            else:
                html, css = _module_render(s)
                variant = s["variant"]
            if not html:
                continue
            key = f"{mid}:{variant}"
            if css and key not in seen_css:
                seen_css.add(key)
                css_parts.append(css)
        i = len(body_parts)
        body_parts.append(f"<!--sx:{mid}:{i}-->{html}<!--/sx:{mid}:{i}-->")
        rendered_ids.append(mid)
        is_block.append(block_part)

    # The deterministic marks render_page applies — the canvas emits the
    # same platform anatomy, so every downstream system works untouched.
    # They land ONLY on non-block parts: a pre-rendered block splices
    # back BYTE-IDENTICAL (§7.2), which the cosmetic marks (class
    # additions, ghost-numeral spans) would break. Numerals/authority/
    # silence target the authored + module-fallback set.
    f_idxs = [i for i, b in enumerate(is_block) if not b]
    f_parts = [body_parts[i] for i in f_idxs]
    f_ids = [rendered_ids[i] for i in f_idxs]
    if sx_base.rule_break_treatment(ctx.get("design")) == "hard_silence":
        site_modules._mark_silence_target(f_parts, f_ids)
    site_modules._mark_authority_band(f_parts, f_ids, ctx)
    site_modules._mark_after_seam(f_parts, f_ids)
    site_modules._inject_ghost_numerals(f_parts, f_ids, ctx)
    for i, p in zip(f_idxs, f_parts):
        body_parts[i] = p
    header_html, header_css = site_modules.header.render_header(rendered_ids,
                                                                ctx)
    body_parts.insert(0, header_html)
    css_parts.insert(0, header_css)
    try:
        from design_specs import motion_css_vars
        css_parts.insert(0, motion_css_vars(ctx.get("motion_tokens"),
                                            ctx.get("motion_spec")))
    except Exception:
        pass
    try:
        _rb = int((ctx.get("rhythm_scale") or {}).get("base_px") or 0)
        if _rb:
            css_parts.insert(0, (":root { --sx-rhythm-base: %dpx; "
                                 "--sx-rhythm-half: %dpx; "
                                 "--sx-rhythm-quarter: %dpx; }"
                                 % (_rb, _rb // 2, _rb // 4)))
    except Exception:
        pass

    doc = sx_base.page_shell(ctx["dna"], title, "\n".join(body_parts),
                             "\n".join(css_parts), design=ctx.get("design"),
                             meta=sx_base.build_page_meta(ctx))
    authored_css = "\n\n".join(c for c in canvas_css if c.strip())
    if authored_css:
        doc = _inject_canvas_css(doc, authored_css)
    if script.strip():
        block = f'<script id="sx-canvas-js">{script.strip()}</script>'
        if "</body>" in doc:
            doc = doc.replace("</body>", block + "\n</body>", 1)
        else:
            doc += block
    return doc, module_fallbacks


# ─── The fact-checker + floor verifier (§7) ──────────────────────────

def _visible_text(html: str) -> str:
    t = re.sub(r"<(script|style|noscript)\b[\s\S]*?</\1>", " ",
               str(html or ""), flags=re.IGNORECASE)
    t = re.sub(r"<!--[\s\S]*?-->", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    return " ".join(t.split())


def _count_visible_words(html: str) -> int:
    return len(_WORD_RE.findall(_visible_text(html)))


def _extract_uid_section(html: str, uid: str) -> str:
    m = re.search(rf"<section\b[^>]*\batl-{re.escape(uid)}\b[^>]*>", html)
    if not m:
        return ""
    nxt = _SECTION_TAG_RE.search(html, m.start())
    return nxt.group(0) if nxt else ""


# Shell chrome injected into authored sections at assembly (Site Arc 10
# ghost chapter numerals) — platform ornament, never model-authored, so
# the §7.1 fact trace must not trace its digits.
_GHOSTNUM_RE = re.compile(
    r'<span class="sxm-ghostnum[^"]*"[^>]*>[\s\S]*?</span>')


def fact_check_canvas(html: str, ctx: Dict[str, Any],
                      plan: Dict[str, Any],
                      blocks: Dict[int, Dict[str, Any]],
                      module_fallbacks: Tuple[str, ...] = (),
                      ) -> Tuple[bool, List[str]]:
    """§7 — runs on the assembled page BEFORE slot population. Returns
    (ok, problems): fact trace over authored sections, immutable block
    byte-identity, the substance floor, required anatomy. Authored
    sections in module_fallbacks degraded to registry renders (§9) —
    they carry no atl-uid and need no fact trace (module output is
    deterministic from ctx)."""
    problems: List[str] = []
    authored = [s for s in plan["sections"]
                if s["role"] == "authored" and s.get("uid")
                and s["module"] not in module_fallbacks]
    data = _chunk_data(plan["sections"], ctx)

    # §7.1 — FACT TRACE: every digit-run in an authored section must
    # exist in the business data JSON (the atelier DATA FIDELITY rule,
    # page-wide). Block sections need no check — deterministic by
    # construction. (Proper names/quotes stay prompt-law: no
    # deterministic source-of-truth comparison exists for them —
    # same standard the atelier set.) Ghost chapter numerals are shell
    # chrome injected at assembly — stripped before the scan.
    data_digits = set(_DIGIT_RUN_RE.findall(
        json.dumps(data, ensure_ascii=False)))
    for s in authored:
        sec = _GHOSTNUM_RE.sub(" ", _extract_uid_section(html, s["uid"]))
        if not sec:
            problems.append(f"authored section {s['module']} (atl-{s['uid']}) "
                            "missing from the assembled page")
            continue
        for run in _DIGIT_RUN_RE.findall(_visible_text(sec)):
            if run not in data_digits:
                problems.append(f"{s['module']}: number '{run}' rendered but "
                                "not present in the business data — never "
                                "invent figures")

    # §7.2 — BLOCK INTEGRITY: every pre-rendered block splices back
    # byte-identically (no model edits); no token left unspliced.
    for _idx, b in (blocks or {}).items():
        if b.get("html") and b["html"] not in html:
            problems.append(f"immutable block '{b['module']}' altered or "
                            "missing — blocks splice byte-identically")
    if "<!--SX_BLOCK:" in html:
        problems.append("an unspliced <!--SX_BLOCK:…--> token survived "
                        "assembly")

    # §7.3 — SUBSTANCE FLOOR (deterministic, from the audit's table)
    words = _count_visible_words(html)
    if words < _floor_words():
        problems.append(f"substance floor: {words} visible words < "
                        f"{_floor_words()} (CANVAS_FLOOR_WORDS)")
    if (ctx.get("gallery") or []) and \
            not re.search(r"<img\b[^>]*\bdata-slot=", html):
        problems.append("imagery floor: gallery photos exist but no "
                        "data-slot image is present in the markup")
    css_all = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html,
                                   re.DOTALL | re.IGNORECASE))
    n_kf = len(re.findall(r"@(?:-webkit-)?keyframes\b", css_all))
    if n_kf > _keyframe_cap():
        problems.append(f"motion ceiling: {n_kf} @keyframes > "
                        f"{_keyframe_cap()} (CANVAS_KEYFRAME_CAP)")
    for s in authored:
        sec = _extract_uid_section(html, s["uid"])
        if not sec:
            continue
        if s["module"] == "about":
            n = len(_WORD_RE.findall(_visible_text(sec)))
            if n < 60:
                problems.append(f"about section carries {n} words (< 60 — "
                                "the §4.7 substance minimum)")
        if s["module"] == "hero":
            h = re.search(r"<h1[^>]*>([\s\S]*?)</h1>", sec, re.IGNORECASE)
            if h:
                n = len(_WORD_RE.findall(
                    re.sub(r"<[^>]+>", " ", h.group(1))))
                if n > 9:
                    problems.append(f"hero headline runs {n} words (> 9 — "
                                    "the §4.7 ceiling)")

    # §7.4 — REQUIRED ANATOMY: markers, DOM ids, override-target census,
    # single script, no banned constructs.
    for s in plan["sections"]:
        mid = s["module"]
        if not re.search(rf"<!--sx:{re.escape(mid)}:\d+-->", html):
            problems.append(f"section marker <!--sx:{mid}:i--> missing")
        dom = atelier._SECTION_DOM_IDS.get(mid)
        if dom and f'id="{dom}"' not in html:
            problems.append(f"stable DOM id '{dom}' missing for {mid}")
    try:
        from site_modules._base import (data_verbatim_strings,
                                        editability_coverage)
        census_data = dict(data)
        census_data["_spec_copy"] = [s.get("content") or {}
                                     for s in plan["sections"]]
        n_ed, samples = editability_coverage(
            html, exempt_texts=data_verbatim_strings(census_data))
        if n_ed:
            problems.append(f"override-target census: {n_ed} visible text "
                            f"node(s) lack data-override-target: {samples[:3]}")
    except Exception:
        pass
    # Platform scripts that ride inside immutable blocks (the contact
    # form's submit handler, contact_footer.py) are byte-identical
    # splices of registry output — the census already guarantees block
    # byte-identity, so an exact body match against the block markup is
    # by definition platform-owned, not canvas-authored.
    block_scripts = set()
    for _b in (blocks or {}).values():
        for _body in re.findall(r"<script\b[^>]*>([\s\S]*?)</script>",
                                str(_b.get("html") or ""), re.IGNORECASE):
            block_scripts.add(_body)
    canvas_scripts = 0
    for attrs, body_js in re.findall(r"<script\b([^>]*)>([\s\S]*?)</script>",
                                     html, re.IGNORECASE):
        if "ld+json" in attrs:
            continue                      # platform JSON-LD meta
        if "sx-canvas-js" in attrs:
            canvas_scripts += 1
            _js_ok, js_problems = scan_canvas_js(body_js)
            problems += js_problems       # defense in depth (already armored)
            continue
        if "IntersectionObserver" in body_js and "sxm-" in body_js:
            continue                      # the platform reveal script
        if body_js in block_scripts:
            continue                      # platform script inside an immutable block
        problems.append("unidentified <script> block — only the platform "
                        "reveal script and ONE sx-canvas-js are allowed")
    if canvas_scripts > 1:
        problems.append(f"{canvas_scripts} canvas scripts — the JS contract "
                        "allows exactly one")
    body_m = re.search(r"<body\b[^>]*>([\s\S]*?)</body>", html, re.IGNORECASE)
    if body_m:
        bp = atelier_validator._FragmentParser()
        try:
            bp.feed(body_m.group(1))
            bp.close()
            for h in bp.handlers:
                problems.append(f"inline event handler banned: {h}")
        except Exception:
            pass
    problems = list(dict.fromkeys(problems))
    return (not problems), problems


# ─── Orchestration (§3 architecture + §9 degradation ladder) ─────────

def run_canvas(spec: List[Dict[str, Any]], ctx: Dict[str, Any],
               dro: Optional[Dict[str, Any]], business_id: str,
               progress_cb=None, feedback: str = ""
               ) -> Dict[str, Any]:
    """The canvas pass: plan → pre-render blocks → author chunks →
    assemble → fact-check (one corrective retry) → document.
    Returns {"html": str|None, "report": {...}} — html None means the
    degradation ladder hands the compose back to today's module+atelier
    path (a failed canvas is never a blank page). Fail-soft throughout;
    the report always returns so findings persist (canvas_report)."""
    report: Dict[str, Any] = {
        "model": _model(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chunks": [], "fallbacks": [],
        "fact_check": {"ok": False, "problems": [], "retried": False},
    }
    try:
        plan = canvas_plan(spec, ctx, dro)
    except Exception as e:
        report["fallbacks"].append({"stage": "plan",
                                    "detail": f"{type(e).__name__}: {e}"})
        return {"html": None, "report": report}
    blocks = prerender_data_sections(plan, ctx)
    authored_mids = [s["module"] for s in plan["sections"]
                     if s["role"] == "authored"]
    report["planned"] = {
        "authored": authored_mids,
        "blocks": [b["module"] for _i, b in sorted(blocks.items())],
        "marquee_wired": bool(plan.get("marquee_wired")),
    }
    brief = canvas_brief.compile_canvas_brief(ctx, dro, spec)
    spans = chunk_spans(plan)
    if not spans:
        report["fallbacks"].append({"stage": "plan",
                                    "detail": "no authored sections in the "
                                              "plan — module path"})
        return {"html": None, "report": report}
    title = (ctx.get("business") or {}).get("name") or "Welcome"

    def _author_all(notes: str = "") -> Tuple[List[Dict[str, Any]], str]:
        results: List[Dict[str, Any]] = []
        prior = ""
        script = ""
        n = len(spans)
        for ci, span in enumerate(spans):
            _report(progress_cb, 48 + int(6 * (ci + 1) / n),
                    f"Authoring the canvas ({ci + 1} of {n})")
            out = _author_chunk(
                brief, span, blocks, ctx, dro,
                is_final=(ci == n - 1), prior_summary=prior,
                business_id=business_id, feedback=notes)
            mids = [s["module"] for s in span if s["role"] == "authored"]
            if out is None:
                report["chunks"].append({"index": ci, "sections": mids,
                                         "ok": False})
                report["fallbacks"].append({
                    "stage": f"chunk_{ci}",
                    "detail": "validation failed after one repair — "
                              f"{', '.join(mids)} render from modules"})
                continue
            report["chunks"].append({
                "index": ci, "sections": mids, "ok": True,
                "repaired": bool(out.get("repaired")),
                "js": bool(out.get("js")),
                "js_dropped": bool(out.get("js_dropped"))})
            if out.get("js"):
                script = out["js"]
            prior = out.get("summary") or prior
            results.append(out)
        return results, script

    results, script = _author_all(feedback or "")
    if not any(r.get("sections") for r in results):
        report["fallbacks"].append({
            "stage": "author",
            "detail": "every chunk failed — the module+atelier path takes over"})
        return {"html": None, "report": report}

    html, mod_fb = assemble_canvas(plan, results, blocks, ctx, title, script)
    if mod_fb:
        logger.info(f"[canvas] module-rendered authored sections for "
                    f"{business_id[:8]}: {mod_fb}")
    ok, problems = fact_check_canvas(html, ctx, plan, blocks,
                                     module_fallbacks=tuple(mod_fb))
    report["fact_check"] = {"ok": ok, "problems": problems[:20],
                            "retried": False}

    if not ok:
        # §7 — ONE corrective retry with the problems pasted in, then
        # the module path (§9).
        report["fact_check"]["retried"] = True
        notes = ("THE PREVIOUS ASSEMBLED PAGE FAILED FACT-CHECK. Problems:\n- "
                 + "\n- ".join(problems[:12])
                 + "\nFix EVERY problem. Re-read the canvas contract.")
        notes = ((feedback + "\n\n") if feedback else "") + notes
        results2, script2 = _author_all(notes)
        if not results2:
            report["fallbacks"].append({
                "stage": "fact_check",
                "detail": "corrective retry produced no chunks"})
            return {"html": None, "report": report}
        html2, mod_fb2 = assemble_canvas(plan, results2, blocks, ctx,
                                         title, script2)
        ok2, problems2 = fact_check_canvas(html2, ctx, plan, blocks,
                                           module_fallbacks=tuple(mod_fb2))
        if ok2:
            html, script = html2, script2
            report["fact_check"].update({"ok": True, "problems": []})
        else:
            report["fact_check"]["problems"] = (problems2 or problems)[:20]
            report["fallbacks"].append({
                "stage": "fact_check",
                "detail": "; ".join((problems2 or problems)[:6])})
            return {"html": None, "report": report}

    report["words"] = _count_visible_words(html)
    report["keyframes"] = len(re.findall(
        r"@(?:-webkit-)?keyframes\b",
        "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html,
                             re.DOTALL | re.IGNORECASE))))
    report["script"] = bool(script.strip())
    logger.info(f"[canvas] composed for {business_id[:8]}: "
                f"{len(report['planned']['authored'])} authored + "
                f"{len(blocks)} blocks, {report['words']} words, "
                f"{report['keyframes']} keyframes, "
                f"chunks={[(c['index'], c['ok']) for c in report['chunks']]}")
    return {"html": html, "report": report}
