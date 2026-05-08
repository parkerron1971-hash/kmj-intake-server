"""Micro-interactions: hover lifts, link underlines, button states, image zoom.

Hover effects are gated to `(hover: hover)` so touch devices don't get
phantom hover states. Reduced-motion users get a hard kill on transitions
and animations.
"""
from __future__ import annotations


def render_styles() -> str:
    """CSS for micro-interactions. Uses CSS variables defined by the
    Builder output (--accent, --bg, --text, --font-accent). Falls back
    to sane defaults inside color-mix() so unknown variables don't break
    rendering.
    """
    return """
<style data-pass="3-8e-micro">
/* === Pass 3.8e micro-interactions === */
@media (hover: hover) {
  /* Card hover lift */
  .split-card,
  .editorial-product,
  .immersive-product,
  .showcase-card,
  .minimal-product,
  [data-card],
  article,
  .card {
    transition: transform 0.32s cubic-bezier(0.2, 0.8, 0.2, 1),
                box-shadow 0.32s cubic-bezier(0.2, 0.8, 0.2, 1),
                border-color 0.32s ease;
    will-change: transform;
  }
  .split-card:hover,
  .editorial-product:hover,
  .immersive-product:hover,
  .showcase-card:hover,
  [data-card]:hover,
  .card:hover,
  article:hover {
    transform: translateY(-3px);
    box-shadow: 0 12px 36px -12px color-mix(in srgb, var(--accent, #c9a84c) 28%, transparent);
  }

  /* Image hover zoom (within fixed-aspect containers) */
  .showcase-card,
  .split-about-photo,
  .gallery-item,
  [data-image-frame] {
    overflow: hidden;
  }
  .showcase-card img,
  .gallery-item img,
  [data-image-frame] img {
    transition: transform 0.6s cubic-bezier(0.2, 0.8, 0.2, 1);
    will-change: transform;
  }
  .showcase-card:hover img,
  .gallery-item:hover img,
  [data-image-frame]:hover img {
    transform: scale(1.05);
  }

  /* Link underline reveal — left to right */
  a:not(.cta-button):not([data-no-underline]) {
    position: relative;
    text-decoration: none;
    background-image: linear-gradient(to right, currentColor, currentColor);
    background-size: 0% 1px;
    background-position: 0 100%;
    background-repeat: no-repeat;
    transition: background-size 0.32s cubic-bezier(0.2, 0.8, 0.2, 1);
  }
  a:not(.cta-button):not([data-no-underline]):hover {
    background-size: 100% 1px;
  }

  /* CTA button hover — gradient sweep + lift */
  .cta-button,
  [data-cta],
  button.primary,
  .btn-primary {
    position: relative;
    overflow: hidden;
    transition: transform 0.18s cubic-bezier(0.2, 0.8, 0.2, 1),
                box-shadow 0.32s ease,
                background-position 0.5s ease;
    background-size: 220% 100%;
    background-position: 100% 0;
  }
  .cta-button:hover,
  [data-cta]:hover,
  button.primary:hover,
  .btn-primary:hover {
    transform: translateY(-2px) scale(1.02);
    box-shadow: 0 10px 30px -10px color-mix(in srgb, var(--accent, #c9a84c) 50%, transparent);
    background-position: 0 0;
  }
  .cta-button:active,
  [data-cta]:active,
  button.primary:active,
  .btn-primary:active {
    transform: translateY(0) scale(0.98);
    transition-duration: 0.08s;
  }
}

/* Touch devices: no hover lifts, just press feedback on CTAs */
@media (hover: none) {
  .cta-button:active,
  [data-cta]:active,
  button.primary:active,
  .btn-primary:active {
    transform: scale(0.98);
    transition: transform 0.08s ease;
  }
}

/* Reduced motion: kill transitions/animations + cancel transform */
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    transition-duration: 0.01ms !important;
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
  }
  .split-card:hover,
  .editorial-product:hover,
  .immersive-product:hover,
  .showcase-card:hover,
  [data-card]:hover,
  .cta-button:hover,
  [data-cta]:hover,
  button.primary:hover,
  .btn-primary:hover {
    transform: none !important;
  }
}
</style>
"""
