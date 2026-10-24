# churchsavvy_site.py — ChurchSavvy's own website (churchsavvy.app): the home
# page, pricing, and how it works with Solutionist. Design canvas
# UZu4VsoY9KemkUGorz234j, boards 2-4 and 17; Kevin 2026-10-24: "I think the
# website could be more top notch. when you start building that see how you
# can improve it even more in design."
#
# ChurchSavvy is its own product, partnered with Solutionist, so it has its
# own front door, rendered here like mysolutionist.app (marketing_pages.py):
# plain HTML and one stylesheet, fast on a phone, readable by search
# engines, no framework.
#
#   churchsavvy.app (and www.)   /  /pricing  /solutionist  /robots.txt  /sitemap.xml
#   mysolutionist.app            /churchsavvy/site[/pricing|/solutionist]   the same pages, before the domain
#   any host                     /churchsavvy-assets/<file>                  logo, icon, share picture
#
# Rules it keeps: the logo's blue-to-violet only on the logo and the
# wordmark's word "ready."; flat color everywhere else; no invented numbers,
# reviews or customers; Scripture is KJV; never a song's words.
from __future__ import annotations

import html as _html
import os
import pathlib
import re
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

router = APIRouter(tags=["churchsavvy-site"])

HOSTS = ("churchsavvy.app", "www.churchsavvy.app")
CANONICAL = "https://churchsavvy.app"
PREVIEW_BASE = "/churchsavvy/site"
_ASSETS = pathlib.Path(__file__).resolve().parent / "static" / "churchsavvy"
_ASSET_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}\.(webp|png)$")
_CACHE = {"Cache-Control": "public, max-age=604800, immutable"}
_PAGE_CACHE = {"Cache-Control": "public, max-age=300, s-maxage=600"}


def is_host(host: str) -> bool:
    return (host or "").split(":")[0].strip().lower() in HOSTS


def app_url() -> str:
    """Where Start and Sign in go: ChurchSavvy's app (its own address once
    it has one, CHURCHSAVVY_SIGNIN_URL), else the app's /churchsavvy."""
    import app_base
    return ((os.environ.get("CHURCHSAVVY_SIGNIN_URL") or "").strip().rstrip("/")
            or f"{app_base.app_base_url()}/churchsavvy")


def _e(s: str) -> str:
    return _html.escape(s, quote=True)


# ─── icons (Lucide paths, drawn inline) ──────────────────────────────

_ICONS = {
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>',
    "mic": '<path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2M12 19v3"/>',
    "radio": '<circle cx="12" cy="12" r="2"/><path d="M16.24 7.76a6 6 0 0 1 0 8.49M7.76 16.24a6 6 0 0 1 0-8.49M19.07 4.93a10 10 0 0 1 0 14.14M4.93 19.07a10 10 0 0 1 0-14.14"/>',
    "door": '<path d="M3 21h18M5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16"/><path d="M14 12h.01"/>',
    "mail": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="m22 7-10 6L2 7"/>',
    "music": '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M9 13h6M9 17h6"/>',
    "camera": '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3z"/><circle cx="12" cy="13" r="3"/>',
    "clipboard": '<rect x="8" y="2" width="8" height="4" rx="1"/><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2"/>',
    "plug": '<path d="M12 22v-5M9 8V2M15 8V2M18 8v5a4 4 0 0 1-4 4h-4a4 4 0 0 1-4-4V8z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "book": '<path d="M2 4h7a3 3 0 0 1 3 3v14a2 2 0 0 0-2-2H2zM22 4h-7a3 3 0 0 0-3 3v14a2 2 0 0 1 2-2h8z"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "bell": '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
    "card": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 10h20"/>',
    "arrow": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "play": '<path d="M6 4v16l14-8z"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>',
    "swap": '<path d="M7 16V4M3 8l4-4 4 4M17 8v12M21 16l-4 4-4-4"/>',
    "heart": '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 0 0 0-7.8z"/>',
}


def icon(name: str, cls: str = "ic") -> str:
    return (f'<svg class="{cls}" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
            f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{_ICONS[name]}</svg>')


# ─── the stylesheet ──────────────────────────────────────────────────

CSS = """
:root{--ink:#0A1033;--ink2:#3D4468;--ink3:#5E6488;--paper:#fff;--ground:#F5F6FB;--tint:#EEF1FE;--line:#E1E4F0;--line2:#CDD2E6;
--blue:#1D45F2;--blue-hi:#163AD6;--blue-soft:#E6ECFF;--violet:#6A14E8;--ok:#11845B;--ok-soft:#E3F5EC;--wait:#A15C07;--wait-soft:#FBF0DD;
--grad:linear-gradient(95deg,#0A47FF 0%,#4B2BF3 55%,#7A0FEA 100%);
--d-bg:#0B0C12;--d-panel:#13141C;--d-raise:#1B1C27;--d-raise2:#232533;--d-line:#262838;--d-line2:#33364A;--d-text:#EEF0F8;--d-dim:#A5A9C0;--d-faint:#7A7F9B;--d-blue:#6D8BFF;--d-live:#E5484D;--d-ok:#3FCF8E;
--display:'Manrope',system-ui,sans-serif;--text:'Inter',system-ui,sans-serif;--r:14px;--r-lg:20px;--r-xl:28px;--wrap:1200px}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%;scroll-behavior:smooth}
body{margin:0;font-family:var(--text);color:var(--ink);background:var(--paper);line-height:1.55;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:inherit;text-decoration:none}img{max-width:100%;display:block}h1,h2,h3,h4,p{margin:0}button{font:inherit;color:inherit;background:none;border:0;padding:0;cursor:pointer}
:focus-visible{outline:3px solid var(--blue);outline-offset:3px;border-radius:6px}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.skip{position:absolute;left:16px;top:-60px;z-index:100;background:var(--ink);color:#fff;padding:10px 16px;border-radius:10px}.skip:focus{top:12px}
.wrap{max-width:var(--wrap);margin:0 auto;padding:0 32px}
.ic{width:20px;height:20px;flex:none}.ic-s{width:16px;height:16px;flex:none}
.eyebrow{font-size:12.5px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--blue)}
.disp{font-family:var(--display);font-weight:800;letter-spacing:-.035em;line-height:1.02;text-wrap:balance}
.h2{font-family:var(--display);font-weight:800;font-size:clamp(32px,4.2vw,48px);letter-spacing:-.03em;line-height:1.06;text-wrap:balance}
.h3{font-family:var(--display);font-weight:800;font-size:21px;letter-spacing:-.02em;line-height:1.2}
.lede{font-size:clamp(17px,1.5vw,19px);color:var(--ink2);line-height:1.6}
.muted{color:var(--ink3)}.grad{background:var(--grad);-webkit-background-clip:text;background-clip:text;color:transparent}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:48px;padding:0 22px;border-radius:999px;font-weight:650;font-size:15.5px;white-space:nowrap;transition:background .15s,box-shadow .15s,transform .15s}
.btn-p{background:var(--blue);color:#fff}.btn-p:hover{background:var(--blue-hi)}
.btn-q{background:var(--paper);color:var(--ink);box-shadow:inset 0 0 0 1px var(--line2)}.btn-q:hover{box-shadow:inset 0 0 0 1px var(--ink3)}
.btn-lg{min-height:56px;padding:0 28px;font-size:16.5px}
.btn .ic-s{transition:transform .15s}.btn:hover .ic-s{transform:translateX(2px)}
.chip{display:inline-flex;align-items:center;gap:6px;height:28px;padding:0 12px;border-radius:999px;font-size:13px;font-weight:600;background:var(--tint);color:var(--ink2)}
.card{background:var(--paper);border-radius:var(--r-lg);box-shadow:0 0 0 1px var(--line)}
section{scroll-margin-top:84px}
/* nav */
.nav{position:sticky;top:0;z-index:50;background:rgba(255,255,255,.86);backdrop-filter:saturate(1.6) blur(14px);-webkit-backdrop-filter:saturate(1.6) blur(14px);border-bottom:1px solid transparent;transition:border-color .2s}
.nav.scrolled{border-bottom-color:var(--line)}
.nav-in{display:flex;align-items:center;gap:28px;height:72px}
.lockup{display:inline-flex;align-items:center;gap:10px}.lockup .m{height:34px;width:auto}.lockup .w{height:22px;width:auto}
.nav-links{display:flex;gap:26px;font-size:15px;font-weight:550;color:var(--ink2)}.nav-links a:hover,.nav-links a[aria-current="page"]{color:var(--ink)}
.nav-right{margin-left:auto;display:flex;align-items:center;gap:10px}
.nav-right .btn{min-height:42px;padding:0 18px;font-size:14.5px}
.menu-btn{display:none;width:44px;height:44px;border-radius:12px;place-items:center;box-shadow:inset 0 0 0 1px var(--line2)}
.sheet{display:none}
/* hero */
.hero{position:relative;padding:72px 0 88px;overflow:hidden;background:linear-gradient(180deg,var(--tint) 0%,var(--paper) 78%)}
.hero-in{display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);gap:48px;align-items:center}
.hero h1{font-size:clamp(52px,7.4vw,92px);margin-top:18px}
.hero .lede{margin-top:22px;max-width:520px}
.ctas{display:flex;gap:12px;flex-wrap:wrap;margin-top:32px}
.facts{display:flex;gap:10px 22px;flex-wrap:wrap;margin-top:28px;font-size:14px;color:var(--ink3)}
.facts span{display:inline-flex;align-items:center;gap:7px}.facts .ic-s{color:var(--blue)}
/* the product window */
.win{border-radius:18px;background:var(--d-bg);color:var(--d-text);box-shadow:0 40px 90px -36px rgba(10,16,51,.5),0 0 0 1px rgba(10,16,51,.1);overflow:hidden;font-size:12px}
.win-bar{height:34px;display:flex;align-items:center;gap:7px;padding:0 14px;background:#11121A;border-bottom:1px solid var(--d-line)}
.win-bar i{width:10px;height:10px;border-radius:50%;background:#2B2E40;display:block}
.bo-top{display:flex;align-items:center;gap:10px;padding:10px 14px;border-bottom:1px solid var(--d-line)}
.tally{display:inline-flex;align-items:center;gap:6px;height:22px;padding:0 9px;border-radius:6px;background:var(--d-live);color:#fff;font-weight:700;font-size:10.5px;letter-spacing:.06em}
.tally i{width:6px;height:6px;border-radius:50%;background:#fff;display:block;animation:pulse 2s ease-in-out infinite}
@keyframes pulse{50%{opacity:.35}}
.bo-top b{font-family:var(--display);font-size:13px}.bo-top .ahead{color:var(--d-ok);font-weight:650;font-size:11px}
.bo-top .clock{margin-left:auto;font-family:var(--display);font-weight:800;font-size:16px;font-variant-numeric:tabular-nums}
.bo-body{display:grid;grid-template-columns:132px minmax(0,1fr) 124px}
.bo-ord{border-right:1px solid var(--d-line);padding:10px 8px;display:flex;flex-direction:column;gap:2px}
.bo-ord .k{font-size:9px;font-weight:800;letter-spacing:.14em;color:var(--d-faint);padding:8px 8px 3px}
.bo-ord .it{display:flex;gap:8px;padding:6px 8px;border-radius:7px;color:var(--d-dim);white-space:nowrap;overflow:hidden}
.bo-ord .it .t{width:30px;flex:none;color:var(--d-faint);font-size:10.5px}
.bo-ord .it.done{opacity:.5}.bo-ord .it.now{background:rgba(229,72,77,.14);color:var(--d-text);box-shadow:inset 2px 0 0 var(--d-live)}
.bo-mid{padding:12px;display:flex;flex-direction:column;gap:10px;min-width:0}
.lab{display:flex;justify-content:space-between;font-size:9.5px;font-weight:800;letter-spacing:.12em;color:var(--d-faint);margin-bottom:5px}.lab.live{color:#FF8A8E}
.slide{aspect-ratio:16/9;border-radius:8px;background:#0F1C55;display:flex;flex-direction:column;justify-content:center;padding:7%;color:#fff;overflow:hidden}
.slide .ref{font-size:9px;letter-spacing:.14em;font-weight:700;opacity:.65}
.slide p{font-family:Georgia,'Times New Roman',serif;font-size:clamp(11px,1.05vw,15px);line-height:1.35;margin-top:6px;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden}
.slide.on{box-shadow:0 0 0 2px var(--d-live)}
.bo-pair{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(0,1fr);gap:10px;align-items:end}
.bo-pair .slide.next p{font-size:clamp(8.5px,.75vw,10.5px);-webkit-line-clamp:2}
.film{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:6px}
.film span{aspect-ratio:16/9;border-radius:4px;background:#1A2350}.film span.on{box-shadow:0 0 0 1.5px var(--d-live)}.film span.nx{box-shadow:0 0 0 1.5px var(--d-blue)}
.bo-side{border-left:1px solid var(--d-line);padding:12px 10px;display:flex;flex-direction:column;gap:8px}
.bo-side .k{font-size:9px;font-weight:800;letter-spacing:.14em;color:var(--d-faint)}
.bo-side .p{display:flex;align-items:center;justify-content:space-between;gap:6px;color:var(--d-dim);font-size:11px}
.bo-side .p b{color:var(--d-text);font-weight:600}.bo-side .here{color:var(--d-ok);font-weight:650;font-size:10.5px}.bo-side .way{color:#F0B64C;font-weight:650;font-size:10.5px}
/* bands */
.band{padding:104px 0}.band-alt{background:var(--ground)}
.head{max-width:720px}.head .h2{margin-top:12px}.head .lede{margin-top:16px}
.head.center{margin:0 auto;text-align:center}
.three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin-top:52px}
.pillar{padding:28px;display:flex;flex-direction:column;gap:12px}
.pillar .n{font-family:var(--display);font-weight:800;font-size:13px;letter-spacing:.08em;color:var(--blue)}
.pillar > p{color:var(--ink2);font-size:15.5px}
.vign{margin-top:auto;border-radius:14px;background:var(--ground);padding:14px;display:flex;flex-direction:column;gap:8px;font-size:13.5px}
.vrow{display:flex;align-items:center;gap:10px}.vrow .t{width:44px;color:var(--ink3);font-size:12.5px;font-variant-numeric:tabular-nums}.vrow b{font-weight:600;flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.st{display:inline-flex;align-items:center;height:22px;padding:0 8px;border-radius:6px;font-size:11.5px;font-weight:650;white-space:nowrap}
.st-yes{background:var(--ok-soft);color:var(--ok)}.st-wait{background:var(--wait-soft);color:var(--wait)}.st-open{box-shadow:inset 0 0 0 1.5px var(--line2);color:var(--ink3)}
.vign.dark{background:var(--d-bg);color:var(--d-text)}
/* four screens */
.screens{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin-top:52px}
.scr{display:flex;flex-direction:column;gap:12px}
.tv{aspect-ratio:16/9;border-radius:12px;overflow:hidden;position:relative;background:#0F1C55;color:#fff;display:flex;flex-direction:column;justify-content:center;padding:8%;box-shadow:0 18px 40px -24px rgba(10,16,51,.55)}
.tv p{font-family:Georgia,serif;font-size:clamp(11px,1.15vw,15px);line-height:1.35}
.tv .ref{font-size:8px;letter-spacing:.14em;font-weight:700;opacity:.65;margin-bottom:5px}
.tv.stage{background:#000;justify-content:flex-start;gap:6px;padding:7%}
.tv.stage .now{font-weight:800;font-size:clamp(11px,1.1vw,14px);line-height:1.25}
.tv.stage .nx{color:#8C90A8;font-size:clamp(8px,.8vw,10.5px)}
.tv.stage .row{margin-top:auto;display:flex;justify-content:space-between;font-weight:800;font-size:clamp(9px,.9vw,12px);font-variant-numeric:tabular-nums}
.tv.stage .row span:last-child{color:var(--d-blue)}
.tv.stream{background:linear-gradient(135deg,#3B4A6B,#1E2638);justify-content:flex-end;padding:0}
.tv.stream .cam{position:absolute;inset:0;background:radial-gradient(60% 70% at 50% 40%,rgba(255,255,255,.14),transparent 70%)}
.tv.stream .lt{position:relative;margin:0 6% 7%;padding:6px 10px;border-radius:6px;background:rgba(10,16,51,.86);font-size:clamp(8.5px,.85vw,11px)}
.tv.stream .lt b{display:block;font-size:clamp(9px,.95vw,12px)}
.tv.lobby{background:#F5F6FB;color:var(--ink);justify-content:flex-end;gap:2px}
.tv.lobby .k{font-size:clamp(7px,.7vw,9px);font-weight:800;letter-spacing:.14em;color:var(--blue)}
.tv.lobby b{font-family:var(--display);font-weight:800;font-size:clamp(12px,1.3vw,17px);letter-spacing:-.02em}
.tv.lobby small{font-size:clamp(8px,.75vw,10px);color:var(--ink2)}
.scr h3{font-family:var(--display);font-size:17px;font-weight:800;letter-spacing:-.02em}
.scr p.d{font-size:14.5px;color:var(--ink2);margin-top:-6px}
/* planning */
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:64px;align-items:center}
.ticks{list-style:none;margin:28px 0 0;padding:0;display:flex;flex-direction:column;gap:14px}
.ticks li{display:flex;gap:12px;font-size:16px;color:var(--ink2)}.ticks li .ic{color:var(--blue);margin-top:2px}
.ticks li b{color:var(--ink);font-weight:650}
.stage-art{position:relative;min-height:520px}
.grid-card{position:absolute;left:0;top:10px;width:70%;padding:16px;background:var(--d-bg);color:var(--d-text);border-radius:16px;box-shadow:0 30px 70px -34px rgba(10,16,51,.6)}
.grid-card .gh{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}.grid-card .gh b{font-family:var(--display);font-size:14px}
.grid-card .gh span{font-size:11px;color:var(--d-faint)}
.mx{display:grid;grid-template-columns:62px repeat(3,minmax(0,1fr));gap:6px;font-size:11px}
.mx .h{color:var(--d-faint);font-weight:700;font-size:10px}.mx .r{color:var(--d-dim);font-weight:600;align-self:center}
.mx .c{border-radius:8px;background:var(--d-panel);padding:6px 7px;display:flex;flex-direction:column;gap:3px;min-height:44px;box-shadow:inset 0 0 0 1px var(--d-line)}
.mx .c b{font-weight:600;font-size:10.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mx .c i{font-style:normal;font-size:9.5px;font-weight:700}.mx .c i.y{color:var(--d-ok)}.mx .c i.w{color:#F0B64C}.mx .c i.o{color:var(--d-faint)}
.mx .x4{display:none}
.mx .c.open{background:transparent;box-shadow:inset 0 0 0 1px var(--d-line2);justify-content:center;align-items:center;color:var(--d-blue);font-weight:700}
.phone{position:absolute;right:0;bottom:0;width:270px;border-radius:34px;background:#fff;box-shadow:0 0 0 9px #0B0C12,0 40px 80px -30px rgba(10,16,51,.65);overflow:hidden}
.phone .bar{height:30px;display:flex;justify-content:center;align-items:center}.phone .bar i{width:84px;height:20px;border-radius:999px;background:#0B0C12}
.mail{padding:12px 16px 18px;display:flex;flex-direction:column;gap:10px;font-size:13px}
.mail .from{display:flex;align-items:center;gap:8px}.mail .crest{width:30px;height:30px;border-radius:8px;background:#0F1C55;color:#fff;display:grid;place-items:center;font-weight:800;font-size:11px}
.mail .from b{display:block;font-size:12.5px}.mail .from small{color:var(--ink3);font-size:11px}
.mail h4{font-family:var(--display);font-weight:800;font-size:19px;letter-spacing:-.02em;line-height:1.15}
.mail .facts2{border-radius:12px;background:var(--ground);padding:4px 12px;font-size:12px}
.mail .facts2 div{display:flex;justify-content:space-between;padding:7px 0;border-top:1px solid var(--line)}.mail .facts2 div:first-child{border-top:0}
.mail .facts2 span{color:var(--ink3)}
.mail .y{height:42px;border-radius:999px;background:var(--blue);color:#fff;display:grid;place-items:center;font-weight:700;font-size:14px}
.mail .n{height:42px;border-radius:999px;box-shadow:inset 0 0 0 1.5px var(--line2);display:grid;place-items:center;font-weight:650;font-size:14px}
.mail .alt{text-align:center;font-size:12px;color:var(--blue);font-weight:600}
/* the week */
.week{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0;margin-top:56px;position:relative}
.week::before{content:"";position:absolute;left:0;right:0;top:19px;height:2px;background:var(--line)}
.day{position:relative;padding-right:18px;display:flex;flex-direction:column;gap:8px}
.day .dot{width:40px;height:40px;border-radius:50%;background:var(--paper);box-shadow:inset 0 0 0 2px var(--blue);display:grid;place-items:center;color:var(--blue);position:relative}
.day.sun .dot{background:var(--blue);color:#fff;box-shadow:none}
.day small,.day b{display:block}
.day small{font-size:12.5px;font-weight:700;letter-spacing:.1em;color:var(--ink3);text-transform:uppercase;margin-top:6px}
.day b{font-family:var(--display);font-size:18px;font-weight:800;letter-spacing:-.02em}
.day p{font-size:14.5px;color:var(--ink2)}
/* bring what you have */
.four{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin-top:52px}
.tile{padding:24px;display:flex;flex-direction:column;gap:10px}
.tile .ib{width:44px;height:44px;border-radius:12px;background:var(--blue-soft);color:var(--blue);display:grid;place-items:center}
.tile p{font-size:14.5px;color:var(--ink2)}
.wide{margin-top:18px;padding:22px 26px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.wide .ib{width:44px;height:44px;border-radius:12px;background:var(--ink);color:#fff;display:grid;place-items:center;flex:none}
.wide p{flex:1;min-width:240px;color:var(--ink2);font-size:15.5px}.wide p b{color:var(--ink)}
/* pricing */
.plans{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin-top:52px;align-items:stretch}
.plan{padding:30px;display:flex;flex-direction:column;gap:14px;position:relative}
.plan.best{box-shadow:0 0 0 2px var(--blue)}
.plan .tag{position:absolute;top:-13px;left:28px;height:26px;padding:0 12px;border-radius:999px;background:var(--blue);color:#fff;font-size:12px;font-weight:700;display:inline-flex;align-items:center}
.plan .amt{font-family:var(--display);font-weight:800;font-size:46px;letter-spacing:-.04em;line-height:1}
.plan .amt small{font-family:var(--text);font-size:15px;font-weight:500;color:var(--ink3);letter-spacing:0}
.plan ul{list-style:none;margin:6px 0 0;padding:0;display:flex;flex-direction:column;gap:10px;font-size:15px;color:var(--ink2)}
.plan li{display:flex;gap:10px}.plan li .ic-s{color:var(--blue);margin-top:3px}
.plan .btn{margin-top:auto}
.note{margin-top:22px;text-align:center;font-size:14.5px;color:var(--ink3)}
/* partner */
.partner{background:var(--ink);color:#fff;border-radius:var(--r-xl);padding:56px;display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:48px;align-items:center}
.partner .eyebrow{color:#8EA6FF}.partner p{color:#C9CEE6;font-size:17px;margin-top:14px}
.pair{display:flex;flex-direction:column;gap:12px}
.pair div{display:flex;gap:14px;align-items:flex-start;padding:16px 18px;border-radius:14px;background:rgba(255,255,255,.06);box-shadow:inset 0 0 0 1px rgba(255,255,255,.08)}
.pair .ic{color:#8EA6FF;margin-top:2px}.pair b{display:block;font-size:15.5px}.pair span{color:#C9CEE6;font-size:14.5px}
.btn-w{background:#fff;color:var(--ink)}.btn-w:hover{background:var(--tint)}
/* faq */
.faq{max-width:820px;margin:44px auto 0;display:flex;flex-direction:column;gap:10px}
.faq details{border-radius:16px;background:var(--paper);box-shadow:0 0 0 1px var(--line);padding:0 22px}
.faq summary{list-style:none;cursor:pointer;display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:64px;font-weight:650;font-size:16.5px}
.faq summary::-webkit-details-marker{display:none}
.faq summary::after{content:"";width:10px;height:10px;border-right:2px solid var(--ink3);border-bottom:2px solid var(--ink3);transform:rotate(45deg) translateY(-3px);transition:transform .2s;flex:none}
.faq details[open] summary::after{transform:rotate(225deg) translateY(-3px)}
.faq details p{padding:0 0 20px;color:var(--ink2);font-size:15.5px;max-width:700px}
/* final */
.final{text-align:center;padding:112px 0}
.final img{height:84px;width:auto;margin:0 auto 22px}
.final h2{font-size:clamp(44px,6vw,72px)}
.final .ctas{justify-content:center}
/* footer */
.foot{border-top:1px solid var(--line);padding:44px 0 56px;font-size:14px;color:var(--ink3)}
.foot-in{display:flex;flex-wrap:wrap;align-items:center;gap:18px 28px}
.foot-in .w{height:20px;width:auto}
.foot-in nav{display:flex;flex-wrap:wrap;gap:8px 24px}.foot-in nav a:hover{color:var(--ink)}
.foot-in .c{margin-left:auto}
/* pricing page */
.page-head{padding:80px 0 20px;text-align:center;background:linear-gradient(180deg,var(--tint) 0%,var(--paper) 100%)}
.page-head h1{font-size:clamp(44px,6vw,68px);margin-top:14px}.page-head .lede{max-width:640px;margin:18px auto 0}
.addon{margin-top:20px;padding:26px 30px;display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:22px;align-items:center}
.addon .sol{width:48px;height:48px;border-radius:13px;background:#2E7DFF;color:#fff;display:grid;place-items:center;font-family:var(--display);font-weight:800;font-size:22px}
.addon p{color:var(--ink2);font-size:15px}.addon b.big{font-family:var(--display);font-size:28px;letter-spacing:-.03em}
.cmp{margin-top:28px;border-radius:var(--r-lg);box-shadow:0 0 0 1px var(--line);overflow:hidden}
.cmp .rw{display:grid;grid-template-columns:minmax(0,1.6fr) repeat(3,minmax(0,1fr));align-items:center;border-top:1px solid var(--line);min-height:52px;font-size:15px}
.cmp .rw:first-child{border-top:0;background:var(--ground);font-weight:700;font-size:13.5px;letter-spacing:.02em}
.cmp .rw > *{padding:12px 18px}.cmp .rw > :not(:first-child){text-align:center}
.cmp .yes{color:var(--blue)}.cmp .no{color:var(--line2)}
.cmp .sec{background:var(--ground);font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--ink3);padding:10px 18px;border-top:1px solid var(--line)}
/* how-it-works page */
.mapx{display:grid;grid-template-columns:minmax(0,1fr) 56px minmax(0,1fr) 56px minmax(0,1fr);margin-top:52px;align-items:stretch}
.col{border-radius:var(--r-xl);padding:28px;display:flex;flex-direction:column;gap:14px}
.col h3{font-family:var(--display);font-weight:800;font-size:22px;letter-spacing:-.02em}
.col ul{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:12px;font-size:15.5px}
.col li{display:flex;gap:10px}.col li .ic-s{margin-top:3px}
.col.a{background:var(--tint)}.col.a .ic-s{color:var(--blue)}
.col.b{background:var(--ink);color:#fff}.col.b .eyebrow{color:#8EA6FF}.col.b .ic-s{color:#8EA6FF}
.col.c{background:#EAF2FF}.col.c .eyebrow{color:#1F63D6}.col.c .ic-s{color:#2E7DFF}
.linkx{display:grid;place-items:center;color:var(--ink3)}
.steps{display:flex;flex-direction:column;gap:18px;margin-top:26px}
.steps div{display:flex;gap:16px}.steps b.n{width:34px;height:34px;border-radius:50%;background:var(--ink);color:#fff;display:grid;place-items:center;font-size:14px;flex:none}
.steps span{font-size:16px;color:var(--ink2);padding-top:5px}.steps strong{color:var(--ink)}
.dlg{padding:28px;display:flex;flex-direction:column;gap:14px;box-shadow:0 30px 80px -34px rgba(10,16,51,.4),0 0 0 1px var(--line)}
.dlg h4{font-family:var(--display);font-weight:800;font-size:20px;letter-spacing:-.02em}
.dlg .sh{display:flex;flex-direction:column;gap:10px;font-size:15px}.dlg .sh div{display:flex;gap:10px;align-items:center}.dlg .sh .ic-s{color:var(--ok)}
/* reveal */
.rv{opacity:0;transform:translateY(16px);transition:opacity .6s ease,transform .6s ease}.rv.in{opacity:1;transform:none}
@media (prefers-reduced-motion:reduce){.rv{opacity:1;transform:none;transition:none}.tally i{animation:none}html{scroll-behavior:auto}}
/* tablet */
@media (max-width:1080px){
 .hero-in,.split,.partner{grid-template-columns:minmax(0,1fr)}
 .hero{padding:52px 0 72px}.stage-art{min-height:500px;max-width:620px}
 .three,.plans{grid-template-columns:minmax(0,1fr)}.plans{max-width:520px;margin-left:auto;margin-right:auto}
 .screens,.four{grid-template-columns:repeat(2,minmax(0,1fr))}
 .week{grid-template-columns:minmax(0,1fr);gap:22px}.week::before{left:19px;right:auto;top:0;bottom:0;width:2px;height:auto}
 .day{flex-direction:row;flex-wrap:wrap;align-items:flex-start;column-gap:16px;padding:0}.day .dot{flex:none}.day > div{flex:1;min-width:0}
 .mapx{grid-template-columns:minmax(0,1fr)}.linkx{height:40px}.linkx svg{transform:rotate(90deg)}
}
/* phone */
@media (max-width:760px){
 .wrap{padding:0 20px}.band{padding:72px 0}
 .nav-in{height:64px}.nav-links,.nav-right .btn-q{display:none}.menu-btn{display:grid}
 .nav-right .btn-p{display:none}
 .bo-top .ahead{display:none}.bo-top b{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
 .sheet{position:fixed;inset:64px 0 auto 0;z-index:49;background:#fff;border-bottom:1px solid var(--line);padding:12px 20px 22px;flex-direction:column;gap:2px}
 .sheet.open{display:flex}.sheet a{min-height:48px;display:flex;align-items:center;font-size:17px;font-weight:600;border-bottom:1px solid var(--line)}
 .sheet .btn{margin-top:14px;border-bottom:0}
 .lockup .m{height:30px}.lockup .w{height:19px}
 .hero h1{font-size:clamp(46px,13vw,60px)}
 .ctas .btn{flex:1 1 100%}
 .bo-body{grid-template-columns:minmax(0,1fr)}.bo-ord,.bo-side{display:none}
 .screens,.four{grid-template-columns:minmax(0,1fr)}
 .stage-art{min-height:auto;display:flex;flex-direction:column;gap:22px}
 .grid-card,.phone{position:relative;width:100%;top:auto;right:auto;bottom:auto}.phone{max-width:300px;margin:0 auto}
 .mx{grid-template-columns:58px repeat(3,minmax(0,1fr))}
 .partner{padding:32px 22px;border-radius:22px}
 .addon{grid-template-columns:auto minmax(0,1fr)}.addon .btn{grid-column:1 / -1}
 .cmp .rw{grid-template-columns:minmax(0,1.3fr) repeat(3,minmax(0,.7fr));font-size:13.5px}.cmp .rw > *{padding:10px 8px}
 .foot-in .c{margin-left:0;width:100%}
}
"""

# ─── shared pieces ───────────────────────────────────────────────────


def _href(base: str, page: str) -> str:
    if page in ("", "/"):
        return base or "/"
    return f"{base}/{page}" if base else f"/{page}"


def _nav(base: str, active: str) -> str:
    app = app_url()
    links = [("#product" if active == "home" else _href(base, "") + "#product", "Product", ""),
             ("#planning" if active == "home" else _href(base, "") + "#planning", "Planning", ""),
             (_href(base, "pricing"), "Pricing", "pricing"),
             (_href(base, "solutionist"), "With Solutionist", "solutionist")]
    here = ' aria-current="page"'
    nav_links = "".join(f'<a href="{_e(h)}"{here if k and k == active else ""}>{_e(t)}</a>' for h, t, k in links)
    sheet_links = "".join(f'<a href="{_e(h)}">{_e(t)}</a>' for h, t, _ in links)
    return f"""
<a class="skip" href="#main">Skip to the page</a>
<header class="nav" id="nav"><div class="wrap nav-in">
  <a href="{_e(_href(base, ''))}" class="lockup" aria-label="ChurchSavvy home"><img class="m" src="/churchsavvy-assets/logo-mark.webp" alt="" width="58" height="34"><img class="w" src="/churchsavvy-assets/logo-word.webp" alt="ChurchSavvy" width="114" height="22"></a>
  <nav class="nav-links" aria-label="Main">{nav_links}</nav>
  <div class="nav-right">
    <a class="btn btn-q" href="{_e(app)}">Sign in</a>
    <a class="btn btn-p" href="{_e(app)}?signup=1">Start your church</a>
    <button class="menu-btn" type="button" aria-expanded="false" aria-controls="sheet" aria-label="Menu" id="menu">{icon('menu')}</button>
  </div>
</div></header>
<nav class="sheet" id="sheet" aria-label="Menu">{sheet_links}<a href="{_e(app)}">Sign in</a><a class="btn btn-p btn-lg" href="{_e(app)}?signup=1">Start your church</a></nav>"""


def _footer(base: str) -> str:
    app = app_url()
    return f"""
<footer class="foot"><div class="wrap foot-in">
  <img class="w" src="/churchsavvy-assets/logo-word.webp" alt="ChurchSavvy" width="104" height="20">
  <nav aria-label="Footer"><a href="{_e(_href(base, ''))}#product">Product</a><a href="{_e(_href(base, 'pricing'))}">Pricing</a><a href="{_e(_href(base, 'solutionist'))}">With Solutionist</a><a href="{_e(app)}">Sign in</a><a href="https://mysolutionist.app/privacy">Privacy</a><a href="https://mysolutionist.app/terms">Terms</a></nav>
  <span class="c">© 2026 ChurchSavvy · A partner of Solutionist</span>
</div></footer>"""


_JS = """
<script>
(function(){
  var nav=document.getElementById('nav');
  function s(){nav.classList.toggle('scrolled',window.scrollY>8)}s();window.addEventListener('scroll',s,{passive:true});
  var b=document.getElementById('menu'),sh=document.getElementById('sheet');
  if(b&&sh){b.addEventListener('click',function(){var o=sh.classList.toggle('open');b.setAttribute('aria-expanded',o?'true':'false')});
    sh.addEventListener('click',function(e){if(e.target.tagName==='A'){sh.classList.remove('open');b.setAttribute('aria-expanded','false')}})}
  var els=[].slice.call(document.querySelectorAll('.rv'));
  if(!('IntersectionObserver' in window)||matchMedia('(prefers-reduced-motion: reduce)').matches){els.forEach(function(e){e.classList.add('in')});return}
  var io=new IntersectionObserver(function(es){es.forEach(function(x){if(x.isIntersecting){x.target.classList.add('in');io.unobserve(x.target)}})},{rootMargin:'0px 0px -8% 0px',threshold:.08});
  els.forEach(function(e){io.observe(e)});
})();
</script>"""


def _page(*, title: str, description: str, path: str, base: str, active: str, body: str) -> str:
    canonical = CANONICAL + (path if path != "/" else "/")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content="{_e(description)}">
<link rel="canonical" href="{_e(canonical)}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="ChurchSavvy">
<meta property="og:title" content="{_e(title)}">
<meta property="og:description" content="{_e(description)}">
<meta property="og:url" content="{_e(canonical)}">
<meta property="og:image" content="{CANONICAL}/churchsavvy-assets/og.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0A1033">
<link rel="icon" type="image/png" sizes="64x64" href="/churchsavvy-assets/icon-64.png">
<link rel="icon" type="image/png" sizes="192x192" href="/churchsavvy-assets/icon-192.png">
<link rel="apple-touch-icon" href="/churchsavvy-assets/icon-192.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap">
<style>{CSS}</style>
</head>
<body>
{_nav(base, active)}
<main id="main">
{body}
</main>
{_footer(base)}
{_JS}
</body>
</html>"""


# ─── the home page ───────────────────────────────────────────────────


def _booth_window() -> str:
    return f"""
<div class="win" role="img" aria-label="The ChurchSavvy booth on a Sunday: the order of service, Psalm 100 on the screens, the next verse, and who's serving today">
  <div class="win-bar"><i></i><i></i><i></i></div>
  <div class="bo-top"><span class="tally"><i></i>LIVE</span><b>Sunday service · Nov 1</b><span class="ahead">2 min ahead</span><span class="clock">11:16</span></div>
  <div class="bo-body">
    <div class="bo-ord" aria-hidden="true">
      <span class="k">BEFORE</span><span class="it done"><span class="t">10:50</span>Welcome loop</span>
      <span class="k">THE SERVICE</span>
      <span class="it done"><span class="t">11:05</span>Holy, Holy, Holy</span>
      <span class="it done"><span class="t">11:10</span>Come, Thou Fount</span>
      <span class="it now"><span class="t">11:15</span>Psalm 100</span>
      <span class="it"><span class="t">11:18</span>Prayer</span>
      <span class="it"><span class="t">11:20</span>Enter His gates</span>
      <span class="it"><span class="t">12:00</span>It Is Well</span>
    </div>
    <div class="bo-mid">
      <div class="bo-pair">
        <div><div class="lab live"><span>LIVE</span><span>1 of 5</span></div>
          <div class="slide on"><span class="ref">PSALM 100:1 · KJV</span><p>Make a joyful noise unto the LORD, all ye lands.</p></div></div>
        <div><div class="lab"><span>NEXT</span></div>
          <div class="slide next"><span class="ref">PSALM 100:2</span><p>Serve the LORD with gladness: come before his presence with singing.</p></div></div>
      </div>
      <div class="film" aria-hidden="true"><span class="on"></span><span class="nx"></span><span></span><span></span><span></span></div>
    </div>
    <div class="bo-side" aria-hidden="true">
      <span class="k">SERVING TODAY</span>
      <span class="p"><b>Slides</b><span class="here">Here</span></span>
      <span class="p"><b>Sound</b><span class="here">Here</span></span>
      <span class="p"><b>Stream</b><span class="here">Here</span></span>
      <span class="p"><b>Lights</b><span class="way">On the way</span></span>
      <span class="p"><b>Greeters</b><span class="here">Here</span></span>
    </div>
  </div>
</div>"""


def render_home(base: str = "") -> str:
    app = app_url()
    body = f"""
<section class="hero" aria-labelledby="hero-h">
  <div class="wrap hero-in">
    <div>
      <p class="eyebrow">Church presentation and planning</p>
      <h1 id="hero-h" class="disp">Every Sunday, <span class="grad">ready.</span></h1>
      <p class="lede">Plan the service, put it on every screen, and get the right people serving — in one place made for churches.</p>
      <div class="ctas">
        <a class="btn btn-p btn-lg" href="{_e(app)}?signup=1">Start your church {icon('arrow', 'ic-s')}</a>
        <a class="btn btn-q btn-lg" href="#product">See how it works</a>
      </div>
      <div class="facts"><span>{icon('check', 'ic-s')}One price per church</span><span>{icon('check', 'ic-s')}Your whole team included</span><span>{icon('check', 'ic-s')}Plug in by HDMI and go</span></div>
    </div>
    <div class="rv">{_booth_window()}</div>
  </div>
</section>

<section class="band" id="product" aria-labelledby="pillars-h">
  <div class="wrap">
    <div class="head rv"><p class="eyebrow">One place, Tuesday to Sunday</p><h2 id="pillars-h" class="h2">Plan&nbsp;it. Show&nbsp;it. Serve&nbsp;it.</h2>
      <p class="lede">Most churches juggle a planning tool, a presentation app and a group text. ChurchSavvy is all three, so the plan you make on Tuesday is the show you run on Sunday.</p></div>
    <div class="three">
      <article class="card pillar rv"><span class="n">PLAN IT</span><h3 class="h3">The whole service, in order.</h3>
        <p>Songs, Scripture, announcements and the sermon, timed to the minute. Start from last week or your own template.</p>
        <div class="vign"><div class="vrow"><span class="t">11:05</span><b>Holy, Holy, Holy</b><span class="st st-yes">Key of E♭</span></div>
          <div class="vrow"><span class="t">11:15</span><b>Psalm 100 · KJV</b><span class="st st-yes">5 slides</span></div>
          <div class="vrow"><span class="t">11:20</span><b>Enter His gates</b><span class="st st-wait">2 points to add</span></div></div></article>
      <article class="card pillar rv"><span class="n">SHOW IT</span><h3 class="h3">Every screen, from one booth.</h3>
        <p>Rehearse it, then run it live. The room, the stage, the stream and the lobby each get the look that fits them.</p>
        <div class="vign dark"><div class="slide" style="box-shadow:none"><span class="ref">PSALM 100:1 · KJV</span><p>Make a joyful noise unto the LORD, all ye lands.</p></div></div></article>
      <article class="card pillar rv"><span class="n">SERVE IT</span><h3 class="h3">The right people, every week.</h3>
        <p>Ask your teams by email. They answer in one tap, with no app and no password, and reminders take care of the rest.</p>
        <div class="vign"><div class="vrow"><span class="t">Slides</span><b>Dana</b><span class="st st-yes">Said yes</span></div>
          <div class="vrow"><span class="t">Sound</span><b>Luis</b><span class="st st-wait">Asked Tue</span></div>
          <div class="vrow"><span class="t">Lights</span><b>Open</b><span class="st st-open">Fill</span></div></div></article>
    </div>
  </div>
</section>

<section class="band band-alt" aria-labelledby="screens-h">
  <div class="wrap">
    <div class="head rv"><p class="eyebrow">ChurchSavvy screens</p><h2 id="screens-h" class="h2">One press. Every screen gets the look that fits.</h2>
      <p class="lede">The booth runs them all. Plug the projector in by HDMI, and open any other screen from its own link: a stage TV, a stream, the lobby.</p></div>
    <div class="screens">
      <div class="scr rv"><div class="tv"><span class="ref">PSALM 100:4</span><p>Enter into his gates with thanksgiving…</p></div><h3>{icon('monitor', 'ic-s')} The room</h3><p class="d">Big, clear words in your church’s look.</p></div>
      <div class="scr rv"><div class="tv stage"><span class="now">Enter into his gates with thanksgiving…</span><span class="nx">Next · For the LORD is good…</span><span class="row"><span>11:16</span><span>Prayer in 2:10</span></span></div><h3>{icon('mic', 'ic-s')} The stage</h3><p class="d">What’s now, what’s next, the clock and the pastor’s notes.</p></div>
      <div class="scr rv"><div class="tv stream"><span class="cam"></span><span class="lt"><b>Psalm 100:4</b>Enter into his gates with thanksgiving</span></div><h3>{icon('radio', 'ic-s')} The stream</h3><p class="d">A lower third over the camera, never covering faces.</p></div>
      <div class="scr rv"><div class="tv lobby"><span class="k">THIS WEEK</span><b>Community dinner</b><small>Wednesday · 6:30 PM · Fellowship hall</small></div><h3>{icon('door', 'ic-s')} The lobby</h3><p class="d">Announcements and loops before and after.</p></div>
    </div>
  </div>
</section>

<section class="band" id="planning" aria-labelledby="plan-h">
  <div class="wrap split">
    <div class="rv">
      <p class="eyebrow">ChurchSavvy Planning</p>
      <h2 id="plan-h" class="h2">Your teams, without the group texts.</h2>
      <p class="lede" style="margin-top:16px">Teams, places and who serves when, with a fair way to fill the month. Every person gets a clear ask, a reminder, and their Sunday.</p>
      <ul class="ticks">
        <li>{icon('mail')}<span><b>Asks by email.</b> Yes or Can’t with one tap, and they can offer another Sunday.</span></li>
        <li>{icon('swap')}<span><b>Fill the month fairly.</b> Nobody twice in one Sunday, nobody on the Sundays they’re away, and whoever has served least goes first.</span></li>
        <li>{icon('bell')}<span><b>Reminders that know the hour.</b> A week before, the night before, that morning — never between 9 PM and 7 AM.</span></li>
        <li>{icon('heart')}<span><b>Their Sunday on one page.</b> When to arrive, their team’s notes, the order, and “I’m here” for the booth.</span></li>
      </ul>
    </div>
    <div class="stage-art rv" aria-hidden="true">
      <div class="grid-card">
        <div class="gh"><b>Who serves when · Tech</b><span>November</span></div>
        <div class="mx">
          <span></span><span class="h">Nov 1</span><span class="h">Nov 8</span><span class="h">Nov 15</span><span class="h x4">Nov 22</span>
          <span class="r">Slides</span><span class="c"><b>Dana R.</b><i class="y">Said yes</i></span><span class="c"><b>Sam K.</b><i class="y">Said yes</i></span><span class="c"><b>Ruth O.</b><i class="y">Said yes</i></span><span class="c open x4">Fill</span>
          <span class="r">Sound</span><span class="c"><b>Luis M.</b><i class="w">Asked</i></span><span class="c"><b>Marcus W.</b><i class="y">Said yes</i></span><span class="c"><b>Luis M.</b><i class="y">Said yes</i></span><span class="c x4"><b>Luis M.</b><i class="w">Asked</i></span>
          <span class="r">Stream</span><span class="c"><b>Marcus W.</b><i class="y">Said yes</i></span><span class="c"><b>Dana R.</b><i class="y">Said yes</i></span><span class="c"><b>Grace L.</b><i class="w">Asked</i></span><span class="c x4"><b>Marcus W.</b><i class="y">Said yes</i></span>
          <span class="r">Lights</span><span class="c"><b>Jordan P.</b><i class="y">Said yes</i></span><span class="c open">Fill</span><span class="c"><b>Jordan P.</b><i class="w">Asked</i></span><span class="c x4"><b>Sam K.</b><i class="y">Said yes</i></span>
        </div>
      </div>
      <div class="phone">
        <div class="bar"><i></i></div>
        <div class="mail">
          <div class="from"><span class="crest">LC</span><span><b>Love City Church</b><small>via ChurchSavvy · 9:12 AM</small></span></div>
          <h4>Can you run Livestream on Sunday, Nov 15?</h4>
          <div class="facts2"><div><span>Arrive by</span><b>10:30 AM</b></div><div><span>Service</span><b>11:05 AM</b></div><div><span>Asked by</span><b>Dana</b></div></div>
          <span class="y">Yes, I’m in</span><span class="n">Can’t this time</span><span class="alt">Can’t that day, but I could do another</span>
        </div>
      </div>
    </div>
  </div>
</section>

<section class="band band-alt" aria-labelledby="week-h">
  <div class="wrap">
    <div class="head center rv"><p class="eyebrow">How a week goes</p><h2 id="week-h" class="h2">From Tuesday’s plan to Sunday’s last slide.</h2></div>
    <div class="week">
      <div class="day rv"><span class="dot">{icon('layers', 'ic-s')}</span><div><small>Tuesday</small><b>Plan the service</b><p>Pick the songs and the reading. The order and times lay themselves out.</p></div></div>
      <div class="day rv"><span class="dot">{icon('users', 'ic-s')}</span><div><small>Wednesday</small><b>Fill the teams</b><p>Fill the month in one press. The asks go out by email.</p></div></div>
      <div class="day rv"><span class="dot">{icon('play', 'ic-s')}</span><div><small>Thursday</small><b>Rehearse</b><p>Step through every slide before Sunday, without going live.</p></div></div>
      <div class="day rv"><span class="dot">{icon('bell', 'ic-s')}</span><div><small>Saturday</small><b>Everyone’s ready</b><p>Each person gets their Sunday: when to arrive, notes, the order.</p></div></div>
      <div class="day sun rv"><span class="dot">{icon('check', 'ic-s')}</span><div><small>Sunday</small><b>Run it live</b><p>One booth, every screen. The booth sees who’s here.</p></div></div>
    </div>
  </div>
</section>

<section class="band" aria-labelledby="bring-h">
  <div class="wrap">
    <div class="head rv"><p class="eyebrow">Switching is easy</p><h2 id="bring-h" class="h2">Bring what you already have.</h2>
      <p class="lede">Your songs come with you, and the words stay exactly as your church typed them.</p></div>
    <div class="four">
      <div class="card tile rv"><span class="ib">{icon('music')}</span><h3 class="h3">From Proclaim</h3><p>Bring your song library over from Proclaim, with each song’s verses and choruses.</p></div>
      <div class="card tile rv"><span class="ib">{icon('file')}</span><h3 class="h3">Song files</h3><p>Open SongSelect and ChordPro files you already have.</p></div>
      <div class="card tile rv"><span class="ib">{icon('camera')}</span><h3 class="h3">A photo of the words</h3><p>Take a picture of a lyric sheet or a chord chart. ChurchSavvy reads it for you.</p></div>
      <div class="card tile rv"><span class="ib">{icon('clipboard')}</span><h3 class="h3">Paste them in</h3><p>Paste the words and ChurchSavvy splits them into slides by verse and chorus.</p></div>
    </div>
    <div class="card wide rv"><span class="ib">{icon('plug')}</span><p><b>Works with the screens you have.</b> Plug the projector into your computer by HDMI, open other screens from a link, and the projector keeps going if the internet drops. Scripture comes in the King James Version and the World English Bible.</p></div>
  </div>
</section>

<section class="band band-alt" aria-labelledby="price-h">
  <div class="wrap">
    <div class="head center rv"><p class="eyebrow">Pricing</p><h2 id="price-h" class="h2">Simple, monthly, one price per church.</h2>
      <p class="lede">Every person on your team is included. Change your plan or cancel any time.</p></div>
    {_plans_html(app)}
    <p class="note rv"><a href="{_e(_href(base, 'pricing'))}" style="color:var(--blue);font-weight:650">Compare the plans in full →</a></p>
  </div>
</section>

<section class="band" aria-labelledby="partner-h">
  <div class="wrap">
    <div class="partner rv">
      <div><p class="eyebrow">A Solutionist partner</p><h2 id="partner-h" class="h2" style="color:#fff">Ready for more than Sunday?</h2>
        <p>When your church wants a member app, giving, groups and care, Solutionist joins the same church. Nothing you built in ChurchSavvy moves.</p>
        <div class="ctas"><a class="btn btn-w btn-lg" href="{_e(_href(base, 'solutionist'))}">How they work together {icon('arrow', 'ic-s')}</a></div></div>
      <div class="pair">
        <div>{icon('bell')}<span><b>Asks reach phones</b>Volunteers with the member app get a notification. Everyone else still gets email.</span></div>
        <div>{icon('users')}<span><b>One list of people</b>The members you care for and the people who serve, added once.</span></div>
        <div>{icon('card')}<span><b>One bill</b>Planning comes included with Solutionist.</span></div>
      </div>
    </div>
  </div>
</section>

<section class="band band-alt" aria-labelledby="faq-h">
  <div class="wrap">
    <div class="head center rv"><p class="eyebrow">Questions</p><h2 id="faq-h" class="h2">Good to know.</h2></div>
    <div class="faq">
      <details class="rv"><summary>Do our volunteers need an account?</summary><p>No. Volunteers answer asks from the email itself and see their Sunday on a web page. Only the people who plan and run Sunday sign in, and each opens to just their part: planner, worship leader, booth, media or admin.</p></details>
      <details class="rv"><summary>Can we bring our songs from Proclaim?</summary><p>Yes. Bring your song library over from Proclaim, along with SongSelect and ChordPro files. You can also add songs from a photo of the words or by pasting them.</p></details>
      <details class="rv"><summary>What do we need for the projector?</summary><p>A computer with ChurchSavvy open in the browser, plugged into your projector by HDMI. ChurchSavvy finds the screen and puts Sunday on it. Other screens — a stage TV, the stream, the lobby — open from their own links.</p></details>
      <details class="rv"><summary>What happens if the internet drops on Sunday?</summary><p>The projector plugged into your computer keeps going, because the booth feeds it directly. Screens opened from a link catch up as soon as they’re back online.</p></details>
      <details class="rv"><summary>Which Bibles are included?</summary><p>The King James Version and the World English Bible, with search by reference or by words, and verses split into slides for you.</p></details>
      <details class="rv"><summary>Is there a contract?</summary><p>No. Plans are monthly, one price for the whole church, and you can change or cancel any time.</p></details>
    </div>
  </div>
</section>

<section class="final" aria-labelledby="final-h">
  <div class="wrap rv">
    <img src="/churchsavvy-assets/logo-mark.webp" alt="" width="142" height="84">
    <h2 id="final-h" class="disp">Every Sunday, <span class="grad">ready.</span></h2>
    <p class="lede" style="margin:18px auto 0;max-width:520px">Set up your church tonight and have your first Sunday on the screens this week.</p>
    <div class="ctas"><a class="btn btn-p btn-lg" href="{_e(app)}?signup=1">Start your church {icon('arrow', 'ic-s')}</a><a class="btn btn-q btn-lg" href="{_e(_href(base, 'pricing'))}">See pricing</a></div>
  </div>
</section>"""
    return _page(title="ChurchSavvy · Every Sunday, ready.",
                 description="Plan the service, put it on every screen, and get the right people serving — church presentation and planning in one place.",
                 path="/", base=base, active="home", body=body)


def _plans_html(app: str) -> str:
    def li(items):
        return "".join(f"<li>{icon('check', 'ic-s')}<span>{_e(t)}</span></li>" for t in items)
    return f"""
<div class="plans">
  <article class="card plan rv"><p class="eyebrow">ChurchSavvy</p><p class="amt">$20<small> / month</small></p>
    <p class="muted">Plan, rehearse and run Sunday on every screen.</p>
    <ul>{li(["Plan each Sunday, rehearse it, run it live", "Songs, Scripture, loops and the sermon", "Room, stage, stream and lobby screens", "Your booth team signs in to just their part"])}</ul>
    <a class="btn btn-q" href="{_e(app)}?signup=1&amp;plan=churchsavvy">Start with ChurchSavvy</a></article>
  <article class="card plan rv"><p class="eyebrow">ChurchSavvy Planning</p><p class="amt">$15<small> / month</small></p>
    <p class="muted">Your teams and who serves when, with asks by email.</p>
    <ul>{li(["Teams, places and who serves when", "Asks and reminders by email, answered in one tap", "Fill the month fairly in one press", "A note for each team on the order"])}</ul>
    <a class="btn btn-q" href="{_e(app)}?signup=1&amp;plan=planning">Start with Planning</a></article>
  <article class="card plan best rv"><span class="tag">Save $6</span><p class="eyebrow">Both together</p><p class="amt">$29<small> / month</small></p>
    <p class="muted">The screens and the people, in one plan.</p>
    <ul>{li(["Everything in ChurchSavvy and Planning", "The booth sees who’s on and who’s here", "Team notes in the booth and on their Sunday", "One price for your whole church"])}</ul>
    <a class="btn btn-p" href="{_e(app)}?signup=1&amp;plan=both">Start with both</a></article>
</div>"""


# ─── pricing ─────────────────────────────────────────────────────────


def render_pricing(base: str = "") -> str:
    app = app_url()
    y = f'<span class="yes">{icon("check", "ic-s")}<span class="sr">Included</span></span>'
    n = '<span class="no">—<span class="sr">Not included</span></span>'
    rows = [
        ("sec", "Sunday on the screens"),
        ("Plan each Sunday, in order and timed", y, n, y), ("Rehearse without going live", y, n, y),
        ("Run it live from the booth", y, n, y), ("Room, stage, stream and lobby screens", y, n, y),
        ("Song library, Proclaim and song files", y, n, y), ("KJV and WEB Bibles", y, n, y),
        ("sec", "Your teams"),
        ("Teams, places and who serves when", n, y, y), ("Asks and reminders by email", n, y, y),
        ("Fill the month fairly", n, y, y), ("Order of service with team notes", n, y, y),
        ("sec", "Together"),
        ("The booth sees who’s on and who’s here", n, n, y), ("Every person on your team", y, y, y),
    ]
    grid = '<div class="rw"><span>What’s included</span><span>ChurchSavvy</span><span>Planning</span><span>Both</span></div>'
    for r in rows:
        if r[0] == "sec":
            grid += f'<div class="sec">{_e(r[1])}</div>'
        else:
            grid += f'<div class="rw"><span>{_e(r[0])}</span>{r[1]}{r[2]}{r[3]}</div>'
    body = f"""
<section class="page-head" aria-labelledby="ph">
  <div class="wrap"><p class="eyebrow">Pricing</p><h1 id="ph" class="disp">One price per church.</h1>
    <p class="lede">Every person on your team is included. Monthly, with no contract — change your plan or cancel any time.</p></div>
</section>
<section class="band" style="padding-top:28px" aria-label="Plans">
  <div class="wrap">
    {_plans_html(app)}
    <div class="card addon rv"><span class="sol" aria-hidden="true">S</span>
      <div><p class="eyebrow" style="color:#1F63D6">Already on Solutionist?</p><p><b class="big">$10</b> a month adds ChurchSavvy’s screens to your Solutionist plan. Planning comes included.</p></div>
      <a class="btn btn-q" href="{_e(_href(base, 'solutionist'))}">How it works</a></div>
    <div class="cmp rv" role="table" aria-label="Compare the plans">{grid}</div>
  </div>
</section>
<section class="band band-alt" aria-labelledby="pfaq">
  <div class="wrap">
    <div class="head center rv"><h2 id="pfaq" class="h2">About billing.</h2></div>
    <div class="faq">
      <details class="rv"><summary>Is it really one price for the whole church?</summary><p>Yes. Add your whole booth team, your worship leader, your planners and every volunteer. The price doesn’t change with the number of people.</p></details>
      <details class="rv"><summary>Can we start with one and add the other later?</summary><p>Yes. Switch to Both any time and the difference is settled on your next bill. Nothing you’ve made moves.</p></details>
      <details class="rv"><summary>What if we cancel?</summary><p>You keep everything until the end of the month you paid for. There’s no contract and no cancellation fee.</p></details>
      <details class="rv"><summary>How do we pay?</summary><p>By card, through Stripe. ChurchSavvy never sees your card number, and receipts are there whenever you need them.</p></details>
    </div>
  </div>
</section>
<section class="final" aria-labelledby="pf">
  <div class="wrap rv"><h2 id="pf" class="disp">Every Sunday, <span class="grad">ready.</span></h2>
    <div class="ctas"><a class="btn btn-p btn-lg" href="{_e(app)}?signup=1">Start your church {icon('arrow', 'ic-s')}</a></div></div>
</section>"""
    return _page(title="Pricing · ChurchSavvy", description="ChurchSavvy is $20 a month, ChurchSavvy Planning $15, or both for $29 — one price for your whole church.",
                 path="/pricing", base=base, active="pricing", body=body)


# ─── with Solutionist ────────────────────────────────────────────────


def render_solutionist(base: str = "") -> str:
    app = app_url()
    li = lambda items: "".join(f"<li>{icon('check', 'ic-s')}<span>{_e(t)}</span></li>" for t in items)  # noqa: E731
    arrows = f'<div class="linkx" aria-hidden="true"><svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h18M7 8l-4 4 4 4M17 8l4 4-4 4"/></svg></div>'
    body = f"""
<section class="page-head" aria-labelledby="sh">
  <div class="wrap"><p class="eyebrow">ChurchSavvy + Solutionist</p><h1 id="sh" class="disp">ChurchSavvy runs Sunday. Solutionist runs the rest of the week.</h1>
    <p class="lede">Two products made to work as one. Start with either. Connect them and nothing moves — your songs, Sundays and teams stay right where they are.</p></div>
</section>
<section class="band" style="padding-top:20px" aria-label="What each does">
  <div class="wrap">
    <div class="mapx">
      <div class="col a rv"><p class="eyebrow">ChurchSavvy</p><h3>Sunday</h3><ul>{li(["The plan and the order of service", "Every screen, live from the booth", "The song library", "Who serves when"])}</ul></div>
      {arrows}
      <div class="col b rv"><p class="eyebrow">Shared</p><h3>One church</h3><ul>{li(["Your church’s name and look", "The people, added once", "Teams and their leaders", "The church calendar"])}</ul></div>
      {arrows}
      <div class="col c rv"><p class="eyebrow">Solutionist</p><h3>The rest of the week</h3><ul>{li(["The member app", "Giving", "Groups and classes", "Messages and care"])}</ul></div>
    </div>
  </div>
</section>
<section class="band band-alt" aria-labelledby="wh">
  <div class="wrap">
    <div class="head rv"><p class="eyebrow">When you connect</p><h2 id="wh" class="h2">Three things get easier.</h2></div>
    <div class="three">
      <article class="card pillar rv">{icon('bell')}<h3 class="h3">Asks reach phones</h3><p>Volunteers with the member app get asks as a notification. Everyone else still gets email.</p></article>
      <article class="card pillar rv">{icon('users')}<h3 class="h3">One list of people</h3><p>The members you care for and the people who serve are the same people. Add someone once.</p></article>
      <article class="card pillar rv">{icon('card')}<h3 class="h3">One bill</h3><p>Planning is included with Solutionist, and ChurchSavvy’s screens are $10 a month on the same plan.</p></article>
    </div>
  </div>
</section>
<section class="band" aria-labelledby="ch">
  <div class="wrap split">
    <div class="rv"><p class="eyebrow">Connecting</p><h2 id="ch" class="h2">Already on one? Add the other.</h2>
      <div class="steps">
        <div><b class="n">1</b><span>In ChurchSavvy, open <strong>Setup, Solutionist</strong>. In Solutionist, open <strong>Operate, Sunday</strong>.</span></div>
        <div><b class="n">2</b><span>Sign in and choose your church.</span></div>
        <div><b class="n">3</b><span>Check what’s shared, then <strong>Connect</strong>.</span></div>
      </div></div>
    <div class="card dlg rv" role="img" aria-label="The window that connects a church">
      <h4>Connect your church to Solutionist</h4><p class="muted">These are shared both ways:</p>
      <div class="sh"><div>{icon('check', 'ic-s')}Church name and look</div><div>{icon('check', 'ic-s')}The people on your teams</div><div>{icon('check', 'ic-s')}Sundays and who serves when</div></div>
      <p class="muted" style="font-size:14px">Disconnect any time. Nothing made in ChurchSavvy is removed.</p>
    </div>
  </div>
</section>
<section class="band band-alt" aria-labelledby="sfaq">
  <div class="wrap">
    <div class="head center rv"><h2 id="sfaq" class="h2">Good to know.</h2></div>
    <div class="faq">
      <details class="rv"><summary>Do we need Solutionist?</summary><p>No. ChurchSavvy stands on its own, with its own sign-in and its own price.</p></details>
      <details class="rv"><summary>Who sees what?</summary><p>Each product keeps its own roles, and a volunteer never needs an account in either.</p></details>
      <details class="rv"><summary>What if we disconnect?</summary><p>Both keep working, and your songs, Sundays and teams stay in ChurchSavvy.</p></details>
    </div>
  </div>
</section>
<section class="final" aria-labelledby="sf">
  <div class="wrap rv"><h2 id="sf" class="disp">Every Sunday, <span class="grad">ready.</span></h2>
    <div class="ctas"><a class="btn btn-p btn-lg" href="{_e(app)}?signup=1">Start your church {icon('arrow', 'ic-s')}</a><a class="btn btn-q btn-lg" href="https://mysolutionist.app">Visit Solutionist</a></div></div>
</section>"""
    return _page(title="ChurchSavvy and Solutionist", description="ChurchSavvy runs Sunday; Solutionist runs the rest of the week. Two products made to work as one.",
                 path="/solutionist", base=base, active="solutionist", body=body)


# ─── serving it ──────────────────────────────────────────────────────

PAGES = {"": render_home, "pricing": render_pricing, "solutionist": render_solutionist}


def _not_found(base: str) -> str:
    body = f"""<section class="final"><div class="wrap"><img src="/churchsavvy-assets/logo-mark.webp" alt="" width="142" height="84">
<h1 class="disp" style="font-size:clamp(40px,6vw,64px)">That page isn’t here.</h1>
<div class="ctas"><a class="btn btn-p btn-lg" href="{_e(_href(base, ''))}">Go to ChurchSavvy</a></div></div></section>"""
    return _page(title="Not found · ChurchSavvy", description="ChurchSavvy", path="/", base=base, active="", body=body)


def respond(path: str, base: str = "") -> Response:
    """churchsavvy.app's answer for one path."""
    p = (path or "/").split("?")[0].rstrip("/") or "/"
    if p == "/robots.txt":
        return PlainTextResponse(f"User-agent: *\nAllow: /\nSitemap: {CANONICAL}/sitemap.xml\n")
    if p == "/sitemap.xml":
        urls = "".join(f"<url><loc>{CANONICAL}/{k}</loc></url>" if k else f"<url><loc>{CANONICAL}/</loc></url>" for k in PAGES)
        return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
                        media_type="application/xml")
    if p == "/favicon.ico":
        return asset("icon-64.png")
    if p.startswith("/churchsavvy-assets/"):
        return asset(p.rsplit("/", 1)[-1])
    page = p.lstrip("/")
    render = PAGES.get(page)
    if render is None:
        return HTMLResponse(_not_found(base), status_code=404)
    return HTMLResponse(render(base), headers=_PAGE_CACHE)


def asset(name: str) -> Response:
    if not _ASSET_RE.match(name or ""):
        raise HTTPException(404, "Not found")
    fp = _ASSETS / name
    try:
        fp.resolve().relative_to(_ASSETS.resolve())
    except ValueError:
        raise HTTPException(404, "Not found")
    if not fp.is_file():
        raise HTTPException(404, "Not found")
    kind = "image/webp" if name.endswith(".webp") else "image/png"
    return FileResponse(str(fp), media_type=kind, headers=_CACHE)


@router.get("/churchsavvy-assets/{name}", include_in_schema=False)
def churchsavvy_asset(name: str):
    return asset(name)


def _preview_host(request: Request) -> bool:
    """The pages before churchsavvy.app is ours: the platform's own hosts
    only, never a church's site."""
    import public_site
    host = public_site.public_host(request)
    return is_host(host) or host in ("mysolutionist.app", "www.mysolutionist.app") or public_site._is_api_host(host)


@router.get("/churchsavvy/site", include_in_schema=False)
def preview_home(request: Request):
    if not _preview_host(request):
        raise HTTPException(404, "Not found")
    return respond("/", base=PREVIEW_BASE)


@router.get("/churchsavvy/site/{page}", include_in_schema=False)
def preview_page(request: Request, page: str):
    if not _preview_host(request):
        raise HTTPException(404, "Not found")
    return respond(f"/{page}", base=PREVIEW_BASE)
