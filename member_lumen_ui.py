"""member_lumen_ui.py — the member app's new look ("Lumen"): its stylesheet and
its shared pieces.

Kevin approved the "clean Lumen" mock on 2026-11-18 (version 29, accent level
2): a white page with no glow at the top, serif display headings with one
italic word, thin dividers, the church's colour on buttons, the current tab
and accents with level 2's soft tints behind key blocks, full-bleed photos,
the ivory verse card and the flame for prayer. Who sees it is member_lumen.py
(MEMBER_LUMEN).

THE SHEET. One more shared file beside /my/app.<hash>.css: /my/lumen.<hash>.css
(member_app_ui.SHEETS), linked after the app's sheet only on a Lumen page.
Every rule sits under body.lm, so the file draws nothing on any other page.
It reads the colours the app's sheet already defines from the church's
palette (--acc, --acc-fill, --on-acc, --bg, --s1, the family inks), worked
out on the white base (member_app_ui.base_of).

DARK. The member's look (member_lumen_look: Light, Dark, Same as my phone)
turns the page dark with one layer over the white one: the near-black of
the approved "Look 4: black base" board (#0A0A0B, its surfaces, its warm
whites), the church's colour lifted to its "lit" shade for words (readable
on black, then lightened the way the reader does), the family inks their
dark shades, hairlines and tints remade for a dark page. Written once
(DARK_TOKENS, and each block's own dark rules) and used twice by dark():
under body.lm.lm-dark, and under body.lm.lm-auto inside a
prefers-color-scheme: dark query. The Bible reader keeps its warm night
and Watch its cinema black, each a narrower rule over this one.

THE PIECES. The top bar of a main tab (logo and name; the bell, the message
bubble with the unread count, the profile picture: Look 5.1's order; Watch,
Connect and the Bible draw their own top there instead, as the mock does), a
pushed page's plain back bar, the tab bar (Look 5.1: Home · Watch · Connect ·
Bible · Give, flat, with a hairline on top), and the small blocks the pages
are made of.

Pure functions, no I/O.
"""
from __future__ import annotations

import re
from html import escape
from string import Template
from typing import Any, Dict, Optional, Tuple

# The tabs, in Lumen's order (Look 5.1, Kevin 2026-11-20: Home · Watch ·
# Connect · Bible · Give). Messages is not a tab: it opens from the bubble.
TABS = (
    ("home", "/my", "Home"),
    ("watch", "/my/sermons", "Watch"),
    ("connect", "/my/connect", "Connect"),
    ("bible", "/my/bible", "Bible"),
    ("give", "/my/give", "Give"),
)
# The pages that are a main tab: they get the full top bar. Every other page
# is pushed, with a back bar.
MAIN = ("home", "watch", "bible", "connect", "give")
# Which tab a page sits under (the old map, with Messages, Me and the alerts
# under none: they open from the top bar, over whatever tab you were on).
TAB_OF = {"home": "home", "watch": "watch", "sermons": "watch", "live": "watch", "bible": "bible",
          "give": "give", "connect": "connect", "groups": "connect", "classes": "connect",
          "directory": "connect", "events": "connect", "prayer": "connect", "news": "connect",
          "ask": "connect", "lead": "lead", "board": "board"}

# Lumen's own icons (the rest are member_app_ui.ICONS).
ICONS = {
    "flame": '<path d="M12 3c2.2 3 5 5.2 5 9.2A5 5 0 0 1 7 12.2c0-2.1 1-3.6 2.2-4.7.4 1.9 1.4 3 2.8 3.2-.9-2.1-.8-5 0-7.7z"/>',
    "cap": '<path d="m2 9 10-5 10 5-10 5z"/><path d="M6 11v5c3 2 9 2 12 0v-5"/>',
    "drop": '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    "megaphone": '<path d="M3 11v2a1 1 0 0 0 1 1h3l6 4V6L7 10H4a1 1 0 0 0-1 1z"/><path d="M17 9a4 4 0 0 1 0 6"/>',
    "people": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/>'
              '<path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',
    "person": '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
    "tv": '<rect x="2.5" y="4" width="19" height="13" rx="3"/><path d="m10.5 8.3 4 2.2-4 2.2z"/><path d="M8 21h8"/>',
    "playfill": '<path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/>',
    # Look 5.1 (Home's doors, the composer, the moments' viewer)
    "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "hands": '<path d="M11.4 4.6 9 10.2v4.6l-3.2 3.1 2.6 2.6L12 17V5.3c0-.4-.3-.7-.6-.7z"/>'
             '<path d="M12.6 4.6 15 10.2v4.6l3.2 3.1-2.6 2.6L12 17"/>',
    "hand": '<path d="M18 11V6a2 2 0 0 0-4 0"/><path d="M14 10V4a2 2 0 0 0-4 0v2"/><path d="M10 10.5V6a2 2 0 0 0-4 0v8"/>'
            '<path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-5.99-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15"/>',
    "smile": '<circle cx="12" cy="12" r="9.5"/><path d="M8 14s1.5 2 4 2 4-2 4-2"/><path d="M9 9h.01"/><path d="M15 9h.01"/>',
}


def ic(name: str, size: int = 22) -> str:
    import member_app_ui as ui
    paths = ICONS.get(name) or ui.ICONS[name]
    return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
            f'focusable="false">{paths}</svg>')


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def dark(css: str) -> str:
    """Rules for the dark look, written under body.lm.lm-dark, and the same
    rules for Same as my phone (body.lm.lm-auto) while the phone is dark."""
    return css + "@media (prefers-color-scheme:dark){" + css.replace(".lm-dark", ".lm-auto") + "}\n"


# The dark layer's colours (member_lumen_look). The page's own names, so
# every part of every page (the new look's and today's pieces inside it)
# turns with it; the church's colour as words is its lit shade (4.5:1 on
# black: member_app_ui.palette) lightened a little more; its button colour
# stays the church's unless that is too deep for near-black (then the page
# carries a lifted one: member_lumen_look.dark_tokens); the tints are the
# church's colour over near-black, stronger than on white so they still
# read as a surface.
DARK_TOKENS = (
    "--bg:#0A0A0B;--s1:#161618;--s2:#202023;--s3:#2E2E32;--line:rgba(255,255,255,.1);"
    "--fg:#F4F2EE;--fg2:#AAA7A1;--fg3:#8F8C86;"
    "--acc:var(--acc-lit);--accent:var(--acc);--focus:var(--acc);"
    "--bar:rgba(10,10,11,.82);--hair:rgba(244,242,238,.1);"
    "--surface:var(--bg);--input-surface:var(--s1);--text-primary:var(--fg);--text-secondary:var(--fg2);"
    "--text-muted:var(--fg3);--border:var(--line);--mb-surface:var(--s1);--mb-surface-2:var(--s2);"
    "--mb-line:var(--line);--error:#FF6B5E;"
    "--gold-ink:var(--gold-lit);--teal-ink:var(--teal-lit);--violet-ink:var(--violet-lit);--coral-ink:var(--coral-lit);"
    "--gold-deep:var(--gold-night);--teal-deep:var(--teal-night);--violet-deep:var(--violet-night);"
    "--coral-deep:var(--coral-night);--acc-deep:var(--acc-night);"
    "--lm-line:rgba(255,255,255,.1);--lm-shadow:rgba(0,0,0,.6);--lm-paper:#F1E8D4;--lm-raise:var(--s3);"
    "--lm-mint:#12332B;--lm-mint-ink:#8EDBC9;--lm-live:#FF6B6B;"
    "color-scheme:dark;"
)
DARK_MIX = (
    "--acc:color-mix(in oklab,var(--acc-lit) 62%,#fff);"
    "--acc-soft:color-mix(in srgb,var(--acc-fill) 18%,transparent);--mb-soft:var(--acc-soft);"
    "--mb-soft-line:color-mix(in srgb,var(--acc-fill) 40%,transparent);"
    "--lm-tint:color-mix(in srgb,var(--acc-fill) 12%,var(--bg));--lm-tint-6:color-mix(in srgb,var(--acc-fill) 8%,var(--bg));"
    "--lm-tint-10:color-mix(in srgb,var(--acc-fill) 16%,var(--bg));--lm-tint-12:color-mix(in srgb,var(--acc-fill) 26%,var(--bg));"
    "--lm-gold-tint:color-mix(in srgb,var(--gold) 14%,var(--bg));--lm-ring:color-mix(in srgb,var(--acc-fill) 50%,transparent);"
    "--lm-mint:color-mix(in srgb,var(--teal) 22%,var(--bg));"
)


def italic_last(text: Any) -> str:
    """A display heading with one italic accent word, the last one:
    "Sunday Worship" → Sunday <em>Worship</em>. Escaped here."""
    words = str(text or "").split()
    if not words:
        return ""
    if len(words) == 1:
        return f"<em>{_e(words[0])}</em>"
    return f'{_e(" ".join(words[:-1]))} <em>{_e(words[-1])}</em>'


def mast(eyebrow: str, title_html: str, sub: str = "", *, tag: str = "h1", crest: bool = False) -> str:
    """A page's masthead: a small eyebrow, the serif heading (trusted
    markup, one <em> word) and a line under it."""
    eb = (f'<p class="lm-eyebrow lm-crest"><i>{ic("cap", 15)}</i>{_e(eyebrow)}</p>' if crest else
          f'<p class="lm-eyebrow">{_e(eyebrow)}</p>' if eyebrow else "")
    return (f'<header class="lm-mast">{eb}<{tag} class="lm-disp">{title_html}</{tag}>'
            f'{f"<p class=lm-sub>{_e(sub)}</p>" if sub else ""}</header>')


def section(title: str, link: str = "", label: str = "", hid: str = "", badge: Optional[int] = None) -> str:
    """The one section header: a bold title, and a link in the church's colour."""
    ida = f' id="{_e(hid)}"' if hid else ""
    chip = f'<span class="lm-chip">{int(badge)}</span>' if badge else ""
    more = f'<a class="lm-more" href="{_e(link)}">{_e(label)}{chip}</a>' if link else ""
    return f'<div class="lm-sec"><h2 class="lm-h2"{ida}>{_e(title)}</h2>{more}</div>'


def row(href: str, icon_html: str, title: str, sub: str = "", *, cls: str = "lm-wrow", k: str = "",
        extra: str = "") -> str:
    """One row: an icon or date on the left, a bold line and a quiet one, a
    chevron. `icon_html` and `extra` are trusted markup."""
    style = f' style="--k:{k}"' if k else ""
    return (f'<a class="{cls}" href="{_e(href)}"{style}>{icon_html}<span class="lm-wt"><b>{_e(title)}</b>'
            f'{f"<span>{_e(sub)}</span>" if sub else ""}{extra}</span>{ic("chevron", 18).replace("lm-ic", "lm-ic lm-chev")}</a>')


def round_icon(name: str, k: str = "var(--acc)") -> str:
    return f'<span class="lm-aic" style="--k:{k}">{ic(name, 18)}</span>'


def date_box(d, k: str = "") -> str:
    """The calendar date on a row: the weekday small in coral, the day in serif."""
    style = f' style="color:{k}"' if k else ""
    return (f'<span class="lm-wdate" aria-hidden="true"><small{style}>{d.strftime("%a")}</small>'
            f'<b>{d.day}</b></span>')


# ─── the bars ────────────────────────────────────────────────────────


def brand(name: str, logo: str) -> str:
    """The church at the top left: its logo (or its initials on its colour)
    in a circle, and its name."""
    import member_app_ui as ui
    mark = (f'<img src="{_e(logo)}" alt="">' if logo else _e(ui.initials(name)))
    return (f'<a class="mb-brand lm-brand" href="/my"><span class="lm-logo{" has-img" if logo else ""}" aria-hidden="true">'
            f'{mark}</span><span class="lm-name">{_e(name)}</span></a>')


def bubble(unread: Optional[int]) -> str:
    """The message bubble, top right: the way to Messages, with how many are
    unread (member_portal_threads' count, already read for the page)."""
    n = int(unread or 0)
    said = f"Messages, {n} new" if n else "Messages"
    cnt = f'<span class="lm-cnt">{n if n < 100 else "99+"}</span>' if n else ""
    return f'<a class="lm-icb mp-noprint" href="/my/messages" aria-label="{said}">{ic("chat")}{cnt}</a>'


def bell(dot: bool) -> str:
    """The bell, top right: the member's alerts (/my/notifications); a dot
    while something there is new (member_lumen.bell_dot)."""
    said = "Alerts, something new" if dot else "Alerts"
    d = '<span class="lm-bdot"></span>' if dot else ""
    return f'<a class="lm-icb mp-noprint" href="/my/notifications" aria-label="{said}">{ic("bell")}{d}</a>'


def nav(active: Optional[str], *, lead: bool = False, board: bool = False, serve: bool = False,
        side: Tuple[str, str] = ("", "")) -> str:
    """The tab bar (Look 5.1): Home · Watch · Connect · Bible · Give, and a
    leader's Serve (or Lead) tab or a board member's Board tab last, as
    today. A flat bar the width of the phone with a hairline on top, an
    icon and a label each; the current tab in the church's colour, its icon
    a little heavier. Keeps the class names the early loading and the
    cross-fade look for (.mb-nav, .mb-tab: member_app_ui.EARLY_RULES,
    MOTION_CSS), and the computer's sidebar parts (`side`)."""
    import member_app_ui as ui
    paths_of = {t[0]: t[3] for t in ui.TABS}
    tabs = [(k, href, label, paths_of[k]) for k, href, label in TABS]
    if lead:
        t = ui.SERVE_TAB if serve else ui.LEAD_TAB
        tabs.append((t[0], t[1], t[2], t[3]))
    elif board:
        t = ui.BOARD_TAB
        tabs.append((t[0], t[1], t[2], t[3]))
    cur = TAB_OF.get(active or "", "")
    if cur == "board" and lead:
        cur = "lead"
    items = []
    for key, href, label, paths in tabs:
        here = ' aria-current="page"' if key == cur else ""
        items.append(f'<a class="mb-tab" href="{href}"{here}><i class="mb-tab-p"><svg width="24" height="24" '
                     f'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" '
                     f'stroke-linejoin="round" aria-hidden="true" focusable="false">{paths}</svg></i><span>{label}</span></a>')
    return (f'<nav class="mb-nav lm-nav mp-noprint" aria-label="Main" style="--n:{len(tabs)}">'
            f'{side[0]}{"".join(items)}{side[1]}</nav>')


# The bar at the top turns solid as the page slides under it, and the page's
# title moves into it once the heading has scrolled away (member_app_ui's
# SCROLL_JS, reading Lumen's headings too). A back link marked data-back goes
# back in the browser's history when the page before was one of ours, so a
# screen opened from the top bar returns to the tab it was opened over.
SCROLL_JS = ("<script>(function(){var t=document.querySelector('.mb-top');if(!t)return;"
             "var h=document.querySelector('.lm-mast h1,.lm-hello h2,.mb-lt h1,.mb-hello');"
             "function f(){var y=window.scrollY;t.classList.toggle('is-solid',y>8);"
             "t.classList.toggle('is-titled',!!h&&h.getBoundingClientRect().bottom<70);}"
             "f();window.addEventListener('scroll',f,{passive:true});"
             "var b=document.querySelector('.mb-back[data-back]');"
             "if(b)b.addEventListener('click',function(e){try{var r=new URL(document.referrer);"
             "if(r.origin===location.origin&&r.pathname.indexOf('/my')===0&&history.length>1){e.preventDefault();history.back();}"
             "}catch(x){}});})();</script>")

# Home's greeting by the phone's own clock (the server can't know the
# member's time of day); without script it reads "Hi, Ana.".
GREETING_JS = ("<script>(function(){var e=document.querySelector('[data-first]');if(!e)return;"
               "var h=new Date().getHours(),g=h<12?'Good morning':(h<17?'Good afternoon':'Good evening');"
               "var em=document.createElement('em');em.textContent=e.getAttribute('data-first')+'.';"
               "e.textContent='';e.append(g+', ',em);})();</script>")


# ─── the sheet ───────────────────────────────────────────────────────
# Accent level 2 ("warm"): the church colour on the italic word, the labels,
# the shortcut icons, the tab line and the buttons, plus soft church-colour
# surfaces behind key blocks, unread chips and a thin rule under the top bar.
# The tints are color-mix over white; a browser without it gets the plain
# light gray surface instead.
_CSS = Template("""
/* member app, clean Lumen (member_lumen_ui) */
body.lm{--lm-paper:#F7F0E1;--lm-ink:#22190b;--lm-ink2:#6a5426;--lm-gold:var(--gold-ink);--lm-teal:var(--teal-ink);
  --lm-violet:var(--violet-ink);--lm-coral:var(--coral-ink);--lm-shadow:rgba(20,20,40,.12);--lm-line:rgba(12,12,20,.09);
  --lm-tint:var(--s1);--lm-tint-6:var(--s1);--lm-tint-10:var(--s1);--lm-tint-12:var(--s1);--lm-gold-tint:var(--s1);
  --lm-ring:var(--line);background:var(--bg);font-family:var(--mb-ui);}
@supports (background:color-mix(in srgb,red 50%,blue)){
  body.lm{--lm-tint:color-mix(in srgb,var(--acc-fill) 8%,var(--bg));--lm-tint-6:color-mix(in srgb,var(--acc-fill) 6%,var(--bg));
    --lm-tint-10:color-mix(in srgb,var(--acc-fill) 10%,var(--bg));--lm-tint-12:color-mix(in srgb,var(--acc-fill) 12%,var(--bg));
    --lm-gold-tint:color-mix(in srgb,var(--gold) 9%,var(--bg));--lm-ring:color-mix(in srgb,var(--acc-fill) 38%,transparent);}
}
.lm .lm-ic{display:block;flex:none;}
body.lm{--lm-raise:var(--bg);--lm-mint:#DCF0EA;--lm-mint-ink:#0b4a40;--lm-live:#c4162a;}

/* the top bar (Look 5.1): the church's mark and name; the bell, the bubble, you. The page's own colour, no rule under it */
.lm .mb-top{min-height:56px;max-width:600px;padding-top:calc(4px + env(safe-area-inset-top,0px));padding-bottom:4px;background:var(--bg);}
.lm .mb-top.is-solid{background:var(--bg);-webkit-backdrop-filter:none;backdrop-filter:none;}
.lm.lm-tab .mb-top.is-solid{box-shadow:0 1px 0 var(--lm-line);}
.lm-brand{gap:10px;}
.lm-logo{width:30px;height:30px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:var(--acc-fill);
  color:var(--on-acc);font:italic 600 13px/1 var(--mb-serif);letter-spacing:0;}
.lm-logo.has-img{background:#fff;box-shadow:inset 0 0 0 1px var(--lm-line);}
.lm-logo img{width:100%;height:100%;object-fit:contain;}
.lm-name{font:750 17px/1.1 var(--mb-ui);letter-spacing:-.012em;color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lm .mb-top-right{gap:4px;}
.lm.lm-tab .mb-top-right{gap:0;margin-right:-10px;}
.lm-icb{position:relative;width:44px;height:44px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--fg);text-decoration:none;}
.lm-cnt{position:absolute;top:5px;right:3px;min-width:18px;height:18px;padding:0 5px;border-radius:9px;background:var(--acc-fill);color:var(--on-acc);
  font:700 10.5px/18px var(--mb-ui);text-align:center;box-shadow:0 0 0 2px var(--bg);}
.lm-bdot{position:absolute;top:11px;right:12px;width:8px;height:8px;border-radius:50%;background:var(--acc-fill);box-shadow:0 0 0 2px var(--bg);}
.lm .mb-avatar{width:30px;height:30px;margin:0 7px;font-size:11px;font-weight:700;color:var(--fg2);background:var(--s2);box-shadow:none;}
.lm .mb-avatar.has-photo{box-shadow:inset 0 0 0 1px var(--lm-line);}
.lm .mb-avatar[aria-current]{box-shadow:0 0 0 2px var(--bg),0 0 0 3.5px var(--acc-fill);}
/* a pushed page: a plain back bar */
.lm.lm-push .mb-top{min-height:58px;}
.lm .mb-back{color:var(--acc);font:600 16px/1 var(--mb-ui);gap:2px;}
.lm .mb-top-t{font:650 15px/1.2 var(--mb-ui);}
/* a main tab keeps its logo and name at the top: no title slides in over them */
.lm.lm-tab .mb-top-t{display:none;}
/* a main tab with its own top in place of the church's bar (Look 5.1: Watch's and Connect's large title and its one
   button, the Bible's segmented control) */
.lm .mb-top.lm-own{min-height:60px;}
.lm .mb-top.lm-own h1{margin:0;font:800 30px/1 var(--mb-ui);letter-spacing:-.028em;color:var(--fg);}

/* the page */
.lm .mp-shell{padding:0 20px 40px;}
.lm .mp-shell.mb-has-nav{padding-bottom:calc(96px + env(safe-area-inset-bottom,0px));}
.lm .mp-foot{margin-top:44px;color:var(--fg3);}
/* today's pages under the new look: the big title in serif, its accent word in the church's colour */
.lm .mb-lt h1{font:400 40px/1.02 var(--mb-serif);letter-spacing:-.025em;}
.lm .mb-lt h1 em,.lm .mb-hello em{color:var(--acc);}
.lm .mb-sh h2{font-size:21px;font-weight:700;letter-spacing:-.02em;}
.lm .mb-sh a,.lm .mp-sect a{color:var(--acc);}
.lm .mp-go{background:var(--acc-fill);color:var(--on-acc);border-radius:999px;}
.lm .mp-card,.lm .mb-cards>li>a,.lm .mb-row,.lm .mb-pray{box-shadow:none;}

/* type */
.lm-mast{margin:16px 0 4px;}
.lm .mb-lt{margin-top:12px;}
.lm-eyebrow{margin:0;display:flex;align-items:center;gap:8px;font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--acc);}
.lm-eyebrow .lm-dot{width:7px;height:7px;border-radius:50%;background:var(--lm-coral);}
.lm-crest i{width:24px;height:24px;border-radius:50%;display:grid;place-items:center;background:var(--s1);color:var(--lm-gold);font-style:normal;}
.lm-disp{margin:10px 0 0;font:400 42px/1 var(--mb-serif);letter-spacing:-.025em;text-wrap:balance;color:var(--fg);}
.lm-disp em{font-style:italic;color:var(--acc);}
.lm-disp.s{font-size:34px;}
.lm-disp.m{font-size:38px;}
.lm-sub{margin:12px 0 0;font:400 15px/1.55 var(--mb-ui);color:var(--fg2);max-width:330px;}
.lm-meta{margin:8px 0 0;font:500 14.5px/1.4 var(--mb-ui);color:var(--fg2);}
.lm-sec{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:40px 0 14px;}
.lm-h2{margin:0;font:700 21px/1.2 var(--mb-ui);letter-spacing:-.02em;}
.lm-more{display:inline-flex;align-items:center;gap:6px;padding:6px 0;color:var(--acc);font:650 14px/1 var(--mb-ui);text-decoration:none;}
.lm-chip{display:inline-flex;align-items:center;justify-content:center;min-width:20px;height:20px;padding:0 6px;border-radius:10px;
  background:var(--lm-tint-12);color:var(--acc);font:700 11px/1 var(--mb-ui);}
.lm-kicker{display:block;font:650 11px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg3);}
.lm-new{display:inline-flex;align-items:center;height:18px;padding:0 6px;border-radius:5px;background:var(--fg);color:var(--bg);
  font:800 9.5px/1 var(--mb-ui);letter-spacing:.1em;vertical-align:middle;}

/* buttons */
.lm-btn{height:46px;padding:0 22px;border-radius:23px;border:0;background:var(--acc-fill);color:var(--on-acc);font:650 15px/1 var(--mb-ui);
  display:inline-flex;align-items:center;justify-content:center;gap:8px;text-decoration:none;cursor:pointer;white-space:nowrap;
  transition:transform .15s ease,background-color .25s,color .25s;}
.lm-btn:active{transform:scale(.97);}
.lm-btn.ghost{background:var(--s1);color:var(--fg);}
.lm-btn.sm{height:38px;padding:0 16px;font-size:13.5px;border-radius:19px;}
.lm-btn.going{background:transparent;color:var(--acc);box-shadow:inset 0 0 0 1.5px var(--acc-fill);}
.lm-btn.gold{background:var(--lm-gold);color:#fff;}
.lm-txtbtn{border:0;background:none;padding:8px 6px;color:var(--fg2);font:650 13.5px/1 var(--mb-ui);text-decoration:none;cursor:pointer;}
.lm form{margin:0;}

/* full-bleed photos */
.lm-bleed{position:relative;display:block;margin:0 -20px;overflow:hidden;background:var(--s2);}
.lm-bleed .mb-ph,.lm-bleed .mb-def{position:absolute;inset:0;width:100%;height:100%;border-radius:0;}
.lm-bleed img{display:block;width:100%;height:100%;object-fit:cover;}
.lm-hero{height:252px;}
.lm-livechip{position:absolute;left:14px;bottom:14px;z-index:2;display:inline-flex;align-items:center;gap:7px;height:30px;padding:0 12px;border-radius:15px;
  background:rgba(0,0,0,.55);color:#fff;font:650 12.5px/1 var(--mb-ui);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);}
.lm-dotlive{width:8px;height:8px;border-radius:50%;background:#ff4d5e;}
@media (prefers-reduced-motion:no-preference){.lm-dotlive{animation:lmpulse 1.6s infinite;}}
@keyframes lmpulse{0%{box-shadow:0 0 0 0 rgba(255,77,94,.55)}100%{box-shadow:0 0 0 10px rgba(255,77,94,0)}}

/* Home's lead: the next gathering on a soft church-colour surface */
.lm-lead{margin:0 -20px;padding:20px 20px 22px;background:var(--lm-tint);}
.lm-row2{display:flex;align-items:center;flex-wrap:wrap;gap:14px;margin-top:18px;}
.lm-count{display:inline-flex;align-items:center;gap:7px;font:600 13.5px/1 var(--mb-ui);color:var(--fg2);}
.lm-hello{margin-top:40px;}
.lm-hint{margin:8px 0 0;font:500 12.5px/1.35 var(--mb-ui);color:var(--fg3);}
.lm-list{border-top:1px solid var(--lm-line);}
.lm-wrow,.lm-pray,.lm-room{display:flex;align-items:center;gap:14px;width:100%;padding:14px 0;color:var(--fg);text-decoration:none;
  border-bottom:1px solid var(--lm-line);}
.lm-pray{border-top:1px solid var(--lm-line);}
.lm-wt{flex:1;min-width:0;}
.lm-wt b{display:block;font:650 16px/1.25 var(--mb-ui);}
.lm-wt>span{display:block;margin-top:3px;font:400 13.5px/1.35 var(--mb-ui);color:var(--fg2);}
.lm-wdate{width:54px;flex:none;}
.lm-wdate small{display:block;font:700 10.5px/1 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--lm-coral);}
.lm-wdate b{display:block;margin-top:4px;font:400 30px/1 var(--mb-serif);letter-spacing:-.03em;}
.lm-wtag{display:inline-flex;margin-top:6px;font:700 10px/1 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--lm-violet);}
.lm-chev{color:var(--fg3);}
.lm-aic{width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--k,var(--acc));background:var(--lm-tint);}
.lm-gmini{width:40px;height:40px;border-radius:12px;flex:none;display:grid;place-items:center;background:var(--lm-mint);color:var(--lm-mint-ink);
  font:italic 500 15px/1 var(--mb-serif);}

/* the check-in card on Sunday morning */
.lm-ck{margin:24px -20px 0;padding:18px 20px 20px;background:var(--lm-tint);}
.lm-ck .ck{margin:0;background:none;box-shadow:none;padding:0;}
.lm-ckt{display:block;margin-top:8px;font:650 17px/1.3 var(--mb-ui);}
.lm-ckm{display:block;margin-top:10px;font:400 12.5px/1.4 var(--mb-ui);color:var(--fg2);}
.lm-cards{display:flex;flex-direction:column;gap:12px;margin-top:24px;}
.lm-cards:empty{display:none;}

/* the ivory page: the verse */
.lm-page{display:block;position:relative;overflow:hidden;border-radius:20px;padding:24px 22px 20px;background:var(--lm-paper);color:var(--lm-ink);
  box-shadow:inset 0 0 0 1.5px var(--lm-ring);text-decoration:none;}
.lm-page .lbl{display:block;font:700 10.5px/1 var(--mb-ui);letter-spacing:.18em;text-transform:uppercase;color:#8A5A00;}
.lm-page q{display:block;margin:14px 0 18px;font:italic 400 24px/1.28 var(--mb-serif);letter-spacing:-.01em;quotes:none;color:var(--lm-ink);}
.lm-page q sup,.lm-page q .bb-vn{display:none;}
.lm-page .ref{display:flex;justify-content:space-between;align-items:center;gap:10px;font:600 12.5px/1 var(--mb-ui);color:var(--lm-ink2);}
.lm-page .ref a{color:var(--lm-ink2);text-decoration:none;}
.lm-prow{display:flex;align-items:center;gap:14px;width:100%;padding:16px 0;color:var(--fg);border-bottom:1px solid var(--lm-line);text-decoration:none;}
.lm-prow>a{display:flex;align-items:center;gap:14px;flex:1;min-width:0;color:inherit;text-decoration:none;}
.lm-prow b{display:block;margin-top:6px;font:650 15.5px/1.25 var(--mb-ui);}
.lm-prow .m{display:block;margin-top:3px;font:400 13px/1.35 var(--mb-ui);color:var(--fg2);}
.lm-ring{position:relative;width:44px;height:44px;flex:none;}
.lm-ring svg{width:44px;height:44px;transform:rotate(-90deg);}
.lm-ring b{position:absolute;inset:0;display:grid;place-items:center;margin:0;font:700 13px/1 var(--mb-ui);}
.lm-circle{width:36px;height:36px;border-radius:50%;border:1.5px solid var(--lm-line);display:grid;place-items:center;flex:none;background:none;
  color:var(--fg3);cursor:pointer;padding:0;}
.lm-circle.done{background:var(--gold);border-color:var(--gold);color:#fff;}
.lm-today-more>*{margin-top:10px;}

/* tiles: a photo or the church's art, a bold title under it */
.lm-tile{display:block;color:var(--fg);text-decoration:none;}
.lm-tile .img{position:relative;display:block;width:100%;height:196px;overflow:hidden;border-radius:14px;background:var(--s2);}
.lm-tile .img>span:not(.lm-playdot){position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm-tile .img img{display:block;width:100%;height:100%;object-fit:cover;}
.lm-tile .tt{display:block;margin-top:12px;font:700 18px/1.25 var(--mb-ui);letter-spacing:-.015em;}
.lm-tile .tm{display:block;margin-top:4px;font:400 13.5px/1.35 var(--mb-ui);color:var(--fg2);}
.lm-playdot{position:absolute;right:12px;bottom:12px;z-index:2;width:40px;height:40px;border-radius:50%;background:#fff;color:#000;
  display:grid;place-items:center;box-shadow:0 4px 14px rgba(0,0,0,.18);}

/* Connect */
.lm-gart{position:relative;display:block;height:150px;border-radius:14px;overflow:hidden;background:var(--lm-mint);color:var(--lm-mint-ink);}
.lm-gart>span{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm-gart b{position:absolute;left:14px;right:14px;bottom:12px;z-index:1;font:italic 400 30px/1 var(--mb-serif);letter-spacing:-.015em;}
.lm-gart.has-ph b{color:#fff;text-shadow:0 1px 12px rgba(0,0,0,.35);}
.lm-cblock{display:flex;gap:12px;align-items:flex-start;padding:16px 0;border-top:1px solid var(--lm-line);border-bottom:1px solid var(--lm-line);}
.lm-crow{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:12px;}
.lm-acad{display:block;padding:20px;border-radius:18px;background:var(--lm-gold-tint);color:var(--fg);text-decoration:none;}
.lm-acad .lm-eyebrow{color:var(--lm-gold);}
.lm-acadt{display:block;margin-top:12px;font:400 26px/1.1 var(--mb-serif);letter-spacing:-.015em;}
.lm-acadt em{font-style:italic;color:var(--lm-gold);}
.lm-acadm{display:block;margin-top:10px;font:500 13px/1.35 var(--mb-ui);color:var(--fg2);}
.lm-pb{display:block;height:4px;margin-top:14px;border-radius:2px;background:var(--s2);overflow:hidden;}
.lm-pb i{display:block;height:100%;border-radius:2px;background:var(--gold);}
.lm-newslot{margin-bottom:10px;}
.lm-newslot:empty{display:none;}
.lm-rail{display:flex;gap:12px;overflow-x:auto;margin:0 -20px;padding:2px 20px 6px;scroll-snap-type:x mandatory;scrollbar-width:none;}
.lm-rail::-webkit-scrollbar{display:none;}
.lm-rail>*{flex:none;scroll-snap-align:start;}
.lm-gcard{width:200px;color:var(--fg);text-decoration:none;}
.lm-gcard .lm-gart{height:120px;}
.lm-gcard .lm-gart b{font-size:26px;}
.lm-gcard h3{margin:12px 0 3px;font:700 16px/1.2 var(--mb-ui);}
.lm-gcard p{margin:0 0 12px;font:400 13px/1.3 var(--mb-ui);color:var(--fg2);}
.lm-rooms{margin-top:34px;border-top:1px solid var(--lm-line);}
.lm-room .lm-aic{color:var(--k,var(--acc));}

/* the tab bar (Look 5.1): flat, the width of the phone, a hairline on top, solid (nothing shows through it, in
   any engine); an icon and a label each, the tab you're on in the church's colour with a heavier icon */
.lm .mb-nav.lm-nav{grid-template-columns:repeat(var(--n),minmax(0,1fr));left:0;right:0;bottom:0;width:auto;max-width:none;margin:0;
  border:0;border-top:1px solid var(--lm-line);border-radius:0;padding:4px 4px max(env(safe-area-inset-bottom,0px),6px);
  background:var(--bg);-webkit-backdrop-filter:none;backdrop-filter:none;box-shadow:none;}
.lm .lm-nav .mb-tab{min-height:52px;justify-content:center;gap:3px;padding-top:0;border-radius:0;color:var(--fg3);
  font:600 11px/1 var(--mb-ui);letter-spacing:0;transition:color .25s;}
.lm .lm-nav .mb-tab[aria-current],.lm .lm-nav .mb-tab[aria-current][data-hue]{color:var(--acc);}
.lm .lm-nav .mb-tab[aria-current] svg{stroke-width:2.1;}
.lm .lm-nav .mb-tab-p,.lm .lm-nav .mb-tab[aria-current] .mb-tab-p{width:auto;height:auto;background:none;}
@media (min-width:1100px){
  .lm .mb-nav.lm-nav{top:0;bottom:0;left:0;right:auto;width:92px;display:flex;flex-direction:column;justify-content:center;align-items:center;
    gap:6px;padding:24px 8px;border-top:0;box-shadow:1px 0 0 var(--lm-line);}
  .lm .lm-nav .mb-tab{width:76px;min-height:60px;border-radius:16px;}
  .lm .lm-nav .mb-tab[aria-current]{background:var(--lm-tint);}
}
@media (min-width:1200px){
  .lm .mb-nav.lm-nav{width:252px;align-items:stretch;justify-content:flex-start;gap:2px;padding:22px 14px 16px;}
  .lm .lm-nav .mb-tab{flex-direction:row;width:auto;min-height:46px;justify-content:flex-start;gap:12px;padding:0 10px 0 6px;font-size:15px;}
}
@media (prefers-reduced-motion:no-preference){
  .lm-wrow,.lm-pray,.lm-room,.lm-tile,.lm-acad,.lm-page,.lm-gcard{transition:transform .15s ease;}
  .lm-wrow:active,.lm-pray:active,.lm-room:active,.lm-tile:active,.lm-acad:active,.lm-page:active,.lm-gcard:active{transform:scale(.985);}
}
.lm-icb:focus-visible,.lm-btn:focus-visible,.lm-wrow:focus-visible,.lm-pray:focus-visible,.lm-room:focus-visible,.lm-tile:focus-visible,
.lm-acad:focus-visible,.lm-page:focus-visible,.lm-gcard:focus-visible,.lm-more:focus-visible,.lm-circle:focus-visible,.lm-brand:focus-visible
{outline:2px solid var(--acc);outline-offset:2px;}
""" + "\n/* the dark look (member_lumen_look): one layer over the white page */\n" + dark(
    "body.lm.lm-dark{" + DARK_TOKENS + "}"
    "@supports (background:color-mix(in srgb,red 50%,blue)){body.lm.lm-dark{" + DARK_MIX + "}}"
    "html:has(>body.lm.lm-dark){background:#0A0A0B;color-scheme:dark;}"
    # the reader's warm night (member_lumen_bible) at the page's edge too
    "html:has(>body.lm.lm-dark .lm-read),html:has(>body.lm.lm-dark .lm-dd){background:#100E0B;}"
    # a gold button keeps dark words on the lighter gold
    "body.lm.lm-dark .lm-btn.gold{color:#1A1205;}"
    # a white logo plate and the photo's play dot stay white; the plain page's picture behind a photo goes dark
    "body.lm.lm-dark .lm-logo.has-img{box-shadow:inset 0 0 0 1px rgba(255,255,255,.14);}"
    "body.lm.lm-dark .lm-gart.has-ph b{text-shadow:0 1px 12px rgba(0,0,0,.5);}"
))


def templates() -> Tuple[Template, ...]:
    """The sheet's parts, in order: the foundation's rules, then each page's
    own block (member_lumen_bible.CSS: the Bible, its reader and plans;
    member_lumen_classes.CSS: Classes; member_lumen_give.CSS: Give and Live;
    member_lumen_people.CSS_PEOPLE: Messages and the people pages;
    member_lumen_motion.CSS: how it all moves, and Live as a cinema;
    member_lumen_moments.CSS: the moments in Prayer, Give and Messages; member_lumen_feed.CSS: Home's feed and
    the comments under each post; member_lumen_home.CSS: the top of Home, Look 5.1;
    member_lumen_devotional.CSS: the devotional on the Bible tab and its
    day; member_lumen_plans.CSS: the Bible tab's Plans and a plan's page; member_lumen_plan_day.CSS: the day in steps; member_pastor.CSS: Meet the pastor; member_lumen_connect.CSS: Connect and a group's page, Look 5.1;
    member_lumen_watch.CSS: Watch, a series and a message, Look 5.1; member_lumen_stories.CSS: Home's moments
    and their viewer; member_moments.CSS: a leader's own moment and its composer; member_lumen_share.CSS: the share sheet; member_mini.CSS: the mini player), and
    last the type (member_lumen_fonts: the faces and the church's pairing, which set every block's fonts).
    member_app_ui.sheet("lumen") serves them as one file."""
    import member_lumen_bible
    import member_lumen_classes
    import member_lumen_connect
    import member_lumen_devotional
    import member_lumen_feed
    import member_lumen_fonts
    import member_lumen_give
    import member_lumen_home
    import member_lumen_moments
    import member_lumen_motion
    import member_lumen_people
    import member_lumen_plan_day
    import member_lumen_plans
    import member_lumen_share
    import member_lumen_stories
    import member_lumen_watch
    import member_mini
    import member_moments
    import member_pastor
    return (_CSS, Template(member_lumen_bible.CSS), Template(member_lumen_classes.CSS), member_lumen_give.CSS,
            member_lumen_people.CSS_PEOPLE, member_lumen_motion.CSS, member_lumen_moments.CSS, member_lumen_feed.CSS,
            member_lumen_home.CSS, Template(member_lumen_devotional.CSS), Template(member_lumen_plans.CSS),
            Template(member_lumen_plan_day.CSS), member_pastor.CSS, member_lumen_connect.CSS,
            member_lumen_watch.CSS, member_lumen_stories.CSS, Template(member_moments.CSS), member_lumen_share.CSS,
            member_mini.CSS,
            member_lumen_fonts.template())


def css() -> str:
    """The sheet's text (member_app_ui.sheet("lumen") serves it as a file)."""
    return "".join(t.template for t in templates())
