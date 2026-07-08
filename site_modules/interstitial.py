"""Interstitial module — Site Arc 10 "wow" — the ceremony seams.

"The page is a ceremony, not a stack": two chapters never simply abut —
the boundary carries something deliberate. These are the deliberate
boundaries, distilled from the owner's highest-rated original designs
(exemplars e5/e6): designed silence, the transition thread, the
statement title card, and the values marquee.

NEVER LLM-picked: site_composer's deterministic ceremony pass inserts
1-3 of these between major sections from the DRO (seeded by
design_rationale_id so recomposes vary). Chrome-like by design — no
image slots, excluded from the authority band, the silence rule-break
target, ghost numerals and atelier planning.

Variants:
  silence   — a 64-88px quiet band holding a lone centered 48px
              gradient hairline. The page pauses on purpose.
  thread    — a full-width transition thread: transparent→accent→
              transparent hairline at ~0.2 opacity with a soft glow.
  statement — a title card: ONE italic display sentence (real spec
              copy, data-override-target) centered on a soft
              accent-tinted ground (color-mix 10%), with the
              accent-word idiom.
  marquee   — brand tone/value words (REAL data only — empty words →
              '' → the section is skipped) scrolling slowly in the
              micro-caps whisper voice with accent separators.
              reduced-motion / stilled pages read it as a static row.

Contract (same as every module): --sx-* tokens only, deterministic,
empty data renders '', every gradient fades, reduced-motion honored.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Tuple

from ._base import safe, ov, accent_headline

VARIANTS = ("silence", "thread", "statement", "marquee")

_WORD_SPLIT_RE = re.compile(r"[•|,/·]+")
_MIN_MARQUEE_WORDS = 3
_MAX_MARQUEE_WORDS = 6


def _marquee_words(content: Dict[str, Any]) -> list:
    """Parse the joined tone-word string ('Precision • Warmth • …')
    back into clean display words. Real data only — the ceremony pass
    writes this from the brand's own tone words, never invents."""
    raw = str(content.get("words") or "")
    out, seen = [], set()
    for w in _WORD_SPLIT_RE.split(raw):
        w = " ".join(w.split())
        if 2 <= len(w) <= 24 and w.lower() not in seen:
            seen.add(w.lower())
            out.append(w)
    return out[:_MAX_MARQUEE_WORDS]


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    if variant == "statement":
        text = str(content.get("text") or "").strip()
        if not text:
            return "", ""   # no real line to say → no seam invented
        html = f"""
<section class="sxm-interstitial sxm-int-statement sxm-reveal" aria-label="Interlude">
  <div class="sxm-inner">
    <p class="sxm-int-statement-text" {ov('interstitial', 'text')}>{accent_headline(text)}</p>
  </div>
</section>"""
        css = """
.sxm-int-statement { padding: clamp(56px, 9vh, 96px) var(--sx-gutter); text-align: center;
  background: color-mix(in srgb, var(--sx-accent) 10%, var(--sx-bg)); }
.sxm-int-statement-text { font-family: var(--sx-font-heading); font-style: italic;
  font-weight: var(--sx-h2-weight, var(--sx-heading-weight));
  font-size: clamp(1.35rem, 2.6vw, 2.05rem); line-height: 1.4;
  letter-spacing: var(--sx-letter-tight); max-width: 36ch; margin: 0 auto;
  color: var(--sx-text); }"""
        return html, css

    if variant == "marquee":
        words = _marquee_words(content)
        if len(words) < _MIN_MARQUEE_WORDS:
            return "", ""   # marquee needs real values to speak
        seq = '<span class="sxm-int-mq-sep" aria-hidden="true">◆</span>'.join(
            f'<span class="sxm-whisper sxm-int-mq-word">{safe(w)}</span>'
            for w in words)
        # The track holds the sequence TWICE and translates -50% for a
        # seamless loop; the copy is aria-hidden and vanishes when the
        # marquee is stilled (reduced-motion → a single static row).
        html = f"""
<div class="sxm-interstitial sxm-int-marquee">
  <div class="sxm-int-mq-track">
    <div class="sxm-int-mq-seq">{seq}</div>
    <div class="sxm-int-mq-seq" aria-hidden="true">{seq}</div>
  </div>
</div>"""
        motion = (ctx.get("dna") or {}).get("motion", "standard")
        # A stilled page (motion=subtle) reads the marquee as a static
        # row — same treatment reduced-motion gets everywhere.
        still = ("\n.sxm-int-mq-track { animation: none; justify-content: center; }"
                 "\n.sxm-int-mq-seq[aria-hidden] { display: none; }"
                 if motion == "subtle" else "")
        css = """
.sxm-int-marquee { overflow: hidden; padding: 16px 0;
  border-top: 1px solid var(--sx-border); border-bottom: 1px solid var(--sx-border);
  -webkit-mask-image: linear-gradient(90deg, transparent, #000 10%, #000 90%, transparent);
  mask-image: linear-gradient(90deg, transparent, #000 10%, #000 90%, transparent); }
.sxm-int-mq-track { display: flex; width: max-content; animation: sxm-int-mq 38s linear infinite; }
.sxm-int-mq-seq { display: flex; align-items: center; gap: 2.6em; padding-right: 2.6em; white-space: nowrap; }
.sxm-int-mq-word { font-size: .7rem; }
.sxm-int-mq-sep { color: var(--sx-accent); font-size: .5rem; opacity: .7; }
@keyframes sxm-int-mq { to { transform: translateX(-50%); } }
@media (prefers-reduced-motion: reduce) {
  .sxm-int-mq-track { animation: none; justify-content: center; }
  .sxm-int-mq-seq[aria-hidden] { display: none; }
}""" + still
        return html, css

    if variant == "thread":
        html = """
<div class="sxm-interstitial sxm-int-thread" aria-hidden="true">
  <span class="sxm-int-thread-line"></span>
</div>"""
        css = """
.sxm-int-thread { padding: clamp(30px, 5vh, 48px) var(--sx-gutter); }
.sxm-int-thread-line { display: block; height: 1px; max-width: var(--sx-content-max);
  margin: 0 auto; opacity: .2;
  background: linear-gradient(90deg, transparent, var(--sx-accent) 50%, transparent);
  box-shadow: 0 0 16px 1px var(--sx-accent-soft); }"""
        return html, css

    # default: silence — the loudest way to say "no rush here".
    html = """
<div class="sxm-interstitial sxm-int-silence" aria-hidden="true">
  <span class="sxm-int-silence-hairline"></span>
</div>"""
    css = """
.sxm-int-silence { height: clamp(64px, 10vh, 88px); display: flex;
  align-items: center; justify-content: center; }
.sxm-int-silence-hairline { width: 48px; height: 1px; opacity: .55;
  background: linear-gradient(90deg, transparent, var(--sx-accent), transparent); }"""
    return html, css
