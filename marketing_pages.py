"""
marketing_pages.py — Multi-page public marketing site for mysolutionist.app.

Pages served:
  /            → Home (hero + features + audience + why + CTA)
  /features    → Deep feature explanation, surface by surface
  /compare     → Solutionist vs the 8-tool stack (with cost breakdown)
  /faq         → FAQ on its own URL
  /about       → Founder note + company
  /get-started → Talk to a person (intake form, POSTs to /api/leads)

Every "start" button points at /start (public_site.py), which forwards to
the app carrying the visitor's campaign params. The site sells a
self-serve subscription: it does not ask anyone to apply.

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
from typing import Any, Dict, List, Optional

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, EmailStr

import platform_addresses
import site_news

# Kept as the bounce-guard fallback only — see platform_addresses. Nothing
# should print this directly; call _public_contact_email() instead.
CONTACT_EMAIL = platform_addresses.FOUNDER_FALLBACK_EMAIL
BUSINESS_NAME = "The Solutionist System LLC"
SITE_NAME = "The Solutionist System"
SITE_DOMAIN = "mysolutionist.app"
# Arc 18 — the web app's home (Vite app on Vercel; marketing stays here).
APP_URL = "https://system.mysolutionist.app"
# Every "start your free trial" button on the site points HERE, not at
# APP_URL directly — /start forwards to the app with the visitor's
# campaign params attached, which is the only way an ad's utm tags
# survive the hop to a different origin. See public_site.public_start.
SIGNUP_PATH = "/start"
DESKTOP_RELEASES_URL = ""  # set to the GitHub Releases URL once installers publish
# Arc 25 — Android distribution. Env-driven so the links go live from
# Railway the moment the first signed APK is uploaded (GitHub Releases),
# no code deploy needed. PLAY_STORE_URL stays empty until the listing
# is approved (docs/play_store_submission.md in the frontend repo).
ANDROID_APK_URL = os.environ.get("ANDROID_APK_URL", "").strip()
PLAY_STORE_URL = os.environ.get("PLAY_STORE_URL", "").strip()

def _trial_days() -> int:
    """How many free days the site is allowed to promise.

    Read from the SAME env var stripe_billing hands Stripe as
    trial_period_days. One source, so the number on the page and the
    number on the subscription cannot drift apart — the site promising
    14 while checkout grants 7 is the kind of thing you only discover
    from a refund request."""
    try:
        return max(0, int(os.environ.get("BILLING_TRIAL_DAYS") or "7"))
    except ValueError:
        return 7


def _trial_free_phrase() -> str:
    """What `__TRIAL_FREE__` becomes in page copy. Every use reads
    "<phrase>, then $79/mo" or "<phrase> · something", so the no-trial
    case has to be a phrase too, not an empty string."""
    days = _trial_days()
    return f"{days} days free" if days else "No setup fee"


def _public_contact_email() -> str:
    """The address the public site prints — resolver in
    `platform_addresses`, which the legal pages now share.

    Kevin, 2026-08-20: contact should land in the system, not in a
    personal mailbox. It already can — `email_sender` routes mail for the
    named platform locals (hello / support / contact / info / billing /
    admin / kevin) into `platform_emails`, which is what Mission
    Control's inbox reads.

    Kevin, 2026-08-23: the published local is `info`, and it is the SAME
    address the legal pages print. It used to not be — this module had
    already moved to a derived address while `legal_content` still
    printed the founder's Gmail, so the About page and the Privacy
    Policy disagreed about how to reach the company. One resolver owns
    both now, and a test holds them together.
    """
    return platform_addresses.public_contact_email()


def _operator_email() -> str:
    """Where the system mails the operator (lead alerts). Internal —
    never printed on a page. See platform_addresses.operator_email."""
    return platform_addresses.operator_email()


# Page bodies are plain triple-quoted strings, not f-strings — they carry
# raw CSS, so every `{` in them would have to be doubled. That is why the
# contact address could not be interpolated where it appears mid-copy and
# got hardcoded twice instead. This sentinel is the way to write it into
# a body: `_render_shell` swaps it on every page, so a new page gets the
# behaviour for free.
CONTACT_TOKEN = "__CONTACT_EMAIL__"
# Same trick for the length of the free trial. It appears in copy on
# five pages, and every one of them has to say what checkout actually
# grants — so none of them hardcodes a number.
TRIAL_TOKEN = "__TRIAL_FREE__"


def _fill_contact(html: str) -> str:
    """Swap the contact sentinel for the resolved address.

    Deliberately does NOT raise when the token is absent — most pages
    don't mention the address in their body and a renderer that throws
    turns a cosmetic problem into a 500. The guard against this quietly
    doing nothing is a test, not an exception:
    `test_no_public_page_prints_the_founder_gmail` renders every page
    and fails if the old literal survives anywhere.
    """
    if CONTACT_TOKEN not in html:
        return html
    return html.replace(CONTACT_TOKEN, _html.escape(_public_contact_email()))


def _fill_trial(html: str) -> str:
    """Swap the trial sentinel for the length checkout actually grants.
    Absent-token tolerant for the same reason _fill_contact is."""
    if TRIAL_TOKEN not in html:
        return html
    return html.replace(TRIAL_TOKEN, _html.escape(_trial_free_phrase()))


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
    /* the one mono face on the site: the contact address, set so it
       reads as something to copy rather than something to skim */
    --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
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
  /* 78, matching the home page's fold. At 68 the inner pages read as
     a lesser tier of page, and nothing justified the demotion. */
  h1{font-size:clamp(42px, 6.2vw, 78px);font-weight:700;}
  h2{font-size:clamp(30px, 4.2vw, 46px);font-weight:700;letter-spacing:-0.03em;margin-bottom:14px;}
  h3{font-size:18px;font-weight:600;color:var(--text-primary);margin-bottom:6px;}
  p{color:var(--text-secondary);font-size:16px;}
  .lead{font-size:18px;color:var(--text-muted);line-height:1.65;}

  /* ─── nav ─── */
  /* NO BAR. The mark and the links sit straight on the page, with the
     hero's own light running behind them, and the row scrolls away
     with the content rather than sticking. A translucent strip still
     reads as a strip — the only way to stop the black band joining the
     brand to the nav was to stop painting one. */
  /* Absolute, not fixed: the row scrolls away with the page. Out of
     flow so the first section starts at the top of the document and
     its light — the hero's blobs on home, .page-hero::before on the
     rest — paints behind the wordmark instead of starting under it.
     Every first section carries 128px of top padding, which clears
     the 65px row with room to spare. */
  .nav{position:absolute;top:0;left:0;right:0;z-index:50;background:transparent;border-bottom:none;}
  .nav-inner{display:flex;align-items:center;justify-content:space-between;padding:14px 28px;max-width:1140px;margin:0 auto;}
  .brand{font-family:var(--font-heading);font-size:17px;font-weight:600;color:var(--text-primary);letter-spacing:-0.01em;display:inline-flex;align-items:center;gap:10px;}
  .brand .logo{height:32px;width:32px;object-fit:contain;display:block;flex-shrink:0;filter:drop-shadow(0 0 8px var(--glow));}
  .footer .brand .logo{height:28px;}
  .brand .dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:linear-gradient(135deg, var(--accent), var(--info));box-shadow:0 0 8px var(--glow);}
  .brand-text{display:inline-block;}
  @media (max-width: 540px){.brand-text{display:none;}}
  /* ══ PAGE TRANSITIONS ═══════════════════════════════════════════════
     Navigating moves the accent marker to the page you picked, and the
     content arrives underneath it. Cross-document, so there is no router
     and no SPA rewrite — the browser morphs the marker between the two
     documents because both name it `nav-current`.

     It runs OVER the arrival, never in front of it: the incoming content
     starts drawing at 60ms while the marker is still travelling, so the
     transition never delays the page.

     Chromium-only today. Everywhere else this is inert and navigation is
     exactly what it was — no layout shift, no fallback to maintain. */
  @view-transition { navigation: auto; }
  @media (prefers-reduced-motion: reduce){ @view-transition { navigation: none; } }

  .page-main{view-transition-name:page-main;}
  ::view-transition-old(page-main){animation:pgOut .14s ease both;}
  ::view-transition-new(page-main){animation:pgIn .26s cubic-bezier(.2,.7,.3,1) .06s backwards;}
  @keyframes pgOut{to{opacity:0;transform:translateY(-6px);}}
  @keyframes pgIn{from{opacity:0;transform:translateY(10px);}}
  /* 340ms — chosen against 200 and 600 side by side */
  ::view-transition-group(nav-current){animation-duration:.34s;
    animation-timing-function:cubic-bezier(.2,.7,.3,1);}

  .nav-links{display:flex;align-items:center;gap:22px;font-size:13px;font-weight:500;}
  .nav-links a{color:var(--text-muted);transition:color 0.15s;position:relative;}
  .nav-links a:hover, .nav-links a.is-active{color:var(--text-primary);}
  /* THE NAV IS A TRACE. One rail under the page links, a node on it for each
     page, and the current sits on the one you are looking at — home is the
     node at the rail's origin, since the logo is the home link.

     Navigating moves the lit node to the page you picked: both documents name
     it `nav-current`, so the browser morphs it across the navigation. It has
     to be a real element — a pseudo element cannot carry a
     view-transition-name, which is why this is a span and not ::after. */
  .nav-pages{display:flex;align-items:center;gap:22px;position:relative;}
  .nav-pages::before{content:'';position:absolute;left:0;right:0;bottom:-17px;height:1.5px;
    background:#1E2A3B;border-radius:1px;pointer-events:none;}
  .nav-pages a{position:relative;}
  .nav-home{display:block;width:7px;height:7px;position:relative;flex:none;}
  .nav-dot{position:absolute;left:50%;margin-left:-3.5px;bottom:-20.5px;width:7px;height:7px;
    border-radius:50%;background:var(--bg);border:1.5px solid #1E2A3B;
    transition:border-color .25s ease, background .25s ease;}
  .nav-pages a.is-active .nav-dot, .nav-home.is-active .nav-dot{
    border-color:var(--accent);background:#0B1220;view-transition-name:nav-current;}
  .nav-pages a.is-active .nav-dot::after, .nav-home.is-active .nav-dot::after{
    content:'';position:absolute;inset:1.5px;border-radius:50%;background:var(--accent);}
  .nav-cta{white-space:nowrap;padding:8px 16px;background:var(--accent);color:var(--ink-on-accent) !important;border-radius:8px;font-weight:700;font-size:13px;box-shadow:0 2px 14px color-mix(in srgb, var(--accent) 30%, transparent);transition:transform 0.15s, box-shadow 0.15s, background 0.15s;}
  .nav-cta:hover{transform:translateY(-1px);background:var(--accent-2);box-shadow:0 4px 20px color-mix(in srgb, var(--accent) 45%, transparent);}
  .nav-login{white-space:nowrap;padding:7px 15px;border:1px solid var(--border-strong);border-radius:8px;color:var(--text-primary) !important;font-weight:600;font-size:13px;transition:border-color 0.15s, background 0.15s;}
  .nav-login:hover{border-color:var(--accent);background:var(--surface);}
  /* 900, not 760: at ~768 every link still showed, which wrapped both the
     brand and "Get the App" onto extra lines and buckled the whole bar. */
  @media (max-width: 900px){.nav-links{gap:12px;font-size:12px;} .nav-pages{display:none;} .nav-links a:not(.nav-cta):not(.nav-login){display:none;}
    .brand-text{white-space:nowrap;}}
  /* Get Started is already the primary button INSIDE the menu, so on a
     phone it was on screen twice and the bar carried three objects in
     390px. The bar keeps the mark and the trigger; the CTA lives one
     tap away where it has room to be a real button. */
  @media (max-width: 900px){.nav-links .nav-cta{display:none;}}
  /* under ~420 the bar runs out of room: Log in lives in the menu instead */
  @media (max-width: 420px){.nav-inner{padding:12px 16px;} .nav-links .nav-login{display:none;}}

  /* ─── mobile menu ───────────────────────────────────────────────
     The links above are hidden below 900px, so without this the only
     way off the page on a phone is the footer. The panel is a SIBLING
     of .nav on purpose: .nav carries a z-index, which creates a
     stacking context, so a panel nested inside it could never climb
     above the bar however high its own z-index went. ── */
  /* 44px, not 40: 44 is the touch-target floor, and a circle reads as
     one object next to the wordmark where a rounded square read as a
     second button. */
  .nav-burger{display:none;align-items:center;justify-content:center;width:44px;height:44px;flex-shrink:0;
    border:1px solid var(--border-strong);border-radius:50%;background:transparent;
    color:var(--text-primary);cursor:pointer;padding:0;font-family:inherit;
    transition:border-color .15s, background .15s;}
  .nav-burger:hover{border-color:var(--accent);background:var(--surface-2);}
  .nav-burger svg{width:19px;height:19px;}
  /* AFTER the base rule on purpose: a media query adds no specificity, so
     "display:none" declared later would win and the button would never
     appear. Same breakpoint that hides the links above. */
  @media (max-width: 900px){.nav-burger{display:inline-flex;}}

  .mobile-menu{position:fixed;inset:0;z-index:60;display:none;}
  .mobile-menu.is-open{display:block;}
  /* --mm-panel-h is written by openMenu(). Falling back to 0 keeps
     the old full-height scrim if the script never runs, so the
     overlay is never left without something to close it. */
  .mm-scrim{position:absolute;inset:0;top:var(--mm-panel-h,0px);
    background:rgba(4,5,8,.66);opacity:0;transition:opacity .22s ease;}
  .mobile-menu.is-in .mm-scrim{opacity:1;}
  /* 72% + blur rather than solid --bg-2: the hero's light carries
     through the whole panel, including behind the mark and the close
     button, so the menu reads as a layer over the page instead of a
     black slab that replaced it. Rounded foot for the same reason. */
  .mm-panel{position:absolute;top:0;left:0;right:0;max-height:100%;overflow-y:auto;
    background:color-mix(in srgb, var(--bg-2) 66%, transparent);
    backdrop-filter:blur(26px) saturate(1.35);-webkit-backdrop-filter:blur(26px) saturate(1.35);
    border-bottom:1px solid var(--border-strong);border-radius:0 0 22px 22px;
    box-shadow:0 30px 56px rgba(0,0,0,.7);padding:0 10px 18px;
    opacity:0;transform:translateY(-12px);
    transition:opacity .2s ease, transform .26s cubic-bezier(.22,1,.36,1);}
  .mobile-menu.is-in .mm-panel{opacity:1;transform:none;}
  .mm-top{display:flex;align-items:center;justify-content:space-between;
    padding:10px 10px;}
  .mm-close{display:inline-flex;align-items:center;justify-content:center;width:44px;height:44px;
    border:1px solid var(--border-strong);border-radius:50%;background:transparent;
    color:var(--text-primary);cursor:pointer;padding:0;font-family:inherit;
    transition:border-color .15s, background .15s;}
  .mm-close:hover{border-color:var(--accent);background:var(--surface-2);}
  .mm-close svg{width:18px;height:18px;}
  /* A hairline under every row made a four-item menu read as a
     settings table. Separation comes from the gap and the pressed
     state instead, and the chevrons are gone with them: a > promises
     a submenu and every one of these opens a page. */
  .mm-links{display:flex;flex-direction:column;gap:4px;padding:4px 0;}
  .mm-links a{display:flex;align-items:center;min-height:52px;
    padding:0 16px;border-radius:999px;
    font-family:var(--font-heading);font-size:17px;font-weight:500;
    letter-spacing:-.01em;color:var(--text-secondary);
    transition:color .16s, background .16s;}
  .mm-links a:hover{color:var(--text-primary);background:var(--surface-2);}
  .mm-links a.is-active{color:var(--accent);background:color-mix(in srgb, var(--accent) 16%, transparent);}
  .mm-actions{display:flex;flex-direction:column;gap:10px;margin-top:14px;padding:0 10px;}
  .mm-actions a{display:flex;align-items:center;justify-content:center;padding:14px 18px;
    border-radius:999px;font-size:15px;font-weight:700;font-family:inherit;}
  .mm-actions .mm-primary{background:var(--accent);color:var(--ink-on-accent);
    box-shadow:0 6px 22px color-mix(in srgb, var(--accent) 30%, transparent);}
  .mm-actions .mm-secondary{background:var(--surface);color:var(--text-primary);
    border:1px solid var(--border-strong);font-weight:600;}
  .mm-fine{display:flex;flex-wrap:wrap;justify-content:center;gap:6px 16px;margin-top:20px;
    font-size:12.5px;color:var(--text-dim);}
  .mm-fine a{color:var(--text-dim);}
  .mm-fine a:hover{color:var(--text-secondary);}
  @media (prefers-reduced-motion: reduce){
    .mm-scrim,.mm-panel{transition:none !important;}
    .mm-panel{transform:none !important;}
  }

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
  /* One number for every section on every page. The home page runs
     128 and the rest ran 80, so following a nav link tightened the
     whole site by 48px a side. */
  section{position:relative;padding:128px 0;}
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

  /* ─── inline icons (replaced the decorative emoji) ─── */
  .pill-ico{width:16px;height:16px;flex-shrink:0;opacity:.85;}
  .audience-pill{gap:9px;}
  .fs-ico{width:15px;height:15px;flex-shrink:0;vertical-align:-2px;margin-right:7px;}
  .fs-eyebrow{display:inline-flex;align-items:center;}

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

  /* ─── card used by /download (and formerly /about) ───
     This rule lived in render_about's extra_css while /download printed
     the class three times — so the Get-the-App cards have never had a
     background, a border or padding. A per-page stylesheet cannot reach
     another page; shared chrome belongs in the shell. */
  .company-card{padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:14px;}
  .company-card h3{font-family:var(--font-heading);font-size:14px;color:var(--text-muted);
    text-transform:uppercase;letter-spacing:1.4px;margin-bottom:10px;}
  .company-card p{font-size:14px;color:var(--text-secondary);}

  /* ─── closing CTA (features / compare / about) ───
     This rule lived in render_home's extra_css until 2026-08-19, when
     the device band replaced home's closer and took the CSS with it.
     Three other pages had been printing the class the whole time and
     never carried the rule — a per-page stylesheet cannot reach them.
     It sits in the shell now, which is the only place shared chrome
     actually is shared. */
  .final-cta{padding:128px 0;text-align:center;position:relative;overflow:hidden;}
  .final-cta::before{content:'';position:absolute;inset:0;pointer-events:none;opacity:.55;
    background:radial-gradient(52% 100% at 50% 50%, var(--glow), transparent 68%);}
  .final-cta .container{position:relative;z-index:1;}
  .final-cta h2{margin-bottom:0;}
  .final-cta p{max-width:520px;margin:0 auto 34px;color:var(--text-muted);}
  .final-cta .btn-primary{margin-top:22px;}

  /* ─── page-hero (for non-home pages) ─── */
  .page-hero{position:relative;padding:128px 0;text-align:center;overflow:hidden;border-bottom:1px solid var(--border);}
  .page-hero::before{content:'';position:absolute;inset:-40px 0 auto;height:280px;background:radial-gradient(60% 80% at 50% 0%, var(--glow), transparent 70%);pointer-events:none;opacity:0.6;}
  .page-hero .container{position:relative;z-index:1;}
  .page-hero h1{margin:14px 0 16px;}
"""

SHELL_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{title} &middot; The Solutionist System</title>
<meta name="description" content="{description}">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{description}">
<meta property="og:url" content="https://mysolutionist.app{path}">
<link rel="canonical" href="https://mysolutionist.app{path}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="The Solutionist System">
<meta property="og:image" content="https://mysolutionist.app/assets/og.png?v=4">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{og_title}">
<meta name="twitter:description" content="{description}">
<meta name="twitter:image" content="https://mysolutionist.app/assets/og.png?v=4">
<link rel="icon" type="image/png" href="/favicon.png">
<link rel="apple-touch-icon" href="/favicon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@500;600;700&family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>{shared_css}{extra_css}</style>
{head_extra}
{pixel_script}
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <a class="brand" href="/">
      <img class="logo" src="/assets/logo-nav.png" alt="The Solutionist System">
      <span class="brand-text">The Solutionist System</span>
    </a>
    <div class="nav-links">
      <div class="nav-pages">
        <span class="nav-home {ax_home}" aria-hidden="true"><span class="nav-dot"></span></span>
        <a href="/about" class="{ax_about}">About<span class="nav-dot"></span></a>
        <a href="/features" class="{ax_features}">Features<span class="nav-dot"></span></a>
        <a href="/compare" class="{ax_compare}">Compare<span class="nav-dot"></span></a>
        <a href="/#pricing">Pricing<span class="nav-dot"></span></a>
      </div>
      <a class="nav-login" href="{app_url}">Log in</a>
      <a class="nav-cta" href="/start">Start free trial</a>
      <button class="nav-burger" id="navBurger" type="button" aria-label="Open menu"
              aria-expanded="false" aria-controls="mobileMenu">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><line x1="4" x2="20" y1="6" y2="6"/><line x1="4" x2="20" y1="12" y2="12"/><line x1="4" x2="20" y1="18" y2="18"/></svg>
      </button>
    </div>
  </div>
</nav>

<div class="mobile-menu" id="mobileMenu" hidden>
  <div class="mm-scrim" data-mm-close></div>
  <div class="mm-panel" role="dialog" aria-modal="true" aria-label="Site menu">
    <div class="mm-top">
      <a class="brand" href="/">
        <img class="logo" src="/assets/logo-nav.png" alt="" width="32" height="32">
        <span class="brand-text">The Solutionist System</span>
      </a>
      <button class="mm-close" id="mmClose" type="button" aria-label="Close menu" data-mm-close>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
      </button>
    </div>
    <nav class="mm-links" aria-label="Pages">
      <a href="/about" class="{ax_about}">About</a>
      <a href="/features" class="{ax_features}">Features</a>
      <a href="/compare" class="{ax_compare}">Compare</a>
      <a href="/#pricing">Pricing</a>
    </nav>
    <div class="mm-actions">
      <a class="mm-primary" href="/start">Start free trial &rarr;</a>
      <a class="mm-secondary" href="{app_url}">Log in</a>
    </div>
    <div class="mm-fine">
      <a href="/privacy">Privacy</a>
      <a href="/terms">Terms</a>
      <a href="mailto:{contact_email}">Contact</a>
    </div>
  </div>
</div>

<main class="page-main">
{content}
</main>

<footer>
  <div class="footer-inner">
    <div class="footer-brand">
      <span class="brand">
        <img class="logo" src="/assets/logo-nav.png" alt="The Solutionist System" style="height:28px;">
        <span class="brand-text">The Solutionist System</span>
      </span>
      <span class="small">Built by The Solutionist System LLC</span>
    </div>
    <div class="footer-links">
      <a href="/features">Features</a>
      <a href="/compare">Compare</a>
      <a href="/faq">FAQ</a>
      <a href="/about">About</a>
      <a href="/news">News</a>
      <a href="/start">Start free trial</a>
      <a href="/get-started">Talk to us</a>
      <a href="{app_url}">Log in</a>
      <a href="/download">Get the app</a>
      <a href="/help">Help</a>
      <a href="{app_url}/status.html">Status</a>
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

    /* ── mobile menu ───────────────────────────────────────────────
       Below 900px the nav links are hidden, so this panel is the only
       way to the other pages. Keep it keyboard-usable: Escape closes,
       Tab stays inside, focus returns to the button that opened it. */
    var burger = document.getElementById('navBurger');
    var menu   = document.getElementById('mobileMenu');
    if (burger && menu) {{
      var panel = menu.querySelector('.mm-panel');
      var closeBtn = document.getElementById('mmClose');
      var openState = false, closeTimer = null;

      function focusables() {{
        return [].slice.call(panel.querySelectorAll('a[href], button:not([disabled])'))
                 .filter(function (el) {{ return el.offsetParent !== null; }});
      }}

      function openMenu() {{
        if (openState) return;
        openState = true;
        if (closeTimer) {{ clearTimeout(closeTimer); closeTimer = null; }}
        menu.hidden = false;
        menu.classList.add('is-open');
        /* reflow so the opening transition actually runs */
        void menu.offsetWidth;
        /* The panel is translucent on purpose. Measure it now that it
           has laid out, so the scrim can start where the panel ends
           instead of double-darkening the page behind it. */
        menu.style.setProperty('--mm-panel-h', panel.offsetHeight + 'px');
        menu.classList.add('is-in');
        burger.setAttribute('aria-expanded', 'true');
        document.body.style.overflow = 'hidden';
        if (closeBtn) closeBtn.focus();
      }}

      function closeMenu(refocus) {{
        if (!openState) return;
        openState = false;
        menu.classList.remove('is-in');
        burger.setAttribute('aria-expanded', 'false');
        document.body.style.overflow = '';
        if (refocus) burger.focus();
        closeTimer = setTimeout(function () {{
          menu.classList.remove('is-open');
          menu.hidden = true;
        }}, reduced ? 0 : 260);
      }}

      burger.addEventListener('click', function () {{
        openState ? closeMenu(true) : openMenu();
      }});
      menu.addEventListener('click', function (e) {{
        if (e.target.closest('[data-mm-close]')) closeMenu(true);
        else if (e.target.closest('a[href]')) closeMenu(false);
      }});
      document.addEventListener('keydown', function (e) {{
        if (!openState) return;
        if (e.key === 'Escape') {{ e.preventDefault(); closeMenu(true); return; }}
        if (e.key !== 'Tab') return;
        var f = focusables();
        if (!f.length) return;
        var first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) {{ e.preventDefault(); last.focus(); }}
        else if (!e.shiftKey && document.activeElement === last) {{ e.preventDefault(); first.focus(); }}
      }});
      window.addEventListener('resize', function () {{
        if (openState && window.innerWidth > 900) closeMenu(false);
      }});
    }}
  }})();
</script>

<script>
/* Campaign attribution — session-scoped, no cookie. If this session's
   first page load carried campaign params (utm_*, gclid, fbclid, ref)
   or an external referrer, remember them in sessionStorage so the lead
   form and the traffic beacon can report the channel. First touch wins
   for the session; the server re-whitelists everything it receives. */
(function () {{
  try {{
    var KEY = '_sol_attr';
    if (sessionStorage.getItem(KEY)) return;
    var KEYS = ['utm_source','utm_medium','utm_campaign','utm_term','utm_content','gclid','fbclid','ref'];
    var qs = new URLSearchParams(location.search);
    var attr = {{}}; var found = false;
    for (var i = 0; i < KEYS.length; i++) {{
      var v = qs.get(KEYS[i]);
      if (v) {{ attr[KEYS[i]] = String(v).slice(0, 120); found = true; }}
    }}
    var ref = document.referrer || '';
    if (ref && ref.indexOf(location.hostname) === -1) {{
      attr.referrer = ref.slice(0, 300); found = true;
    }}
    if (!found) return;
    attr.landing_path = location.pathname.slice(0, 200);
    sessionStorage.setItem(KEY, JSON.stringify(attr));
  }} catch (e) {{ /* attribution must never break the page */ }}
}})();
</script>

<script>
/* First-party, anonymous traffic. No cookie is set: the session id lives
   in sessionStorage and dies with the tab, so it cannot follow anyone
   across visits or across sites. Do Not Track is honoured here AND again
   server-side. Nothing blocks render; failures are swallowed on purpose. */
(function () {{
  try {{
    if (navigator.doNotTrack === '1' || window.doNotTrack === '1') return;
    var KEY = '_sol_s';
    var sid = sessionStorage.getItem(KEY);
    if (!sid) {{
      sid = (Math.random().toString(36).slice(2) + Date.now().toString(36)).slice(0, 24);
      sessionStorage.setItem(KEY, sid);
    }}
    var w = window.innerWidth || 1024;
    var device = w < 700 ? 'mobile' : (w < 1024 ? 'tablet' : 'desktop');

    /* the session's campaign params, if any — whitelisted again server-side */
    var camp = null;
    try {{
      var a = JSON.parse(sessionStorage.getItem('_sol_attr') || 'null');
      if (a) {{
        camp = {{}};
        ['utm_source','utm_medium','utm_campaign','gclid','fbclid','ref'].forEach(function (k) {{
          if (a[k]) camp[k] = a[k];
        }});
        if (!Object.keys(camp).length) camp = null;
      }}
    }} catch (e) {{ camp = null; }}

    function send(event) {{
      var body = JSON.stringify({{
        s: sid, p: location.pathname, r: document.referrer || null,
        d: device, e: event, c: camp
      }});
      /* sendBeacon survives the page unloading; fetch is the fallback */
      if (navigator.sendBeacon) {{
        navigator.sendBeacon('/api/track', new Blob([body], {{ type: 'application/json' }}));
      }} else {{
        fetch('/api/track', {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }},
                              body: body, keepalive: true }}).catch(function () {{}});
      }}
    }}

    send('view');
    /* the two conversions worth knowing about */
    document.addEventListener('click', function (e) {{
      var a = e.target && e.target.closest && e.target.closest('a[href*="/start"], a[href*="get-started"], .btn-primary, .nav-cta');
      if (a) send('cta');
    }}, {{ passive: true }});
    window.addEventListener('solutionist:applied', function () {{ send('submit'); }});
  }} catch (e) {{ /* analytics must never break the page */ }}
}})();
</script>
{extra_scripts}
</body>
</html>"""


def _pixel_script() -> str:
    """The Meta Pixel, present ONLY while META_PIXEL_ID is configured —
    ads not running means no third-party script and the privacy page's
    advertising section stays hidden with it (legal_content.py gates on
    the same env var; they must move together). Honours Do Not Track
    exactly like the first-party analytics beacon does."""
    pid = (os.environ.get("META_PIXEL_ID") or "").strip()
    if not pid:
        return ""
    return (
        "<script>\n"
        "if (!(navigator.doNotTrack === '1' || window.doNotTrack === '1')) {\n"
        "!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?"
        "n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;"
        "n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;"
        "t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}"
        "(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');\n"
        f"fbq('init', '{pid}');\n"
        "fbq('track', 'PageView');\n"
        "}\n"
        "</script>"
    )


def _render_shell(*, title: str, description: str, content_html: str, path: str = "/",
                  active: str = "", extra_css: str = "", extra_scripts: str = "",
                  head_extra: str = "") -> str:
    """Render any page in the shared shell. `active` keys into the nav
    to mark the current page. Only about/features/compare still light a
    nav dot — faq, help and download moved to the footer when the bar was
    cut to four links, and Pricing is an in-page anchor with no active
    state of its own. The unused keys stay in the map so every existing
    caller keeps working.

    `head_extra` is raw markup for <head> — the news pages use it for
    Article schema. It is NOT escaped, so nothing derived from a post's
    text may be passed through it unescaped."""
    active_map = {
        "ax_home":        "is-active" if path == "/"            else "",
        "ax_features":    "is-active" if active == "features"    else "",
        "ax_compare":     "is-active" if active == "compare"     else "",
        "ax_faq":         "is-active" if active == "faq"         else "",
        "ax_about":       "is-active" if active == "about"       else "",
        "ax_help":        "is-active" if active == "help"        else "",
        "ax_download":    "is-active" if active == "download"    else "",
        "ax_get_started": "is-active" if active == "get_started" else "",
    }
    return _fill_trial(_fill_contact(SHELL_TEMPLATE.format(
        title=_html.escape(title),
        description=_html.escape(description),
        og_title=_html.escape(f"{title} · {SITE_NAME}"),
        path=path,
        shared_css=SHARED_CSS,
        extra_css=extra_css,
        contact_email=_html.escape(_public_contact_email()),
        business_name=_html.escape(BUSINESS_NAME),
        year=datetime.date.today().year,
        content=content_html,
        extra_scripts=extra_scripts,
        app_url=APP_URL,
        pixel_script=_pixel_script(),
        head_extra=head_extra,
        **active_map,
    )))


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
      /* ── command palette (features §1) ── */
      .pal{border-radius:10px;border:1px solid var(--line);background:var(--pane-2);overflow:hidden;
        box-shadow:0 18px 44px rgba(0,0,0,.55);}
      .pal-in{display:flex;align-items:center;gap:8px;padding:10px 12px;font-size:12px;
        border-bottom:1px solid var(--line);color:var(--ink);}
      .pal-ico{width:12px;height:12px;border-radius:50%;flex-shrink:0;
        border:1.5px solid var(--ink-3);}
      .pal-q{display:inline-block;overflow:hidden;white-space:nowrap;vertical-align:bottom;
        animation:palType 6s steps(21) infinite;}
      @keyframes palType{0%{width:0;}40%{width:21ch;}100%{width:21ch;}}
      .pal-in .caret{width:1.5px;height:13px;background:var(--gold);flex-shrink:0;
        animation:palCaret 1.05s step-end infinite;}
      @keyframes palCaret{50%{opacity:0;}}
      .pal-kbd{margin-left:auto;padding:1px 5px;border-radius:4px;font-size:8.5px;color:var(--ink-3);
        background:rgba(255,255,255,.06);border:1px solid var(--line);flex-shrink:0;}
      .pal-r{display:flex;align-items:center;gap:9px;padding:7px 12px;font-size:10.5px;color:var(--ink-2);}
      .pal-r.on{background:rgba(255,255,255,.07);color:var(--ink);}
      .pal-d{width:6px;height:6px;border-radius:50%;background:var(--c,#2E7DFF);flex-shrink:0;}
      .pal-r .k{margin-left:auto;font-size:8.5px;color:var(--ink-3);flex-shrink:0;
        border:1px solid var(--line);padding:0 5px;border-radius:4px;}
      .pal-voice{display:flex;align-items:center;gap:9px;margin-top:11px;font-size:9.5px;color:var(--ink-3);}
      .pal-voice .hint{margin-left:auto;}
      .pal-voice .wave{display:inline-flex;align-items:center;gap:2px;height:14px;flex-shrink:0;}
      .pal-voice .wave i{width:2px;border-radius:1px;background:var(--gold);height:30%;
        animation:palWave 1.1s ease-in-out infinite;}
      .pal-voice .wave i:nth-child(2){animation-delay:-.9s;} .pal-voice .wave i:nth-child(3){animation-delay:-.75s;}
      .pal-voice .wave i:nth-child(4){animation-delay:-.6s;}  .pal-voice .wave i:nth-child(5){animation-delay:-.45s;}
      .pal-voice .wave i:nth-child(6){animation-delay:-.3s;}  .pal-voice .wave i:nth-child(7){animation-delay:-.15s;}
      @keyframes palWave{0%,100%{height:26%;}50%{height:100%;}}

      /* ── unified inbox + contact record (features §3) ── */
      .inbox{display:grid;grid-template-columns:1.25fr .75fr;gap:9px;flex:1;min-height:0;}
      .pill.mail{color:#7DD3FC;background:rgba(125,211,252,.12);border:1px solid rgba(125,211,252,.3);}
      .pill.sms{color:#C4B5FD;background:rgba(196,181,253,.12);border:1px solid rgba(196,181,253,.3);}
      .rec{gap:8px;}
      .rec-h{display:flex;align-items:center;gap:8px;}
      .rec-h .av{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;
        font-size:8.5px;font-weight:800;color:#08090C;flex-shrink:0;}
      .rec-h .nm{font-size:11px;font-weight:600;color:var(--ink);line-height:1.25;}
      .rec-h .nm span{display:block;font-size:8.5px;font-weight:400;color:var(--ink-3);}
      .rec-g{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;}
      .rec-g div{padding:6px;border-radius:7px;background:rgba(255,255,255,.03);
        border:1px solid var(--line);text-align:center;}
      .rec-g b{display:block;font-family:var(--font-heading);font-size:12px;font-weight:700;color:var(--ink);}
      .rec-g span{font-size:7px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-3);}
      .rec-t{display:flex;flex-direction:column;gap:6px;font-size:9px;color:var(--ink-2);}
      .rec-t div{display:flex;align-items:center;gap:7px;}
      .rec-t .d{width:5px;height:5px;border-radius:50%;background:var(--gold);flex-shrink:0;}
      @media (max-width:520px){.inbox{grid-template-columns:1fr;} .rec{display:none;}}

      @media (prefers-reduced-motion: reduce){
        .pal-q{animation:none !important;width:21ch !important;}
        .pal-in .caret,.pal-voice .wave i{animation:none !important;}
      }

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
      .brief-mark{position:absolute;right:14%;bottom:10px;width:128px;height:128px;
        pointer-events:none;opacity:.92;
        filter:drop-shadow(0 0 26px rgba(124,58,237,.65)) drop-shadow(0 10px 22px rgba(0,0,0,.5));}
      .app.is-mini .brief-mark{display:none;}
      /* once .brief stacks on phones the mark lands on Chief's buttons */
      @media (max-width:700px){.brief-mark{display:none;}}
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
      /* ── the hero replica answers a question ──────────────────────
         The Chief panel types a question and answers it, on a 15s
         loop. Every string is HARDCODED — this makes no request to
         anything. It is the same fiction as the rest of the replica
         (Jordan Reyes is not real, $12,480 is not real), just moving.
         A live endpoint here would be an unauthenticated LLM surface
         that every crawler on the internet could bill us for.

         The numbers agree with the panel's own resting state: it says
         8 overdue / $1,865, so the answer names two of those eight
         rather than inventing a separate set of figures.

         Both faces are stacked, face A in flow and face B absolute on
         top of it, so the panel height is whatever face A needs and
         the swap cannot shift the hero. Everything is opacity and
         transform, nothing that triggers layout.

         One shared 15s timeline; each piece picks its moment with
         keyframe percentages. Character stagger is animation-delay,
         which permanently phase-shifts that character's own loop —
         which is exactly the intent. */
      .chief-body{position:relative;display:flex;flex-direction:column;gap:6px;}
      .chief-note{font-size:8px;color:var(--ink-3);opacity:.8;letter-spacing:.01em;}
      .cf{display:flex;flex-direction:column;gap:6px;}
      .cf-b{position:absolute;inset:0;opacity:0;}
      .cf-a{animation:cfA 15s ease infinite;}
      .cf-b{animation:cfB 15s ease infinite;}
      @keyframes cfA{0%,19%{opacity:1;}24%,85%{opacity:0;}91%,100%{opacity:1;}}
      @keyframes cfB{0%,23%{opacity:0;}28%,84%{opacity:1;}88%,100%{opacity:0;}}
      /* rows land one after another rather than as a block */
      .cf-b > *{opacity:0;transform:translateY(3px);animation:cfRow 15s ease infinite;}
      .cf-b > *:nth-child(1){animation-delay:.00s;}
      .cf-b > *:nth-child(2){animation-delay:.13s;}
      .cf-b > *:nth-child(3){animation-delay:.26s;}
      .cf-b > *:nth-child(4){animation-delay:.39s;}
      .cf-b > *:nth-child(5){animation-delay:.52s;}
      .cf-b > *:nth-child(6){animation-delay:.65s;}
      @keyframes cfRow{0%,24%{opacity:0;transform:translateY(3px);}
                       29%,84%{opacity:1;transform:translateY(0);}
                       87%,100%{opacity:0;transform:translateY(3px);}}

      .cin-wrap{position:relative;flex:1;min-width:0;overflow:hidden;white-space:nowrap;}
      .cin-ph{display:block;animation:cinPh 15s ease infinite;}
      @keyframes cinPh{0%,11%{opacity:1;}13%,88%{opacity:0;}92%,100%{opacity:1;}}
      .cin-q{position:absolute;left:0;top:0;white-space:nowrap;color:var(--ink-1,#fff);}
      .cin-q i{display:inline-block;max-width:0;overflow:hidden;opacity:0;font-style:normal;
        vertical-align:bottom;animation:cinCh 15s linear infinite;}
      @keyframes cinCh{0%,12.5%{max-width:0;opacity:0;}
                       14%,86%{max-width:1.6em;opacity:1;}
                       88%,100%{max-width:0;opacity:0;}}
      /* caret rides the end of the typed text because it is inline after it */
      .cin-q::after{content:'';display:inline-block;width:1px;height:8px;
        vertical-align:-1px;background:var(--gold);animation:cinCar 15s steps(1) infinite;}
      @keyframes cinCar{0%,11%{opacity:0;}
                        12%,34%{opacity:1;}35%{opacity:0;}37%{opacity:1;}
                        39%{opacity:0;}41%{opacity:1;}43%,100%{opacity:0;}}

      /* let people stop it and read */
      .chief:hover .cf-a,.chief:hover .cf-b,.chief:hover .cf-b > *,
      .chief:hover .cin-ph,.chief:hover .cin-q i,.chief:hover .cin-q::after{
        animation-play-state:paused;}

      /* rest on the honest static state, no motion at all */
      @media (prefers-reduced-motion: reduce){
        .chief .cf-b,.chief .cin-q{display:none;}
        .chief .cf-a,.chief .cin-ph{opacity:1;}
        .chief *{animation:none !important;}
      }


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


      /* ── phones: the replicas stop pretending to be a desktop window ──
         They were previously pinned at desktop pixel widths (748px faces,
         a 960px hero) inside a horizontally-scrolling strip, so on a 390px
         screen you saw a clipped middle band — "Invoices" rendered as
         "ces" and INV-2026-011 as "2026-011". Shrinking that to fit would
         have put the body type near 4px, so instead the mock RESPONDS the
         way the real app responds on a phone: the nav rail goes away, the
         KPI grid halves, and the secondary columns stack. ── */
      @media (max-width: 700px){
        .app{font-size:10.5px;}
        .app-side{display:none;}
        .app-strip{display:none;}
        .app-top{padding:8px 10px;gap:8px;}
        .at-cta, .at-urgent{display:none;}
        .app-canvas{padding:11px;gap:9px;}

        .kpi-row{grid-template-columns:repeat(2,1fr);}
        .kpi-row .kpi:nth-child(n+5){display:none;}
        .kpi .v{font-size:17px;}

        .age{grid-template-columns:repeat(3,1fr);gap:6px;}
        .age > div:nth-child(-n+2){display:none;}   /* the two $0.00 "nothing here" buckets */
        .age .v{font-size:12px;}
        .age .k{font-size:6.5px;letter-spacing:.09em;}

        .qa{grid-template-columns:repeat(4,1fr);}
        .qa i:nth-child(n+5){display:none;}

        /* the briefing's Chief column sits under it rather than beside */
        .brief{flex-direction:column;}
        .chief{width:auto;}
        .brief .hi{font-size:20px;}
        .brief .cp{max-width:none;}

        .ah-title{font-size:16px;}
        .arts{grid-template-columns:repeat(2,1fr);}
        .art:nth-child(3){display:none;}
        .chips span:nth-child(n+5){display:none;}
        .r .id{display:none;}
      }
      @media (max-width: 430px){
        .kpi-row .kpi:nth-child(n+3){display:none;}
        .qa i:nth-child(n+4){display:none;}
        .r .amt{font-size:9px;}
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


# ══════════════════════════════════════════════════════════════════════
# THE TRACE BOARD lived here until 2026-08-20 (BE#540-550 built it).
#
# It was the one visual arguing that the PARTS ARE CONNECTED — a real
# event walking a spine through Build / Operate / Grow. That argument is
# worth making. This was no longer the thing making it well:
#
#   * hairline strokes and 8px labels under a fold that had just been
#     given a full-size Mission Control panel — a schematic sitting
#     directly beneath a photograph,
#   * ~600 lines of CSS + JS shipped on every home page load for it,
#   * Chromium-only, so a chunk of visitors never saw it move anyway,
#   * and the device band now closes the page with the same claim made
#     in the product's own pixels instead of in wireframe.
#
# Removed on Kevin's call. `git show 31d7446:marketing_pages.py` has the
# whole thing if the argument needs a better vehicle later.
# ══════════════════════════════════════════════════════════════════════

SPINE_CSS = """
      .pspine{position:absolute;left:0;width:44px;pointer-events:none;z-index:2;}
      .pspine-rail,.pspine-lit{position:absolute;left:21px;top:0;width:1.5px;border-radius:1px;}
      .pspine-rail{height:100%;background:#1E2A3B;}
      .pspine-lit{height:0;background:var(--accent);opacity:.7;}
      .pspine-dot{position:absolute;left:17px;width:9px;height:9px;border-radius:50%;
        background:var(--bg);border:1.5px solid #1E2A3B;transform:translateY(-50%);
        transition:border-color .35s ease,background .35s ease;}
      .pspine-dot.on{border-color:var(--accent);background:#0B1220;}
      .pspine-dot.on::after{content:"";position:absolute;inset:2px;border-radius:50%;background:var(--accent);}
      @media (max-width:900px){
        .pspine{width:20px;}
        .pspine-rail,.pspine-lit{left:8px;}
        .pspine-dot{left:4.5px;width:7px;height:7px;}
      }
      @media (prefers-reduced-motion:reduce){
        .pspine-dot{transition:none;}
      }
"""


SPINE_SCRIPT = """
<script>
(function () {
  var marks = [].slice.call(document.querySelectorAll('[data-spine]'));
  if (marks.length < 2) return;   /* nothing to thread */

  var host = document.createElement('div');
  host.className = 'pspine';
  host.setAttribute('aria-hidden', 'true');
  var rail = document.createElement('span'); rail.className = 'pspine-rail';
  var lit  = document.createElement('span'); lit.className  = 'pspine-lit';
  host.appendChild(rail); host.appendChild(lit);
  var dots = marks.map(function () {
    var d = document.createElement('span');
    d.className = 'pspine-dot';
    host.appendChild(d);
    return d;
  });
  document.body.appendChild(host);

  var ys = [], y0 = 0, y1 = 1;

  function layout() {
    ys = marks.map(function (el) {
      var r = el.getBoundingClientRect();
      return r.top + window.pageYOffset + r.height / 2;
    });
    y0 = ys[0]; y1 = ys[ys.length - 1];
    host.style.top = y0 + 'px';
    host.style.height = Math.max(1, y1 - y0) + 'px';
    for (var i = 0; i < dots.length; i++) dots[i].style.top = (ys[i] - y0) + 'px';
    paint();
  }

  /* the reader's position is the middle of their screen, not its top —
     a section is "reached" when it is in front of them, not when its
     first pixel clears the fold */
  function paint() {
    var cur = window.pageYOffset + window.innerHeight * 0.55;
    var p = Math.max(0, Math.min(1, (cur - y0) / Math.max(1, y1 - y0)));
    lit.style.height = (p * 100) + '%';
    for (var i = 0; i < dots.length; i++) dots[i].classList.toggle('on', cur >= ys[i]);
  }

  layout();
  window.addEventListener('scroll', paint, { passive: true });
  window.addEventListener('resize', layout);
  /* fonts and images settle after DOMContentLoaded and move every marker */
  window.addEventListener('load', layout);
})();
</script>
"""


# ══════════════════════════════════════════════════════════════════════
# FOLD — the hero panel re-skins through the seven verticals it knows.
#
# The whole pitch is "tell it what you do and it arrives shaped around
# your work." That is a demonstrable claim, so the fold demonstrates it
# rather than asserting it: the sidebar relabels, the numbers change,
# and Chief says something only that business would say. The vocabulary
# here is the terminology the product actually ships (Regulars for a
# barber, Members for a ministry) — if that drifts, this drifts with it.
# ══════════════════════════════════════════════════════════════════════

TRADES_JS = """
  /* THE TRADE VOCABULARY — one source, two consumers.
     kpi = [label, value, footnote] x4 ; rows = [text, amount|null] x3 ;
     sugg = [name, sub, pill] x3. This is the terminology the product
     actually ships (Regulars for a barber, Members for a ministry) —
     if that drifts, this has to drift with it. The home fold reads it
     to rebuild Mission Control; Get Started reads it to show which
     room you would be handed. Neither owns it.  */
  var TRADES = [
    { word: 'barber', cap: 'for a barber', biz: 'Fade &amp; Co.', owner: 'Andre Whitfield', first: 'Andre',
      grp: 'The chair', nav: ['Regulars', 'Chair calendar', 'Walk-ins', 'Payments'],
      kpi: [['Chairs booked this week', '38', '4 open Friday'], ['Regulars', '124', '9 overdue for a cut'], ['Revenue \\u00b7 this month', '$6,910', '\\u25b2 12% vs last mo'], ['Business health', '61%', 'steady']],
      lead: 'I\\u2019ve analyzed your day. Here\\u2019s what I found:',
      ask: 'Want me to text them your Tuesday openings?',
      rows: [['3 regulars not rebooked', '6 weeks'], ['2 drafts waiting for you', null], ['$6,910 collected this month', null]],
      sugg: [['Marcus Bell', 'last cut 41 days ago', 'Text'], ['Tia Okonkwo', 'last cut 38 days ago', 'Text'], ['2 drafts pending review', 'from last night\\u2019s run', 'Open']],
      today: ['7', ['9:00 AM', 'Marcus Bell'], ['10:30 AM', 'Devon Pryce'], ['1:00 PM', 'Walk-in hold']] },
    { word: 'therapist', cap: 'for a therapist', biz: 'Vale Counseling', owner: 'Dana Vale', first: 'Dana',
      grp: 'The practice', nav: ['Clients', 'Sessions', 'Intake forms', 'Superbills'],
      kpi: [['Sessions this week', '22', '2 unconfirmed'], ['Active clients', '31', '4 on the waitlist'], ['Revenue \\u00b7 this month', '$9,340', '\\u25b2 9% vs last mo'], ['Business health', '74%', 'steady']],
      lead: 'Two things before your 9:00. Clinical notes stay in your EHR:',
      ask: 'Want me to send both a reminder?',
      rows: [['2 sessions unconfirmed', 'tomorrow'], ['1 intake form outstanding', null], ['$9,340 collected this month', null]],
      sugg: [['Priya Raman', 'unconfirmed for 9:00 AM', 'Remind'], ['Lewis Barr', 'intake form never opened', 'Resend'], ['3 superbills ready', 'for July sessions', 'Send']],
      today: ['5', ['9:00 AM', 'Priya Raman'], ['11:00 AM', 'Lewis Barr'], ['2:00 PM', 'Intake &mdash; new']] },
    { word: 'attorney', cap: 'for an attorney', biz: 'Okafor Law', owner: 'Ada Okafor', first: 'Ada',
      grp: 'The office', nav: ['Clients', 'Matters', 'Time &amp; billing', 'Trust ledger'],
      kpi: [['Unbilled hours', '14.5', 'across 6 matters'], ['Open matters', '19', '3 with deadlines'], ['Collected \\u00b7 this month', '$28,600', 'trust reconciled'], ['Business health', '68%', 'steady']],
      lead: 'Your book as of this morning:',
      ask: 'Want me to draft this month\\u2019s invoices?',
      rows: [['14.5 hours unbilled', '6 matters'], ['3 filing deadlines this week', null], ['Trust account reconciled', null]],
      sugg: [['Renner v. Colby', 'discovery due Thursday', 'Open'], ['Hartline LLC', '8.2 hours unbilled', 'Bill'], ['2 engagement letters', 'awaiting signature', 'Chase']],
      today: ['4', ['9:30 AM', 'Renner call'], ['11:00 AM', 'Hartline review'], ['3:00 PM', 'Filing deadline']] },
    { word: 'contractor', cap: 'for a contractor', biz: 'Halstead Build', owner: 'Ray Halstead', first: 'Ray',
      grp: 'The jobs', nav: ['Customers', 'Jobs', 'Estimates', 'Change orders'],
      kpi: [['Jobs scheduled', '9', '2 waiting on materials'], ['Estimates out', '6', '$41,200 in play'], ['Revenue \\u00b7 this month', '$18,750', '\\u25b2 14% vs last mo'], ['Business health', '57%', 'steady']],
      lead: 'Two jobs and one estimate need a decision:',
      ask: 'Want me to follow up on the estimate this morning?',
      rows: [['Kellerman estimate quiet', '11 days'], ['2 jobs waiting on materials', null], ['$18,750 collected this month', null]],
      sugg: [['Kellerman deck', 'estimate out 11 days', 'Follow up'], ['Bryce kitchen', 'change order unsigned', 'Send'], ['Materials delayed', '2 jobs affected', 'Reschedule']],
      today: ['4', ['7:30 AM', 'Kellerman site'], ['11:00 AM', 'Materials pickup'], ['2:30 PM', 'Bryce walkthrough']] },
    { word: 'coach', cap: 'for a coach', biz: 'Reyes &amp; Co.', owner: 'Jordan Reyes', first: 'Jordan',
      grp: 'The practice', nav: ['Clients', 'Programs', 'Sessions', 'Payments'],
      kpi: [['Active clients', '17', 'all in good standing'], ['Renewals this month', '3', 'none contacted yet'], ['Revenue \\u00b7 this month', '$12,480', '\\u25b2 18% vs last mo'], ['Business health', '61%', 'steady']],
      lead: 'I\\u2019ve analyzed your day. Here\\u2019s what I found:',
      ask: 'Want me to send the renewal offers now?',
      rows: [['3 renewals this month', 'uncontacted'], ['2 drafts waiting for you', null], ['$12,480 collected this month', null]],
      sugg: [['Marcus Bell', 'renews in 9 days', 'Offer'], ['Grace Okoye', 'renews in 14 days', 'Offer'], ['2 drafts pending review', 'from your last agent run', 'Open']],
      today: ['4', ['9:00 AM', 'Marcus Bell'], ['11:30 AM', 'Grace Okoye'], ['2:00 PM', 'Tia Okonkwo']] },
    { word: 'consultant', cap: 'for a consultant', biz: 'Northbridge', owner: 'Simone Aden', first: 'Simone',
      grp: 'The book', nav: ['Clients', 'Engagements', 'Proposals', 'Retainers'],
      kpi: [['Proposals out', '4', '2 quiet past ten days'], ['Live engagements', '7', '2 wrapping this month'], ['Retainer revenue', '$12,480', '\\u25b2 18% vs last mo'], ['Business health', '72%', 'steady']],
      lead: 'Your pipeline went quiet in two places:',
      ask: 'Want me to nudge both with the case study attached?',
      rows: [['2 proposals unanswered', '10+ days'], ['2 engagements wrapping', null], ['$12,480 in retainers this month', null]],
      sugg: [['Lowell Group', 'proposal out 12 days', 'Nudge'], ['Anders Co.', 'proposal out 10 days', 'Nudge'], ['Q3 wrap reports', '2 engagements ending', 'Draft']],
      today: ['3', ['10:00 AM', 'Lowell kickoff'], ['1:00 PM', 'Anders check-in'], ['4:00 PM', 'Q3 wrap draft']] },
    { word: 'pastor', cap: 'for a ministry', biz: 'Grace Chapel', owner: 'Elias Barrow', first: 'Elias',
      grp: 'The congregation', nav: ['Members', 'Services', 'Giving', 'Volunteers'],
      kpi: [['Giving this month', '$8,240', '\\u25b2 6% vs last mo'], ['Members', '218', '14 not seen in a month'], ['Volunteers serving', '34', '6 new this month'], ['Congregation health', '70%', 'steady']],
      lead: 'Before Sunday, two things worth your time:',
      ask: 'Want me to send each a check-in note?',
      rows: [['14 members not seen', 'a month'], ['3 volunteer slots open', null], ['$8,240 given this month', null]],
      sugg: [['14 members quiet', 'no attendance in 30 days', 'Check in'], ['Nursery Sunday', '2 slots unfilled', 'Ask'], ['Giving statements', 'ready for Q2', 'Send']],
      today: ['5', ['8:00 AM', 'Staff prayer'], ['12:00 PM', 'Hospital visit'], ['6:30 PM', 'Youth group']] }
  ];
"""

FOLD_SCRIPT = """
<script>
(function () {
  var word  = document.getElementById('heroWord');
  var chips = document.getElementById('heroChips');
  var stage = document.getElementById('foldStage');
  if (!word || !chips || !stage) return;

""" + TRADES_JS + """

  var IDS = ['heroCap','fdBiz','fdOwner','fdFirst','fdGrp','fdN1','fdN2','fdN3','fdN4',
             'fdK1','fdV1','fdF1','fdK2','fdV2','fdF2','fdK3','fdV3','fdF3','fdK4','fdV4','fdF4',
             'fdLead','fdAsk','fdR1','fdA1','fdR2','fdR3',
             'fdS1','fdS1b','fdS2','fdS2b','fdS3','fdS3b',
             'fdTn','fdT1','fdT1b','fdT2','fdT2b','fdT3','fdT3b'];
  var el = {};
  IDS.forEach(function (id) { el[id] = document.getElementById(id); });
  for (var k in el) { if (!el[k]) return; }   /* markup drifted — leave the static state alone */

  var reduced = window.matchMedia &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var idx = 0, timer = null, held = false;

  TRADES.forEach(function (t, i) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'hero-chip';
    b.textContent = t.word.charAt(0).toUpperCase() + t.word.slice(1);
    b.setAttribute('aria-pressed', i === 0 ? 'true' : 'false');
    b.addEventListener('click', function () { held = true; stop(); show(i); });
    chips.appendChild(b);
  });

  function show(i) {
    idx = i;
    var t = TRADES[i];
    stage.classList.add('is-swapping');
    window.setTimeout(function () {
      word.textContent      = t.word;
      el.heroCap.textContent = t.cap;
      /* .nm and .nm.g hold their label as a leading TEXT NODE with a
         nested span after it. textContent on the parent would delete
         that span, so the label is written to the text node instead. */
      el.fdOwner.firstChild.nodeValue = t.owner;
      el.fdBiz.innerHTML     = t.biz;
      el.fdFirst.textContent = t.first;
      el.fdGrp.textContent   = t.grp;
      for (var n = 0; n < 4; n++) { el['fdN' + (n + 1)].innerHTML = t.nav[n]; }
      for (var m = 0; m < 4; m++) {
        var s = String(m + 1);
        el['fdK' + s].innerHTML   = t.kpi[m][0];
        el['fdV' + s].textContent = t.kpi[m][1];
        el['fdF' + s].innerHTML   = t.kpi[m][2];
      }
      el.fdLead.innerHTML = t.lead;
      el.fdAsk.innerHTML  = t.ask;
      el.fdR1.innerHTML   = t.rows[0][0];
      el.fdA1.textContent = t.rows[0][1] || '';
      el.fdR2.innerHTML   = t.rows[1][0];
      el.fdR3.innerHTML   = t.rows[2][0];
      for (var g = 0; g < 3; g++) {
        var q = String(g + 1);
        el['fdS' + q].firstChild.nodeValue = t.sugg[g][0];
        el['fdS' + q + 'b'].innerHTML      = t.sugg[g][1];
        el['fdT' + q].firstChild.nodeValue = t.today[g + 1][0];
        el['fdT' + q + 'b'].innerHTML      = t.today[g + 1][1];
      }
      el.fdTn.textContent = t.today[0];
      stage.classList.remove('is-swapping');
    }, reduced ? 0 : 190);
    for (var c = 0; c < chips.children.length; c++) {
      chips.children[c].setAttribute('aria-pressed', c === i ? 'true' : 'false');
    }
  }

  function stop()  { if (timer) { window.clearInterval(timer); timer = null; } }
  function start() {
    /* held = the visitor picked one; that choice outranks the tour */
    if (!timer && !held && !reduced && !document.hidden) {
      timer = window.setInterval(function () { show((idx + 1) % TRADES.length); }, 3600);
    }
  }

  stage.addEventListener('mouseenter', stop);
  stage.addEventListener('mouseleave', start);
  chips.addEventListener('focusin', stop);
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { stop(); } else { start(); }
  });
  start();
})();
</script>
"""


# ══════════════════════════════════════════════════════════════════════
# THE DEVICE BAND — the page's closer
#
# A full-bleed scene 1680px wide that deliberately crops off BOTH edges,
# with the copy floating on top of it. The bleed is the point: a scene
# that ends inside the content column reads as a picture of the product;
# one that runs past the edges reads as the product being used somewhere
# past the screen.
#
# Three depth slots, read as three distances: a desktop bleeding off the
# left, the phone nearest and centre, and a second desktop bleeding off
# the right caught MID-DECISION (Chief's purchase order open, cursor
# resting on "Send it", never completing). Depth is scale + shadow weight
# + how low each sits. No 3D — the rooms carousel already owns that.
#
# NO scroll-linked anything. No parallax, no pinning, no reveal. This is
# the only section on the page that does not use `.reveal`, and that is
# deliberate (Kevin, 2026-08-19): the art has to read as already running
# when it comes into view, not as something that woke up for you.
#
# The screens are REPLICA KIT, not a second vocabulary — the same .app /
# .app-top / .app-side / .brief / .chief / .kpi-row / .qa the hero and
# the six room faces use, so the band cannot drift away from the rest of
# the page. Only what the kit has no word for is new here: the phone
# frame, the inventory table and the drafted-PO drawer.
#
# The fiction is the page's OWN fiction — Andre Whitfield at Fade & Co.,
# the barber the hero opens on, with the barber's vocabulary (Regulars,
# Chair calendar, Walk-ins). Nothing here is a real person or business.
#
# ── The video seam ────────────────────────────────────────────────────
# The plan is for the screen areas to become short muted looping video of
# the real app. Those recordings do not exist yet, so the band ships with
# the live replicas below, which move on their own 9s loop. When the
# loops are cut, each screen swaps to:
#     <video autoplay loop muted playsinline preload="none"
#            poster="/assets/dv-home-poster.webp"></video>
# with src assigned by a matchMedia hydrator so only the slots visible at
# the current width ever fetch, reduced-motion gets the poster and no src,
# and nothing loads until the band is near the viewport. Note before you
# add those routes: the live server ignores Range and answers 200 with the
# whole file (measured on /assets/demo.mp4 before ranges landed), which
# iOS Safari dislikes; /assets/film.mp4 answers ranges properly now,
# add a range-aware responder in the same pass.
# ══════════════════════════════════════════════════════════════════════

# The 55-second walkthrough. It sat on the home page until 2026-08-21,
# where it was the fifth place in a row the page showed the product:
# the fold panel, the Chief chat, the six-room carousel, this, and
# then the device band. It lives on /features now, which the home page
# already links to from the rooms section, and it is one constant plus
# one section so putting it back on the home page is two edits.
DEMO_CSS = """
      .demo-section{padding:128px 0;border-top:1px solid var(--border);}
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
"""

DEVICE_BAND_CSS = """
      /* Slot widths are variables so one media query re-sizes the whole
         scene — a wide monitor needs BIGGER screens, not the same ones
         adrift in more ground. */
      .dv{position:relative;overflow:hidden;isolation:isolate;padding:128px 0;
        --dv-a:868px;--dv-c:790px;--dv-b:254px;--dv-scale:1;--dv-stage:1680px;
        min-height:calc(368px + 452px * var(--dv-scale));}
      /* NO bottom fade here. There was one — 150px ramping to solid --bg —
         from when the screens hung past the section and ended on a hard
         cut line. Once they were raised to sit inside the band it had
         nothing left to soften, and stacked with the scene's own bottom
         stop it painted a flat black bar across the foot of the page.
         Both are gone; the screens simply end, on the section's own
         ground. (Reported 2026-08-19 as "a black strip" across the foot.) */

      /* ── the bloom behind the scene ──────────────────────────────
         Four blurred colour fields: accent blue carries it, cyan on the
         left, violet on the right. Ambient drift only, on the same
         cadence as the shell's .orb loops — nothing reads scroll. ── */
      .dv-glow{position:absolute;inset:0;z-index:0;pointer-events:none;overflow:hidden;}
      .dv-glow i{position:absolute;display:block;border-radius:50%;filter:blur(78px);}
      .dv-g1{left:50%;top:42px;width:1180px;height:520px;margin-left:-590px;opacity:.62;
        background:radial-gradient(50% 50% at 50% 50%, rgba(46,125,255,.44), rgba(46,125,255,0) 72%);
        animation:dvDrift1 24s ease-in-out infinite;}
      .dv-g2{left:6%;top:250px;width:680px;height:430px;opacity:.5;
        background:radial-gradient(50% 50% at 50% 50%, rgba(34,211,238,.34), rgba(34,211,238,0) 70%);
        animation:dvDrift2 30s ease-in-out infinite;}
      .dv-g3{right:2%;top:210px;width:720px;height:470px;opacity:.5;
        background:radial-gradient(50% 50% at 50% 50%, rgba(124,58,237,.40), rgba(124,58,237,0) 70%);
        animation:dvDrift3 27s ease-in-out infinite;}
      .dv-g4{left:50%;top:330px;width:900px;height:360px;margin-left:-450px;opacity:.5;
        background:radial-gradient(50% 50% at 50% 50%, rgba(29,99,230,.36), rgba(8,9,12,0) 72%);
        animation:dvDrift2 22s ease-in-out infinite reverse;}
      @keyframes dvDrift1{0%,100%{transform:translate(0,0) scale(1);}50%{transform:translate(34px,-22px) scale(1.06);}}
      @keyframes dvDrift2{0%,100%{transform:translate(0,0) scale(1);}50%{transform:translate(-40px,26px) scale(1.08);}}
      @keyframes dvDrift3{0%,100%{transform:translate(0,0) scale(1);}50%{transform:translate(26px,-30px) scale(1.05);}}
      /* a fine grain over the bloom — without it the gradients band into
         visible steps on a wide monitor */
      .dv-grain{position:absolute;inset:0;z-index:1;pointer-events:none;opacity:.16;mix-blend-mode:overlay;
        background-image:radial-gradient(rgba(255,255,255,.5) .5px, transparent .5px);background-size:3px 3px;}

      .dv-copy{position:relative;z-index:4;max-width:780px;margin:0 auto;padding:0 28px;text-align:center;}
      .dv-copy h2{margin:18px 0 0;text-shadow:0 2px 30px rgba(8,9,12,.9);}
      .dv-lead{font-size:18px;color:var(--text-secondary);line-height:1.62;max-width:54ch;margin:16px auto 0;
        text-shadow:0 1px 22px rgba(8,9,12,.9);}
      .dv-ctas{display:flex;justify-content:center;gap:12px;margin-top:30px;flex-wrap:wrap;}
      .dv-note{margin-top:16px;font-size:12.5px;color:var(--text-dim);}

      /* ── the oversized scene ── */
      .dv-scene{position:relative;z-index:2;height:calc(452px * var(--dv-scale));margin-top:86px;}
      /* The stage is composed ONCE at 1680 and then scaled as a whole on a
         wide monitor. Widening it instead (tried first) left the replica's
         fixed 11px type marooned in a much bigger box — the screens read
         as empty. Scaling keeps the density the kit was drawn at, keeps
         the type vector-crisp, and keeps the crop: every step below is
         chosen so 1680 x scale is wider than the viewport it serves. */
      .dv-stage{position:absolute;left:50%;bottom:0;width:var(--dv-stage);height:540px;
        transform:translateX(-50%) scale(var(--dv-scale));transform-origin:bottom center;}
      .dv-slot{position:absolute;}
      /* each screen throws its own tinted bloom onto the ground behind it */
      .dv-slot::before{content:'';position:absolute;left:-8%;right:-8%;top:14%;bottom:-16%;z-index:-1;
        filter:blur(58px);border-radius:50%;}
      .dv-a{left:-150px;bottom:-48px;width:var(--dv-a);}
      .dv-a::before{background:radial-gradient(50% 50% at 50% 50%, rgba(46,125,255,.30), rgba(46,125,255,0) 70%);}
      .dv-c{right:-150px;bottom:10px;width:var(--dv-c);}
      .dv-c::before{background:radial-gradient(50% 50% at 50% 50%, rgba(124,58,237,.30), rgba(124,58,237,0) 70%);}
      .dv-b{left:50%;margin-left:calc(var(--dv-b) / -2);bottom:-40px;width:var(--dv-b);z-index:4;}
      .dv-b::before{background:radial-gradient(50% 50% at 50% 50%, rgba(34,211,238,.30), rgba(34,211,238,0) 68%);}
      .dv-a .app,.dv-c .app{aspect-ratio:16/10;height:auto;}
      .dv-a .app{box-shadow:0 60px 120px -34px rgba(0,0,0,.86),0 24px 50px -18px rgba(0,0,0,.6),
        0 0 0 1px rgba(0,0,0,.6),0 1px 0 rgba(255,255,255,.06) inset;}
      .dv-c .app{box-shadow:0 70px 130px -34px rgba(0,0,0,.9),0 26px 56px -18px rgba(0,0,0,.66),
        0 0 0 1px rgba(0,0,0,.6),0 1px 0 rgba(255,255,255,.07) inset;}
      /* the sheen that stops the glass reading as flat paper */
      .dv-slot .app,.dv-fone{position:relative;}
      .dv-slot .app::after,.dv-fone::after{content:'';position:absolute;inset:0;pointer-events:none;z-index:9;
        border-radius:inherit;background:linear-gradient(147deg, rgba(255,255,255,.055), rgba(255,255,255,0) 34%);}
      /* the scene dissolves into the ground instead of ending on an edge */
      /* NO scrim on the scene. There was one — solid --bg at the top of
         the scene box, out by 15% — meant to seat the art under the copy.
         But the stage is taller than the scene and overflows upward, so
         the screens START ABOVE the scene box: measured, that scrim's
         solid line landed 137-156px INSIDE the tops of all three screens
         and its end drew a hard horizontal edge across them. That edge is
         what was reported. Legibility is handled where it belongs — the
         copy gets clear air below it (.dv-scene margin) and a soft radial
         behind it (.dv-shade), neither of which has an edge to see. */
      .dv-shade{position:absolute;left:50%;top:-470px;width:1180px;height:480px;margin-left:-590px;z-index:3;
        pointer-events:none;background:radial-gradient(50% 50% at 50% 50%, rgba(8,9,12,.72), rgba(8,9,12,0) 74%);}

      /* ── the phone (the kit has no word for one) ── */
      .dv-fone{--ink:#F2F4F8;--ink-2:#A9B0BD;--ink-3:#6E7684;--pane:#101319;
        --line:rgba(255,255,255,.07);--gold:#C9A84C;--vio:#7C3AED;
        display:flex;flex-direction:column;overflow:hidden;color:var(--ink);
        aspect-ratio:9/19.5;border-radius:30px;border:6px solid #15181F;background:#080A0E;
        font-size:11px;line-height:1.42;
        box-shadow:0 0 0 1px rgba(255,255,255,.1),0 60px 100px -26px rgba(0,0,0,.94),
                   0 18px 40px -12px rgba(0,0,0,.7);}
      .dv-fone::before{content:'';position:absolute;top:7px;left:50%;transform:translateX(-50%);
        width:56px;height:12px;border-radius:99px;background:#05070A;z-index:8;
        box-shadow:0 0 0 1px rgba(255,255,255,.05);}
      .dv-fone-top{display:flex;align-items:center;gap:6px;padding:24px 12px 9px;
        border-bottom:1px solid var(--line);}
      .dv-fone-top .mk{width:15px;height:15px;border-radius:5px;flex-shrink:0;
        background:linear-gradient(135deg,#E879F9,#22D3EE);}
      .dv-fone-top b{font-family:var(--font-heading);font-size:12px;font-weight:600;letter-spacing:-.02em;}
      .dv-fone-top .on{margin-left:auto;display:inline-flex;align-items:center;gap:4px;font-size:7.5px;
        font-weight:600;color:#22C55E;}
      .dv-fone-top .on::before{content:'';width:4px;height:4px;border-radius:50%;background:#22C55E;
        box-shadow:0 0 6px #22C55E;}
      .dv-chat{flex:1;padding:10px;display:flex;flex-direction:column;gap:7px;min-height:0;
        background:radial-gradient(100% 60% at 50% 0%, rgba(124,58,237,.10), transparent 62%);}
      .dv-msg{padding:7px 9px;border-radius:12px;font-size:9.5px;line-height:1.45;max-width:88%;}
      .dv-msg.you{align-self:flex-end;border-bottom-right-radius:5px;color:var(--ink);
        background:color-mix(in srgb, var(--gold) 18%, transparent);
        border:1px solid color-mix(in srgb, var(--gold) 30%, transparent);}
      .dv-msg.ai{border-bottom-left-radius:5px;background:var(--pane);border:1px solid var(--line);
        color:var(--ink-2);}
      .dv-card{margin-top:auto;padding:10px;border-radius:12px;
        background:linear-gradient(165deg,#161A22,#0F1218);
        border:1px solid color-mix(in srgb, var(--gold) 34%, transparent);
        box-shadow:0 10px 30px rgba(0,0,0,.5), 0 0 22px rgba(201,168,76,.10) inset;}
      .dv-card .k{font-size:6.5px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);}
      .dv-card .v{font-family:var(--font-heading);font-size:17px;font-weight:700;margin:2px 0 1px;
        letter-spacing:-.03em;font-variant-numeric:tabular-nums;}
      .dv-card .s{font-size:8px;color:var(--ink-3);margin-bottom:8px;}
      .dv-card .go{position:relative;overflow:hidden;display:block;text-align:center;padding:7.5px;
        border-radius:9px;background:var(--gold);color:#1A1405;font-size:10px;font-weight:700;
        box-shadow:0 4px 14px rgba(201,168,76,.26);}
      .dv-fone-bar{display:flex;align-items:center;gap:7px;margin:0 10px 8px;padding:8px 10px;border-radius:11px;
        background:var(--pane);border:1px solid var(--line);font-size:8.5px;color:var(--ink-3);}
      .dv-fone-bar .mic{margin-left:auto;width:11px;height:11px;border-radius:3px;
        background:color-mix(in srgb, var(--gold) 55%, transparent);}
      .dv-fone-home{width:78px;height:3px;border-radius:99px;background:rgba(255,255,255,.22);margin:0 auto 7px;}

      /* ── inventory + the drafted PO (slot C) ── */
      /* The table sits BESIDE the drawer, not under it. Under it, the only
         part of the list that cleared the drawer was the on-hand column,
         which read as a black panel with loose digits in it rather than as
         an inventory. It also runs full height with enough rows to fill —
         a stretched panel with seven rows in it is the same black box. */
      .dv-inv{border-radius:9px;border:1px solid var(--line);background:var(--pane);overflow:hidden;
        flex:1;min-height:0;margin-left:262px;}
      .dv-inv .h,.dv-inv .t{display:grid;grid-template-columns:1fr 62px 44px 78px;gap:8px;align-items:center;
        padding:6px 11px;border-bottom:1px solid var(--line);}
      .dv-inv .h{font-size:7px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-3);
        background:rgba(255,255,255,.02);}
      .dv-inv .t{font-size:9.5px;position:relative;}
      .dv-inv .t:last-child{border-bottom:none;}
      .dv-inv .t .nm{color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
      .dv-inv .t .n{font-variant-numeric:tabular-nums;color:var(--ink);font-size:9px;}
      .dv-inv .t.low{background:linear-gradient(90deg,
        color-mix(in srgb, var(--gold) 9%, transparent), transparent 42%);}
      .dv-inv .t.low::before{content:'';position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--gold);
        animation:dvPulse 9s ease-in-out infinite;}
      @keyframes dvPulse{0%,100%{opacity:.34;}12%,20%{opacity:1;}40%{opacity:.34;}}

      /* The drawer sits on the LEFT of this screen even though the real
         app opens it from the right: slot C bleeds off the RIGHT edge, so
         anything anchored there is the first thing cropped away. Built it
         right-anchored first and measured — at 2560 only 21px of the
         drafted order survived, which is the one thing this screen exists
         to show. It clears the header rather than covering it. */
      .dv-po{position:absolute;top:70px;left:9px;bottom:9px;width:252px;border-radius:11px;padding:11px;
        background:linear-gradient(165deg,#151821,#0F1218);
        border:1px solid color-mix(in srgb, var(--gold) 36%, transparent);
        box-shadow:30px 0 60px rgba(0,0,0,.66), 0 0 26px rgba(201,168,76,.10) inset;
        display:flex;flex-direction:column;gap:6px;
        animation:dvPoIn 9s cubic-bezier(.2,.85,.25,1) infinite;}
      @keyframes dvPoIn{0%,10%{opacity:0;transform:translateX(-26px);}22%,100%{opacity:1;transform:none;}}
      .dv-po .k{font-size:7px;font-weight:800;letter-spacing:.15em;text-transform:uppercase;color:var(--gold);}
      .dv-po .t{font-family:var(--font-heading);font-size:13px;font-weight:600;letter-spacing:-.025em;}
      .dv-po .s{font-size:8px;color:var(--ink-3);margin-top:-3px;}
      .dv-po .li{display:flex;justify-content:space-between;gap:8px;font-size:8.5px;color:var(--ink-2);
        padding:4.5px 0;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums;}
      .dv-po .li b{color:var(--ink);font-weight:500;white-space:nowrap;}
      .dv-po .tot{display:flex;justify-content:space-between;font-size:10px;font-weight:700;padding-top:5px;
        font-variant-numeric:tabular-nums;}
      .dv-po .why{font-size:7.5px;color:var(--ink-3);line-height:1.45;padding:6px 7px;border-radius:7px;
        background:rgba(255,255,255,.03);border:1px solid var(--line);}
      .dv-po .acts{display:flex;gap:6px;margin-top:auto;position:relative;}
      .dv-po .go{flex:1;text-align:center;padding:6.5px;border-radius:8px;background:var(--gold);color:#1A1405;
        font-size:9.5px;font-weight:700;box-shadow:0 4px 14px rgba(201,168,76,.26);}
      .dv-po .alt{flex:1;text-align:center;padding:6.5px;border-radius:8px;background:rgba(255,255,255,.05);
        color:var(--ink-2);font-size:9.5px;font-weight:600;border:1px solid rgba(255,255,255,.16);}
      /* the cursor comes to rest on "Send it" and stops. It never lands —
         that is the whole argument of this screen. */
      .dv-cursor{position:absolute;left:44px;top:15px;width:12px;height:12px;border-radius:50%;
        border:1.5px solid rgba(255,255,255,.92);background:rgba(255,255,255,.2);
        box-shadow:0 0 0 4px rgba(255,255,255,.06);
        animation:dvCursor 9s cubic-bezier(.2,.85,.25,1) infinite;}
      @keyframes dvCursor{0%,26%{opacity:0;transform:translate(18px,12px);}38%,100%{opacity:1;transform:none;}}
      .dv-canvas{position:relative;}

      /* ── the loops (one shared 9s period, so the band reads as one scene) ── */
      .dv-drop{animation:dvDrop 9s cubic-bezier(.2,.8,.25,1) infinite;}
      @keyframes dvDrop{0%,8%{opacity:0;transform:translateY(-7px);}18%,100%{opacity:1;transform:none;}}
      .dv-roll{height:20px;overflow:hidden;}
      .dv-roll span{display:block;height:20px;animation:dvRoll 9s cubic-bezier(.7,0,.2,1) infinite;}
      @keyframes dvRoll{0%,24%{transform:translateY(0);}34%,100%{transform:translateY(-20px);}}
      .dv-say{animation:dvSay 9s ease-out infinite;}
      .dv-say-2{animation:dvSay 9s ease-out infinite;animation-delay:.5s;}
      .dv-say-3{animation:dvSay 9s ease-out infinite;animation-delay:1.1s;}
      @keyframes dvSay{0%,10%{opacity:0;transform:translateY(7px);}20%,100%{opacity:1;transform:none;}}
      .dv-tap{position:absolute;left:50%;top:50%;width:8px;height:8px;margin:-4px 0 0 -4px;border-radius:50%;
        background:rgba(26,20,5,.5);animation:dvTap 9s ease-out infinite;}
      @keyframes dvTap{0%,66%{transform:scale(0);opacity:.7;}84%,100%{transform:scale(16);opacity:0;}}
      /* let people stop it and read, the same courtesy the hero panel gives */
      .dv-slot:hover .dv-drop,.dv-slot:hover .dv-roll span,.dv-slot:hover .dv-po,
      .dv-slot:hover .dv-cursor,.dv-slot:hover .dv-say,.dv-slot:hover .dv-say-2,
      .dv-slot:hover .dv-say-3,.dv-slot:hover .dv-tap,.dv-slot:hover .dv-inv .t.low::before{
        animation-play-state:paused;}

      /* ── recomposed, not shrunk ───────────────────────────────────
         Narrow widths get a DIFFERENT scene. Shrinking one wide picture
         would put the product type near 4px, which is the same mistake
         the replicas already learned at 700px. ── */
      /* A wide monitor is served by BOTH dials, in a deliberate ratio.
         Scale alone reached the edges but blew the screens up to 1370px
         (measured) — the product read as a wall, not as devices in a
         room. Stage width alone kept them small but parked them in two
         holes of bare ground. So each step widens the stage a little and
         scales a little, and every step keeps stage x scale ahead of the
         viewport it serves — that product is what guarantees the crop. */
      @media (min-width:1600px){ .dv{--dv-stage:1780px;--dv-scale:1.06;} }  /* 1887 */
      @media (min-width:1850px){ .dv{--dv-stage:1900px;--dv-scale:1.12;} }  /* 2128 */
      @media (min-width:2100px){ .dv{--dv-stage:2040px;--dv-scale:1.18;} }  /* 2407 */
      @media (min-width:2400px){ .dv{--dv-stage:2180px;--dv-scale:1.24;} }  /* 2703 */
      @media (min-width:2700px){ .dv{--dv-stage:2320px;--dv-scale:1.32;} }  /* 3062 */
      @media (min-width:3000px){ .dv{--dv-stage:2500px;--dv-scale:1.40;} }  /* 3500 */

      /* Every narrow step re-aims the stage as well as the slots, against
         one rule: the drafted PO — the single thing slot C exists to show
         — has to land FULLY on screen. The first pass kept the wide
         geometry and only swapped slots in and out; measured, that put the
         PO entirely past the right edge between 1000 and 1199 and left the
         phone half off at 700. Bleed is worth nothing if it eats the
         payload. */
      @media (max-width:1199px){
        .dv{--dv-stage:1180px;}
        .dv-a{display:none;}
        .dv-c{right:-150px;--dv-c:756px;}
        .dv-b{left:22%;margin-left:0;}
      }
      @media (max-width:999px){
        .dv{padding-top:90px;--dv-stage:980px;}
        .dv-scene{height:398px;}
        .dv-c{right:-140px;--dv-c:648px;bottom:12px;}
        .dv-b{left:30%;--dv-b:228px;bottom:-72px;}
        .dv-g1{width:820px;margin-left:-410px;}
      }
      /* 700 matches the replica kit's OWN phone breakpoint: below it the
         .app drops its sidebar, and that is what makes room for the
         drawer once the screen is this narrow. */
      @media (max-width:700px){
        .dv{padding-top:76px;--dv-stage:620px;}
        .dv-lead{font-size:16px;}
        .dv-ctas{flex-direction:column;align-items:stretch;padding:0 18px;}
        .dv-ctas .btn-primary,.dv-ctas .btn-secondary{justify-content:center;}
        /* stage height == the phone's own height less its hang, so the
           scene cannot overflow UPWARD into the copy. Measured before
           this: the 594px-tall phone rose 136px past the top of the
           scene and sat on top of the two buttons. */
        .dv-scene{height:462px;}
        .dv-stage{height:508px;}
        .dv-c{right:-168px;--dv-c:528px;bottom:52px;}
        .dv-b{left:50%;--dv-b:240px;margin-left:calc(var(--dv-b) / -2);bottom:-26px;}
        .dv-shade{width:640px;margin-left:-320px;top:-400px;height:400px;}
        .dv-g1{width:620px;margin-left:-310px;height:420px;}
        .dv-g2,.dv-g3{width:460px;height:340px;}
      }
      @media (max-width:429px){
        .dv-scene{height:496px;}
        .dv-stage{height:542px;}
        .dv-c{display:none;}                            /* the phone stands alone */
        .dv-b{--dv-b:256px;bottom:-26px;}
      }

      /* rest on the poster state: everything still composed, nothing moving */
      @media (prefers-reduced-motion: reduce){
        .dv-glow i,.dv-drop,.dv-roll span,.dv-po,.dv-cursor,.dv-say,.dv-say-2,.dv-say-3,
        .dv-tap,.dv-inv .t.low::before{animation:none !important;}
        .dv-tap{display:none;}
      }
"""


# ══════════════════════════════════════════════════════════════════════
# Live plan dials for site copy
# ══════════════════════════════════════════════════════════════════════

def _tier_dials() -> dict:
    """The live plan numbers, from the same dials the app's Billing
    cards read (feature_gates.plan_limits + chief_models). This page
    carried hand-typed numbers through two rescales; rendering the
    dials at request time means the site cannot drift from the product
    again. analysis is the vendor-neutral wording (2026-08-19 ruling:
    the public site never names AI models — providers will diversify);
    it is "" while a CHIEF_MODEL_DEEP override has the tier ladder
    switched off, and the page drops the line rather than promise a
    difference nobody would get."""
    import chief_models
    import feature_gates
    import pricing_config
    prices = pricing_config.tier_price_cents()
    out = {}
    for plan, lim in feature_gates.plan_limits().items():
        banks = lim.get("plaid_connections")
        out[plan] = {
            "price": f"${prices.get(plan, 0) // 100}",
            "price_num": prices.get(plan, 0) // 100,
            "credits": f"{lim['chief_messages_monthly']:,}",
            "seats": lim["max_seats"],
            "businesses": lim["max_businesses"],
            "banks": "Unlimited" if banks is None else str(banks),
            "analysis": chief_models.deep_analysis_label(plan) or "",
        }
    return out


def _price_cards_html() -> str:
    """The home page's three price cards, numbers from the dials."""
    d = _tier_dials()

    def card(plan: str, name: str, blurb: str, mid: bool = False) -> str:
        t = d[plan]
        seats = "1 seat" if t["seats"] == 1 else f"{t['seats']} team seats"
        biz = "1 business" if t["businesses"] == 1 else f"{t['businesses']} businesses"
        banks = ("Unlimited bank connections" if t["banks"] == "Unlimited"
                 else f"{t['banks']} bank connections")
        model_li = f"<li>{t['analysis']} deep analysis</li>" if t["analysis"] else ""
        return f"""
      <div class="price-card{' is-mid' if mid else ''}">
        <div class="price-name">{name}</div>
        <div class="price-fig"><b class="pc-num" data-to="{t['price_num']}" data-prefix="$">{t['price']}</b><span>/month</span></div>
        <p>{blurb}</p>
        <ul class="price-facts">
          <li>{t['credits']} AI actions a month</li>
          {model_li}
          <li>{seats} &middot; {biz}</li>
          <li>{banks}</li>
        </ul>
        <a class="price-cta{' is-mid' if mid else ''}" href="/start?plan={plan}">Start with {name} &rarr;</a>
      </div>"""

    return (
        card("starter", "Starter",
             "The full workspace. Contacts, invoicing, scheduling, content, goals, your site, and Chief.")
        + card("professional", "Professional",
               "Everything in Starter, plus Autopilot running overnight and deeper Chief automation.",
               mid=True)
        + card("practice", "Solutionist",
               "For the operator running everything through the system: "
               "everything in Professional, plus room for a team and more than one business.")
    )


# Feature rows for the tier table on /compare — keys are
# feature_gates.FEATURE_MIN_PLAN entries; only labeled features render,
# so an unlabeled future gate never leaks a raw key onto the site.
_SITE_FEATURE_LABELS = (
    ("general_ledger", "General Ledger &amp; Trial Balance"),
    ("reports_full", "Full financial reports"),
    ("period_close", "Period closing"),
    ("contractor_payments", "Contractor payments + 1099"),
    ("accountant_package", "Year-end accountant package"),
    ("sourcing_desk", "Sourcing Desk — find &amp; RFQ vendors"),
    ("vertical_ledgers", "Trust accounting check (IOLTA)"),
    ("vertical_reports", "Compliance reports (trust reconciliation, 990 prep)"),
    ("accountant_collaborator", "Accountant collaborator seat"),
    ("audit_trail", "Audit trail"),
)


def _plan_compare_section_html() -> str:
    """Tier-vs-tier table for /compare — the same rows the in-app
    comparison shows, driven by the same feature map and dials."""
    import feature_gates
    d = _tier_dials()
    plans = ("starter", "professional", "practice")

    def num_row(label, value):
        cells = "".join(f"<td>{value(d[p])}</td>" for p in plans)
        return f"<tr><td>{label}</td>{cells}</tr>"

    rows = [
        num_row("AI actions / month", lambda t: t["credits"]),
        num_row("Team seats", lambda t: t["seats"]),
        num_row("Businesses", lambda t: t["businesses"]),
        num_row("Bank connections", lambda t: t["banks"]),
    ]
    if all(d[p]["analysis"] for p in plans):
        rows.insert(1, num_row("Deep analysis", lambda t: t["analysis"]))
    rank = feature_gates._PLAN_RANK
    for key, label in _SITE_FEATURE_LABELS:
        min_plan = feature_gates.FEATURE_MIN_PLAN.get(key)
        if not min_plan:
            continue
        cells = "".join(
            '<td class="sol">✓</td>' if rank.get(p, 0) >= rank.get(min_plan, 99)
            else '<td class="alt">&mdash;</td>'
            for p in plans)
        rows.append(f"<tr><td>{label}</td>{cells}</tr>")
    header = "".join(
        f'<th class="sol-col">{name} {d[p]["price"]}/mo</th>'
        for p, name in zip(plans, ("Starter", "Professional", "Solutionist")))
    return f"""
<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">Which plan</span>
      <h2>Every plan is the whole product.</h2>
      <p>Bigger plans add AI headroom, deeper analysis, seats for a team, and room for more than one business.</p>
    </div>
    <div class="table-wrap reveal reveal-delay-1">
      <table class="compare plans">
        <thead><tr><th>What you get</th>{header}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    <div class="compare-door reveal reveal-delay-2">
      <a class="btn-primary" href="/start">Start your free trial &rarr;</a>
      <span>__TRIAL_FREE__ on any plan, then the one you picked. Switch tier or
        cancel from inside the app; nothing here is locked in.</span>
    </div>
  </div>
</section>
"""


def render_home() -> str:
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
      /* Wide screens: the VISUAL column grows, prose does not. `.container`
         stays at 1140 — a 1700px line of body copy is unreadable — while
         `.container-xl` carries the product art, and art wants the room.
         These live HERE, not in SHARED_CSS: the shell is injected first,
         so a media query up there loses to this base rule on source order
         (media queries add no specificity). Measured dead before moving. */
      @media (min-width:1800px){ .container-xl{max-width:1560px;} }
      @media (min-width:2200px){ .container-xl{max-width:1720px;} }
      @media (max-width:640px){.container-xl{padding:0 20px;}}

""" + REPLICA_KIT_CSS + """

      /* ══════════════════════════════════════════════════════════════
         HERO — the claim on the left, the claim happening on the right

         The fold used to be copy alone over black: 41 words, no product,
         and roughly the right 45% empty from the subhead down. Widening
         the headline to 1180px closed the hole on line one only. The
         panel now fills it, and it re-skins through the seven verticals
         so the first screen performs "it already knows your business"
         instead of asserting it.

         The full 540px Mission Control replica that used to sit at
         1363px — two screens down, where nobody met it — is gone: this
         panel says the same thing inside the fold, and §04 already
         carries the room-by-room detail.
         ══════════════════════════════════════════════════════════════ */
      /* One number, no exceptions — the hero included. An earlier pass
   welded the hero to .trust and gave the pair their own spacing;
   that made the fold the one place on the page playing by
   different rules. */
      .hero{position:relative;padding:128px 0;overflow:hidden;}
      /* The closer at the foot of the page sits in a drifting colour
         field; the fold had a single flat radial. Same instrument at both
         ends now, so the page opens and closes on the same light. The
         drift keyframes are DEVICE_BAND_CSS's — both blocks ship on this
         document, and two copies of the same animation would be two
         things to keep in step. */
      .hero-glow{position:absolute;inset:0;z-index:0;pointer-events:none;overflow:hidden;}
      .hero-glow i{position:absolute;display:block;border-radius:50%;filter:blur(84px);}
      .hg1{left:50%;top:-190px;width:1240px;height:760px;margin-left:-930px;opacity:.85;
        background:radial-gradient(50% 50% at 50% 50%, rgba(46,125,255,.58), rgba(46,125,255,0) 70%);
        animation:dvDrift1 24s ease-in-out infinite;}
      .hg2{left:50%;top:-110px;width:900px;height:680px;margin-left:-190px;opacity:.62;
        background:radial-gradient(50% 50% at 50% 50%, rgba(124,58,237,.52), rgba(124,58,237,0) 70%);
        animation:dvDrift3 27s ease-in-out infinite;}
      .hg3{left:50%;top:300px;width:820px;height:540px;margin-left:-890px;opacity:.5;
        background:radial-gradient(50% 50% at 50% 50%, rgba(34,211,238,.40), rgba(34,211,238,0) 70%);
        animation:dvDrift2 30s ease-in-out infinite;}
      /* .hero is overflow:hidden and .hg3 runs past its foot, so the
         bloom was being guillotined at the section edge. Fade it with a
         MASK, not a dark overlay: an overlay paints the hero's last
         190px to pure --bg, and `.trust` below carries a 3% accent tint,
         so the "fix" drew a brighter-below ruled line exactly where the
         seam was supposed to disappear. Masking removes light instead of
         adding ink, and the boundary goes back to being only the tint. */
      .hero-glow{-webkit-mask-image:linear-gradient(to bottom, #000 64%, rgba(0,0,0,0) 99%);
        mask-image:linear-gradient(to bottom, #000 64%, rgba(0,0,0,0) 99%);}
      .hero-grain{position:absolute;inset:0;z-index:1;pointer-events:none;opacity:.14;mix-blend-mode:overlay;
        background-image:radial-gradient(rgba(255,255,255,.5) .5px, transparent .5px);background-size:3px 3px;}
      @media (prefers-reduced-motion: reduce){.hero-glow i{animation:none !important;}}
      .hero .container-xl{position:relative;z-index:1;}

      /* min-width:0 on both tracks — a grid child's automatic minimum is
         its content, and the panel's own flex row would otherwise push
         the column past the container instead of shrinking inside it */
      .hero-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.04fr);
        gap:clamp(30px,3.4vw,54px);align-items:center;}
      .hero-copy{min-width:0;}
      .hero h1{margin:0 0 22px;font-size:clamp(34px,4.9vw,78px);line-height:1.0;
        letter-spacing:-.042em;text-wrap:balance;}
      /* `.gradient-text` is flat accent everywhere by design (the blue-led
         palette pass killed gradient text site-wide). The one statement
         the whole company is named after gets the exception, and only
         here — blue into cyan, the same two colours the closer blooms. */
      .hero h1 .gradient-text{background:linear-gradient(103deg,
          var(--accent) 0%, #4C9DFF 30%, #45C9F0 58%, var(--info) 82%);
        -webkit-background-clip:text;background-clip:text;
        -webkit-text-fill-color:transparent;color:transparent;
        text-shadow:none;}
      @supports not ((-webkit-background-clip:text) or (background-clip:text)){
        .hero h1 .gradient-text{color:var(--accent);-webkit-text-fill-color:var(--accent);}
      }
      /* The anchor: the one line that says what the system IS. The h1 is
         a maxim and the slot line below is a demo — without a category
         between them a cold visitor is told the product is better before
         being told what it is. It sits one tier brighter than the muted
         copy under it because it is the sentence the rest of the fold
         spends its time arguing. */
      /* The announcement slot. The walkthrough used to be a 952px
         section at position seven, which is a long way to scroll for a
         film. As a pill it costs ~34px, sits above the statement, and
         opens over the page instead of navigating away. The slot outlives
         this particular video: it is where the next shipped thing goes. */
      .hero-pill{display:inline-flex;align-items:center;gap:9px;
        margin:0 0 20px;padding:7px 8px 7px 9px;border-radius:999px;
        font-family:var(--font-body);font-size:12.5px;font-weight:500;
        color:var(--text-secondary);cursor:pointer;
        border:1px solid var(--border);background:var(--surface);
        transition:color .16s, border-color .16s, background .16s;}
      .hero-pill:hover{color:var(--text-primary);background:var(--surface-2);
        border-color:color-mix(in srgb, var(--accent) 50%, transparent);}
      .hero-pill:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
      .hero-pill .tag{font-size:10px;font-weight:700;letter-spacing:.11em;
        text-transform:uppercase;color:var(--accent);
        background:color-mix(in srgb, var(--accent) 15%, transparent);
        border-radius:999px;padding:3px 8px;}
      .hero-pill b{font-weight:600;color:var(--text-primary);}
      .hero-pill .dur{color:var(--text-dim);}
      .hero-pill .play{display:inline-flex;align-items:center;justify-content:center;
        width:20px;height:20px;border-radius:50%;flex:0 0 auto;
        background:var(--accent);color:var(--ink-on-accent);font-size:8px;}

      /* the modal */
      .vmodal{position:fixed;inset:0;z-index:200;display:none;
        align-items:center;justify-content:center;padding:24px;
        background:rgba(4,5,8,.82);-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);}
      .vmodal[open]{display:flex;}
      .vmodal-box{position:relative;width:min(960px,100%);
        border-radius:14px;overflow:hidden;border:1px solid var(--border-strong);
        background:#000;box-shadow:0 50px 120px rgba(0,0,0,.7);}
      .vmodal video{display:block;width:100%;aspect-ratio:16/9;background:#000;}
      .vmodal-x{position:absolute;top:10px;right:10px;z-index:2;
        width:36px;height:36px;border-radius:50%;cursor:pointer;
        display:inline-flex;align-items:center;justify-content:center;
        font-family:var(--font-body);font-size:17px;line-height:1;
        color:var(--text-primary);background:rgba(10,12,16,.72);
        border:1px solid var(--border-strong);
        transition:background .16s, border-color .16s;}
      .vmodal-x:hover{background:rgba(10,12,16,.92);
        border-color:color-mix(in srgb, var(--accent) 60%, transparent);}
      .vmodal-x:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
      .vmodal-cap{padding:12px 16px;font-size:12.5px;color:var(--text-muted);
        border-top:1px solid var(--border);background:var(--bg-2);}
      /* Under 1000px the hero column is a stretching flex, which blew the
         pill out to the full 689px at 768. It is a label, not a bar. */
      .hero-pill{align-self:flex-start;}
      @media (hover:none), (max-width:900px){
        .hero-pill{min-height:44px;}
      }
      @media (max-width:640px){
        .vmodal{padding:14px;}
        .vmodal-x{width:44px;height:44px;}
        .hero-pill{font-size:12px;}
      }

      .hero-anchor{max-width:46ch;margin:0 0 20px;
        font-family:var(--font-body);font-weight:400;
        font-size:clamp(16.5px,1.42vw,20px);line-height:1.5;
        color:var(--text-secondary);text-wrap:balance;}
      .hero-anchor b{color:var(--text-primary);font-weight:600;}
      /* demoted a step so the anchor above reads as the louder of the two */
      .hero-turn{max-width:44ch;margin:0 0 26px;font-size:clamp(15px,1.12vw,16.5px);
        font-family:var(--font-body);font-weight:400;line-height:1.55;
        color:var(--text-muted);text-wrap:pretty;}
      .hero-turn b{color:var(--text-primary);font-weight:500;}
      .hero-ctas{display:flex;flex-wrap:wrap;gap:12px;align-items:center;}
      .hero-meta{display:flex;flex-wrap:wrap;align-items:center;gap:14px 18px;margin-top:24px;}
      .hero-note{font-size:12.5px;color:var(--text-dim);}

      /* ── the live slot: "Tell it what you do — [ barber ]" ────────── */
      .hero-slot-line{display:flex;flex-wrap:wrap;align-items:center;gap:10px;
        margin:0 0 22px;font-family:var(--font-body);
        font-size:clamp(16px,1.3vw,18px);color:var(--text-muted);}
      .hero-slot{display:inline-flex;align-items:center;gap:8px;
        border:1px solid rgba(46,125,255,.42);background:rgba(46,125,255,.11);
        border-radius:9px;padding:6px 13px;color:var(--text-primary);
        font-weight:600;letter-spacing:-.01em;min-width:11.5em;}
      .hero-slot .caret{width:2px;height:1.1em;background:var(--accent);flex-shrink:0;
        animation:heroCaret 1.1s steps(1,end) infinite;}
      @keyframes heroCaret{0%,49%{opacity:1;}50%,100%{opacity:0;}}
      .hero-chips{display:flex;flex-wrap:wrap;gap:7px;margin:0 0 26px;}
      .hero-chip{font-family:var(--font-body);font-size:12.5px;padding:6px 12px;
        border-radius:99px;border:1px solid var(--border);color:var(--text-muted);
        background:transparent;cursor:pointer;
        transition:color .16s ease,border-color .16s ease,background .16s ease;}
      .hero-chip:hover{color:var(--text-primary);border-color:rgba(255,255,255,.28);}
      .hero-chip[aria-pressed="true"]{color:var(--text-primary);
        border-color:rgba(46,125,255,.55);background:rgba(46,125,255,.13);}

      /* ── the fold panel: the REAL replica, not a stand-in ──────────
         First pass built a simplified panel out of the SITE's tokens
         (blue accent, site surfaces). Ruled a misleading panel —
         it promises a workspace the product does not actually look
         like. So the fold now runs on the replica kit, the same
         vocabulary traced from the product and used by the six room
         faces: the product's own palette inside .app (amber actions,
         violet briefing, magenta/cyan mark), the real top bar, the
         real sidebar, the KPI row, the briefing beside Chief, the AI
         Suggestions rail and the Quick Actions strip.

         Every layout floor here is CONTAINER-relative (auto-fit +
         min(), flex-wrap). The old .hero-2col dropped its rail on a
         VIEWPORT media query, which never fires when the panel is the
         narrow half of a wide screen — the rail stayed and crushed. */
      /* The panel and the screens in the closing band are the same
         replica kit, but the band's read as objects in a room and this
         one read as a div: the difference was never the UI inside, it
         was the bloom under it, the layered shadow and the sheen over
         the glass. Same treatment here. */
      .fold-stage{min-width:0;position:relative;}
      .fold-stage::before{content:'';position:absolute;left:-7%;right:-7%;top:6%;bottom:-12%;z-index:-1;
        filter:blur(64px);border-radius:50%;
        background:radial-gradient(50% 50% at 50% 50%, rgba(46,125,255,.34), rgba(46,125,255,0) 70%);}
      .fold-stage .app{border-radius:16px;border-color:rgba(255,255,255,.14);
        box-shadow:0 60px 120px -34px rgba(0,0,0,.86), 0 24px 50px -18px rgba(0,0,0,.6),
                   0 0 0 1px rgba(0,0,0,.6), 0 1px 0 rgba(255,255,255,.07) inset;}
      .fold-stage .app::after{content:'';position:absolute;inset:0;pointer-events:none;z-index:9;
        border-radius:inherit;
        background:linear-gradient(147deg, rgba(255,255,255,.06), rgba(255,255,255,0) 34%);}
      .fold-stage .app{position:relative;}

      /* What actually separates the closing band's screens from this
         panel is not resolution, it is that they sit in PERSPECTIVE and
         this sat flat-on to the reader. A replica photographed square is
         a div; the same replica at a few degrees is a screen on a desk.
         So the panel now arrives tilted and settles level — the gesture
         of something being set down in front of you — and it happens
         ONCE, on the reveal. Not tied to scroll: a hero that keeps
         moving while you read it is a hero you cannot read.

         The transform sits on .app, not on .fold-stage, on purpose.
         .fold-stage::before is the bloom at z-index:-1; transforming its
         parent would trap it in a new stacking context and put the bloom
         behind the very panel it exists to light. */
      .fold-stage .app{transform-origin:62% 100%;
        transform:perspective(2400px) rotateX(7.5deg) rotateY(-9deg) scale(.962);
        transition:transform 1.25s cubic-bezier(.16,.84,.28,1) .16s;
        will-change:transform;}
      .fold-stage.visible .app{
        transform:perspective(2400px) rotateX(0deg) rotateY(0deg) scale(1);}
      @media (prefers-reduced-motion: reduce){
        .fold-stage .app{transform:none !important;transition:none !important;}
      }
      /* A sentence, not a flex row. The caption is one line of prose
         with a bare text node in the middle, so `display:flex` made each
         fragment its own item and put a 9px gutter between them — on a
         phone the line broke into three blocks with visible gaps, like
         justified text gone wrong. It reads as prose because it IS
         prose; the dot is the only thing that needs to be a box. */
      .fold-cap{margin-bottom:11px;line-height:1.55;
        font-size:11.5px;color:var(--text-dim);letter-spacing:.02em;}
      .fold-cap b{color:var(--text-secondary);font-weight:600;}
      .fold-cap .dot{display:inline-block;vertical-align:middle;
        width:6px;height:6px;border-radius:50%;background:var(--success);
        box-shadow:0 0 8px var(--success);margin:-1px 7px 0 0;}

      .hero .app{min-height:472px;}
      .hero .kpi-row{grid-template-columns:repeat(auto-fit,minmax(min(112px,100%),1fr));}
      .hero-panes{display:flex;flex-wrap:wrap;gap:9px;flex:1;min-height:0;}
      .hero-panes > .brief{flex:1 1 300px;min-width:0;}
      .hero-panes > .pnl{flex:1 1 186px;min-width:0;}
      .hero .qa{grid-template-columns:repeat(auto-fit,minmax(min(84px,100%),1fr));}

      /* The rail has to answer to the CANVAS, not the window. Left to
         wrap it dropped under the briefing and took the panel to 789px
         tall at a 1180 viewport, which shoves the whole fold off screen.
         A viewport media query cannot express this — the same 1180
         window holds a wide canvas or a narrow one depending on the copy
         column — so the canvas becomes the query container and the rail
         hides below the width where it stops being readable. Without
         container-query support it just wraps: the old behaviour, still
         legible. */
      .hero .app-canvas{container-type:inline-size;}
      @container (max-width:498px){
        .hero-panes > .pnl{display:none;}
      }
      /* .brief puts the greeting beside Chief, which wants ~700px. In
         the fold it gets 425–500, so side-by-side crushed the greeting
         into a ~90px column. Stacked it reads correctly at any width the
         fold can produce; the standing line and the buttons come out to
         buy the height back, leaving the date and the greeting — the
         part that is recognisably this dashboard. */
      .hero .brief{flex-direction:column;gap:10px;}
      .hero .brief .cp, .hero .brief .brief-btns{display:none;}
      /* 8 tiles through an auto-fit floor of 84px resolved to 7 tracks
         and wrapped 7+1, which left a ragged single tile under a full
         row. A fixed 4x2 block reads as a deliberate grid, and at the
         widths the fold produces the tiles land near the size they are
         in the product. */
      .hero .qa{grid-template-columns:repeat(4,1fr);}
      /* the labels cross-fade; the frame never moves, so it reads as one
         workspace changing its mind rather than a carousel */
      .fold-swap{transition:opacity .2s ease;}
      .is-swapping .fold-swap{opacity:.25;}

      /* ── measure ───────────────────────────────────────────────────
         On a 2560 display the old rule sized the copy column at 599px
         and let the panel balloon to 1201px — twice the copy. The bleed
         was (100vw-1404)/2 with no ceiling, so it grew without limit
         while the container stayed pinned at 1340: every pixel of a
         bigger monitor went to the panel and none to anything else.

         The bleed is now capped at 72px, and the split is a percentage
         with a ceiling instead of a bare fr, so the copy keeps a
         readable measure rather than stretching to half of whatever
         screen is attached. The hero also keeps the site's own 1340px
         container rather than opening wider on big screens: a fold
         measured differently from every section under it reads as
         broken, not generous. */
      .hero-grid{display:grid;grid-template-columns:minmax(0,clamp(340px,42%,560px)) minmax(0,1fr);
        gap:clamp(30px,3vw,52px);align-items:center;}
      /* NO TILT. rotateY under perspective magnifies the near edge, so
         the panel's two vertical sides render at different heights —
         measured, the tilt inflated the box from 618px to 645px, and
         that difference is the whole of it: one side sat closer than
         the other. On a photograph it reads as depth; on a dense grid
         of rows and rules it reads as a crooked screen. It also fights
         the reason this panel exists — a fold that says "this is what
         you actually get" should not skew the thing it is showing.
         Depth comes from the shadow, which does not bend anything.

         The bleed stays: it only widens, and it is capped at 72px so it
         can never outrun the container's 32px gutter. */
      @media (min-width:1200px){
        .fold-stage{margin-right:calc(-1 * min(72px, max(0px, (100vw - 1404px) / 2)));}
      }

      /* ── the fold's replica, at phone width ──────────────────────
         The stage is 335px across at 390px, and the replica was
         setting its labels at 7-8px inside it: the biggest object
         on the screen was the one nobody could read. The panes that
         do not fit are already dropped below; these are the sizes
         for the ones that stay. Type only — moving anything
         structural here would reflow a layout that is already
         correct. */
      @media (max-width:700px){
        /* The label is nowrap+ellipsis at desktop size, where it fits.
           At 10.5px in a 152px tile it does not, so let it take a
           second line rather than truncate the noun it exists to
           name. */
        .fold-stage .app .kpi .k{font-size:10px;letter-spacing:.05em;
          white-space:normal;overflow:visible;line-height:1.25;}
        .fold-stage .app .kpi .f{font-size:11px;}
        .fold-stage .app .brief-l .date{font-size:10px;}
        .fold-stage .app .chief-h .on{font-size:10px;}
        .fold-stage .app .chief-f .tag{font-size:9.5px;}
        .fold-stage .app .chief-f .amt{font-size:10.5px;}
        .fold-stage .app .chief-f .g{font-size:12px;}
        .fold-stage .app .cf .chief-lead{font-size:11.5px;}
        .fold-stage .app .cf .chief-ask{font-size:11.5px;}
        .fold-stage .app .chief-btns b,
        .fold-stage .app .chief-btns i{font-size:11.5px;}
        .fold-stage .app .cin-wrap .cin-ph{font-size:11.5px;}
      }

      @media (max-width:1000px){
        /* 52px predates the one-number rhythm, and with the nav out of
           flow it would seat the badge under the wordmark. 128 both
           clears the row and keeps the fold on the same number as
           every other section. */
        .hero{padding-top:128px;}
        .hero-grid{display:flex;flex-direction:column;align-items:stretch;gap:24px;}
        /* 7.2vw bottomed out at the 32px floor on every phone — a 78px
   desktop headline arriving at 32. 11.8vw lands it near 46 at 390px
   and still tops out at 54. */
.hero h1{font-size:clamp(38px,11.8vw,54px);}
        .hero-anchor{max-width:60ch;}
        .hero-turn{max-width:56ch;}
        .fold-stage{margin-right:0;}

        /* One column turns the copy above the panel into a budget, and the
           anchor now spends most of it saying what the system is. So the
           chameleon demo moves below the panel and takes the chips with it:
           the anchor answers "what is this", the panel proves it, and the
           demo is the supporting act it always was. Chips end up adjacent
           to the slot word they drive, which the panel used to split.

           display:contents dissolves .hero-copy so its children become flex
           items of .hero-grid and can be ordered around the panel. Safe
           here only because .hero-copy carries no .reveal of its own — a
           transform on a display:contents box does nothing. */
        .hero-copy{display:contents;}
        /* display:contents moves these into the flex BOX tree, but
           selectors still match the DOM tree — .hero-grid > .hero-meta
           matches nothing, so these have to be addressed through their
           real parent. `order` then applies because they are flex items. */
        .hero-grid > *, .hero-copy > *{margin-top:0;margin-bottom:0;}
        .hero-grid > .fold-stage{order:1;}
        .hero-copy > .hero-slot-line{order:2;}
        .hero-copy > .hero-turn{order:2;}
        .hero-copy > .hero-chips{order:3;}
        .hero-copy > .hero-meta{order:4;}
      }

      /* Phones get the same deal the desktop fold gets, or the change is
         only half shipped. Stacked at 390px the panel first landed ~690px
         down — a whole screen of copy again, which is the bug this fold
         exists to kill. The ordering that claws it back now lives in the
         1000px block above, because every single-column width has the same
         problem. What is left here is genuinely phone-only: the chips
         become one swipeable row instead of three stacked ones, the top
         padding tightens, and the panel drops the chrome that needs width
         to read. */
      @media (max-width:640px){
        /* 34px was fine while the nav sat above the fold in flow. It does
           not any more — it floats over it — so 34 seated the NEW badge
           underneath the wordmark. 128 both clears the row and keeps the
           phone on the same one number as every other section. */
        .hero{padding-top:128px;}
        /* align-items goes back to the grid's own `center`: on a phone the
           CTA row and the slot line shrink-wrap and sit centred, which is
           how this fold has always shipped. Only the wider single-column
           range needs `stretch`, where shrink-wrapping would leave the
           headline and the anchor floating in the middle of a 700px column. */
        .hero-grid{gap:20px;align-items:center;}
        .hero-slot{min-width:0;flex:1;}
        /* a nowrap scroller's automatic minimum size is its content, so
           without min-width:0 the chip row sets the column's width and
           bleeds past the screen instead of scrolling inside it */
        .hero-chips{flex-wrap:nowrap;overflow-x:auto;min-width:0;max-width:100%;
          padding-bottom:2px;scrollbar-width:none;-webkit-overflow-scrolling:touch;}
        .hero-chips::-webkit-scrollbar{display:none;}
        .hero-chip{flex:0 0 auto;}
        /* the phone keeps the numbers and Chief — the parts that carry
           the claim — and drops the chrome that needs width to read */
        .hero .app{min-height:0;}
        .hero .app-side, .hero .qa, .hero .qa-h, .hero .app-top{display:none;}
        .hero-panes > .pnl{display:none;}
      }
      @media (prefers-reduced-motion:reduce){
        .hero-slot .caret{animation:none;}
        .fold-swap{transition:none;}
      }

      /* ── pricing ─────────────────────────────────────────────────── */
      .pricing{padding:128px 0;border-top:1px solid var(--border);}
      .price-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;max-width:1000px;margin:0 auto;}
      @media (max-width:860px){.price-grid{grid-template-columns:1fr;}}
      .price-card{padding:26px 24px;border:1px solid var(--border);border-radius:16px;background:var(--surface);
        display:flex;flex-direction:column;}
      .price-card.is-mid{border-color:color-mix(in srgb, var(--accent) 42%, transparent);
        background:color-mix(in srgb, var(--accent) 6%, var(--surface));}
      .price-name{font-size:11px;letter-spacing:.14em;text-transform:uppercase;
        color:var(--text-muted);font-weight:700;margin-bottom:12px;}
      .price-fig{display:flex;align-items:baseline;gap:6px;margin-bottom:14px;}
      /* The figure counts up on reveal; without tabular numerals every
         digit change reflowed the row and the roll read as a glitch. */
      .price-fig b{font-family:var(--font-heading);font-size:40px;font-weight:700;
        font-variant-numeric:tabular-nums;
        color:var(--text-primary);letter-spacing:-.03em;line-height:1;}
      .price-fig span{font-size:13.5px;color:var(--text-muted);}
      .price-card p{margin:0;font-size:13.5px;line-height:1.65;color:var(--text-secondary);}
      .price-facts{list-style:none;margin:14px 0 18px;padding:14px 0 0;border-top:1px solid var(--border);
        display:flex;flex-direction:column;gap:7px;font-size:12.5px;color:var(--text-secondary);}
      .price-facts li{font-variant-numeric:tabular-nums;}
      /* The table published three prices and gave you nothing to press —
         the only link in the whole section was "talk to us" in the fine
         print. Measured 2026-08-20: 3 cards, 0 doors. */
      .price-cta{display:flex;align-items:center;justify-content:center;gap:7px;margin-top:auto;
        padding:11px 16px;border-radius:10px;font-size:13.5px;font-weight:700;font-family:inherit;
        background:var(--surface-2);color:var(--text-primary);border:1px solid var(--border-strong);
        transition:background .15s,border-color .15s,transform .15s;}
      .price-cta:hover{background:var(--surface);border-color:color-mix(in srgb, var(--accent) 55%, transparent);
        transform:translateY(-1px);}
      .price-cta.is-mid{background:var(--accent);color:var(--ink-on-accent);border-color:transparent;
        box-shadow:0 6px 22px color-mix(in srgb, var(--accent) 30%, transparent);}
      .price-cta.is-mid:hover{background:var(--accent-2);}
      @media (prefers-reduced-motion: reduce){.price-cta:hover{transform:none;}}
      .price-note{max-width:620px;margin:26px auto 0;text-align:center;font-size:13.5px;color:var(--text-muted);}

      /* The cards answer "which one"; they cannot answer "what is
         actually different". That question had one door on the whole
         page and it was the word "comparison" inside a FAQ answer two
         screens down. Ghost weight on purpose: the three card CTAs are
         the primary action here and this must not outrank them. */
      .price-doors{display:flex;justify-content:center;margin-top:22px;}
      .price-compare{display:inline-flex;align-items:center;gap:8px;
        padding:11px 20px;border-radius:10px;font-family:inherit;
        font-size:13.5px;font-weight:600;color:var(--text-secondary);
        background:transparent;border:1px solid var(--border-strong);
        transition:color .18s, border-color .18s, background .18s, box-shadow .28s;}
      .price-compare:hover{color:var(--text-primary);background:var(--surface);
        border-color:color-mix(in srgb, var(--accent) 55%, transparent);
        box-shadow:0 10px 26px color-mix(in srgb, var(--accent) 18%, transparent);}

      /* ── pricing: cards that answer the cursor ──────────────────────
         Three cards published three numbers and then sat perfectly
         still. Everything below is either hover-driven or fires once on
         arrival. Nothing loops forever: that is the taste call (one
         ignite moment per screen) and the battery call on a phone.

         --pc-angle MUST be a registered property. CSS interpolates a
         registered <angle>; it never interpolates a gradient, so an
         unregistered angle gives a conic gradient that simply cannot
         move. The var() carries its own 0deg fallback so a browser
         without @property paints a static ring instead of throwing the
         whole background out as invalid. */
      @property --pc-angle{syntax:'<angle>';initial-value:0deg;inherits:false;}

      .price-card{position:relative;isolation:isolate;
        transition:transform .28s cubic-bezier(.2,.7,.3,1),
                   border-color .28s ease, box-shadow .28s ease;}
      /* the card's own content rides above the spotlight wash */
      .price-card > *{position:relative;z-index:2;}

      /* THE TRAVELLING EDGE — a conic gradient masked down to the 1px
         ring. content-box mask minus full-box mask leaves the border
         and nothing else; -webkit-mask-composite:xor is Safari's
         spelling of mask-composite:exclude, so both ship. */
      /* 2.5px, and colour all the way round rather than one arc across
         178deg with the rest transparent: at 1px on a faint border the
         travel was there and nobody saw it. The stops are the site's
         own tokens in order — accent, info, violet, amber, success —
         so the card lights up in the palette it already lives in, and
         the drop-shadow follows the masked ring rather than the box. */
      .price-card::before{content:'';position:absolute;inset:0;border-radius:inherit;
        padding:2.5px;pointer-events:none;z-index:3;opacity:0;transition:opacity .3s ease;
        filter:drop-shadow(0 0 7px color-mix(in srgb, var(--accent) 50%, transparent));
        background:conic-gradient(from var(--pc-angle,0deg),
          var(--accent) 0deg,
          var(--info) 62deg,
          var(--violet) 128deg,
          var(--amber) 192deg,
          var(--success) 256deg,
          var(--info) 310deg,
          var(--accent) 360deg);
        -webkit-mask:linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
        -webkit-mask-composite:xor;
        mask:linear-gradient(#fff 0 0) content-box, linear-gradient(#fff 0 0);
        mask-composite:exclude;}

      /* THE SPOTLIGHT — a bloom parked wherever the cursor actually is.
         --pc-x/--pc-y are written by the script on pointermove. */
      .price-card::after{content:'';position:absolute;inset:0;border-radius:inherit;
        pointer-events:none;z-index:1;opacity:0;transition:opacity .35s ease;
        background:radial-gradient(340px circle at var(--pc-x,50%) var(--pc-y,0%),
          color-mix(in srgb, var(--accent) 22%, transparent), transparent 62%);}

      .price-facts li{transition:color .3s ease, transform .3s ease;}
      .price-facts li:nth-child(1){transition-delay:.02s;}
      .price-facts li:nth-child(2){transition-delay:.07s;}
      .price-facts li:nth-child(3){transition-delay:.12s;}
      .price-facts li:nth-child(4){transition-delay:.17s;}

      @media (hover:hover) and (pointer:fine){
        .price-card:hover{transform:translateY(-4px);
          border-color:color-mix(in srgb, var(--accent) 32%, transparent);
          box-shadow:0 22px 48px rgba(0,0,0,.42);}
        .price-card:hover::before{opacity:1;animation:pcTravel 2.6s linear infinite;}
        .price-card:hover::after{opacity:1;}
        /* the facts light in order instead of all at once */
        .price-card:hover .price-facts li{color:var(--text-primary);transform:translateX(3px);}
      }

      /* A phone never fires :hover, so the edge runs once as each card
         arrives instead — same signature move, one pass, no loop. The
         script adds .is-lit and takes it back off when the run ends. */
      .price-card.is-lit::before{opacity:1;animation:pcTravel 2.6s linear 1;}
      @keyframes pcTravel{to{--pc-angle:360deg;}}

      /* THE BUTTON — a bloom that grows out of it, and one sheen that
         crosses it. The sheen is meant to pass over the label too, so it
         deliberately sits above the text. */
      .price-cta{position:relative;overflow:hidden;
        transition:background .18s, border-color .18s, transform .18s, box-shadow .3s ease;}
      .price-cta::after{content:'';position:absolute;inset:0;pointer-events:none;
        background:linear-gradient(105deg, transparent 38%,
          rgba(255,255,255,.20) 50%, transparent 62%);
        transform:translateX(-130%);}
      @media (hover:hover) and (pointer:fine){
        .price-cta:hover{transform:translateY(-2px);
          box-shadow:0 12px 30px color-mix(in srgb, var(--accent) 30%, transparent);}
        .price-cta:hover::after{animation:pcSheen .75s ease;}
        .price-cta.is-mid:hover{box-shadow:0 16px 42px color-mix(in srgb, var(--accent) 55%, transparent);}
      }
      @keyframes pcSheen{from{transform:translateX(-130%);}to{transform:translateX(130%);}}

      /* touch gets the press instead of the hover */
      @media (hover:none){
        .price-card:active::before{opacity:1;}
        .price-cta:active{transform:scale(.985);}
      }

      @media (prefers-reduced-motion: reduce){
        .price-card,.price-cta,.price-facts li{transition:none;}
        .price-card:hover{transform:none;}
        .price-card:hover::before,.price-card.is-lit::before{animation:none;opacity:1;}
        .price-card:hover::after{opacity:.5;}
        .price-cta:hover{transform:none;}
        .price-cta:hover::after{animation:none;}
      }

      /* ── the chameleon section ───────────────────────────────────── */
      .shape{padding:128px 0;border-top:1px solid var(--border);}

      /* This section spent 1181px, the second most on the page, telling
         you that a salon has regulars and a contractor has jobs. It is
         the most demonstrable claim the product owns and it was written
         as an essay. Now it demonstrates: the words on the right are the
         terminology the product actually ships, and they re-letter when
         you pick a business.

         The seven pills used to sit at the bottom as decoration, a
         second list of the same seven verticals the fold already lists.
         They are the control now, so one component both names who it is
         for and proves the claim, where there used to be two. */
      .shape-grid{display:grid;grid-template-columns:minmax(0,.92fr) minmax(0,1.08fr);
        gap:clamp(28px,4vw,56px);align-items:center;max-width:1120px;margin:0 auto;}
      .shape-copy p{font-size:16px;line-height:1.7;color:var(--text-secondary);
        margin:0 0 15px;max-width:46ch;}
      .shape-copy p:last-of-type{color:var(--text-primary);}
      /* a column, not a 3-up: these are a sequence, and they now sit
         beside the thing they describe instead of under it */
      .shape-steps{display:flex;flex-direction:column;gap:9px;margin-top:24px;}
      .shape-step{display:flex;gap:12px;align-items:flex-start;
        padding:13px 15px;border:1px solid var(--border);border-radius:12px;
        background:var(--surface);}
      .shape-step .n{display:inline-flex;align-items:center;justify-content:center;
        width:22px;height:22px;flex:0 0 auto;margin-top:1px;
        border-radius:50%;background:color-mix(in srgb, var(--accent) 16%, transparent);
        color:var(--accent);font-weight:700;font-size:11.5px;}
      .shape-step b{display:block;font-size:14px;color:var(--text-primary);
        margin-bottom:2px;letter-spacing:-.01em;}
      .shape-step span:last-child{display:block;font-size:13px;color:var(--text-muted);line-height:1.55;}

      .mp{border:1px solid var(--border);border-radius:18px;padding:24px;
        background:linear-gradient(160deg, rgba(255,255,255,.05), rgba(255,255,255,.018));
        box-shadow:0 26px 60px rgba(0,0,0,.5);}
      .mp-cap{display:flex;align-items:center;gap:9px;margin-bottom:18px;
        font-size:11.5px;letter-spacing:.13em;text-transform:uppercase;
        color:var(--text-dim);font-weight:700;}
      .mp-cap .live{width:7px;height:7px;border-radius:50%;flex:0 0 auto;
        background:var(--success);box-shadow:0 0 10px rgba(34,197,94,.75);}
      .mrow{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1.2fr);
        align-items:baseline;gap:14px;padding:13px 0;
        border-bottom:1px dashed rgba(255,255,255,.08);}
      .mrow:last-of-type{border-bottom:0;}
      .mlab{font-size:13px;color:var(--text-dim);}
      .marrow{font-size:13px;color:var(--text-dim);}
      .mval{font-family:var(--font-heading);font-size:clamp(18px,1.9vw,24px);
        font-weight:600;letter-spacing:-.022em;color:var(--text-primary);text-align:right;}
      .mp-rest{margin-top:18px;padding-top:16px;border-top:1px solid var(--border);}
      .mp-rest .lbl{font-size:11px;letter-spacing:.13em;text-transform:uppercase;
        color:var(--text-dim);font-weight:700;}
      .mp-items{display:flex;flex-wrap:wrap;gap:7px;margin-top:10px;}
      .mp-item{font-size:12.5px;color:var(--text-secondary);padding:6px 11px;
        border-radius:8px;background:var(--surface-2);border:1px solid var(--border);}
      /* out, swap the text, back in, staggered down the column */
      .swap{display:inline-block;
        transition:opacity .2s ease, transform .2s ease, filter .2s ease;}
      .swap.out{opacity:0;transform:translateY(-7px);filter:blur(4px);}

      /* the control belongs with the thing it controls: these used to
         sit at the bottom of the section, past a paragraph, as a second
         list of the same seven verticals */
      .mp-pick{margin-top:18px;}
      .mp-pick .lbl{display:block;font-size:11px;letter-spacing:.13em;
        text-transform:uppercase;color:var(--text-dim);font-weight:700;
        margin-bottom:10px;}
      .mp-pick .audience-grid{display:flex;flex-wrap:wrap;gap:7px;
        justify-content:flex-start;margin:0;}
      .mp-pick .audience-pill{cursor:pointer;font-family:var(--font-body);}
      .mp-pick .audience-pill[aria-pressed="true"]{color:var(--text-primary);
        border-color:color-mix(in srgb, var(--accent) 60%, transparent);
        background:color-mix(in srgb, var(--accent) 13%, transparent);}
      .mp-pick .audience-pill:focus-visible{outline:2px solid var(--accent);
        outline-offset:2px;}

      @media (max-width:900px){
        .shape-grid{grid-template-columns:1fr;gap:30px;}
        .mrow{grid-template-columns:minmax(0,1fr) auto;row-gap:3px;}
        .marrow{display:none;}
        .mval{grid-column:1 / -1;text-align:left;}
      }
      .audience-note{max-width:620px;margin:22px auto 0;text-align:center;font-size:14px;color:var(--text-muted);}
      .shape-close{max-width:700px;margin:38px auto 0;text-align:center;font-size:15.5px;
        line-height:1.65;color:var(--text-secondary);}

      /* ── trust band: this product asks for Stripe, bank connections and
         a whole client list. Answering "what happens to my data" directly
         under the hero is the honest place for it. Every claim here is
         already documented in /privacy — nothing new is promised. ── */
      /* No top rule. The hero above is now a continuous colour field,
         and a hairline plus a flat tint band starting on the same pixel
         drew a hard seam directly under the fold — the one edge on the
         page a visitor is guaranteed to look at. The tint now grows in
         from nothing over the first third of the band, so the field
         resolves into the band instead of hitting a lid. The bottom
         rule stays: that boundary is a real change of subject. */
      .trust{border-bottom:1px solid var(--border);padding:128px 0;
        background:linear-gradient(to bottom,
          transparent 0%,
          color-mix(in srgb, var(--accent) 3.5%, transparent) 34%,
          color-mix(in srgb, var(--accent) 3.5%, transparent) 100%);}
      /* "Every action logged. Undo means undo." was the most important
         promise on the page and the least visual thing on it: 507px of
         centred prose and three icons. It gets the artifact it had been
         describing all along, and the section goes asymmetric with the
         log on the left, which also breaks the centred rhythm the rest
         of the page kept repeating. */
      .trust-layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);
        gap:clamp(28px,4vw,54px);align-items:center;max-width:1120px;margin:0 auto;}
      .trust-layout .trust-head{max-width:none;margin:0;text-align:left;}
      .trust-layout .trust-head > .eyebrow{align-self:flex-start;}
      .trust-grid{display:flex;flex-direction:column;gap:15px;margin-top:22px;}

      .log{border:1px solid var(--border);border-radius:18px;padding:22px;
        background:linear-gradient(160deg, rgba(255,255,255,.05), rgba(255,255,255,.018));
        box-shadow:0 26px 60px rgba(0,0,0,.5);}
      .lrow{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:12px;
        align-items:center;padding:12px 2px;border-bottom:1px solid rgba(255,255,255,.055);}
      .lrow:last-of-type{border-bottom:0;}
      .ltick{width:8px;height:8px;border-radius:50%;background:var(--success);}
      .lrow.needs .ltick{background:var(--warn);}
      .lmain{min-width:0;}
      .lmain b{display:block;font-size:13.5px;font-weight:500;color:var(--text-primary);
        letter-spacing:-.008em;}
      .lmain span{display:block;margin-top:2px;font-size:11.5px;color:var(--text-dim);
        font-variant-numeric:tabular-nums;}
      .lundo{font-family:var(--font-body);font-size:11.5px;font-weight:600;
        padding:6px 12px;border-radius:8px;cursor:pointer;white-space:nowrap;
        color:var(--text-secondary);background:var(--surface-2);
        border:1px solid var(--border-strong);
        transition:color .16s, border-color .16s, background .16s;}
      .lundo:hover{color:var(--text-primary);background:rgba(46,125,255,.12);
        border-color:color-mix(in srgb, var(--accent) 60%, transparent);}
      .lundo[disabled]{opacity:.45;cursor:default;}
      .lrow.undone .lmain b{color:var(--text-dim);text-decoration:line-through;
        text-decoration-color:rgba(255,255,255,.3);}
      .lrow.undone .ltick{background:var(--text-dim);}
      .lpill{font-size:10.5px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;
        padding:4px 9px;border-radius:999px;white-space:nowrap;color:var(--warn);
        background:color-mix(in srgb, var(--warn) 12%, transparent);
        border:1px solid color-mix(in srgb, var(--warn) 32%, transparent);}
      .log-foot{margin-top:14px;padding-top:13px;border-top:1px solid var(--border);
        font-size:12px;color:var(--text-dim);min-height:1.5em;}

      @media (max-width:900px){
        .trust-layout{grid-template-columns:1fr;gap:28px;}
        .trust-layout .log{order:2;}
      }
      /* a finger needs 44px. Undo measured 28 and the pills 41, which is
         a control you can see and cannot reliably hit. */
      @media (hover:none), (max-width:900px){
        .lundo{min-height:44px;padding:6px 15px;}
        .mp-pick .audience-pill{min-height:44px;}
      }
      .trust-item{display:flex;gap:11px;align-items:flex-start;}
      .trust-item svg{width:17px;height:17px;flex-shrink:0;margin-top:1px;color:var(--accent);}
      .trust-item b{display:block;font-size:13px;font-weight:600;color:var(--text-primary);
        letter-spacing:-.01em;margin-bottom:3px;}
      .trust-item span{font-size:12.5px;color:var(--text-muted);line-height:1.5;}
      /* the head carries two beats now — who Chief is, then how it
         behaves — so it is a touch wider and the paragraphs are spaced
         by the block rather than by their own margins */
      .trust-head{max-width:720px;margin:0 auto 30px;text-align:center;
        display:flex;flex-direction:column;gap:11px;}
      /* a column flex stretches its children, which turned the eyebrow
         pill into a 720px-wide bar; only it needs to shrink to content */
      .trust-head > .eyebrow{align-self:center;}
      .trust-head h2{margin:4px 0 0;font-size:clamp(24px,3vw,34px);letter-spacing:-.02em;
        text-wrap:balance;}
      .trust-head p{font-size:14.5px;color:var(--text-muted);line-height:1.6;margin:0;}
      .trust-head p b{color:var(--text-primary);font-weight:600;}
      .trust-kicker{max-width:600px;margin:30px auto 0;text-align:center;font-family:var(--font-heading);
        font-size:16.5px;line-height:1.55;letter-spacing:-.01em;color:var(--text-muted);}
      .trust-kicker span{color:var(--text-primary);font-weight:600;}
      .trust-more{margin-top:22px;text-align:center;font-size:12.5px;color:var(--text-dim);}
      .trust-more a{color:var(--text-secondary);text-decoration:underline;text-underline-offset:3px;}

      /* ══════════════════════════════════════════════════════════════
         CHIEF strip
         ══════════════════════════════════════════════════════════════ */
      .ask{position:relative;padding:128px 0;border-top:1px solid var(--border);}
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
      .rooms{padding:128px 0;border-top:1px solid var(--border);position:relative;overflow:hidden;}
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
        .room-face{position:static;flex:0 0 auto;width:min(92vw, 720px);height:auto;min-height:340px;margin:0;
          transform:none !important;opacity:1;filter:none;pointer-events:auto;scroll-snap-align:center;}
        .room-face .app{height:100%;min-height:340px;}
        .rooms-nav{display:none;}
      }

      /* ══════════════════════════════════════════════════════════════
         rest of page
         ══════════════════════════════════════════════════════════════ */
      .audience{padding:128px 0;border-top:1px solid var(--border);border-bottom:1px solid var(--border);}
      .audience-grid{display:flex;flex-wrap:wrap;gap:10px;justify-content:center;}
      .audience-pill{display:inline-flex;align-items:center;gap:9px;padding:11px 20px;background:var(--surface);
        border:1px solid var(--border);border-radius:99px;font-size:14px;font-weight:500;
        color:var(--text-secondary);transition:border-color .18s, background .18s;}
      .audience-pill:hover{border-color:color-mix(in srgb, var(--accent) 48%, transparent);
        background:color-mix(in srgb, var(--accent) 8%, transparent);}
      .audience-pill .emoji{font-size:17px;}

      .audience-ask{text-align:center;margin-top:14px;font-size:14.5px;color:var(--text-muted);}
      .audience-ask a{color:var(--accent);font-weight:600;border-bottom:1px solid
        color-mix(in srgb, var(--accent) 40%, transparent);padding-bottom:1px;}
      .audience-ask a:hover{border-bottom-color:var(--accent);}

      .rooms-cta{display:flex;justify-content:center;align-items:center;gap:12px;
        flex-wrap:wrap;margin-top:36px;}
      @media (max-width:520px){.rooms-cta{flex-direction:column;align-items:stretch;}
        .rooms-cta a{justify-content:center;}}

      /* `.why-grid` / `.why-card` lived here until 2026-08-20, styling the
         "Why Solutionist" four-up. That section was a recap of the page —
         two of its four cards restated the rooms headline and the Chief
         claim — so it went, and its styling with it. */

      /* `.final-cta` lived here until 2026-08-19 — the device band is the
         closer now, and home is the only page that styled it. /features,
         /compare and /about still print that class but have never carried
         its CSS, so nothing here was ever reaching them. */

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

    body = ("""
<section class="hero">
  <div class="hero-glow" aria-hidden="true"><i class="hg1"></i><i class="hg2"></i><i class="hg3"></i></div>
  <div class="hero-grain" aria-hidden="true"></div>
  <div class="container-xl">
    <div class="hero-grid">
      <div class="hero-copy">
        <button type="button" class="hero-pill reveal" id="heroPill"
                aria-haspopup="dialog" aria-controls="videoModal">
          <span class="tag">New</span>
          <b>See it move</b>
          <span class="dur">&middot; 58 seconds</span>
          <span class="play" aria-hidden="true">&#9654;</span>
        </button>
        <h1 class="reveal">Every Problem <span class="gradient-text">Has A Solution.</span></h1>
        <p class="hero-anchor reveal reveal-delay-1"><b>The Solutionist System</b> is one workspace that runs your whole business: clients, money, marketing, and your site. A chief of staff does the work, all under one subscription.</p>
        <p class="hero-slot-line reveal reveal-delay-1">
          <span>Tell it what you do:</span>
          <span class="hero-slot"><span id="heroWord">barber</span><span class="caret" aria-hidden="true"></span></span>
        </p>
        <p class="hero-turn reveal reveal-delay-1">It arrives already speaking that language. Not a system you teach: <b>a system that already knows your business.</b></p>
        <div class="hero-chips reveal reveal-delay-2" id="heroChips" role="group" aria-label="See the system as a different business"></div>
        <div class="hero-ctas reveal reveal-delay-2">
          <a class="btn-primary" href="/start">Start your free trial &rarr;</a>
          <a class="btn-secondary" href="#rooms">Look inside</a>
        </div>
        <div class="hero-meta reveal reveal-delay-3">
          <span class="stat-block"><span class="big">7</span><span>business types it already knows</span></span>
          <span class="hero-note">__TRIAL_FREE__ &middot; Every action logged and reversible</span>
        </div>
      </div>

      <div class="fold-stage reveal reveal-delay-2" id="foldStage">
        <!-- This caption is the first time the visitor meets the word
             "Chief" — the panel below it says the name four more times
             (top bar, sidebar, briefing, Quick Actions) and the page did
             not define it until word ~566. So the caption carries the
             role, and the name is never naked on first sight. -->
        <div class="fold-cap"><span class="dot"></span><b>Mission Control</b> &middot; what Chief, your chief of staff, has ready each morning <span id="heroCap">for a barber</span></div>
        <div class="app">
          <div class="app-top">
            <span class="at-mark"></span>
            <span class="at-search">Ask Chief anything&hellip;<span class="kbd">&#8984;K</span></span>
            <span class="at-cta">+ Quick Create</span>
            <span class="at-urgent">Urgent</span>
            <span class="at-av"></span>
          </div>
          <div class="app-body">
            <div class="app-side">
              <div class="as-user"><span class="av"></span>
                <span class="nm fold-swap" id="fdOwner">Jordan Reyes<span id="fdBiz">Fade &amp; Co.</span></span>
                <span class="as-plan">STARTER</span></div>
              <div class="as-sec">Mission Control</div>
              <div class="as-item is-on"><span class="ic"></span>Dashboard</div>
              <div class="as-item"><span class="ic"></span>Operations</div>
              <div class="as-item"><span class="ic"></span>Notifications<span class="ct">15</span></div>
              <div class="as-sec fold-swap" id="fdGrp">The chair</div>
              <div class="as-item fold-swap"><span class="ic"></span><span id="fdN1">Regulars</span></div>
              <div class="as-item fold-swap"><span class="ic"></span><span id="fdN2">Chair calendar</span></div>
              <div class="as-item fold-swap"><span class="ic"></span><span id="fdN3">Walk-ins</span></div>
              <div class="as-item fold-swap"><span class="ic"></span><span id="fdN4">Payments</span></div>
              <div class="as-sec">Finance</div>
              <div class="as-item"><span class="ic"></span>Invoices</div>
              <div class="as-item"><span class="ic"></span>Expenses</div>
              <div class="as-item"><span class="ic"></span>Revenue</div>
              <div class="as-chief">Chief AI<span class="on">Online</span></div>
            </div>
            <div class="app-canvas">
              <div class="kpi-row">
                <div class="kpi fold-swap"><span class="k" id="fdK1">Chairs booked this week</span><span class="v" id="fdV1">38</span><span class="f" id="fdF1">4 open Friday</span></div>
                <div class="kpi fold-swap"><span class="k" id="fdK2">Regulars</span><span class="v" id="fdV2">124</span><span class="f" id="fdF2">9 overdue for a cut</span></div>
                <div class="kpi fold-swap"><span class="k" id="fdK3">Revenue &middot; this month</span><span class="v gold" id="fdV3">$6,910</span><span class="f up" id="fdF3">&#9650; 12% vs last mo</span></div>
                <div class="kpi fold-swap"><span class="k" id="fdK4">Business health</span><span class="v up" id="fdV4">61%</span><span class="f" id="fdF4">steady</span></div>
              </div>
              <div class="hero-panes">
                <div class="brief">
                  <div class="brief-l">
                    <span class="date">Monday, August 13 &middot; Morning edition</span>
                    <span class="hi">Good morning,<br><b id="fdFirst">Jordan</b></span>
                    <span class="cp">2 things need you today. Chief has them queued, and one word clears the deck.</span>
                    <span class="brief-btns"><span class="ah-btn">Focus Mode &rarr;</span><span class="lnk">Read today&rsquo;s briefing</span></span>
                  </div>
                  <div class="chief">
                    <div class="chief-h">Chief AI<span class="on">Online</span></div>
                    <div class="chief-body">
                      <div class="cf">
                        <div class="chief-lead fold-swap" id="fdLead">I&rsquo;ve analyzed your day. Here&rsquo;s what I found:</div>
                        <div class="chief-f fold-swap"><span class="sq warn"></span><span class="g" id="fdR1">3 regulars not rebooked</span><span class="amt" id="fdA1">6 weeks</span></div>
                        <div class="chief-f fold-swap"><span class="sq"></span><span class="g" id="fdR2">2 drafts waiting for you</span><span class="tag">Needs you</span></div>
                        <div class="chief-f fold-swap"><span class="sq ok"></span><span class="g" id="fdR3">$6,910 collected this month</span></div>
                        <div class="chief-ask fold-swap" id="fdAsk">Want me to text them your Tuesday openings?</div>
                        <div class="chief-btns"><b>Yes, handle it</b><i>Review first</i></div>
                      </div>
                    </div>
                    <div class="chief-in"><span class="cin-wrap"><span class="cin-ph">Ask Chief anything&hellip;</span></span><span class="go"></span></div>
                  </div>
                </div>
                <div class="pnl">
                  <div class="pnl-h">AI Suggestions<span class="ct">4</span></div>
                  <div class="r fold-swap"><span class="bar red"></span><span class="nm g" id="fdS1">Marcus Bell<span id="fdS1b">last cut 41 days ago</span></span><span class="pill sent">Text</span></div>
                  <div class="r fold-swap"><span class="bar red"></span><span class="nm g" id="fdS2">Tia Okonkwo<span id="fdS2b">last cut 38 days ago</span></span><span class="pill sent">Text</span></div>
                  <div class="r fold-swap"><span class="bar amb"></span><span class="nm g" id="fdS3">2 drafts pending review<span id="fdS3b">from last night&rsquo;s run</span></span><span class="pill draft">Open</span></div>
                  <div class="pnl-h" style="margin-top:4px;">Today<span class="ct" id="fdTn">4</span></div>
                  <div class="r fold-swap"><span class="bar grn"></span><span class="nm g" id="fdT1">9:00 AM<span id="fdT1b">Marcus Bell</span></span></div>
                  <div class="r fold-swap"><span class="bar grn"></span><span class="nm g" id="fdT2">11:30 AM<span id="fdT2b">Grace Okoye</span></span></div>
                  <div class="r fold-swap"><span class="bar"></span><span class="nm g" id="fdT3">2:00 PM<span id="fdT3b">Tia Okonkwo</span></span></div>
                </div>
              </div>
              <div class="qa-h">Quick Actions<span class="hint">one click, Chief handles the rest</span></div>
              <div class="qa">
                <i style="--c:#3B82F6">Draft Email</i><i style="--c:#EF4444">Chase Overdue</i>
                <i style="--c:#F59E0B">New Invoice</i><i style="--c:#22C55E">Add Contact</i>
                <i style="--c:#06B6D4">Book Session</i><i style="--c:#A855F7">Create a Post</i>
                <i style="--c:#7C3AED">Run Autopilot</i><i style="--c:#C9A84C">Set a Goal</i>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
"""
    + """
  </div>
</section>


<!-- MEET CHIEF — this band already answered "will it do something
     dumb?" before the page had said what Chief IS. The name appeared 8
     times before the first definition, which arrived at word ~566 of
     1,884 and led with a negation ("Chief isn't a chatbot bolted onto a
     dashboard"). The answer was already on the page as an 11px eyebrow
     three screens down: chief of staff. Introduce the ROLE, then the
     NAME — nobody knows "Chief", everybody knows what a chief of staff
     does. "Autonomous, not unsupervised." is not lost: it leads the
     conduct paragraph, which is the job it was always doing. -->
<section class="trust" id="chief">
  <div class="container-xl">
    <div class="trust-layout reveal">

    <!-- The rows are the same overnight run the Autopilot room already
         shows in the carousel below. One of them is live: undo actually
         undoes, and the footer records that it did, because "we log the
         undo too" is the part of the promise a paragraph cannot make. -->
    <div class="log" id="trustLog">
      <div class="lrow" id="trustUndoRow">
        <span class="ltick"></span>
        <span class="lmain"><b>Sent 3 invoice reminders</b><span>from your address &middot; 04:12</span></span>
        <button type="button" class="lundo" id="trustUndoBtn">Undo</button>
      </div>
      <div class="lrow">
        <span class="ltick"></span>
        <span class="lmain"><b>Reconciled 14 bank transactions</b><span>matched to invoices &middot; 07:01</span></span>
        <button type="button" class="lundo" disabled>Undo</button>
      </div>
      <div class="lrow">
        <span class="ltick"></span>
        <span class="lmain"><b>Prepped notes for the 9:00 discovery call</b><span>pulled the last 3 conversations &middot; 06:20</span></span>
        <button type="button" class="lundo" disabled>Undo</button>
      </div>
      <div class="lrow needs">
        <span class="ltick"></span>
        <span class="lmain"><b>Drafted a follow-up to Northside Co-op</b><span>waiting on your approval &middot; 05:03</span></span>
        <span class="lpill">Needs you</span>
      </div>
      <div class="lrow needs">
        <span class="ltick"></span>
        <span class="lmain"><b>Tia&rsquo;s card expires in 6 days</b><span>needs a human &middot; 07:28</span></span>
        <span class="lpill">Needs you</span>
      </div>
      <div class="log-foot" id="trustLogFoot" role="status">Autopilot, overnight &middot; nothing happened without a line in this log.</div>
    </div>

    <div>
    <div class="trust-head">
      <span data-spine class="eyebrow">Meet Chief</span>
      <h2>Every business runs on a chief of staff. <span class="gradient-text">Yours is called Chief.</span></h2>
      <p>The one who knows what is going on, keeps the day moving, and handles what you shouldn&rsquo;t have to.</p>
      <p><b>Autonomous, not unsupervised.</b> Chief runs your week on its own, and it asks first on anything that touches money, messages a client, or can&rsquo;t be taken back. Every action it takes is written down, explained in plain language, and reversible.</p>
    </div>
    <div class="trust-grid">
        <div class="trust-item"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 11V6a2 2 0 0 0-4 0v5"/><path d="M14 10V4a2 2 0 0 0-4 0v2"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/><path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/></svg><span><b>Asks before it acts</b>Refunds, bulk messages, anything irreversible: your call, every time.</span></div>
        <div class="trust-item"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/></svg><span><b>Shows its work</b>Every action logged in plain English. No black box, no mystery charges.</span></div>
        <div class="trust-item"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 5.5 5.5v0a5.5 5.5 0 0 1-5.5 5.5H11"/></svg><span><b>Undo means undo</b>If Chief gets it wrong, you take it back. That&rsquo;s a feature, not an apology.</span></div>
    </div>
    </div>
    </div>
    <p class="trust-kicker reveal">Most AI will do what you ask. <span>The question worth asking is what it does when you&rsquo;re not looking.</span></p>
    <div class="trust-more reveal">
      Full detail in the <a href="/privacy">Privacy Policy</a> and <a href="/terms">Terms</a>, including how to export everything or delete your account.
    </div>
  </div>
</section>

<section class="ask">
  <div class="container-xl">
    <div class="ask-grid">
      <div class="ask-copy">
                <span data-spine class="eyebrow reveal">The Chief of Staff</span>
        <h2 class="reveal reveal-delay-1" style="margin-top:14px;">Ask once. The whole system <span class="gradient-text">moves.</span></h2>
        <p class="lead reveal reveal-delay-2">Chief isn&rsquo;t a chatbot bolted onto a dashboard. It reads your real contacts, invoices, calendar and goals every turn, then acts on them.</p>
        <ul class="ask-list reveal reveal-delay-3">
          <li><span class="n">1</span><span>You ask in plain words, typed or spoken. <b>No menus to learn.</b></span></li>
          <li><span class="n">2</span><span>Chief reads your live data, not a generic model&rsquo;s guess. <b>It knows your numbers.</b></span></li>
          <li><span class="n">3</span><span>It does the work: drafts, sends, books, files. <b>Autopilot runs while you sleep.</b></span></li>
        </ul>
      </div>
      <div class="reveal reveal-delay-2">
        <div class="app cx">
          <div class="app-top"><span class="at-mark"></span><span class="at-search">Chief of Staff<span class="kbd">&#8984;K</span></span><span class="at-av"></span></div>
          <div class="app-canvas">
            <div class="cx-b you">Who owes me money?</div>
            <div class="cx-b ai">Three invoices are past due, <b>$2,140</b> total. Marcus (18 days), Grace Chapel (11), Tia (4). Want me to send reminders?</div>
            <div class="cx-b you">Yes, and book Marcus for Thursday.</div>
            <div class="cx-b ai">Done. Reminders sent from your address, and Marcus is on Thursday at 2:00&nbsp;PM, and the invite went out.</div>
            <div class="cx-b act">&#10003; 3 reminders sent &middot; 1 session booked</div>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>


<section class="shape" id="audience">
  <div class="container">
    <div class="section-head reveal">
      <span data-spine class="eyebrow">Who it&rsquo;s for</span>
      <h2 class="reveal reveal-delay-1" style="margin-top:14px;">Why it already speaks <span class="gradient-text">your language.</span></h2>
    </div>

    <div class="shape-grid reveal reveal-delay-2">
      <div class="shape-copy">
        <p>A salon doesn&rsquo;t have &ldquo;clients.&rdquo; It has regulars. A contractor doesn&rsquo;t book &ldquo;appointments.&rdquo; They schedule jobs. A bookkeeper&rsquo;s late-payment nudge sounds nothing like a therapist&rsquo;s.</p>
        <p>Tell the system what you do and it loads the whole world of your specialty: the vocabulary, the workflows, the rhythm of the week, what should happen automatically and what should never happen without you. Not a blank assistant waiting to be trained. A system that showed up knowing.</p>
        <div class="shape-steps">
          <div class="shape-step"><span class="n">1</span><span><b>You say what you do.</b><span>One sentence at intake. No setup wizard, no database design.</span></span></div>
          <div class="shape-step"><span class="n">2</span><span><b>The system takes that shape.</b><span>Terminology, workflows, dashboard, the whole room.</span></span></div>
          <div class="shape-step"><span class="n">3</span><span><b>Chief works inside it.</b><span>It is not guessing at your business. It is standing in it.</span></span></div>
        </div>
      </div>

      <div class="mp" id="shapePanel">
        <div class="mp-cap"><span class="live"></span>What <span class="swap" id="mpWord">a barber</span> opens on day one</div>
        <div class="mrow">
          <span class="mlab">The people you serve</span><span class="marrow">&rarr;</span>
          <span class="mval"><span class="swap" data-mp="people">Regulars</span></span>
        </div>
        <div class="mrow">
          <span class="mlab">The room they live in</span><span class="marrow">&rarr;</span>
          <span class="mval"><span class="swap" data-mp="room">The chair</span></span>
        </div>
        <div class="mrow">
          <span class="mlab">What you book</span><span class="marrow">&rarr;</span>
          <span class="mval"><span class="swap" data-mp="work">Chair calendar</span></span>
        </div>
        <div class="mp-rest">
          <span class="lbl">And the rest of the sidebar</span>
          <div class="mp-items" id="mpRest"></div>
        </div>

        <div class="mp-pick">
          <span class="lbl">Seven it already speaks &middot; pick one</span>
          <div class="audience-grid" id="shapeChips" role="group" aria-label="See the system as a different business"><button type="button" class="audience-pill" data-trade="coach" aria-pressed="false"><svg class="pill-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg> Coaches</button>
            <button type="button" class="audience-pill" data-trade="consultant" aria-pressed="false"><svg class="pill-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="20" height="14" x="2" y="7" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg> Consultants</button>
            <button type="button" class="audience-pill" data-trade="barber" aria-pressed="false"><svg class="pill-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 21v-7a4 4 0 0 1 8 0v7"/><path d="M8 10V3"/><path d="M14 21V8l6-3v16"/></svg> Barbers &amp; salons</button>
            <button type="button" class="audience-pill" data-trade="therapist" aria-pressed="false"><svg class="pill-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l8.8 8.8 8.8-8.8a5.5 5.5 0 0 0 0-7.8z"/></svg> Therapists</button>
            <button type="button" class="audience-pill" data-trade="contractor" aria-pressed="false"><svg class="pill-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg> Contractors</button>
            <button type="button" class="audience-pill" data-trade="attorney" aria-pressed="false"><svg class="pill-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v18"/><path d="M5 7h14"/><path d="M5 7 2 14h6zM19 7l-3 7h6z"/></svg> Attorneys</button>
            <button type="button" class="audience-pill" data-trade="pastor" aria-pressed="false"><svg class="pill-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 22h18"/><path d="M6 18v-7M10 18v-7M14 18v-7M18 18v-7"/><path d="M12 2 3 8h18Z"/></svg> Ministries &amp; churches</button></div>
        </div>
      </div>
    </div>

    <p class="shape-close reveal">One system instead of eight subscriptions, and unlike the eight, this one actually knows what your business is.</p>

    <p class="audience-note reveal reveal-delay-2">Each one gets its own version of the system, not a generic one with your logo dropped in.</p>
    <p class="audience-ask reveal reveal-delay-2">Don&rsquo;t see yours?
      <a href="/get-started">Tell us what you do &rarr;</a></p>
    <p class="audience-note reveal reveal-delay-2" style="margin-top:10px;">Two of those come with the scope stated up front. For therapists, the system runs the practice: scheduling, billing, and reminders. It deliberately keeps clinical notes and records out; those stay in your EHR. For attorneys, it runs the office: clients, matters, and invoicing. It reconciles your trust account three ways: book, client ledgers, and bank. IOLTA report formats vary by jurisdiction, so filing in your state&rsquo;s format stays with you.</p>
  </div>
</section>

<section class="rooms" id="rooms">
  <div class="container-xl">
    <div class="section-head reveal">
            <span data-spine class="eyebrow">Look inside</span>
      <h2>Six rooms. <span class="gradient-text">One brain.</span></h2>
      <p>Each room is built for what happens in it, and they all share your contacts, your brand, and your Chief. Every number updates as the data changes: no CSV exports, no waiting on a weekly report.</p>
    </div>

    <div class="rooms-tabs reveal" role="tablist" aria-label="Rooms">
      <button class="room-tab" role="tab" aria-selected="true" data-i="0">Operate</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="1">Clients</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="2">The Studio</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="3">The Academy</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="4">Smart Sites</button>
      <button class="room-tab" role="tab" aria-selected="false" data-i="5">Autopilot</button>
    </div>

    <div class="rooms-viewport reveal" id="roomsViewport">
      <div class="rooms-ring" id="roomsRing">

        <div class="room-face is-active" style="--fa:0deg;" data-i="0"
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
        <div class="room-face" style="--fa:60deg;" data-i="1"
             data-caption="The client register: every person you serve, their standing, their history, and who's gone quiet. Update a contact once; every room sees it.">
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
        <div class="room-face" style="--fa:120deg;" data-i="2"
             data-caption="Walk into a storefront built from your own brand. Try your identity on real artifacts (card, invoice, social post) and watch everything repaint as you edit.">
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
                <div class="r"><span class="bar"></span><span class="g">Change one color and every artifact repaints live</span><span class="pill live">Live</span></div>
              </div>
            </div>
          </div>
        </div>
        <div class="room-face" style="--fa:180deg;" data-i="3"
             data-caption="A dedicated Strategy Coach walks you through eight courses, discovery to launch plan, with a degree ring, sealed courses, and a diploma when you graduate.">
          <div class="app is-mini">
            <div class="app-body">""" + SIDEBAR + """
              <div class="app-canvas">
                <div class="ah-rule"></div>
                <div class="ah-eyebrow">The Academy &middot; Legal &amp; Tax Setup</div>
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
        <div class="room-face" style="--fa:240deg;" data-i="4"
             data-caption="Your site is composed from your brand DNA and your own words: typography, spacing and motion reasoned from who you are, live on your own link in minutes.">
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
                <div class="r"><span class="bar"></span><span class="g">Typography and spacing reasoned from your brand, not a theme</span><span class="pill live">Live</span></div>
              </div>
            </div>
          </div>
        </div>
        <div class="room-face" style="--fa:300deg;" data-i="5"
             data-caption="Set the rules once. Chief works your follow-ups, reminders and drafts on schedule overnight, and logs every action it took, so nothing happens behind your back.">
          <div class="app is-mini">
            <div class="app-body">""" + SIDEBAR + """
              <div class="app-canvas">
                <div class="ah-rule"></div>
                <div class="ah-row"><div><div class="ah-eyebrow">Autopilot &middot; Overnight run</div>
                  <div class="ah-title">Ran while you slept</div>
                  <div class="ah-sub">04:00 &ndash; 07:30 &middot; 12 actions &middot; 1 needs you</div></div>
                  <span class="ah-btn">Rules</span></div>
                <div class="pnl" style="flex:1;">
                  <div class="pnl-h">Action log<span class="ct">12</span></div>
                  <div class="r"><span class="bar grn"></span><span class="g nm">Sent 3 invoice reminders<span>from your address &middot; 04:12</span></span><span class="pill paid">Done</span></div>
                  <div class="r"><span class="bar amb"></span><span class="g nm">Drafted follow-up to Northside Co-op<span>waiting on your approval &middot; 05:03</span></span><span class="pill sent">Review</span></div>
                  <div class="r"><span class="bar grn"></span><span class="g nm">Prepped notes for 9:00 discovery call<span>pulled last 3 conversations &middot; 06:20</span></span><span class="pill paid">Done</span></div>
                  <div class="r"><span class="bar grn"></span><span class="g nm">Reconciled 14 bank transactions<span>matched to invoices &middot; 07:01</span></span><span class="pill paid">Done</span></div>
                  <div class="r"><span class="bar red"></span><span class="g nm">Flagged: Tia&rsquo;s card expires in 6 days<span>needs a human &middot; 07:28</span></span><span class="pill due">You</span></div>
                </div>
                <div class="r"><span class="bar"></span><span class="g">Every action logged. Approve, undo, or change the rules anytime</span><span class="pill live">Logged</span></div>
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
    <p class="room-caption" id="roomCaption">Invoices, payments and bookkeeping that reconcile themselves. Chief chases what's late so you don't have to write another awkward email.</p>

    <div class="rooms-cta reveal">
      <a class="btn-primary" href="/start">Start your free trial &rarr;</a>
      <a class="btn-secondary" href="/features">Explore every feature in depth &rarr;</a>
    </div>
  </div>
</section>


<section class="pricing" id="pricing">
  <div class="container">
    <div class="section-head reveal">
            <span data-spine class="eyebrow">What it costs</span>
      <h2 class="reveal reveal-delay-1" style="margin-top:14px;">Priced for one person running the whole thing.</h2>
    </div>
    <div class="price-grid reveal reveal-delay-2">""" + _price_cards_html() + """
    </div>
    <div class="price-doors reveal reveal-delay-3">
      <a class="price-compare" href="/compare">Compare every plan &rarr;</a>
    </div>
    <p class="price-note reveal">Running a team or more than one business? That is what the Solutionist plan is for; bigger networks are custom. <a href="/get-started" style="color:var(--accent);">Talk to us</a>. Every plan starts with __TRIAL_FREE__, and you can change tier or cancel yourself at any time.</p>
  </div>
</section>



<!-- ══ THE DEVICE BAND — the closer ══════════════════════════════════
     This REPLACED the old `.final-cta` (2026-08-19). That block
     and this one do the same job — the last word before the footer —
     and stacking them would have asked for the same click twice. The
     beta line it carried lives on under the buttons.

     Deliberately no `.reveal` anywhere in here: see DEVICE_BAND_CSS.
     The scene is aria-hidden — it is product art, and the copy above it
     already says everything a screen reader needs. ══ -->
<!-- The film. preload="none" so the 6.8MB costs nothing until somebody
     asks for it; the source is only fetched on the first open. The same
     film is still inline on /features for anyone reading that page top
     to bottom. ?v=2 since 2026-09-02: "The System" replaced "Takes Shape"
     at the same URL, and a cached poster would have shown the old film. -->
<div class="vmodal" id="videoModal" role="dialog" aria-modal="true"
     aria-label="The Solutionist System, fifty-eight seconds of the product at work">
  <div class="vmodal-box">
    <button type="button" class="vmodal-x" id="videoModalClose" aria-label="Close video">&times;</button>
    <video id="videoModalPlayer" controls playsinline preload="none"
           poster="/assets/film-poster.jpg?v=2">
      <source src="/assets/film.mp4?v=2" type="video/mp4">
      Your browser doesn&rsquo;t support embedded video.
      <a href="/assets/film.mp4?v=2">Download the film</a>.
    </video>
    <div class="vmodal-cap">One photographer&rsquo;s Tuesday: Home, Chief, the rooms, the shift it works while you are closed, and the one thing it will not do without you.</div>
  </div>
</div>

<section class="dv">
  <div class="dv-glow" aria-hidden="true">
    <i class="dv-g1"></i><i class="dv-g2"></i><i class="dv-g3"></i><i class="dv-g4"></i>
  </div>
  <div class="dv-grain" aria-hidden="true"></div>

  <div class="dv-copy">
    <span class="eyebrow">Wherever you work</span>
    <h2>Your business, open on <span class="gradient-text">every screen you own.</span></h2>
    <p class="dv-lead">One account, one system. The same data and the same Chief on the desk,
       at the counter, and in your pocket.</p>
    <div class="dv-ctas">
      <a class="btn-primary" href="/start">Start your free trial &rarr;</a>
      <a class="btn-secondary" href="/download">Get the app</a>
    </div>
    <p class="dv-note">__TRIAL_FREE__ &middot; every action logged and reversible.</p>
  </div>

  <div class="dv-scene" aria-hidden="true">
    <div class="dv-stage">

      <!-- ── A · the desk: Home, bleeding off the left edge ── -->
      <div class="dv-slot dv-a">
        <div class="app">
          <div class="app-top">
            <span class="at-mark"></span>
            <span class="at-search">Search or ask Chief<span class="kbd">&#8984;K</span></span>
            <span class="at-urgent">3 need you</span>
            <span class="at-cta">Quick Create</span>
            <span class="at-av"></span>
          </div>
          <div class="app-strip">
            <span class="biz">Fade &amp; Co.</span>
            <span class="tab on">Home</span>
            <span class="sp"></span>
            <span>Solutionist System</span>
          </div>
          <div class="app-body">
            <div class="app-side">
              <div class="as-user"><span class="av"></span>
                <span class="nm">Andre Whitfield<span>Fade &amp; Co.</span></span>
                <span class="as-plan">PRO</span></div>
              <div class="as-sec">Mission Control</div>
              <div class="as-item is-on"><span class="ic"></span>Dashboard</div>
              <div class="as-item"><span class="ic"></span>Needs you<span class="ct">3</span></div>
              <div class="as-item"><span class="ic"></span>Notifications<span class="ct">7</span></div>
              <div class="as-sec">The chair</div>
              <div class="as-item"><span class="ic"></span>Regulars<span class="ct">124</span></div>
              <div class="as-item"><span class="ic"></span>Chair calendar</div>
              <div class="as-item"><span class="ic"></span>Walk-ins</div>
              <div class="as-item"><span class="ic"></span>Inventory<span class="ct">3</span></div>
              <div class="as-sec">Finance</div>
              <div class="as-item"><span class="ic"></span>Invoices</div>
              <div class="as-item"><span class="ic"></span>Payments</div>
              <div class="as-chief">Chief AI<span class="on">Online</span></div>
            </div>
            <div class="app-canvas">
              <div class="brief">
                <div class="brief-l">
                  <div class="date">Tuesday &middot; 8:04 AM</div>
                  <div class="hi">Good morning, <b>Andre</b></div>
                  <div class="cp">Three regulars are past due for a cut, and the pomade is
                     nearly out.</div>
                  <div class="brief-btns"><span class="lnk">Read today&rsquo;s briefing</span></div>
                </div>
                <div class="chief">
                  <div class="chief-h">Chief AI<span class="on">Online</span></div>
                  <div class="chief-lead">I&rsquo;ve analyzed your day. Here&rsquo;s what I found:</div>
                  <div class="chief-f dv-drop"><span class="sq warn"></span>
                    <span class="g">3 regulars not rebooked</span><span class="tag">6 WEEKS</span></div>
                  <div class="chief-f"><span class="sq"></span>
                    <span class="g">Pomade down to 2 tubs</span><span class="tag">PO READY</span></div>
                  <div class="chief-f"><span class="sq ok"></span>
                    <span class="g">$6,910 collected</span><span class="amt">this month</span></div>
                  <div class="chief-ask">Want me to text them your Tuesday openings?</div>
                  <div class="chief-btns"><b>Yes, handle it</b><i>Review first</i></div>
                </div>
              </div>
              <div class="kpi-row">
                <div class="kpi"><span class="k">Chairs booked</span><span class="v">38</span>
                  <span class="f">4 open Friday</span></div>
                <div class="kpi"><span class="k">Regulars</span><span class="v">124</span>
                  <span class="f">9 overdue for a cut</span></div>
                <div class="kpi"><span class="k">Revenue &middot; this month</span>
                  <span class="v dv-roll"><span>$6,470</span><span>$6,910</span></span>
                  <span class="f up">&#9650; 12% vs last mo</span></div>
                <div class="kpi"><span class="k">Walk-ins today</span><span class="v">5</span>
                  <span class="f">2 before noon</span></div>
                <div class="kpi"><span class="k">Business health</span><span class="v up">61%</span>
                  <span class="f">steady</span></div>
              </div>
              <div class="qa-h">Quick Actions<span class="hint">the four you actually use</span></div>
              <div class="qa">
                <i style="--c:#C9A84C">New invoice</i>
                <i style="--c:#7C3AED">Add regular</i>
                <i style="--c:#22D3EE">Book a chair</i>
                <i style="--c:#22C55E">Walk-in</i>
                <i style="--c:#F97316">Text blast</i>
                <i style="--c:#7C3AED">New post</i>
                <i style="--c:#C9A84C">Reorder</i>
                <i style="--c:#22D3EE">Reports</i>
                <i style="--c:#6B707B">Custom</i>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── C · the counter: Inventory with Chief's order drafted,
              caught mid-decision, bleeding off the right edge ── -->
      <div class="dv-slot dv-c">
        <div class="app">
          <div class="app-top">
            <span class="at-mark"></span>
            <span class="at-search">Search or ask Chief<span class="kbd">&#8984;K</span></span>
            <span class="at-urgent">3 low</span>
            <span class="at-cta">New order</span>
            <span class="at-av"></span>
          </div>
          <div class="app-strip">
            <span class="biz">Fade &amp; Co.</span>
            <span class="tab on">Operate</span>
            <span class="sp"></span>
            <span>Inventory</span>
          </div>
          <div class="app-body">
            <div class="app-side">
              <div class="as-user"><span class="av"></span>
                <span class="nm">Andre Whitfield<span>Fade &amp; Co.</span></span>
                <span class="as-plan">PRO</span></div>
              <div class="as-sec">Mission Control</div>
              <div class="as-item"><span class="ic"></span>Dashboard</div>
              <div class="as-item"><span class="ic"></span>Needs you<span class="ct">3</span></div>
              <div class="as-sec">The chair</div>
              <div class="as-item"><span class="ic"></span>Regulars<span class="ct">124</span></div>
              <div class="as-item"><span class="ic"></span>Chair calendar</div>
              <div class="as-item is-on"><span class="ic"></span>Inventory<span class="ct">3</span></div>
              <div class="as-sec">Finance</div>
              <div class="as-item"><span class="ic"></span>Invoices</div>
              <div class="as-item"><span class="ic"></span>Payments</div>
              <div class="as-chief">Chief AI<span class="on">Online</span></div>
            </div>
            <div class="app-canvas dv-canvas">
              <div class="ah-row">
                <div>
                  <div class="ah-rule"></div>
                  <div class="ah-eyebrow">Operate</div>
                  <div class="ah-title">Inventory</div>
                  <div class="ah-sub">3 items below par &middot; Chief drafted one order</div>
                </div>
                <span class="ah-btn">New order</span>
              </div>
              <div class="dv-inv">
                <div class="h"><span>Item</span><span>On hand</span><span>Par</span><span>Status</span></div>
                <div class="t low"><span class="nm">Fade &amp; Shine Pomade 4oz</span>
                  <span class="n">2</span><span class="n">12</span><span class="pill sent">Reorder</span></div>
                <div class="t low"><span class="nm">Neck strips &mdash; box of 500</span>
                  <span class="n">1</span><span class="n">4</span><span class="pill sent">Reorder</span></div>
                <div class="t low"><span class="nm">Clipper guard set</span>
                  <span class="n">0</span><span class="n">2</span><span class="pill due">Out</span></div>
                <div class="t"><span class="nm">Blade oil 8oz</span>
                  <span class="n">18</span><span class="n">10</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Straight razor blades</span>
                  <span class="n">64</span><span class="n">40</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Barber capes &mdash; black</span>
                  <span class="n">12</span><span class="n">8</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Talc brush refill</span>
                  <span class="n">9</span><span class="n">6</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Shave cream 12oz</span>
                  <span class="n">14</span><span class="n">8</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Aftershave &mdash; cedar</span>
                  <span class="n">21</span><span class="n">12</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Disposable razors</span>
                  <span class="n">140</span><span class="n">100</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Beard oil 2oz</span>
                  <span class="n">16</span><span class="n">10</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Clipper blades &mdash; #1</span>
                  <span class="n">7</span><span class="n">6</span><span class="pill ok">OK</span></div>
                <div class="t"><span class="nm">Sanitizing jar refill</span>
                  <span class="n">5</span><span class="n">4</span><span class="pill ok">OK</span></div>
              </div>
              <div class="dv-po">
                <span class="k">Chief drafted this</span>
                <span class="t">PO-0043</span>
                <span class="s">Midway Supply &middot; 2&ndash;3 day delivery</span>
                <div class="li"><span>Fade &amp; Shine Pomade 4oz</span><b>24 &times; $6.40</b></div>
                <div class="li"><span>Neck strips &mdash; box of 500</span><b>10 &times; $3.10</b></div>
                <div class="li"><span>Clipper guard set</span><b>2 &times; $28.00</b></div>
                <div class="tot"><span>Total</span><span>$240.60</span></div>
                <div class="why">You go through about nine tubs a month, and Saturday is
                   fully booked.</div>
                <div class="acts">
                  <span class="go">Send it</span>
                  <span class="alt">Change it</span>
                  <span class="dv-cursor"></span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── B · the pocket: Chief, nearest of the three ── -->
      <div class="dv-slot dv-b">
        <div class="dv-fone">
          <div class="dv-fone-top"><span class="mk"></span><b>Chief</b><span class="on">Online</span></div>
          <div class="dv-chat">
            <div class="dv-msg you">Who hasn&rsquo;t rebooked?</div>
            <div class="dv-msg ai dv-say">Three regulars are past six weeks: Marcus, Tia and Devon.</div>
            <div class="dv-msg ai dv-say-2">Tuesday afternoon is your emptiest slot.</div>
            <div class="dv-card dv-say-3">
              <div class="k">Overdue for a cut</div>
              <div class="v">3 regulars</div>
              <div class="s">Marcus Bell &middot; Tia Okonkwo &middot; Devon Pryce</div>
              <span class="go">Text them Tuesday<span class="dv-tap"></span></span>
            </div>
          </div>
          <div class="dv-fone-bar">Ask or tell me what to do&hellip;<span class="mic"></span></div>
          <div class="dv-fone-home"></div>
        </div>
      </div>

    </div>
    <div class="dv-shade"></div>
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
<script>
(function () {
  /* Pricing cards. Three jobs: park the spotlight under the cursor,
     count the price up when the row arrives, and — only where :hover
     can never fire — run the travelling edge once so a phone gets the
     same move a desktop gets on hover. */
  var reduced = window.matchMedia &&
                window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var fine    = window.matchMedia &&
                window.matchMedia('(hover:hover) and (pointer:fine)').matches;
  var cards   = [].slice.call(document.querySelectorAll('.price-card'));
  if (!cards.length) return;

  if (fine && !reduced) {
    cards.forEach(function (c) {
      c.addEventListener('pointermove', function (e) {
        var r = c.getBoundingClientRect();
        if (!r.width || !r.height) return;
        c.style.setProperty('--pc-x', ((e.clientX - r.left) / r.width  * 100).toFixed(1) + '%');
        c.style.setProperty('--pc-y', ((e.clientY - r.top)  / r.height * 100).toFixed(1) + '%');
      });
    });
  }

  function countUp(el) {
    var to = Number(el.dataset.to || 0), pre = el.dataset.prefix || '';
    if (!to) return;
    if (reduced) { el.textContent = pre + to; return; }
    var dur = 900, t0 = null;
    function step(ts) {
      if (t0 === null) t0 = ts;
      var p = Math.min(1, (ts - t0) / dur);
      el.textContent = pre + Math.round(to * (1 - Math.pow(1 - p, 3)));  /* easeOutCubic */
      if (p < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  }

  function arrive(card, i) {
    var n = card.querySelector('.pc-num');
    if (n) countUp(n);
    if (reduced || fine) return;          /* desktop gets the edge on hover */
    setTimeout(function () {
      card.classList.add('is-lit');
      setTimeout(function () { card.classList.remove('is-lit'); }, 2700);
    }, i * 220);                          /* left to right, not all at once */
  }

  if (!('IntersectionObserver' in window)) {
    cards.forEach(function (c, i) { arrive(c, i); });
    return;
  }
  var io = new IntersectionObserver(function (entries) {
    entries.forEach(function (e) {
      if (!e.isIntersecting) return;
      arrive(e.target, cards.indexOf(e.target));
      io.unobserve(e.target);
    });
  }, { threshold: 0.35 });
  cards.forEach(function (c) { io.observe(c); });
})();
</script>
<script>
(function () {
  /* The shape section's panel. The vocabulary is the same TRADES table
     the fold runs on: if the product renames Regulars, both have to
     move together, so they are deliberately the same words. */
  var VOCAB = {
    barber:     {word:'a barber',     people:'Regulars',  room:'The chair',        work:'Chair calendar', rest:['Walk-ins','Payments']},
    therapist:  {word:'a therapist',  people:'Clients',   room:'The practice',     work:'Sessions',       rest:['Intake forms','Superbills']},
    attorney:   {word:'an attorney',   people:'Clients',   room:'The office',       work:'Matters',        rest:['Time &amp; billing','Trust ledger']},
    contractor: {word:'a contractor', people:'Customers', room:'The jobs',         work:'Jobs',           rest:['Estimates','Change orders']},
    coach:      {word:'a coach',      people:'Clients',   room:'The practice',     work:'Programs',       rest:['Sessions','Payments']},
    consultant: {word:'a consultant', people:'Clients',   room:'The book',         work:'Engagements',    rest:['Proposals','Retainers']},
    pastor:     {word:'a ministry',     people:'Members',   room:'The congregation', work:'Services',       rest:['Giving','Volunteers']}
  };

  var chips = document.getElementById('shapeChips');
  var rest  = document.getElementById('mpRest');
  var capW  = document.getElementById('mpWord');
  if (chips && rest && capW) {
    var reduced = window.matchMedia &&
                  window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var vals = {};
    ['people','room','work'].forEach(function (k) {
      vals[k] = document.querySelector('[data-mp="' + k + '"]');
    });

    var setText = function (el, text, i) {
      if (!el) return;
      if (reduced) { el.innerHTML = text; return; }
      setTimeout(function () {
        el.classList.add('out');
        setTimeout(function () {
          el.innerHTML = text;
          el.classList.remove('out');
        }, 200);
      }, i * 65);
    };

    var buttons = [].slice.call(chips.querySelectorAll('.audience-pill'));
    var cur = -1, timer = null;

    var paint = function (i) {
      var b = buttons[i];
      if (!b) return;
      var v = VOCAB[b.getAttribute('data-trade')];
      if (!v) return;
      cur = i;
      setText(capW, v.word, 0);
      setText(vals.people, v.people, 0);
      setText(vals.room,   v.room,   1);
      setText(vals.work,   v.work,   2);
      rest.innerHTML = '';
      v.rest.forEach(function (n, k) {
        var el = document.createElement('span');
        el.className = 'mp-item swap' + (reduced ? '' : ' out');
        el.innerHTML = n;
        rest.appendChild(el);
        if (!reduced) setTimeout(function () { el.classList.remove('out'); }, 240 + k * 65);
      });
      buttons.forEach(function (x, n) {
        x.setAttribute('aria-pressed', n === i ? 'true' : 'false');
      });
    };

    var stop = function () { if (timer) { clearInterval(timer); timer = null; } };
    buttons.forEach(function (b, i) {
      b.addEventListener('click', function () { stop(); paint(i); });
    });

    /* start on the barber, which is the row already in the markup, then
       cycle so the mechanic is visible without a click. Any click ends
       the cycle for good: it is a control, not a carousel. */
    var startAt = 0;
    buttons.forEach(function (b, i) { if (b.getAttribute('data-trade') === 'barber') startAt = i; });
    paint(startAt);
    if (!reduced && 'IntersectionObserver' in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting && !timer) {
            timer = setInterval(function () { paint((cur + 1) % buttons.length); }, 2800);
          } else if (!e.isIntersecting) { stop(); }
        });
      }, { threshold: 0.3 });
      io.observe(chips.closest('.shape') || chips);
    }
  }

  /* The trust section's log. Undo is real, and the footer says the undo
     was logged too, which is the half of the promise the copy could
     only assert. */
  var row = document.getElementById('trustUndoRow');
  var btn = document.getElementById('trustUndoBtn');
  var foot = document.getElementById('trustLogFoot');
  if (row && btn && foot) {
    var REST = 'Autopilot, overnight \u00b7 nothing happened without a line in this log.';
    var PULLED = 'Reminders pulled back \u00b7 the log keeps the action and the undo.';
    var undone = false;
    btn.addEventListener('click', function () {
      undone = !undone;
      row.classList.toggle('undone', undone);
      btn.textContent = undone ? 'Redo' : 'Undo';
      foot.textContent = undone ? PULLED : REST;
    });
  }
})();
</script>
<script>
(function () {
  var pill  = document.getElementById('heroPill');
  var modal = document.getElementById('videoModal');
  var vid   = document.getElementById('videoModalPlayer');
  var xBtn  = document.getElementById('videoModalClose');
  if (!pill || !modal || !vid || !xBtn) return;

  var lastFocus = null;

  function open() {
    lastFocus = document.activeElement;
    modal.setAttribute('open', '');
    document.body.style.overflow = 'hidden';
    xBtn.focus();
    /* the click that opened this counts as the gesture, so play() is
       allowed even unmuted. If a browser disagrees, the poster and the
       controls are already there and nothing is broken. */
    var p = vid.play();
    if (p && p.catch) p.catch(function () {});
  }

  function close() {
    modal.removeAttribute('open');
    document.body.style.overflow = '';
    vid.pause();
    /* back where they were, or the pill. A programmatic open leaves
       activeElement on <body>, and restoring focus to the body drops the
       keyboard user at the top of the document instead of where they
       opened the dialog from. */
    var back = (lastFocus && lastFocus.focus && lastFocus !== document.body)
             ? lastFocus : pill;
    back.focus();
  }

  pill.addEventListener('click', open);
  xBtn.addEventListener('click', close);
  /* the backdrop closes; a click inside the box must not */
  modal.addEventListener('click', function (e) { if (e.target === modal) close(); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && modal.hasAttribute('open')) close();
  });

  /* keep the tab ring inside the dialog while it is open */
  modal.addEventListener('keydown', function (e) {
    if (e.key !== 'Tab') return;
    var focusable = [xBtn, vid];
    var first = focusable[0], last = focusable[focusable.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
})();
</script>
"""
    return _render_shell(
        title="One workspace that runs your whole business",
        description="The business system that already knows how yours runs. Bookings, clients, invoices, and an AI chief of staff that logs every move and never acts without your approval.",
        content_html=body, path="/",
        extra_css=extra_css + SPINE_CSS + DEVICE_BAND_CSS,
        extra_scripts=extra_scripts + SPINE_SCRIPT + FOLD_SCRIPT,
    )


# ══════════════════════════════════════════════════════════════════════
# FEATURES — surface-by-surface deep dive
# ══════════════════════════════════════════════════════════════════════

def render_features() -> str:
    extra_css = REPLICA_KIT_CSS + FEATURES_FX_CSS + DEMO_CSS + """

      /* ── the way through nine sections ────────────────────────────
         5,900px with no navigation: you scrolled or you left. A left
         rail only has room to exist above ~1400px, which would have
         been navigation for wide monitors and nothing for anyone else.
         A sticky strip works at every width, and the main nav is
         absolute now so nothing is competing for the top edge. */
      .fs-nav{position:sticky;top:0;z-index:40;
        background:color-mix(in srgb, var(--bg) 86%, transparent);
        backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
        border-bottom:1px solid var(--border);}
      .fsn-row{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;
        padding:10px 0;-webkit-overflow-scrolling:touch;}
      .fsn-row::-webkit-scrollbar{display:none;}
      .fsn-l{flex:0 0 auto;font-size:13px;font-weight:500;white-space:nowrap;
        padding:7px 14px;border-radius:99px;color:var(--text-muted);
        transition:color .16s, background .16s;}
      .fsn-l:hover{color:var(--text-primary);background:var(--surface);}
      .fsn-l.is-here{color:var(--accent);background:color-mix(in srgb, var(--accent) 14%, transparent);
        font-weight:600;}
      .fsn-l:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
      /* the strip is what pins now, so anchored sections clear IT */
      .feature-section{scroll-margin-top:64px;}

      /* Eleven pills in a run read heavy because they were drawn as
         eleven buttons. They are a list of capabilities, so: one hairline
         each, no fill, and the dot carries the accent instead of the
         border. Same information, a third of the visual weight. */
      .fs-chips .fs-chip{background:transparent;border-color:var(--border);}
      .feature-section{padding:128px 0;border-bottom:1px solid var(--border);}
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

<nav class="fs-nav" id="fsNav" aria-label="Sections on this page">
  <div class="container">
    <div class="fsn-row">
      <a href="#fs-command" class="fsn-l">Command Center</a>
      <a href="#fs-build" class="fsn-l">Build</a>
      <a href="#fs-operate" class="fsn-l">Operate</a>
      <a href="#fs-grow" class="fsn-l">Grow</a>
      <a href="#fs-chief" class="fsn-l">Chief of Staff</a>
      <a href="#fs-channels" class="fsn-l">Channels</a>
    </div>
  </div>
</nav>

<section class="feature-section" id="fs-command">
  <div class="container">
    <div class="fs-grid">
      <div class="reveal">
        <div class="fs-eyebrow"><svg class="fs-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/></svg>Command Center</div>
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
            <span class="at-search">Mission Control</span><span class="at-av"></span></div>
          <div class="app-canvas" style="justify-content:center;">
            <div class="pal">
              <div class="pal-in"><span class="pal-ico"></span>
                <span class="pal-q">book marcus thursday</span><span class="caret"></span>
                <span class="pal-kbd">&#8984;K</span></div>
              <div class="pal-r on"><span class="pal-d" style="--c:#22C55E"></span>Book a session &middot; Marcus Bell, Thu 2:00&nbsp;PM<span class="k">&crarr;</span></div>
              <div class="pal-r"><span class="pal-d" style="--c:#2E7DFF"></span>Draft an email to Marcus Bell<span class="k">&darr;</span></div>
              <div class="pal-r"><span class="pal-d" style="--c:#EF4444"></span>Chase 3 overdue invoices<span class="k">&darr;</span></div>
              <div class="pal-r"><span class="pal-d" style="--c:#C9A84C"></span>Open Marcus Bell&rsquo;s record<span class="k">&darr;</span></div>
            </div>
            <div class="pal-voice">
              <span class="wave"><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>
              <span>Listening &middot; say &ldquo;Hey Chief&rdquo;</span>
              <span class="hint">or press &#8984;K</span>
            </div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>One bar for everything. Type it, or just say it out loud.</div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section" id="fs-build">
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
        <div class="fsv-cap"><span class="dot"></span>Composed from your brand DNA, section by section, not a template.</div>
      </div>
      <div class="reveal reveal-delay-1">
        <div class="fs-eyebrow"><svg class="fs-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="7" height="7" x="14" y="3" rx="1"/><path d="M10 21V8a1 1 0 0 0-1-1H4a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5a1 1 0 0 0-1-1"/></svg>Build</div>
        <h2>Sites, brand and intake, all yours.</h2>
        <p>Spin up your own site, set your brand kit (colors, fonts, logo), capture leads through intake forms, and wire up the integrations you need.</p>
        <ul class="fs-list">
          <li>Practitioner sites</li><li>Brand kits</li><li>Intake forms</li><li>Custom modules</li>
          <li>Print materials</li><li>Booking page</li><li>Link page</li><li>Email templates</li>
          <li>Products &amp; services</li><li>Integrations hub</li>
        </ul>
      </div>
    </div>
  </div>
</section>

<section class="feature-section" id="fs-operate">
  <div class="container">
    <div class="fs-grid">
      <div class="reveal">
        <div class="fs-eyebrow"><svg class="fs-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1"/></svg>Operate</div>
        <h2>The day-to-day plumbing.</h2>
        <p>Track contacts, send branded invoices, manage your calendar, run tasks, handle email and SMS, all from one screen with one search bar.</p>
        <ul class="fs-list">
          <li>Contacts (CRM)</li><li>Invoices &amp; payments</li><li>Calendar</li><li>Tasks</li>
          <li>Email hub</li><li>SMS hub</li><li>Projects</li><li>Documents</li><li>Autopilot agents</li>
        </ul>
      </div>
      <div class="fs-visual fsv reveal reveal-delay-1">
        <div class="app">
          <div class="app-top"><span class="at-mark"></span>
            <span class="at-search">Operate &middot; Inbox</span><span class="at-cta">+ New</span></div>
          <div class="app-canvas">
            <div class="inbox">
              <div class="pnl fx-seq" style="min-height:0;">
                <div class="pnl-h">All channels<span class="ct">6</span></div>
                <div class="r"><span class="bar red"></span><span class="pill mail">Email</span>
                  <span class="g nm">Marcus Bell<span>Re: Thursday, can we push to 3?</span></span><span class="amt">9:04</span></div>
                <div class="r"><span class="bar amb"></span><span class="pill sms">SMS</span>
                  <span class="g nm">Tia Randall<span>Got it, thank you!</span></span><span class="amt">8:41</span></div>
                <div class="r"><span class="bar"></span><span class="pill mail">Email</span>
                  <span class="g nm">Grace Chapel<span>Invoice received, paying Friday</span></span><span class="amt">Tue</span></div>
                <div class="r"><span class="bar"></span><span class="pill sms">SMS</span>
                  <span class="g nm">J. Okafor<span>Confirming next week</span></span><span class="amt">Tue</span></div>
              </div>
              <div class="pnl rec">
                <div class="rec-h"><span class="av" style="background:#3B82F6">MB</span>
                  <span class="nm">Marcus Bell<span>Client since Mar 2026</span></span></div>
                <span class="pill ok" style="align-self:flex-start;">Good standing</span>
                <div class="rec-g">
                  <div><b>4</b><span>Sessions</span></div>
                  <div><b>$3,140</b><span>Billed</span></div>
                  <div><b>1</b><span>Overdue</span></div>
                </div>
                <div class="rec-t">
                  <div><span class="d"></span>Session booked &middot; Thu 2:00</div>
                  <div><span class="d"></span>Invoice sent &middot; $640</div>
                  <div><span class="d"></span>Note added by Chief</div>
                </div>
              </div>
            </div>
            <div class="r"><span class="bar"></span><span class="g">Email, SMS, calendar and billing on one contact, one thread, one search bar</span><span class="pill live">Unified</span></div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>Every channel lands on the same record. Nothing to reconcile by hand.</div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section" id="fs-grow">
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
        <div class="fsv-cap"><span class="dot"></span>Every metric updates as the data changes, not on a weekly report.</div>
      </div>
      <div class="reveal reveal-delay-1">
        <div class="fs-eyebrow"><svg class="fs-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/><polyline points="16 7 22 7 22 13"/></svg>Grow</div>
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

<section class="feature-section" id="fs-chief">
  <div class="container">
    <div class="fs-grid">
      <div class="reveal">
        <div class="fs-eyebrow"><svg class="fs-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.9 5.8L4 10.7l6.1 1.9L12 18.4l1.9-5.8 6.1-1.9-6.1-1.9z"/><path d="M19 3v4M21 5h-4"/></svg>Chief of Staff</div>
        <h2>An AI that knows your business.</h2>
        <p>Not a generic LLM. Chief reads your real contacts, invoices, goals, content, and brand on every turn. Ask for input, delegate actions, get tactical guidance, by chat or by voice.</p>
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
            <div class="cx-b ai">Three invoices are past due, <b>$2,140</b> total. Want me to send reminders?</div>
            <div class="cx-b you">Yes, and book Marcus for Thursday.</div>
            <div class="cx-b act">&#10003; 3 reminders sent &middot; 1 session booked</div>
          </div>
        </div>
        <div class="fsv-cap"><span class="dot"></span>It reads your live data every turn, then does the work.</div>
      </div>
    </div>
  </div>
</section>

<section class="feature-section" id="fs-channels">
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
                off the hard conversation about your numbers, this is the room for it.&rdquo;</div>
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
        <div class="fs-eyebrow"><svg class="fs-ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/></svg>Publish to Facebook + Instagram</div>
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

<section id="demo" class="demo-section">
  <div class="container">
    <div class="section-head reveal">
            <span data-spine class="eyebrow">See it move</span>
      <h2>Fifty-eight seconds, <span class="gradient-text">end to end.</span></h2>
      <p>One photographer's Tuesday: Home, Chief, the rooms, the shift it works while you are closed, and the one thing it will not do without you.</p>
    </div>
    <div class="demo-frame reveal">
      <div class="demo-chrome"><span></span><span></span><span></span><em>The Solutionist System</em></div>
      <video class="demo-video" controls playsinline preload="metadata" poster="/assets/film-poster.jpg?v=2">
        <source src="/assets/film.mp4?v=2" type="video/mp4">
        Your browser doesn't support embedded video. <a href="/assets/film.mp4?v=2">Download the film</a>.
      </video>
    </div>
  </div>
</section>

<section class="final-cta">
  <div class="container">
    <span class="eyebrow reveal">Ready to try it?</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">Open it and see.</h2>
    <p class="reveal reveal-delay-2">__TRIAL_FREE__ on any plan. Your workspace arrives already
       speaking your trade, so there is nothing to configure before it is useful.</p>
    <a class="btn-primary reveal reveal-delay-3" href="/start">Start your free trial →</a>
  </div>
</section>
"""
    return _render_shell(
        title="Features",
        description="Every surface in the Solutionist System: Command Center, Build, Operate, Grow, Chief of Staff, and Publish.",
        content_html=body, path="/features", active="features", extra_css=extra_css, extra_scripts=FEATURES_SCRIPT + """
<script>
(function () {
  var bar = document.getElementById('fsNav');
  if (!bar || !('IntersectionObserver' in window)) return;
  var links = {};
  var ls = bar.querySelectorAll('.fsn-l');
  for (var i = 0; i < ls.length; i++) {
    links[ls[i].getAttribute('href').slice(1)] = ls[i];
  }
  var secs = document.querySelectorAll('.feature-section[id]');
  if (!secs.length) return;

  var here = null;
  function light(id) {
    if (id === here) return;
    here = id;
    for (var k in links) {
      if (Object.prototype.hasOwnProperty.call(links, k)) {
        links[k].classList.toggle('is-here', k === id);
      }
    }
  }

  /* Top-biased band: a section counts as "here" once its heading has
     reached the upper third, which is where you are actually reading —
     not when it merely touches the viewport. */
  var io = new IntersectionObserver(function (entries) {
    var best = null;
    for (var i = 0; i < entries.length; i++) {
      if (entries[i].isIntersecting) {
        if (!best || entries[i].boundingClientRect.top < best.boundingClientRect.top) {
          best = entries[i];
        }
      }
    }
    if (best) light(best.target.id);
  }, { rootMargin: '-64px 0px -66% 0px', threshold: 0 });

  for (var j = 0; j < secs.length; j++) io.observe(secs[j]);
})();
</script>
""",
    )


# ══════════════════════════════════════════════════════════════════════
# COMPARE — polished comparison page
# ══════════════════════════════════════════════════════════════════════

# ── the compare page's arithmetic ────────────────────────────────────
# Both of these are quoted twice on /compare: once as the headline in
# the fold, once at the foot of the itemised stack. They live here so a
# price change lands in both places or neither. The per-tool prices
# under STACK_TOTAL are list prices for the named plans and are stated
# as "about" for that reason.
STACK_TOTAL = "$125+"
SOLUTIONIST_FROM = "$79"


def render_compare() -> str:
    extra_css = """

      /* ── the arithmetic, in the fold ──────────────────────────────
         The number that wins this page was already on it and sat about
         1,400px down. Both figures come from STACK_TOTAL and
         SOLUTIONIST_FROM, so this cannot drift from the itemised card
         below it. The list stays there: the fold makes the claim, the
         section proves it. */
      .cmp-math{display:grid;grid-template-columns:1fr auto 1fr;gap:24px;align-items:center;
        max-width:820px;margin:44px auto 0;text-align:left;}
      .cmp-side{display:flex;flex-direction:column;gap:5px;}
      .cmp-lbl{font-size:10.5px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;
        color:var(--text-dim);}
      .cmp-fig{font-family:var(--font-heading);font-size:52px;font-weight:700;letter-spacing:-.035em;
        line-height:1;color:var(--accent);font-variant-numeric:tabular-nums;}
      .cmp-fig.alt{color:var(--text-muted);}
      .cmp-fig i{font-style:normal;font-size:16px;font-weight:500;letter-spacing:0;
        color:var(--text-dim);margin-left:3px;}
      .cmp-sub{font-size:12.5px;color:var(--text-dim);line-height:1.5;}
      .cmp-arrow{display:flex;align-items:center;justify-content:center;}
      .cmp-arrow span{display:block;width:38px;height:1px;background:var(--border-strong);
        position:relative;}
      .cmp-arrow span::after{content:'';position:absolute;right:0;top:-3.5px;
        border-left:7px solid var(--accent);border-top:4px solid transparent;
        border-bottom:4px solid transparent;}
      @media (max-width: 720px){
        .cmp-math{grid-template-columns:1fr;gap:14px;text-align:center;}
        .cmp-side{align-items:center;}
        .cmp-fig{font-size:44px;}
        .cmp-arrow span{width:1px;height:26px;}
        .cmp-arrow span::after{right:-3.5px;top:auto;bottom:0;
          border-left:4px solid transparent;border-right:4px solid transparent;
          border-top:7px solid var(--accent);border-bottom:0;}
      }

      /* Ten rows is long enough that the column you are reading stops
         being obvious. The head pins under the page's own sticky
         offset so "Solutionist" and "The 8-tool stack" stay overhead. */
      table.compare thead th{position:sticky;top:0;z-index:2;
        background:color-mix(in srgb, var(--bg) 92%, transparent);
        backdrop-filter:blur(12px);-webkit-backdrop-filter:blur(12px);}
      /* The tier table is where the decision actually gets made, and it
         ended with nothing to press: the only door was the final CTA two
         sections further down, past "Switching from?". */
      .compare-door{display:flex;flex-direction:column;align-items:center;
        gap:12px;margin-top:30px;text-align:center;}
      .compare-door span{max-width:480px;font-size:12.5px;line-height:1.6;
        color:var(--text-muted);}

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
      .table-wrap{overflow-x:auto;}
      .compare.plans{min-width:600px;}
      .compare.plans td{font-variant-numeric:tabular-nums;}
      .switch-grid{display:grid;grid-template-columns:repeat(3, 1fr);gap:18px;margin-top:14px;}
      @media (max-width: 860px){.switch-grid{grid-template-columns:1fr;}}
      .switch-card{padding:24px;background:var(--surface);border:1px solid var(--border);border-radius:14px;}
      .switch-card h3{font-family:var(--font-heading);color:var(--text-primary);font-size:16px;margin-bottom:10px;}
      .switch-card p{font-size:14px;color:var(--text-muted);line-height:1.6;}
      .switch-card p + p{margin-top:10px;}
    """
    body = """
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">Solutionist vs. alternatives</span>
    <h1 class="reveal reveal-delay-1">Eight tools that don&rsquo;t know each other.<br>Or <span class="gradient-text">one that knows you.</span></h1>
    <p class="lead reveal reveal-delay-2" style="max-width:700px;margin:14px auto 0;">The stack is not expensive because of what it costs. It is expensive because you are the integration layer.</p>
    <div class="cmp-math reveal reveal-delay-3">
      <div class="cmp-side">
        <span class="cmp-lbl">Eight tools, list price</span>
        <span class="cmp-fig alt">""" + STACK_TOTAL + """<i>/mo</i></span>
        <span class="cmp-sub">HubSpot &middot; Stripe &middot; Calendly &middot; Buffer &middot; Notion
          &middot; Mixpanel &middot; Squarespace &middot; ChatGPT</span>
      </div>
      <div class="cmp-arrow" aria-hidden="true"><span></span></div>
      <div class="cmp-side">
        <span class="cmp-lbl">One system</span>
        <span class="cmp-fig">""" + SOLUTIONIST_FROM + """<i>/mo</i></span>
        <span class="cmp-sub">Everything below, on one login, sharing what it knows</span>
      </div>
    </div>

  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">The real number</span>
      <h2>The subscriptions are the cheap part.</h2>
      <p>Add up the subscriptions and you get one number. Add up the re-typing, the copy-paste between tabs, the context you rebuild every time you open ChatGPT, and the client who slipped because two tools disagreed about what happened, and you get the real one. A stack of eight tools has no idea you exist: each one holds a slice of your business and none of them holds the business.</p>
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
        <div class="cost-total"><span class="label">≈ Total</span><span class="price">""" + STACK_TOTAL + """ /mo</span></div>
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
        <div class="cost-total"><span class="label">From</span><span class="price">$79 /mo</span></div>
        <p style="margin-top:14px;font-size:12px;color:var(--text-dim);">Starter $79 &middot; Professional $199 &middot; Solutionist $399. Every plan starts with __TRIAL_FREE__, and you can cancel yourself at any time.</p>
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
""" + _plan_compare_section_html() + """
<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">Switching from?</span>
      <h2>If you're coming from these, here's what's different.</h2>
    </div>
    <div class="switch-grid">
      <div class="switch-card reveal">
        <h3>From Notion</h3>
        <p>Notion is a blank canvas, flexible but you build everything yourself, and there's no AI that reads your business data. Solutionist comes opinionated: contacts work like contacts, invoices work like invoices, goals work like goals. You skip the database-design stage.</p>
      </div>
      <div class="switch-card reveal reveal-delay-1">
        <h3>From HubSpot</h3>
        <p>HubSpot is enterprise CRM at scale, with sales-team assumptions, deal pipelines built for B2B reps, and pricing that doesn't fit a one-person business. Solutionist is purpose-built for one operator running their whole business, not a sales team managing leads.</p>
      </div>
      <div class="switch-card reveal reveal-delay-2">
        <h3>From &ldquo;I&rsquo;ll just build my own agent&rdquo;</h3>
        <p>You can. The tools are genuinely good now, and you&rsquo;ll have something impressive running in an afternoon.</p>
        <p>Then it double-books a client. Then it promises a refund policy you don&rsquo;t have. Then it forgets what happened last Tuesday. Not because the AI isn&rsquo;t smart, but because smart isn&rsquo;t the same as dependable, and dependable is built, not prompted.</p>
        <p>That&rsquo;s the part that took us since January: knowing what a booking agent must never do, what has to be logged, what has to ask first, what a week in your line of work actually looks like. You&rsquo;d be starting that from zero, and everything your business teaches it would live in a tool you have to maintain forever.</p>
        <p>Ours shows up already knowing your business. And it keeps everything it learns about yours specifically.</p>
      </div>
    </div>
  </div>
</section>

<section class="final-cta">
  <div class="container">
    <span class="eyebrow reveal">Stop stitching tools.</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">One workspace, one login, one Chief.</h2>
    <a class="btn-primary reveal reveal-delay-3" href="/start" style="margin-top:14px;">Start your free trial →</a>
  </div>
</section>
"""
    return _render_shell(
        title="Compare",
        description="Eight tools that do not know each other, or one that knows you. Feature-by-feature comparison and switching guides for the Solutionist System.",
        content_html=body, path="/compare", active="compare", extra_css=extra_css,
    )


# ══════════════════════════════════════════════════════════════════════
# FAQ
# ══════════════════════════════════════════════════════════════════════

def render_faq() -> str:
    extra_css = """
      /* Ten closed headings in one flat run gave nobody a way to find the
         thing they came to check. The accordion was already here; what
         was missing was somewhere to aim. Groups, not a search box: at
         ten questions a filter is faster to use than a field to type in,
         and it shows you the shape of the list as a side effect. */
      .faq-filter{display:flex;flex-wrap:wrap;gap:8px;max-width:780px;margin:0 auto 20px;}
      .faq-f{font:inherit;font-size:13.5px;font-weight:500;cursor:pointer;
        display:inline-flex;align-items:center;gap:7px;padding:8px 15px;border-radius:99px;
        border:1px solid var(--border);background:transparent;color:var(--text-secondary);
        transition:color .16s, background .16s, border-color .16s;}
      .faq-f span{font-family:var(--font-mono);font-size:11px;color:var(--text-dim);}
      .faq-f:hover{color:var(--text-primary);border-color:var(--border-strong);}
      .faq-f[aria-pressed="true"]{background:color-mix(in srgb, var(--accent) 16%, transparent);
        border-color:color-mix(in srgb, var(--accent) 44%, transparent);color:var(--accent);font-weight:600;}
      .faq-f[aria-pressed="true"] span{color:var(--accent);}
      .faq-f:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
      .faq-item[hidden]{display:none;}
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
    <p class="lead reveal reveal-delay-2" style="max-width:600px;margin:14px auto 0;">Don't see your question? Email us at <a href="mailto:__CONTACT_EMAIL__" style="color:var(--accent);">__CONTACT_EMAIL__</a>.</p>
  </div>
</section>

<section>
  <div class="container-narrow">
    <div class="faq-filter reveal" id="faqFilter" role="group" aria-label="Filter questions">
      <button type="button" class="faq-f" data-f="all"   aria-pressed="true">Everything<span>10</span></button>
      <button type="button" class="faq-f" data-f="fit"   aria-pressed="false">Is it for me<span>3</span></button>
      <button type="button" class="faq-f" data-f="how"   aria-pressed="false">How it works<span>3</span></button>
      <button type="button" class="faq-f" data-f="money" aria-pressed="false">Money<span>2</span></button>
      <button type="button" class="faq-f" data-f="data"  aria-pressed="false">Your data<span>2</span></button>
    </div>
    <div class="faq-list reveal" id="faqList">
      <details class="faq-item" data-g="fit">
        <summary>Who is this actually for?</summary>
        <div class="faq-body"><p>People who run the whole thing themselves: pastors, ministry leaders, coaches, consultants, creatives, agencies-of-one, and small service businesses. If you run your whole show, from sales and delivery to marketing and finances, Solutionist is for you. If you have a 20-person team with a dedicated ops person, it's overkill.</p></div>
      </details>
      <details class="faq-item" data-g="fit">
        <summary>Do I need a team to use this?</summary>
        <div class="faq-body"><p>No. Solo-first is the default: one operator, everything in one workspace. When you do bring people in, the Solutionist plan includes team seats with roles and an accountant collaborator seat: invite by email, they see the business, no enterprise admin sprawl.</p></div>
      </details>
      <details class="faq-item" data-g="money">
        <summary>What about pricing?</summary>
        <div class="faq-body"><p>Starter is $79/month, Professional $199, and Solutionist $399. Every plan is the whole product; bigger plans add AI headroom, deeper analysis, and room for a team. See the <a href="/compare" style="color:var(--accent);">plan comparison</a> for the side-by-side. Every plan opens with __TRIAL_FREE__, and you can move between tiers or cancel yourself from inside the app.</p></div>
      </details>
      <details class="faq-item" data-g="how">
        <summary>How is this different from Notion, HubSpot, or just using ChatGPT?</summary>
        <div class="faq-body">
          <p><strong>Notion</strong> is a blank canvas, so you'd build all this yourself, and it doesn't have an AI that knows your actual business data.</p>
          <p><strong>HubSpot</strong> is enterprise CRM with a steep learning curve, sales-team assumptions, and pricing that doesn't fit a one-person business.</p>
          <p><strong>ChatGPT</strong> is generic, so you have to re-explain your business every time. Chief reads your real contacts, invoices, goals, content, and brand on every turn.</p>
          <p>Solutionist is purpose-built for solo operators with AI woven through every surface.</p>
          <p>See the full <a href="/compare" style="color:var(--accent);">comparison page</a> for the side-by-side.</p>
        </div>
      </details>
      <details class="faq-item" data-g="how">
        <summary>Does the AI replace my judgment?</summary>
        <div class="faq-body"><p>No. Chief drafts, suggests, and assists. It never sends without you approving (except for explicit actions you ask it to take, like "send this email" or "publish this post"). It's an instrument, not a replacement.</p></div>
      </details>
      <details class="faq-item" data-g="data">
        <summary>What about my existing tools? Do I have to move everything?</summary>
        <div class="faq-body"><p>No. Connect what you want (Stripe for payments, Facebook for publishing, Resend for email). The rest stays. Solutionist is opinionated about workflow but not greedy, so you can keep Calendly or your existing email tool and Solutionist will work around it.</p></div>
      </details>
      <details class="faq-item" data-g="data">
        <summary>How secure is my data?</summary>
        <div class="faq-body"><p>Connected social account tokens and other credentials are stored server-side only, and your browser never sees them. We use Supabase for data storage and Railway for hosting. You can disconnect any integration immediately from the app, which deletes the stored token. Full details in the <a href="/privacy" style="color:var(--accent);">Privacy Policy</a>.</p></div>
      </details>
      <details class="faq-item" data-g="fit">
        <summary>Does it work for churches and ministries?</summary>
        <div class="faq-body"><p>It works for the <em>person</em> running a church or ministry: pastors, ministry leaders, faith-based coaches. The product is solo-first: one person runs the workspace. The Solutionist plan adds staff seats when you need them. If you need full church membership tools, we're not the right fit yet (those are on the roadmap).</p></div>
      </details>
      <details class="faq-item" data-g="how">
        <summary>Can the AI publish to my social accounts?</summary>
        <div class="faq-body"><p>Yes, once you connect your Facebook Page (and linked Instagram Business account). Chief can draft, schedule, and publish directly. You approve each post; nothing goes out without your action. Connect from <strong>Build → Integrations → Social Publishing</strong>.</p></div>
      </details>
      <details class="faq-item" data-g="money">
        <summary>When can I sign up?</summary>
        <div class="faq-body"><p>Right now, and you do it yourself. <a href="/start" style="color:var(--accent);">Start your free trial</a>, name your business, and the workspace is built around that trade before you have typed anything else. No application, no waiting list, no call to book. If you would rather talk to a person first, <a href="/get-started" style="color:var(--accent);">we're here</a>.</p></div>
      </details>
    </div>
    <div style="text-align:center;margin-top:48px;" class="reveal reveal-delay-2">
      <a class="btn-primary" href="/start">Start your free trial →</a>
    </div>
  </div>
</section>
"""
    return _render_shell(
        title="FAQ",
        description="Answers to common questions about the Solutionist System: who it's for, pricing, how it compares to other tools, security, and signup.",
        content_html=body, path="/faq", active="faq", extra_css=extra_css,
        extra_scripts="""
<script>
(function () {
  var bar  = document.getElementById('faqFilter');
  var list = document.getElementById('faqList');
  if (!bar || !list) return;
  var items = list.querySelectorAll('.faq-item');

  function openFirstVisible() {
    var first = null;
    for (var i = 0; i < items.length; i++) {
      if (!items[i].hidden) { first = items[i]; break; }
    }
    /* Every group lands with its first answer already open, so a filter
       never resolves to a column of closed headings. */
    for (var j = 0; j < items.length; j++) items[j].open = (items[j] === first);
  }

  function apply(f) {
    for (var i = 0; i < items.length; i++) {
      items[i].hidden = !(f === 'all' || items[i].getAttribute('data-g') === f);
    }
    var btns = bar.querySelectorAll('.faq-f');
    for (var k = 0; k < btns.length; k++) {
      btns[k].setAttribute('aria-pressed', String(btns[k].getAttribute('data-f') === f));
    }
    openFirstVisible();
  }

  bar.addEventListener('click', function (e) {
    var b = e.target.closest('.faq-f');
    if (b) apply(b.getAttribute('data-f'));
  });

  openFirstVisible();
})();
</script>
""",
    )


# ══════════════════════════════════════════════════════════════════════
# ABOUT
# ══════════════════════════════════════════════════════════════════════

def render_about() -> str:
    """Why the system exists — not who built it.

    Rewritten 2026-08-20 on Kevin's ask: the page was a founder note with
    his name, his signature, the state the LLC was formed in, and a card
    listing the stack. None of that is the reason a visitor is on this
    page. What they are actually asking is "why does this exist, and do
    these people think about it the way I do?" — so the page answers that,
    in the company's voice, with the three principles as the proof.

    Deliberately gone: the founder card, the name and signature, every
    mention of where the company was formed, and the stack card (an
    inventory of our attack surface, published for no one's benefit).

    Michigan still appears in the Terms (governing law) and the Privacy
    Policy (the registered entity) — those are legal statements, not
    marketing copy, and removing them there would be wrong.
    """
    extra_css = """
      /* ── the one picture on this page ──────────────────────────────
         Seven sections of prose and nothing to look at, so the argument
         was being read by almost nobody who started it. This is the
         claim the page already makes, drawn: eight boxes that do not
         touch, then one that does. The eight are CATEGORIES, not named
         products — naming competitors would be a claim about other
         companies, and the point does not need one. */
      .stk{margin:38px 0;padding:0;display:grid;grid-template-columns:1fr auto 1fr;
        gap:22px;align-items:center;}
      .stk-lbl{font-size:10.5px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;
        color:var(--text-dim);margin:0 0 12px;}
      .stk-grid{list-style:none;margin:0;padding:0;display:grid;
        grid-template-columns:repeat(2,1fr);gap:8px;}
      .stk-t{border:1px solid var(--border);border-radius:9px;padding:10px 12px;
        background:var(--bg-2);display:flex;flex-direction:column;gap:2px;}
      .stk-t .n{font-family:var(--font-heading);font-size:14px;font-weight:600;
        color:var(--text-secondary);letter-spacing:-.01em;}
      .stk-t .s{font-size:10.5px;color:var(--text-dim);}
      .stk-turn{display:flex;align-items:center;justify-content:center;}
      .stk-turn span{display:block;width:34px;height:1px;background:var(--border-strong);
        position:relative;}
      .stk-turn span::after{content:'';position:absolute;right:0;top:-3.5px;
        border-left:7px solid var(--accent);border-top:4px solid transparent;
        border-bottom:4px solid transparent;}
      .stk-one{border:1px solid color-mix(in srgb, var(--accent) 45%, transparent);
        border-radius:12px;padding:20px 18px;background:color-mix(in srgb, var(--accent) 8%, var(--bg-2));
        display:flex;flex-direction:column;gap:7px;min-height:118px;justify-content:center;}
      .stk-one .n{font-family:var(--font-heading);font-size:19px;font-weight:700;
        color:var(--text-primary);letter-spacing:-.02em;}
      .stk-one .s{font-size:12.5px;color:var(--text-secondary);line-height:1.5;}
      .stk-note{margin:12px 0 0;font-size:12.5px;color:var(--text-dim);line-height:1.5;}
      .stk-cap{grid-column:1 / -1;margin:22px 0 0;text-align:center;font-size:13px;
        color:var(--text-muted);font-style:italic;}
      @media (max-width: 760px){
        .stk{grid-template-columns:1fr;gap:16px;}
        /* the arrow turns to point down when the halves stack */
        .stk-turn span{width:1px;height:30px;}
        .stk-turn span::after{right:-3.5px;top:auto;bottom:0;
          border-left:4px solid transparent;border-right:4px solid transparent;
          border-top:7px solid var(--accent);border-bottom:0;}
      }
      .why-body{max-width:660px;margin:0 auto;}
      .why-body p{font-size:16.5px;line-height:1.75;color:var(--text-secondary);margin-bottom:18px;}
      .why-body p:last-child{margin-bottom:0;}
      .why-body b{color:var(--text-primary);font-weight:600;}
      .why-pull{margin:34px auto;max-width:660px;padding:22px 26px;border-left:2px solid var(--accent);
        background:linear-gradient(90deg, color-mix(in srgb, var(--accent) 7%, transparent), transparent 70%);
        font-family:var(--font-heading);font-size:21px;line-height:1.4;letter-spacing:-.02em;
        color:var(--text-primary);}

      /* Eight tools that never spoke to each other, and the thing that
         replaced them. The page says it; this shows it. */
      .stack-flow{display:grid;grid-template-columns:1fr 72px 1fr;align-items:center;gap:10px;
        max-width:940px;margin:0 auto;}
      .stack-cap{font-size:10px;font-weight:800;letter-spacing:.18em;text-transform:uppercase;
        color:var(--text-dim);margin-bottom:12px;display:block;}
      .stack-eight{display:grid;grid-template-columns:repeat(2,1fr);gap:8px;}
      .stack-eight span{display:flex;align-items:center;gap:9px;padding:12px 13px;border-radius:10px;
        font-size:13.5px;color:var(--text-secondary);border:1px dashed var(--border-strong);
        background:rgba(255,255,255,.025);}
      /* each one sitting on its own island is the point */
      .stack-eight span::before{content:'';width:7px;height:7px;border-radius:2px;flex-shrink:0;
        background:var(--text-dim);opacity:.55;}
      .stack-arrow{position:relative;height:64px;}
      .stack-arrow::before{content:'';position:absolute;left:0;right:14px;top:50%;height:2px;
        margin-top:-1px;border-radius:2px;
        background:linear-gradient(90deg, rgba(255,255,255,.10), var(--accent));}
      .stack-arrow::after{content:'';position:absolute;right:0;top:50%;width:11px;height:11px;
        margin-top:-5.5px;border-radius:50%;background:var(--accent);
        box-shadow:0 0 16px var(--glow), 0 0 0 4px color-mix(in srgb, var(--accent) 14%, transparent);}
      .stack-one{padding:24px;border-radius:16px;position:relative;overflow:hidden;
        border:1px solid color-mix(in srgb, var(--accent) 45%, transparent);
        background:linear-gradient(160deg, color-mix(in srgb, var(--accent) 12%, transparent),
                                            rgba(255,255,255,.02));
        box-shadow:0 18px 50px -20px rgba(0,0,0,.7);}
      .stack-one b{display:block;font-family:var(--font-heading);font-size:22px;font-weight:700;
        letter-spacing:-.02em;color:var(--text-primary);}
      .stack-one em{display:block;font-style:normal;font-size:13px;color:var(--text-muted);margin-top:8px;
        line-height:1.6;}
      @media (max-width:760px){
        .stack-flow{grid-template-columns:1fr;gap:16px;}
        .stack-arrow{height:44px;width:100%;}
        .stack-arrow::before{left:50%;right:auto;top:0;bottom:14px;width:2px;height:auto;margin:0 0 0 -1px;
          background:linear-gradient(180deg, rgba(255,255,255,.10), var(--accent));}
        .stack-arrow::after{right:auto;left:50%;top:auto;bottom:0;margin:0 0 0 -5.5px;}
      }

      .principles{display:grid;grid-template-columns:repeat(3, 1fr);gap:18px;margin-top:14px;}
      @media (max-width: 860px){.principles{grid-template-columns:1fr;}}
      .principle{padding:26px 24px;background:var(--surface);border:1px solid var(--border);
        border-radius:14px;position:relative;}
      .principle .num{font-family:var(--font-heading);font-size:11px;font-weight:700;color:var(--accent);
        letter-spacing:1.4px;text-transform:uppercase;margin-bottom:10px;}
      .principle h3{font-family:var(--font-heading);font-size:16.5px;color:var(--text-primary);margin-bottom:8px;}
      .principle p{font-size:14px;color:var(--text-muted);line-height:1.65;}

      .about-engine p{font-size:15.5px;line-height:1.7;color:var(--text-secondary);margin-bottom:14px;}
      .about-engine p:last-child{margin-bottom:0;}
      .about-engine-close{padding:18px 20px;border-radius:14px;background:var(--surface);
        border:1px solid var(--border);color:var(--text-muted);font-size:14.5px;margin-top:6px;}
      .about-engine-close b{color:var(--text-primary);}

      /* Who we are, with no address and no inventory of the stack. */
      .ident{display:grid;grid-template-columns:repeat(3,1fr);gap:0;max-width:940px;margin:0 auto;
        border:1px solid var(--border);border-radius:16px;overflow:hidden;background:var(--surface);}
      .ident > div{padding:22px 24px;border-right:1px solid var(--border);}
      .ident > div:last-child{border-right:none;}
      .ident b{display:block;font-family:var(--font-heading);font-size:15px;color:var(--text-primary);
        margin-bottom:5px;}
      .ident span{font-size:13.5px;color:var(--text-muted);line-height:1.6;}
      @media (max-width:760px){
        .ident{grid-template-columns:1fr;}
        .ident > div{border-right:none;border-bottom:1px solid var(--border);}
        .ident > div:last-child{border-bottom:none;}
      }

      .reach{max-width:940px;margin:18px auto 0;padding:28px;border-radius:16px;
        border:1px solid var(--border-strong);background:var(--bg-2);
        display:grid;grid-template-columns:1fr 1fr;gap:26px;align-items:center;}
      @media (max-width:760px){.reach{grid-template-columns:1fr;gap:18px;padding:24px;}}
      .reach h3{font-family:var(--font-heading);font-size:18px;color:var(--text-primary);margin-bottom:10px;}
      .reach-mail{font-family:var(--font-mono);font-size:16px;color:var(--accent);word-break:break-all;}
      .reach-mail:hover{text-decoration:underline;}
      .reach .small{display:block;font-size:13px;color:var(--text-dim);margin-top:8px;}
      .reach-note{font-size:13.5px;color:var(--text-muted);line-height:1.7;padding-left:20px;
        border-left:1px solid var(--border);}
      @media (max-width:760px){.reach-note{padding-left:0;border-left:none;padding-top:16px;
        border-top:1px solid var(--border);}}
      .reach-note b{color:var(--text-secondary);font-weight:600;}
    """
    contact = _public_contact_email()
    body = f"""
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">Why this exists</span>
    <h1 class="reveal reveal-delay-1">The work was never <span class="gradient-text">the problem.</span></h1>
    <p class="lead reveal reveal-delay-2" style="max-width:640px;margin:14px auto 0;">The eight tools
       around it were.</p>
  </div>
</section>

<section>
  <div class="container">
    <div class="why-body reveal">
      <p>Every solo operator runs the same scattered stack. Notes in one app. Invoices in another.
         Booking somewhere else. Content in a fourth. Goals in a spreadsheet, and a CRM nobody opens.
         Each one is good at its single job. <b>None of them know the others exist.</b></p>
      <p>So the operator becomes the integration layer. Copying a name from one tab into another.
         Remembering what was promised in an email while looking at a calendar that never heard about
         it. Reconciling a number by hand because two tools disagree. The friction between the tools
         quietly costs more hours than the work does.</p>
    </div>


    <figure class="stk reveal" aria-labelledby="stkCap">
      <div class="stk-half">
        <p class="stk-lbl">What you have now</p>
        <ul class="stk-grid">
          <li class="stk-t"><span class="n">Notes</span><span class="s">own login</span></li>
          <li class="stk-t"><span class="n">Invoices</span><span class="s">own bill</span></li>
          <li class="stk-t"><span class="n">Booking</span><span class="s">own login</span></li>
          <li class="stk-t"><span class="n">Content</span><span class="s">own bill</span></li>
          <li class="stk-t"><span class="n">Goals</span><span class="s">a spreadsheet</span></li>
          <li class="stk-t"><span class="n">CRM</span><span class="s">own bill</span></li>
          <li class="stk-t"><span class="n">Email</span><span class="s">own login</span></li>
          <li class="stk-t"><span class="n">Files</span><span class="s">own bill</span></li>
        </ul>
        <p class="stk-note">Eight bills, eight logins, and you in the middle carrying
           what none of them will tell each other.</p>
      </div>

      <div class="stk-turn" aria-hidden="true"><span></span></div>

      <div class="stk-half">
        <p class="stk-lbl">What this is</p>
        <div class="stk-one">
          <span class="n">One workspace</span>
          <span class="s">Notes, invoices, booking, content, goals, contacts, email and files &mdash;
             sharing what they know</span>
        </div>
        <p class="stk-note">One bill, one login, and nothing to carry between them.</p>
      </div>

      <figcaption id="stkCap" class="stk-cap">The hours are not in the work. They are in the gaps.</figcaption>
    </figure>

    <p class="why-pull reveal">The industry&rsquo;s answer has been enterprise software with the seats
       removed. That is not the same thing as software built for one person.</p>

    <div class="why-body reveal">
      <p>A system for one operator has to hold the whole business at once, because that is how the
         operator holds it. The invoice knows who the client is. The calendar knows what was sold.
         The follow-up knows what was said last time. That only works if it is <b>one system with one
         brain</b>, not eight subscriptions with an export button.</p>
      <p>That is the whole reason this exists: one workspace where the parts share what they know, and
         a chief of staff that reads the real thing (your contacts, your money, your week)
         instead of guessing at it.</p>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="stack-flow reveal">
      <div>
        <span class="stack-cap">What you have now</span>
        <div class="stack-eight" aria-hidden="true">
        <span>Notes</span><span>Invoices</span>
        <span>Booking</span><span>Content</span>
        <span>Goals</span><span>CRM</span>
        <span>Email</span><span>Files</span>
        </div>
      </div>
      <div class="stack-arrow" aria-hidden="true"></div>
      <div>
        <span class="stack-cap">What this is</span>
        <div class="stack-one">
        <b>One system</b>
        <em>Contacts, money, the calendar, content and goals in one place, plus
            a Chief that reads all of it every turn.</em>
        </div>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">How we build</span>
      <h2>Three principles we won&rsquo;t break.</h2>
    </div>
    <div class="principles">
      <div class="principle reveal">
        <div class="num">01</div>
        <h3>Real data, never invented metrics.</h3>
        <p>Every number in the workspace comes from your actual data. We never fake counts, never
           invent &ldquo;engagement scores&rdquo; without a source. If we don&rsquo;t have the data to
           back a metric, the metric doesn&rsquo;t ship.</p>
      </div>
      <div class="principle reveal reveal-delay-1">
        <div class="num">02</div>
        <h3>AI in service of judgment, not instead of it.</h3>
        <p>Chief drafts, suggests and assists. You approve. Anything that touches money, messages a
           client, or can&rsquo;t be taken back asks first, and every action is logged in plain
           language and reversible.</p>
      </div>
      <div class="principle reveal reveal-delay-2">
        <div class="num">03</div>
        <h3>One operator, one workspace.</h3>
        <p>We&rsquo;re not building enterprise software with the seats removed. Every decision
           optimises for one person running their whole business. If a feature only makes sense for a
           twenty-person team, we don&rsquo;t build it.</p>
      </div>
    </div>
  </div>
</section>

<section>
  <div class="container-narrow">
    <div class="section-head reveal" style="text-align:left;margin-bottom:22px;">
      <span class="eyebrow">The engine</span>
      <h2 style="margin-top:12px;">The AI world moves fast. <span class="gradient-text">You don&rsquo;t have to.</span></h2>
    </div>
    <div class="about-engine reveal">
      <p>Every few months someone announces a smarter model. For most businesses that&rsquo;s another
         thing to learn, another tool to evaluate, another migration nobody has time for.</p>
      <p>Here it&rsquo;s just a better engine dropped into the same car. Your workflows don&rsquo;t
         change. Your data doesn&rsquo;t move. You don&rsquo;t retrain. The system you opened this
         morning quietly got sharper overnight, and you find out because the work got easier, not
         because you got an email about it.</p>
      <p class="about-engine-close">We are not in the AI business. We&rsquo;re in the
         <b>how-your-business-actually-runs business.</b> The AI is just the engine, and engines are
         supposed to get better.</p>
    </div>
  </div>
</section>

<section>
  <div class="container">
    <div class="section-head reveal">
      <span class="eyebrow">The company</span>
      <h2>Who you&rsquo;re dealing with.</h2>
    </div>
    <div class="ident reveal">
      <div><b>{BUSINESS_NAME}</b><span>A real company with a real legal entity behind it,
        not a side project that disappears.</span></div>
      <div><b>One product</b><span>The Solutionist System. No spinouts, no pivots, no second bet
        that takes the attention.</span></div>
      <div><b>Open to sign up</b><span>You start it yourself, today, on a __TRIAL_FREE__ trial.
        No application to pass and nobody to wait on.</span></div>
    </div>

    <div class="reach reveal">
      <div>
        <h3>Reach a person</h3>
        <a class="reach-mail" href="mailto:{contact}">{contact}</a>
        <span class="small">Replies usually within a day.</span>
      </div>
      <p class="reach-note">Mail sent here lands in <b>the same inbox the system runs on</b>. We read
         it in Chief, next to everything else that needs an answer, just as you would.</p>
    </div>
  </div>
</section>

<section class="final-cta">
  <div class="container">
    <span class="eyebrow reveal">Want to talk?</span>
    <h2 style="margin-top:14px;" class="reveal reveal-delay-1">Start it yourself, or just say hi.</h2>
    <a class="btn-primary reveal reveal-delay-3" href="/start">Start your free trial &rarr;</a>
    <p class="reveal reveal-delay-3" style="margin-top:12px;font-size:13.5px;">Rather ask a question first?
      <a href="/get-started" style="color:var(--accent);">Tell us what you do &rarr;</a></p>
  </div>
</section>
"""
    return _render_shell(
        title="About",
        description=("Why the Solutionist System exists: one workspace for the person who runs the "
                     "whole business, instead of eight tools that never speak to each other."),
        content_html=body, path="/about", active="about", extra_css=extra_css,
    )


# ══════════════════════════════════════════════════════════════════════
# DOWNLOAD / GET THE APP, then GET STARTED — the intake form
# (the form POSTs to /api/leads via fetch)
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
        play_block = """<span class="dl-soon">Play Store, coming soon</span>"""
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
             the web app does today: same account, same data, same Chief.</p>"""
    content = f"""
<section class="hero" style="text-align:center;">
  <div class="container">
    <h1 class="reveal">Solutionist, wherever you work.</h1>
    <p class="reveal" style="color:var(--text-muted);max-width:560px;margin:18px auto 0;">
      One account, one system: phone, tablet, and desktop.
      The web app at <a href="{APP_URL}" style="color:var(--accent);">{APP_URL.replace("https://", "")}</a> works everywhere today.
    </p>

    <div class="dl-devices reveal" aria-hidden="true">
      <div class="dl-dev desk">
        <div class="dl-screen">
          <div class="app">
            <div class="app-top">
              <span class="at-mark"></span>
              <span class="at-search">Search or ask Chief<span class="kbd">&#8984;K</span></span>
              <span class="at-urgent">3 need you</span>
              <span class="at-cta">Quick Create</span>
              <span class="at-av"></span>
            </div>
            <div class="app-body">
              <div class="app-side">
                <div class="as-sec">Mission Control</div>
                <div class="as-item is-on"><span class="ic"></span>Dashboard</div>
                <div class="as-item"><span class="ic"></span>Needs you<span class="ct">3</span></div>
                <div class="as-sec">The chair</div>
                <div class="as-item"><span class="ic"></span>Regulars<span class="ct">124</span></div>
                <div class="as-item"><span class="ic"></span>Chair calendar</div>
                <div class="as-sec">Finance</div>
                <div class="as-item"><span class="ic"></span>Invoices</div>
                <div class="as-chief">Chief AI<span class="on">Online</span></div>
              </div>
              <div class="app-canvas">
                <div class="kpi-row">
                  <div class="kpi"><span class="k">Regulars</span><span class="v">124</span><span class="f">9 overdue for a cut</span></div>
                  <div class="kpi"><span class="k">Revenue</span><span class="v gold">$6,910</span><span class="f">+12% vs last mo</span></div>
                </div>
                <div class="brief">
                  <div class="brief-l">
                    <div class="date">Tuesday &middot; 8:04 AM</div>
                    <div class="hi">Good morning, <b>Andre</b></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="dl-dev tab">
        <div class="dl-screen">
          <div class="app">
            <div class="app-top">
              <span class="at-mark"></span>
              <span class="at-search">Ask Chief</span>
              <span class="at-av"></span>
            </div>
            <div class="app-body">
              <div class="app-canvas">
                <div class="brief">
                  <div class="brief-l">
                    <div class="date">Morning edition</div>
                    <div class="hi">Good morning, <b>Andre</b></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div class="dl-dev phone">
        <div class="dl-screen">
          <div class="app">
            <div class="app-body">
              <div class="app-canvas">
                <div class="brief">
                  <div class="brief-l">
                    <div class="date">Tuesday</div>
                    <div class="hi">Good morning, <b>Andre</b></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    <p class="dl-caption">The same account on every screen. Nothing syncs, because nothing is separate.</p>
  </div>
</section>
<section>
  <div class="container">
    <p class="dl-eyebrow" id="dlHere">Pick your platform</p>
    <div class="dl-grid">
      <div class="company-card reveal" data-plat="android">
        <h3>Android</h3>
        {android_block}
      </div>
      <div class="company-card reveal reveal-delay-1" data-plat="ios">
        <h3>iPhone &amp; iPad</h3>
        <p class="dl-note">Installs as an app straight from Safari. No App Store needed.</p>
        <details class="dl-steps" open>
          <summary>Install steps</summary>
          <ol>
            <li>Open <strong>{APP_URL.replace("https://", "")}</strong> in Safari.</li>
            <li>Tap the Share button, then <strong>Add to Home Screen</strong>.</li>
            <li>Tap Add. Solutionist appears on your home screen.</li>
          </ol>
        </details>
      </div>
      <div class="company-card reveal reveal-delay-2" data-plat="desktop">
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
        extra_css=REPLICA_KIT_CSS + """
  /* ── the three screens ─────────────────────────────────────────────
     A download page with no picture of the app was asking people to
     take the product on faith. These are the replica kit at three
     sizes: each frame carries only as much markup as it can hold
     legibly, so the phone shows the briefing and nothing else rather
     than a desktop layout shrunk past reading. */
  .dl-devices{display:flex;align-items:flex-end;justify-content:center;gap:22px;
    margin:56px auto 0;max-width:940px;}
  .dl-dev{position:relative;border-radius:14px;background:var(--bg-2);
    border:1px solid var(--border-strong);padding:7px;flex:0 0 auto;
    box-shadow:0 30px 70px -34px rgba(0,0,0,.9);}
  .dl-dev .dl-screen{border-radius:8px;overflow:hidden;background:#0F1218;height:100%;}
  .dl-dev .app{height:100%;width:100%;}
  .dl-dev.desk{flex:1 1 auto;max-width:600px;height:340px;border-radius:16px;}
  .dl-dev.tab{width:246px;height:292px;}
  .dl-dev.phone{width:158px;height:252px;border-radius:22px;padding:5px;}
  .dl-dev.phone .dl-screen{border-radius:17px;}
  /* No font-size override here. Bumping the type inside a 210px frame
     was what truncated the KPI labels to single letters; the fix was to
     give each frame less to hold, not smaller words. */
  /* The kit's .kpi-row is a fixed 5-column grid, so two tiles were
     being held to two fifths of the width and clipping their own
     figures. In these frames the row carries exactly what is in it. */
  .dl-dev .kpi-row{grid-template-columns:repeat(2,1fr);}
  .dl-caption{text-align:center;color:var(--text-muted);font-size:13.5px;margin-top:22px;}
  @media (max-width: 880px){
    .dl-devices{flex-wrap:wrap;gap:16px;}
    .dl-dev.desk{max-width:100%;flex:1 1 100%;height:260px;}
    .dl-dev.tab{width:200px;height:236px;}
    .dl-dev.phone{width:140px;height:224px;}
  }
  @media (max-width: 560px){
    .dl-dev.tab{display:none;}
    .dl-dev.desk{height:210px;}
  }

  .dl-eyebrow{text-align:center;font-size:11px;font-weight:700;letter-spacing:2px;
    text-transform:uppercase;color:var(--text-muted);margin:0 0 24px;}

  /* the card for the device you are actually holding */
  .company-card[data-plat].is-yours{border-color:color-mix(in srgb, var(--accent) 52%, transparent);
    background:color-mix(in srgb, var(--accent) 7%, var(--surface));
    box-shadow:0 18px 46px -26px color-mix(in srgb, var(--accent) 70%, transparent);}
  .company-card[data-plat].is-yours::before{content:'You are on this';position:absolute;
    top:-10px;left:22px;font-size:10px;font-weight:700;letter-spacing:1.4px;
    text-transform:uppercase;color:var(--ink-on-accent);background:var(--accent);
    border-radius:99px;padding:3px 11px;}
  .company-card[data-plat]{position:relative;}

  .dl-soon{display:inline-block;margin-top:4px;padding:6px 16px;border:1px solid var(--border-strong);border-radius:99px;font-size:12px;font-weight:700;letter-spacing:2px;text-transform:uppercase;color:var(--text-muted);}
  .dl-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-top:8px;}
  @media (max-width: 880px){.dl-grid{grid-template-columns:1fr;}}
  .dl-grid .company-card h3{margin-bottom:12px;}
  .dl-note{color:var(--text-secondary);font-size:13.5px;line-height:1.55;margin:8px 0 0;}
  .dl-steps{margin-top:14px;text-align:left;}
  .dl-steps summary{cursor:pointer;font-size:13px;font-weight:700;color:var(--text-muted);letter-spacing:0.4px;}
  .dl-steps ol{margin:10px 0 0;padding-left:20px;color:var(--text-secondary);font-size:13.5px;line-height:1.6;display:flex;flex-direction:column;gap:6px;}
""",
        extra_scripts="""
<script>
  /* Lift the card for the device you are holding. Read-only feature
     sniffing on the UA string: it decides which of three cards gets a
     highlight and nothing else, so a wrong guess costs a visitor
     nothing and every card stays visible and usable either way. */
  (function(){
    var ua = navigator.userAgent || '';
    var plat;
    if (/Android/i.test(ua))                                  plat = 'android';
    else if (/iPhone|iPad|iPod/i.test(ua))                    plat = 'ios';
    else if (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1) plat = 'ios';
    else if (/Windows|Macintosh|Linux|CrOS/i.test(ua))        plat = 'desktop';
    if (!plat) return;
    var card = document.querySelector('.company-card[data-plat="' + plat + '"]');
    if (!card) return;
    card.classList.add('is-yours');
    var grid = card.parentNode;
    if (grid && grid.firstChild !== card) grid.insertBefore(card, grid.firstChild);
    var label = document.getElementById('dlHere');
    if (label) label.textContent = 'Pick your platform \u2014 yours is first';
  })();
</script>
""",
    )


GS_SWITCHER_SCRIPT = """
<script>
""" + TRADES_JS + """
(function () {
  var chips = document.getElementById('gsChips');
  var card  = document.getElementById('gsCard');
  if (!chips || !card || typeof TRADES === 'undefined') return;

  var nav  = document.getElementById('gsNav');
  var kpis = document.getElementById('gsKpis');
  var biz  = document.getElementById('gsBiz');
  var room = document.getElementById('gsRoom');
  var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function cap(s){ return s.charAt(0).toUpperCase() + s.slice(1); }

  function paint(t) {
    biz.innerHTML  = t.biz;
    room.innerHTML = t.grp;
    nav.innerHTML  = t.nav.map(function (n) { return '<span>' + n + '</span>'; }).join('');
    kpis.innerHTML = t.kpi.slice(0, 4).map(function (k, i) {
      return '<div class="gs-pv-kpi"><span class="k">' + k[0] + '</span>' +
             '<span class="v' + (i === 2 ? ' gold' : '') + '">' + k[1] + '</span></div>';
    }).join('');
  }

  function select(i) {
    var btns = chips.querySelectorAll('.gs-chip');
    for (var j = 0; j < btns.length; j++) {
      btns[j].setAttribute('aria-pressed', String(j === i));
    }
    if (reduced) { paint(TRADES[i]); return; }
    card.classList.add('is-swapping');
    window.setTimeout(function () {
      paint(TRADES[i]);
      card.classList.remove('is-swapping');
    }, 170);
  }

  chips.innerHTML = TRADES.map(function (t, i) {
    return '<button type="button" class="gs-chip" data-i="' + i + '" aria-pressed="' +
           (i === 0 ? 'true' : 'false') + '">' + cap(t.word) + '</button>';
  }).join('');

  chips.addEventListener('click', function (e) {
    var b = e.target.closest('.gs-chip');
    if (b) select(parseInt(b.getAttribute('data-i'), 10));
  });

  paint(TRADES[0]);
})();
</script>
"""

def render_get_started() -> str:
    extra_css = """

      /* ── the workspace you would be handed ────────────────────────────
         This page asked someone to describe their business and gave
         nothing back until they submitted. The trade switcher already
         existed on the home fold; it reads the same TRADES_JS here and
         answers the form's first question before it is asked. */
      .gs-preview{margin-top:40px;}
      .gs-pv-eyebrow{font-size:11px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;
        color:var(--text-muted);margin:0 0 14px;}
      .gs-chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:18px;}
      .gs-chip{font:inherit;font-size:13.5px;font-weight:500;cursor:pointer;padding:7px 15px;
        border-radius:99px;border:1px solid var(--border);background:transparent;
        color:var(--text-secondary);transition:color .16s, background .16s, border-color .16s;}
      .gs-chip:hover{color:var(--text-primary);border-color:var(--border-strong);}
      .gs-chip[aria-pressed="true"]{background:color-mix(in srgb, var(--accent) 16%, transparent);
        border-color:color-mix(in srgb, var(--accent) 44%, transparent);color:var(--accent);font-weight:600;}
      .gs-chip:focus-visible{outline:2px solid var(--accent);outline-offset:2px;}
      .gs-pv-card{border:1px solid var(--border);border-radius:16px;background:var(--surface);
        padding:20px 22px;transition:opacity .2s ease;}
      .gs-pv-card.is-swapping{opacity:.3;}
      .gs-pv-top{display:flex;align-items:baseline;justify-content:space-between;gap:12px;
        padding-bottom:12px;border-bottom:1px solid var(--border);}
      .gs-pv-biz{font-family:var(--font-heading);font-size:17px;font-weight:700;
        letter-spacing:-.02em;color:var(--text-primary);}
      .gs-pv-room{font-size:11px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;
        color:var(--accent);}
      .gs-pv-nav{display:flex;flex-wrap:wrap;gap:7px;padding:14px 0;}
      .gs-pv-nav span{font-size:12.5px;color:var(--text-secondary);border:1px solid var(--border);
        border-radius:7px;padding:5px 10px;background:var(--bg-2);}
      .gs-pv-kpis{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;}
      .gs-pv-kpi{border:1px solid var(--border);border-radius:10px;padding:10px 12px;background:var(--bg-2);}
      .gs-pv-kpi .k{display:block;font-size:9.5px;font-weight:700;letter-spacing:.11em;
        text-transform:uppercase;color:var(--text-dim);line-height:1.3;}
      .gs-pv-kpi .v{display:block;font-family:var(--font-heading);font-size:21px;font-weight:700;
        letter-spacing:-.02em;margin-top:3px;font-variant-numeric:tabular-nums;}
      .gs-pv-kpi .v.gold{color:var(--amber);}
      .gs-pv-foot{margin:14px 0 0;font-size:12.5px;color:var(--text-dim);line-height:1.5;}
      /* The preview used to be the end of the thought. It is now the
         start of one: you looked at your own workspace, so the button
         that opens it belongs directly under it. */
      .gs-pv-start{display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin:18px 0 0;}
      .gs-pv-start span{font-size:12.5px;color:var(--text-dim);}
      .form-intro{margin:0 0 20px;padding-bottom:16px;border-bottom:1px solid var(--border);
        font-size:13.5px;line-height:1.55;color:var(--text-secondary);}
      @media (max-width: 520px){.gs-pv-kpis{grid-template-columns:1fr;}}
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
        honeypot:    form.website.value,  // honeypot field
        // which door they walked in through — the shell stashed the
        // session's campaign params; the server whitelists them again
        attribution: (function () {
          try {
            var a = JSON.parse(sessionStorage.getItem('_sol_attr') || 'null');
            return (a && Object.keys(a).length) ? a : null;
          } catch (e) { return null; }
        })()
      };
      try {
        try { window.dispatchEvent(new Event('solutionist:applied')); } catch (e) {}
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
        msg.textContent = "Got it — we'll reply within 24 hours. You don't have to wait on us to start, though: the trial is open right now.";
        form.reset();
        btn.textContent = 'Sent ✓';
      } catch (err) {
        msg.classList.add('err');
        msg.textContent = 'Something went wrong — please email __CONTACT_EMAIL__ directly.';
        btn.disabled = false;
        btn.textContent = 'Send it →';
      }
    });
  })();
</script>
"""
    body = """
<section class="page-hero">
  <span class="orb orb-1" aria-hidden></span>
  <div class="container">
    <span class="eyebrow reveal">__TRIAL_FREE__ &middot; no application, no waiting list</span>
    <h1 class="reveal reveal-delay-1">Start it yourself in about <span class="gradient-text">two minutes.</span></h1>
    <p class="lead reveal reveal-delay-2" style="max-width:640px;margin:14px auto 0;">Create your account, name your business, and the whole workspace arrives already speaking your trade. Pick yours below and see exactly what you would be handed.</p>
    <p class="reveal reveal-delay-3" style="margin-top:22px;">
      <a class="btn-primary" href="/start">Start your free trial &rarr;</a>
    </p>
  </div>
</section>

<section>
  <div class="container">
    <div class="gs-preview reveal">
      <p class="gs-pv-eyebrow">Pick your trade &mdash; this is the workspace you would be handed</p>
      <div class="gs-chips" id="gsChips" role="group" aria-label="Business type"></div>
      <div class="gs-pv-card" id="gsCard">
        <div class="gs-pv-top">
          <span class="gs-pv-biz" id="gsBiz">Fade &amp; Co.</span>
          <span class="gs-pv-room" id="gsRoom">The chair</span>
        </div>
        <div class="gs-pv-nav" id="gsNav"></div>
        <div class="gs-pv-kpis" id="gsKpis"></div>
        <p class="gs-pv-foot">Every one of those names is the vocabulary the system ships with.
           Nothing here is set up by you.</p>
      </div>
      <p class="gs-pv-start"><a class="btn-primary" href="/start">Start with this workspace &rarr;</a>
        <span>__TRIAL_FREE__ &middot; cancel yourself any time</span></p>
    </div>
    <div class="gs-grid">
      <form id="lead-form" class="form-card reveal">
        <p class="form-intro">Rather ask a person first? This reaches the team directly &mdash;
          and it is not a gate: the trial above is open either way.</p>
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
            <option value="">Pick what fits best</option>
            <option value="pastor">Pastor</option>
            <option value="ministry_leader">Ministry Leader</option>
            <option value="coach">Coach</option>
            <option value="consultant">Consultant</option>
            <option value="creative">Creative</option>
            <option value="practitioner">Service Provider</option>
            <option value="solo_studio">Solo Studio</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div class="form-row">
          <label>Tell us a bit about your business <span class="req">*</span></label>
          <textarea name="what_you_do" required placeholder="Who do you serve? What's the work look like? What's your biggest tooling headache today?"></textarea>
        </div>
        <div class="form-row">
          <label>How did you hear about us?</label>
          <input type="text" name="source" autocomplete="off" placeholder="Optional: Twitter, friend referral, search, etc.">
        </div>
        <div class="honeypot" aria-hidden>
          <label>Website</label>
          <input type="text" name="website" tabindex="-1" autocomplete="off">
        </div>
        <button type="submit" id="submit-btn" class="btn-primary form-submit">Send it →</button>
        <div id="form-msg" class="form-msg" role="status" aria-live="polite"></div>
      </form>

      <aside class="next-steps reveal reveal-delay-1">
        <h3>If you start it yourself</h3>
        <ul class="next-list">
          <li>
            <span class="num">1</span>
            <span class="text"><strong>Create your account.</strong> Email and a password. Nothing to approve, nobody to wait on.</span>
          </li>
          <li>
            <span class="num">2</span>
            <span class="text"><strong>Name your business and say what you do.</strong> The rooms, the vocabulary and Chief's first questions are all built from that answer.</span>
          </li>
          <li>
            <span class="num">3</span>
            <span class="text"><strong>Pick a plan.</strong> Starter, Professional or Solutionist &mdash; __TRIAL_FREE__ on any of them, and the card is not charged until the trial ends.</span>
          </li>
          <li>
            <span class="num">4</span>
            <span class="text"><strong>Change your mind whenever.</strong> Switch tier or cancel yourself from inside the app. Your data stays exportable either way.</span>
          </li>
        </ul>
      </aside>
    </div>
  </div>
</section>
"""
    return _render_shell(
        title="Get Started",
        description="Start your free trial of the Solutionist System, or ask us a question first. Self-serve: no application and no waiting list.",
        content_html=body, path="/get-started", active="get_started",
        extra_css=extra_css, extra_scripts=extra_scripts + GS_SWITCHER_SCRIPT,
    )


# ══════════════════════════════════════════════════════════════════════
# NEWS — the platform's own feed, on the platform's own domain
# ══════════════════════════════════════════════════════════════════════
#
# site_news.py already renders a news feed for a PRACTITIONER's site, in
# that practitioner's shell. This is the same data shape rendered in the
# marketing shell instead, because the two live at different addresses
# and only one of them is the domain every CTA on this site points at.
#
# Publishing to `the-solutionist-system.mysolutionist.app/news` would put
# the company's own launch writing on a bare subdomain with no inbound
# links, while the apex holds whatever authority the site has earned.
# Same renderer, wrong address — so the renderer is what gets reused and
# the shell is what changes.
#
# Storage is the platform business's settings.website_content.news — the
# same field the practitioner feed reads, on the row that already stands
# for the platform itself (settings.platform_books). Deliberately NOT a
# business_sites row: pointing one's custom_domain at mysolutionist.app
# would hand the apex to the practitioner site-server and take the
# marketing site down.

NEWS_CSS = """
      .nw-wrap{max-width:760px;margin:0 auto;padding:0 24px;}
      .nw-list{list-style:none;margin:44px 0 0;padding:0;
        border-top:1px solid var(--border);}
      .nw-item{padding:30px 0;border-bottom:1px solid var(--border);}
      .nw-date{font-size:11px;font-weight:700;letter-spacing:1.6px;text-transform:uppercase;
        color:var(--text-dim);margin:0 0 10px;}
      .nw-item h2{font-family:var(--font-heading);font-size:23px;line-height:1.3;margin:0 0 10px;
        letter-spacing:-0.01em;}
      .nw-item h2 a{transition:color .15s;}
      .nw-item h2 a:hover{color:var(--accent);}
      .nw-sum{color:var(--text-secondary);font-size:15px;margin:0;}
      .nw-post h1{font-family:var(--font-heading);font-size:34px;line-height:1.2;
        letter-spacing:-0.02em;margin:14px 0 18px;}
      .nw-body{color:var(--text-secondary);font-size:16.5px;line-height:1.75;
        margin-top:26px;}
      .nw-body p{margin:0 0 20px;}
      .nw-img{border-radius:12px;border:1px solid var(--border);margin:26px 0 0;}
      .nw-back{display:inline-block;margin-top:38px;font-size:13.5px;color:var(--text-muted);
        transition:color .15s;}
      .nw-back:hover{color:var(--accent);}
      .nw-cta{margin:56px 0 0;padding:28px;border-radius:14px;border:1px solid var(--border);
        background:var(--surface);text-align:center;}
      .nw-cta p{color:var(--text-secondary);font-size:15px;margin:0 0 16px;}
      @media (max-width:640px){
        .nw-post h1{font-size:27px;}
        .nw-item h2{font-size:20px;}
        .nw-body{font-size:16px;}
        .nw-wrap{padding:0 18px;}
      }
"""

_NEWS_CTA = """
      <div class="nw-cta">
        <p>The Solutionist System runs the whole business from one place &mdash;
           bookings, clients, invoices, and a chief of staff that never acts
           without your approval.</p>
        <a class="btn-primary" href="/start">Start your free trial &rarr;</a>
      </div>
"""


def render_news_index(posts: List[Dict[str, Any]]) -> str:
    """The archive.

    Empty is a real state and it renders, because the footer links here
    from every page and a link that 404s is a dead end. It carries
    `noindex` instead: the reason the empty archive used to 404 was to
    keep a thin page out of search, and noindex says that directly
    rather than by withholding the page from people too. The sitemap
    still omits /news until a post exists.
    """
    if not posts:
        body = """
    <section class="section">
      <div class="nw-wrap">
        <div class="page-hero">
          <span class="eyebrow">News</span>
          <h1>Nothing here yet</h1>
        </div>
        <p class="nw-sum" style="text-align:center;">
          Product news will show up here as it ships.
        </p>
      </div>
    </section>
    """
        return _render_shell(
            title="News",
            description="Product news from the Solutionist System.",
            content_html=body, path="/news", extra_css=NEWS_CSS,
            head_extra='<meta name="robots" content="noindex">',
        )

    items = []
    for post in posts:
        date_html = ""
        when = site_news.display_date(post.get("published_at"))
        if when:
            date_html = f'<p class="nw-date">{_html.escape(when)}</p>'
        items.append(
            '<li class="nw-item">'
            f'{date_html}'
            f'<h2><a href="/news/{_html.escape(post["slug"])}">'
            f'{_html.escape(post["title"])}</a></h2>'
            f'<p class="nw-sum">{_html.escape(site_news.summarize(post["body"]))}</p>'
            '</li>'
        )

    body = f"""
    <section class="section">
      <div class="nw-wrap">
        <div class="page-hero">
          <span class="eyebrow">News</span>
          <h1>What we shipped, and why</h1>
        </div>
        <ul class="nw-list">{''.join(items)}</ul>
      </div>
    </section>
    """
    return _render_shell(
        title="News",
        description="Product news from the Solutionist System — what shipped, what changed, and what it means for the people running a business on it.",
        content_html=body, path="/news", extra_css=NEWS_CSS,
    )


def render_news_post(post: Dict[str, Any]) -> str:
    """One post at its own address. The stable URL is the whole point:
    it keeps earning long after a social post has scrolled away."""
    url = f"https://mysolutionist.app/news/{post['slug']}"
    when = site_news.display_date(post.get("published_at"))
    date_html = f'<p class="nw-date">{_html.escape(when)}</p>' if when else ""

    image_html = ""
    if post.get("image_url"):
        image_html = (f'<img class="nw-img" src="{_html.escape(post["image_url"])}" '
                      f'alt="" loading="lazy" />')

    schema = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": post["title"][:110],
        "description": site_news.summarize(post["body"]),
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "url": url,
        "publisher": {"@type": "Organization", "name": SITE_NAME,
                      "url": "https://mysolutionist.app"},
        "author": {"@type": "Organization", "name": SITE_NAME},
    }
    if post.get("published_at"):
        schema["datePublished"] = post["published_at"].isoformat()
    if post.get("image_url"):
        schema["image"] = post["image_url"]
    # json.dumps escapes nothing HTML-significant except via ensure_ascii;
    # close the one sequence that could break out of the script element.
    schema_json = json.dumps(schema).replace("<", "\\u003c")
    head_extra = f'<script type="application/ld+json">{schema_json}</script>'

    body = f"""
    <section class="section">
      <div class="nw-wrap nw-post">
        {date_html}
        <h1>{_html.escape(post['title'])}</h1>
        {image_html}
        <div class="nw-body">{site_news.paragraphs(post['body'])}</div>
        {_NEWS_CTA}
        <a class="nw-back" href="/news">&larr; All news</a>
      </div>
    </section>
    """
    return _render_shell(
        title=post["title"],
        description=site_news.summarize(post["body"]),
        content_html=body, path=f"/news/{post['slug']}", extra_css=NEWS_CSS,
        head_extra=head_extra,
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
    # Session campaign params the shell stashed (utm_*, gclid, fbclid,
    # ref, referrer, landing_path). Whitelisted server-side — a lie here
    # can only misattribute one marketing row.
    attribution: Optional[Dict[str, Any]] = None


async def handle_lead_intake(req: LeadIntakeRequest,
                             request: Any = None,
                             background_tasks: Any = None) -> Dict[str, Any]:
    """Validate + persist + notify. Honeypot returns success silently
    so bots don't learn they were rejected. `request` (the Starlette
    request, when the route passes it) supplies the Referer header —
    lead_attribution reads campaign params + landing page off it."""
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

    # Which door they walked in through: campaign params off the Referer
    # + whatever the shell stashed client-side, whitelisted + clipped.
    import lead_attribution
    attribution = lead_attribution.capture(
        request, {"attribution": req.attribution}) or None

    # 1. Insert into Supabase
    supabase_url = os.environ.get("SUPABASE_URL", "")
    supabase_key = os.environ.get("SUPABASE_ANON", "")
    inserted_id = None
    if supabase_url and supabase_key:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
            try:
                row = {
                    "name": name, "email": email, "role": role,
                    "what_you_do": what_you_do, "source": source,
                    "status": "new",
                }
                if attribution:
                    row["attribution"] = attribution
                r = await client.post(
                    f"{supabase_url}/rest/v1/marketing_leads",
                    headers={
                        "apikey": supabase_key,
                        "Authorization": f"Bearer {supabase_key}",
                        "Content-Type": "application/json",
                        "Prefer": "return=representation",
                    },
                    content=json.dumps(row),
                )
                if r.status_code >= 400 and attribution:
                    # attribution column not migrated yet — the lead
                    # itself must never be lost to a marketing field.
                    logger.warning(f"insert with attribution failed "
                                   f"{r.status_code} — retrying without")
                    row.pop("attribution", None)
                    r = await client.post(
                        f"{supabase_url}/rest/v1/marketing_leads",
                        headers={
                            "apikey": supabase_key,
                            "Authorization": f"Bearer {supabase_key}",
                            "Content-Type": "application/json",
                            "Prefer": "return=representation",
                        },
                        content=json.dumps(row),
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
        _attr = attribution or {}
        channel = (" / ".join(x for x in (_attr.get("utm_source"),
                                          _attr.get("utm_medium"),
                                          _attr.get("utm_campaign")) if x)
                   or _attr.get("referrer_host") or "direct / untagged")
        owner_subject = f"New lead: {name} ({role or 'no role'})"
        owner_body = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;color:#222;padding:20px;max-width:600px;margin:0 auto;background:#fff;">
<h2 style="color:#1D63E6;margin-bottom:18px;">Someone wants to talk</h2>
<table style="width:100%;border-collapse:collapse;font-size:14px;">
<tr><td style="padding:8px 0;color:#666;width:140px;">Name</td><td style="padding:8px 0;font-weight:600;">{_html.escape(name)}</td></tr>
<tr><td style="padding:8px 0;color:#666;">Email</td><td style="padding:8px 0;font-weight:600;"><a href="mailto:{_html.escape(email)}">{_html.escape(email)}</a></td></tr>
<tr><td style="padding:8px 0;color:#666;">Role</td><td style="padding:8px 0;">{_html.escape(role or '(not specified)')}</td></tr>
<tr><td style="padding:8px 0;color:#666;">Source</td><td style="padding:8px 0;">{_html.escape(source or '(not specified)')}</td></tr>
<tr><td style="padding:8px 0;color:#666;">Channel</td><td style="padding:8px 0;">{_html.escape(channel)}</td></tr>
</table>
<div style="margin-top:18px;padding:14px;background:#f5f5f7;border-radius:8px;font-size:13px;line-height:1.6;">
<strong style="display:block;margin-bottom:6px;color:#444;">About their business:</strong>
{_html.escape(what_you_do or '(empty)').replace(chr(10), '<br>')}
</div>
<p style="margin-top:18px;font-size:11px;color:#999;">Lead ID: {inserted_id or '(persist failed)'}</p>
</body></html>"""
        try:
            await send_via_resend(
                to_email=_operator_email(), to_name=None,
                from_email=from_email, from_name="Solutionist Site",
                subject=owner_subject, body=owner_body, reply_to=email,
            )
        except Exception as e:
            logger.warning(f"owner email failed: {e}")

        # Lead confirmation
        lead_subject = "Got your note — and the trial is open whenever you are"
        lead_body = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;color:#222;padding:20px;max-width:600px;margin:0 auto;background:#fff;line-height:1.65;">
<h2 style="color:#1D63E6;margin-bottom:14px;">Thanks for writing, {_html.escape(name.split()[0])}.</h2>
<p style="font-size:15px;color:#333;">We got your note about the Solutionist System, and someone from the team will reply within 24 hours &mdash; usually faster.</p>
<p style="font-size:15px;color:#333;">One thing worth saying now: <strong>you don't have to wait on us to start.</strong> The system is self-serve, every plan opens with a {_trial_days()}-day free trial, and your workspace is built around your trade the moment you name it.</p>
<p style="text-align:center;margin:26px 0;"><a href="https://mysolutionist.app/start" style="display:inline-block;background:#1D63E6;color:#fff;text-decoration:none;padding:13px 26px;border-radius:8px;font-weight:600;font-size:15px;">Start your free trial &rarr;</a></p>
<p style="font-size:14px;color:#666;margin-top:18px;">Either way, just reply to this email &mdash; it comes straight to the team.</p>
<p style="margin-top:24px;font-size:14px;color:#444;">Talk soon,<br><strong>The Solutionist Team</strong><br>The Solutionist System LLC</p>
</body></html>"""
        try:
            await send_via_resend(
                to_email=email, to_name=name,
                from_email=from_email, from_name="The Solutionist Team",
                subject=lead_subject, body=lead_body, reply_to=_public_contact_email(),
            )
        except Exception as e:
            logger.warning(f"lead confirmation email failed: {e}")
    except Exception as e:
        logger.warning(f"resend import/send failed: {e}")

    # 3. Growth arc Rung 2 — tell Meta a Lead happened, AFTER the
    # response (BackgroundTasks), so ad delivery optimizes toward people
    # who apply rather than people who click. No-op unless META_PIXEL_ID
    # + META_CAPI_ACCESS_TOKEN are configured. The honeypot returned
    # early above, so anything reaching here is a human.
    try:
        import meta_capi
        if background_tasks is not None and meta_capi.configured():
            ctx = meta_capi.request_context(request)
            background_tasks.add_task(
                meta_capi.send_event, "Lead",
                email=email,
                event_id=str(inserted_id) if inserted_id else None,
                event_source_url="https://mysolutionist.app/get-started",
                **ctx)
    except Exception as e:
        logger.warning(f"capi lead schedule failed: {e}")

    logger.info(f"new lead persisted id={inserted_id} from {email}")
    return {"ok": True, "id": inserted_id}
