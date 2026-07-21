# canvas_brief.py
# ─────────────────────────────────────────────────────────────────────
# The Canvas Pass (Phase 1, docs/CANVAS_PASS.md §3.1) — the deterministic
# brief compiler. NO LLM, no network: a pure function of ctx + dro + spec.
#
# The artifact the reference experiment effectively received, compiled
# from data the pipeline already has — shaped like the owner's hand
# prompt: overview (offer, audience, verbs), brand (palette direction +
# pairing + accent hexes named by role), the section plan with
# per-section intent, the interactions budget (the ONE loud moment), and
# the do/don't rules (avoid list, inspiration notes, DRO rule-break +
# tension + first impression, the doctrine one-liner).
#
# Also home to section_role() — the deterministic authored-vs-block
# classifier (§3.2) shared by canvas.canvas_plan and the brief's section
# plan, so the two can never drift.
# ─────────────────────────────────────────────────────────────────────

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("canvas_brief")

# §3.2 — the split. Authored: the creative sections where craft lives.
# Block: data-bearing sections pre-rendered by the module registry into
# immutable truth blocks. gallery joins the authored set ONLY in its
# awaiting-frames form (no real photos — nothing factual to protect);
# with photos it is a data section. An interstitial in its marquee form
# carries real tone words + deterministic chrome motion, so it renders
# as a block (§10.2 marquee wiring); every other seam variant is
# authored. Unknown modules default to block (safe: module-rendered).
AUTHORED_MODULES = frozenset({"hero", "about", "cta", "interstitial"})
BLOCK_MODULES = frozenset({"offerings", "testimonials", "statband",
                           "process", "faq", "store", "showcase",
                           "contact"})


def section_role(module: str, variant: str, ctx: Dict[str, Any]) -> str:
    """'authored' | 'block' for one spec section (spec §3.2)."""
    mid = str(module or "")
    if mid == "gallery":
        return "block" if (ctx.get("gallery") or []) else "authored"
    if mid == "interstitial":
        return "block" if str(variant or "") == "marquee" else "authored"
    if mid in AUTHORED_MODULES:
        return "authored"
    return "block"


_WORD_SPLIT_RE = re.compile(r"[•|,/·]+|\s+")


def _tone_words(ctx: Dict[str, Any]) -> List[str]:
    """The brand's real tone/value words (bundle voice.tone_words —
    list or free string). The verbs the brief's overview carries.
    Deterministic twin of site_composer._ceremony_tone_words, kept local
    so this module stays a leaf (no composer import)."""
    voice = ((ctx.get("bundle") or {}).get("voice")
             if isinstance((ctx.get("bundle") or {}).get("voice"), dict) else {})
    raw = voice.get("tone_words")
    if isinstance(raw, (list, tuple)):
        words = [str(w) for w in raw]
    elif isinstance(raw, str):
        words = _WORD_SPLIT_RE.split(raw)
    else:
        words = []
    out: List[str] = []
    seen = set()
    for w in words:
        w = " ".join(w.split()).strip(".,;:")
        if 2 <= len(w) <= 24 and w.lower() not in seen and w.isascii():
            seen.add(w.lower())
            out.append(w)
    return out[:6]


def _offer_line(ctx: Dict[str, Any]) -> str:
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    offer = str(prefs.get("offer") or "").strip()
    if offer:
        return offer[:300]
    names = [str(o.get("name") or "").strip()
             for o in (ctx.get("offerings") or [])[:4]
             if isinstance(o, dict) and str(o.get("name") or "").strip()]
    if names:
        return "; ".join(names)
    btype = str((ctx.get("business") or {}).get("type") or "").strip()
    return btype or "(read the rationale — the offer must be unmistakable)"


def _section_intent(sec: Dict[str, Any], role: str,
                    dro: Optional[Dict[str, Any]]) -> str:
    """One line of per-section intent for the section plan. Authored
    sections get a craft instruction (with the §4.7 substance minimums);
    blocks get the immutability rule."""
    mid = str(sec.get("module") or "")
    variant = str(sec.get("variant") or "")
    if role == "block":
        if mid == "interstitial":
            return ("PRE-RENDERED values marquee — real tone words, "
                    "immutable; position its token, never rewrite it")
        return (f"PRE-RENDERED DATA ({mid}) — immutable truth block; "
                "position its token, never rewrite a byte of it")
    d = (dro or {}).get("decisions") or {}
    if mid == "hero":
        concept = str((d.get("hero_concept") or {}).get("direction") or "")
        return ("the opening frame — headline ≤ 9 words, a REAL subhead "
                "(no caption-only hero); the concept's first move"
                + (f"; direction: {concept}" if concept else ""))
    if mid == "about":
        return ("the story — ≥ 60 words of real narrative in the "
                "concept's voice, never a bio template")
    if mid == "cta":
        return "the closing invitation — one clear action, no hedging"
    if mid == "gallery":
        return ("the awaiting-frames gallery — design the empty state as "
                "intentional texture (real photos land via slots later)")
    if mid == "interstitial":
        if variant == "statement":
            return "a title-card pause — ONE italic display sentence"
        return "designed silence between chapters — a deliberate seam"
    return "an authored creative section — real paragraphs, no filler"


def compile_canvas_brief(ctx: Dict[str, Any],
                         dro: Optional[Dict[str, Any]],
                         spec: List[Dict[str, Any]]) -> str:
    """The canvas brief (§3.1) — deterministic compile, no LLM. Pure:
    same inputs → same text. Never raises (a brief hiccup must not kill
    a compose — the section plan alone is worth sending)."""
    try:
        return _compile(ctx, dro, spec)
    except Exception as e:  # fail-soft: the minimal brief still carries law
        logger.info(f"[canvas-brief] full compile skipped ({e}) — minimal brief")
        return "CANVAS BRIEF\nFollow the design rationale and the canvas " \
               "contract. Real data only; never invent facts."


def _compile(ctx: Dict[str, Any], dro: Optional[Dict[str, Any]],
             spec: List[Dict[str, Any]]) -> str:
    biz = ctx.get("business") or {}
    dna = ctx.get("dna") or {}
    palette = dna.get("palette") or {}
    typography = dna.get("typography") or {}
    prefs = ctx.get("site_prefs") if isinstance(ctx.get("site_prefs"), dict) else {}
    d = (dro or {}).get("decisions") or {}
    lines: List[str] = []
    A = lines.append

    A(f"CANVAS BRIEF — {biz.get('name') or 'this business'}")
    A("")

    # ── OVERVIEW: offer, audience, verbs ──
    A("== OVERVIEW ==")
    A(f"- what they offer: {_offer_line(ctx)}")
    btype = str(biz.get("type") or "").strip()
    A("- who it's for: " + (f"the people a {btype} serves — speak to them "
                            "specifically, never to everyone"
                            if btype else
                            "the clients this business serves — specifically, "
                            "never generically"))
    verbs = _tone_words(ctx)
    if verbs:
        A("- the verbs (real brand tone words — the page's motion and "
          "copy should feel like these): " + ", ".join(verbs))
    A("")

    # ── BRAND: palette direction + pairing + accent hexes by role ──
    A("== BRAND ==")
    pal = d.get("palette") or {}
    direction = "; ".join(str(pal.get(k)) for k in
                          ("base", "temperature", "accent_strategy") if pal.get(k))
    A(f"- palette direction: {direction or '(token system below)'}; "
      f"ground mode: {palette.get('mode') or 'light'}")
    A(f"- type pairing: display '{typography.get('heading') or 'heading'}' / "
      f"body '{typography.get('body') or 'body'}'"
      + (f" / accent '{typography.get('accent')}'"
         if typography.get("accent") else ""))
    A(f"- --sx-accent = {palette.get('accent') or '(token)'} — THE brand accent")
    if palette.get("secondary_active") and palette.get("secondary"):
        A(f"- --sx-secondary = {palette['secondary']} — the SECOND brand accent "
          "(spend it as ONE section's family, never everywhere)")
    A(f"- --sx-bg = {palette.get('bg') or '(token)'}; "
      f"--sx-text = {palette.get('text') or '(token)'}; "
      f"--sx-authority = {palette.get('authority') or '(token)'} "
      "(the deep color-block ground)")
    A("Every color/font you emit is a var(--sx-*) reference to these — "
      "never a literal.")
    A("")

    # ── SECTION PLAN with per-section intent ──
    A("== SECTION PLAN (in order) ==")
    for i, sec in enumerate(spec or [], start=1):
        mid = str(sec.get("module") or "")
        role = section_role(mid, str(sec.get("variant") or ""), ctx)
        tag = "AUTHORED" if role == "authored" else \
              f"IMMUTABLE BLOCK — token <!--SX_BLOCK:{mid}-->"
        A(f"{i}. {mid} [{tag}] — {_section_intent(sec, role, dro)}")
    A("")

    # ── INTERACTIONS BUDGET: the ONE loud moment ──
    A("== INTERACTIONS BUDGET ==")
    loud_where = str(d.get("_owner_loud_where") or "").strip()
    signature = str((d.get("motion") or {}).get("signature_move") or "").strip()
    rb = d.get("rule_break") or {}
    loud_bits = []
    if loud_where:
        loud_bits.append(f"the owner asked for the loud moment at: {loud_where}")
    if signature:
        loud_bits.append(f"the rationale's signature move: {signature}")
    if rb.get("what"):
        loud_bits.append(f"the ONE rule-break: {rb.get('what')}"
                         + (f" (at {rb.get('where')})" if rb.get("where") else ""))
    A("- " + ("; ".join(loud_bits) if loud_bits
              else "no loud moment called for — quiet confidence throughout"))
    A("- ONE signature interaction maximum (marquee, filter tabs, modal, "
      "or accordion) under the JS contract; everything else stays still. "
      "The page must be fully coherent with JS disabled (filters show "
      "everything, modals read inline).")
    A("")

    # ── DO / DON'T ──
    A("== DO / DON'T ==")
    tension = d.get("tension") or {}
    if tension.get("pole_a"):
        A(f"DO hold the tension: '{tension.get('pole_a')}' vs "
          f"'{tension.get('pole_b')}' — {tension.get('expression') or ''}".rstrip(" —"))
    fi = d.get("first_impression") or {}
    if fi.get("feel_in_3s") or fi.get("remember"):
        A(f"DO land the first 3 seconds: feel = {fi.get('feel_in_3s') or ''}; "
          f"remember = {fi.get('remember') or ''}")
    insp = str(prefs.get("inspiration_notes") or prefs.get("inspiration") or "").strip()
    if insp:
        A(f"DO take the owner's inspiration seriously: {insp[:240]}")
    notes = (d.get("voice_to_visual") or {}).get("notes")
    if isinstance(notes, list) and notes:
        A("DO translate the voice: " + "; ".join(str(n) for n in notes[:4]))
    avoid = prefs.get("avoid")
    if isinstance(avoid, (list, tuple)) and avoid:
        A("DON'T (owner's avoid list): " + ", ".join(str(a) for a in avoid[:6]))
    elif isinstance(avoid, str) and avoid.strip():
        A(f"DON'T (owner's avoid list): {avoid.strip()[:240]}")
    A("DON'T invent facts, prices, testimonials, stats, or credentials — "
      "doctrine D10: REAL OR REMOVED. Every constraint above is the floor, "
      "not the ceiling (D1) — honor it, then add instinct on top.")
    return "\n".join(lines)
