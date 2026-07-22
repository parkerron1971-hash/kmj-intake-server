"""
art_direction.py — THE AUTHORSHIP PASS (piece 1 of the instinct arc,
2026-07-22, Kevin's ruling: "the brain has tools but no permission to
use them — give it the pen").

On claude.ai the model writes the whole page itself: one mind, one
aesthetic thesis, executed everywhere. In this pipeline the model only
ever touched three narrow points (DRO fields, 2-3 atelier fragments,
the judge) — template renderers built everything else, which is why
every build gravitated to the same generic floor no matter what the
DRO reasoned.

This pass hands the model the WHOLE PAGE, safely:

  • It runs after the body HTML is fully assembled. The model receives
    the DRO's vision, the DNA tokens, and the page's REAL class
    inventory (every .sxm-*/.atl-* class actually present), and authors
    one page-wide CSS layer — section treatments, gallery framing,
    rhythm breaks, hover language, token retunes.
  • The layer is SANITIZED, not trusted: every selector must anchor to
    an existing scope (.sxm-/.sx-/.atl- or :root for token overrides);
    bare element selectors, url(), @import, position:fixed and
    oversized payloads are dropped rule-by-rule.
  • It is appended AFTER all other CSS, so the author's voice wins
    cascade ties against the templates — the pen, not a whisper.
  • Fail-open everywhere: no key, timeout, junk output → the page
    ships exactly as it would have before this pass existed.

Env:
  ART_DIRECTION=off   — kill switch (default on)
  ART_DIRECTION_MODEL — model override (default: the atelier's model)
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("art_direction")

_MAX_LAYER_CHARS = 9000
_MAX_TOKENS = 3000

# Selector anchors the sanitizer accepts. `:root` enables token retunes
# (--sx-accent-soft etc.); everything else must target classes that the
# renderer or atelier actually stamped.
_ALLOWED_SELECTOR = re.compile(
    r"^\s*(:root$|\.(?:sxm|sx|atl|sxad)-)")
# position:absolute joined the ban after the first live layer pinned all
# four gallery figures to one corner (the model guessed .sxm-gal-fig-over
# was a caption chip; it was the figure itself). The art director styles
# surfaces, type, color, spacing — it does NOT re-architect layout, so
# structural declarations are dropped wholesale.
_FORBIDDEN_SNIPPETS = ("@import", "url(", "expression(", "position:fixed",
                       "position: fixed", "position:absolute",
                       "position: absolute", "display:none", "display: none",
                       "visibility:hidden", "visibility: hidden",
                       "</style", "<script")


def enabled() -> bool:
    return (os.environ.get("ART_DIRECTION") or "on").strip().lower() != "off"


# ─── Sanitizer ────────────────────────────────────────────────────────

def _strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _split_rules(css: str) -> List[str]:
    """Split top-level rules honoring nested braces (@media blocks)."""
    rules, depth, start = [], 0, 0
    for i, ch in enumerate(css):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                rules.append(css[start:i + 1])
                start = i + 1
    return [r.strip() for r in rules if r.strip()]


def _rule_ok(rule: str) -> bool:
    low = rule.lower()
    if any(s in low for s in _FORBIDDEN_SNIPPETS):
        return False
    if rule.startswith("@keyframes"):
        return bool(re.match(r"@keyframes\s+sxad-[\w-]+\s*\{", rule))
    if rule.startswith("@media"):
        inner = rule[rule.index("{") + 1:rule.rfind("}")]
        inner_rules = _split_rules(inner)
        return bool(inner_rules) and all(_rule_ok(r) for r in inner_rules)
    if rule.startswith("@"):
        return False          # @font-face / @supports / anything exotic
    sel = rule.split("{", 1)[0]
    parts = [p.strip() for p in sel.split(",") if p.strip()]
    return bool(parts) and all(_ALLOWED_SELECTOR.match(p) for p in parts)


def sanitize_layer(css: str) -> str:
    """Keep only rules that pass the scope contract. Returns '' when
    nothing survives (caller treats as no-layer)."""
    css = _strip_comments(css or "")
    kept = [r for r in _split_rules(css) if _rule_ok(r)]
    out = "\n".join(kept).strip()
    return out[:_MAX_LAYER_CHARS] if out else ""


# ─── Class inventory ─────────────────────────────────────────────────

def class_inventory(body_html: str, cap: int = 120) -> List[str]:
    """Every real styling hook on the assembled page — grounds the
    author's selectors in what actually exists."""
    found: List[str] = []
    seen = set()
    for m in re.finditer(r'class="([^"]+)"', body_html or ""):
        for cls in m.group(1).split():
            if cls.startswith(("sxm-", "atl-", "sx-")) and cls not in seen:
                seen.add(cls)
                found.append(cls)
            if len(found) >= cap:
                return found
    return found


# ─── Prompt ──────────────────────────────────────────────────────────

_SYSTEM = """You are the art director taking final possession of a website page.
A reasoning pass (the DRO) chose the direction; template renderers built solid,
generic sections. Your job is what a designer does on their own canvas: make the
whole page feel AUTHORED — one aesthetic thesis executed everywhere.

You write ONE page-wide CSS layer. It is injected AFTER all existing CSS, so your
rules win ties. Work with what exists — you cannot add HTML.

HARD CONTRACT (violations are dropped silently, so obey exactly):
- Selectors MUST start with an existing class from the INVENTORY (.sxm-*, .sx-*,
  .atl-*) or be exactly `:root` (for CSS-token retunes).
- No bare element selectors (no `h2 {}` — write `.sxm-section h2 {}`).
- No url(), no @import, no @font-face, no position:fixed, no scripts.
- @keyframes names must start with `sxad-`.
- Use the design tokens (var(--sx-accent), --sx-surface, --sx-font-heading …)
  so the layer stays theme-coherent. You may retune tokens on :root.
- NEVER change `position` or `display` of existing elements, and never hide
  anything. You see class NAMES, not their structural roles — a class that
  sounds like a caption may be the element itself, and re-positioning it
  destroys the layout. Style surfaces, borders, spacing, typography, color,
  shadows, transitions; leave the skeleton alone.
- Total under 8000 characters. Output ONLY CSS — no prose, no markdown fences.

WHAT AUTHORSHIP MEANS HERE (your instincts, the ones templates lack):
- Commit to the DRO's thesis and push it into every section — if the vision says
  "calm and dark, one warm accent", the gallery mats, card borders, heading
  spacing and hover states should ALL say it.
- One deliberate loud moment; quiet craft everywhere else (hairlines, letter
  spacing, rhythm shifts between sections so the page breathes unevenly like a
  designed magazine, not a stack of equal blocks).
- The gallery is where generic shows most: frame it (mats, offsets, varied
  spans, a caption voice) so it reads curated, not dumped.
- Details carry conviction: selection color, focus states, numbered markers,
  first-letter or first-line moves where the content invites them.
- SPACING DISCIPLINE (live-audit): the page's rhythm should vary, but no
  section becomes a near-empty viewport — padding-block above 8rem needs
  content the space is staging. Tighten bloated bands; don't add air to air.
- ACCENT DISCIPLINE: at most ONE full-bleed accent-tinted band on the whole
  page. Elsewhere the accent lives in ink-level doses — words, hairlines,
  one button. A page bathed in accent reads cheap; scarcity reads intended.
- Body copy and form hints always var(--sx-font-body) — fix any section
  where the display face leaked into paragraphs."""


def _user_prompt(design: Dict[str, Any], dna: Dict[str, Any],
                 inventory: List[str], dro_summary: str,
                 business_name: str) -> str:
    import json
    pal = (dna.get("palette") or {})
    typ = (dna.get("typography") or {})
    return (
        f"BUSINESS: {business_name}\n\n"
        f"THE VISION (DRO summary):\n{(dro_summary or 'none recorded')[:900]}\n\n"
        f"DRO DESIGN FIELDS:\n{json.dumps(design or {}, default=str)[:2200]}\n\n"
        f"CURRENT TOKENS: accent={pal.get('accent')} bg={pal.get('bg')} "
        f"surface={pal.get('surface')} heading_font={typ.get('heading')} "
        f"body_font={typ.get('body')}\n\n"
        f"CLASS INVENTORY (the only hooks that exist on this page):\n"
        f"{' '.join(inventory)}\n\n"
        "Author the page-wide layer now. CSS only.")


# ─── Entry point ─────────────────────────────────────────────────────

# One authored layer per (business, rationale): render() runs on every
# re-render and live edit — without this cache each of those would be a
# paid LLM call (the cost-diet rule). A new DRO (new rationale id or a
# changed vision summary) is a new design and authors fresh.
_CACHE: Dict[str, str] = {}
_CACHE_MAX = 300


def _cache_key(ctx: Dict[str, Any], business_id: str) -> str:
    import hashlib
    rid = str(ctx.get("design_rationale_id") or "")
    if not rid:
        summary = str(ctx.get("dro_summary") or "")
        accent = str(((ctx.get("dna") or {}).get("palette") or {}).get("accent") or "")
        rid = hashlib.sha256(f"{summary}:{accent}".encode()).hexdigest()[:16]
    return f"{business_id}:{rid}"


def author_layer(ctx: Dict[str, Any], body_html: str,
                 business_id: str = "") -> str:
    """The authorship pass. Returns sanitized CSS ('' = no layer).
    NEVER raises — any failure means the page ships unchanged."""
    if not enabled():
        return ""
    try:
        key = _cache_key(ctx, business_id)
        if key in _CACHE:
            return _CACHE[key]
        inventory = class_inventory(body_html)
        if len(inventory) < 5:
            logger.info("[art-direction] inventory too small — skipping")
            return ""
        design = ctx.get("design") or {}
        dna = ctx.get("dna") or {}
        summary = str(ctx.get("dro_summary") or
                      (design.get("meta") or {}).get("summary") or "")
        name = str((ctx.get("business") or {}).get("name") or
                   ctx.get("business_name") or "")
        import atelier
        prev_model = os.environ.get("ATELIER_MODEL")
        ad_model = (os.environ.get("ART_DIRECTION_MODEL") or "").strip()
        try:
            if ad_model:
                os.environ["ATELIER_MODEL"] = ad_model
            raw = atelier._call_llm(
                _SYSTEM, _user_prompt(design, dna, inventory, summary, name),
                business_id)
        finally:
            if ad_model:
                if prev_model is None:
                    os.environ.pop("ATELIER_MODEL", None)
                else:
                    os.environ["ATELIER_MODEL"] = prev_model
        if not raw:
            return ""          # call failed — NOT cached, retries next render
        # Tolerate a fenced reply despite the contract.
        raw = re.sub(r"^```(?:css)?|```$", "", raw.strip(), flags=re.M).strip()
        layer = sanitize_layer(raw)
        if layer:
            logger.info(f"[art-direction] layer authored for "
                        f"{(business_id or 'unknown')[:8]}: "
                        f"{len(layer)} chars, {layer.count('{')} rules")
        else:
            logger.warning("[art-direction] nothing survived the sanitizer")
        if len(_CACHE) >= _CACHE_MAX:
            _CACHE.clear()
        _CACHE[key] = layer     # completed roundtrips cache (even empty)
        return layer
    except Exception as e:
        logger.warning(f"[art-direction] failed open: {type(e).__name__}: {e}")
        return ""
