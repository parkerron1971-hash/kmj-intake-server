"""Scroll behaviors: fade-up reveals, parallax, smooth scroll, sticky CTAs.

Uses IntersectionObserver for reveals (no library). Auto-tags top-level
section/article elements unless the hero. Builds a sticky CTA bar by
cloning the primary CTA out of the hero.
"""
from __future__ import annotations


def render_styles() -> str:
    return """
<style data-pass="3-8e-scroll">
html { scroll-behavior: smooth; }

/* Fade-up reveal baseline (set by JS, animated by CSS) */
[data-reveal] {
  opacity: 0;
  transform: translateY(24px);
  transition: opacity 0.7s cubic-bezier(0.2, 0.8, 0.2, 1),
              transform 0.7s cubic-bezier(0.2, 0.8, 0.2, 1);
  transition-delay: var(--reveal-delay, 0s);
  will-change: opacity, transform;
}
[data-reveal].is-revealed {
  opacity: 1;
  transform: translateY(0);
}

/* Subtle parallax hooks (transform set by JS) */
[data-parallax] {
  will-change: transform;
}

/* Sticky CTA bar — slides up after the hero scrolls past */
.sticky-cta-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  padding: 0.85rem clamp(1rem, 4vw, 2rem);
  background: color-mix(in srgb, var(--bg, #0a0a0a) 96%, transparent);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-top: 1px solid color-mix(in srgb, var(--accent, #c9a84c) 20%, transparent);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  transform: translateY(110%);
  transition: transform 0.4s cubic-bezier(0.2, 0.8, 0.2, 1);
  z-index: 100;
  pointer-events: none;
}
.sticky-cta-bar.visible {
  transform: translateY(0);
  pointer-events: auto;
}
.sticky-cta-bar-label {
  font-family: var(--font-accent, sans-serif);
  font-size: 0.78rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text, #f4f4f4);
  opacity: 0.75;
  margin: 0;
}
.sticky-cta-bar a {
  background-image: none !important;
}
@media (max-width: 640px) {
  .sticky-cta-bar-label { display: none; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  [data-reveal] { opacity: 1; transform: none; transition: none; }
  [data-parallax] { transform: none !important; }
  .sticky-cta-bar { transition: none; }
}
</style>
"""


def render_script() -> str:
    return """
<script data-pass="3-8e-scroll">
(function() {
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    document.querySelectorAll('[data-reveal]').forEach(function(el) {
      el.classList.add('is-revealed');
    });
    return;
  }

  // Hero selectors — used for both reveal-skip and sticky CTA source
  var heroSelectors = [
    '.split-hero',
    '.editorial-hero',
    '.immersive-section.scene-1',
    '.showcase-hero',
    '.statement-hero',
    '.minimal-hero'
  ];

  // Auto-tag candidate sections for reveal if not explicitly tagged.
  // Skip the hero (it should be visible immediately on load).
  var autoTagSelectors = [
    'section', 'article',
    '.split-section', '.editorial-section',
    '.immersive-section', '.showcase-section', '.minimal-section',
    '[data-section]'
  ];
  var heroSelectorString = heroSelectors.join(', ');
  autoTagSelectors.forEach(function(sel) {
    document.querySelectorAll(sel).forEach(function(el) {
      if (el.hasAttribute('data-reveal')) return;
      // Don't auto-tag hero blocks
      try {
        if (el.matches(heroSelectorString)) return;
      } catch (_) { /* matches throws on invalid combined selectors */ }
      el.setAttribute('data-reveal', '');
    });
  });

  // Intersection Observer for fade-up reveals
  if ('IntersectionObserver' in window) {
    var io = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (!entry.isIntersecting) return;
        var parent = entry.target.parentElement;
        var siblings = parent
          ? Array.prototype.slice.call(parent.children).filter(function(s) {
              return s.hasAttribute && s.hasAttribute('data-reveal');
            })
          : [];
        var idx = siblings.indexOf(entry.target);
        if (idx > 0 && idx < 6) {
          entry.target.style.setProperty('--reveal-delay', (idx * 0.08) + 's');
        }
        entry.target.classList.add('is-revealed');
        io.unobserve(entry.target);
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
    document.querySelectorAll('[data-reveal]').forEach(function(el) {
      io.observe(el);
    });
  } else {
    document.querySelectorAll('[data-reveal]').forEach(function(el) {
      el.classList.add('is-revealed');
    });
  }

  // Subtle parallax on backgrounds tagged with [data-parallax]
  var parallaxEls = document.querySelectorAll('[data-parallax]');
  if (parallaxEls.length) {
    var ticking = false;
    function update() {
      parallaxEls.forEach(function(el) {
        var rect = el.getBoundingClientRect();
        var move = rect.top * -0.08;
        el.style.transform = 'translate3d(0,' + move + 'px,0)';
      });
      ticking = false;
    }
    window.addEventListener('scroll', function() {
      if (!ticking) { requestAnimationFrame(update); ticking = true; }
    }, { passive: true });
    update();
  }

  // Auto-build sticky CTA bar from the hero's primary CTA (mobile-leaning UX)
  function buildStickyCTA() {
    var hero = null;
    for (var i = 0; i < heroSelectors.length; i++) {
      hero = document.querySelector(heroSelectors[i]);
      if (hero) break;
    }
    if (!hero) hero = document.querySelector('section');
    if (!hero) return;

    var primaryCTA = hero.querySelector(
      '.cta-button, [data-cta], .btn-primary, button.primary, ' +
      'a[href^="#contact"], a[href^="mailto:"]'
    );
    if (!primaryCTA) return;

    var cloneText = (primaryCTA.textContent || '').trim();
    var cloneHref = primaryCTA.getAttribute('href') || '#contact';
    if (!cloneText) return;

    var bar = document.createElement('div');
    bar.className = 'sticky-cta-bar';
    var label = document.createElement('span');
    label.className = 'sticky-cta-bar-label';
    label.textContent = 'Ready when you are';
    var link = document.createElement('a');
    link.className = 'cta-button';
    link.href = cloneHref;
    link.textContent = cloneText;
    bar.appendChild(label);
    bar.appendChild(link);
    document.body.appendChild(bar);

    // Show after hero scrolls past viewport
    var heroObs = new IntersectionObserver(function(entries) {
      entries.forEach(function(entry) {
        if (!entry.isIntersecting) {
          bar.classList.add('visible');
        } else {
          bar.classList.remove('visible');
        }
      });
    }, { threshold: 0.05 });
    heroObs.observe(hero);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildStickyCTA);
  } else {
    buildStickyCTA();
  }
})();
</script>
"""
