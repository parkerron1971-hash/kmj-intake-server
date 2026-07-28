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
    /* ── "Ember & Ink" (2026-07-27). The violet→cyan dark-SaaS palette
       had become the house style of every AI product on the internet;
       this is warm near-black + molten brass instead. Bone text rather
       than #fff, ember as the heat accent, and teal held in reserve for
       data only — so the S-mark's magenta/cyan reads as a jewel against
       metal instead of competing with a matching gradient. ── */
    --bg: #0C0A0A;
    --bg-2: #16110E;
    --surface: rgba(245,239,230,0.045);
    --surface-2: rgba(245,239,230,0.075);
    --border: rgba(245,239,230,0.10);
    --border-strong: rgba(245,239,230,0.20);
    --text-primary: #F5EFE6;
    --text-secondary: #D9CFC1;
    --text-muted: #A89C8C;
    --text-dim: #7A7065;
    --accent: #E6A24B;
    --accent-2: #C9822F;
    --hot: #FF6B35;
    --ink-on-accent: #1A1206;
    --info: #4ECDC4;
    --success: #7BC49A;
    --warning: #E6A24B;
    --danger: #E5533D;
    --glow: rgba(230, 162, 75, 0.30);
    --glow-ember: rgba(255, 107, 53, 0.26);
    --glow-cyan: rgba(255, 107, 53, 0.22);
    --font-heading: 'Fraunces', Georgia, 'Times New Roman', serif;
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
  .gradient-text{background:linear-gradient(120deg, var(--accent), var(--hot));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;}
  h1,h2,h3{font-family:var(--font-heading);font-optical-sizing:auto;letter-spacing:-0.01em;line-height:1.08;}
  h1{font-size:clamp(40px, 6vw, 64px);font-weight:600;}
  h2{font-size:clamp(30px, 4.2vw, 44px);font-weight:600;margin-bottom:14px;}
  h3{font-size:18px;font-weight:600;color:var(--text-primary);margin-bottom:6px;}
  p{color:var(--text-secondary);font-size:16px;}
  .lead{font-size:18px;color:var(--text-muted);line-height:1.65;}

  /* ─── nav ─── */
  .nav{position:sticky;top:0;z-index:50;background:rgba(12,10,10,0.82);backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);border-bottom:1px solid var(--border);}
  .nav-inner{display:flex;align-items:center;justify-content:space-between;padding:14px 28px;max-width:1140px;margin:0 auto;}
  .brand{font-family:var(--font-heading);font-size:17px;font-weight:600;color:var(--text-primary);letter-spacing:-0.01em;display:inline-flex;align-items:center;gap:10px;}
  .brand .logo{height:32px;width:auto;display:block;filter:drop-shadow(0 0 8px var(--glow));}
  .footer .brand .logo{height:28px;}
  .brand .dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--hot));box-shadow:0 0 8px var(--glow);}
  .brand-text{display:inline-block;}
  @media (max-width: 540px){.brand-text{display:none;}}
  .nav-links{display:flex;align-items:center;gap:22px;font-size:13px;font-weight:500;}
  .nav-links a{color:var(--text-muted);transition:color 0.15s;position:relative;}
  .nav-links a:hover, .nav-links a.is-active{color:var(--text-primary);}
  .nav-links a.is-active::after{content:'';position:absolute;left:0;right:0;bottom:-18px;height:2px;background:linear-gradient(90deg, var(--accent), var(--hot));border-radius:2px;}
  .nav-cta{padding:8px 16px;background:var(--accent);color:var(--ink-on-accent) !important;border-radius:8px;font-weight:700;font-size:13px;box-shadow:0 2px 14px color-mix(in srgb, var(--accent) 30%, transparent);transition:transform 0.15s, box-shadow 0.15s, background 0.15s;}
  .nav-cta:hover{transform:translateY(-1px);background:#F0B265;box-shadow:0 4px 20px color-mix(in srgb, var(--accent) 45%, transparent);}
  .nav-cta.is-active::after{display:none;}
  .nav-login{padding:7px 15px;border:1px solid var(--border-strong);border-radius:8px;color:var(--text-primary) !important;font-weight:600;font-size:13px;transition:border-color 0.15s, background 0.15s;}
  .nav-login:hover{border-color:var(--accent);background:var(--surface);}
  /* 900, not 760: at ~768 every link still showed, which wrapped both the
     brand and "Get the App" onto extra lines and buckled the whole bar. */
  @media (max-width: 900px){.nav-links{gap:12px;font-size:12px;} .nav-links a:not(.nav-cta):not(.nav-login){display:none;}
    .brand-text{white-space:nowrap;}}

  /* ─── buttons ─── */
  .btn-primary{display:inline-flex;align-items:center;gap:8px;padding:14px 28px;background:var(--accent);color:var(--ink-on-accent);font-weight:700;font-size:14px;letter-spacing:.01em;border-radius:10px;border:none;cursor:pointer;box-shadow:0 6px 26px color-mix(in srgb, var(--accent) 32%, transparent), inset 0 1px 0 rgba(255,255,255,.28);transition:transform 0.15s, box-shadow 0.15s, background 0.15s;font-family:inherit;}
  .btn-primary:hover{transform:translateY(-2px);background:#F0B265;box-shadow:0 10px 34px color-mix(in srgb, var(--accent) 46%, transparent), inset 0 1px 0 rgba(255,255,255,.34);}
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
  .stat-block .big{font-family:var(--font-heading);font-size:24px;font-weight:600;color:transparent;background:linear-gradient(120deg, var(--accent), var(--hot));-webkit-background-clip:text;background-clip:text;line-height:1;}
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
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400..700&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
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

def render_home() -> str:
    # ── "Ember & Ink" 3D home (Kevin's ruling 2026-07-27: the violet→cyan
    #    dark-SaaS palette was everywhere, and the old page DESCRIBED the
    #    system without ever showing it). Two changes carry the rebuild:
    #      1. a real CSS-3D scene graph (perspective + preserve-3d), not
    #         flat divs with a spin — the deck is an object you can tilt;
    #      2. the rooms are rendered as live HTML mockups of the actual
    #         product on a 3D carousel, so a visitor SEES Mission Control,
    #         Chief, Operate, the Studio, the Academy and Smart Sites
    #         without clicking a video.
    #    Zero dependencies — no three.js, no build step. Everything below
    #    degrades to flat layout under prefers-reduced-motion and to a
    #    scroll-snap strip under 900px.
    extra_css = """
      /* ══ layout: break the 1140 cage on the cinematic sections ══ */
      .container-xl{max-width:1340px;margin:0 auto;padding:0 32px;}
      @media (max-width:640px){.container-xl{padding:0 20px;}}

      /* ══════════════════════════════════════════════════════════════
         01 — THE COMMAND DECK (hero)
         A true 3D scene: .deck-stage owns the perspective, .deck-tilt
         takes pointer parallax, .deck holds the world rotation, and the
         chips ride two orbital rings inside it. Each chip billboards
         (counter-rotates) so its label always faces the camera while its
         POSITION stays in 3D — that is what separates this from a flat
         ring of absolutely-positioned labels.
         ══════════════════════════════════════════════════════════════ */
      .hero{position:relative;padding:64px 0 92px;overflow:hidden;}
      .hero::before{content:'';position:absolute;inset:-120px 0 auto;height:620px;pointer-events:none;
        background:radial-gradient(58% 78% at 50% 0%, var(--glow), transparent 72%);}
      /* Ember haze low and warm — the light source sits under the deck */
      .hero::after{content:'';position:absolute;left:50%;bottom:-180px;width:900px;height:420px;
        transform:translateX(-50%);pointer-events:none;opacity:.5;
        background:radial-gradient(50% 50% at 50% 50%, var(--glow-ember), transparent 70%);filter:blur(20px);}
      .hero .container-xl{position:relative;z-index:1;}
      .hero-grid{display:grid;grid-template-columns:1.02fr .98fr;gap:40px;align-items:center;}
      .hero h1{margin:20px 0 22px;max-width:660px;font-size:clamp(42px,5.6vw,72px);line-height:1.02;}
      .hero .lead{max-width:540px;margin:0 0 34px;}
      .hero-ctas{display:flex;flex-wrap:wrap;gap:12px;}
      .hero-note{margin-top:22px;font-size:12px;color:var(--text-dim);letter-spacing:.02em;}
      .hero-rule{width:64px;height:2px;margin:26px 0 0;border-radius:2px;
        background:linear-gradient(90deg, var(--accent), transparent);}

      /* Perspective is deliberately long. At 1250px a 536px-wide ring
         projects with so much divergence that concentric orbits stop
         reading as concentric; ~2100 keeps real depth (chips still scale
         front-to-back) while the rings stay legibly co-axial. */
      .deck-stage{position:relative;height:540px;perspective:2100px;perspective-origin:50% 50%;}
      .deck-tilt{position:absolute;inset:0;transform-style:preserve-3d;
        transform:rotateX(var(--py,0deg)) rotateY(var(--px,0deg));
        transition:transform .5s cubic-bezier(.22,1,.36,1);will-change:transform;}
      .deck{position:absolute;inset:0;transform-style:preserve-3d;
        transform:rotateX(var(--tilt)) translateY(10px);--tilt:57deg;}

      /* the orbital planes — circles lying IN the deck, so perspective
         turns them into ellipses for free. They have to carry real
         weight: at 26% on a #0C0A0A ground the strokes vanished and the
         chips read as scattered labels instead of an orbit. */
      .deck-plane{position:absolute;top:50%;left:50%;border-radius:50%;
        border:1px solid color-mix(in srgb, var(--accent) 52%, transparent);
        transform:translate(-50%,-50%);pointer-events:none;
        box-shadow:0 0 26px color-mix(in srgb, var(--accent) 14%, transparent),
                   inset 0 0 34px color-mix(in srgb, var(--accent) 7%, transparent);}
      .deck-plane.pl1{width:calc(var(--r1) * 2);height:calc(var(--r1) * 2);
        border-style:dashed;border-color:color-mix(in srgb, var(--accent) 40%, transparent);}
      /* a brighter leading arc so the plane itself reads as turning */
      .deck-plane.pl2{width:calc(var(--r2) * 2);height:calc(var(--r2) * 2);
        border-width:1.5px;border-top-color:color-mix(in srgb, var(--accent) 92%, #fff);
        animation:deckPlaneSpin 28s linear infinite;}
      .deck-plane.pl3{width:calc(var(--r1) * 1.42);height:calc(var(--r1) * 1.42);
        border-color:color-mix(in srgb, var(--hot) 34%, transparent);
        border-top-color:color-mix(in srgb, var(--hot) 80%, transparent);
        animation:deckPlaneSpin 40s linear infinite reverse;}
      /* NB: the plane spin MUST re-state translate(-50%,-50%) — an
         animated `transform` replaces the base one outright, and without
         the centering here each ring drifts half its own width off-axis
         (which is exactly what it looked like: scattered ovals). rotateZ,
         not rotateY: the plane already lies in the tilted deck, so Z-spin
         travels the bright arc around the rim without tipping it out. */
      @keyframes deckPlaneSpin{
        from{transform:translate(-50%,-50%) rotateZ(0deg);}
        to  {transform:translate(-50%,-50%) rotateZ(360deg);}}
      /* the deck floor — a warm pool of light the rings sit on */
      .deck-floor{position:absolute;top:50%;left:50%;width:calc(var(--r1) * 2.3);height:calc(var(--r1) * 2.3);
        transform:translate(-50%,-50%);border-radius:50%;pointer-events:none;
        background:radial-gradient(circle, color-mix(in srgb, var(--accent) 22%, transparent), transparent 66%);
        filter:blur(16px);}
      /* the anchor: a cast shadow lying IN the deck, directly under the
         core. Without it the mark reads as detached from the rings
         rather than hovering above them. */
      .deck-shadow{position:absolute;top:50%;left:50%;width:calc(var(--r2) * 1.25);height:calc(var(--r2) * 1.25);
        transform:translate(-50%,-50%);border-radius:50%;pointer-events:none;
        background:radial-gradient(circle, rgba(0,0,0,.85) 0%, rgba(0,0,0,.5) 44%, transparent 70%);
        filter:blur(10px);}
      /* the pedestal: a bright rim right under the core. A black shadow on
         a #0C0A0A ground is nearly invisible — the anchor has to be LIGHT,
         so the mark reads as standing over the deck rather than drifting
         above it with nothing beneath. */
      .deck-pedestal{position:absolute;top:50%;left:50%;width:calc(var(--r2) * 0.94);height:calc(var(--r2) * 0.94);
        transform:translate(-50%,-50%);border-radius:50%;pointer-events:none;
        border:1px solid color-mix(in srgb, var(--accent) 68%, transparent);
        box-shadow:0 0 22px color-mix(in srgb, var(--accent) 28%, transparent),
                   inset 0 0 26px color-mix(in srgb, var(--accent) 15%, transparent);}

      /* ring 1 (outer, 5 chips) + ring 2 (inner, 4 chips, counter-spin) */
      .deck-ring{position:absolute;inset:0;transform-style:preserve-3d;}
      .deck-ring.rA{animation:deckSpin 46s linear infinite;}
      /* Ring B rides a second shell ~44px above the deck (again: local Y
         is the normal). Two shells at different heights stop A's and B's
         labels from colliding as they cross — they used to overlap head-on
         whenever the two rings lined up. The lift has to live INSIDE the
         keyframe, since an animated transform replaces the base one. */
      .deck-ring.rB{animation:deckSpinLift 34s linear infinite reverse;}
      @keyframes deckSpin{to{transform:rotateY(360deg);}}
      @keyframes deckSpinLift{
        from{transform:translateY(-44px) rotateY(0deg);}
        to  {transform:translateY(-44px) rotateY(360deg);}}

      .chip-slot{position:absolute;top:50%;left:50%;transform-style:preserve-3d;
        transform:translate(-50%,-50%) rotateY(var(--a)) translateZ(var(--r));}
      /* billboard: undoes the ring's spin at exactly the same rate, so the
         label never turns edge-on. Paired durations with .rA / .rB. */
      .chip-bb{transform-style:preserve-3d;}
      .rA .chip-bb{animation:deckSpin 46s linear infinite reverse;}
      .rB .chip-bb{animation:deckSpin 34s linear infinite;}
      /* The node stays IN the orbital plane (no X counter-rotation), so it
         reads as a body actually riding the ring; the label then floats
         above it. Without this the billboarded labels looked like they
         were hovering off the rings by accident. */
      .chip-node{position:absolute;top:50%;left:50%;width:13px;height:13px;margin:-6.5px 0 0 -6.5px;
        border-radius:50%;background:var(--accent);
        box-shadow:0 0 12px color-mix(in srgb, var(--accent) 85%, transparent),
                   0 0 3px color-mix(in srgb, #fff 60%, transparent);}
      .is-hot-slot .chip-node{background:var(--hot);
        box-shadow:0 0 12px color-mix(in srgb, var(--hot) 85%, transparent),
                   0 0 3px color-mix(in srgb, #fff 55%, transparent);}
      .deck-chip{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;
        padding:9px 14px;border-radius:11px;font-size:12.5px;font-weight:600;letter-spacing:.01em;
        color:var(--text-secondary);background:color-mix(in srgb, var(--bg-2) 82%, transparent);
        border:1px solid color-mix(in srgb, var(--accent) 26%, var(--border));
        backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);
        box-shadow:0 10px 30px rgba(0,0,0,.55), 0 0 0 1px rgba(0,0,0,.2);
        /* undo the slot's own Y rotation + the deck's world tilt, then lift
           the label clear of its node. The trailing translateY runs in the
           already-counter-rotated (screen-aligned) frame, so it moves
           straight up on screen regardless of where the chip is in orbit. */
        transform:rotateY(calc(-1 * var(--a))) rotateX(calc(-1 * var(--tilt))) translateY(-27px);}
      .deck-chip .ci{font-style:normal;font-size:13px;line-height:1;
        color:var(--accent);filter:drop-shadow(0 0 6px color-mix(in srgb, var(--accent) 60%, transparent));}
      .deck-chip.is-hot{border-color:color-mix(in srgb, var(--hot) 40%, transparent);}
      .deck-chip.is-hot .ci{color:var(--hot);filter:drop-shadow(0 0 6px color-mix(in srgb, var(--hot) 60%, transparent));}

      /* the core — stands upright at the middle of the discs, lifted off
         the floor along the deck normal, then counter-tilted to face us */
      .deck-core{position:absolute;top:50%;left:50%;width:190px;height:190px;
        transform-style:preserve-3d;
        /* translateY, NOT translateZ. The chip rings trace circles in the
           local XZ plane, so the disc's normal is local Y — a translateZ
           here slid the mark backwards ACROSS the deck (which merely looks
           like "up" once tilted) and left it hovering off its own pedestal.
           Negative Y is the true lift off the deck. */
        transform:translate(-50%,-50%) translateY(-62px) rotateX(calc(-1 * var(--tilt)));}
      .core-halo{position:absolute;inset:6px;border-radius:50%;filter:blur(20px);
        background:radial-gradient(circle, color-mix(in srgb, var(--accent) 46%, transparent),
                                            color-mix(in srgb, var(--hot) 16%, transparent) 55%, transparent 72%);
        animation:corePulse 4.2s ease-in-out infinite;}
      .core-logo{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
        animation:coreFloat 6s ease-in-out infinite;}
      .core-logo img{width:146px;height:146px;display:block;
        filter:drop-shadow(0 0 34px color-mix(in srgb, var(--accent) 48%, transparent))
               drop-shadow(0 18px 34px rgba(0,0,0,.7));}
      @keyframes coreFloat{0%,100%{transform:translateY(0);}50%{transform:translateY(-13px);}}
      @keyframes corePulse{0%,100%{transform:scale(1);opacity:.9;}50%{transform:scale(1.08);opacity:1;}}

      /* desktop ring radii; shrunk on smaller stages via the same vars */
      .deck{--r1:268px;--r2:180px;}
      @media (max-width:1180px){.deck{--r1:218px;--r2:146px;}
        .deck-core{width:160px;height:160px;} .core-logo img{width:124px;height:124px;}}
      @media (max-width:900px){
        .hero{padding:44px 0 72px;}
        .hero-grid{grid-template-columns:1fr;text-align:center;gap:20px;}
        .hero h1{margin:18px auto 20px;} .hero .lead{margin:0 auto 30px;}
        .hero-ctas{justify-content:center;} .hero-copy .stat-block{margin:0 auto;}
        .hero-rule{margin:26px auto 0;}
        .deck-stage{height:400px;}
        .deck{--r1:156px;--r2:102px;--tilt:54deg;}
        .deck-core{width:126px;height:126px;} .core-logo img{width:104px;height:104px;}
        .deck-chip{font-size:11px;padding:7px 11px;gap:6px;}
      }
      /* Phones can't carry nine labels on two rings — at ~390px the inner
         ring's chips collided with the outer ring's on every pass. Drop
         ring B's LABELS only: its nodes and orbit still read as a second
         shell, and those four modules are all named further down the page. */
      @media (max-width:560px){
        .rB .deck-chip{display:none;}
        .deck-chip{font-size:10.5px;padding:6px 10px;}
      }
      @media (max-width:420px){
        .deck-stage{height:330px;} .deck{--r1:126px;--r2:80px;}
        .deck-core{width:104px;height:104px;} .core-logo img{width:86px;height:86px;}
        .deck-chip{font-size:10px;padding:5px 9px;}
      }

      /* ══════════════════════════════════════════════════════════════
         02 — ASK, AND IT MOVES (Chief, on a tilted pane)
         ══════════════════════════════════════════════════════════════ */
      .ask{position:relative;padding:96px 0;border-top:1px solid var(--border);overflow:hidden;}
      .ask::before{content:'';position:absolute;inset:0;pointer-events:none;opacity:.5;
        background:radial-gradient(46% 60% at 78% 40%, var(--glow), transparent 70%);}
      .ask .container-xl{position:relative;z-index:1;}
      .ask-grid{display:grid;grid-template-columns:.86fr 1.14fr;gap:56px;align-items:center;}
      @media (max-width:980px){.ask-grid{grid-template-columns:1fr;gap:36px;}}
      .ask-copy h2{margin-bottom:16px;}
      .ask-list{list-style:none;margin-top:26px;display:grid;gap:14px;}
      .ask-list li{display:flex;gap:13px;align-items:flex-start;font-size:14.5px;color:var(--text-muted);line-height:1.55;}
      .ask-list .n{flex-shrink:0;width:24px;height:24px;border-radius:7px;display:grid;place-items:center;
        font-family:var(--font-heading);font-size:12px;font-weight:600;color:var(--accent);
        background:color-mix(in srgb, var(--accent) 12%, transparent);
        border:1px solid color-mix(in srgb, var(--accent) 30%, transparent);}
      .ask-list b{color:var(--text-primary);font-weight:600;}

      .pane-stage{perspective:1500px;}
      .pane{transform-style:preserve-3d;transform:rotateY(-13deg) rotateX(5deg) translateZ(0);
        transition:transform .7s cubic-bezier(.22,1,.36,1);}
      .pane-stage:hover .pane{transform:rotateY(-6deg) rotateX(2deg) translateZ(24px);}
      @media (max-width:980px){.pane{transform:rotateY(0deg) rotateX(0deg);}}

      /* ══════════════════════════════════════════════════════════════
         03 — THE ROOMS (3D carousel of real product surfaces)
         ══════════════════════════════════════════════════════════════ */
      .rooms{padding:96px 0 84px;border-top:1px solid var(--border);position:relative;overflow:hidden;}
      .rooms::before{content:'';position:absolute;inset:auto 0 -10% 0;height:420px;pointer-events:none;opacity:.5;
        background:radial-gradient(50% 60% at 50% 100%, var(--glow-ember), transparent 70%);}
      .rooms .container-xl{position:relative;z-index:1;}
      .rooms-tabs{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin:0 auto 40px;max-width:900px;}
      .room-tab{padding:8px 15px;border-radius:99px;font-size:12.5px;font-weight:600;letter-spacing:.01em;
        color:var(--text-muted);background:transparent;border:1px solid var(--border);
        cursor:pointer;font-family:inherit;transition:color .18s, border-color .18s, background .18s;}
      .room-tab:hover{color:var(--text-primary);border-color:var(--border-strong);}
      .room-tab[aria-selected="true"]{color:var(--ink-on-accent);background:var(--accent);
        border-color:var(--accent);box-shadow:0 6px 20px color-mix(in srgb, var(--accent) 30%, transparent);}

      /* 6 faces at 60° apart: the ring radius that just clears them is
         (width/2)/tan(30°) ≈ width × 0.866. The ring is then pushed back
         by the same amount so the front face lands at z=0 (scale 1:1). */
      .rooms-viewport{position:relative;height:412px;perspective:1600px;perspective-origin:50% 45%;}
      .rooms-ring{position:absolute;inset:0;transform-style:preserve-3d;
        transform:translateZ(-620px) rotateY(var(--ry,0deg));
        transition:transform .85s cubic-bezier(.4,.9,.25,1);will-change:transform;}
      .room-face{position:absolute;top:50%;left:50%;width:700px;height:356px;margin:-178px 0 0 -350px;
        transform:rotateY(var(--fa)) translateZ(620px);
        opacity:.26;filter:blur(3px) saturate(.55);pointer-events:none;
        transition:opacity .5s ease, filter .5s ease;}
      .room-face.is-active{opacity:1;filter:none;pointer-events:auto;}
      .room-face .mock{height:100%;}

      .rooms-nav{display:flex;align-items:center;justify-content:center;gap:16px;margin-top:34px;}
      .rooms-arrow{width:42px;height:42px;border-radius:50%;display:grid;place-items:center;cursor:pointer;
        background:var(--surface);border:1px solid var(--border-strong);color:var(--text-secondary);
        font-size:16px;font-family:inherit;transition:background .18s, border-color .18s, color .18s;}
      .rooms-arrow:hover{background:var(--surface-2);border-color:var(--accent);color:var(--accent);}
      .rooms-count{font-family:var(--font-heading);font-size:13px;color:var(--text-dim);
        letter-spacing:.16em;min-width:64px;text-align:center;}
      .room-caption{text-align:center;max-width:600px;margin:22px auto 0;font-size:14px;
        color:var(--text-muted);line-height:1.6;min-height:44px;}

      /* mobile: the ring becomes a snap strip — no perspective, no blur */
      @media (max-width:900px){
        .rooms-viewport{height:auto;perspective:none;overflow-x:auto;overflow-y:hidden;
          scroll-snap-type:x mandatory;-webkit-overflow-scrolling:touch;
          padding-bottom:8px;margin:0 -20px;scrollbar-width:none;}
        .rooms-viewport::-webkit-scrollbar{display:none;}
        .rooms-ring{position:static;transform:none !important;display:flex;gap:14px;padding:0 20px;}
        .room-face{position:static;flex:0 0 auto;width:min(84vw,470px);height:340px;margin:0;
          transform:none !important;opacity:1;filter:none;pointer-events:auto;scroll-snap-align:center;}
        .rooms-nav{display:none;}
      }

      /* ══ the mock kit — one small UI vocabulary all six rooms share ══ */
      .mock{border-radius:16px;overflow:hidden;display:flex;flex-direction:column;
        background:linear-gradient(180deg, var(--bg-2), var(--bg));
        border:1px solid var(--border-strong);
        box-shadow:0 40px 90px rgba(0,0,0,.6), 0 0 0 1px rgba(0,0,0,.4),
                   0 0 60px color-mix(in srgb, var(--accent) 8%, transparent);}
      .mock-bar{display:flex;align-items:center;gap:7px;padding:11px 15px;flex-shrink:0;
        border-bottom:1px solid var(--border);background:color-mix(in srgb, #000 28%, var(--bg-2));}
      .mock-bar i{width:9px;height:9px;border-radius:50%;background:var(--border-strong);font-style:normal;}
      .mock-bar i:nth-child(1){background:#E5533D;}
      .mock-bar i:nth-child(2){background:var(--accent);}
      .mock-bar i:nth-child(3){background:var(--success);}
      .mock-bar em{margin-left:8px;font-style:normal;font-size:10.5px;letter-spacing:.16em;
        text-transform:uppercase;color:var(--text-dim);}
      .mock-body{flex:1;padding:18px;display:flex;flex-direction:column;gap:14px;min-height:0;overflow:hidden;}
      .m-eyebrow{font-size:9.5px;font-weight:800;letter-spacing:.2em;text-transform:uppercase;color:var(--accent);}
      .m-h{font-family:var(--font-heading);font-size:17px;font-weight:600;color:var(--text-primary);line-height:1.2;}
      .m-tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;}
      .m-tile{padding:11px 12px;border-radius:11px;background:var(--surface);border:1px solid var(--border);}
      .m-tile .k{font-size:9px;letter-spacing:.13em;text-transform:uppercase;color:var(--text-dim);}
      .m-tile .v{font-family:var(--font-heading);font-size:20px;font-weight:600;color:var(--text-primary);
        line-height:1.15;margin-top:5px;}
      .m-tile .v.accent{color:var(--accent);}
      .m-tile .v.hot{color:var(--hot);}
      .m-cols{display:grid;grid-template-columns:1.25fr .75fr;gap:12px;flex:1;min-height:0;}
      .m-panel{border-radius:11px;background:var(--surface);border:1px solid var(--border);padding:12px;
        display:flex;flex-direction:column;gap:9px;min-height:0;overflow:hidden;}
      .m-row{display:flex;align-items:center;gap:9px;font-size:11.5px;color:var(--text-secondary);}
      .m-row .dot{width:6px;height:6px;border-radius:50%;background:var(--accent);flex-shrink:0;}
      .m-row .dot.cool{background:var(--info);} .m-row .dot.hot{background:var(--hot);}
      .m-row .grow{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
      .m-row .t{font-size:10.5px;color:var(--text-dim);flex-shrink:0;}
      .m-pill{padding:3px 9px;border-radius:99px;font-size:9.5px;font-weight:700;letter-spacing:.08em;
        text-transform:uppercase;flex-shrink:0;}
      .m-pill.paid{color:var(--success);background:color-mix(in srgb, var(--success) 14%, transparent);
        border:1px solid color-mix(in srgb, var(--success) 32%, transparent);}
      .m-pill.sent{color:var(--info);background:color-mix(in srgb, var(--info) 12%, transparent);
        border:1px solid color-mix(in srgb, var(--info) 30%, transparent);}
      .m-pill.due{color:var(--hot);background:color-mix(in srgb, var(--hot) 14%, transparent);
        border:1px solid color-mix(in srgb, var(--hot) 34%, transparent);}
      .m-bar{height:5px;border-radius:3px;background:var(--surface-2);overflow:hidden;}
      .m-bar span{display:block;height:100%;border-radius:3px;
        background:linear-gradient(90deg, var(--accent), var(--hot));}
      .m-label{font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--text-dim);}

      /* chat bubbles (Chief) */
      .m-chat{display:flex;flex-direction:column;gap:10px;flex:1;justify-content:flex-end;min-height:0;}
      .m-bubble{max-width:82%;padding:10px 13px;border-radius:13px;font-size:12px;line-height:1.5;}
      .m-bubble.you{align-self:flex-end;background:var(--surface-2);color:var(--text-secondary);
        border:1px solid var(--border);border-bottom-right-radius:4px;}
      .m-bubble.chief{align-self:flex-start;border-bottom-left-radius:4px;color:var(--text-primary);
        background:color-mix(in srgb, var(--accent) 11%, transparent);
        border:1px solid color-mix(in srgb, var(--accent) 28%, transparent);}
      .m-act{display:inline-flex;align-items:center;gap:7px;align-self:flex-start;padding:6px 11px;
        border-radius:8px;font-size:10.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
        color:var(--success);background:color-mix(in srgb, var(--success) 12%, transparent);
        border:1px solid color-mix(in srgb, var(--success) 30%, transparent);}

      /* swatches (Studio) */
      .m-swatches{display:flex;gap:7px;}
      .m-swatches span{width:30px;height:30px;border-radius:8px;border:1px solid var(--border-strong);}
      .m-arts{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;flex:1;min-height:0;}
      .m-art{border-radius:10px;border:1px solid var(--border);padding:10px;display:flex;
        flex-direction:column;justify-content:space-between;
        background:linear-gradient(160deg, color-mix(in srgb, var(--accent) 9%, transparent), transparent);}
      .m-art .cap{font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:var(--text-dim);}
      .m-art .mk{font-family:var(--font-heading);font-size:14px;font-weight:600;color:var(--text-primary);}
      .m-art .ln{height:3px;border-radius:2px;background:var(--surface-2);margin-top:5px;}
      .m-art .ln.s{width:60%;}

      /* progress ring (Academy) */
      .m-ring{width:88px;height:88px;border-radius:50%;flex-shrink:0;display:grid;place-items:center;
        background:conic-gradient(var(--accent) 0turn 0.62turn, var(--surface-2) 0.62turn 1turn);}
      .m-ring .in{width:66px;height:66px;border-radius:50%;background:var(--bg-2);display:grid;place-items:center;
        font-family:var(--font-heading);font-size:17px;font-weight:600;color:var(--text-primary);}

      /* mini site (Smart Sites) */
      .m-site{flex:1;border-radius:10px;overflow:hidden;border:1px solid var(--border);display:flex;
        flex-direction:column;min-height:0;}
      .m-site .band{padding:16px 14px;display:flex;flex-direction:column;gap:6px;
        background:linear-gradient(135deg, color-mix(in srgb, var(--accent) 18%, transparent),
                                            color-mix(in srgb, var(--hot) 10%, transparent));}
      .m-site .band .t{font-family:var(--font-heading);font-size:15px;font-weight:600;color:var(--text-primary);}
      .m-site .band .s{font-size:10.5px;color:var(--text-muted);}
      .m-site .cards{flex:1;display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:11px;}
      .m-site .cards div{border-radius:7px;background:var(--surface);border:1px solid var(--border);}

      /* ══════════════════════════════════════════════════════════════
         04 — WHY / audience / CTA
         ══════════════════════════════════════════════════════════════ */
      .demo-section{padding:88px 0;border-top:1px solid var(--border);}
      .demo-frame{max-width:880px;margin:0 auto;border-radius:18px;overflow:hidden;
        border:1px solid var(--border-strong);background:var(--surface);
        box-shadow:0 40px 90px rgba(0,0,0,.6);}
      .demo-chrome{display:flex;align-items:center;gap:7px;padding:11px 16px;border-bottom:1px solid var(--border);
        background:color-mix(in srgb, #000 28%, var(--bg-2));}
      .demo-chrome span{width:10px;height:10px;border-radius:50%;background:var(--border-strong);}
      .demo-chrome span:nth-child(1){background:#E5533D;}
      .demo-chrome span:nth-child(2){background:var(--accent);}
      .demo-chrome span:nth-child(3){background:var(--success);}
      .demo-chrome em{margin-left:10px;font-style:normal;font-size:11px;letter-spacing:.16em;
        text-transform:uppercase;color:var(--text-dim);}
      .demo-video{width:100%;display:block;aspect-ratio:16/9;background:#000;}
      .demo-caption{text-align:center;margin-top:18px;font-size:13px;color:var(--text-dim);}

      .sec-num{font-family:var(--font-heading);font-size:13px;font-weight:600;line-height:1;
        letter-spacing:.3em;color:color-mix(in srgb, var(--accent) 76%, var(--text-dim));
        display:block;margin-bottom:14px;}

      .audience{padding:76px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);
        background:linear-gradient(180deg, transparent, color-mix(in srgb, var(--accent) 4%, transparent), transparent);}
      .audience-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;}
      .audience-pill{display:inline-flex;align-items:center;gap:9px;padding:11px 20px;background:var(--surface);
        border:1px solid var(--border);border-radius:99px;font-size:14px;font-weight:500;
        color:var(--text-secondary);transition:border-color .18s, background .18s, transform .18s;}
      .audience-pill:hover{border-color:color-mix(in srgb, var(--accent) 45%, transparent);
        background:color-mix(in srgb, var(--accent) 8%, transparent);transform:translateY(-2px);}
      .audience-pill .emoji{font-size:17px;}

      .why-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:18px;}
      @media (max-width:760px){.why-grid{grid-template-columns:1fr;}}
      .why-card{display:flex;gap:16px;border-radius:16px;}
      .why-card .check{flex-shrink:0;width:34px;height:34px;border-radius:9px;display:grid;place-items:center;
        font-family:var(--font-heading);font-size:13px;font-weight:600;color:var(--accent);
        background:color-mix(in srgb, var(--accent) 12%, transparent);
        border:1px solid color-mix(in srgb, var(--accent) 32%, transparent);}
      .why-card p{font-size:14px;color:var(--text-muted);}

      .final-cta{padding:110px 0;text-align:center;position:relative;overflow:hidden;}
      .final-cta::before{content:'';position:absolute;inset:0;pointer-events:none;opacity:.7;
        background:radial-gradient(56% 100% at 50% 50%, var(--glow), transparent 66%);}
      .final-cta::after{content:'';position:absolute;left:50%;top:50%;width:520px;height:520px;
        transform:translate(-50%,-50%);pointer-events:none;opacity:.4;border-radius:50%;
        background:radial-gradient(circle, var(--glow-ember), transparent 66%);filter:blur(30px);}
      .final-cta .container{position:relative;z-index:1;}
      .final-cta h2{margin-bottom:14px;}
      .final-cta p{max-width:520px;margin:0 auto 34px;color:var(--text-muted);}

      /* ══ depth reveal — home overrides the shell's flat translateY so
         every section ARRIVES from Z instead of sliding up ══ */
      .reveal{opacity:0;transform:perspective(1200px) translate3d(0,26px,-90px) rotateX(7deg);
        transition:opacity .7s cubic-bezier(.22,1,.36,1), transform .7s cubic-bezier(.22,1,.36,1);}
      .reveal.visible{opacity:1;transform:perspective(1200px) translate3d(0,0,0) rotateX(0deg);}

      @media (prefers-reduced-motion: reduce){
        .deck-ring,.chip-bb,.deck-plane,.core-halo,.core-logo,.deck-tilt{animation:none !important;transition:none !important;}
        .rooms-ring,.pane,.room-face{transition:none !important;}
        .reveal{transform:none !important;}
      }
    """
    body = """
<section class="hero">
  <span class="orb orb-1" aria-hidden></span>
  <span class="orb orb-2" aria-hidden></span>
  <div class="container-xl">
    <div class="hero-grid">
      <div class="hero-copy">
        <span class="eyebrow reveal">For solo practitioners + small studios</span>
        <h1 class="reveal reveal-delay-1">Every problem<br>has a <span class="gradient-text">solution.</span></h1>
        <p class="lead reveal reveal-delay-2">One workspace that runs your whole practice — contacts, invoices, sessions, content, goals — commanded by an AI Chief of Staff that knows your business. Eight tools, replaced.</p>
        <div class="hero-ctas reveal reveal-delay-3">
          <a class="btn-primary" href="/get-started">Start Solving →</a>
          <a class="btn-secondary" href="#rooms">Look inside</a>
        </div>
        <div class="reveal reveal-delay-3" style="margin-top:20px;">
          <span class="stat-block"><span class="big">8</span><span>tools replaced by one workspace</span></span>
        </div>
        <div class="hero-rule reveal reveal-delay-3" aria-hidden="true"></div>
        <div class="hero-note reveal reveal-delay-3">Currently in private beta · Apply for access</div>
      </div>

      <div class="deck-stage reveal reveal-delay-2" id="deckStage" aria-hidden="true">
        <div class="deck-tilt" id="deckTilt">
          <div class="deck">
            <span class="deck-floor"></span>
            <span class="deck-shadow"></span>
            <span class="deck-pedestal"></span>
            <span class="deck-plane pl1"></span>
            <span class="deck-plane pl2"></span>
            <span class="deck-plane pl3"></span>

            <div class="deck-ring rA">
              <div class="chip-slot" style="--a:0deg;--r:var(--r1);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip"><i class="ci">◈</i>Finance</span></div></div>
              <div class="chip-slot" style="--a:72deg;--r:var(--r1);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip"><i class="ci">✎</i>Content</span></div></div>
              <div class="chip-slot" style="--a:144deg;--r:var(--r1);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip"><i class="ci">↗</i>Growth</span></div></div>
              <div class="chip-slot" style="--a:216deg;--r:var(--r1);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip"><i class="ci">◔</i>Analytics</span></div></div>
              <div class="chip-slot" style="--a:288deg;--r:var(--r1);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip"><i class="ci">✦</i>Branding</span></div></div>
            </div>

            <div class="deck-ring rB">
              <div class="chip-slot is-hot-slot" style="--a:45deg;--r:var(--r2);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip is-hot"><i class="ci">⚡</i>Autopilot</span></div></div>
              <div class="chip-slot" style="--a:135deg;--r:var(--r2);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip"><i class="ci">☑</i>Operate</span></div></div>
              <div class="chip-slot" style="--a:225deg;--r:var(--r2);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip"><i class="ci">♞</i>Strategy</span></div></div>
              <div class="chip-slot" style="--a:315deg;--r:var(--r2);"><span class="chip-node"></span><div class="chip-bb"><span class="deck-chip"><i class="ci">◎</i>Vision</span></div></div>
            </div>

            <div class="deck-core">
              <span class="core-halo"></span>
              <picture class="core-logo">
                <source srcset="/assets/mark.webp" type="image/webp">
                <img src="/assets/mark.png" alt="" width="158" height="158" loading="eager">
              </picture>
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
        <span class="sec-num reveal" aria-hidden="true">01</span>
        <span class="eyebrow reveal">The Chief of Staff</span>
        <h2 class="reveal reveal-delay-1" style="margin-top:14px;">Ask once. The whole system <span class="gradient-text">moves.</span></h2>
        <p class="lead reveal reveal-delay-2">Chief isn't a chatbot bolted onto a dashboard. It reads your real contacts, invoices, calendar and goals every turn — then acts on them.</p>
        <ul class="ask-list reveal reveal-delay-3">
          <li><span class="n">1</span><span>You ask in plain words — typed or spoken. <b>No menus to learn.</b></span></li>
          <li><span class="n">2</span><span>Chief reads your live data, not a generic model's guess. <b>It knows your numbers.</b></span></li>
          <li><span class="n">3</span><span>It does the work — drafts, sends, books, files. <b>Autopilot handles the routine while you sleep.</b></span></li>
        </ul>
      </div>
      <div class="pane-stage reveal reveal-delay-2">
        <div class="pane">
          <div class="mock" style="height:404px;">
            <div class="mock-bar"><i></i><i></i><i></i><em>Chief of Staff</em></div>
            <div class="mock-body">
              <div class="m-chat">
                <div class="m-bubble you">Who owes me money?</div>
                <div class="m-bubble chief">Three invoices are past due — <b>$2,140</b> total. Marcus (18 days), Grace Chapel (11), Tia (4). Want me to send reminders?</div>
                <div class="m-bubble you">Yes, and book Marcus for Thursday.</div>
                <div class="m-bubble chief">Done. Reminders sent from your address, and Marcus is on Thursday at 2:00 PM — invite went out.</div>
                <span class="m-act">✓ 3 reminders sent · 1 session booked</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="rooms" id="rooms">
  <div class="container-xl">
    <div class="section-head reveal">
      <span class="sec-num" aria-hidden="true">02</span>
      <span class="eyebrow">Look inside</span>
      <h2>Six rooms. <span class="gradient-text">One brain.</span></h2>
      <p>Each room is built for what happens in it — and they all share your contacts, your brand, and your Chief.</p>
    </div>

    <div class="rooms-tabs reveal" role="tablist" aria-label="Rooms">
      <button class="room-tab" role="tab" aria-selected="true"  data-i="0">Mission Control</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="1">Operate</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="2">The Studio</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="3">The Academy</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="4">Smart Sites</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="5">Autopilot</button>
    </div>

    <div class="rooms-viewport reveal" id="roomsViewport">
      <div class="rooms-ring" id="roomsRing">

        <div class="room-face is-active" style="--fa:0deg;" data-i="0"
             data-caption="Your AI core with live module satellites, four stat cards counting your real numbers, today's schedule, and what needs attention — the first thing you see every day.">
          <div class="mock">
            <div class="mock-bar"><i></i><i></i><i></i><em>Mission Control</em></div>
            <div class="mock-body">
              <div class="m-tiles">
                <div class="m-tile"><div class="k">Collected</div><div class="v accent">$12,480</div></div>
                <div class="m-tile"><div class="k">Past due</div><div class="v hot">3</div></div>
                <div class="m-tile"><div class="k">Sessions</div><div class="v">4</div></div>
                <div class="m-tile"><div class="k">Tasks</div><div class="v">7</div></div>
              </div>
              <div class="m-cols">
                <div class="m-panel">
                  <span class="m-label">Today</span>
                  <div class="m-row"><span class="dot"></span><span class="grow">Discovery call — Marcus Bell</span><span class="t">9:00</span></div>
                  <div class="m-row"><span class="dot cool"></span><span class="grow">Grace Chapel — planning session</span><span class="t">11:30</span></div>
                  <div class="m-row"><span class="dot hot"></span><span class="grow">Follow up: 3 overdue invoices</span><span class="t">2:00</span></div>
                  <div class="m-row"><span class="dot"></span><span class="grow">Draft October newsletter</span><span class="t">4:15</span></div>
                  <div class="m-row"><span class="dot cool"></span><span class="grow">Tia Randall — check-in call</span><span class="t">5:30</span></div>
                </div>
                <div class="m-panel">
                  <span class="m-label">Goal · Q4</span>
                  <div class="m-h">$40k</div>
                  <div class="m-bar"><span style="width:62%"></span></div>
                  <div class="m-row"><span class="t">62% — on pace</span></div>
                  <span class="m-label" style="margin-top:4px;">Modules</span>
                  <div class="m-row"><span class="dot"></span><span class="grow">9 live</span></div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:60deg;" data-i="1"
             data-caption="Contacts, invoices, calendar, tasks, email + SMS hubs, bookkeeping with reconciliation — the plumbing that keeps clients moving, all talking to each other.">
          <div class="mock">
            <div class="mock-bar"><i></i><i></i><i></i><em>Operate · Invoices</em></div>
            <div class="mock-body">
              <div style="display:flex;align-items:baseline;justify-content:space-between;">
                <span class="m-eyebrow">Accounts receivable</span>
                <span class="m-label">This month</span>
              </div>
              <div class="m-panel" style="flex:1;gap:11px;">
                <div class="m-row"><span class="grow">#1042 · Marcus Bell</span><span class="t">$640</span><span class="m-pill due">Overdue</span></div>
                <div class="m-row"><span class="grow">#1041 · Grace Chapel</span><span class="t">$1,200</span><span class="m-pill due">Overdue</span></div>
                <div class="m-row"><span class="grow">#1040 · Tia Randall</span><span class="t">$300</span><span class="m-pill due">Overdue</span></div>
                <div class="m-row"><span class="grow">#1039 · Northside Co-op</span><span class="t">$2,400</span><span class="m-pill sent">Sent</span></div>
                <div class="m-row"><span class="grow">#1038 · J. Okafor</span><span class="t">$850</span><span class="m-pill paid">Paid</span></div>
                <div class="m-row"><span class="grow">#1037 · Rivera Studio</span><span class="t">$1,150</span><span class="m-pill paid">Paid</span></div>
                <div class="m-row"><span class="grow">#1036 · Bethel Youth</span><span class="t">$475</span><span class="m-pill paid">Paid</span></div>
              </div>
              <div class="m-row"><span class="dot"></span><span class="grow">Reconciled to your bank feed 6 minutes ago</span></div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:120deg;" data-i="2"
             data-caption="Walk into a storefront built from your own brand. Try your identity on real artifacts — business card, invoice, social post — and watch everything repaint as you edit.">
          <div class="mock">
            <div class="mock-bar"><i></i><i></i><i></i><em>The Creative Studio · Fitting Room</em></div>
            <div class="mock-body">
              <span class="m-eyebrow">Your brand DNA</span>
              <div style="display:flex;align-items:center;gap:14px;">
                <div class="m-swatches">
                  <span style="background:#E6A24B"></span><span style="background:#FF6B35"></span>
                  <span style="background:#16110E"></span><span style="background:#F5EFE6"></span>
                  <span style="background:#4ECDC4"></span>
                </div>
                <div style="flex:1;">
                  <div class="m-h" style="font-size:15px;">Warm · Grounded · Direct</div>
                  <span class="m-label">Fraunces / Inter · generous spacing</span>
                </div>
              </div>
              <div class="m-arts">
                <div class="m-art"><span class="cap">Card</span><div><div class="mk">KMJ</div><div class="ln"></div><div class="ln s"></div></div></div>
                <div class="m-art"><span class="cap">Invoice</span><div><div class="mk">$1,200</div><div class="ln"></div><div class="ln s"></div></div></div>
                <div class="m-art"><span class="cap">Post</span><div><div class="mk">Launch</div><div class="ln"></div><div class="ln s"></div></div></div>
              </div>
              <div class="m-row"><span class="dot"></span><span class="grow">Change one color — every artifact repaints live</span></div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:180deg;" data-i="3"
             data-caption="A dedicated Strategy Coach walks you through eight courses — discovery to launch plan — with a degree ring, sealed courses, and a diploma when you graduate.">
          <div class="mock">
            <div class="mock-bar"><i></i><i></i><i></i><em>The Academy · Foundation Track</em></div>
            <div class="mock-body">
              <div style="display:flex;align-items:center;gap:16px;">
                <div class="m-ring"><span class="in">62%</span></div>
                <div style="flex:1;">
                  <span class="m-eyebrow">Foundation Track</span>
                  <div class="m-h" style="margin-top:4px;">5 of 8 courses sealed</div>
                  <span class="m-label">Diploma unlocks at 8</span>
                </div>
              </div>
              <div class="m-panel" style="flex:1;">
                <div class="m-row"><span class="dot"></span><span class="grow">01 · Who you serve</span><span class="m-pill paid">Sealed</span></div>
                <div class="m-row"><span class="dot"></span><span class="grow">02 · What you actually sell</span><span class="m-pill paid">Sealed</span></div>
                <div class="m-row"><span class="dot"></span><span class="grow">03 · Pricing with a spine</span><span class="m-pill paid">Sealed</span></div>
                <div class="m-row"><span class="dot cool"></span><span class="grow">04 · Your offer ladder</span><span class="m-pill sent">In progress</span></div>
                <div class="m-row"><span class="dot"></span><span class="grow">05 · The launch plan</span><span class="t">Locked</span></div>
              </div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:240deg;" data-i="4"
             data-caption="Your site is composed from your brand DNA and your own words — typography, spacing and motion reasoned from who you are, live on your own link in minutes.">
          <div class="mock">
            <div class="mock-bar"><i></i><i></i><i></i><em>Smart Sites · Live</em></div>
            <div class="mock-body">
              <div style="display:flex;align-items:baseline;justify-content:space-between;">
                <span class="m-eyebrow">Composed, not templated</span>
                <span class="m-label">yoursite.mysolutionist.app</span>
              </div>
              <div class="m-site">
                <div class="band">
                  <div class="t">Counsel that holds up.</div>
                  <div class="s">Family mediation · Grand Rapids, MI</div>
                </div>
                <div class="cards"><div></div><div></div><div></div></div>
              </div>
              <div class="m-row"><span class="dot"></span><span class="grow">Typography and spacing reasoned from your brand — not a theme</span></div>
            </div>
          </div>
        </div>

        <div class="room-face" style="--fa:300deg;" data-i="5"
             data-caption="Set the rules once. Chief works your follow-ups, reminders and drafts on schedule — and shows you every action it took, so nothing happens behind your back.">
          <div class="mock">
            <div class="mock-bar"><i></i><i></i><i></i><em>Autopilot · Overnight</em></div>
            <div class="mock-body">
              <div style="display:flex;align-items:baseline;justify-content:space-between;">
                <span class="m-eyebrow">Ran while you slept</span>
                <span class="m-label">04:00 — 07:30</span>
              </div>
              <div class="m-panel" style="flex:1;gap:11px;">
                <div class="m-row"><span class="dot"></span><span class="grow">Sent 3 invoice reminders</span><span class="m-pill paid">Done</span></div>
                <div class="m-row"><span class="dot"></span><span class="grow">Drafted follow-up to Northside Co-op</span><span class="m-pill sent">Review</span></div>
                <div class="m-row"><span class="dot"></span><span class="grow">Prepped notes for 9:00 discovery call</span><span class="m-pill paid">Done</span></div>
                <div class="m-row"><span class="dot cool"></span><span class="grow">Reconciled 14 bank transactions</span><span class="m-pill paid">Done</span></div>
                <div class="m-row"><span class="dot hot"></span><span class="grow">Flagged: Tia's card expires in 6 days</span><span class="m-pill due">You</span></div>
              </div>
              <div class="m-row"><span class="dot"></span><span class="grow">Every action logged — approve, undo, or change the rules anytime</span></div>
            </div>
          </div>
        </div>

      </div>
    </div>

    <div class="rooms-nav">
      <button class="rooms-arrow" id="roomPrev" aria-label="Previous room">‹</button>
      <span class="rooms-count" id="roomCount">01 / 06</span>
      <button class="rooms-arrow" id="roomNext" aria-label="Next room">›</button>
    </div>
    <p class="room-caption" id="roomCaption">Your AI core with live module satellites, four stat cards counting your real numbers, today's schedule, and what needs attention — the first thing you see every day.</p>

    <div style="text-align:center;margin-top:36px;" class="reveal">
      <a class="btn-secondary" href="/features">Explore every feature in depth →</a>
    </div>
  </div>
</section>

<section id="demo" class="demo-section">
  <div class="container">
    <div class="section-head reveal">
      <span class="sec-num" aria-hidden="true">03</span>
      <span class="eyebrow">See it move</span>
      <h2>Fifty-five seconds, <span class="gradient-text">end to end.</span></h2>
      <p>The real system, scene by scene — Chief, Mission Control, getting paid, the Academy, the Studio, Autopilot.</p>
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
      <span class="sec-num reveal" aria-hidden="true">04</span>
      <span class="eyebrow reveal">Who it's for</span>
      <h2 class="reveal reveal-delay-1" style="margin-top:14px;">Built for people who serve people.</h2>
    </div>
    <div class="audience-grid reveal reveal-delay-2">
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
      <span class="sec-num" aria-hidden="true">05</span>
      <span class="eyebrow">Why Solutionist</span>
      <h2>One workspace replacing the chaos of eight.</h2>
    </div>
    <div class="why-grid">
      <div class="card why-card reveal">
        <div class="check">01</div>
        <div><h3>One brain, not eight</h3><p>Your CRM, invoicing, calendar, content and analytics all talk to each other. Update a contact once; every tool sees it.</p></div>
      </div>
      <div class="card why-card reveal reveal-delay-1">
        <div class="check">02</div>
        <div><h3>AI that knows your business</h3><p>Chief reads your real data every turn — not a generic LLM. Asks for context once, then uses it forever.</p></div>
      </div>
      <div class="card why-card reveal">
        <div class="check">03</div>
        <div><h3>Real-time, not weekly reports</h3><p>Every metric updates as data changes. No CSV exports, no waiting for someone to refresh.</p></div>
      </div>
      <div class="card why-card reveal reveal-delay-1">
        <div class="check">04</div>
        <div><h3>Built for solo, not enterprise</h3><p>No teams, no seat math, no Slack-integration sprawl. Designed for one operator running their whole practice.</p></div>
      </div>
    </div>
  </div>
</section>

<section class="final-cta">
  <div class="container">
    <span class="eyebrow reveal">Ready when you are</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">Run your practice <span class="gradient-text">from one place.</span></h2>
    <p class="reveal reveal-delay-2">Currently in private beta. Apply for access — we'll set you up and walk you through onboarding.</p>
    <a class="btn-primary reveal reveal-delay-3" href="/get-started">Apply for Access →</a>
  </div>
</section>
"""
    extra_scripts = """
<script>
(function () {
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  /* ── hero: pointer parallax on the command deck ──
     Tilts the whole scene as one object. Pointer-coarse devices and
     reduced-motion users get the static tilt the CSS already sets. */
  var stage = document.getElementById('deckStage');
  var tilt  = document.getElementById('deckTilt');
  var fine  = window.matchMedia && window.matchMedia('(pointer: fine)').matches;
  if (stage && tilt && fine && !reduced) {
    var raf = 0, tx = 0, ty = 0;
    function apply() {
      raf = 0;
      tilt.style.setProperty('--px', tx.toFixed(2) + 'deg');
      tilt.style.setProperty('--py', ty.toFixed(2) + 'deg');
    }
    stage.addEventListener('mousemove', function (e) {
      var r = stage.getBoundingClientRect();
      tx = ((e.clientX - r.left) / r.width  - 0.5) * 16;   /* yaw   */
      ty = ((e.clientY - r.top)  / r.height - 0.5) * -11;  /* pitch */
      if (!raf) raf = requestAnimationFrame(apply);
    });
    stage.addEventListener('mouseleave', function () {
      tx = 0; ty = 0;
      if (!raf) raf = requestAnimationFrame(apply);
    });
  }

  /* ── rooms: the 3D carousel ── */
  var ring    = document.getElementById('roomsRing');
  var vp      = document.getElementById('roomsViewport');
  var caption = document.getElementById('roomCaption');
  var counter = document.getElementById('roomCount');
  if (ring) {
    var faces = [].slice.call(ring.querySelectorAll('.room-face'));
    var tabs  = [].slice.call(document.querySelectorAll('.room-tab'));
    var n = faces.length, cur = 0, timer = null, manual = false;
    var flat = function () {
      return window.matchMedia && window.matchMedia('(max-width: 900px)').matches;
    };

    function pad(i) { return (i + 1 < 10 ? '0' : '') + (i + 1); }

    function show(i, fromUser) {
      cur = ((i % n) + n) % n;
      if (fromUser) { manual = true; if (timer) { clearInterval(timer); timer = null; } }

      /* On phones the ring is a snap strip — scroll instead of rotate.
         Deliberately NOT scrollIntoView: on a horizontally-scrolling
         container it still scrolls the PAGE vertically to reach the
         element, so the strip yanked the whole document down to the
         rooms section. Driving scrollLeft moves only the container. */
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

      for (var f = 0; f < n; f++) faces[f].classList.toggle('is-active', f === cur);
      for (var t = 0; t < tabs.length; t++) {
        tabs[t].setAttribute('aria-selected', String(Number(tabs[t].dataset.i) === cur));
      }
      if (caption) caption.textContent = faces[cur].dataset.caption || '';
      if (counter) counter.textContent = pad(cur) + ' / ' + pad(n - 1);
    }

    tabs.forEach(function (b) {
      b.addEventListener('click', function () { show(Number(b.dataset.i), true); });
    });
    var prev = document.getElementById('roomPrev');
    var next = document.getElementById('roomNext');
    if (prev) prev.addEventListener('click', function () { show(cur - 1, true); });
    if (next) next.addEventListener('click', function () { show(cur + 1, true); });

    /* keyboard: arrows move the carousel when it has focus within */
    if (vp) {
      vp.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowRight') { show(cur + 1, true); e.preventDefault(); }
        if (e.key === 'ArrowLeft')  { show(cur - 1, true); e.preventDefault(); }
      });
    }

    /* On phones the user scrolls the strip directly — keep the tabs and
       caption honest by tracking which face is centred. */
    if (vp) {
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
          if (best !== cur) {
            cur = best;
            for (var g = 0; g < n; g++) faces[g].classList.toggle('is-active', g === cur);
            for (var t2 = 0; t2 < tabs.length; t2++) {
              tabs[t2].setAttribute('aria-selected', String(Number(tabs[t2].dataset.i) === cur));
            }
            if (caption) caption.textContent = faces[cur].dataset.caption || '';
            if (counter) counter.textContent = pad(cur) + ' / ' + pad(n - 1);
          }
        }, 90);
      }, { passive: true });
    }

    /* auto-advance until the visitor takes the wheel; paused off-screen
       and on hover so it never spins at a nobody. */
    if (!reduced) {
      var start = function () {
        /* never auto-advance the phone strip: it fights the reader's own
           swipe and moves content under their thumb mid-read */
        if (manual || timer || flat()) return;
        timer = setInterval(function () { show(cur + 1, false); }, 6000);
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
  }
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
<h2 style="color:#8F5A16;margin-bottom:18px;">New beta application</h2>
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
<h2 style="color:#8F5A16;margin-bottom:14px;">Thanks for applying, {_html.escape(name.split()[0])}.</h2>
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
