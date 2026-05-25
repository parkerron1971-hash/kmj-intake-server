"""
marketing_pages.py — Multi-page public marketing site for mysolutionist.app.

Pages served:
  /            → Home (hero + features + audience + why + CTA)
  /features    → Deep feature explanation, surface by surface
  /compare     → Solutionist vs the 8-tool stack (with cost breakdown)
  /faq         → FAQ on its own URL
  /about       → Founder note + company
  /get-started → Intake form (POSTs to /api/leads)

All pages share a single shell (nav + footer + CSS + scroll-reveal
script) so they feel like one product. Edit copy here; routes in
public_site.py pick up automatically.
"""

from __future__ import annotations

import datetime
import html as _html
import json
import logging
import os
from typing import Any, Dict, Optional

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, EmailStr

CONTACT_EMAIL = "kmjcreativesolution@gmail.com"
BUSINESS_NAME = "KMJ Creative Solutions LLC"
SITE_NAME = "The Solutionist System"
SITE_DOMAIN = "mysolutionist.app"

logger = logging.getLogger("marketing_pages")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] marketing: %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)


# ══════════════════════════════════════════════════════════════════════
# SHARED SHELL — CSS + nav + footer + scroll-reveal script
# Per-page bodies plug in via {content}.
# ══════════════════════════════════════════════════════════════════════

SHARED_CSS = """
  :root {
    --bg: #0a0a0e;
    --bg-2: #11111a;
    --surface: rgba(255,255,255,0.04);
    --surface-2: rgba(255,255,255,0.06);
    --border: rgba(255,255,255,0.08);
    --border-strong: rgba(255,255,255,0.14);
    --text-primary: #fafafa;
    --text-secondary: #d4d4d4;
    --text-muted: #a1a1a1;
    --text-dim: #737373;
    --accent: #7c3aed;
    --accent-2: #6366f1;
    --info: #06b6d4;
    --success: #34d399;
    --warning: #fbbf24;
    --danger: #f87171;
    --glow: rgba(124, 58, 237, 0.35);
    --glow-cyan: rgba(6, 182, 212, 0.28);
    --font-heading: 'Space Grotesk', system-ui, sans-serif;
    --font-body: 'Inter', system-ui, sans-serif;
  }
  *{margin:0;padding:0;box-sizing:border-box;}
  html,body{background:var(--bg);color:var(--text-primary);font-family:var(--font-body);line-height:1.6;-webkit-font-smoothing:antialiased;}
  body{overflow-x:hidden;}
  a{color:inherit;text-decoration:none;}
  img{max-width:100%;display:block;}

  .container{max-width:1140px;margin:0 auto;padding:0 28px;}
  .container-narrow{max-width:820px;margin:0 auto;padding:0 28px;}
  .eyebrow{display:inline-flex;align-items:center;gap:8px;padding:5px 14px;font-size:10px;font-weight:700;letter-spacing:2.4px;text-transform:uppercase;color:var(--accent);background:color-mix(in srgb, var(--accent) 12%, transparent);border:1px solid color-mix(in srgb, var(--accent) 28%, transparent);border-radius:99px;}
  .gradient-text{background:linear-gradient(135deg, var(--accent), var(--info));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
  h1,h2,h3{font-family:var(--font-heading);letter-spacing:-0.015em;line-height:1.1;}
  h1{font-size:clamp(38px, 6vw, 60px);font-weight:600;}
  h2{font-size:clamp(28px, 4vw, 40px);font-weight:600;margin-bottom:14px;}
  h3{font-size:18px;font-weight:600;color:var(--text-primary);margin-bottom:6px;}
  p{color:var(--text-secondary);font-size:16px;}
  .lead{font-size:18px;color:var(--text-muted);line-height:1.65;}

  /* ─── nav ─── */
  .nav{position:sticky;top:0;z-index:50;background:rgba(10,10,14,0.78);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border-bottom:1px solid var(--border);}
  .nav-inner{display:flex;align-items:center;justify-content:space-between;padding:14px 28px;max-width:1140px;margin:0 auto;}
  .brand{font-family:var(--font-heading);font-size:17px;font-weight:600;color:var(--text-primary);letter-spacing:-0.01em;display:inline-flex;align-items:center;gap:10px;}
  .brand .logo{height:32px;width:auto;display:block;filter:drop-shadow(0 0 8px var(--glow));}
  .footer .brand .logo{height:28px;}
  .brand .dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));box-shadow:0 0 8px var(--glow);}
  .brand-text{display:inline-block;}
  @media (max-width: 540px){.brand-text{display:none;}}
  .nav-links{display:flex;align-items:center;gap:22px;font-size:13px;font-weight:500;}
  .nav-links a{color:var(--text-muted);transition:color 0.15s;position:relative;}
  .nav-links a:hover, .nav-links a.is-active{color:var(--text-primary);}
  .nav-links a.is-active::after{content:'';position:absolute;left:0;right:0;bottom:-18px;height:2px;background:linear-gradient(90deg, var(--accent), var(--info));border-radius:2px;}
  .nav-cta{padding:8px 16px;background:linear-gradient(135deg, var(--accent), var(--info));color:var(--text-primary) !important;border-radius:8px;font-weight:600;font-size:13px;box-shadow:0 2px 14px color-mix(in srgb, var(--accent) 28%, transparent);transition:transform 0.15s, box-shadow 0.15s;}
  .nav-cta:hover{transform:translateY(-1px);box-shadow:0 4px 18px color-mix(in srgb, var(--accent) 42%, transparent);}
  .nav-cta.is-active::after{display:none;}
  @media (max-width: 760px){.nav-links{gap:12px;font-size:12px;} .nav-links a:not(.nav-cta){display:none;}}

  /* ─── buttons ─── */
  .btn-primary{display:inline-flex;align-items:center;gap:8px;padding:13px 26px;background:linear-gradient(135deg, var(--accent), var(--info));color:var(--text-primary);font-weight:600;font-size:14px;border-radius:10px;border:none;cursor:pointer;box-shadow:0 4px 22px color-mix(in srgb, var(--accent) 35%, transparent);transition:transform 0.15s, box-shadow 0.15s;font-family:inherit;}
  .btn-primary:hover{transform:translateY(-2px);box-shadow:0 8px 30px color-mix(in srgb, var(--accent) 50%, transparent);}
  .btn-secondary{display:inline-flex;align-items:center;gap:8px;padding:13px 22px;background:var(--surface);color:var(--text-primary);font-weight:600;font-size:14px;border-radius:10px;border:1px solid var(--border-strong);cursor:pointer;transition:background 0.15s, border-color 0.15s;font-family:inherit;}
  .btn-secondary:hover{background:var(--surface-2);border-color:color-mix(in srgb, var(--accent) 50%, transparent);}

  /* ─── animations + reveals ─── */
  @keyframes brandPulse {
    0%, 100% { box-shadow: 0 0 10px var(--glow); }
    50%      { box-shadow: 0 0 16px var(--glow), 0 0 4px color-mix(in srgb, var(--accent) 80%, transparent); }
  }
  @keyframes logoGlow {
    0%, 100% { filter: drop-shadow(0 0 8px var(--glow)); }
    50%      { filter: drop-shadow(0 0 14px var(--glow)) drop-shadow(0 0 4px color-mix(in srgb, var(--info) 60%, transparent)); }
  }
  .brand .logo { animation: logoGlow 3s ease-in-out infinite; }
  .brand .dot  { animation: brandPulse 2.6s ease-in-out infinite; }
  .orb{position:absolute;border-radius:50%;filter:blur(50px);opacity:0.55;pointer-events:none;z-index:0;}
  .orb-1{top:10%;left:8%;width:280px;height:280px;background:radial-gradient(circle, var(--glow), transparent 70%);animation:orbDrift1 18s ease-in-out infinite;}
  .orb-2{top:60%;right:6%;width:220px;height:220px;background:radial-gradient(circle, var(--glow-cyan), transparent 70%);animation:orbDrift2 22s ease-in-out infinite;}
  .orb-3{bottom:-40px;left:40%;width:200px;height:200px;background:radial-gradient(circle, color-mix(in srgb, var(--accent-2) 35%, transparent), transparent 70%);animation:orbDrift3 26s ease-in-out infinite;opacity:0.4;}
  @keyframes orbDrift1{0%,100%{transform:translate(0,0);}50%{transform:translate(40px,-30px);}}
  @keyframes orbDrift2{0%,100%{transform:translate(0,0);}50%{transform:translate(-30px,25px);}}
  @keyframes orbDrift3{0%,100%{transform:translate(0,0);}50%{transform:translate(20px,-20px);}}
  .reveal{opacity:0;transform:translateY(18px);transition:opacity 0.6s ease, transform 0.6s ease;}
  .reveal.visible{opacity:1;transform:translateY(0);}
  .reveal-delay-1{transition-delay:0.08s;}
  .reveal-delay-2{transition-delay:0.16s;}
  .reveal-delay-3{transition-delay:0.24s;}

  /* ─── section base ─── */
  section{position:relative;padding:80px 0;}
  .section-head{text-align:center;max-width:680px;margin:0 auto 56px;}
  .section-head .eyebrow{margin-bottom:14px;}
  .section-head p{color:var(--text-muted);margin-top:8px;}

  .card{background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:26px;transition:transform 0.18s, border-color 0.18s, background 0.18s;}
  .card:hover{transform:translateY(-2px);border-color:color-mix(in srgb, var(--accent) 35%, transparent);}
  .card-icon{display:inline-flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:10px;background:color-mix(in srgb, var(--accent) 14%, transparent);color:var(--accent);font-size:20px;margin-bottom:14px;border:1px solid color-mix(in srgb, var(--accent) 30%, transparent);}

  /* ─── stat block ─── */
  .stat-block{display:inline-flex;align-items:baseline;gap:8px;margin-top:6px;padding:8px 16px;background:var(--surface);border:1px solid var(--border);border-radius:99px;font-size:13px;color:var(--text-muted);}
  .stat-block .big{font-family:var(--font-heading);font-size:22px;font-weight:700;color:transparent;background:linear-gradient(135deg, var(--accent), var(--info));-webkit-background-clip:text;background-clip:text;line-height:1;}
  .stat-block .big::after{content:'';display:inline-block;width:4px;height:4px;border-radius:50%;background:var(--accent);margin-left:6px;box-shadow:0 0 6px var(--glow);animation:brandPulse 1.8s ease-in-out infinite;}

  /* ─── footer ─── */
  footer{background:var(--bg-2);border-top:1px solid var(--border);padding:42px 0 32px;}
  .footer-inner{max-width:1140px;margin:0 auto;padding:0 28px;display:flex;justify-content:space-between;align-items:flex-start;gap:24px;flex-wrap:wrap;}
  .footer-brand{display:flex;flex-direction:column;gap:6px;}
  .footer-brand .small{font-size:12px;color:var(--text-dim);}
  .footer-links{display:flex;flex-wrap:wrap;gap:18px;font-size:13px;}
  .footer-links a{color:var(--text-muted);transition:color 0.15s;}
  .footer-links a:hover{color:var(--text-primary);}
  .footer-bottom{max-width:1140px;margin:32px auto 0;padding:16px 28px 0;border-top:1px solid var(--border);font-size:11px;color:var(--text-dim);display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;}

  /* ─── shared feature mini-visuals ─── */
  .mini-visual{height:64px;margin-bottom:18px;position:relative;background:linear-gradient(180deg, color-mix(in srgb, var(--surface-2) 60%, transparent), transparent);border-radius:10px;overflow:hidden;display:flex;align-items:center;justify-content:center;}
  .mv-orbit{position:relative;width:56px;height:56px;}
  .mv-orbit::before,.mv-orbit::after{content:'';position:absolute;border-radius:50%;border:1px dashed color-mix(in srgb, var(--accent) 35%, transparent);}
  .mv-orbit::before{inset:0;}
  .mv-orbit::after{inset:12px;border-color:color-mix(in srgb, var(--info) 35%, transparent);}
  .mv-orbit .center{position:absolute;top:50%;left:50%;width:10px;height:10px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));transform:translate(-50%,-50%);box-shadow:0 0 10px var(--glow);}
  .mv-orbit .moon{position:absolute;top:50%;left:50%;width:6px;height:6px;border-radius:50%;background:var(--accent);margin:-3px 0 0 -3px;animation:orbitSpin 6s linear infinite;transform-origin:0 0;}
  .mv-orbit .moon-2{background:var(--info);animation-duration:9s;animation-delay:-3s;}
  @keyframes orbitSpin{from{transform:rotate(0deg) translateX(22px) rotate(0deg);}to{transform:rotate(360deg) translateX(22px) rotate(-360deg);}}
  .mv-stack{position:relative;width:64px;height:48px;}
  .mv-stack span{position:absolute;width:48px;height:30px;border-radius:6px;border:1px solid var(--border);background:var(--surface);transition:transform 0.25s ease;}
  .mv-stack span:nth-child(1){top:0;left:0;background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 18%, transparent), transparent);}
  .mv-stack span:nth-child(2){top:6px;left:8px;background:linear-gradient(135deg, color-mix(in srgb, var(--info) 16%, transparent), transparent);animation:stackFloat 5s ease-in-out infinite;}
  .mv-stack span:nth-child(3){top:14px;left:16px;background:linear-gradient(135deg, color-mix(in srgb, var(--success) 15%, transparent), transparent);animation:stackFloat 5s ease-in-out infinite;animation-delay:-2.5s;}
  @keyframes stackFloat{0%,100%{transform:translateY(0);}50%{transform:translateY(-3px);}}
  .mv-grid{display:grid;grid-template-columns:repeat(5, 8px);grid-template-rows:repeat(3, 8px);gap:3px;}
  .mv-grid span{width:8px;height:8px;border-radius:2px;background:color-mix(in srgb, var(--accent) 14%, transparent);border:1px solid var(--border);}
  .mv-grid span.live{background:linear-gradient(135deg, var(--accent), var(--info));border-color:transparent;box-shadow:0 0 6px var(--glow);animation:gridPing 2.4s ease-in-out infinite;}
  @keyframes gridPing{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.6;transform:scale(1.2);}}
  .mv-bars{display:flex;align-items:flex-end;gap:4px;height:36px;}
  .mv-bars span{width:6px;border-radius:2px 2px 0 0;background:linear-gradient(180deg, var(--accent), var(--info));animation:barRise 3.2s ease-in-out infinite;}
  .mv-bars span:nth-child(1){height:40%;animation-delay:0s;}
  .mv-bars span:nth-child(2){height:70%;animation-delay:-0.4s;}
  .mv-bars span:nth-child(3){height:55%;animation-delay:-0.8s;}
  .mv-bars span:nth-child(4){height:90%;animation-delay:-1.2s;}
  .mv-bars span:nth-child(5){height:65%;animation-delay:-1.6s;}
  @keyframes barRise{0%,100%{transform:scaleY(0.85);opacity:0.85;transform-origin:bottom;}50%{transform:scaleY(1.05);opacity:1;}}
  .mv-spark{position:relative;width:36px;height:36px;}
  .mv-spark::before,.mv-spark::after{content:'';position:absolute;inset:0;border-radius:50%;border:1px solid var(--accent);opacity:0.5;animation:sparkExpand 2.6s ease-out infinite;}
  .mv-spark::after{animation-delay:-1.3s;border-color:var(--info);}
  .mv-spark .core{position:absolute;top:50%;left:50%;width:12px;height:12px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));transform:translate(-50%,-50%);box-shadow:0 0 14px var(--glow);}
  @keyframes sparkExpand{0%{transform:scale(0.4);opacity:0.9;}100%{transform:scale(1.6);opacity:0;}}
  .mv-publish{display:flex;align-items:center;gap:12px;}
  .mv-publish .platform{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;color:#fff;}
  .mv-publish .fb{background:#1877F2;}
  .mv-publish .ig{background:linear-gradient(135deg, #833AB4, #FD1D1D, #FCB045);}
  .mv-publish .flow{flex:1;min-width:16px;max-width:24px;height:2px;background:linear-gradient(90deg, transparent, var(--accent), var(--info), transparent);background-size:200% 100%;animation:flowSweep 2.4s linear infinite;border-radius:2px;}
  @keyframes flowSweep{0%{background-position:200% 0;}100%{background-position:-200% 0;}}

  /* ─── page-hero (for non-home pages) ─── */
  .page-hero{position:relative;padding:80px 0 60px;text-align:center;overflow:hidden;border-bottom:1px solid var(--border);}
  .page-hero::before{content:'';position:absolute;inset:-40px 0 auto;height:280px;background:radial-gradient(60% 80% at 50% 0%, var(--glow), transparent 70%);pointer-events:none;opacity:0.6;}
  .page-hero .container{position:relative;z-index:1;}
  .page-hero h1{margin:14px 0 16px;}
"""

SHELL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} — The Solutionist System</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="https://mysolutionist.app{path}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="The Solutionist System">
<meta property="og:image" content="https://mysolutionist.app/assets/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="https://mysolutionist.app/assets/og.png">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/favicon.png">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{shared_css}{extra_css}</style>
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <a class="brand" href="/">
      <img class="logo" src="/assets/logo-nav.png" alt="The Solutionist System">
      <span class="brand-text">The Solutionist System</span>
    </a>
    <div class="nav-links">
      <a href="/features" class="{ax_features}">Features</a>
      <a href="/compare" class="{ax_compare}">Compare</a>
      <a href="/faq" class="{ax_faq}">FAQ</a>
      <a href="/about" class="{ax_about}">About</a>
      <a href="/help" class="{ax_help}">Help</a>
      <a class="nav-cta {ax_get_started}" href="/get-started">Get Started</a>
    </div>
  </div>
</nav>

{content}

<footer>
  <div class="footer-inner">
    <div class="footer-brand">
      <span class="brand">
        <img class="logo" src="/assets/logo-nav.png" alt="The Solutionist System" style="height:28px;">
        <span class="brand-text">The Solutionist System</span>
      </span>
      <span class="small">Built by KMJ Creative Solutions LLC · Michigan, USA</span>
    </div>
    <div class="footer-links">
      <a href="/features">Features</a>
      <a href="/compare">Compare</a>
      <a href="/faq">FAQ</a>
      <a href="/about">About</a>
      <a href="/get-started">Get Started</a>
      <a href="/help">Help</a>
      <a href="/privacy">Privacy</a>
      <a href="/data-deletion">Data Deletion</a>
      <a href="/terms">Terms</a>
      <a href="mailto:{contact_email}">Contact</a>
    </div>
  </div>
  <div class="footer-bottom">
    <span>&copy; {year} {business_name}</span>
    <span>mysolutionist.app</span>
  </div>
</footer>

<script>
  (function() {{
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var els = document.querySelectorAll('.reveal');
    if (reduced || !('IntersectionObserver' in window)) {{
      for (var i = 0; i < els.length; i++) els[i].classList.add('visible');
    }} else {{
      var io = new IntersectionObserver(function(entries) {{
        entries.forEach(function(entry) {{
          if (entry.isIntersecting) {{
            entry.target.classList.add('visible');
            io.unobserve(entry.target);
          }}
        }});
      }}, {{ threshold: 0.12, rootMargin: '0px 0px -40px 0px' }});
      for (var j = 0; j < els.length; j++) io.observe(els[j]);
    }}
    document.querySelectorAll('a[href^="#"]').forEach(function(a) {{
      a.addEventListener('click', function(e) {{
        var id = a.getAttribute('href').slice(1);
        if (!id) return;
        var target = document.getElementById(id);
        if (target) {{
          e.preventDefault();
          target.scrollIntoView({{ behavior: reduced ? 'auto' : 'smooth', block: 'start' }});
        }}
      }});
    }});
  }})();
</script>
{extra_scripts}
</body>
</html>"""


def _render_shell(*, title: str, description: str, content_html: str, path: str = "/",
                  active: str = "", extra_css: str = "", extra_scripts: str = "") -> str:
    """Render any page in the shared shell. `active` keys into the nav
    to mark the current page (one of: features, compare, faq, about,
    help, get_started)."""
    active_map = {
        "ax_features":    "is-active" if active == "features"    else "",
        "ax_compare":     "is-active" if active == "compare"     else "",
        "ax_faq":         "is-active" if active == "faq"         else "",
        "ax_about":       "is-active" if active == "about"       else "",
        "ax_help":        "is-active" if active == "help"        else "",
        "ax_get_started": "is-active" if active == "get_started" else "",
    }
    return SHELL_TEMPLATE.format(
        title=_html.escape(title),
        description=_html.escape(description),
        og_title=_html.escape(f"{title} — {SITE_NAME}"),
        path=path,
        shared_css=SHARED_CSS,
        extra_css=extra_css,
        contact_email=_html.escape(CONTACT_EMAIL),
        business_name=_html.escape(BUSINESS_NAME),
        year=datetime.date.today().year,
        content=content_html,
        extra_scripts=extra_scripts,
        **active_map,
    )


# ══════════════════════════════════════════════════════════════════════
# HOME — trimmed: hero + features overview + audience + why + CTA
# ══════════════════════════════════════════════════════════════════════

def render_home() -> str:
    extra_css = """
      .hero{position:relative;padding:88px 0 96px;text-align:center;overflow:hidden;}
      .hero::before{content:'';position:absolute;inset:-80px 0 auto;height:520px;background:radial-gradient(60% 80% at 50% 0%, var(--glow), transparent 70%);pointer-events:none;}
      .hero .container{position:relative;z-index:1;}
      .hero h1{margin:18px auto 22px;max-width:900px;}
      .hero .lead{max-width:680px;margin:0 auto 36px;}
      .hero-ctas{display:flex;flex-wrap:wrap;gap:12px;justify-content:center;}
      .hero-note{margin-top:22px;font-size:12px;color:var(--text-dim);}
      .features-grid{display:grid;grid-template-columns:repeat(3, 1fr);gap:18px;}
      @media (max-width: 920px){.features-grid{grid-template-columns:repeat(2, 1fr);}}
      @media (max-width: 600px){.features-grid{grid-template-columns:1fr;}}
      .feature-card p{font-size:14px;color:var(--text-muted);line-height:1.6;}
      .audience{padding:64px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);background:linear-gradient(180deg, transparent, color-mix(in srgb, var(--accent) 4%, transparent), transparent);}
      .audience-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;}
      .audience-pill{display:inline-flex;align-items:center;gap:8px;padding:10px 18px;background:var(--surface);border:1px solid var(--border);border-radius:99px;font-size:14px;font-weight:500;color:var(--text-secondary);transition:border-color 0.18s, background 0.18s;}
      .audience-pill:hover{border-color:color-mix(in srgb, var(--accent) 40%, transparent);background:color-mix(in srgb, var(--accent) 8%, transparent);}
      .audience-pill .emoji{font-size:18px;}
      .why-grid{display:grid;grid-template-columns:repeat(2, 1fr);gap:18px;}
      @media (max-width: 760px){.why-grid{grid-template-columns:1fr;}}
      .why-card{display:flex;gap:16px;}
      .why-card .check{flex-shrink:0;width:32px;height:32px;border-radius:8px;background:color-mix(in srgb, var(--success) 18%, transparent);color:var(--success);display:inline-flex;align-items:center;justify-content:center;font-weight:700;border:1px solid color-mix(in srgb, var(--success) 40%, transparent);}
      .final-cta{padding:96px 0;text-align:center;position:relative;overflow:hidden;}
      .final-cta::before{content:'';position:absolute;inset:0;background:radial-gradient(60% 100% at 50% 50%, var(--glow), transparent 65%);pointer-events:none;opacity:0.65;}
      .final-cta .container{position:relative;z-index:1;}
      .final-cta h2{margin-bottom:14px;}
      .final-cta p{max-width:520px;margin:0 auto 32px;color:var(--text-muted);}
    """
    body = """
<section class="hero">
  <span class="orb orb-1" aria-hidden></span>
  <span class="orb orb-2" aria-hidden></span>
  <span class="orb orb-3" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">For solo practitioners + small studios</span>
    <h1 class="reveal reveal-delay-1">One workspace that runs your <span class="gradient-text">whole practice.</span></h1>
    <p class="lead reveal reveal-delay-2">Contacts, invoices, sessions, content, goals, and an AI Chief of Staff that knows your business — replacing eight tools and the friction between them.</p>
    <div class="hero-ctas reveal reveal-delay-3">
      <a class="btn-primary" href="/get-started">Get Started →</a>
      <a class="btn-secondary" href="/features">See what it does</a>
    </div>
    <div class="reveal reveal-delay-3" style="margin-top:18px;">
      <span class="stat-block"><span class="big">8</span><span>tools replaced by one workspace</span></span>
    </div>
    <div class="hero-note reveal reveal-delay-3">Currently in private beta · Apply for access</div>
  </div>
</section>

<section id="features">
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">What it does</span>
      <h2>Six surfaces, one workspace.</h2>
      <p>Each tab is its own command center. They share contacts, content, brand, and your Chief — so nothing falls between the cracks.</p>
    </div>
    <div class="features-grid">
      <div class="card feature-card reveal">
        <div class="mini-visual" aria-hidden><div class="mv-orbit"><span class="center"></span><span class="moon"></span><span class="moon moon-2"></span></div></div>
        <div class="card-icon">🏠</div><h3>Command Center</h3>
        <p>Daily dashboard: today's schedule, what needs attention, recent activity. Voice-first option — wake your Chief by name.</p>
      </div>
      <div class="card feature-card reveal reveal-delay-1">
        <div class="mini-visual" aria-hidden><div class="mv-stack"><span></span><span></span><span></span></div></div>
        <div class="card-icon">🧱</div><h3>Build</h3>
        <p>Practitioner sites, brand kits, intake forms, integrations. Connect Stripe, Facebook Pages, and the tools you already use.</p>
      </div>
      <div class="card feature-card reveal reveal-delay-2">
        <div class="mini-visual" aria-hidden><div class="mv-grid"><span></span><span></span><span></span><span class="live"></span><span></span><span></span><span class="live"></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span class="live"></span></div></div>
        <div class="card-icon">⚙️</div><h3>Operate</h3>
        <p>Contacts, invoices, calendar, tasks, email + SMS hubs. The day-to-day plumbing that keeps clients moving forward.</p>
      </div>
      <div class="card feature-card reveal">
        <div class="mini-visual" aria-hidden><div class="mv-bars"><span></span><span></span><span></span><span></span><span></span></div></div>
        <div class="card-icon">📈</div><h3>Grow</h3>
        <p>Revenue analytics, goals across five lenses, sales funnel, and a content calendar with pillars.</p>
      </div>
      <div class="card feature-card reveal reveal-delay-1">
        <div class="mini-visual" aria-hidden><div class="mv-spark"><span class="core"></span></div></div>
        <div class="card-icon">🤖</div><h3>Chief of Staff</h3>
        <p>An AI that reads your real data every turn. Drafts emails, plans posts, sets goals, sends reports, and gives tactical input on what to push.</p>
      </div>
      <div class="card feature-card reveal reveal-delay-2">
        <div class="mini-visual" aria-hidden><div class="mv-publish"><span class="platform fb">f</span><span class="flow"></span><span class="platform ig">📷</span></div></div>
        <div class="card-icon">📣</div><h3>Publish anywhere</h3>
        <p>Connect your Facebook Page and linked Instagram Business account, then publish from the Content tab in one click.</p>
      </div>
    </div>
    <div style="text-align:center;margin-top:36px;" class="reveal">
      <a class="btn-secondary" href="/features">Explore every feature in depth →</a>
    </div>
  </div>
</section>

<section id="audience" class="audience">
  <div class="container">
    <div class="section-head" style="margin-bottom:32px;">
      <span class="eyebrow">Who it's for</span>
      <h2 style="margin-top:14px;">Built for people who serve people.</h2>
    </div>
    <div class="audience-grid reveal">
      <span class="audience-pill"><span class="emoji">⛪</span> Pastors</span>
      <span class="audience-pill"><span class="emoji">✝️</span> Ministry Leaders</span>
      <span class="audience-pill"><span class="emoji">🎯</span> Coaches</span>
      <span class="audience-pill"><span class="emoji">💼</span> Consultants</span>
      <span class="audience-pill"><span class="emoji">🎨</span> Creatives</span>
      <span class="audience-pill"><span class="emoji">🧘</span> Practitioners</span>
      <span class="audience-pill"><span class="emoji">🏠</span> Solo Studios</span>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">Why Solutionist</span>
      <h2>One workspace replacing the chaos of eight.</h2>
    </div>
    <div class="why-grid">
      <div class="card why-card reveal">
        <div class="check">✓</div>
        <div><h3>One brain, not eight</h3><p style="font-size:14px;color:var(--text-muted);">Your CRM, invoicing, calendar, content, and analytics all talk to each other. Update a contact once; every tool sees it.</p></div>
      </div>
      <div class="card why-card reveal reveal-delay-1">
        <div class="check">✓</div>
        <div><h3>AI that knows your business</h3><p style="font-size:14px;color:var(--text-muted);">Chief reads your real data every turn — not a generic LLM. Asks for context once, then uses it forever.</p></div>
      </div>
      <div class="card why-card reveal">
        <div class="check">✓</div>
        <div><h3>Real-time, not weekly reports</h3><p style="font-size:14px;color:var(--text-muted);">Every metric updates as data changes. No CSV exports, no waiting for someone to refresh.</p></div>
      </div>
      <div class="card why-card reveal reveal-delay-1">
        <div class="check">✓</div>
        <div><h3>Built for solo, not enterprise</h3><p style="font-size:14px;color:var(--text-muted);">No teams, no seat math, no Slack-integration sprawl. Designed for one operator running their whole practice.</p></div>
      </div>
    </div>
  </div>
</section>

<section class="final-cta">
  <div class="container">
    <span class="eyebrow reveal">Ready when you are</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">Run your practice from one place.</h2>
    <p class="reveal reveal-delay-2">Currently in private beta. Apply for access — we'll set you up and walk you through onboarding.</p>
    <a class="btn-primary reveal reveal-delay-3" href="/get-started">Apply for Access →</a>
  </div>
</section>
"""
    return _render_shell(
        title="One workspace that runs your whole practice",
        description="The Solutionist System is one AI-powered workspace that replaces 8+ tools for solo practitioners. Contacts, invoices, sessions, content, goals, and a Chief of Staff that knows your business.",
        content_html=body, path="/", extra_css=extra_css,
    )


# ══════════════════════════════════════════════════════════════════════
# FEATURES — surface-by-surface deep dive
# ══════════════════════════════════════════════════════════════════════

def render_features() -> str:
    extra_css = """
      .feature-section{padding:64px 0;border-bottom:1px solid var(--border);}
      .feature-section:last-of-type{border-bottom:none;}
      .fs-grid{display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:center;}
      @media (max-width: 880px){.fs-grid{grid-template-columns:1fr;gap:32px;}}
      .fs-eyebrow{font-size:11px;font-weight:700;letter-spacing:2.4px;text-transform:uppercase;color:var(--accent);margin-bottom:10px;}
      .fs-visual{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:32px;display:flex;align-items:center;justify-content:center;min-height:280px;position:relative;overflow:hidden;}
      .fs-visual::before{content:'';position:absolute;inset:0;background:radial-gradient(60% 60% at 50% 50%, var(--glow), transparent 70%);opacity:0.35;pointer-events:none;}
      .fs-visual .inner{position:relative;z-index:1;transform:scale(2);}
      .fs-list{list-style:none;padding:0;margin:18px 0 0;display:flex;flex-wrap:wrap;gap:8px;}
      .fs-list li{display:inline-flex;align-items:center;gap:6px;font-size:13px;color:var(--text-secondary);padding:5px 12px;background:var(--surface);border:1px solid var(--border);border-radius:99px;}
      .fs-list li::before{content:'';width:5px;height:5px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));}
    """
    body = """
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">All features</span>
    <h1 class="reveal reveal-delay-1">Every surface, <span class="gradient-text">in depth.</span></h1>
    <p class="lead reveal reveal-delay-2" style="max-width:680px;margin:14px auto 0;">Six tabs in the workspace, plus an AI Chief that touches every one of them. Here's what each does.</p>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="reveal">
        <div class="fs-eyebrow">🏠 Command Center</div>
        <h2>Your daily mission control.</h2>
        <p>The first thing you see when you open the app. Today's schedule, who needs your attention, what shipped overnight, and Chief one tap away.</p>
        <ul class="fs-list">
          <li>Daily dashboard</li><li>Voice-first Chief</li><li>Command palette</li>
          <li>Wake-word listening</li><li>Activity feed</li><li>Smart notifications</li>
        </ul>
      </div>
      <div class="fs-visual reveal reveal-delay-1" aria-hidden>
        <div class="inner"><div class="mv-orbit"><span class="center"></span><span class="moon"></span><span class="moon moon-2"></span></div></div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="fs-visual reveal" aria-hidden>
        <div class="inner"><div class="mv-stack"><span></span><span></span><span></span></div></div>
      </div>
      <div class="reveal reveal-delay-1">
        <div class="fs-eyebrow">🧱 Build</div>
        <h2>Sites, brand, intake — all yours.</h2>
        <p>Spin up a practitioner site, set your brand kit (colors, fonts, logo), capture leads through intake forms, and wire up the integrations you need.</p>
        <ul class="fs-list">
          <li>Practitioner sites</li><li>Brand kits</li><li>Intake forms</li><li>Custom modules</li>
          <li>Print materials</li><li>Booking page</li><li>Link page</li><li>Email templates</li>
          <li>Products &amp; services</li><li>Integrations hub</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="reveal">
        <div class="fs-eyebrow">⚙️ Operate</div>
        <h2>The day-to-day plumbing.</h2>
        <p>Track contacts, send branded invoices, manage your calendar, run tasks, handle email and SMS — all from one screen with one search bar.</p>
        <ul class="fs-list">
          <li>Contacts (CRM)</li><li>Invoices &amp; payments</li><li>Calendar</li><li>Tasks</li>
          <li>Email hub</li><li>SMS hub</li><li>Projects</li><li>Documents</li><li>Autopilot agents</li>
        </ul>
      </div>
      <div class="fs-visual reveal reveal-delay-1" aria-hidden>
        <div class="inner"><div class="mv-grid"><span></span><span></span><span></span><span class="live"></span><span></span><span></span><span class="live"></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span class="live"></span></div></div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="fs-visual reveal" aria-hidden>
        <div class="inner"><div class="mv-bars"><span></span><span></span><span></span><span></span><span></span></div></div>
      </div>
      <div class="reveal reveal-delay-1">
        <div class="fs-eyebrow">📈 Grow</div>
        <h2>Where strategy meets data.</h2>
        <p>Revenue analytics with an allocator, expense tracking, goals across five lenses (Business / Team Building / Personal / Custom), a real sales funnel with drop-off insights, and a full content calendar.</p>
        <ul class="fs-list">
          <li>Revenue analytics</li><li>Revenue Allocator</li><li>Expense tracking</li>
          <li>Goals (5 lenses)</li><li>Goal reminders</li><li>Funnel analytics</li>
          <li>Drop-off insights</li><li>Lost-reason logging</li><li>Content calendar</li>
          <li>Content pillars</li><li>Idea inbox</li><li>Engagement tracking</li>
          <li>Weekly briefing</li><li>Insights feed</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="reveal">
        <div class="fs-eyebrow">🤖 Chief of Staff</div>
        <h2>An AI that knows your business.</h2>
        <p>Not a generic LLM. Chief reads your real contacts, invoices, goals, content, and brand on every turn. Ask for input, delegate actions, get tactical guidance — by chat or by voice.</p>
        <ul class="fs-list">
          <li>Voice mode</li><li>Memory + standing instructions</li>
          <li>Action delegation</li><li>Goal coaching</li><li>Content drafting</li>
          <li>Direct publishing</li><li>Report generation</li><li>Insight + tactical input</li>
        </ul>
      </div>
      <div class="fs-visual reveal reveal-delay-1" aria-hidden>
        <div class="inner"><div class="mv-spark"><span class="core"></span></div></div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="fs-visual reveal" aria-hidden>
        <div class="inner"><div class="mv-publish"><span class="platform fb">f</span><span class="flow"></span><span class="platform ig">📷</span></div></div>
      </div>
      <div class="reveal reveal-delay-1">
        <div class="fs-eyebrow">📣 Publish to Facebook + Instagram</div>
        <h2>One workspace, every channel.</h2>
        <p>Connect your Facebook Page once. Draft posts in the Content tab, publish to your Page (and linked Instagram Business account) in one click. Engagement lives next to your goals.</p>
        <ul class="fs-list">
          <li>Facebook Page publishing</li><li>Instagram Business publishing</li>
          <li>Per-post pillar tagging</li><li>Reminders before posting</li>
          <li>Real engagement tracking</li><li>Server-side token storage</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<section class="final-cta" style="padding:80px 0;">
  <div class="container">
    <span class="eyebrow reveal">Ready to try it?</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">Apply for access today.</h2>
    <p class="reveal reveal-delay-2">Private beta — we'll set you up and walk you through onboarding personally.</p>
    <a class="btn-primary reveal reveal-delay-3" href="/get-started">Apply for Access →</a>
  </div>
</section>
"""
    return _render_shell(
        title="Features",
        description="Every surface in the Solutionist System: Command Center, Build, Operate, Grow, Chief of Staff, and Publish.",
        content_html=body, path="/features", active="features", extra_css=extra_css,
    )


# ══════════════════════════════════════════════════════════════════════
# COMPARE — polished comparison page
# ══════════════════════════════════════════════════════════════════════

def render_compare() -> str:
    extra_css = """
      .cost-grid{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin:28px 0;}
      @media (max-width: 760px){.cost-grid{grid-template-columns:1fr;}}
      .cost-card{padding:28px;border-radius:18px;}
      .cost-card.alt{background:color-mix(in srgb, var(--danger) 5%, transparent);border:1px solid color-mix(in srgb, var(--danger) 25%, transparent);}
      .cost-card.sol{background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 14%, transparent), color-mix(in srgb, var(--info) 10%, transparent));border:1px solid color-mix(in srgb, var(--accent) 40%, transparent);box-shadow:0 8px 36px var(--glow);}
      .cost-title{font-family:var(--font-heading);font-size:14px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:1.6px;margin-bottom:14px;}
      .cost-card.alt .cost-title{color:var(--danger);}
      .cost-card.sol .cost-title{color:var(--accent);}
      .cost-stack{list-style:none;padding:0;margin:0 0 18px 0;display:flex;flex-direction:column;gap:6px;font-size:13px;}
      .cost-stack li{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px dashed var(--border);color:var(--text-secondary);}
      .cost-stack li span:last-child{font-variant-numeric:tabular-nums;font-weight:600;color:var(--text-primary);}
      .cost-total{display:flex;justify-content:space-between;align-items:baseline;padding-top:10px;border-top:1px solid var(--border);font-family:var(--font-heading);}
      .cost-total .label{font-size:13px;color:var(--text-muted);font-family:var(--font-body);}
      .cost-total .price{font-size:32px;font-weight:700;letter-spacing:-0.02em;}
      .cost-card.alt .cost-total .price{color:var(--danger);}
      .cost-card.sol .cost-total .price{background:linear-gradient(135deg, var(--accent), var(--info));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
      .compare{width:100%;border-collapse:separate;border-spacing:0;background:var(--surface);border:1px solid var(--border);border-radius:16px;overflow:hidden;}
      .compare th,.compare td{padding:14px 18px;text-align:left;font-size:14px;}
      .compare thead{background:color-mix(in srgb, var(--accent) 8%, transparent);}
      .compare thead th{font-family:var(--font-heading);font-weight:600;color:var(--text-primary);font-size:13px;border-bottom:1px solid var(--border);}
      .compare thead th.sol-col{color:var(--accent);}
      .compare tbody td{border-top:1px solid var(--border);color:var(--text-secondary);}
      .compare tbody td:first-child{font-weight:600;color:var(--text-primary);}
      .compare td.sol{color:var(--success);}
      .compare td.alt{color:var(--text-muted);font-style:italic;}
      @media (max-width: 720px){.compare th,.compare td{padding:10px 12px;font-size:12.5px;}}
      .switch-grid{display:grid;grid-template-columns:repeat(3, 1fr);gap:18px;margin-top:14px;}
      @media (max-width: 860px){.switch-grid{grid-template-columns:1fr;}}
      .switch-card{padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:14px;}
      .switch-card h3{font-family:var(--font-heading);color:var(--text-primary);font-size:16px;margin-bottom:10px;}
      .switch-card p{font-size:14px;color:var(--text-muted);line-height:1.6;}
    """
    body = """
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">Solutionist vs. alternatives</span>
    <h1 class="reveal reveal-delay-1">One workspace vs. <span class="gradient-text">cobbling 8 tools.</span></h1>
    <p class="lead reveal reveal-delay-2" style="max-width:680px;margin:14px auto 0;">What you'd normally pay $200+/month for and lose to context-switching every day.</p>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">Real cost breakdown</span>
      <h2>The math on the 8-tool stack.</h2>
      <p>Conservative pricing — most operators end up paying more once they hit usage tiers.</p>
    </div>
    <div class="cost-grid">
      <div class="cost-card alt reveal">
        <div class="cost-title">The 8-tool stack (per month)</div>
        <ul class="cost-stack">
          <li><span>HubSpot Starter (CRM)</span><span>$20</span></li>
          <li><span>Stripe (no monthly, fees on volume)</span><span>$0+</span></li>
          <li><span>Calendly (booking)</span><span>$12</span></li>
          <li><span>Buffer Essentials (content)</span><span>$15</span></li>
          <li><span>Notion Plus (notes/goals)</span><span>$10</span></li>
          <li><span>Mixpanel / Looker Studio (analytics)</span><span>$25+</span></li>
          <li><span>Squarespace Business (website)</span><span>$23</span></li>
          <li><span>ChatGPT Plus (AI assistant)</span><span>$20</span></li>
        </ul>
        <div class="cost-total"><span class="label">≈ Total</span><span class="price">$125+ /mo</span></div>
        <p style="margin-top:14px;font-size:12px;color:var(--text-dim);">Plus the time + headache of stitching them together. Each tool wants its own login, notification settings, billing cycle, and integrations that mostly don't work.</p>
      </div>
      <div class="cost-card sol reveal reveal-delay-1">
        <div class="cost-title">Solutionist System</div>
        <ul class="cost-stack">
          <li><span>CRM + Contacts</span><span>✓</span></li>
          <li><span>Invoicing &amp; payments</span><span>✓</span></li>
          <li><span>Calendar + booking</span><span>✓</span></li>
          <li><span>Content planning &amp; publishing</span><span>✓</span></li>
          <li><span>Goals + tracking</span><span>✓</span></li>
          <li><span>Funnel + revenue analytics</span><span>✓</span></li>
          <li><span>Practitioner site + brand kit</span><span>✓</span></li>
          <li><span>Chief of Staff (AI)</span><span>✓</span></li>
        </ul>
        <div class="cost-total"><span class="label">Pricing TBD</span><span class="price">Private beta</span></div>
        <p style="margin-top:14px;font-size:12px;color:var(--text-dim);">We're growing carefully. Apply for access — early users get grandfathered pricing once we launch publicly.</p>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">Feature by feature</span>
      <h2>The side-by-side.</h2>
    </div>
    <div class="reveal reveal-delay-1">
      <table class="compare">
        <thead>
          <tr><th>What you need</th><th class="sol-col">Solutionist</th><th>The 8-tool stack</th></tr>
        </thead>
        <tbody>
          <tr><td>CRM &amp; contacts</td><td class="sol">✓ Built-in</td><td class="alt">HubSpot / Notion / spreadsheet</td></tr>
          <tr><td>Invoicing &amp; payments</td><td class="sol">✓ Built-in</td><td class="alt">Stripe + QuickBooks</td></tr>
          <tr><td>Calendar &amp; booking</td><td class="sol">✓ Built-in</td><td class="alt">Calendly + Google Calendar</td></tr>
          <tr><td>Content planning &amp; publishing</td><td class="sol">✓ Built-in</td><td class="alt">Buffer / Hootsuite + Notion</td></tr>
          <tr><td>Goals &amp; tracking</td><td class="sol">✓ Built-in</td><td class="alt">Spreadsheet + sticky notes</td></tr>
          <tr><td>Funnel &amp; pipeline analytics</td><td class="sol">✓ Built-in</td><td class="alt">Mixpanel / Looker / DIY</td></tr>
          <tr><td>Website &amp; brand</td><td class="sol">✓ Built-in</td><td class="alt">Squarespace / Webflow + Figma</td></tr>
          <tr><td>AI assistant that knows your business</td><td class="sol">✓ Chief of Staff</td><td class="alt">ChatGPT + manual context every time</td></tr>
          <tr><td>One login</td><td class="sol">✓</td><td class="alt">8+ logins</td></tr>
          <tr><td>Real-time data flow</td><td class="sol">✓ Native</td><td class="alt">Zapier / manual sync</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">Switching from?</span>
      <h2>If you're coming from these, here's what's different.</h2>
    </div>
    <div class="switch-grid">
      <div class="switch-card reveal">
        <h3>From Notion</h3>
        <p>Notion is a blank canvas — flexible but you build everything yourself, and there's no AI that reads your business data. Solutionist comes opinionated: contacts work like contacts, invoices work like invoices, goals work like goals. You skip the database-design stage.</p>
      </div>
      <div class="switch-card reveal reveal-delay-1">
        <h3>From HubSpot</h3>
        <p>HubSpot is enterprise CRM at scale — sales-team assumptions, deal pipelines built for B2B reps, and pricing that doesn't fit a solo practice. Solutionist is purpose-built for one operator running their whole business, not a sales team managing leads.</p>
      </div>
      <div class="switch-card reveal reveal-delay-2">
        <h3>From "I'll just use ChatGPT"</h3>
        <p>ChatGPT is brilliant but generic — every conversation starts cold. Chief reads your real contacts, invoices, goals, content, and brand on every turn. Ask "how am I doing on my goals?" and you get a real answer, not a checklist of what to consider.</p>
      </div>
    </div>
  </div>
</section>

<section class="final-cta" style="padding:80px 0;">
  <div class="container">
    <span class="eyebrow reveal">Stop stitching tools.</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">One workspace, one login, one Chief.</h2>
    <a class="btn-primary reveal reveal-delay-3" href="/get-started" style="margin-top:14px;">Apply for Access →</a>
  </div>
</section>
"""
    return _render_shell(
        title="Compare",
        description="The Solutionist System vs. cobbling 8 tools together. Real cost breakdown, feature-by-feature comparison, and switching guides.",
        content_html=body, path="/compare", active="compare", extra_css=extra_css,
    )


# ══════════════════════════════════════════════════════════════════════
# FAQ
# ══════════════════════════════════════════════════════════════════════

def render_faq() -> str:
    extra_css = """
      .faq-list{display:flex;flex-direction:column;gap:10px;max-width:780px;margin:0 auto;}
      .faq-item{background:var(--surface);border:1px solid var(--border);border-radius:12px;overflow:hidden;transition:border-color 0.18s;}
      .faq-item[open]{border-color:color-mix(in srgb, var(--accent) 45%, transparent);}
      .faq-item summary{padding:18px 22px;cursor:pointer;font-family:var(--font-heading);font-weight:600;font-size:15px;color:var(--text-primary);list-style:none;display:flex;align-items:center;justify-content:space-between;gap:12px;}
      .faq-item summary::-webkit-details-marker{display:none;}
      .faq-item summary::after{content:'+';font-family:var(--font-body);font-weight:400;font-size:22px;color:var(--accent);transition:transform 0.18s;line-height:1;}
      .faq-item[open] summary::after{transform:rotate(45deg);}
      .faq-body{padding:0 22px 20px;font-size:14.5px;color:var(--text-secondary);line-height:1.65;}
      .faq-body p{margin-bottom:10px;}
      .faq-body p:last-child{margin-bottom:0;}
    """
    body = """
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">Common questions</span>
    <h1 class="reveal reveal-delay-1">Answers to <span class="gradient-text">what people ask first.</span></h1>
    <p class="lead reveal reveal-delay-2" style="max-width:600px;margin:14px auto 0;">Don't see your question? Email us at <a href="mailto:kmjcreativesolution@gmail.com" style="color:var(--accent);">kmjcreativesolution@gmail.com</a>.</p>
  </div>
</section>

<section>
  <div class="container-narrow">
    <div class="faq-list reveal">
      <details class="faq-item">
        <summary>Who is this actually for?</summary>
        <div class="faq-body"><p>Solo practitioners and small studios. The people we built it for: pastors, ministry leaders, coaches, consultants, creatives, agencies-of-one, and small service businesses. If you run your whole show — sales, delivery, marketing, finances — Solutionist is for you. If you have a 20-person team with a dedicated ops person, it's overkill.</p></div>
      </details>
      <details class="faq-item">
        <summary>Do I need a team to use this?</summary>
        <div class="faq-body"><p>No. The whole product assumes one operator. No seat math, no "add a teammate" friction, no admin role management. If you grow to a team later, the data model supports it — but it's not the default.</p></div>
      </details>
      <details class="faq-item">
        <summary>What about pricing?</summary>
        <div class="faq-body"><p>We're in private beta right now. Pricing is coming when we open public access. Apply for access — if you're a fit, we'll get you in early and grandfather you on whatever pricing launches.</p></div>
      </details>
      <details class="faq-item">
        <summary>How is this different from Notion, HubSpot, or just using ChatGPT?</summary>
        <div class="faq-body">
          <p><strong>Notion</strong> is a blank canvas — you'd build all this yourself, and it doesn't have an AI that knows your actual business data.</p>
          <p><strong>HubSpot</strong> is enterprise CRM with a steep learning curve, sales-team assumptions, and pricing that doesn't fit a solo practice.</p>
          <p><strong>ChatGPT</strong> is generic — you have to re-explain your business every time. Chief reads your real contacts, invoices, goals, content, and brand on every turn.</p>
          <p>Solutionist is purpose-built for solo operators with AI woven through every surface.</p>
          <p>See the full <a href="/compare" style="color:var(--accent);">comparison page</a> for the side-by-side.</p>
        </div>
      </details>
      <details class="faq-item">
        <summary>Does the AI replace my judgment?</summary>
        <div class="faq-body"><p>No. Chief drafts, suggests, and assists — it never sends without you approving (except for explicit actions you ask it to take, like "send this email" or "publish this post"). It's an instrument, not a replacement.</p></div>
      </details>
      <details class="faq-item">
        <summary>What about my existing tools — do I have to move everything?</summary>
        <div class="faq-body"><p>No. Connect what you want (Stripe for payments, Facebook for publishing, Resend for email). The rest stays. Solutionist is opinionated about workflow but not greedy — you can keep Calendly or your existing email tool and Solutionist will work around it.</p></div>
      </details>
      <details class="faq-item">
        <summary>How secure is my data?</summary>
        <div class="faq-body"><p>Connected social account tokens and other credentials are stored server-side only — your browser never sees them. We use Supabase for data storage and Railway for hosting. You can disconnect any integration immediately from the app, which deletes the stored token. Full details in the <a href="/privacy" style="color:var(--accent);">Privacy Policy</a>.</p></div>
      </details>
      <details class="faq-item">
        <summary>Does it work for churches and ministries?</summary>
        <div class="faq-body"><p>It works for the <em>person</em> running a church or ministry — pastors, ministry leaders, faith-based coaches. The product is single-operator: one person, one workspace. If you need multi-staff role management or church membership tools, we're not the right fit yet (those are on the roadmap).</p></div>
      </details>
      <details class="faq-item">
        <summary>Can the AI publish to my social accounts?</summary>
        <div class="faq-body"><p>Yes — once you connect your Facebook Page (and linked Instagram Business account). Chief can draft, schedule, and publish directly. You approve each post; nothing goes out without your action. Connect from <strong>Build → Integrations → Social Publishing</strong>.</p></div>
      </details>
      <details class="faq-item">
        <summary>When can I sign up?</summary>
        <div class="faq-body"><p>Now — <a href="/get-started" style="color:var(--accent);">apply for access</a> with a few sentences about your practice. If we're a fit, we'll onboard you within a few days.</p></div>
      </details>
    </div>
    <div style="text-align:center;margin-top:48px;" class="reveal reveal-delay-2">
      <a class="btn-primary" href="/get-started">Apply for Access →</a>
    </div>
  </div>
</section>
"""
    return _render_shell(
        title="FAQ",
        description="Answers to common questions about the Solutionist System: who it's for, pricing, how it compares to other tools, security, and signup.",
        content_html=body, path="/faq", active="faq", extra_css=extra_css,
    )


# ══════════════════════════════════════════════════════════════════════
# ABOUT
# ══════════════════════════════════════════════════════════════════════

def render_about() -> str:
    extra_css = """
      .founder{position:relative;padding:36px;background:var(--surface);border:1px solid var(--border);border-radius:18px;display:grid;grid-template-columns:80px 1fr;gap:24px;align-items:flex-start;}
      @media (max-width: 640px){.founder{grid-template-columns:1fr;padding:28px;}}
      .founder-avatar{width:80px;height:80px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg, var(--accent), var(--info));color:var(--text-primary);font-family:var(--font-heading);font-weight:600;font-size:28px;box-shadow:0 4px 26px var(--glow);}
      .founder-body p{font-size:15.5px;line-height:1.7;color:var(--text-secondary);margin-bottom:14px;}
      .founder-body p:last-of-type{margin-bottom:0;}
      .founder-sig{margin-top:16px;font-family:var(--font-heading);font-weight:600;color:var(--text-primary);font-size:15px;}
      .founder-sig .small{display:block;font-family:var(--font-body);font-weight:400;font-size:12px;color:var(--text-dim);margin-top:2px;}
      .principles{display:grid;grid-template-columns:repeat(3, 1fr);gap:18px;margin-top:14px;}
      @media (max-width: 860px){.principles{grid-template-columns:1fr;}}
      .principle{padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:14px;}
      .principle .num{font-family:var(--font-heading);font-size:11px;font-weight:700;color:var(--accent);letter-spacing:1.4px;text-transform:uppercase;margin-bottom:10px;}
      .principle h3{font-family:var(--font-heading);font-size:16px;color:var(--text-primary);margin-bottom:8px;}
      .principle p{font-size:14px;color:var(--text-muted);line-height:1.6;}
      .company-row{display:grid;grid-template-columns:repeat(2, 1fr);gap:18px;margin-top:14px;}
      @media (max-width: 720px){.company-row{grid-template-columns:1fr;}}
      .company-card{padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:14px;}
      .company-card h3{font-family:var(--font-heading);font-size:14px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1.4px;margin-bottom:10px;}
      .company-card p{font-size:14px;color:var(--text-secondary);}
    """
    body = """
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">About</span>
    <h1 class="reveal reveal-delay-1">Built by a solo operator, <span class="gradient-text">for solo operators.</span></h1>
    <p class="lead reveal reveal-delay-2" style="max-width:680px;margin:14px auto 0;">A small Michigan LLC building software for the people who actually do the work.</p>
  </div>
</section>

<section>
  <div class="container-narrow">
    <div class="section-head reveal" style="margin-bottom:32px;text-align:left;">
      <span class="eyebrow">From the founder</span>
    </div>
    <div class="founder reveal reveal-delay-1">
      <div class="founder-avatar">KM</div>
      <div class="founder-body">
        <p>I built the Solutionist System because I was tired of running my own business across eight tools that didn't talk to each other.</p>
        <p>Every solo operator I know lives in the same chaos: Notion for notes, Stripe for invoices, Calendly for booking, Buffer for content, a spreadsheet for goals, a CRM nobody actually uses. The friction between tools eats more time than the actual work.</p>
        <p>So we built one workspace where everything lives together — with an AI Chief of Staff that actually knows your business, not generic prompts. We're growing it carefully in private beta. If you're a coach, pastor, ministry leader, consultant, or solo studio, I'd love to talk.</p>
        <div class="founder-sig">
          Kevin McCloud Jr.
          <span class="small">Founder &middot; KMJ Creative Solutions LLC</span>
        </div>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">How we build</span>
      <h2>Three principles we won't break.</h2>
    </div>
    <div class="principles">
      <div class="principle reveal">
        <div class="num">01</div>
        <h3>Real data, never invented metrics.</h3>
        <p>Every number in the workspace comes from your actual data. We never fake counts, never invent "engagement scores" without a source. If we don't have the data to back a metric, the metric doesn't ship.</p>
      </div>
      <div class="principle reveal reveal-delay-1">
        <div class="num">02</div>
        <h3>AI in service of judgment, not instead of it.</h3>
        <p>Chief drafts, suggests, and assists. You approve. Actions are explicit. No autonomous decisions on your behalf without your sign-off — your business stays your business.</p>
      </div>
      <div class="principle reveal reveal-delay-2">
        <div class="num">03</div>
        <h3>Single operator, single workspace.</h3>
        <p>We're not building enterprise SaaS. Every design decision optimizes for one person running their whole practice. If a feature only makes sense for a 20-person team, we don't build it.</p>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="container-narrow">
    <div class="section-head reveal" style="text-align:left;">
      <span class="eyebrow">The company</span>
      <h2>KMJ Creative Solutions LLC.</h2>
    </div>
    <div class="company-row">
      <div class="company-card reveal">
        <h3>Founded</h3>
        <p>2025 in Michigan, USA. A real LLC, real legal entity, registered with the state.</p>
      </div>
      <div class="company-card reveal reveal-delay-1">
        <h3>What we ship</h3>
        <p>The Solutionist System — one product, no spinouts, no pivots. Built to last for the people who use it.</p>
      </div>
      <div class="company-card reveal">
        <h3>Stack</h3>
        <p>React + TypeScript + Vite (Tauri desktop), Python + FastAPI on Railway, Supabase for data, Resend for email, Anthropic for AI.</p>
      </div>
      <div class="company-card reveal reveal-delay-1">
        <h3>Contact</h3>
        <p><a href="mailto:kmjcreativesolution@gmail.com" style="color:var(--accent);">kmjcreativesolution@gmail.com</a> — replies usually within a day.</p>
      </div>
    </div>
  </div>
</section>

<section class="final-cta" style="padding:80px 0;">
  <div class="container">
    <span class="eyebrow reveal">Want to talk?</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">Apply for access — or just say hi.</h2>
    <a class="btn-primary reveal reveal-delay-3" href="/get-started" style="margin-top:14px;">Apply for Access →</a>
  </div>
</section>
"""
    return _render_shell(
        title="About",
        description="Built by Kevin McCloud Jr. at KMJ Creative Solutions LLC. A Michigan-based company building one workspace for solo practitioners.",
        content_html=body, path="/about", active="about", extra_css=extra_css,
    )


# ══════════════════════════════════════════════════════════════════════
# GET STARTED — intake form (form POSTs to /api/leads via fetch)
# ══════════════════════════════════════════════════════════════════════

def render_get_started() -> str:
    extra_css = """
      .gs-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:48px;margin-top:20px;align-items:flex-start;}
      @media (max-width: 880px){.gs-grid{grid-template-columns:1fr;gap:28px;}}
      .form-card{background:var(--surface);border:1px solid var(--border);border-radius:18px;padding:32px;}
      .form-row{display:flex;flex-direction:column;gap:6px;margin-bottom:18px;}
      .form-row label{font-size:11px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--text-muted);}
      .form-row label .req{color:var(--accent);}
      .form-row input,.form-row select,.form-row textarea{padding:11px 14px;font-family:var(--font-body);font-size:14px;color:var(--text-primary);background:var(--bg);border:1px solid var(--border);border-radius:8px;outline:none;transition:border-color 0.15s, background 0.15s;}
      .form-row input:focus,.form-row select:focus,.form-row textarea:focus{border-color:color-mix(in srgb, var(--accent) 60%, transparent);background:var(--bg-2);}
      .form-row textarea{resize:vertical;min-height:96px;line-height:1.55;}
      .honeypot{position:absolute;left:-9999px;width:1px;height:1px;opacity:0;}
      .form-submit{width:100%;}
      .form-msg{margin-top:14px;padding:12px 14px;border-radius:8px;font-size:13px;line-height:1.5;display:none;}
      .form-msg.ok{display:block;background:color-mix(in srgb, var(--success) 12%, transparent);border:1px solid color-mix(in srgb, var(--success) 35%, transparent);color:var(--success);}
      .form-msg.err{display:block;background:color-mix(in srgb, var(--danger) 12%, transparent);border:1px solid color-mix(in srgb, var(--danger) 35%, transparent);color:var(--danger);}
      .next-steps{padding:28px;background:var(--surface);border:1px solid var(--border);border-radius:16px;}
      .next-steps h3{font-family:var(--font-heading);font-size:14px;color:var(--text-muted);text-transform:uppercase;letter-spacing:1.4px;margin-bottom:14px;}
      .next-list{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:14px;}
      .next-list li{display:grid;grid-template-columns:28px 1fr;gap:10px;align-items:flex-start;}
      .next-list .num{display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));color:var(--text-primary);font-family:var(--font-heading);font-weight:700;font-size:12px;}
      .next-list .text{font-size:13.5px;color:var(--text-secondary);line-height:1.55;}
      .next-list .text strong{color:var(--text-primary);}
    """
    extra_scripts = """
<script>
  (function() {
    var form = document.getElementById('lead-form');
    var msg  = document.getElementById('form-msg');
    var btn  = document.getElementById('submit-btn');
    if (!form) return;
    form.addEventListener('submit', async function(e) {
      e.preventDefault();
      msg.className = 'form-msg';
      msg.textContent = '';
      btn.disabled = true;
      btn.textContent = 'Sending…';
      var data = {
        name:        form.name.value.trim(),
        email:       form.email.value.trim(),
        role:        form.role.value,
        what_you_do: form.what_you_do.value.trim(),
        source:      form.source.value.trim(),
        honeypot:    form.website.value  // honeypot field
      };
      try {
        var res = await fetch('/api/leads', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        });
        if (!res.ok) {
          var t = await res.text();
          throw new Error(t || ('Server ' + res.status));
        }
        msg.classList.add('ok');
        msg.textContent = "Got it. We'll be in touch within 24 hours — check your inbox for a quick confirmation.";
        form.reset();
        btn.textContent = 'Sent ✓';
      } catch (err) {
        msg.classList.add('err');
        msg.textContent = 'Something went wrong — please email kmjcreativesolution@gmail.com directly.';
        btn.disabled = false;
        btn.textContent = 'Apply for Access →';
      }
    });
  })();
</script>
"""
    body = """
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">Private beta · Apply for access</span>
    <h1 class="reveal reveal-delay-1">Tell us about your <span class="gradient-text">practice.</span></h1>
    <p class="lead reveal reveal-delay-2" style="max-width:600px;margin:14px auto 0;">We onboard each new user personally. Takes about 60 seconds to apply.</p>
  </div>
</section>

<section>
  <div class="container">
    <div class="gs-grid">
      <form id="lead-form" class="form-card reveal">
        <div class="form-row">
          <label>Your name <span class="req">*</span></label>
          <input type="text" name="name" required autocomplete="name" placeholder="Jane Doe">
        </div>
        <div class="form-row">
          <label>Email <span class="req">*</span></label>
          <input type="email" name="email" required autocomplete="email" placeholder="you@yourdomain.com">
        </div>
        <div class="form-row">
          <label>What do you do?</label>
          <select name="role">
            <option value="">— pick what fits best —</option>
            <option value="pastor">Pastor</option>
            <option value="ministry_leader">Ministry Leader</option>
            <option value="coach">Coach</option>
            <option value="consultant">Consultant</option>
            <option value="creative">Creative</option>
            <option value="practitioner">Practitioner</option>
            <option value="solo_studio">Solo Studio</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div class="form-row">
          <label>Tell us a bit about your practice <span class="req">*</span></label>
          <textarea name="what_you_do" required placeholder="Who do you serve? What's the work look like? What's your biggest tooling headache today?"></textarea>
        </div>
        <div class="form-row">
          <label>How did you hear about us?</label>
          <input type="text" name="source" autocomplete="off" placeholder="Optional — Twitter, friend referral, search, etc.">
        </div>
        <div class="honeypot" aria-hidden>
          <label>Website</label>
          <input type="text" name="website" tabindex="-1" autocomplete="off">
        </div>
        <button type="submit" id="submit-btn" class="btn-primary form-submit">Apply for Access →</button>
        <div id="form-msg" class="form-msg" role="status" aria-live="polite"></div>
      </form>

      <aside class="next-steps reveal reveal-delay-1">
        <h3>What happens next</h3>
        <ul class="next-list">
          <li>
            <span class="num">1</span>
            <span class="text"><strong>Quick confirmation email</strong> — you'll get a "we got it" email within a minute of submitting.</span>
          </li>
          <li>
            <span class="num">2</span>
            <span class="text"><strong>Kevin reaches out within 24 hours</strong> — usually faster. He'll ask a few questions to make sure Solutionist is a fit for your practice.</span>
          </li>
          <li>
            <span class="num">3</span>
            <span class="text"><strong>Personal onboarding</strong> — if it's a fit, we set up your account and walk you through it together (~30 min).</span>
          </li>
          <li>
            <span class="num">4</span>
            <span class="text"><strong>You start running your practice from one place</strong> — and grandfather in on whatever pricing we launch publicly.</span>
          </li>
        </ul>
      </aside>
    </div>
  </div>
</section>
"""
    return _render_shell(
        title="Get Started",
        description="Apply for private beta access to the Solutionist System. We onboard each new user personally.",
        content_html=body, path="/get-started", active="get_started",
        extra_css=extra_css, extra_scripts=extra_scripts,
    )


# ══════════════════════════════════════════════════════════════════════
# LEAD INTAKE — POST /api/leads handler
# ══════════════════════════════════════════════════════════════════════

class LeadIntakeRequest(BaseModel):
    name: str
    email: str
    role: Optional[str] = None
    what_you_do: Optional[str] = None
    source: Optional[str] = None
    honeypot: Optional[str] = None   # bots fill this; humans don't


async def handle_lead_intake(req: LeadIntakeRequest) -> Dict[str, Any]:
    """Validate + persist + notify. Honeypot returns success silently
    so bots don't learn they were rejected."""
    name = (req.name or "").strip()
    email = (req.email or "").strip().lower()

    # Honeypot → silent success
    if req.honeypot and req.honeypot.strip():
        logger.info(f"honeypot triggered from {email or '(no email)'} — silently dropping")
        return {"ok": True}

    if not name:
        raise HTTPException(400, "name is required")
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "valid email is required")
    if len(name) > 200 or len(email) > 200:
        raise HTTPException(400, "name/email too long")

    role = (req.role or "").strip().lower() or None
    what_you_do = (req.what_you_do or "").strip() or None
    source = (req.source or "").strip() or None
    if what_you_do and len(what_you_do) > 4000:
        what_you_do = what_you_do[:4000]

    # 1. Insert into Supabase
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_ANON", "")
    inserted_id = None
    if supabase_url and supabase_key:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            try:
                r = await client.post(
                    f"{supabase_url}/rest/v1/marketing_leads",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=representation",
                    },
                    content=json.dumps({
                        "name": name, "email": email, "role": role,
                        "what_you_do": what_you_do, "source": source,
                        "status": "new",
                    }),
                )
                if r.status_code < 400:
                    data = r.json() if r.text else []
                    if isinstance(data, list) and data:
                        inserted_id = data[0].get("id")
                else:
                    logger.warning(f"supabase insert failed {r.status_code}: {r.text[:300]}")
            except Exception as e:
                logger.warning(f"supabase insert error: {e}")
    else:
        logger.warning("SUPABASE_URL/ANON not configured — skipping persist")

    # 2. Send emails via Resend — owner notification + lead confirmation
    try:
        from email_sender import send_via_resend
        from_email = os.environ.get("RESEND_FROM_EMAIL") or "noreply@mysolutionist.app"

        # Owner notification
        owner_subject = f"New lead: {name} ({role or 'no role'})"
        owner_body = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;color:#222;padding:20px;max-width:600px;margin:0 auto;background:#fff;">
<h2 style="color:#7c3aed;margin-bottom:18px;">New beta application</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px;">
<tr><td style="padding:8px 0;color:#666;width:140px;">Name</td><td style="padding:8px 0;font-weight:600;">{_html.escape(name)}</td></tr>
<tr><td style="padding:8px 0;color:#666;">Email</td><td style="padding:8px 0;font-weight:600;"><a href="mailto:{_html.escape(email)}">{_html.escape(email)}</a></td></tr>
<tr><td style="padding:8px 0;color:#666;">Role</td><td style="padding:8px 0;">{_html.escape(role or '(not specified)')}</td></tr>
<tr><td style="padding:8px 0;color:#666;">Source</td><td style="padding:8px 0;">{_html.escape(source or '(not specified)')}</td></tr>
</table>
<div style="margin-top:18px;padding:14px;background:#f5f5f7;border-radius:8px;font-size:13px;line-height:1.6;">
<strong style="display:block;margin-bottom:6px;color:#444;">About their practice:</strong>
{_html.escape(what_you_do or '(empty)').replace(chr(10), '<br>')}
</div>
<p style="margin-top:18px;font-size:11px;color:#999;">Lead ID: {inserted_id or '(persist failed)'}</p>
</body></html>"""
        try:
            await send_via_resend(
                to_email=CONTACT_EMAIL, to_name=None,
                from_email=from_email, from_name="Solutionist Site",
                subject=owner_subject, body=owner_body, reply_to=email,
            )
        except Exception as e:
            logger.warning(f"owner email failed: {e}")

        # Lead confirmation
        lead_subject = "Got your application — welcome to Solutionist"
        lead_body = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;color:#222;padding:20px;max-width:600px;margin:0 auto;background:#fff;line-height:1.65;">
<h2 style="color:#7c3aed;margin-bottom:14px;">Thanks for applying, {_html.escape(name.split()[0])}.</h2>
<p style="font-size:15px;color:#333;">We got your application for the Solutionist System private beta. Here's what happens next:</p>
<ol style="font-size:14px;color:#444;padding-left:20px;margin:18px 0;">
<li style="margin-bottom:8px;"><strong>Kevin will reach out within 24 hours</strong> — usually faster. He'll ask a few questions to make sure we're a fit for what you're building.</li>
<li style="margin-bottom:8px;"><strong>If it's a fit, we'll set up personal onboarding</strong> — about 30 minutes, we walk you through the workspace and get you running.</li>
<li><strong>You'll get grandfathered pricing</strong> when we launch publicly.</li>
</ol>
<p style="font-size:14px;color:#666;margin-top:18px;">Questions before then? Just reply to this email — it goes straight to Kevin.</p>
<p style="margin-top:24px;font-size:14px;color:#444;">Talk soon,<br><strong>Kevin McCloud Jr.</strong><br>Founder, KMJ Creative Solutions LLC</p>
</body></html>"""
        try:
            await send_via_resend(
                to_email=email, to_name=name,
                from_email=from_email, from_name="Kevin at Solutionist",
                subject=lead_subject, body=lead_body, reply_to=CONTACT_EMAIL,
            )
        except Exception as e:
            logger.warning(f"lead confirmation email failed: {e}")
    except Exception as e:
        logger.warning(f"resend import/send failed: {e}")

    logger.info(f"new lead persisted id={inserted_id} from {email}")
    return {"ok": True, "id": inserted_id}
