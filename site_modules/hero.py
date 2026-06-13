"""Hero module — 3 expression variants. Content: eyebrow, headline,
subheadline, cta_label. Image slot: hero_main (split/banner only)."""
from __future__ import annotations

from typing import Any, Dict, Tuple

from ._base import safe, ov, cta_button, eyebrow, heading_accent

VARIANTS = ("split", "statement", "banner", "cinematic")


def render(variant: str, content: Dict[str, Any], ctx: Dict[str, Any]) -> Tuple[str, str]:
    dna = ctx["dna"]
    headline = content.get("headline") or (ctx.get("business") or {}).get("name") or "Welcome"
    sub = content.get("subheadline") or ""
    eb = eyebrow("hero", content.get("eyebrow") or "")
    cta = cta_button(ctx, content.get("cta_label") or "Book a session", "hero")

    if variant == "cinematic":
        # Full-bleed, art-directed: tall viewport, image graded by a layered
        # scrim, oversized display headline anchored low-left. The premium
        # "walk into a strategy session" first impression.
        html = f"""
<section class="sxm-hero-cine" id="top">
  <img data-slot="hero_main" src="" alt="" class="sxm-cine-bg">
  <div class="sxm-cine-scrim"></div>
  <div class="sxm-inner sxm-cine-inner">
    <div class="sxm-cine-copy">
      {eb}
      <h1 {ov('hero', 'headline')}>{safe(headline)}</h1>
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
.sxm-hero-cine h1 { font-size: clamp(2.8rem, 7.2vw, 6rem); margin-bottom: 22px; }
.sxm-hero-cine .sxm-cine-sub { font-size: 1.18rem; max-width: 44ch; margin-bottom: 36px; color: var(--sx-text);
  opacity: .92; }
.sxm-hero-cine .sxm-eyebrow { color: var(--sx-accent); }
@media (max-width: 768px) { .sxm-hero-cine { min-height: 92vh; } }"""
        return html, css

    if variant == "statement":
        html = f"""
<section class="sxm-section sxm-hero-statement" id="top">
  <div class="sxm-inner">
    {eb}
    <h1 {ov('hero', 'headline')}>{safe(headline)}</h1>
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
  <img data-slot="hero_main" src="" alt="" class="sxm-hero-bgimg">
  <div class="sxm-hero-banner-scrim"></div>
  <div class="sxm-inner sxm-hero-banner-inner">
    {eb}
    <h1 {ov('hero', 'headline')}>{safe(headline)}</h1>
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
      {eb}
      <h1 {ov('hero', 'headline')}>{safe(headline)}</h1>
      <p class="sxm-hero-sub sxm-muted" {ov('hero', 'subheadline')}>{safe(sub)}</p>
      {cta}
    </div>
    <div class="sxm-hero-visual">
      <img data-slot="hero_main" src="" alt="">
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
