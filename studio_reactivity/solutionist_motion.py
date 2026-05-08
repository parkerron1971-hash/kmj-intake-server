"""Pass 3.8g — Solutionist motion injection.

Adds the Solutionist signature animation layer:
  - Always-on film grain overlay (8s steps animation)
  - Shimmer pass on every primary CTA
  - Floating diamonds for luxury / dark / corporate strand pages
  - Pulse glow on hero photo / feature frame
  - 0.9s cubic-bezier(0.16, 1, 0.3, 1) reveal timing override
  - .accent-word styling for italic accent words inside h2

Each helper returns a self-contained CSS string so inject.py can append
it without worrying about ordering. Every animation respects
prefers-reduced-motion.
"""
from __future__ import annotations


def render_solutionist_styles() -> str:
    """Return the Solutionist motion stylesheet as one <style> block.

    Inserted just before </head> by inject.py. Designed to be additive
    on top of the Pass 3.8e baseline (micro_interactions, scroll_behaviors,
    strand_gradients) — selectors are unique to this module, so nothing
    is overwritten except the data-reveal transition timing (intentional).
    """
    return """
<style data-pass="3-8g-solutionist">
/* === Film grain overlay — ALWAYS ON (subtle, 1.8% opacity) === */
body::before {
  content: '';
  position: fixed;
  inset: -50%;
  width: 200%;
  height: 200%;
  pointer-events: none;
  z-index: 1;
  opacity: 0.018;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.9'/></filter><rect width='100%25' height='100%25' filter='url(%23n)'/></svg>");
  animation: solutionist-grain 8s steps(10) infinite;
}

@keyframes solutionist-grain {
  0%, 100% { transform: translate(0, 0); }
  10% { transform: translate(-5%, -10%); }
  30% { transform: translate(3%, -15%); }
  50% { transform: translate(12%, 9%); }
  70% { transform: translate(9%, 4%); }
  90% { transform: translate(-1%, 7%); }
}

@media (prefers-reduced-motion: reduce) {
  body::before { animation: none; }
}

/* === Shimmer on primary CTA === */
.cta-button, [data-cta], button.primary, .btn-primary, .btn-gold {
  position: relative;
  overflow: hidden;
}
.cta-button::after, [data-cta]::after, button.primary::after,
.btn-primary::after, .btn-gold::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.22), transparent);
  background-size: 200% 100%;
  animation: solutionist-shimmer 2.5s linear infinite;
  pointer-events: none;
}

@keyframes solutionist-shimmer {
  0%   { background-position: -200% 0; }
  100% { background-position:  200% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .cta-button::after, [data-cta]::after, button.primary::after,
  .btn-primary::after, .btn-gold::after { animation: none; }
}

/* === Floating diamonds (rendered inline via render_floating_diamonds_for_strand) === */
.solutionist-diamond {
  position: absolute;
  pointer-events: none;
  transform: rotate(45deg);
  border-radius: 4px;
  animation: solutionist-float 6s ease-in-out infinite;
}

@keyframes solutionist-float {
  0%, 100% { transform: rotate(45deg) translateY(0); }
  50%      { transform: rotate(45deg) translateY(-14px); }
}

@media (prefers-reduced-motion: reduce) {
  .solutionist-diamond { animation: none; }
}

/* === Pulse glow on headshot / feature frames === */
[data-headshot-frame], [data-feature-frame] {
  animation: solutionist-pulse-glow 4s ease-in-out infinite;
}

@keyframes solutionist-pulse-glow {
  0%, 100% { box-shadow: 0 0 40px rgba(198, 149, 47, 0.15); }
  50%      { box-shadow: 0 0 80px rgba(198, 149, 47, 0.25); }
}

@media (prefers-reduced-motion: reduce) {
  [data-headshot-frame], [data-feature-frame] { animation: none; }
}

/* === Solutionist signature reveal — overrides Pass 3.8e baseline === */
[data-reveal] {
  transition: opacity 0.9s cubic-bezier(0.16, 1, 0.3, 1),
              transform 0.9s cubic-bezier(0.16, 1, 0.3, 1);
}

/* === Solutionist signature easing on key elements === */
.split-card, .editorial-product, .immersive-product, .showcase-card,
.minimal-product, [data-card], .card,
.cta-button, [data-cta], button.primary, .btn-primary, .btn-gold {
  transition-timing-function: cubic-bezier(0.16, 1, 0.3, 1) !important;
}

/* === Italic accent word styling === */
.accent-word, em.accent-word {
  font-style: italic;
  font-weight: 400;
  color: var(--accent, #c9a84c);
}
</style>
"""


def render_floating_diamonds_for_strand(strand_id: str) -> str:
    """Decorative diamond layer for dark / luxury / corporate strands.

    Returned as a positioned div ready to be dropped into a hero or
    section. Empty string for any other strand so callers can blindly
    concat.
    """
    if strand_id not in ("luxury", "dark", "corporate"):
        return ""
    return """
<div aria-hidden="true" class="solutionist-diamonds-layer" style="position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;overflow:hidden;z-index:0;">
  <div class="solutionist-diamond" style="top:8%;left:6%;width:80px;height:80px;background:rgba(198,149,47,0.04);animation-delay:0s;"></div>
  <div class="solutionist-diamond" style="top:30%;right:10%;width:120px;height:120px;border:1px solid rgba(198,149,47,0.08);animation-delay:1.5s;"></div>
  <div class="solutionist-diamond" style="bottom:20%;left:15%;width:60px;height:60px;background:rgba(198,149,47,0.04);animation-delay:3s;"></div>
  <div class="solutionist-diamond" style="bottom:35%;right:5%;width:200px;height:200px;border:1px solid rgba(198,149,47,0.06);animation-delay:2s;"></div>
</div>
"""
