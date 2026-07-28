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
BUSINESS_NAME = "The Solutionist System LLC"
SITE_NAME = "The Solutionist System"
SITE_DOMAIN = "mysolutionist.app"
# Arc 18 — the web app's home (Vite app on Vercel; marketing stays here).
APP_URL = "https://system.mysolutionist.app"
DESKTOP_RELEASES_URL = ""  # set to the GitHub Releases URL once installers publish
# Arc 25 — Android distribution. Env-driven so the links go live from
# Railway the moment the first signed APK is uploaded (GitHub Releases),
# no code deploy needed. PLAY_STORE_URL stays empty until the listing
# is approved (docs/play_store_submission.md in the frontend repo).
ANDROID_APK_URL = os.environ.get("ANDROID_APK_URL", "").strip()
PLAY_STORE_URL = os.environ.get("PLAY_STORE_URL", "").strip()

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
    /* ── Blue-led. Same violet/cyan family the site has always used,
       re-weighted so electric blue carries the brand and violet drops to
       a rare accent. Flat solid colour, no gradient text.

       NOTE --amber: that is the product's own action colour (Quick
       Create, New Invoice, Chase Overdue, Chief AI). It is used ONLY
       inside the product replicas so they read as genuine screenshots —
       never on site chrome. ── */
    --bg: #08090C;
    --bg-2: #0E1015;
    --bg-3: #141821;
    --surface: rgba(255,255,255,0.035);
    --surface-2: rgba(255,255,255,0.065);
    --border: rgba(255,255,255,0.09);
    --border-strong: rgba(255,255,255,0.17);
    --text-primary: #F7F8FA;
    --text-secondary: #C9CDD6;
    --text-muted: #949AA6;
    --text-dim: #6B707B;
    --accent: #2E7DFF;
    --accent-2: #1D63E6;
    --info: #22D3EE;
    --violet: #7C3AED;
    --amber: #C9A84C;
    --success: #22C55E;
    --warning: #F5C542;
    --danger: #EF4444;
    --hot: #F97316;
    --ink-on-accent: #FFFFFF;
    --glow: rgba(46,125,255,0.30);
    --glow-2: rgba(34,211,238,0.20);
    --glow-cyan: rgba(34,211,238,0.20);
    --glow-ember: rgba(46,125,255,0.18);
    --font-heading: 'Inter Tight', 'Inter', system-ui, sans-serif;
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
  .gradient-text{color:var(--accent);-webkit-text-fill-color:currentColor;background:none;}
  h1,h2,h3{font-family:var(--font-heading);letter-spacing:-0.032em;line-height:1.04;}
  h1{font-size:clamp(42px, 6.2vw, 68px);font-weight:700;}
  h2{font-size:clamp(30px, 4.2vw, 46px);font-weight:700;letter-spacing:-0.03em;margin-bottom:14px;}
  h3{font-size:18px;font-weight:600;color:var(--text-primary);margin-bottom:6px;}
  p{color:var(--text-secondary);font-size:16px;}
  .lead{font-size:18px;color:var(--text-muted);line-height:1.65;}

  /* ─── nav ─── */
  .nav{position:sticky;top:0;z-index:50;background:rgba(8,9,12,0.82);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border-bottom:1px solid var(--border);}
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
  .nav-cta{padding:8px 16px;background:var(--accent);color:var(--ink-on-accent) !important;border-radius:8px;font-weight:700;font-size:13px;box-shadow:0 2px 14px color-mix(in srgb, var(--accent) 30%, transparent);transition:transform 0.15s, box-shadow 0.15s, background 0.15s;}
  .nav-cta:hover{transform:translateY(-1px);background:var(--accent-2);box-shadow:0 4px 20px color-mix(in srgb, var(--accent) 45%, transparent);}
  .nav-cta.is-active::after{display:none;}
  .nav-login{padding:7px 15px;border:1px solid var(--border-strong);border-radius:8px;color:var(--text-primary) !important;font-weight:600;font-size:13px;transition:border-color 0.15s, background 0.15s;}
  .nav-login:hover{border-color:var(--accent);background:var(--surface);}
  /* 900, not 760: at ~768 every link still showed, which wrapped both the
     brand and "Get the App" onto extra lines and buckled the whole bar. */
  @media (max-width: 900px){.nav-links{gap:12px;font-size:12px;} .nav-links a:not(.nav-cta):not(.nav-login){display:none;}
    .brand-text{white-space:nowrap;}}

  /* ─── buttons ─── */
  .btn-primary{display:inline-flex;align-items:center;gap:8px;padding:14px 28px;background:var(--accent);color:var(--ink-on-accent);font-weight:700;font-size:14px;letter-spacing:.01em;border-radius:10px;border:none;cursor:pointer;box-shadow:0 6px 24px color-mix(in srgb, var(--accent) 30%, transparent);transition:transform 0.15s, box-shadow 0.15s, background 0.15s;font-family:inherit;}
  .btn-primary:hover{transform:translateY(-2px);background:var(--accent-2);box-shadow:0 10px 34px color-mix(in srgb, var(--accent) 42%, transparent);}
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
  .stat-block .big{font-family:var(--font-heading);font-size:24px;font-weight:700;color:var(--accent);line-height:1;}
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
  .mv-orbit::after{inset:12px;border-color:color-mix(in srgb, var(--hot) 35%, transparent);}
  .mv-orbit .center{position:absolute;top:50%;left:50%;width:10px;height:10px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--hot));transform:translate(-50%,-50%);box-shadow:0 0 10px var(--glow);}
  .mv-orbit .moon{position:absolute;top:50%;left:50%;width:6px;height:6px;border-radius:50%;background:var(--accent);margin:-3px 0 0 -3px;animation:orbitSpin 6s linear infinite;transform-origin:0 0;}
  .mv-orbit .moon-2{background:var(--hot);animation-duration:9s;animation-delay:-3s;}
  @keyframes orbitSpin{from{transform:rotate(0deg) translateX(22px) rotate(0deg);}to{transform:rotate(360deg) translateX(22px) rotate(-360deg);}}
  .mv-stack{position:relative;width:64px;height:48px;}
  .mv-stack span{position:absolute;width:48px;height:30px;border-radius:6px;border:1px solid var(--border);background:var(--surface);transition:transform 0.25s ease;}
  .mv-stack span:nth-child(1){top:0;left:0;background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 18%, transparent), transparent);}
  .mv-stack span:nth-child(2){top:6px;left:8px;background:linear-gradient(135deg, color-mix(in srgb, var(--info) 16%, transparent), transparent);animation:stackFloat 5s ease-in-out infinite;}
  .mv-stack span:nth-child(3){top:14px;left:16px;background:linear-gradient(135deg, color-mix(in srgb, var(--success) 15%, transparent), transparent);animation:stackFloat 5s ease-in-out infinite;animation-delay:-2.5s;}
  @keyframes stackFloat{0%,100%{transform:translateY(0);}50%{transform:translateY(-3px);}}
  .mv-grid{display:grid;grid-template-columns:repeat(5, 8px);grid-template-rows:repeat(3, 8px);gap:3px;}
  .mv-grid span{width:8px;height:8px;border-radius:2px;background:color-mix(in srgb, var(--accent) 14%, transparent);border:1px solid var(--border);}
  .mv-grid span.live{background:linear-gradient(135deg, var(--accent), var(--hot));border-color:transparent;box-shadow:0 0 6px var(--glow);animation:gridPing 2.4s ease-in-out infinite;}
  @keyframes gridPing{0%,100%{opacity:1;transform:scale(1);}50%{opacity:0.6;transform:scale(1.2);}}
  .mv-bars{display:flex;align-items:flex-end;gap:4px;height:36px;}
  .mv-bars span{width:6px;border-radius:2px 2px 0 0;background:linear-gradient(180deg, var(--accent), var(--hot));animation:barRise 3.2s ease-in-out infinite;}
  .mv-bars span:nth-child(1){height:40%;animation-delay:0s;}
  .mv-bars span:nth-child(2){height:70%;animation-delay:-0.4s;}
  .mv-bars span:nth-child(3){height:55%;animation-delay:-0.8s;}
  .mv-bars span:nth-child(4){height:90%;animation-delay:-1.2s;}
  .mv-bars span:nth-child(5){height:65%;animation-delay:-1.6s;}
  @keyframes barRise{0%,100%{transform:scaleY(0.85);opacity:0.85;transform-origin:bottom;}50%{transform:scaleY(1.05);opacity:1;}}
  .mv-spark{position:relative;width:36px;height:36px;}
  .mv-spark::before,.mv-spark::after{content:'';position:absolute;inset:0;border-radius:50%;border:1px solid var(--accent);opacity:0.5;animation:sparkExpand 2.6s ease-out infinite;}
  .mv-spark::after{animation-delay:-1.3s;border-color:var(--hot);}
  .mv-spark .core{position:absolute;top:50%;left:50%;width:12px;height:12px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--hot));transform:translate(-50%,-50%);box-shadow:0 0 14px var(--glow);}
  @keyframes sparkExpand{0%{transform:scale(0.4);opacity:0.9;}100%{transform:scale(1.6);opacity:0;}}
  .mv-publish{display:flex;align-items:center;gap:12px;}
  .mv-publish .platform{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:700;font-size:14px;color:#fff;}
  .mv-publish .fb{background:#1877F2;}
  .mv-publish .ig{background:linear-gradient(135deg, #833AB4, #FD1D1D, #FCB045);}
  .mv-publish .flow{flex:1;min-width:16px;max-width:24px;height:2px;background:linear-gradient(90deg, transparent, var(--accent), var(--hot), transparent);background-size:200% 100%;animation:flowSweep 2.4s linear infinite;border-radius:2px;}
  @keyframes flowSweep{0%{background-position:200% 0;}100%{background-position:-200% 0;}}

  /* ─── reduced motion, site-wide ───
     The shell has always run several ambient loops (logo glow, brand dot,
     drifting orbs, every mini-visual) with no reduced-motion escape at
     all. Per-page blocks can't reach them, so the opt-out belongs here. */
  @media (prefers-reduced-motion: reduce){
    .orb, .brand .logo, .brand .dot, .stat-block .big::after,
    .mv-orbit .moon, .mv-grid span.live, .mv-bars span, .mv-stack span,
    .mv-spark::before, .mv-spark::after, .mv-publish .flow{animation:none !important;}
    .reveal{transition:none !important;}
    .card:hover, .btn-primary:hover, .nav-cta:hover{transform:none !important;}
  }

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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;600;700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
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
      <a href="/download" class="{ax_download}" title="Get the app for Android, iPhone, Windows &amp; macOS">Get the App</a>
      <a class="nav-login" href="{app_url}">Log in</a>
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
      <span class="small">Built by The Solutionist System LLC · Michigan, USA</span>
    </div>
    <div class="footer-links">
      <a href="/features">Features</a>
      <a href="/compare">Compare</a>
      <a href="/faq">FAQ</a>
      <a href="/about">About</a>
      <a href="/get-started">Get Started</a>
      <a href="{app_url}">Log in</a>
      <a href="/download">Get the app</a>
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
        "ax_download":    "is-active" if active == "download"    else "",
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
        app_url=APP_URL,
        **active_map,
    )


# ══════════════════════════════════════════════════════════════════════
# HOME — trimmed: hero + features overview + audience + why + CTA
# ══════════════════════════════════════════════════════════════════════

FEATURES_SCRIPT = """
<script>
(function () {
  /* Count the KPI numerals up when their panel scrolls into view. The
     numbers are the point of those panels — landing on the final value
     with no motion made them read as flat screenshots. */
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var nums = [].slice.call(document.querySelectorAll('.fx-num'));
  if (!nums.length) return;

  function fmt(v, prefix) {
    return (prefix || '') + Math.round(v).toLocaleString('en-US');
  }
  function run(el) {
    var to = Number(el.dataset.to || 0), prefix = el.dataset.prefix || '';
    if (reduced) { el.textContent = fmt(to, prefix); return; }
    var dur = 1100, t0 = null;
    function step(ts) {
      if (t0 === null) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      el.textContent = fmt(to * (1 - Math.pow(1 - p, 3)), prefix);   /* easeOutCubic */
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  if (!('IntersectionObserver' in window)) { nums.forEach(run); return; }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (e.isIntersecting) { run(e.target); io.unobserve(e.target); }
    });
  }, { threshold: 0.4 });
  nums.forEach(function (n) { io.observe(n); });
})();
</script>
"""

FEATURES_FX_CSS = """
      /* ── feature visuals: every abstract mv-* shape is replaced by a
         real product panel, each animating the ONE thing that section is
         actually about. Panels reuse the replica kit, so the features
         page and the home wheel are visibly the same software. ── */
      /* .fs-visual is still a centring flex box from the old abstract
         shapes — without display:block the panel and its caption laid out
         as flex siblings in a ROW and the app shrank to a corner. */
      /* Qualified with .fs-visual on purpose: the page's own .fs-visual
         rule is emitted AFTER this block at equal specificity, so a bare
         .fsv lost every tie — the panel stayed a centring flex box and
         laid the app and its caption out side by side. */
      .fs-visual.fsv{display:block;background:transparent;border:0;padding:0;min-height:0;
        position:relative;overflow:visible;}
      .fs-visual.fsv::before{display:none;}
      .fs-visual.fsv .app{width:100%;height:322px;}
      .fsv-cap{margin-top:11px;font-size:11.5px;color:var(--text-dim);display:flex;align-items:center;gap:8px;}
      .fsv-cap .dot{width:6px;height:6px;border-radius:50%;background:var(--success);
        box-shadow:0 0 8px var(--success);flex-shrink:0;}

      /* rows arriving in sequence */
      @keyframes fxRise{from{opacity:0;transform:translateY(8px);}to{opacity:1;transform:none;}}
      .fx-seq > *{opacity:0;animation:fxRise .55s ease forwards;}
      .fx-seq > *:nth-child(1){animation-delay:.10s;} .fx-seq > *:nth-child(2){animation-delay:.24s;}
      .fx-seq > *:nth-child(3){animation-delay:.38s;} .fx-seq > *:nth-child(4){animation-delay:.52s;}
      .fx-seq > *:nth-child(5){animation-delay:.66s;} .fx-seq > *:nth-child(6){animation-delay:.80s;}

      /* an invoice settling: SENT flips to PAID and a green sweep runs through */
      .fx-settle{position:relative;overflow:hidden;}
      .fx-settle::after{content:'';position:absolute;inset:0;pointer-events:none;
        background:linear-gradient(90deg,transparent,rgba(34,197,94,.22),transparent);
        transform:translateX(-100%);animation:fxSweep 5.5s ease-in-out infinite;}
      @keyframes fxSweep{0%,45%{transform:translateX(-100%);}70%,100%{transform:translateX(100%);}}
      .fx-flip{position:relative;display:inline-grid;}
      .fx-flip > *{grid-area:1/1;}
      .fx-flip .a{animation:fxOut 5.5s ease-in-out infinite;}
      .fx-flip .b{animation:fxIn  5.5s ease-in-out infinite;}
      @keyframes fxOut{0%,52%{opacity:1;}62%,100%{opacity:0;}}
      @keyframes fxIn {0%,52%{opacity:0;}62%,100%{opacity:1;}}

      /* growth bars */
      .fx-chart{display:flex;align-items:flex-end;gap:7px;height:104px;padding:0 2px;}
      .fx-chart i{flex:1;border-radius:3px 3px 0 0;transform-origin:bottom;transform:scaleY(.06);
        background:linear-gradient(180deg,var(--accent),color-mix(in srgb,var(--accent) 35%,transparent));
        animation:fxGrow 1s cubic-bezier(.22,1,.36,1) forwards;}
      .fx-chart i:nth-child(1){height:34%;animation-delay:.05s;}
      .fx-chart i:nth-child(2){height:52%;animation-delay:.13s;}
      .fx-chart i:nth-child(3){height:44%;animation-delay:.21s;}
      .fx-chart i:nth-child(4){height:68%;animation-delay:.29s;}
      .fx-chart i:nth-child(5){height:60%;animation-delay:.37s;}
      .fx-chart i:nth-child(6){height:84%;animation-delay:.45s;}
      .fx-chart i:nth-child(7){height:100%;animation-delay:.53s;
        background:linear-gradient(180deg,var(--info),color-mix(in srgb,var(--info) 35%,transparent));}
      @keyframes fxGrow{to{transform:scaleY(1);}}
      .fx-axis{display:flex;justify-content:space-between;font-size:7.5px;color:var(--ink-3);
        letter-spacing:.08em;text-transform:uppercase;margin-top:5px;}

      /* a site composing itself, band by band */
      .fx-compose{flex:1;border-radius:8px;overflow:hidden;border:1px solid var(--line);
        display:flex;flex-direction:column;min-height:0;}
      .fx-compose > *{opacity:0;animation:fxRise .6s ease forwards;}
      .fx-compose > *:nth-child(1){animation-delay:.15s;}
      .fx-compose > *:nth-child(2){animation-delay:.75s;}
      .fx-compose > *:nth-child(3){animation-delay:1.35s;}

      /* publish: one post, two channels */
      .fx-pub{display:flex;align-items:center;gap:12px;}
      .fx-pub .ch{width:34px;height:34px;border-radius:9px;display:grid;place-items:center;flex-shrink:0;
        font-size:13px;font-weight:800;color:#fff;}
      .fx-pub .fb{background:#1877F2;} .fx-pub .ig{background:linear-gradient(135deg,#833AB4,#FD1D1D,#FCB045);}
      .fx-pub .wire{flex:1;height:2px;border-radius:2px;position:relative;background:rgba(255,255,255,.09);overflow:hidden;}
      .fx-pub .wire::after{content:'';position:absolute;inset:0;width:42%;border-radius:2px;
        background:linear-gradient(90deg,transparent,var(--accent),var(--info),transparent);
        animation:fxWire 2.3s linear infinite;}
      @keyframes fxWire{from{transform:translateX(-110%);}to{transform:translateX(340%);}}

      /* the count-up numerals get their value written by JS on reveal */
      .fx-num{font-variant-numeric:tabular-nums;}

      @media (prefers-reduced-motion: reduce){
        .fx-seq > *,.fx-compose > *{opacity:1 !important;animation:none !important;}
        .fx-settle::after,.fx-flip .a,.fx-flip .b,.fx-pub .wire::after{animation:none !important;}
        .fx-flip .a{opacity:0;} .fx-flip .b{opacity:1;}
        .fx-chart i{transform:scaleY(1);animation:none !important;}
      }
"""

REPLICA_KIT_CSS = """
      /* ══════════════════════════════════════════════════════════════
         THE REPLICA KIT
         One UI vocabulary traced from the real product, reused by the
         hero, the six room faces and the features page.

         Colour note: inside .app we deliberately switch to the PRODUCT's
         own palette — amber actions, violet briefing, magenta/cyan mark —
         because that is what the software actually looks like. The blue
         site chrome frames it; it does not repaint it.
         ══════════════════════════════════════════════════════════════ */
      .app{--ink:#F3F5F8;--ink-2:#AEB4C0;--ink-3:#767D8B;
        --pane:#0F1218;--pane-2:#151A23;--line:rgba(255,255,255,.08);
        --gold:#C9A84C;--vio:#7C3AED;
        display:flex;flex-direction:column;overflow:hidden;border-radius:14px;
        background:#0B0D12;border:1px solid var(--border-strong);
        box-shadow:0 40px 100px rgba(0,0,0,.65), 0 0 0 1px rgba(0,0,0,.5);
        font-size:11px;line-height:1.4;color:var(--ink);}

      /* ── top bar ── */
      .app-top{display:flex;align-items:center;gap:12px;padding:9px 12px;flex-shrink:0;
        border-bottom:1px solid var(--line);background:#0C0F14;}
      .at-mark{width:17px;height:17px;flex-shrink:0;border-radius:5px;
        background:linear-gradient(135deg,#E879F9,#22D3EE);}
      .at-search{flex:1;min-width:0;display:flex;align-items:center;gap:7px;height:25px;padding:0 9px;
        border-radius:7px;background:var(--pane);border:1px solid var(--line);color:var(--ink-3);font-size:10.5px;}
      .at-search .kbd{margin-left:auto;padding:1px 5px;border-radius:4px;font-size:8.5px;
        background:rgba(255,255,255,.06);border:1px solid var(--line);}
      .at-cta{padding:5px 10px;border-radius:7px;background:var(--gold);color:#1A1405;
        font-size:10px;font-weight:700;white-space:nowrap;}
      .at-urgent{display:inline-flex;align-items:center;gap:5px;font-size:9.5px;font-weight:600;color:#F87171;white-space:nowrap;}
      .at-urgent::before{content:'';width:5px;height:5px;border-radius:50%;background:#EF4444;}
      .at-av{width:20px;height:20px;border-radius:6px;flex-shrink:0;
        background:linear-gradient(135deg,#3B82F6,#7C3AED);}

      /* ── the workspace strip under the top bar ── */
      .app-strip{display:flex;align-items:center;gap:9px;padding:6px 12px;flex-shrink:0;
        border-bottom:1px solid var(--line);background:#0A0D11;font-size:9px;
        letter-spacing:.13em;text-transform:uppercase;color:var(--ink-3);}
      .app-strip .biz{color:var(--ink-2);letter-spacing:.04em;text-transform:none;font-size:10.5px;font-weight:600;}
      .app-strip .sp{margin-left:auto;}
      .app-strip .tab{padding:3px 8px;border-radius:5px;}
      .app-strip .tab.on{background:color-mix(in srgb, var(--gold) 16%, transparent);color:var(--gold);
        border:1px solid color-mix(in srgb, var(--gold) 34%, transparent);}

      .app-body{flex:1;display:flex;min-height:0;}

      /* ── sidebar ── */
      .app-side{width:168px;flex-shrink:0;display:flex;flex-direction:column;gap:1px;
        padding:9px 7px;border-right:1px solid var(--line);background:#0A0D11;overflow:hidden;}
      .app.is-mini .app-side{width:136px;}
      .as-user{display:flex;align-items:center;gap:7px;padding:6px 6px 9px;margin-bottom:4px;
        border-bottom:1px solid var(--line);}
      .as-user .av{width:19px;height:19px;border-radius:6px;flex-shrink:0;
        background:linear-gradient(135deg,#F59E0B,#EF4444);}
      .as-user .nm{font-size:10px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
      .as-user .nm span{display:block;font-size:8px;font-weight:500;color:var(--ink-3);}
      .as-plan{margin-left:auto;padding:1px 5px;border-radius:4px;font-size:7.5px;font-weight:800;
        letter-spacing:.1em;color:var(--gold);border:1px solid color-mix(in srgb, var(--gold) 40%, transparent);}
      .app.is-mini .as-plan{display:none;}
      .as-sec{display:flex;align-items:center;gap:5px;margin:9px 0 3px;padding:0 6px;white-space:nowrap;
        font-size:7.5px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-3);}
      /* the mini sidebar is ~136px — full tracking wrapped "MISSION CONTROL"
         onto two lines and shoved the whole nav down */
      .app.is-mini .as-sec{letter-spacing:.08em;font-size:7px;}
      .app.is-mini .as-user .nm{font-size:9px;}
      .as-sec::before{content:'';width:4px;height:4px;border-radius:50%;background:var(--gold);flex-shrink:0;}
      .as-item{display:flex;align-items:center;gap:8px;padding:5px 7px;border-radius:6px;
        color:var(--ink-2);font-size:10px;white-space:nowrap;overflow:hidden;position:relative;}
      .as-item .ic{width:13px;height:13px;flex-shrink:0;border-radius:4px;
        background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.14);}
      .as-item.is-on .ic{background:color-mix(in srgb, var(--gold) 30%, transparent);
        border-color:color-mix(in srgb, var(--gold) 55%, transparent);}
      .as-item.is-on{background:rgba(255,255,255,.07);color:var(--ink);font-weight:600;}
      .as-item.is-on::before{content:'';position:absolute;left:0;top:5px;bottom:5px;width:2px;
        border-radius:0 2px 2px 0;background:var(--gold);}
      .as-item .ct{margin-left:auto;font-size:8.5px;color:var(--ink-3);}
      .as-chief{margin-top:auto;display:flex;align-items:center;gap:6px;padding:7px 8px;border-radius:8px;
        font-size:9.5px;font-weight:700;color:var(--gold);
        background:color-mix(in srgb, var(--gold) 11%, transparent);
        border:1px solid color-mix(in srgb, var(--gold) 32%, transparent);}
      .as-chief::before{content:'';width:5px;height:5px;border-radius:50%;background:#22C55E;flex-shrink:0;
        box-shadow:0 0 7px #22C55E;}
      .as-chief .on{margin-left:auto;font-size:7.5px;letter-spacing:.1em;color:#22C55E;}

      /* ── canvas ── */
      .app-canvas{flex:1;min-width:0;padding:13px;display:flex;flex-direction:column;gap:11px;overflow:hidden;}

      /* the app's signature header block: rule → eyebrow → title → substat */
      .ah-rule{width:26px;height:2px;border-radius:2px;background:var(--gold);}
      .ah-eyebrow{font-size:8px;font-weight:800;letter-spacing:.19em;text-transform:uppercase;color:var(--ink-3);}
      .ah-title{font-family:var(--font-heading);font-size:19px;font-weight:700;letter-spacing:-.02em;line-height:1.1;}
      .ah-sub{font-size:9.5px;color:var(--ink-3);}
      .ah-row{display:flex;align-items:flex-end;justify-content:space-between;gap:10px;}
      .ah-btn{padding:5px 10px;border-radius:6px;background:var(--gold);color:#1A1405;
        font-size:9.5px;font-weight:700;white-space:nowrap;flex-shrink:0;}

      /* KPI cards */
      .kpi-row{display:grid;grid-template-columns:repeat(5,1fr);gap:8px;}
      .kpi{padding:9px 10px;border-radius:9px;background:var(--pane);border:1px solid var(--line);
        display:flex;flex-direction:column;gap:3px;min-width:0;overflow:hidden;}
      .kpi .k{font-size:7.5px;font-weight:700;letter-spacing:.13em;text-transform:uppercase;color:var(--ink-3);
        white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
      .kpi .v{font-family:var(--font-heading);font-size:19px;font-weight:700;letter-spacing:-.02em;line-height:1.05;}
      .kpi .v.gold{color:var(--gold);} .kpi .v.up{color:#22C55E;} .kpi .v.warn{color:#F87171;}
      .kpi .f{font-size:8.5px;color:var(--ink-3);}
      .kpi .f.up{color:#22C55E;}
      .kpi-ico{display:none;}

      /* the violet briefing panel + Chief */
      .brief{position:relative;border-radius:11px;padding:13px;display:flex;gap:12px;min-height:0;overflow:hidden;
        border:1px solid color-mix(in srgb, var(--vio) 34%, transparent);
        background:linear-gradient(125deg, color-mix(in srgb, var(--vio) 34%, #0B0D12),
                                            color-mix(in srgb, #1E1B4B 70%, #0B0D12) 55%,
                                            color-mix(in srgb, #22D3EE 9%, #0B0D12));}
      .brief-l{position:relative;z-index:1;flex:1;min-width:0;display:flex;flex-direction:column;gap:6px;}
      /* the real briefing has the S-mark floating in it — without this the
         panel reads as an empty purple slab under the greeting */
      .brief-mark{position:absolute;right:232px;bottom:-14px;width:128px;height:128px;
        pointer-events:none;opacity:.92;
        filter:drop-shadow(0 0 26px rgba(124,58,237,.65)) drop-shadow(0 10px 22px rgba(0,0,0,.5));}
      .app.is-mini .brief-mark{display:none;}
      @media (max-width:1100px){.brief-mark{right:24px;}}
      .brief .date{font-size:7.5px;font-weight:800;letter-spacing:.17em;text-transform:uppercase;color:#C4B5FD;}
      .brief .hi{font-family:var(--font-heading);font-size:23px;font-weight:700;letter-spacing:-.025em;line-height:1.05;}
      .brief .hi b{color:var(--gold);font-weight:700;}
      .brief .cp{font-size:9.5px;color:#CBD5E1;max-width:250px;}
      .brief-btns{display:flex;align-items:center;gap:9px;margin-top:2px;}
      .brief-btns .lnk{font-size:9.5px;color:#C4B5FD;text-decoration:underline;text-underline-offset:2px;}

      .chief{width:220px;flex-shrink:0;border-radius:9px;padding:9px;display:flex;flex-direction:column;gap:6px;
        background:rgba(6,8,13,.62);border:1px solid rgba(255,255,255,.11);}
      .app.is-mini .chief{display:none;}
      .chief-h{display:flex;align-items:center;gap:5px;font-size:8px;font-weight:800;
        letter-spacing:.14em;text-transform:uppercase;color:var(--ink-2);}
      .chief-h .on{margin-left:auto;display:inline-flex;align-items:center;gap:3px;color:#22C55E;letter-spacing:.08em;}
      .chief-h .on::before{content:'';width:4px;height:4px;border-radius:50%;background:#22C55E;box-shadow:0 0 6px #22C55E;}
      .chief-lead{font-size:9px;color:var(--ink-3);}
      .chief-f{display:flex;align-items:center;gap:6px;padding:5px 7px;border-radius:6px;
        background:rgba(255,255,255,.045);border:1px solid var(--line);font-size:9px;}
      .chief-f .sq{width:13px;height:13px;border-radius:4px;flex-shrink:0;
        background:color-mix(in srgb, var(--vio) 40%, transparent);}
      .chief-f .sq.warn{background:color-mix(in srgb, #EF4444 40%, transparent);}
      .chief-f .sq.ok{background:color-mix(in srgb, #22C55E 40%, transparent);}
      .chief-f .g{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
      .chief-f .amt{color:var(--gold);font-weight:700;font-size:8.5px;}
      .chief-f .tag{font-size:7px;font-weight:800;letter-spacing:.08em;padding:1px 4px;border-radius:3px;
        color:#F5C542;background:rgba(245,197,66,.14);}
      .chief-ask{font-size:9px;color:var(--ink-2);margin-top:1px;}
      .chief-btns{display:flex;gap:6px;}
      .chief-btns b{flex:1;text-align:center;padding:5px;border-radius:6px;font-size:9px;font-weight:700;
        background:var(--gold);color:#1A1405;}
      .chief-btns i{flex:1;text-align:center;padding:5px;border-radius:6px;font-size:9px;font-style:normal;
        border:1px solid rgba(255,255,255,.16);color:var(--ink-2);}
      .chief-in{display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:6px;font-size:9px;
        color:var(--ink-3);background:rgba(255,255,255,.04);border:1px solid var(--line);}
      .chief-in .go{margin-left:auto;width:14px;height:14px;border-radius:4px;background:var(--gold);}

      /* generic panel + list rows */
      .pnl{border-radius:9px;background:var(--pane);border:1px solid var(--line);padding:9px;
        display:flex;flex-direction:column;gap:6px;min-height:0;overflow:hidden;}
      .pnl-h{display:flex;align-items:center;gap:6px;font-size:8px;font-weight:800;
        letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);}
      .pnl-h .ct{margin-left:auto;padding:1px 5px;border-radius:4px;font-size:7.5px;
        color:var(--gold);background:color-mix(in srgb, var(--gold) 14%, transparent);}
      .r{display:flex;align-items:center;gap:8px;padding:5px 7px;border-radius:6px;font-size:9.5px;
        background:rgba(255,255,255,.028);border:1px solid var(--line);position:relative;overflow:hidden;}
      .r .bar{position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--vio);
        border-radius:0;padding:0;border:0;flex:none;}
      /* modifiers are spelled out: single letters collided with the row
         class .r and the grow class .g, which turned these 2px status bars
         into stretched blocks over the invoice IDs. */
      .r .bar.grn{background:#22C55E;} .r .bar.red{background:#EF4444;} .r .bar.amb{background:var(--gold);}
      .r .id{font-size:8px;letter-spacing:.06em;color:var(--ink-3);flex-shrink:0;}
      .r .nm{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
      .r .nm span{display:block;font-size:8px;font-weight:400;color:var(--ink-3);}
      .r .g{flex:1;min-width:0;}
      .r .amt{font-weight:600;flex-shrink:0;font-size:9.5px;}
      .r .av{width:17px;height:17px;border-radius:50%;flex-shrink:0;display:grid;place-items:center;
        font-size:7px;font-weight:800;color:#08090C;}
      .pill{padding:2px 6px;border-radius:4px;font-size:7px;font-weight:800;letter-spacing:.1em;
        text-transform:uppercase;flex-shrink:0;}
      .pill.paid{color:#22C55E;background:rgba(34,197,94,.14);border:1px solid rgba(34,197,94,.32);}
      .pill.sent{color:var(--gold);background:color-mix(in srgb, var(--gold) 14%, transparent);
        border:1px solid color-mix(in srgb, var(--gold) 32%, transparent);}
      .pill.due{color:#F87171;background:rgba(239,68,68,.14);border:1px solid rgba(239,68,68,.32);}
      .pill.draft{color:var(--ink-3);border:1px solid var(--line);}
      .pill.ok{color:#22C55E;border:1px solid rgba(34,197,94,.3);background:rgba(34,197,94,.08);}
      .pill.live{color:#22D3EE;background:rgba(34,211,238,.12);border:1px solid rgba(34,211,238,.3);}

      /* aging buckets (Operate) */
      .age{display:grid;grid-template-columns:repeat(5,1fr);gap:7px;}
      .age > div{padding:7px 8px;border-radius:8px;background:var(--pane);border:1px solid var(--line);}
      .age .k{font-size:7px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-3);}
      .age .v{font-family:var(--font-heading);font-size:13px;font-weight:700;margin-top:2px;}
      .age .s{font-size:7.5px;color:var(--ink-3);}
      .age .hot{border-color:rgba(239,68,68,.3);background:rgba(239,68,68,.07);}
      .age .hot .v{color:#F87171;}
      .age .cta{background:var(--gold);border-color:var(--gold);color:#1A1405;}
      .age .cta .k,.age .cta .s{color:rgba(26,20,5,.72);}
      .age .cta .v{color:#1A1405;font-size:11px;}

      /* filter chips */
      .chips{display:flex;flex-wrap:wrap;gap:5px;}
      .chips span{padding:3px 8px;border-radius:99px;font-size:8.5px;color:var(--ink-2);
        border:1px solid var(--line);display:inline-flex;align-items:center;gap:5px;}
      .chips span b{color:var(--ink-3);font-size:7.5px;}
      .chips span.on{background:color-mix(in srgb, var(--gold) 16%, transparent);color:var(--gold);
        border-color:color-mix(in srgb, var(--gold) 36%, transparent);}
      .chips span.on b{color:var(--gold);}

      /* quick actions */
      .qa-h{display:flex;align-items:center;gap:6px;font-size:8px;font-weight:800;
        letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);}
      .qa-h .hint{margin-left:auto;font-size:8px;letter-spacing:.02em;text-transform:none;font-style:italic;}
      .qa{display:grid;grid-template-columns:repeat(9,1fr);gap:7px;}
      .qa i{border-radius:8px;background:var(--pane);border:1px solid var(--line);font-style:normal;
        padding:7px 4px;display:flex;flex-direction:column;align-items:center;gap:5px;
        font-size:7.5px;line-height:1.25;text-align:center;color:var(--ink-3);
        white-space:nowrap;overflow:hidden;}
      .qa i::before{content:'';width:17px;height:17px;border-radius:5px;flex-shrink:0;
        background:color-mix(in srgb, var(--c,#7C3AED) 30%, transparent);
        border:1px solid color-mix(in srgb, var(--c,#7C3AED) 58%, transparent);}

      /* progress ring (Academy) */
      .ring{width:64px;height:64px;border-radius:50%;flex-shrink:0;display:grid;place-items:center;
        background:conic-gradient(var(--gold) 0turn .62turn, rgba(255,255,255,.07) .62turn 1turn);}
      .ring i{width:48px;height:48px;border-radius:50%;background:#0B0D12;display:grid;place-items:center;
        font-family:var(--font-heading);font-size:14px;font-weight:700;font-style:normal;}

      /* brand swatches + artifacts (Studio) */
      .sw{display:flex;gap:5px;}
      .sw i{width:22px;height:22px;border-radius:6px;border:1px solid rgba(255,255,255,.18);}
      .arts{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;flex:1;min-height:0;}
      .art{border-radius:8px;border:1px solid var(--line);padding:8px;display:flex;flex-direction:column;
        justify-content:space-between;background:linear-gradient(160deg, rgba(124,58,237,.14), transparent);}
      .art .c{font-size:7px;letter-spacing:.13em;text-transform:uppercase;color:var(--ink-3);}
      .art .m{font-family:var(--font-heading);font-size:12px;font-weight:700;}
      .art .l{height:2.5px;border-radius:2px;background:rgba(255,255,255,.1);margin-top:4px;}
      .art .l.s{width:58%;}

      /* the Chief transcript replays itself — one line at a time */
      .cx{height:330px;}
      .cx .app-canvas{justify-content:flex-end;gap:8px;}
      .cx-b{max-width:80%;padding:8px 11px;border-radius:11px;font-size:11px;line-height:1.5;
        opacity:0;animation:cxIn .5s ease forwards;}
      .cx-b.you{align-self:flex-end;background:rgba(255,255,255,.06);border:1px solid var(--line);
        border-bottom-right-radius:3px;color:var(--ink-2);}
      .cx-b.ai{align-self:flex-start;border-bottom-left-radius:3px;color:var(--ink);
        background:color-mix(in srgb, var(--vio) 22%, transparent);
        border:1px solid color-mix(in srgb, var(--vio) 42%, transparent);}
      .cx-b.act{align-self:flex-start;font-size:9.5px;font-weight:800;letter-spacing:.08em;
        text-transform:uppercase;color:#22C55E;background:rgba(34,197,94,.12);
        border:1px solid rgba(34,197,94,.3);padding:6px 10px;border-radius:7px;}
      .cx-b b{color:var(--gold);}
      @keyframes cxIn{from{opacity:0;transform:translateY(9px);}to{opacity:1;transform:none;}}
      .cx-b:nth-child(1){animation-delay:.15s;} .cx-b:nth-child(2){animation-delay:1.5s;}
      .cx-b:nth-child(3){animation-delay:3.1s;} .cx-b:nth-child(4){animation-delay:4.3s;}
      .cx-b:nth-child(5){animation-delay:5.6s;}

      @media (prefers-reduced-motion: reduce){
        .cx-b{animation:none !important;opacity:1 !important;transform:none !important;}
      }

      /* mini site (Smart Sites) */
      .site{flex:1;border-radius:8px;overflow:hidden;border:1px solid var(--line);display:flex;
        flex-direction:column;min-height:0;}
      .site .band{padding:13px 11px;display:flex;flex-direction:column;gap:4px;
        background:linear-gradient(135deg, rgba(124,58,237,.3), rgba(34,211,238,.12));}
      .site .band .t{font-family:var(--font-heading);font-size:13px;font-weight:700;letter-spacing:-.02em;}
      .site .band .s{font-size:8.5px;color:var(--ink-2);}
      .site .cards{flex:1;display:grid;grid-template-columns:repeat(3,1fr);gap:6px;padding:9px;}
      .site .cards i{border-radius:5px;background:var(--pane);border:1px solid var(--line);}
"""


def render_home() -> str:
    # ── Pass 2 (2026-07-27, Kevin's redirect). Three changes:
    #      1. blue leads (see :root) — the ember/brass pass read purple-
    #         adjacent to him and he asked to flip the original palette
    #         so blue carries it instead of violet/pink;
    #      2. the hero orbit is GONE. "the orbit at the top should be
    #         different. in the system this is not there." It has been
    #         replaced by a detailed replica of the real Mission Control;
    #      3. every product surface is now drawn with the replica kit,
    #         traced from the live app, per "I want this to look like the
    #         replica of the system itself. very detailed like it."
    #    Restraint follows bridgemind.ai, which Kevin cited as the target:
    #    flat colour, hairline borders, no glow stacking, generous air.
    extra_css = """
      .container-xl{max-width:1340px;margin:0 auto;padding:0 32px;}
      @media (max-width:640px){.container-xl{padding:0 20px;}}

""" + REPLICA_KIT_CSS + """

      /* ══════════════════════════════════════════════════════════════
         HERO — copy over a full-width Mission Control replica
         ══════════════════════════════════════════════════════════════ */
      .hero{position:relative;padding:72px 0 20px;overflow:hidden;}
      .hero::before{content:'';position:absolute;inset:-160px 0 auto;height:620px;pointer-events:none;
        background:radial-gradient(52% 70% at 50% 0%, var(--glow), transparent 72%);opacity:.55;}
      .hero .container-xl{position:relative;z-index:1;}
      .hero-copy{max-width:780px;}
      .hero h1{margin:20px 0 20px;font-size:clamp(42px,6.2vw,68px);line-height:1.02;}
      .hero .lead{max-width:600px;margin:0 0 32px;font-size:17px;}
      .hero-ctas{display:flex;flex-wrap:wrap;gap:12px;align-items:center;}
      .hero-meta{display:flex;flex-wrap:wrap;align-items:center;gap:18px;margin-top:26px;}
      .hero-note{font-size:12.5px;color:var(--text-dim);}

      .hero-app{margin-top:52px;}
      .hero-app-cap{display:flex;align-items:center;gap:9px;margin-bottom:11px;font-size:11.5px;
        color:var(--text-dim);letter-spacing:.02em;}
      .hero-app-cap b{color:var(--text-secondary);font-weight:600;}
      .hero-app-cap .dot{width:6px;height:6px;border-radius:50%;background:var(--success);
        box-shadow:0 0 8px var(--success);flex-shrink:0;}
      .hero-app .app{height:540px;}
      .hero-2col{display:grid;grid-template-columns:1fr 226px;gap:10px;flex:1;min-height:0;}
      @media (max-width:1100px){.hero-2col{grid-template-columns:1fr;} .hero-2col > .pnl{display:none;}}

      /* the replica is the hero image — below ~980px it stops being
         readable at any scale, so it scrolls horizontally at real size
         rather than shrinking into illegible mush */
      .app-scroll{overflow-x:auto;overflow-y:hidden;-webkit-overflow-scrolling:touch;
        scrollbar-width:thin;padding-bottom:6px;}
      @media (max-width:980px){
        .app-scroll{margin:0 -20px;padding:0 20px 8px;}
        .hero-app .app{width:960px;height:500px;}
      }

      /* ══════════════════════════════════════════════════════════════
         CHIEF strip
         ══════════════════════════════════════════════════════════════ */
      .ask{position:relative;padding:104px 0;border-top:1px solid var(--border);}
      .ask-grid{display:grid;grid-template-columns:.88fr 1.12fr;gap:60px;align-items:center;}
      @media (max-width:980px){.ask-grid{grid-template-columns:1fr;gap:36px;}}
      .ask-list{list-style:none;margin-top:28px;display:grid;gap:16px;}
      .ask-list li{display:flex;gap:13px;align-items:flex-start;font-size:14.5px;color:var(--text-muted);line-height:1.55;}
      .ask-list .n{flex-shrink:0;width:23px;height:23px;border-radius:6px;display:grid;place-items:center;
        font-family:var(--font-heading);font-size:11px;font-weight:700;color:var(--accent);
        background:color-mix(in srgb, var(--accent) 13%, transparent);
        border:1px solid color-mix(in srgb, var(--accent) 32%, transparent);}
      .ask-list b{color:var(--text-primary);font-weight:600;}

      /* ══════════════════════════════════════════════════════════════
         THE ROOMS — a carousel of real product surfaces
         ══════════════════════════════════════════════════════════════ */
      .rooms{padding:104px 0 88px;border-top:1px solid var(--border);position:relative;overflow:hidden;}
      .rooms .container-xl{position:relative;z-index:1;}
      .rooms-tabs{display:flex;flex-wrap:wrap;justify-content:center;gap:7px;margin:0 auto 40px;max-width:940px;}
      .room-tab{padding:8px 15px;border-radius:99px;font-size:12.5px;font-weight:600;
        color:var(--text-muted);background:transparent;border:1px solid var(--border);
        cursor:pointer;font-family:inherit;transition:color .18s, border-color .18s, background .18s;}
      .room-tab:hover{color:var(--text-primary);border-color:var(--border-strong);}
      .room-tab[aria-selected="true"]{color:var(--ink-on-accent);background:var(--accent);border-color:var(--accent);}

      .rooms-viewport{position:relative;height:432px;perspective:1900px;perspective-origin:50% 46%;}
      .rooms-ring{position:absolute;inset:0;transform-style:preserve-3d;
        transform:translateZ(-660px) rotateY(var(--ry,0deg));
        transition:transform .85s cubic-bezier(.4,.9,.25,1);will-change:transform;}
      .room-face{position:absolute;top:50%;left:50%;width:748px;height:376px;margin:-188px 0 0 -374px;
        transform:rotateY(var(--fa)) translateZ(660px);
        opacity:.2;filter:blur(3px) saturate(.5);pointer-events:none;
        transition:opacity .5s ease, filter .5s ease;}
      .room-face.is-active{opacity:1;filter:none;pointer-events:auto;}
      .room-face .app{height:100%;}

      .rooms-nav{display:flex;align-items:center;justify-content:center;gap:16px;margin-top:34px;}
      .rooms-arrow{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;cursor:pointer;
        background:var(--surface);border:1px solid var(--border-strong);color:var(--text-secondary);
        font-size:16px;font-family:inherit;transition:background .18s, border-color .18s, color .18s;}
      .rooms-arrow:hover{background:var(--surface-2);border-color:var(--accent);color:var(--accent);}
      .rooms-count{font-family:var(--font-heading);font-size:12.5px;color:var(--text-dim);
        letter-spacing:.16em;min-width:66px;text-align:center;}
      .room-caption{text-align:center;max-width:640px;margin:22px auto 0;font-size:14.5px;
        color:var(--text-muted);line-height:1.6;min-height:46px;}

      @media (max-width:1000px){
        .rooms-viewport{height:auto;perspective:none;overflow-x:auto;overflow-y:hidden;
          scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;
          padding-bottom:8px;margin:0 -20px;scrollbar-width:none;}
        .rooms-viewport::-webkit-scrollbar{display:none;}
        .rooms-ring{position:static;transform:none !important;display:flex;gap:14px;padding:0 20px;}
        .room-face{position:static;flex:0 0 auto;width:748px;height:376px;margin:0;
          transform:none !important;opacity:1;filter:none;pointer-events:auto;scroll-snap-align:center;}
        .rooms-nav{display:none;}
      }

      /* ══════════════════════════════════════════════════════════════
         rest of page
         ══════════════════════════════════════════════════════════════ */
      .demo-section{padding:96px 0;border-top:1px solid var(--border);}
      .demo-frame{max-width:900px;margin:0 auto;border-radius:14px;overflow:hidden;
        border:1px solid var(--border-strong);background:var(--surface);box-shadow:0 40px 90px rgba(0,0,0,.6);}
      .demo-chrome{display:flex;align-items:center;gap:7px;padding:11px 16px;border-bottom:1px solid var(--border);
        background:#0C0F14;}
      .demo-chrome span{width:10px;height:10px;border-radius:50%;background:var(--border-strong);}
      .demo-chrome span:nth-child(1){background:#EF4444;}
      .demo-chrome span:nth-child(2){background:var(--warning);}
      .demo-chrome span:nth-child(3){background:var(--success);}
      .demo-chrome em{margin-left:10px;font-style:normal;font-size:11px;letter-spacing:.16em;
        text-transform:uppercase;color:var(--text-dim);}
      .demo-video{width:100%;display:block;aspect-ratio:16/9;background:#000;}
      .demo-caption{text-align:center;margin-top:18px;font-size:13px;color:var(--text-dim);}

      .sec-num{font-family:var(--font-heading);font-size:12px;font-weight:700;line-height:1;
        letter-spacing:.28em;color:var(--accent);display:block;margin-bottom:14px;}

      .audience{padding:80px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);}
      .audience-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;}
      .audience-pill{display:inline-flex;align-items:center;gap:9px;padding:11px 20px;background:var(--surface);
        border:1px solid var(--border);border-radius:99px;font-size:14px;font-weight:500;
        color:var(--text-secondary);transition:border-color .18s, background .18s;}
      .audience-pill:hover{border-color:color-mix(in srgb, var(--accent) 48%, transparent);
        background:color-mix(in srgb, var(--accent) 8%, transparent);}
      .audience-pill .emoji{font-size:17px;}

      .why-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:16px;}
      @media (max-width:760px){.why-grid{grid-template-columns:1fr;}}
      .why-card{display:flex;gap:16px;border-radius:14px;}
      .why-card .check{flex-shrink:0;width:32px;height:32px;border-radius:8px;display:grid;place-items:center;
        font-family:var(--font-heading);font-size:12px;font-weight:700;color:var(--accent);
        background:color-mix(in srgb, var(--accent) 13%, transparent);
        border:1px solid color-mix(in srgb, var(--accent) 32%, transparent);}
      .why-card p{font-size:14px;color:var(--text-muted);}

      .final-cta{padding:112px 0;text-align:center;position:relative;overflow:hidden;}
      .final-cta::before{content:'';position:absolute;inset:0;pointer-events:none;opacity:.55;
        background:radial-gradient(52% 100% at 50% 50%, var(--glow), transparent 68%);}
      .final-cta .container{position:relative;z-index:1;}
      .final-cta p{max-width:520px;margin:0 auto 34px;color:var(--text-muted);}

      .reveal{opacity:0;transform:translateY(20px);
        transition:opacity .7s cubic-bezier(.22,1,.36,1), transform .7s cubic-bezier(.22,1,.36,1);}
      .reveal.visible{opacity:1;transform:none;}

      @media (prefers-reduced-motion: reduce){
        .rooms-ring,.room-face{transition:none !important;}
        .reveal{transform:none !important;}
      }
    """

    # ── the Mission Control replica, reused at two sizes ──────────────
    SIDEBAR = """
        <div class="app-side">
          <div class="as-user"><span class="av"></span>
            <span class="nm">Jordan Reyes<span>Reyes &amp; Co.</span></span>
            <span class="as-plan">STARTER</span></div>
          <div class="as-sec">Mission Control</div>
          <div class="as-item is-on"><span class="ic"></span>Dashboard</div>
          <div class="as-item"><span class="ic"></span>Operations</div>
          <div class="as-item"><span class="ic"></span>Notifications<span class="ct">15</span></div>
          <div class="as-sec">Workspace</div>
          <div class="as-item"><span class="ic"></span>Clients</div>
          <div class="as-item"><span class="ic"></span>Inbox</div>
          <div class="as-item"><span class="ic"></span>Schedule</div>
          <div class="as-item"><span class="ic"></span>Projects</div>
          <div class="as-sec">Finance</div>
          <div class="as-item"><span class="ic"></span>Invoices</div>
          <div class="as-item"><span class="ic"></span>Payments</div>
          <div class="as-item"><span class="ic"></span>Revenue</div>
          <div class="as-chief">Chief AI<span class="on">Online</span></div>
        </div>"""

    TOPBAR = """
      <div class="app-top">
        <span class="at-mark"></span>
        <span class="at-search">Ask the AI anything&hellip;<span class="kbd">&#8984;K</span></span>
        <span class="at-cta">+ Quick Create</span>
        <span class="at-urgent">Urgent</span>
        <span class="at-av"></span>
      </div>
      <div class="app-strip">
        <span class="biz">Reyes &amp; Co.</span>
        <span class="sp">Foundation Track 4/7</span>
        <span class="tab">Studio</span>
        <span class="tab on">Mission Control</span>
        <span class="tab">Solutionist System</span>
      </div>"""

    body = ("""
<section class="hero">
  <div class="container-xl">
    <div class="hero-copy">
      <span class="eyebrow reveal">For solo practitioners + small studios</span>
      <h1 class="reveal reveal-delay-1">Every problem<br>has a <span class="gradient-text">solution.</span></h1>
      <p class="lead reveal reveal-delay-2">One workspace that runs your whole practice &mdash; contacts, invoices, sessions, content, goals &mdash; commanded by an AI Chief of Staff that knows your business. Eight tools, replaced.</p>
      <div class="hero-ctas reveal reveal-delay-3">
        <a class="btn-primary" href="/get-started">Start Solving &rarr;</a>
        <a class="btn-secondary" href="#rooms">Look inside</a>
      </div>
      <div class="hero-meta reveal reveal-delay-3">
        <span class="stat-block"><span class="big">8</span><span>tools replaced by one workspace</span></span>
        <span class="hero-note">Currently in private beta &middot; Apply for access</span>
      </div>
    </div>

    <div class="hero-app reveal reveal-delay-3">
      <div class="hero-app-cap"><span class="dot"></span><b>Mission Control</b> &mdash; the first thing you see every day</div>
      <div class="app-scroll">
        <div class="app">"""
    + TOPBAR + """
          <div class="app-body">"""
    + SIDEBAR + """
            <div class="app-canvas">
              <div class="kpi-row">
                <div class="kpi"><span class="kpi-ico"></span><span class="k">Revenue &middot; this month</span><span class="v gold">$12,480</span><span class="f up">&#9650; 18% vs last mo</span></div>
                <div class="kpi"><span class="kpi-ico"></span><span class="k">Active clients</span><span class="v">17</span><span class="f">all in good standing</span></div>
                <div class="kpi"><span class="kpi-ico"></span><span class="k">Projects in progress</span><span class="v">3</span><span class="f">open board &rarr;</span></div>
                <div class="kpi"><span class="kpi-ico"></span><span class="k">Tasks today</span><span class="v">7</span><span class="f">2 due by 5:00</span></div>
                <div class="kpi"><span class="kpi-ico"></span><span class="k">Business health</span><span class="v up">61%</span><span class="f">steady</span></div>
              </div>

              <div class="hero-2col">
                <div class="brief">
                  <div class="brief-l">
                    <span class="date">Monday, July 27 &middot; Evening edition</span>
                    <span class="hi">Good evening,<br><b>Jordan</b> &#128075;</span>
                    <span class="cp">2 things need you today. Chief has them queued &mdash; one word clears the deck.</span>
                    <span class="brief-btns"><span class="ah-btn">Focus Mode &rarr;</span><span class="lnk">Read today&rsquo;s briefing</span></span>
                  </div>
                  <img class="brief-mark" src="/assets/mark.webp" alt="" width="128" height="128" loading="lazy">
                  <div class="chief">
                    <div class="chief-h">Chief AI<span class="on">Online</span></div>
                    <div class="chief-lead">I&rsquo;ve analyzed your day. Here&rsquo;s what I found:</div>
                    <div class="chief-f"><span class="sq warn"></span><span class="g">8 invoices overdue</span><span class="amt">$1,865</span></div>
                    <div class="chief-f"><span class="sq"></span><span class="g">2 drafts waiting for you</span><span class="tag">Needs you</span></div>
                    <div class="chief-f"><span class="sq ok"></span><span class="g">$12,480 collected this month</span></div>
                    <div class="chief-ask">Would you like me to handle these?</div>
                    <div class="chief-btns"><b>Yes, handle it</b><i>Review first</i></div>
                    <div class="chief-in">Ask Chief anything&hellip;<span class="go"></span></div>
                  </div>
                </div>

                <div class="pnl">
                  <div class="pnl-h">AI Suggestions<span class="ct">4</span></div>
                  <div class="r"><span class="bar red"></span><span class="nm g">INV-2026-010 overdue<span>Marcus Bell &middot; 38 days</span></span><span class="pill sent">Remind</span></div>
                  <div class="r"><span class="bar red"></span><span class="nm g">INV-2026-002 overdue<span>Grace Chapel &middot; 59 days</span></span><span class="pill sent">Remind</span></div>
                  <div class="r"><span class="bar amb"></span><span class="nm g">2 drafts pending review<span>from your last agent run</span></span><span class="pill draft">Open</span></div>
                  <div class="r"><span class="bar"></span><span class="nm g">Tia&rsquo;s card expires in 6 days<span>update payment method</span></span><span class="pill draft">Fix</span></div>
                </div>
              </div>

              <div class="qa-h">Quick Actions<span class="hint">one click, Chief handles the rest</span></div>
              <div class="qa">
                <i style="--c:#3B82F6">Draft Email</i><i style="--c:#EF4444">Chase Overdue</i>
                <i style="--c:#F59E0B">New Invoice</i><i style="--c:#22C55E">Add Contact</i>
                <i style="--c:#06B6D4">Book Session</i><i style="--c:#A855F7">Create a Post</i>
                <i style="--c:#7C3AED">Run Autopilot</i><i style="--c:#C9A84C">Set a Goal</i>
                <i style="--c:#64748B">Custom</i>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="ask">
  <div class="container-xl">
    <div class="ask-grid">
      <div class="ask-copy">
        <span class="sec-num reveal">01</span>
        <span class="eyebrow reveal">The Chief of Staff</span>
        <h2 class="reveal reveal-delay-1" style="margin-top:14px;">Ask once. The whole system <span class="gradient-text">moves.</span></h2>
        <p class="lead reveal reveal-delay-2">Chief isn&rsquo;t a chatbot bolted onto a dashboard. It reads your real contacts, invoices, calendar and goals every turn &mdash; then acts on them.</p>
        <ul class="ask-list reveal reveal-delay-3">
          <li><span class="n">1</span><span>You ask in plain words &mdash; typed or spoken. <b>No menus to learn.</b></span></li>
          <li><span class="n">2</span><span>Chief reads your live data, not a generic model&rsquo;s guess. <b>It knows your numbers.</b></span></li>
          <li><span class="n">3</span><span>It does the work &mdash; drafts, sends, books, files. <b>Autopilot runs while you sleep.</b></span></li>
        </ul>
      </div>
      <div class="reveal reveal-delay-2">
        <div class="app cx">
          <div class="app-top"><span class="at-mark"></span><span class="at-search">Chief of Staff<span class="kbd">&#8984;K</span></span><span class="at-av"></span></div>
          <div class="app-canvas">
            <div class="cx-b you">Who owes me money?</div>
            <div class="cx-b ai">Three invoices are past due &mdash; <b>$2,140</b> total. Marcus (18 days), Grace Chapel (11), Tia (4). Want me to send reminders?</div>
            <div class="cx-b you">Yes, and book Marcus for Thursday.</div>
            <div class="cx-b ai">Done. Reminders sent from your address, and Marcus is on Thursday at 2:00&nbsp;PM &mdash; invite went out.</div>
            <div class="cx-b act">&#10003; 3 reminders sent &middot; 1 session booked</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="rooms" id="rooms">
  <div class="container-xl">
    <div class="section-head reveal">
      <span class="sec-num">02</span>
      <span class="eyebrow">Look inside</span>
      <h2>Six rooms. <span class="gradient-text">One brain.</span></h2>
      <p>Each room is built for what happens in it &mdash; and they all share your contacts, your brand, and your Chief.</p>
    </div>

    <div class="rooms-tabs reveal" role="tablist" aria-label="Rooms">
      <button class="room-tab" role="tab" aria-selected="true"  data-i="0">Mission Control</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="1">Operate</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="2">Clients</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="3">The Studio</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="4">The Academy</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="5">Smart Sites</button>
    </div>

    <div class="rooms-viewport reveal" id="roomsViewport">
      <div class="rooms-ring" id="roomsRing">

        <div class="room-face is-active" style="--fa:0deg;" data-i="0"
             data-caption="Your whole practice on one screen — real numbers counting, today's schedule, and Chief telling you what actually needs you before you've had coffee.">
          <div class="app is-mini">
            <div class="app-body">""" + SIDEBAR + """
              <div class="app-canvas">
                <div class="ah-rule"></div>
                <div class="ah-row"><div><div class="ah-eyebrow">Mission Control</div>
                  <div class="ah-title">Good evening, Jordan</div>
                  <div class="ah-sub">2 things need you today &middot; Chief has them queued</div></div>
                  <span class="ah-btn">Focus Mode &rarr;</span></div>
                <div class="kpi-row">
                  <div class="kpi"><span class="k">Revenue</span><span class="v gold">$12,480</span><span class="f up">&#9650; 18%</span></div>
                  <div class="kpi"><span class="k">Clients</span><span class="v">17</span><span class="f">good standing</span></div>
                  <div class="kpi"><span class="k">Projects</span><span class="v">3</span><span class="f">in progress</span></div>
                  <div class="kpi"><span class="k">Tasks</span><span class="v">7</span><span class="f">2 due by 5:00</span></div>
                  <div class="kpi"><span class="k">Health</span><span class="v up">61%</span><span class="f">steady</span></div>
                </div>
                <div class="pnl" style="flex:1;">
                  <div class="pnl-h">Today<span class="ct">5</span></div>
                  <div class="r"><span class="bar"></span><span class="g nm">Discovery call &mdash; Marcus Bell<span>45 min &middot; video</span></span><span class="amt">9:00</span></div>
                  <div class="r"><span class="bar amb"></span><span class="g nm">Grace Chapel &mdash; planning session<span>on site</span></span><span class="amt">11:30</span></div>
                  <div class="r"><span class="bar red"></span><span class="g nm">Follow up: 3 overdue invoices<span>Chief drafted all three</span></span><span class="amt">2:00</span></div>
                  <div class="r"><span class="bar"></span><span class="g nm">Draft October newsletter<span>outline ready</span></span><span class="amt">4:15</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:60deg;" data-i="1"
             data-caption="Invoices, payments and bookkeeping that reconcile themselves. Chief chases what's late so you don't have to write another awkward email.">
          <div class="app is-mini">
            <div class="app-body">""" + SIDEBAR + """
              <div class="app-canvas">
                <div class="ah-rule"></div>
                <div class="ah-row"><div><div class="ah-eyebrow">Operate &middot; Invoices</div>
                  <div class="ah-title">Invoices</div>
                  <div class="ah-sub">$1,865.00 outstanding &middot; $12,480 paid &middot; 2 drafts</div></div>
                  <span class="ah-btn">+ New Invoice</span></div>
                <div class="age">
                  <div><div class="k">Current</div><div class="v">$0.00</div><div class="s">nothing here</div></div>
                  <div><div class="k">1&ndash;30 days</div><div class="v">$0.00</div><div class="s">nothing here</div></div>
                  <div class="hot"><div class="k">31&ndash;60 days</div><div class="v">$1,265</div><div class="s">7 past due</div></div>
                  <div class="hot"><div class="k">60+ days</div><div class="v">$600</div><div class="s">1 past due</div></div>
                  <div class="cta"><div class="k">Chase all overdue</div><div class="v">$1,865</div><div class="s">8 invoices</div></div>
                </div>
                <div class="pnl" style="flex:1;">
                  <div class="r"><span class="bar red"></span><span class="id">INV-2026-011</span><span class="g nm">Marcus Bell<span>1 item &middot; due Jun 26</span></span><span class="amt">$640</span><span class="pill due">Overdue</span></div>
                  <div class="r"><span class="bar red"></span><span class="id">INV-2026-010</span><span class="g nm">Grace Chapel<span>1 item &middot; due Jun 20</span></span><span class="amt">$1,200</span><span class="pill due">Overdue</span></div>
                  <div class="r"><span class="bar amb"></span><span class="id">INV-2026-009</span><span class="g nm">Northside Co-op<span>3 items &middot; due Jul 15</span></span><span class="amt">$2,400</span><span class="pill sent">Sent</span></div>
                  <div class="r"><span class="bar grn"></span><span class="id">INV-2026-008</span><span class="g nm">J. Okafor<span>paid via card</span></span><span class="amt">$850</span><span class="pill paid">Paid</span></div>
                  <div class="r"><span class="bar grn"></span><span class="id">INV-2026-007</span><span class="g nm">Rivera Studio<span>paid via check</span></span><span class="amt">$1,150</span><span class="pill paid">Paid</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:120deg;" data-i="2"
             data-caption="The client register — every person you serve, their standing, their history, and who's gone quiet. Update a contact once; every room sees it.">
          <div class="app is-mini">
            <div class="app-body">""" + SIDEBAR + """
              <div class="app-canvas">
                <div class="ah-rule"></div>
                <div class="ah-row"><div><div class="ah-eyebrow">The Client Register</div>
                  <div class="ah-title">Clients</div>
                  <div class="ah-sub">17 clients &middot; 17 in good standing</div></div>
                  <span class="ah-btn">+ Add</span></div>
                <div class="chips">
                  <span class="on">All Clients <b>17</b></span><span>New Leads &middot; 30d <b>3</b></span>
                  <span>Standing at Risk <b>0</b></span><span>Hot Leads <b>0</b></span>
                  <span>Not Contacted <b>13</b></span><span>Has Unpaid Invoice <b>2</b></span>
                </div>
                <div class="pnl" style="flex:1;">
                  <div class="r"><span class="av" style="background:#3B82F6">MB</span><span class="g nm">Marcus Bell<span>marcus@&hellip; &middot; 17d ago</span></span><span class="pill ok">Good standing</span></div>
                  <div class="r"><span class="av" style="background:#22C55E">GC</span><span class="g nm">Grace Chapel<span>hello@&hellip; &middot; 4d ago</span></span><span class="pill ok">Good standing</span></div>
                  <div class="r"><span class="av" style="background:#A855F7">TR</span><span class="g nm">Tia Randall<span>tia@&hellip; &middot; 63d silent</span></span><span class="pill sent">Check in</span></div>
                  <div class="r"><span class="av" style="background:#F59E0B">NC</span><span class="g nm">Northside Co-op<span>ops@&hellip; &middot; 18d ago</span></span><span class="pill ok">Good standing</span></div>
                  <div class="r"><span class="av" style="background:#EF4444">JO</span><span class="g nm">J. Okafor<span>j@&hellip; &middot; 2d ago</span></span><span class="pill ok">Good standing</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:180deg;" data-i="3"
             data-caption="Walk into a storefront built from your own brand. Try your identity on real artifacts — card, invoice, social post — and watch everything repaint as you edit.">
          <div class="app is-mini">
            <div class="app-body">""" + SIDEBAR + """
              <div class="app-canvas">
                <div class="ah-rule"></div>
                <div class="ah-row"><div><div class="ah-eyebrow">The Creative Studio &middot; Fitting Room</div>
                  <div class="ah-title">Brand Studio</div>
                  <div class="ah-sub">Warm &middot; Grounded &middot; Direct</div></div>
                  <span class="ah-btn">Apply to all</span></div>
                <div class="pnl">
                  <div class="pnl-h">Your brand DNA</div>
                  <div style="display:flex;align-items:center;gap:12px;">
                    <span class="sw"><i style="background:#2E7DFF"></i><i style="background:#22D3EE"></i><i style="background:#7C3AED"></i><i style="background:#0E1015"></i><i style="background:#F7F8FA"></i></span>
                    <span class="ah-sub" style="flex:1;">Inter Tight / Inter &middot; generous spacing &middot; 14px radius</span>
                  </div>
                </div>
                <div class="arts">
                  <div class="art"><span class="c">Business card</span><span><span class="m">R&amp;Co</span><span class="l"></span><span class="l s"></span></span></div>
                  <div class="art"><span class="c">Invoice</span><span><span class="m">$1,200</span><span class="l"></span><span class="l s"></span></span></div>
                  <div class="art"><span class="c">Social post</span><span><span class="m">Launch</span><span class="l"></span><span class="l s"></span></span></div>
                </div>
                <div class="r"><span class="bar"></span><span class="g">Change one color &mdash; every artifact repaints live</span><span class="pill live">Live</span></div>
              </div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:240deg;" data-i="4"
             data-caption="A dedicated Strategy Coach walks you through eight courses — discovery to launch plan — with a degree ring, sealed courses, and a diploma when you graduate.">
          <div class="app is-mini">
            <div class="app-body">""" + SIDEBAR + """
              <div class="app-canvas">
                <div class="ah-rule"></div>
                <div class="ah-eyebrow">The Academy &middot; Foundation Track</div>
                <div style="display:flex;align-items:center;gap:14px;">
                  <span class="ring"><i>62%</i></span>
                  <span style="flex:1;"><span class="ah-title" style="display:block;">5 of 8 courses sealed</span>
                  <span class="ah-sub">Diploma unlocks at 8 &middot; Strategy Coach standing by</span></span>
                </div>
                <div class="pnl" style="flex:1;">
                  <div class="r"><span class="bar grn"></span><span class="g nm">01 &middot; Who you serve<span>sealed Jun 2</span></span><span class="pill paid">Sealed</span></div>
                  <div class="r"><span class="bar grn"></span><span class="g nm">02 &middot; What you actually sell<span>sealed Jun 9</span></span><span class="pill paid">Sealed</span></div>
                  <div class="r"><span class="bar grn"></span><span class="g nm">03 &middot; Pricing with a spine<span>sealed Jun 21</span></span><span class="pill paid">Sealed</span></div>
                  <div class="r"><span class="bar amb"></span><span class="g nm">04 &middot; Your offer ladder<span>2 of 5 lessons</span></span><span class="pill sent">In progress</span></div>
                  <div class="r"><span class="bar"></span><span class="g nm">05 &middot; The launch plan<span>unlocks after 04</span></span><span class="pill draft">Locked</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:300deg;" data-i="5"
             data-caption="Your site is composed from your brand DNA and your own words — typography, spacing and motion reasoned from who you are, live on your own link in minutes.">
          <div class="app is-mini">
            <div class="app-body">""" + SIDEBAR + """
              <div class="app-canvas">
                <div class="ah-rule"></div>
                <div class="ah-row"><div><div class="ah-eyebrow">Smart Sites &middot; Composed, not templated</div>
                  <div class="ah-title">Your site</div>
                  <div class="ah-sub">counsel.mysolutionist.app &middot; published 6 min ago</div></div>
                  <span class="ah-btn">Publish</span></div>
                <div class="site">
                  <div class="band"><span class="t">Counsel that holds up.</span><span class="s">Family mediation &middot; Grand Rapids, MI</span></div>
                  <div class="cards"><i></i><i></i><i></i></div>
                </div>
                <div class="r"><span class="bar"></span><span class="g">Typography and spacing reasoned from your brand &mdash; not a theme</span><span class="pill live">Live</span></div>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>

    <div class="rooms-nav">
      <button class="rooms-arrow" id="roomPrev" aria-label="Previous room">&lsaquo;</button>
      <span class="rooms-count" id="roomCount">01 / 06</span>
      <button class="rooms-arrow" id="roomNext" aria-label="Next room">&rsaquo;</button>
    </div>
    <p class="room-caption" id="roomCaption">Your whole practice on one screen &mdash; real numbers counting, today&rsquo;s schedule, and Chief telling you what actually needs you before you&rsquo;ve had coffee.</p>

    <div style="text-align:center;margin-top:36px;" class="reveal">
      <a class="btn-secondary" href="/features">Explore every feature in depth &rarr;</a>
    </div>
  </div>
</section>

<section id="demo" class="demo-section">
  <div class="container">
    <div class="section-head reveal">
      <span class="sec-num">03</span>
      <span class="eyebrow">See it move</span>
      <h2>Fifty-five seconds, <span class="gradient-text">end to end.</span></h2>
      <p>The real system, scene by scene &mdash; Chief, Mission Control, getting paid, the Academy, the Studio, Autopilot.</p>
    </div>
    <div class="demo-frame reveal">
      <div class="demo-chrome"><span></span><span></span><span></span><em>The Solutionist System</em></div>
      <video class="demo-video" controls playsinline preload="metadata" poster="/assets/demo-poster.jpg">
        <source src="/assets/demo.mp4" type="video/mp4">
        Your browser doesn't support embedded video - <a href="/assets/demo.mp4">download the demo</a>.
      </video>
    </div>
  </div>
</section>

<section id="audience" class="audience">
  <div class="container">
    <div class="section-head" style="margin-bottom:34px;">
      <span class="sec-num reveal">04</span>
      <span class="eyebrow reveal">Who it&rsquo;s for</span>
      <h2 class="reveal reveal-delay-1" style="margin-top:14px;">Built for people who serve people.</h2>
    </div>
    <div class="audience-grid reveal reveal-delay-2">
      <span class="audience-pill"><span class="emoji">&#9962;</span> Pastors</span>
      <span class="audience-pill"><span class="emoji">&#10013;</span> Ministry Leaders</span>
      <span class="audience-pill"><span class="emoji">&#127919;</span> Coaches</span>
      <span class="audience-pill"><span class="emoji">&#128188;</span> Consultants</span>
      <span class="audience-pill"><span class="emoji">&#127912;</span> Creatives</span>
      <span class="audience-pill"><span class="emoji">&#129496;</span> Practitioners</span>
      <span class="audience-pill"><span class="emoji">&#127968;</span> Solo Studios</span>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="sec-num">05</span>
      <span class="eyebrow">Why Solutionist</span>
      <h2>One workspace replacing the chaos of eight.</h2>
    </div>
    <div class="why-grid">
      <div class="card why-card reveal"><div class="check">01</div>
        <div><h3>One brain, not eight</h3><p>Your CRM, invoicing, calendar, content and analytics all talk to each other. Update a contact once; every tool sees it.</p></div></div>
      <div class="card why-card reveal reveal-delay-1"><div class="check">02</div>
        <div><h3>AI that knows your business</h3><p>Chief reads your real data every turn &mdash; not a generic LLM. Asks for context once, then uses it forever.</p></div></div>
      <div class="card why-card reveal"><div class="check">03</div>
        <div><h3>Real-time, not weekly reports</h3><p>Every metric updates as data changes. No CSV exports, no waiting for someone to refresh.</p></div></div>
      <div class="card why-card reveal reveal-delay-1"><div class="check">04</div>
        <div><h3>Built for solo, not enterprise</h3><p>No teams, no seat math, no Slack-integration sprawl. Designed for one operator running their whole practice.</p></div></div>
    </div>
  </div>
</section>

<section class="final-cta">
  <div class="container">
    <span class="eyebrow reveal">Ready when you are</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">Run your practice <span class="gradient-text">from one place.</span></h2>
    <p class="reveal reveal-delay-2">Currently in private beta. Apply for access &mdash; we&rsquo;ll set you up and walk you through onboarding.</p>
    <a class="btn-primary reveal reveal-delay-3" href="/get-started">Apply for Access &rarr;</a>
  </div>
</section>
""")

    extra_scripts = """
<script>
(function () {
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var ring    = document.getElementById('roomsRing');
  var vp      = document.getElementById('roomsViewport');
  var caption = document.getElementById('roomCaption');
  var counter = document.getElementById('roomCount');
  if (!ring) return;

  var faces = [].slice.call(ring.querySelectorAll('.room-face'));
  var tabs  = [].slice.call(document.querySelectorAll('.room-tab'));
  var n = faces.length, cur = 0, timer = null, manual = false;
  var flat = function () {
    return window.matchMedia && window.matchMedia('(max-width: 1000px)').matches;
  };
  function pad(i) { return (i + 1 < 10 ? '0' : '') + (i + 1); }

  function paint() {
    for (var f = 0; f < n; f++) faces[f].classList.toggle('is-active', f === cur);
    for (var t = 0; t < tabs.length; t++) {
      tabs[t].setAttribute('aria-selected', String(Number(tabs[t].dataset.i) === cur));
    }
    if (caption) caption.textContent = faces[cur].dataset.caption || '';
    if (counter) counter.textContent = pad(cur) + ' / ' + pad(n - 1);
  }

  function show(i, fromUser) {
    cur = ((i % n) + n) % n;
    if (fromUser) { manual = true; if (timer) { clearInterval(timer); timer = null; } }
    /* NOT scrollIntoView: on a horizontally-scrolling container it still
       scrolls the PAGE vertically to reach the element, which yanked the
       whole document down to this section every time it advanced. */
    if (flat()) {
      var f = faces[cur];
      if (f && vp) {
        var target = f.offsetLeft - (vp.clientWidth - f.offsetWidth) / 2;
        if (vp.scrollTo) vp.scrollTo({ left: target, behavior: reduced ? 'auto' : 'smooth' });
        else vp.scrollLeft = target;
      }
    } else {
      ring.style.setProperty('--ry', (-60 * cur) + 'deg');
    }
    paint();
  }

  tabs.forEach(function (b) {
    b.addEventListener('click', function () { show(Number(b.dataset.i), true); });
  });
  var prev = document.getElementById('roomPrev');
  var next = document.getElementById('roomNext');
  if (prev) prev.addEventListener('click', function () { show(cur - 1, true); });
  if (next) next.addEventListener('click', function () { show(cur + 1, true); });

  if (vp) {
    vp.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowRight') { show(cur + 1, true); e.preventDefault(); }
      if (e.key === 'ArrowLeft')  { show(cur - 1, true); e.preventDefault(); }
    });
    var sT = null;
    vp.addEventListener('scroll', function () {
      if (!flat()) return;
      if (sT) clearTimeout(sT);
      sT = setTimeout(function () {
        var mid = vp.scrollLeft + vp.clientWidth / 2, best = 0, bestD = Infinity;
        for (var f = 0; f < n; f++) {
          var c = faces[f].offsetLeft + faces[f].offsetWidth / 2;
          var d = Math.abs(c - mid);
          if (d < bestD) { bestD = d; best = f; }
        }
        if (best !== cur) { cur = best; paint(); }
      }, 90);
    }, { passive: true });
  }

  if (!reduced) {
    var start = function () {
      /* never auto-advance the phone strip — it fights the reader's swipe */
      if (manual || timer || flat()) return;
      timer = setInterval(function () { show(cur + 1, false); }, 6500);
    };
    var stop = function () { if (timer) { clearInterval(timer); timer = null; } };
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (es) {
        es.forEach(function (e) { e.isIntersecting ? start() : stop(); });
      }, { threshold: 0.35 }).observe(vp || ring);
    } else { start(); }
    if (vp) {
      vp.addEventListener('mouseenter', stop);
      vp.addEventListener('mouseleave', start);
      vp.addEventListener('focusin', stop);
    }
  }
  show(0, false);
})();
</script>
"""
    return _render_shell(
        title="One workspace that runs your whole practice",
        description="The Solutionist System is one AI-powered workspace that replaces 8+ tools for solo practitioners. Contacts, invoices, sessions, content, goals, and a Chief of Staff that knows your business.",
        content_html=body, path="/", extra_css=extra_css, extra_scripts=extra_scripts,
    )


# ══════════════════════════════════════════════════════════════════════
# FEATURES — surface-by-surface deep dive
# ══════════════════════════════════════════════════════════════════════

def render_features() -> str:
    extra_css = REPLICA_KIT_CSS + FEATURES_FX_CSS + """
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
      <div class="fs-visual fsv reveal reveal-delay-1">
        <div class="app">
          <div class="app-top"><span class="at-mark"></span>
            <span class="at-search">Ask the AI anything&hellip;<span class="kbd">&#8984;K</span></span>
            <span class="at-cta">+ Quick Create</span><span class="at-av"></span></div>
          <div class="app-canvas">
            <div class="kpi-row" style="grid-template-columns:repeat(3,1fr);">
              <div class="kpi"><span class="k">Revenue &middot; this month</span>
                <span class="v gold fx-num" data-to="12480" data-prefix="$">$0</span><span class="f up">&#9650; 18%</span></div>
              <div class="kpi"><span class="k">Active clients</span>
                <span class="v fx-num" data-to="17">0</span><span class="f">good standing</span></div>
              <div class="kpi"><span class="k">Tasks today</span>
                <span class="v fx-num" data-to="7">0</span><span class="f">2 due by 5:00</span></div>
            </div>
            <div class="pnl fx-seq" style="flex:1;">
              <div class="pnl-h">Today<span class="ct">4</span></div>
              <div class="r"><span class="bar"></span><span class="g nm">Discovery call &mdash; Marcus Bell<span>45 min &middot; video</span></span><span class="amt">9:00</span></div>
              <div class="r"><span class="bar amb"></span><span class="g nm">Grace Chapel &mdash; planning session<span>on site</span></span><span class="amt">11:30</span></div>
              <div class="r"><span class="bar red"></span><span class="g nm">Follow up: 3 overdue invoices<span>Chief drafted all three</span></span><span class="amt">2:00</span></div>
            </div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>Your real numbers, counting as the data changes.</div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="fs-visual fsv reveal">
        <div class="app">
          <div class="app-top"><span class="at-mark"></span>
            <span class="at-search">counsel.mysolutionist.app</span>
            <span class="at-cta">Publish</span></div>
          <div class="app-canvas">
            <div class="ah-rule"></div>
            <div class="ah-eyebrow">Smart Sites &middot; composing</div>
            <div class="fx-compose">
              <div class="band" style="padding:15px 13px;display:flex;flex-direction:column;gap:5px;
                background:linear-gradient(135deg,rgba(46,125,255,.3),rgba(34,211,238,.12));">
                <span style="font-family:var(--font-heading);font-size:15px;font-weight:700;letter-spacing:-.02em;">Counsel that holds up.</span>
                <span style="font-size:9px;color:var(--ink-2);">Family mediation &middot; Grand Rapids, MI</span></div>
              <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:7px;padding:10px;">
                <span style="height:46px;border-radius:6px;background:var(--pane);border:1px solid var(--line);"></span>
                <span style="height:46px;border-radius:6px;background:var(--pane);border:1px solid var(--line);"></span>
                <span style="height:46px;border-radius:6px;background:var(--pane);border:1px solid var(--line);"></span></div>
              <div style="padding:0 10px 10px;"><span class="r"><span class="bar"></span>
                <span class="g">Book a consultation</span><span class="pill live">Wired</span></span></div>
            </div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>Composed from your brand DNA &mdash; section by section, not a template.</div>
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
      <div class="fs-visual fsv reveal reveal-delay-1">
        <div class="app">
          <div class="app-top"><span class="at-mark"></span>
            <span class="at-search">Operate &middot; Invoices</span><span class="at-cta">+ New Invoice</span></div>
          <div class="app-canvas">
            <div class="age" style="grid-template-columns:repeat(3,1fr);">
              <div><div class="k">Outstanding</div><div class="v">$1,865</div><div class="s">8 invoices</div></div>
              <div class="hot"><div class="k">Past due</div><div class="v">$1,265</div><div class="s">7 invoices</div></div>
              <div class="cta"><div class="k">Chase all overdue</div><div class="v">Send</div><div class="s">Chief drafts each one</div></div>
            </div>
            <div class="pnl fx-seq" style="flex:1;">
              <div class="r fx-settle"><span class="bar grn"></span><span class="id">INV-2026-009</span>
                <span class="g nm">Northside Co-op<span>3 items &middot; due Jul 15</span></span><span class="amt">$2,400</span>
                <span class="fx-flip"><span class="pill sent a">Sent</span><span class="pill paid b">Paid</span></span></div>
              <div class="r"><span class="bar red"></span><span class="id">INV-2026-011</span>
                <span class="g nm">Marcus Bell<span>1 item &middot; due Jun 26</span></span><span class="amt">$640</span><span class="pill due">Overdue</span></div>
              <div class="r"><span class="bar amb"></span><span class="id">INV-2026-010</span>
                <span class="g nm">Grace Chapel<span>reminder sent by Chief</span></span><span class="amt">$1,200</span><span class="pill sent">Sent</span></div>
              <div class="r"><span class="bar grn"></span><span class="id">INV-2026-008</span>
                <span class="g nm">J. Okafor<span>paid via card</span></span><span class="amt">$850</span><span class="pill paid">Paid</span></div>
            </div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>Payments land and reconcile themselves &mdash; no CSV, no chasing.</div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="fs-visual fsv reveal">
        <div class="app">
          <div class="app-top"><span class="at-mark"></span>
            <span class="at-search">Grow &middot; Revenue</span><span class="at-cta">Set a Goal</span></div>
          <div class="app-canvas">
            <div class="ah-rule"></div>
            <div class="ah-row"><div><div class="ah-eyebrow">Q4 goal</div>
              <div class="ah-title"><span class="fx-num" data-to="40000" data-prefix="$">$0</span></div>
              <div class="ah-sub">62% of target &middot; on pace</div></div>
              <span class="ring" style="width:52px;height:52px;"><i style="width:38px;height:38px;font-size:11px;">62%</i></span></div>
            <div class="pnl" style="flex:1;">
              <div class="fx-chart"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
              <div class="fx-axis"><span>Apr</span><span>May</span><span>Jun</span><span>Jul</span><span>Aug</span><span>Sep</span><span>Oct</span></div>
            </div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>Every metric updates as the data changes &mdash; not on a weekly report.</div>
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
      <div class="fs-visual fsv reveal">
        <div class="app cx" style="height:308px;">
          <div class="app-top"><span class="at-mark"></span>
            <span class="at-search">Chief of Staff</span><span class="at-av"></span></div>
          <div class="app-canvas">
            <div class="cx-b you">Who owes me money?</div>
            <div class="cx-b ai">Three invoices are past due &mdash; <b>$2,140</b> total. Want me to send reminders?</div>
            <div class="cx-b you">Yes, and book Marcus for Thursday.</div>
            <div class="cx-b act">&#10003; 3 reminders sent &middot; 1 session booked</div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>It reads your live data every turn &mdash; then does the work.</div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section">
  <div class="container">
    <div class="fs-grid">
      <div class="fs-visual fsv reveal">
        <div class="app">
          <div class="app-top"><span class="at-mark"></span>
            <span class="at-search">Grow &middot; Content Studio</span><span class="at-cta">Publish</span></div>
          <div class="app-canvas">
            <div class="pnl">
              <div class="pnl-h">Draft &middot; ready to send</div>
              <div style="font-size:10.5px;color:var(--ink-2);line-height:1.55;">
                &ldquo;Three seats left for the October intensive. If you&rsquo;ve been putting
                off the hard conversation about your numbers &mdash; this is the room for it.&rdquo;</div>
            </div>
            <div class="pnl" style="flex:1;justify-content:center;">
              <div class="fx-pub">
                <span class="ch fb">f</span><span class="wire"></span>
                <span style="font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);white-space:nowrap;">One post</span>
                <span class="wire"></span><span class="ch ig">&#9673;</span>
              </div>
              <div class="fx-axis" style="justify-content:center;gap:26px;">
                <span>Facebook &middot; scheduled 9:00</span><span>Instagram &middot; scheduled 9:00</span></div>
            </div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>Write once. Chief adapts and schedules it per channel.</div>
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
        content_html=body, path="/features", active="features", extra_css=extra_css, extra_scripts=FEATURES_SCRIPT,
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
          <span class="small">Founder &middot; The Solutionist System LLC</span>
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
      <h2>The Solutionist System LLC.</h2>
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
        description="Built by Kevin McCloud Jr. at The Solutionist System LLC. A Michigan-based company building one workspace for solo practitioners.",
        content_html=body, path="/about", active="about", extra_css=extra_css,
    )


# ══════════════════════════════════════════════════════════════════════
# GET STARTED — intake form (form POSTs to /api/leads via fetch)
# ══════════════════════════════════════════════════════════════════════

def render_download() -> str:
    """Arc 18 desktop page, expanded in Arc 25 into the "Get the App"
    surface: Android (direct APK + Play Store when live), iPhone (PWA
    install steps), Desktop (Tauri coming-soon until DESKTOP_RELEASES_URL
    is set). Android links are env-driven — see ANDROID_APK_URL above."""
    # — Android card —
    if PLAY_STORE_URL:
        play_block = f"""<a class="nav-cta" style="display:inline-block;font-size:14px;padding:11px 20px;" href="{_html.escape(PLAY_STORE_URL)}">Get it on Google Play</a>"""
    else:
        play_block = """<span class="dl-soon">Play Store &mdash; coming soon</span>"""
    if ANDROID_APK_URL:
        android_block = f"""
          <a class="nav-cta" style="display:inline-block;font-size:14px;padding:11px 20px;" href="{_html.escape(ANDROID_APK_URL)}">Download the Android app (APK)</a>
          <div style="margin-top:14px;">{play_block}</div>
          <details class="dl-steps">
            <summary>How to install the APK</summary>
            <ol>
              <li>Tap the download button above and open the downloaded file.</li>
              <li>If prompted, allow your browser to install unknown apps
                  (Settings &rarr; Install unknown apps &rarr; allow).</li>
              <li>Tap Install. Solutionist appears on your home screen.</li>
            </ol>
          </details>"""
    else:
        android_block = f"""
          <span class="dl-soon">Coming soon</span>
          <p class="dl-note">The Android app is in final packaging. Until it lands,
             install from the browser: open <strong>{APP_URL.replace("https://", "")}</strong>
             in Chrome &rarr; menu (&#8942;) &rarr; <strong>Add to Home screen</strong>.</p>
          <div style="margin-top:14px;">{play_block}</div>"""
    # — Desktop card —
    if DESKTOP_RELEASES_URL:
        desktop_block = f"""
          <a class="nav-cta" style="display:inline-block;font-size:14px;padding:11px 20px;" href="{_html.escape(DESKTOP_RELEASES_URL)}">Download for Windows &amp; macOS</a>"""
    else:
        desktop_block = f"""
          <span class="dl-soon">Coming soon</span>
          <p class="dl-note">The desktop app is in final packaging. Everything it does,
             the web app does today &mdash; same account, same data, same Chief.</p>"""
    content = f"""
<section class="hero" style="padding-top:96px;padding-bottom:40px;text-align:center;">
  <div class="container">
    <h1 class="reveal">Solutionist, wherever you work.</h1>
    <p class="reveal" style="color:var(--text-muted);max-width:560px;margin:18px auto 0;">
      One account, one system &mdash; phone, tablet, and desktop.
      The web app at <a href="{APP_URL}" style="color:var(--accent);">{APP_URL.replace("https://", "")}</a> works everywhere today.
    </p>
  </div>
</section>
<section style="padding:0 0 80px;">
  <div class="container">
    <div class="dl-grid">
      <div class="company-card reveal">
        <h3>Android</h3>
        {android_block}
      </div>
      <div class="company-card reveal reveal-delay-1">
        <h3>iPhone &amp; iPad</h3>
        <p class="dl-note">Installs as an app straight from Safari &mdash; no App Store needed.</p>
        <details class="dl-steps" open>
          <summary>Install steps</summary>
          <ol>
            <li>Open <strong>{APP_URL.replace("https://", "")}</strong> in Safari.</li>
            <li>Tap the Share button, then <strong>Add to Home Screen</strong>.</li>
            <li>Tap Add. Solutionist appears on your home screen.</li>
          </ol>
        </details>
      </div>
      <div class="company-card reveal reveal-delay-2">
        <h3>Windows &amp; macOS</h3>
        {desktop_block}
      </div>
    </div>
    <p class="reveal" style="text-align:center;margin-top:34px;">
      <a class="nav-cta" style="display:inline-block;font-size:15px;padding:12px 24px;" href="{APP_URL}">Use the web app now</a>
    </p>
  </div>
</section>"""
    return _render_shell(
        title="Get the App",
        description="Get The Solutionist System on Android, iPhone, Windows, and macOS — one account, one system, every device.",
        content_html=content,
        path="/download",
        active="download",
        extra_css="""
  .dl-soon{display:inline-block;margin-top:4px;padding:6px 16px;border:1px solid var(--border-strong);border-radius:99px;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text-muted);}
  .dl-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:8px;}
  @media (max-width: 880px){.dl-grid{grid-template-columns:1fr;}}
  .dl-grid .company-card h3{margin-bottom:12px;}
  .dl-note{color:var(--text-secondary);font-size:13.5px;line-height:1.55;margin:8px 0 0;}
  .dl-steps{margin-top:14px;text-align:left;}
  .dl-steps summary{cursor:pointer;font-size:13px;font-weight:700;color:var(--text-muted);letter-spacing:0.4px;}
  .dl-steps ol{margin:10px 0 0;padding-left:20px;color:var(--text-secondary);font-size:13.5px;line-height:1.6;display:flex;flex-direction:column;gap:6px;}
""",
    )


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
<h2 style="color:#1D63E6;margin-bottom:18px;">New beta application</h2>
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
<h2 style="color:#1D63E6;margin-bottom:14px;">Thanks for applying, {_html.escape(name.split()[0])}.</h2>
<p style="font-size:15px;color:#333;">We got your application for the Solutionist System private beta. Here's what happens next:</p>
<ol style="font-size:14px;color:#444;padding-left:20px;margin:18px 0;">
<li style="margin-bottom:8px;"><strong>Kevin will reach out within 24 hours</strong> — usually faster. He'll ask a few questions to make sure we're a fit for what you're building.</li>
<li style="margin-bottom:8px;"><strong>If it's a fit, we'll set up personal onboarding</strong> — about 30 minutes, we walk you through the workspace and get you running.</li>
<li><strong>You'll get grandfathered pricing</strong> when we launch publicly.</li>
</ol>
<p style="font-size:14px;color:#666;margin-top:18px;">Questions before then? Just reply to this email — it goes straight to Kevin.</p>
<p style="margin-top:24px;font-size:14px;color:#444;">Talk soon,<br><strong>Kevin McCloud Jr.</strong><br>Founder, The Solutionist System LLC</p>
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
