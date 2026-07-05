"""Hero module — 6 expression variants. Content: eyebrow, headline,
subheadline, cta_label. Image slot: hero_main (split/banner/cinematic/
editorial); 'constructed' builds a typographic hero over a generated
ornament field — no photo at all (Arc 3, DRO visual_metaphor)."""
from __future__ import annotations

import hashlib
from typing import Any, Dict, Tuple

from ._base import (safe, ov, cta_button, eyebrow, heading_accent,
                    accent_headline, diamond_field, GRAIN_DATA_URI)

VARIANTS = ("split", "statement", "banner", "cinematic", "editorial", "constructed")

# Quality-floor arc 7: the accent-word idiom was promoted to _base
# (accent_headline) and now marks EVERY hero variant's h1; its CSS
# (.sxm-accent-word) ships in base_css. Alias kept for older callers.
_accent_headline = accent_headline


def _constructed_recipe(ctx: Dict[str, Any]) -> Tuple[str, str]:
    """(arrangement, motif) for the constructed hero — deterministic from
    the DRO concept words (hash-picked), so the same rationale always
    renders the same ornament field. Concept keywords steer the motif:
    regal/stellar words → diamond, luminous words → ring, journey words
    → bar; otherwise the hash decides."""
    design = ctx.get("design") or {}
    hero_c = design.get("hero_concept") or {}
    words = [str(w) for w in (hero_c.get("metaphor_elements") or []) if str(w or "").strip()]
    blob = (" ".join(words + [str(hero_c.get("concept_statement") or "")])).strip().lower()
    seed_src = blob or str((ctx.get("dna") or {}).get("seed") or "0")
    h = int(hashlib.sha256(seed_src.encode()).hexdigest()[:8], 16)

    if any(k in blob for k in ("crown", "royal", "diamond", "gem", "star", "peak", "throne")):
        motif = "diamond"
    elif any(k in blob for k in ("light", "glow", "sun", "halo", "warm", "fire", "dawn", "radian")):
        motif = "ring"
    elif any(k in blob for k in ("path", "journey", "line", "thread", "river", "road", "bridge", "horizon")):
        motif = "bar"
    else:
        motif = ("diamond", "ring", "bar")[h % 3]
    arrangement = ("orbital", "horizon", "ascend")[(h >> 4) % 3]
    return arrangement, motif


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    biz_name = (ctx.get("business") or {}).get("name") or ""
    headline = content.get("headline") or biz_name or "Welcome"
    sub = content.get("subheadline") or ""
    eb = eyebrow("hero", content.get("eyebrow") or "")
    cta = cta_button(ctx, content.get("cta_label") or "Book a session", "hero")
    # Deterministic, meaningful alt for the hero image (Arc 1).
    img_alt = safe(f"{biz_name} — {headline}" if biz_name and biz_name != headline
                   else headline)

    if variant == "cinematic":
        # Full-bleed, art-directed: tall viewport, image graded by a layered
        # scrim, oversized display headline anchored low-left. The premium
        # "walk into a strategy session" first impression.
        html = f"""
<section class="sxm-hero-cine" id="top">
  <img data-slot="hero_main" src="" alt="{img_alt}" class="sxm-cine-bg">
  <div class="sxm-cine-scrim"></div>{diamond_field(dna, 3)}
  <div class="sxm-inner sxm-cine-inner">
    <div class="sxm-cine-copy">
      {heading_accent(dna)}
      {eb}
      <h1 {ov('hero', 'headline')}>{accent_headline(headline)}</h1>
      <p class="sxm-cine-sub" {ov('hero', 'subheadline')}>{safe(sub)}</p>
      {cta}
    </div>
  </div>
</section>"""
        css = """
.sxm-hero-cine { position: relative; min-height: 100vh; min-height: 100svh; display: flex;
  align-items: flex-end; padding: var(--sx-section-pad) var(--sx-gutter) clamp(56px, 9vh, 110px);
  overflow: hidden; isolation: isolate; }
.sxm-cine-bg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; z-index: -2;
  filter: saturate(1.04) contrast(1.04); transform: scale(1.04); }
.sxm-cine-scrim { position: absolute; inset: 0; z-index: -1; background:
  linear-gradient(to top, var(--sx-bg) 4%, color-mix(in srgb, var(--sx-bg) 58%, transparent) 34%, transparent 72%),
  linear-gradient(105deg, color-mix(in srgb, var(--sx-bg) 72%, transparent) 0%, transparent 55%); }
.sxm-cine-inner { position: relative; width: 100%; }
.sxm-cine-copy { max-width: 22ch; }
.sxm-hero-cine h1 { font-size: clamp(3.2rem, 7.2vw, 6rem); margin-bottom: 22px; }
.sxm-hero-cine .sxm-cine-sub { font-size: 1.18rem; max-width: 44ch; margin-bottom: 36px; color: var(--sx-text);
  opacity: .92; }
.sxm-hero-cine .sxm-eyebrow { color: var(--sx-accent); }
@media (max-width: 768px) { .sxm-hero-cine { min-height: 92vh; } }"""
        return html, css

    if variant == "editorial":
        # Arc 3 — asymmetric offset split (craft source: cathedral
        # asymmetric_left + the italic accent-word signature). Oversized
        # display type overhangs the image column; the visual sits a
        # beat lower — asymmetric tension, not a broken grid.
        html = f"""
<section class="sxm-section sxm-hero-ed" id="top">
  <div class="sxm-inner sxm-hero-ed-grid">
    <div class="sxm-hero-ed-copy">
      {heading_accent(dna)}
      {eb}
      <h1 {ov('hero', 'headline')}>{accent_headline(headline)}</h1>
      <p class="sxm-hero-sub" {ov('hero', 'subheadline')}>{safe(sub)}</p>
      {cta}
    </div>
    <div class="sxm-hero-ed-visual sxm-imgbox">
      <img data-slot="hero_main" src="" alt="{img_alt}">
    </div>
  </div>
</section>"""
        css = """
.sxm-hero-ed { min-height: 86vh; display: flex; align-items: center; overflow: hidden; }
.sxm-hero-ed-grid { display: grid; grid-template-columns: 1.15fr .85fr; gap: clamp(28px, 5vw, 72px);
  align-items: start; width: 100%; }
.sxm-hero-ed h1 { font-size: clamp(3.5rem, 7.4vw, 6.4rem); line-height: 1.02; max-width: 13ch;
  position: relative; z-index: 2; margin: 0 clamp(-140px, -12%, 0px) 26px 0; }
.sxm-hero-ed .sxm-hero-sub { font-size: 1.14rem; max-width: 44ch; margin-bottom: 34px; color: var(--sx-muted); }
.sxm-hero-ed-visual { margin-top: clamp(46px, 9vh, 120px); }
.sxm-hero-ed-visual img { width: 100%; aspect-ratio: 4/5; object-fit: cover; }
@media (max-width: 860px) {
  .sxm-hero-ed { min-height: 0; }
  .sxm-hero-ed-grid { grid-template-columns: 1fr; }
  .sxm-hero-ed h1 { margin-right: 0; max-width: none; }
  .sxm-hero-ed-visual { margin-top: 8px; }
}"""
        return html, css

    if variant == "constructed":
        # Arc 3 — the CONSTRUCTED hero (DRO visual_metaphor): no stock
        # photo. A typographic statement over a generated ornament field
        # — layered soft radial/conic accent gradients (every gradient
        # fades), subtle grain, and geometric motifs echoing the concept
        # keywords. Arrangement + motif are hash-picked from the DRO
        # concept words, so the metaphor — not a photo — is the image.
        arrangement, motif = _constructed_recipe(ctx)
        field = "".join(
            f'\n    <span class="sxm-orn-layer sxm-orn-{c}"></span>' for c in "abc"
        ) + "".join(
            f'\n    <span class="sxm-motif sxm-motif-{motif} sxm-m{i}"></span>'
            for i in (1, 2, 3))
        html = f"""
<section class="sxm-hero-constructed sxm-orn-{arrangement}" id="top">
  <div class="sxm-orn-field" aria-hidden="true">{field}
  </div>
  <div class="sxm-inner sxm-hero-con-inner">
    {heading_accent(dna)}
    {eb}
    <h1 {ov('hero', 'headline')}>{accent_headline(headline)}</h1>
    <p class="sxm-hero-sub" {ov('hero', 'subheadline')}>{safe(sub)}</p>
    {cta}
  </div>
</section>"""
        css = """
.sxm-hero-constructed { position: relative; min-height: 92vh; display: flex; align-items: center;
  padding: var(--sx-section-pad) var(--sx-gutter); overflow: hidden; isolation: isolate; }
.sxm-hero-constructed::after { content: ""; position: absolute; inset: 0; z-index: -1;
  pointer-events: none; background-image: """ + GRAIN_DATA_URI + """;
  background-size: 160px 160px; opacity: .05; }
.sxm-orn-field { position: absolute; inset: 0; z-index: -2; }
.sxm-orn-layer { position: absolute; border-radius: 50%; }
.sxm-orn-a { top: -20%; right: -30%; width: 70vw; height: 70vw;
  background: radial-gradient(closest-side, color-mix(in srgb, var(--sx-accent) 26%, transparent), transparent 72%); }
.sxm-orn-b { bottom: -30%; left: -20%; width: 60vw; height: 60vw;
  background: radial-gradient(closest-side, color-mix(in srgb, var(--sx-accent-strong) 18%, transparent), transparent 70%); }
.sxm-orn-c { inset: 0; width: 100%; height: 100%; border-radius: 0;
  background: conic-gradient(from 210deg at 70% 20%, transparent 0deg,
    color-mix(in srgb, var(--sx-accent) 8%, transparent) 80deg, transparent 160deg); }
.sxm-orn-horizon .sxm-orn-a { top: auto; right: -25%; bottom: -45%; left: -25%; width: auto; height: 80vh;
  background: radial-gradient(ellipse at 50% 100%, color-mix(in srgb, var(--sx-accent) 24%, transparent), transparent 70%); }
.sxm-orn-horizon .sxm-orn-b { top: -35%; right: auto; bottom: auto; left: 30%; }
.sxm-orn-ascend .sxm-orn-a { top: auto; right: auto; bottom: -25%; left: -15%; }
.sxm-orn-ascend .sxm-orn-b { top: -25%; right: -15%; bottom: auto; left: auto; }
.sxm-orn-ascend .sxm-orn-c { background: conic-gradient(from 30deg at 20% 80%, transparent 0deg,
  color-mix(in srgb, var(--sx-accent) 9%, transparent) 70deg, transparent 150deg); }
.sxm-motif { position: absolute; }
.sxm-motif-diamond { width: 18px; height: 18px; background: var(--sx-accent);
  transform: rotate(45deg); opacity: .35; }
.sxm-motif-ring { width: 46px; height: 46px; border-radius: 50%;
  border: 2px solid color-mix(in srgb, var(--sx-accent) 65%, transparent); opacity: .5; }
.sxm-motif-bar { width: 90px; height: 2px; transform: rotate(-18deg);
  background: linear-gradient(90deg, var(--sx-accent), transparent); opacity: .5; }
.sxm-m1 { top: 18%; right: 14%; }
.sxm-m2 { top: 36%; right: 26%; opacity: .26; }
.sxm-m3 { bottom: 22%; left: 12%; opacity: .2; }
.sxm-hero-con-inner { position: relative; width: 100%; }
.sxm-hero-constructed h1 { font-size: clamp(3.2rem, 8vw, 7rem); max-width: 14ch; margin-bottom: 26px; }
.sxm-hero-constructed .sxm-hero-sub { font-size: 1.16rem; max-width: 46ch; margin-bottom: 36px;
  color: var(--sx-text); opacity: .9; }
@media (max-width: 768px) { .sxm-hero-constructed { min-height: 80vh; } }"""
        return html, css

    if variant == "statement":
        html = f"""
<section class="sxm-section sxm-hero-statement" id="top">
  <div class="sxm-inner">
    {heading_accent(dna)}
    {eb}
    <h1 {ov('hero', 'headline')}>{accent_headline(headline)}</h1>
    <p class="sxm-hero-sub sxm-muted" {ov('hero', 'subheadline')}>{safe(sub)}</p>
    {cta}
  </div>
</section>"""
        css = """
.sxm-hero-statement { min-height: 78vh; display: flex; align-items: center; }
.sxm-hero-statement h1 { max-width: 16ch; margin-bottom: 26px; }
.sxm-hero-statement .sxm-hero-sub { font-size: 1.15rem; max-width: 48ch; margin-bottom: 38px; }"""
        return html, css

    if variant == "banner":
        html = f"""
<section class="sxm-hero-banner" id="top">
  <img data-slot="hero_main" src="" alt="{img_alt}" class="sxm-hero-bgimg">
  <div class="sxm-hero-banner-scrim"></div>
  <div class="sxm-inner sxm-hero-banner-inner">
    {heading_accent(dna)}
    {eb}
    <h1 {ov('hero', 'headline')}>{accent_headline(headline)}</h1>
    <p class="sxm-hero-sub" {ov('hero', 'subheadline')}>{safe(sub)}</p>
    {cta}
  </div>
</section>"""
        css = """
.sxm-hero-banner { position: relative; min-height: 86vh; display: flex; align-items: flex-end;
  padding: var(--sx-section-pad) var(--sx-gutter); overflow: hidden; }
.sxm-hero-bgimg { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.sxm-hero-banner-scrim { position: absolute; inset: 0;
  background: linear-gradient(to top, var(--sx-bg) 8%, transparent 70%); }
.sxm-hero-banner-inner { position: relative; width: 100%; }
.sxm-hero-banner h1 { max-width: 15ch; margin-bottom: 20px; }
.sxm-hero-banner .sxm-hero-sub { font-size: 1.1rem; max-width: 46ch; margin-bottom: 32px; }"""
        return html, css

    # default: split
    html = f"""
<section class="sxm-section sxm-hero-split" id="top">
  <div class="sxm-inner sxm-hero-split-grid">
    <div class="sxm-hero-copy">
      {heading_accent(dna)}
      {eb}
      <h1 {ov('hero', 'headline')}>{accent_headline(headline)}</h1>
      <p class="sxm-hero-sub sxm-muted" {ov('hero', 'subheadline')}>{safe(sub)}</p>
      {cta}
    </div>
    <div class="sxm-hero-visual sxm-imgbox">
      <img data-slot="hero_main" src="" alt="{img_alt}">
    </div>
  </div>
</section>"""
    css = """
.sxm-hero-split { min-height: 72vh; display: flex; align-items: center; }
.sxm-hero-split-grid { display: grid; grid-template-columns: 1.1fr .9fr; gap: clamp(32px, 6vw, 80px); align-items: center; width: 100%; }
.sxm-hero-split h1 { margin-bottom: 22px; }
.sxm-hero-split .sxm-hero-sub { font-size: 1.12rem; margin-bottom: 34px; }
.sxm-hero-visual img { width: 100%; aspect-ratio: 4/5; object-fit: cover; border-radius: var(--sx-radius-image); }
@media (max-width: 860px) { .sxm-hero-split-grid { grid-template-columns: 1fr; } .sxm-hero-split { min-height: 0; } }"""
    return html, css
