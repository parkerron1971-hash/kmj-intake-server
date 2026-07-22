"""
atelier.py — Arc 8 "THE ATELIER" — bespoke AI-written sections.

Breaks the fixed-library ceiling: 2-3 sections per page (always the
hero, plus wherever the DRO's rule-break lands) are WRITTEN by an LLM —
the revival of the original studio_builder_agent's creativity — inside
modern guardrails:

  - ONE LLM call per section (ATELIER_MODEL, temp 0.8, 60s timeout,
    usage-logged task='atelier'), same _call idiom as drl/passes.py.
  - A HARD output contract (scoped .atl-{uid} CSS, --sx-* tokens only,
    data-slot imagery, data-override-target copy paths, no scripts /
    external URLs / fixed positioning) enforced by atelier_validator.
  - One REPAIR attempt on validation failure, then a SILENT fallback to
    the module-library section — quality can only go up: zero bespoke
    sections is exactly the Arc 7 page.

Integration (site_composer.render_and_persist): render_page emits
section comment markers (<!--sx:{module}:{i}-->) when the atelier is
active; run_atelier() replaces the marked module sections with the
validated bespoke fragments BEFORE slot population / override
resolution / the quality gate, so all downstream systems treat bespoke
sections exactly like module ones. Fragments persist on
site_config.atelier so shuffle/refresh/override re-renders REUSE them
(no LLM); only a full recompose regenerates.

Cost/time: 2-3 calls x ~8k output tokens ≈ $0.10-0.25 and ~60-90s per
full compose — inside the compose background job's budget.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger("atelier")

# Site Arc 11 — THE QUALITY LEVER: bespoke sections (and refines) author
# on Opus by default. Cost is ~2-3x Sonnet per section (Kevin approved
# quality-first, 2026-07); ATELIER_MODEL env still overrides either way.
#
# Site Arc 12 — the model LADDER (model_ladder.py) now protects every
# call: a model-identity error (404/403/invalid-model 400) triggers ONE
# loud (logger.error) + breadcrumbed (site_config.model_fallbacks) retry
# on Sonnet; a timeout gets one same-model retry at -35% max_tokens
# before the sonnet rung. temperature is dropped automatically on the
# families that reject sampling params (Opus 4.7/4.8 400s on it — the
# post-#62 silent-atelier killer: every bespoke call failed identically
# and fell back to the module section with only a per-section warning).
# COST DIET (2026-07-22): Sonnet 5 default — the atelier writes
# structured HTML fragments under a validator + repair loop; Sonnet
# handles it at a fraction of Opus cost. ATELIER_MODEL env = premium
# override.
ATELIER_MODEL_DEFAULT = "claude-sonnet-5"
ATELIER_TEMPERATURE = 0.8          # creative latitude — the point of the atelier
                                   # (auto-omitted where the model rejects it)
ATELIER_MAX_TOKENS = 8000
# Constructor default only — every real call passes the family-scaled
# ceiling from model_ladder.timeout_for('atelier', model): 240s on Opus
# (streams ~2-3x slower), 120s on Sonnet. Background job budget holds
# (2-3 calls per compose; jobs sweep stale at 10 min).
_CALL_TIMEOUT_S = 120.0

# Sections that must stay modular: their value is DATA RENDERED RIGHT
# (live records, real product cards) — bespoke rewriting risks fidelity
# for no aesthetic win. store per the Arc 8 brief; statband/showcase by
# the same data-dense principle. interstitial (Site Arc 10): the
# ceremony seams are deterministic chrome — no slots, no seat at the
# atelier.
# B4 (2026-07-18): contact LEFT the list — its working form now rides
# the bespoke path VERBATIM (build_contact_form + a validator-enforced
# presence check in generate_bespoke_section / generate_refined_section),
# so the finale can be art-directed without the form ever being rewritten.
_NEVER_BESPOKE = frozenset({"store", "statband", "showcase",
                            "interstitial"})

# module id → the stable DOM id its <section> must carry (mirror of
# site_composer._SECTION_DOM_IDS — kept local to avoid an import cycle;
# the quality gate + header nav anchors depend on these ids).
_SECTION_DOM_IDS = {
    "hero": "top", "about": "about", "offerings": "offerings",
    "testimonials": "testimonials", "gallery": "gallery", "cta": "cta",
    "contact": "contact", "store": "store", "showcase": "showcase",
    "statband": "stats",
}

# Which data-slot names a bespoke section of each kind may use (subset
# of agents/slot_system SLOT_DEFINITIONS, role-matched to the section).
ALLOWED_SLOTS: Dict[str, Tuple[str, ...]] = {
    "hero": ("hero_main",),
    "about": ("about_subject",),
    "gallery": ("gallery_1", "gallery_2", "gallery_3", "gallery_4",
                "chamber_main"),
    "offerings": ("chamber_main",),
    "testimonials": ("decorative_1",),
    "cta": (),
    "contact": (),
}

# B4 (2026-07-18) — the bespoke-contact form contract. A bespoke contact
# fragment never WRITES a form: it places this exact token on its own
# line where the working form belongs, and the platform substitutes the
# real markup (build_contact_form) after validation — deterministic, no
# byte-matching gamble, the form's endpoint/input names/consent wiring
# physically cannot drift. run_atelier ships CONTACT_FORM_CSS + the
# wiring script alongside any replaced contact fragment.
_FORM_TOKEN = "<!--CONTACT_FORM-->"


def _contact_form(ctx: Dict[str, Any]) -> Tuple[str, str]:
    """(form_html, script_html) for a bespoke contact section — both ''
    when no live form exists (the fragment then composes the invitation
    + channels only, like the module's solo mode). Fail-soft: any import
    problem means no form requirement (never blocks a compose)."""
    try:
        from site_modules import contact_footer
        return contact_footer.build_contact_form(ctx)
    except Exception:
        return "", ""


# Rule-break `where` free text → module id (which section the loud
# moment lives in). First hit wins; hero keywords intentionally absent —
# the hero is ALWAYS bespoke already, so the break's section gets the
# second seat.
_WHERE_KEYWORDS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("about", ("about", "story", "bio", "practice", "practitioner",
               "portrait", "founder")),
    ("offerings", ("offering", "service", "package", "price", "pricing",
                   "menu")),
    ("testimonials", ("testimonial", "quote", "proof", "review",
                      "client words", "voices")),
    ("gallery", ("gallery", "image", "imagery", "photo", "work",
                 "mosaic")),
    ("cta", ("cta", "call to action", "invitation", "book", "closing",
             "conversion")),
    # B4: contact is bespoke-eligible — the loud moment may live in the
    # finale now (its form still rides by platform token, never rewritten).
    ("contact", ("contact", "form", "finale", "get in touch", " touch",
                 "message", "inquiry", "enquiry")),
)

# The complete --sx-* token contract — every variable page_shell's :root
# defines (brand_dna.css_variables), with its role. This IS the palette
# and type system a bespoke section may reference; anything else fails
# validation.
TOKEN_CONTRACT: Tuple[Tuple[str, str], ...] = (
    ("--sx-bg", "page ground — the section's default background"),
    ("--sx-surface", "raised surface one step off the ground (cards, panels)"),
    ("--sx-surface-2", "second surface step (nested panels, hover grounds)"),
    ("--sx-text", "primary text on the page ground"),
    ("--sx-muted", "secondary/supporting text"),
    ("--sx-accent", "THE brand accent — spend with intent (CTAs, accent words, rules)"),
    ("--sx-accent-soft", "soft wash of the accent (tints, soft rules, gradient tails)"),
    ("--sx-accent-strong", "deeper accent for hover/pressed states"),
    ("--sx-on-accent", "text/icons ON an accent-filled surface"),
    ("--sx-accent-ground", "GOVERNED accent for LARGE fills (full-bleed bands) — "
                           "chroma-capped; never use raw --sx-accent as a "
                           "section ground"),
    ("--sx-on-accent-ground", "text/icons on an accent-ground fill"),
    ("--sx-border", "hairlines and card borders"),
    ("--sx-authority", "the deep authority ground (the navy chapter-break) — "
                       "full-bleed color-block moments"),
    ("--sx-on-authority", "text on the authority ground"),
    ("--sx-accent-on-authority", "accent recalibrated for the authority ground"),
    ("--sx-accent-break", "the ONE deliberately-wrong accent (rule-break only; "
                          "may be undefined — always give a fallback: "
                          "var(--sx-accent-break, var(--sx-accent)))"),
    ("--sx-on-accent-break", "text on the wrong-accent (fallback var(--sx-on-accent))"),
    ("--sx-font-heading", "display face — headings only"),
    ("--sx-font-body", "body face"),
    ("--sx-font-accent", "editorial accent face — the italic accent word, pull-quotes, eyebrow flourishes (falls back to the heading face)"),
    ("--sx-secondary", "SECOND brand accent (present only when the brand carries one) — spend it as ONE section's family per the restraint budget, never everywhere"),
    ("--sx-secondary-soft", "soft wash of the second accent (present only with --sx-secondary)"),
    ("--sx-h1", "h1 scale (already clamp()ed)"),
    ("--sx-h2", "h2 scale (already clamp()ed)"),
    ("--sx-heading-weight", "display weight"),
    ("--sx-h2-weight", "h2 weight"),
    ("--sx-letter-tight", "negative tracking for display type"),
    ("--sx-section-pad", "the section's vertical padding rhythm (>=120px desktop)"),
    ("--sx-rhythm-base", "the page's vertical rhythm unit — space custom blocks at this, its -half or -quarter variants; any other vertical margin is an ad-hoc margin (doctrine D5: ONE RHYTHM)"),
    ("--sx-gutter", "horizontal page gutter"),
    ("--sx-content-max", "content max-width"),
    ("--sx-radius-card", "card corner radius"),
    ("--sx-radius-button", "button radius (pill)"),
    ("--sx-radius-image", "image frame radius"),
    ("--sx-ease", "the house easing curve — use it on every transition"),
    ("--sx-dur-quick", "content landing (~.45s) — text, buttons arriving"),
    ("--sx-dur-scene", "ornament pace (~.9s) — lines drawing, marks settling"),
    ("--sx-dur-grand", "ground pace (~1.6s) — backgrounds breathing in"),
    ("--sx-stagger", "the beat between siblings (~.12s) — delay steps"),
)


def atelier_enabled() -> bool:
    """Env gate, default ON. ATELIER_ENABLED=0 restores the exact Arc 7
    module-only pipeline (render_page emits no markers, no LLM calls)."""
    return (os.environ.get("ATELIER_ENABLED") or "1").strip().lower() not in (
        "0", "false", "no", "off")


def _model() -> str:
    return (os.environ.get("ATELIER_MODEL") or "").strip() or ATELIER_MODEL_DEFAULT


# ─── LLM plumbing (the drl/passes.py _call idiom) ─────────────────────

def _client():
    from anthropic import Anthropic
    key = os.environ.get("ANTHROPIC_API_KEY")
    return (Anthropic(api_key=key, timeout=_CALL_TIMEOUT_S, max_retries=1)
            if key else None)


def _call_llm(system: str, user: str, business_id: str) -> Optional[str]:
    """One bespoke-section call under the model ladder (Site Arc 12):
    family-scaled timeout, loud+breadcrumbed sonnet fallback on a
    model-identity error, same-model reduced-tokens retry on a timeout.
    Returns the raw text or None on total failure — the caller treats
    None as 'fall back to the module section', but that failure is now
    IMPOSSIBLE to be silent: logger.error + a site_config.model_fallbacks
    breadcrumb fire before None is returned."""
    import model_ladder

    client = _client()
    if client is None:
        logger.info("[atelier] no ANTHROPIC_API_KEY — skipping bespoke")
        return None
    # Site Arc 11 — log the model per call (the quality lever is
    # observable: Opus default vs an ATELIER_MODEL env override).
    logger.info(f"[atelier] authoring with model={_model()} for "
                f"{(business_id or 'unknown')[:8]}")

    def _do(model: str, max_tokens: int, timeout: float):
        return client.messages.create(
            model=model, max_tokens=max_tokens,
            system=system, messages=[{"role": "user", "content": user}],
            timeout=timeout,
            # Opus 4.7/4.8 / Sonnet 5 / Fable 400 on temperature —
            # omitted there, kept on Sonnet 4.x.
            **model_ladder.sampling_kwargs(model, ATELIER_TEMPERATURE),
        )

    try:
        # Provider switch (2026-07-18): the atelier was the one composer
        # stage still hardwired to Claude — Kevin's first true Kimi build
        # came back HYBRID (DRL stages on kimi-k3, atelier fragments on
        # claude-opus-4-8, visible in api_usage). Same branch as
        # drl/passes: on moonshot, site_llm handles the call (fail-open
        # to Anthropic); otherwise the Claude model ladder as before.
        import site_llm
        if site_llm.provider() == "moonshot":
            msg = site_llm.create_message(
                model=_model(), max_tokens=ATELIER_MAX_TOKENS,
                temperature=ATELIER_TEMPERATURE, system=system,
                user_content=user, timeout=90.0, task="atelier")
            used_model = getattr(msg, "model", "moonshot")
        else:
            msg, used_model = model_ladder.call_with_ladder(
                _do, model=_model(), task="atelier",
                business_id=business_id or "", max_tokens=ATELIER_MAX_TOKENS)
    except Exception as e:
        # Every rung failed. LOUD + breadcrumbed (to_model=None records
        # 'no rung succeeded') — a bare module-only page is never a
        # mystery again.
        logger.error(f"[atelier] LLM call failed on EVERY ladder rung for "
                     f"{(business_id or 'unknown')[:8]} "
                     f"(model={_model()}): {type(e).__name__}: {e}")
        model_ladder.record_model_fallback(
            business_id or "", task="atelier", from_model=_model(),
            to_model=None, reason=f"{type(e).__name__}: {e}")
        return None
    try:
        from api_usage_logger import log_api_usage_sync
        u = getattr(msg, "usage", None)
        log_api_usage_sync(
            endpoint="/composer/atelier", model=used_model,
            input_tokens=getattr(u, "input_tokens", 0) or 0,
            output_tokens=getattr(u, "output_tokens", 0) or 0,
            business_id=business_id, task_type="atelier")
    except Exception:
        pass
    return "".join(b.text for b in msg.content
                   if getattr(b, "type", None) == "text")


# ─── Planning ─────────────────────────────────────────────────────────

def _rule_break_module(dro: Optional[Dict[str, Any]]) -> Optional[str]:
    rb = ((dro or {}).get("decisions") or {}).get("rule_break")
    if not isinstance(rb, dict):
        return None
    blob = f"{rb.get('where') or ''} {rb.get('what') or ''}".lower()
    for mid, words in _WHERE_KEYWORDS:
        if any(w in blob for w in words):
            return mid
    return None


def plan_bespoke(dro: Optional[Dict[str, Any]], spec: List[Dict[str, Any]],
                 ctx: Dict[str, Any]) -> List[int]:
    """Which spec sections go bespoke. Budget: 2 sections, or 3 when the
    DRO authored a rule_break (the extra seat pays for the loud moment).
    ALWAYS the hero (where eyes land); then the section the rule-break
    lives in (else 'about'); never the data-dense modular sections."""
    by_module: Dict[str, int] = {}
    for i, s in enumerate(spec):
        mid = s.get("module")
        if isinstance(mid, str) and mid not in by_module:
            by_module[mid] = i

    def eligible(mid: Optional[str]) -> bool:
        return bool(mid) and mid in by_module and mid not in _NEVER_BESPOKE

    rb = ((dro or {}).get("decisions") or {}).get("rule_break")
    budget = 3 if isinstance(rb, dict) and (rb.get("what") or rb.get("where")) else 2

    picks: List[str] = []
    if eligible("hero"):
        picks.append("hero")

    rb_mid = _rule_break_module(dro)
    second = rb_mid if (eligible(rb_mid) and rb_mid not in picks) else None
    if second is None:
        for cand in ("about", "cta", "contact"):
            if eligible(cand) and cand not in picks:
                second = cand
                break
    if second:
        picks.append(second)

    if budget >= 3 and len(picks) < 3:
        for cand in ("about", "cta", "gallery", "testimonials", "offerings",
                     "contact"):
            if eligible(cand) and cand not in picks:
                picks.append(cand)
                break

    return sorted(by_module[m] for m in picks[:budget])


# ─── Section data (the ONLY facts the LLM may render) ─────────────────

def _section_data(kind: str, section_copy: Dict[str, Any],
                  ctx: Dict[str, Any]) -> Dict[str, Any]:
    biz = ctx.get("business") or {}
    bundle = ctx.get("bundle") or {}
    b = bundle.get("business") or {}
    intel = bundle.get("practitioner_intelligence") or {}
    booking = ctx.get("booking") or {}

    data: Dict[str, Any] = {
        "business_name": biz.get("name") or "",
        "business_type": biz.get("type") or "",
        "tagline": str(b.get("tagline") or "")[:200],
        "copy": {k: v for k, v in (section_copy or {}).items()
                 if isinstance(v, str) and v.strip()},
    }
    # Arc 10 "offer clarity" — the owner's own offer statement (from
    # site_prefs, sanitized upstream) rides the REAL DATA block so every
    # bespoke section makes the offer unmistakable.
    _prefs = (ctx.get("site_prefs")
              if isinstance(ctx.get("site_prefs"), dict) else {})
    _offer = str((_prefs or {}).get("offer") or "").strip()
    if _offer:
        data["what_the_business_offers"] = _offer[:600]
    # Creative-capture arc (2026-07-18) — the interview-v2 answers ride
    # the REAL DATA block. THE CREATIVE CONTRACT: these are the FLOOR,
    # not the ceiling — honor every constraint, then add instinct on top.
    for _k in ("type_personality", "structure"):
        _v = (_prefs or {}).get(_k)
        if isinstance(_v, str) and _v.strip():
            data[_k] = _v.strip()
    _stats = (_prefs or {}).get("proof_stats")
    if isinstance(_stats, list) and _stats:
        data["proof_stats_real_numbers"] = _stats[:3]
    _steps = (_prefs or {}).get("process_steps")
    if isinstance(_steps, list) and _steps:
        data["how_they_work_process"] = _steps[:5]
    cta_href = (booking.get("url") if booking.get("enabled") and booking.get("url")
                else "#contact")
    if kind in ("hero", "cta", "about", "offerings"):
        data["cta_href"] = cta_href
    if kind == "about":
        about = str(intel.get("about_business") or intel.get("about_me") or "")
        if about.strip():
            data["about"] = about.strip()[:700]
    if kind == "offerings":
        data["offerings"] = [
            {"name": o.get("name") or "",
             "price": o.get("price"),
             "description": str(o.get("description") or "")[:200]}
            for o in (ctx.get("offerings") or [])[:8]]
    if kind == "testimonials":
        quotes = []
        for t in (ctx.get("testimonials") or [])[:4]:
            if isinstance(t, dict):
                q = str(t.get("quote") or t.get("text") or t.get("content") or "").strip()
                if q:
                    quotes.append({"quote": q[:300],
                                   "author": str(t.get("author_name")
                                                 or t.get("name") or "")[:80]})
        data["testimonials"] = quotes
    if kind == "contact":
        # B4 — the finale's REAL wiring. The fragment renders these facts
        # (never invents handles/numbers); the working form itself does
        # NOT ride this block — it is platform markup, injected verbatim
        # per the WORKING FORM contract in build_bespoke_prompt.
        contact = ctx.get("contact") or {}
        data["contact_channels"] = {
            "email": str(contact.get("email") or ""),
            "phone": str(contact.get("phone") or ""),
            "hours": str(contact.get("hours") or ""),
            "address": str(contact.get("address") or ""),
            "socials": {str(k): str(v) for k, v in
                        (contact.get("social") or {}).items() if v},
        }
        if booking.get("enabled") and booking.get("url"):
            data["booking_url"] = str(booking["url"])
    return data


def _allowed_hrefs(data: Dict[str, Any]) -> List[str]:
    return [h for h in [data.get("cta_href")] if isinstance(h, str)
            and h.startswith("http")]


# ─── The prompt (the product) ─────────────────────────────────────────

# Phase 1 (Kimi design integration): THE DOCTRINE + creative contract
# wrap the atelier's system prompt for BOTH providers (Symmetry Rule
# — prompt content is never provider-gated; fallback keeps the law).
from design_doctrine import DOCTRINE as _DOCTRINE, DIVERSITY_LINE as _DIVERSITY, CREATIVE_CONTRACT as _CONTRACT

_SYSTEM_PROMPT = _DOCTRINE + "\n\n" + _CONTRACT + "\n\n" + """You are a senior creative director and master frontend craftsperson working in a design atelier. You art-direct ONE section of a production website — not a template slot, a composition. You read a design rationale the way a designer reads a brief: you feel the tension, hear the organizing concept, and then build the moment where the visitor's eyes land.

You output exactly one <section> fragment plus its CSS. The platform owns the page shell, the design tokens, the fonts, and every other section — your section must sit inside that system flawlessly while feeling unmistakably art-directed. The difference between great and mediocre is specificity: great design encodes THIS business's actual character; mediocre design fills a layout with its data.

WHAT GREAT LOOKS LIKE (real reference moves — inspiration vocabulary, not a checklist):
- A display headline anchored in the lower third of the viewport, a founder's italic quote sitting beside it — authority plus intimacy in one frame.
- A numbered offerings list (I, II, III) with prices right-aligned in a hairline column — editorial confidence instead of three cards.
- One accent-colored italic word inside every heading — the emotional core of the line, and the visual thread of the whole page.
- A full-bleed color-blocked band on the authority ground as punctuation between chapters — braver than any gradient.
- A pull-quote set oversized in the display serif italic — a magazine-spread moment inside the page.
- Floating diamond ornaments (rotated squares) at .04-.08 opacity — depth the eye discovers, never notices.
- A full-bleed hero where the headline rests on the FLOOR of the viewport (align-items:flex-end), under a scrim that deepens only toward the words (15% at the top → 85% at the baseline) — a film title, not a centered caption.
- A headline that lands word by word — each word rises on its own delay (0.15s apart, ~0.6s each), and exactly one word shifts to italic in the accent color mid-sentence.
- A third type voice: micro-caps at 9-11px with 0.18-0.34em tracking carrying every eyebrow, label, price and button — the whisper that makes the display feel monumental (a ~40:1 size gap on one page).
- Designed silence between chapters: a 60-80px band holding nothing but a centered 48px hairline, or a full-width gradient thread at 20% opacity — the page pauses on purpose.
- A statement bar as an interstitial title card: one italic display sentence, centered, on a full-width band washed with var(--sx-accent-soft).
- An offerings list set as an engraved menu: 0.5px rules, italic serif names, whisper-caps prices right-aligned; hovering a row indents it 1rem and draws a hairline across its top (scaleX(0)→scaleX(1), transform-origin left).
- Ghost chapter numerals — clamp(4rem, 9vw, 7rem) display digits at rgba(255,255,255,.04) on dark grounds (rgba(0,0,0,.05) on light), absolutely positioned into a section corner, behind the content.
- Miniature evidence dioramas instead of icons: a postage-stamp mock-UI built from pure CSS (26px browser-chrome bar, 6px traffic-light dots, 3-8px skeleton lines, a tiny tinted focal block) showing the actual kind of work.

WHAT MEDIOCRE LOOKS LIKE (never do these):
- Centered "Welcome to [Business]" + generic value prop + "Get Started".
- A three-card grid with stock icons; "Why Choose Us" / "What Clients Say" labels.
- Copy that could belong to any business in the category.

You never invent facts, prices, testimonials or credentials. You render ONLY the data you are given, in the concept's voice."""


def _fmt_decision(name: str, block: Any, keys: Tuple[str, ...]) -> str:
    if not isinstance(block, dict):
        return ""
    bits = [f"{k}={block[k]}" for k in keys if block.get(k)]
    because = str(block.get("because") or "").strip()
    line = f"- {name}: " + ("; ".join(bits) if bits else "(authored)")
    if because:
        line += f"\n    because: {because}"
    return line


def _dro_block(dro: Dict[str, Any]) -> str:
    d = (dro or {}).get("decisions") or {}
    hero = d.get("hero_concept") or {}
    tension = d.get("tension") or {}
    rb = d.get("rule_break") or {}
    fi = d.get("first_impression") or {}
    lines = [
        "THE DESIGN RATIONALE — this brief is the law of the page:",
        f"- ORGANIZING CONCEPT: {hero.get('concept_statement') or '(none)'}",
        f"    hero direction: {hero.get('direction') or ''}; "
        f"metaphor elements: {', '.join(str(m) for m in (hero.get('metaphor_elements') or [])) or '(none)'}",
    ]
    if isinstance(tension, dict) and tension.get("pole_a"):
        lines.append(f"- TENSION: '{tension.get('pole_a')}' vs "
                     f"'{tension.get('pole_b')}' — {tension.get('expression') or ''}")
    if isinstance(rb, dict) and (rb.get("what") or rb.get("where")):
        lines.append(f"- THE ONE RULE-BREAK: {rb.get('what') or ''} — "
                     f"placed at: {rb.get('where') or ''}"
                     + (f"\n    because: {rb.get('because')}" if rb.get("because") else ""))
    if isinstance(fi, dict) and (fi.get("feel_in_3s") or fi.get("remember")):
        lines.append(f"- FIRST 3 SECONDS: feel = {fi.get('feel_in_3s') or ''}; "
                     f"remember = {fi.get('remember') or ''}")
    for name, keys in (("palette", ("base", "temperature", "accent_strategy")),
                       ("typography", ("display_personality", "scale_contrast")),
                       ("layout", ("symmetry", "density", "hierarchy_approach")),
                       ("motion", ("temperature", "signature_move")),
                       ("whitespace", ("philosophy",))):
        row = _fmt_decision(name, d.get(name), keys)
        if row:
            lines.append(row)
    notes = (d.get("voice_to_visual") or {}).get("notes")
    if isinstance(notes, list) and notes:
        lines.append("- voice→visual: " + "; ".join(str(n) for n in notes[:4]))
    return "\n".join(lines)


def _token_block() -> str:
    return "\n".join(f"  var({name})  — {role}" for name, role in TOKEN_CONTRACT)


def _accent_scarcity_line(dro: Dict[str, Any]) -> str:
    """Site Arc 9 — when the DRO rules accent scarcity, the atelier gets
    the same discipline the module renderer enforces via body class."""
    strategy = str((((dro or {}).get("decisions") or {}).get("palette") or {})
                   .get("accent_strategy") or "").lower()
    if not any(w in strategy for w in ("single_semantic", "scarce", "scarcity")):
        return ""
    return ("\n- ACCENT SCARCITY (from the rationale): the accent is "
            "semantic — CTAs and one italic word per heading; never "
            "grounds, frames, or large fills.")


def _photo_reality_block(allowed_slots: Tuple[str, ...],
                         slot_records: Optional[Dict[str, Any]]) -> str:
    """Site Arc 9 — describe the ACTUAL photographs already assigned to
    the section's allowed slots (subject/search, source, credit), so the
    composition is built around the real image, not an imagined one."""
    lines: List[str] = []
    for s in allowed_slots:
        r = (slot_records or {}).get(s)
        if not isinstance(r, dict):
            continue
        url = r.get("custom_url") or r.get("default_url")
        if not url:
            continue
        source = ("owner upload" if r.get("custom_url")
                  else str(r.get("default_source") or "stock"))
        subject = str(r.get("default_query")
                      or r.get("default_dalle_prompt") or "").strip()[:120]
        credit = str(((r.get("default_credit") or {}) or {}).get("name") or "")
        bits = [f'"{s}" — {source}']
        if subject:
            bits.append(f"subject: {subject}")
        if credit:
            bits.append(f"photographer: {credit}")
        lines.append("  - " + "; ".join(bits))
    if not lines:
        return ""
    return ("\n\nPHOTO REALITY — the actual photographs already assigned to "
            "your allowed slots:\n" + "\n".join(lines)
            + "\nCompose around the actual photograph, or choose a "
              "constructed ornament-field treatment instead when the "
              "subject is weak or off-concept.")


def _contract_block(kind: str, uid: str, dom_id: str, slots_line: str,
                    hrefs_line: str, copy_fields: List[str]) -> str:
    """The HARD OUTPUT CONTRACT + OUTPUT FORMAT tail shared by the
    bespoke prompt and the refine prompt (Site Arc 11) — one text, one
    validator, no drift."""
    return f"""HARD OUTPUT CONTRACT — violations are rejected by a validator:
1. Exactly ONE root element: <section id="{dom_id}" class="atl-{uid} ...">…</section>. Nothing outside it.
2. Every CSS selector is prefixed with .atl-{uid} (e.g. ".atl-{uid} .crest"). No bare element/class/#id selectors. @media queries allowed; @keyframes names must start with atl-{uid}. The atl-{uid} class itself appears ONLY on the root <section> — child elements get plain role classes (class="crest", never class="atl-{uid} crest"): repeating the scope class makes the root's base rule (min-height, flex, section padding) cascade onto every child and destroys the layout.
3. Colors ONLY: var(--sx-*), transparent, currentColor, rgba(0,0,0,X), rgba(255,255,255,X). NO hex, NO rgb()/hsl(), no named colors.
4. Fonts ONLY var(--sx-font-heading) / var(--sx-font-body) / var(--sx-font-accent) — the accent face is for italic editorial moments (one accent word in a heading, a pull-quote), never body text.
5. Images ONLY as <img data-slot="…" src="" alt="specific, evocative alt"> with data-slot from: {slots_line}. Each slot at most once. The platform fills src.
6. Every text element rendering a provided copy field carries data-override-target="{kind}/<field>" (fields provided: {', '.join(copy_fields) or '(none)'} — each must appear exactly once). TOTAL EDITABILITY: any ADDITIONAL display text you invent (a label, a kicker, a closing line) must carry its own data-override-target="{kind}/custom_1", "{kind}/custom_2", … numbered sequentially — every visible word on the page must be editable. Business facts you were given (prices, names) are rendered verbatim and need no extra target beyond the provided fields.
7. Links: href is a #anchor or one of: {hrefs_line}. NO other URLs anywhere (no imports, no url(), no external anything).
8. NO <script>, NO <style> tags in the HTML, NO inline event handlers, NO position:fixed, NO id selectors in CSS.
9. Responsive: include at least one @media (max-width: 760px) block that keeps the composition intact on a phone.
10. Any animation respects @media (prefers-reduced-motion: reduce).
11. Size: HTML ≤ 14KB, CSS ≤ 10KB.

OUTPUT FORMAT — exactly this, nothing else:
<!--HTML-->
<section id="{dom_id}" class="atl-{uid} …">…</section>
<!--CSS-->
.atl-{uid} {{ … }}
…

After the final closing brace of your last CSS rule, output NOTHING — no closing tags, no commentary, no code fences."""


def build_bespoke_prompt(kind: str, variant_hint: Optional[str], uid: str,
                         dro: Dict[str, Any], data: Dict[str, Any],
                         allowed_slots: Tuple[str, ...],
                         allowed_hrefs: List[str],
                         slot_records: Optional[Dict[str, Any]] = None,
                         feedback: str = "",
                         form_token: bool = False) -> str:
    """The user prompt for one bespoke section — the DRO fused with the
    original creative-director voice, the real data, the full token
    contract, and the hard output contract the validator enforces.
    `feedback` (A2, 2026-07-18) carries the vision grader's notes from a
    FAILED previous render — the bounded quality regen injects it so the
    second take fixes what the grader actually flagged.
    `form_token` (B4, contact only): require the <!--CONTACT_FORM-->
    placement token — the platform substitutes the live form markup."""
    copy_fields = sorted((data.get("copy") or {}).keys())
    _fb = ""
    if (feedback or "").strip():
        _fb = ("\n\nGRADER FEEDBACK FROM THE PREVIOUS RENDER OF THIS PAGE — "
               "the last version FAILED design grading. Fix EVERY point "
               "below with materially different choices, not small tweaks:\n"
               + feedback.strip()[:900])
    _form_block = ""
    if form_token:
        _form_block = f"""

WORKING FORM — PLATFORM MARKUP BY TOKEN:
- This page has a LIVE contact form (real messages reach the owner). You never write it: place the exact token {_FORM_TOKEN} on its own line, EXACTLY ONCE, where the form belongs in your composition (inside a card, a column, an offset panel — your call).
- The platform substitutes the real form there, ships its base styles, and wires its submit + SMS-consent logic. Never build a form yourself, never wrap the token in a <form>, never add handlers, never fake a static form, never emit the token twice.
- You MAY theme around it: your CSS can target ".atl-{uid} .sxm-contact-form …" (its inputs and the .sxm-cta submit) to seat the form inside your composition."""
    slots_line = (", ".join(f'"{s}"' for s in allowed_slots)
                  if allowed_slots else "(none — this section uses NO images)")
    hrefs_line = (", ".join(allowed_hrefs) if allowed_hrefs
                  else "(none — links may only be #anchors like #contact)")
    dom_id = _SECTION_DOM_IDS.get(kind, kind)
    return f"""{_dro_block(dro)}{_photo_reality_block(allowed_slots, slot_records)}{_fb}{_form_block}

YOUR SECTION
- Kind: "{kind}" — you are replacing the platform's modular "{kind}" section (its library variant would have been "{variant_hint or 'default'}"; transcend it, don't imitate it).
- This section must read as ART-DIRECTED, not templated: reach for compound layouts, overlapping elements, editorial asymmetry, an oversized type moment, or a quiet ornament field — whichever serves the concept. One idea, executed completely, beats three ideas gestured at.

REAL DATA (the ONLY facts you may render — every price/number/claim on screen must literally appear here):
{json.dumps(data, indent=2, ensure_ascii=False)}

TOKEN CONTRACT — the page shell defines these CSS variables; they are your entire palette and type system:
{_token_block()}

CRAFT BAR (non-negotiable):
- One accent-colored italic word per heading: wrap it as <em class="sxm-accent-word">word</em> — the emotional core of the line.
- Vertical generosity: the section breathes at 120px+ top/bottom on desktop (var(--sx-section-pad) or more). Cramped is cheap.
- CHAPTER RHYTHM: the section may claim var(--sx-surface) or var(--sx-authority) as a deliberate chapter break — the page must never read as one continuous ground.
- DATA DIGNITY: a price of 0 renders as the word "Free" (never "$0"); omit the price line entirely for placeholder-grade prices under $5; never render an empty action area — every card foot ends in a working CTA or a real fact.{_accent_scarcity_line(dro)}
- Gradients only ever FADE — every gradient ends in transparency or the ground it sits on; never a hard-edged band of translucent color.
- THREE VOICES, NOT TWO: any label, eyebrow, price or button smaller than body size is set as micro-caps (11px or less, tracking 0.16em or more, never bold display weight) — the whisper voice is what makes the display voice monumental.
- SEAMS ARE DESIGNED: your section never simply abuts its neighbors — its top or bottom boundary carries something deliberate (a quiet band of air, a fading hairline thread, or a ground change).
- ORNAMENTS STAY SUB-PERCEPTUAL: watermarks/crests at 0.04-0.05 opacity, symbols and dividers at 0.08 or less, ghost numerals at 0.04-0.06 — depth the eye discovers on the second look, never the first.
- SCRIMS ARE DIRECTIONAL: a gradient over a photograph always deepens toward the text edge and stays at 30% or less at the photo's far edge — the image must keep breathing.
- HOVERS DRAW, THEY DON'T GLOW: hover feedback is a line drawing itself (scaleX from an origin), a lift of 2px or less, or a gap widening — never a box-shadow bloom or a color flood.
- MOTION IS STAGED ON ARRIVAL: the platform holds every animation in your section PAUSED until the visitor scrolls to it, then releases the whole chain. Author your entrance with animation-delays from 0s exactly as if the section is already on screen — it will play at the perfect moment. Full entrance settled within ~2.5s (delays past 4s are rejected).
- MOTION DEPTH LADDER: three planes moving at three speeds is what reads as depth — the ground breathes in slowest (var(--sx-dur-grand)), ornaments draw at mid pace (var(--sx-dur-scene)), content lands crisp and last (var(--sx-dur-quick)), siblings stepping in var(--sx-stagger) apart.
- MOTION STAYS HOME: everything that moves lives INSIDE the section — the root keeps overflow:hidden whenever anything animates position or is absolutely placed; moving decorations sit on a layer BEHIND content (content wrapper position:relative with the higher z-index); nothing animated ever crosses a neighboring section or slides under running text.
- ANIMATE ONLY transform/opacity (plus SVG stroke-dashoffset/filter): never width, height, top, left, or margins — those re-layout every frame and stutter on phones.
- AMBIENT LOOPS: at most one infinite loop per section, sub-perceptual (an opacity or scale drift of 3% or less), never beneath body text.
- HEADLINE INTEGRITY: the h1/h2 must read as a complete, correct sentence as PLAIN TEXT (CSS off) — that text is what screen readers speak, search engines index, and copy-paste yields. NEVER split a headline across hidden/aria-hidden/sr-only spans, never word-morph one word into another, never echo headline words in duplicate spans. Animate the whole heading or whole visible words landing; the markup itself contains each word exactly once, in reading order.
- Fluid display type via clamp(); tight negative tracking (var(--sx-letter-tight)) on display sizes.
- Transitions use var(--sx-ease); reveals may use the shared class "sxm-reveal" (the platform's IntersectionObserver picks it up).
- CTAs may use the shared class "sxm-cta" (pill, shimmer, working styles ship with the shell).

{_contract_block(kind, uid, dom_id, slots_line, hrefs_line, copy_fields)}"""


# ─── Generation ───────────────────────────────────────────────────────

def _strip_css_tail_junk(css: str) -> str:
    """The CSS part is everything after <!--CSS--> to end-of-response, so
    any trailing artifact the model emits lands in the stylesheet verbatim.
    A single stray token like '</section>' makes the browser's CSS parser
    discard the junk AND the entire next rule — which in an assembled page
    is the NEXT fragment's base rule (this took down two sections of a
    live page). Strip code fences and trailing closing tags."""
    css = css.strip()
    css = re.sub(r"^```[a-zA-Z]*\s*", "", css)
    css = re.sub(r"```+\s*$", "", css)
    # Trailing closing tags ('</section>', '</style>', leaked tool syntax…)
    css = re.sub(r"(?:\s*</[A-Za-z][^>]*>)+\s*$", "", css)
    return css.strip()


def _descope_child_uids(html: str, uid: str) -> str:
    """Keep the atl-{uid} scope class ONLY on the root <section>.

    Some rolls stamp the uid class on EVERY element. Descendant selectors
    still work either way, but the fragment's base rule '.atl-{uid} {…}'
    (min-height, flex, section padding) then cascades onto every child —
    an h1 with min-height:88vh, divs turned into flex rows — and the
    layout detonates. Deterministic heal: strip the token from every
    element after the root tag."""
    token = f"atl-{uid}"
    m = re.search(r"<section\b[^>]*>", html)
    root_end = m.end() if m else 0

    def _clean(mm: "re.Match[str]") -> str:
        classes = [c for c in mm.group(2).split() if c != token]
        return mm.group(1) + " ".join(classes) + mm.group(3)

    head, tail = html[:root_end], html[root_end:]
    tail = re.sub(r'(class\s*=\s*")([^"]*)(")', _clean, tail)
    tail = re.sub(r"(class\s*=\s*')([^']*)(')", _clean, tail)
    return head + tail


_AUDIT_COMMENT_RE = re.compile(
    r"<!--\s*(DERIVATION|INVENTION|EXCEPTION)\s*:\s*(.*?)-->", re.DOTALL | re.IGNORECASE)


def _log_audit_comments(raw: str, kind: str, business_id: str) -> None:
    """Phase 1 telemetry: surface the model's derivation / invention /
    exception audit trail in the logs. The exception register (weekly
    aggregation -> vocabulary roadmap) is Phase 2; this feed is what it
    will read. Never raises."""
    try:
        for label, body in _AUDIT_COMMENT_RE.findall(raw or ""):
            text = " ".join(str(body).split())[:300]
            if not text:
                continue
            lvl = logger.info
            if label.upper() == "EXCEPTION" and text.strip().lower() not in ("none", "none.", '"none"'):
                lvl = logger.warning  # wanted-but-blocked = vocabulary gap
                # Phase 2: persist into the exception register.
                try:
                    from design_register import record_exception
                    record_exception(business_id or "", f"atelier:{kind}", text)
                except Exception:
                    pass
            lvl(f"[atelier-audit] {label.upper()} ({kind}, "
                f"{(business_id or 'unknown')[:8]}): {text}")
    except Exception:
        pass


def _split_fragment(raw: str, uid: str = "") -> Optional[Tuple[str, str]]:
    """Parse the <!--HTML--> / <!--CSS--> delimited response, then
    sanitize both parts (tail junk out of the CSS, uid scope class off
    child elements)."""
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
    html, css = m.group(1).strip(), _strip_css_tail_junk(m.group(2))
    if not html or not css:
        return None
    if uid:
        html = _descope_child_uids(html, uid)
    return html, css


def generate_bespoke_section(kind: str, variant_hint: Optional[str],
                             dro: Dict[str, Any], ctx: Dict[str, Any],
                             section_copy: Dict[str, Any],
                             business_id: str = "",
                             feedback: str = "") -> Optional[Tuple[str, str]]:
    """One bespoke section: ONE LLM call, deterministic validation, one
    repair attempt, else None (caller keeps the module section).
    `feedback` (A2) = the vision grader's notes from a failed previous
    render, injected by the bounded quality regen."""
    import atelier_validator

    uid = uuid4().hex[:8]
    data = _section_data(kind, section_copy, ctx)
    allowed_slots = ALLOWED_SLOTS.get(kind, ())
    allowed_hrefs = _allowed_hrefs(data)
    required_targets = [f for f, v in (data.get("copy") or {}).items()
                        if str(v or "").strip()]
    allowed_fields = _module_fields(kind)
    # B4 — bespoke contact: the working form rides by token. form_html ''
    # means no live form exists → no token requirement (solo finale).
    form_html, _form_script = (_contact_form(ctx) if kind == "contact"
                               else ("", ""))
    # Site Arc 9 (PHOTO REALITY): the stored slot records describe the
    # actual photographs the section will receive. Fail-soft — a missing
    # row / offline test context just omits the block.
    slot_records: Optional[Dict[str, Any]] = None
    if allowed_slots and business_id:
        try:
            from agents.slot_system import slot_storage
            slot_records = slot_storage.get_all_slots(business_id) or {}
        except Exception:
            slot_records = None
    prompt = build_bespoke_prompt(kind, variant_hint, uid, dro, data,
                                  allowed_slots, allowed_hrefs,
                                  slot_records=slot_records,
                                  feedback=feedback,
                                  form_token=bool(form_html))

    # Phase 1 — instructed diversity (K1) + the audit trail (K2):
    # derivation / invention / exception ride as HTML comments BEFORE
    # the <!--HTML--> marker, so the fragment contract is untouched
    # (_split_fragment anchors on the marker and ignores the preamble).
    audit_clause = (
        "\n\n" + _DIVERSITY + "\n"
        "Before the <!--HTML--> marker, output exactly three single-line comments:\n"
        "<!--DERIVATION: the 2-4 signals you read and what they imply-->\n"
        "<!--INVENTION: one thing you added that is NOT in the brief, and the constraint it builds on-->\n"
        "<!--EXCEPTION: anything you wanted that the spec cannot express, or none-->\n"
        "Then the standard <!--HTML--> / <!--CSS--> fragment."
    )

    def _attempt(extra: str = "") -> Tuple[Optional[Tuple[str, str]], List[str]]:
        raw = _call_llm(_SYSTEM_PROMPT, prompt + audit_clause + extra, business_id or "unknown")
        if raw is None:
            return None, ["LLM call failed"]
        _log_audit_comments(raw, kind, business_id)
        frag = _split_fragment(raw, uid)
        if frag is None:
            return None, ["response missing <!--HTML--> / <!--CSS--> delimiters "
                          "or an empty part"]
        ok, problems = atelier_validator.validate_fragment(
            frag[0], frag[1], uid=uid, kind=kind, data=data,
            allowed_slots=allowed_slots, required_targets=required_targets,
            allowed_hrefs=allowed_hrefs, allowed_fields=allowed_fields)
        # B4 — the working-form token: exactly one placement, then the
        # platform substitutes the live form markup (deterministic — the
        # form's endpoint/names/consent wiring cannot drift).
        if ok and form_html:
            n_tok = frag[0].count(_FORM_TOKEN)
            if n_tok != 1:
                ok = False
                problems = [f"the working-form token {_FORM_TOKEN} must "
                            f"appear exactly once in the HTML (found {n_tok})"] \
                    + list(problems)
        if ok and form_html:
            frag = (frag[0].replace(_FORM_TOKEN, form_html), frag[1])
        return (frag if ok else None), problems

    frag, problems = _attempt()
    if frag is None and problems:
        repair = ("\n\nYOUR PREVIOUS OUTPUT FAILED VALIDATION. Problems:\n- "
                  + "\n- ".join(problems[:12])
                  + "\n\nFix EVERY problem. Re-read the HARD OUTPUT CONTRACT. "
                    "Output ONLY the <!--HTML--> / <!--CSS--> fragment.")
        frag, problems = _attempt(repair)
    if frag is None:
        logger.warning(f"[atelier] fell back: {kind} for "
                       f"{(business_id or 'unknown')[:8]} — {problems[:6]}")
        return None
    logger.info(f"[atelier] bespoke '{kind}' accepted for "
                f"{(business_id or 'unknown')[:8]} (uid atl-{uid}, "
                f"html {len(frag[0])}B css {len(frag[1])}B)")
    return frag


def _module_fields(kind: str) -> Tuple[str, ...]:
    """The module's declared copy fields (site_modules registry) — the
    validator accepts these as override-target suffixes alongside the
    provided fields and custom_N. Fail-soft to () offline."""
    try:
        import site_modules
        return tuple((site_modules.MODULES.get(kind) or {}).get("fields") or ())
    except Exception:
        return ()


# ─── Site Arc 11 — THE RESIDENT CREATOR: refine one section ──────────

_REFINE_SYSTEM_PROMPT = _SYSTEM_PROMPT + """

REFINE MODE: this session you are not starting from a blank brief — you are REVISING one existing section of a live page at its owner's request. You receive the section's current HTML+CSS and one plain-words instruction ('make it moodier', 'more space', 'bolder type'). Honor the instruction decisively — the owner must SEE the change — while keeping everything that already works: the real data, the working links, the copy's override targets, the design system's discipline. You re-author the section fresh under a NEW scope uid; never echo the old atl- classes."""


def build_refine_prompt(kind: str, uid: str, dro: Dict[str, Any],
                        data: Dict[str, Any], current_html: str,
                        current_css: str, instruction: str,
                        allowed_slots: Tuple[str, ...],
                        allowed_hrefs: List[str],
                        form_token: bool = False) -> str:
    """The refine-mode user prompt: the DRO brief, the CURRENT section
    (html+css), the owner's instruction, the real data, the token
    contract, and the SAME hard output contract the validator enforces
    (shared _contract_block — one contract, no drift).
    `form_token` (B4, contact only): the current section's live form
    must exit as the <!--CONTACT_FORM--> placement token."""
    copy_fields = sorted((data.get("copy") or {}).keys())
    slots_line = (", ".join(f'"{s}"' for s in allowed_slots)
                  if allowed_slots else "(none — this section uses NO images)")
    hrefs_line = (", ".join(allowed_hrefs) if allowed_hrefs
                  else "(none — links may only be #anchors like #contact)")
    dom_id = _SECTION_DOM_IDS.get(kind, kind)
    _form_line = (f"\n- THE WORKING FORM: the current section's <form> is "
                  f"LIVE platform markup (real messages reach the owner). "
                  f"In your output its whole block becomes the exact token "
                  f"{_FORM_TOKEN} on its own line, EXACTLY ONCE, where the "
                  f"form belongs — the platform substitutes the real form "
                  f"(styled + wired). Never rewrite, rename or fake it."
                  if form_token else "")
    return f"""{_dro_block(dro)}

THE OWNER'S INSTRUCTION (the reason for this revision — honor it visibly):
"{instruction.strip()}"

THE CURRENT "{kind}" SECTION — revise THIS, don't start over blindly. Keep its facts, links and copy targets; change what the instruction asks for (and whatever craft the change demands):
<!--CURRENT HTML-->
{current_html.strip()}
<!--CURRENT CSS-->
{current_css.strip()}

REAL DATA (the ONLY facts you may render — every price/number/claim on screen must literally appear here):
{json.dumps(data, indent=2, ensure_ascii=False)}

TOKEN CONTRACT — the page shell defines these CSS variables; they are your entire palette and type system:
{_token_block()}

REVISION BAR (non-negotiable):
- The instruction must be VISIBLE in the result — a side-by-side look shows the change immediately.
- Everything the current section says stays sayable: keep every provided copy field (same data-override-target paths) unless the instruction explicitly asks for different wording of platform framing.
- Keep the craft bar of the house: one accent-italic word per heading, whisper-voice micro-caps for small labels, directional scrims, gradients that fade, hovers that draw, generous vertical air, reduced-motion respect.
- Your output is scoped under the NEW uid atl-{uid} — do not reuse the old section's atl- classes or ids.{_form_line}

{_contract_block(kind, uid, dom_id, slots_line, hrefs_line, copy_fields)}"""


def generate_refined_section(kind: str, current_html: str, current_css: str,
                             instruction: str, dro: Dict[str, Any],
                             ctx: Dict[str, Any],
                             section_copy: Dict[str, Any],
                             business_id: str = "") -> Optional[Tuple[str, str]]:
    """One refined section (Site Arc 11 'resident creator'): ONE
    atelier-style call revising the CURRENT section under the owner's
    instruction, same validator, one repair attempt, else None (the
    caller reports an honest 'couldn't refine')."""
    import atelier_validator

    uid = uuid4().hex[:8]
    data = _section_data(kind, section_copy, ctx)
    allowed_slots = ALLOWED_SLOTS.get(kind, ())
    allowed_hrefs = _allowed_hrefs(data)
    required_targets = [f for f, v in (data.get("copy") or {}).items()
                        if str(v or "").strip()]
    allowed_fields = _module_fields(kind)
    # B4 — refined contact: the live form exits as the placement token,
    # substituted after validation (same contract as the bespoke path).
    form_html, _form_script = (_contact_form(ctx) if kind == "contact"
                               else ("", ""))
    prompt = build_refine_prompt(kind, uid, dro or {}, data, current_html,
                                 current_css, instruction, allowed_slots,
                                 allowed_hrefs, form_token=bool(form_html))

    def _attempt(extra: str = "") -> Tuple[Optional[Tuple[str, str]], List[str]]:
        raw = _call_llm(_REFINE_SYSTEM_PROMPT, prompt + extra,
                        business_id or "unknown")
        if raw is None:
            return None, ["LLM call failed"]
        frag = _split_fragment(raw, uid)
        if frag is None:
            return None, ["response missing <!--HTML--> / <!--CSS--> delimiters "
                          "or an empty part"]
        ok, problems = atelier_validator.validate_fragment(
            frag[0], frag[1], uid=uid, kind=kind, data=data,
            allowed_slots=allowed_slots, required_targets=required_targets,
            allowed_hrefs=allowed_hrefs, allowed_fields=allowed_fields)
        # B4 — the working-form token (see generate_bespoke_section).
        if ok and form_html:
            n_tok = frag[0].count(_FORM_TOKEN)
            if n_tok != 1:
                ok = False
                problems = [f"the working-form token {_FORM_TOKEN} must "
                            f"appear exactly once in the HTML (found {n_tok})"] \
                    + list(problems)
        if ok and form_html:
            frag = (frag[0].replace(_FORM_TOKEN, form_html), frag[1])
        return (frag if ok else None), problems

    frag, problems = _attempt()
    if frag is None and problems:
        repair = ("\n\nYOUR PREVIOUS OUTPUT FAILED VALIDATION. Problems:\n- "
                  + "\n- ".join(problems[:12])
                  + "\n\nFix EVERY problem. Re-read the HARD OUTPUT CONTRACT. "
                    "Output ONLY the <!--HTML--> / <!--CSS--> fragment.")
        frag, problems = _attempt(repair)
    if frag is None:
        logger.warning(f"[atelier] refine fell back: {kind} for "
                       f"{(business_id or 'unknown')[:8]} — {problems[:6]}")
        return None
    logger.info(f"[atelier] refined '{kind}' accepted for "
                f"{(business_id or 'unknown')[:8]} (uid atl-{uid}, "
                f"html {len(frag[0])}B css {len(frag[1])}B)")
    return frag


# ─── Assembly: marker-based replacement ───────────────────────────────

def _stamp_dom_id(fragment_html: str, kind: str) -> str:
    """Guarantee the root <section> carries the module's stable DOM id
    (header nav anchors + the quality gate's sections_rendered check)."""
    dom_id = _SECTION_DOM_IDS.get(kind)
    if not dom_id:
        return fragment_html
    m = re.search(r"<section\b[^>]*>", fragment_html)
    if not m or re.search(r"\bid\s*=", m.group(0)):
        return fragment_html
    return (fragment_html[:m.start()]
            + m.group(0)[:-1].rstrip() + f' id="{dom_id}">'
            + fragment_html[m.end():])


def _stamp_stage(fragment_html: str) -> str:
    """Motion System (2026-07-10): add sxm-stage to the bespoke root so
    the page's IntersectionObserver releases the section's paused
    entrance animations on arrival (.sxm-in). Deterministic assembly
    step — the model never writes this class itself. Unlike sxm-reveal,
    sxm-stage carries NO opacity/transform of its own: the fragment's
    authored choreography IS the entrance, staged instead of doubled."""
    m = re.search(r"<section\b[^>]*>", fragment_html)
    if not m or "sxm-stage" in m.group(0):
        return fragment_html
    tag = m.group(0)
    cm = re.search(r'(class\s*=\s*")([^"]*)(")', tag) or \
         re.search(r"(class\s*=\s*')([^']*)(')", tag)
    if cm:
        new_tag = tag[:cm.start(2)] + cm.group(2).rstrip() + " sxm-stage" + tag[cm.end(2):]
    else:
        new_tag = tag[:-1].rstrip() + ' class="sxm-stage">'
    return fragment_html[:m.start()] + new_tag + fragment_html[m.end():]


def replace_sections(html: str, fragments: Dict[str, Dict[str, Any]]
                     ) -> Tuple[str, List[str]]:
    """Swap each marked module section (<!--sx:{module}:{i}--> … end
    marker) for its bespoke fragment. Returns (html, replaced_modules).
    Fragments whose marker is absent are skipped silently (e.g. the
    section was legitimately dropped this render)."""
    replaced: List[str] = []
    for mid, frag in fragments.items():
        f_html = str((frag or {}).get("html") or "")
        if not f_html.strip():
            continue
        stamped = _stamp_stage(_stamp_dom_id(f_html, mid))
        pattern = re.compile(
            rf"<!--sx:{re.escape(mid)}:(\d+)-->.*?<!--/sx:{re.escape(mid)}:\1-->",
            re.DOTALL)
        new_html, n = pattern.subn(
            lambda m: f"<!--sx:{mid}:{m.group(1)}-->{stamped}<!--/sx:{mid}:{m.group(1)}-->",
            html, count=1)
        if n:
            html = new_html
            replaced.append(mid)
    return html, replaced


def _inject_css(html: str, css: str) -> str:
    """Bespoke CSS rides its own <style id="sx-atelier"> appended after
    the shell's module <style> (page_shell untouched; later rules win
    the cascade at equal specificity, and .atl- scoping wins anyway)."""
    block = f'<style id="sx-atelier">\n{css}\n</style>'
    if "</head>" in html:
        return html.replace("</head>", block + "\n</head>", 1)
    return html + block


def _report(cb, pct: int, stage: str) -> None:
    """Arc 10 — fail-soft progress ping (chief_jobs loading bar). Local
    twin of site_composer._report_progress: atelier must not import
    site_composer (cycle), and a cb error must never break a compose."""
    if cb is None:
        return
    try:
        cb(pct, stage)
    except Exception as e:
        logger.debug(f"[atelier] progress cb error (ignored): {e}")


def run_atelier(html: str, spec: List[Dict[str, Any]], ctx: Dict[str, Any],
                dro: Optional[Dict[str, Any]], business_id: str, *,
                regenerate: bool,
                stored: Optional[Dict[str, Any]] = None,
                precomputed: Optional[Dict[str, Any]] = None,
                progress_cb=None,
                feedback: str = "",
                ) -> Tuple[str, Optional[Dict[str, Any]]]:
    """The render_and_persist hook. Three modes:
      precomputed — the self-heal re-render reuses the fragments the
                    first pass already generated (never pay twice);
      regenerate  — full recompose: plan + generate + validate;
      else        — shuffle/refresh/override re-render: reuse the
                    fragments persisted on site_config.atelier.
    `feedback` (A2): vision-grader notes from a failed previous render —
    the bounded quality regen injects them into every fragment prompt.
    Returns (html, atelier_meta|None). Fail-soft: any failure returns
    the input html — exactly the Arc 7 module page."""
    # Site Arc 12 — startup model probe (once per process; covers the
    # directions→choose publish path, which never calls produce_dro).
    try:
        import model_ladder
        from agents.composer.drl.passes import _drl_model
        model_ladder.probe_models_once([_model(), _drl_model()])
    except Exception:
        pass

    if precomputed and (precomputed.get("fragments") or {}):
        meta = precomputed
    elif regenerate:
        if not dro:
            return html, None
        picks = plan_bespoke(dro, spec, ctx)
        fragments: Dict[str, Dict[str, Any]] = {}
        _n = max(len(picks), 1)
        for _step, i in enumerate(picks, start=1):
            sec = spec[i] if 0 <= i < len(spec) else {}
            mid = sec.get("module")
            if not mid:
                continue
            out = generate_bespoke_section(
                mid, sec.get("variant"), dro, ctx,
                sec.get("content") or {}, business_id=business_id,
                feedback=feedback)
            if out:
                fragments[mid] = {"html": out[0], "css": out[1],
                                  "index": i, "variant": sec.get("variant")}
            # Arc 10 — 55→80 stepped per bespoke section (55 was reported
            # by render_and_persist before this call).
            _report(progress_cb, 55 + int(25 * _step / _n),
                    f"Drafting bespoke sections ({_step} of {_n})")
        if not fragments:
            return html, None
        meta = {
            "sections": [{"index": f["index"], "module": m}
                         for m, f in fragments.items()],
            # P3 (2026-07-18): planned seat count — the design-health
            # endpoint reads planned-vs-generated as the atelier fallback
            # rate (a planned seat with no fragment = a silent fallback
            # made countable).
            "planned": len(picks),
            "model": _model(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fragments": fragments,
        }
    else:
        meta = stored if isinstance(stored, dict) else {}
        if not (meta.get("fragments") or {}):
            return html, None

    fragments = {m: f for m, f in (meta.get("fragments") or {}).items()
                 if isinstance(f, dict)}
    new_html, replaced = replace_sections(html, fragments)
    if not replaced:
        return html, None
    css = "\n\n".join(str(fragments[m].get("css") or "") for m in replaced)
    # B4 — a bespoke contact fragment carries the working form (token-
    # substituted at generation): the platform ships the form's base
    # styles + wiring script with it. Runs for every mode (generated,
    # precomputed, stored) — each starts from a fresh module page whose
    # contact script was replaced along with the section.
    if "contact" in replaced and 'id="sxm-contact-form"' in new_html:
        try:
            from site_modules import contact_footer as _cf
            _fh, _form_script = _cf.build_contact_form(ctx)
            if _form_script:
                css += "\n\n" + _cf.CONTACT_FORM_CSS
                if "sxm-consent-armed" not in new_html:
                    if "</body>" in new_html:
                        new_html = new_html.replace(
                            "</body>", _form_script + "\n</body>", 1)
                    else:
                        new_html += _form_script
        except Exception as _e:
            logger.info(f"[atelier] contact form runtime skipped: {_e}")
    new_html = _inject_css(new_html, css)
    logger.info(f"[atelier] {'generated' if regenerate else 'reused'} "
                f"{len(replaced)} bespoke section(s) for {business_id[:8]}: "
                f"{replaced}")
    return new_html, meta
