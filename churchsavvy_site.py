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
# The home page is its own design (canvas FDAysirAGzcrWosHuzijSA, version 3;
# Kevin 2026-10-25): a cutaway of a church from above, a booth people can try
# in the page, and what's in the booth. Its markup, stylesheet, script and
# drawings live in churchsavvy_site/ and are filled here per request; the
# pricing and Solutionist pages keep the stylesheet below.
#
# Rules it keeps: the logo's blue-to-violet only on the logo and the
# wordmark's word "ready."; no invented numbers, reviews or customers;
# Scripture is KJV; never a song's words, in the booth you can try too (it
# puts up Scripture or the visitor's own words, as text, never markup).
from __future__ import annotations

import functools
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
_HOME_DIR = pathlib.Path(__file__).resolve().parent / "churchsavvy_site"
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
/* buttons in a row */
.ctas{display:flex;gap:12px;flex-wrap:wrap;margin-top:32px}
/* bands */
.band{padding:104px 0}.band-alt{background:var(--ground)}
.head{max-width:720px}.head .h2{margin-top:12px}.head .lede{margin-top:16px}
.head.center{margin:0 auto;text-align:center}
.three{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px;margin-top:52px}
.pillar{padding:28px;display:flex;flex-direction:column;gap:12px}
.pillar .n{font-family:var(--display);font-weight:800;font-size:13px;letter-spacing:.08em;color:var(--blue)}
.pillar > p{color:var(--ink2);font-size:15.5px}
/* two columns */
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:64px;align-items:center}
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


_FONTS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Manrope:wght@600;700;800&display=swap"
_HOME_FONTS = ("https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600"
               "&family=Manrope:wght@600;700;800&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600&display=swap")


def _page(*, title: str, description: str, path: str, base: str, active: str, body: str,
          css: str = CSS, fonts: str = _FONTS, chrome: bool = True, script: str = _JS) -> str:
    """One page. `chrome=False` when the body brings its own bar and footer
    (the home page)."""
    canonical = CANONICAL + (path if path != "/" else "/")
    inner = f"{_nav(base, active)}\n<main id=\"main\">\n{body}\n</main>\n{_footer(base)}" if chrome else body
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
<meta property="og:image" content="{CANONICAL}/churchsavvy-assets/og-2.png">
<meta name="twitter:card" content="summary_large_image">
<meta name="theme-color" content="#0A1033">
<link rel="icon" type="image/png" sizes="64x64" href="/churchsavvy-assets/icon-64.png">
<link rel="icon" type="image/png" sizes="192x192" href="/churchsavvy-assets/icon-192.png">
<link rel="apple-touch-icon" href="/churchsavvy-assets/icon-192.png">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{_e(fonts)}">
<style>{css}</style>
</head>
<body>
{inner}
{script}
</body>
</html>"""


# ─── the home page ───────────────────────────────────────────────────
# churchsavvy_site/home.html is the body; {{APP}} {{HOME}} {{PRICING}}
# {{SOLUTIONIST}} are filled per request (escaped), the {{ART_*}} drawings
# once, from their files (made by scripts/churchsavvy_art.py).

_HOME_TOKEN = re.compile(r"\{\{(APP|HOME|PRICING|SOLUTIONIST)\}\}")


@functools.lru_cache(maxsize=1)
def _home_files() -> tuple[str, str, str]:
    read = lambda name: (_HOME_DIR / name).read_text(encoding="utf-8")  # noqa: E731
    body = read("home.html")
    for token, name in (("ART_CHURCH", "art-church.svg"), ("ART_STAGE_BACK", "art-stage-back.svg"),
                        ("ART_STAGE_FRONT", "art-stage-front.svg")):
        body = body.replace("{{" + token + "}}", read(name).strip())
    return body, read("home.css"), "<script>\n" + read("home.js") + "</script>"


def render_home(base: str = "") -> str:
    body, css, script = _home_files()
    fills = {"APP": app_url(), "HOME": _href(base, ""), "PRICING": _href(base, "pricing"),
             "SOLUTIONIST": _href(base, "solutionist")}
    body = _HOME_TOKEN.sub(lambda m: _e(fills[m.group(1)]), body)
    return _page(title="ChurchSavvy · Every service, ready.",
                 description="Plan the service, put it on every screen in the building, and get the right people serving: "
                             "church presentation and planning in one place. Try the booth in your browser.",
                 path="/", base=base, active="home", body=body, css=css, fonts=_HOME_FONTS, chrome=False, script=script)


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
  <div class="wrap rv"><h2 id="pf" class="disp">Every service, <span class="grad">ready.</span></h2>
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
  <div class="wrap rv"><h2 id="sf" class="disp">Every service, <span class="grad">ready.</span></h2>
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
