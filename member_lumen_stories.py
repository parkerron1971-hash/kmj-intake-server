"""member_lumen_stories.py — the moments at the top of the member app's new
Home ("Look 5.1"), and the full-screen viewer they open.

Kevin, 2026-11-20, on the Look 5.1 mock: "this is awesome. much better
design. lets build this including the new still to build!" The mock opens
Home with a row of circles, as a phone's stories do: the pastor, Sunday,
the member's groups, the church's events. (Not member_lumen_moments: those
are the small moves that answer a tap in Prayer, Give and Messages.)

WHAT A MOMENT IS. Only something the church's own records hold, built by
member_portal_lumen.render_home from what Home already reads:
  - a word from the pastor: today's day of the devotional the member is on
    (member_portal_devotionals' pick), else the newest post in the last
    three days by someone in a pastoral role (church_news' own "pastor"
    flag on Home's posts);
  - the church's next service (member_lumen_home.service_next), its time,
    its message when one is dated that day, its picture spot;
  - each of the member's groups' next gathering within two days, with its
    RSVP;
  - the church's events in the next seven days that have a picture.
In that order. Fewer than two, and the row isn't drawn. Nothing is made up:
a moment's line is its record's own words (a title, the devotional's line
to hold on to, the post's words), its kicker the record's day and time.

THE ROW. A circle each: an unseen one has a ring in the church's colour, a
seen one a quiet grey ring. "Seen" lives on the phone (localStorage
"lm-seen", kept two weeks): no write to the church, no read. Without
script each circle is a plain link to its page (the devotional's day, the
post, the group, Events).

THE VIEWER. A tap opens it full screen: thin progress segments, on to the
next after about six seconds (never with reduced motion, nor once the
member taps a button in it), tap the left side or the right to go back or
on, X or Escape to close (the phone's back button too: the viewer is a
history entry). Each moment: who it's from and how long ago (a post), the
kicker, the serif line, a quiet line, at most one button (the record's own
action: Read today's, I'll be there, I'm coming, I'm here, Sign up), then
a reply pill when member messaging lets this member write there (the
pastor, when member messages allow it; the group's chat; else the church's
conversation while church threads are open), Love when it is a real
reaction (a post's, through /my/news/react), and Share only on the church's
own content (Sunday, an event, the devotional: contract 1's
<a class="lm-share">; never a group's gathering nor a post, which are for
members only). Its buttons are today's forms posting to today's routes
(each with its own session, same-site and rate checks): this file adds no
route and no write.

Its colours: the viewer is a photo seen in the dark, white words over a
black scrim in every look (as Watch's cinema is); the row uses the look's
tokens. CSS joins /my/lumen.<hash>.css (member_lumen_ui.templates), every
rule under .lm. Pure functions, no I/O.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from string import Template
from typing import Any, Dict, List, Optional

# A pastor's post counts as today's word for this long.
POST_DAYS = 3
# A group's gathering is a moment this close.
GROUP_DAYS = 2
# The church's events are moments this close (with a picture of their own).
EVENT_DAYS = 7
MOST = 8


def _e(s: Any) -> str:
    return escape(str(s if s is not None else ""), quote=True)


def _at(iso: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def pastor_post(posts: Optional[List[Dict[str, Any]]], now: datetime) -> Optional[Dict[str, Any]]:
    """The newest of Home's posts by someone in a pastoral role (the post's
    own "pastor" flag, church_news._decorate) from the last POST_DAYS days,
    with words to show; None otherwise."""
    best = None
    for p in posts or []:
        if not p.get("pastor") or not p.get("posted_by"):
            continue
        if not (str(p.get("title") or "").strip() or str(p.get("body") or "").strip()):
            continue
        at = _at(p.get("created_at"))
        if not at or not timedelta(0) <= now - at <= timedelta(days=POST_DAYS):
            continue
        if best is None or at > best[0]:
            best = (at, p)
    return best[1] if best else None


def ago(iso: Any, now: datetime) -> str:
    """'2h', '35m', '1d': how long ago, as a phone's stories say it."""
    at = _at(iso)
    if not at:
        return ""
    s = max(0, int((now - at).total_seconds()))
    if s < 3600:
        return f"{max(1, s // 60)}m"
    if s < 86400:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def clip(text: Any, most: int) -> str:
    """Words cut at a word boundary with an ellipsis."""
    t = " ".join(str(text or "").split())
    if len(t) <= most:
        return t
    cut = t[:most].rsplit(" ", 1)[0].rstrip(",;:.")
    return cut + "…"


def short_name(name: Any) -> str:
    """The name under a circle: 'Pastor James' from 'Pastor James Carter'
    (a title and a first name), else the first two words."""
    words = str(name or "").split()
    return " ".join(words[:2])


def _ic(name: str, size: int = 24) -> str:
    import member_lumen_ui as lm
    return lm.ic(name, size)


def ring_initials(name: Any) -> str:
    import member_app_ui as ui
    return f'<span class="lm-moini" aria-hidden="true">{_e(ui.initials(name))}</span>'


def share_link(href: str, kind: str, title: str, sub: str = "", img: str = "") -> str:
    """Contract 1's share control: a link to the PUBLIC page (it opens it
    without script); the share sheet takes the click when it's there."""
    return (f'<a class="lm-share lm-mvac" href="{_e(href)}" data-share-kind="{_e(kind)}" data-share-title="{_e(title)}"'
            f' data-share-sub="{_e(sub)}" data-share-img="{_e(img)}" aria-label="Share">{_ic("share", 24)}</a>')


def love_form(post_id: str, on: bool) -> str:
    """Love on a post: the feed's own reaction form (/my/news/react; Home's
    RX_JS answers it in place, a plain post without script)."""
    return (f'<form method="post" action="/my/news/react" class="nw-rxf lm-mvlove">'
            f'<input type="hidden" name="id" value="{_e(post_id)}"><input type="hidden" name="kind" value="love">'
            f'<input type="hidden" name="back" value="/my"><button class="lm-mvac" type="submit" '
            f'aria-pressed="{"true" if on else "false"}" aria-label="Love">{_ic("heart", 24)}</button></form>')


def moment(*, mid: str, label: str, ring: str, bg: str, face: str, name: str, href: str, kicker: str, line: str,
           sub: str = "", when: str = "", action: str = "", reply: Optional[tuple] = None, love: str = "",
           share: str = "") -> Dict[str, Any]:
    """One moment. `ring`, `bg`, `face`, `action`, `love` and `share` are
    trusted markup; the words are escaped where they're drawn."""
    return {"id": mid, "label": label, "ring": ring, "bg": bg, "face": face, "name": name, "href": href,
            "kicker": kicker, "line": line, "sub": sub, "when": when, "action": action, "reply": reply,
            "love": love, "share": share}


def row(moments: List[Dict[str, Any]]) -> str:
    """The circles, the viewer and its script; '' with fewer than two."""
    ms = [m for m in moments if m][:MOST]
    if len(ms) < 2:
        return ""
    circles, slides, segs = [], [], []
    n = len(ms)
    for i, m in enumerate(ms):
        circles.append(
            f'<a class="lm-mo" href="{_e(m["href"])}" data-mo="{_e(m["id"])}" aria-label="{_e(m["name"])}: {_e(m["line"])}">'
            f'<span class="lm-mor"><span><span class="lm-mop">{m["ring"]}</span></span></span>'
            f'<b>{_e(m["label"])}</b></a>')
        reply = m.get("reply")
        pill = (f'<a class="lm-mvre" href="{_e(reply[0])}">{_e(reply[1])}</a>' if reply else "")
        acts = f'{pill}<span class="lm-mvacts">{m.get("love") or ""}{m.get("share") or ""}</span>'
        when = f'<small>{_e(m["when"])}</small>' if m.get("when") else ""
        sub = f'<p class="lm-mvp">{_e(m["sub"])}</p>' if m.get("sub") else ""
        act = f'<div class="lm-mvdo">{m["action"]}</div>' if m.get("action") else ""
        slides.append(
            f'<section class="lm-mvs" role="group" aria-roledescription="moment" aria-label="{i + 1} of {n}: {_e(m["name"])}" hidden>'
            f'<span class="lm-mvbg">{m["bg"]}</span><span class="lm-mvsh" aria-hidden="true"></span>'
            f'<header class="lm-mvhd"><span class="lm-mvf">{m["face"]}</span><span class="lm-mvn"><b>{_e(m["name"])}</b>{when}</span></header>'
            f'<div class="lm-mvbd"><p class="lm-mvk">{_e(m["kicker"])}</p><h2 class="lm-mvh">{_e(m["line"])}</h2>{sub}{act}</div>'
            f'<div class="lm-mvft">{acts}</div></section>')
        segs.append("<i></i>")
    return (f'<nav class="lm-mos" id="lm-mos" aria-label="Moments from your church">{"".join(circles)}</nav>'
            f'<div class="lm-mv" id="lm-mv" role="dialog" aria-modal="true" aria-label="Moments" hidden>'
            f'<div class="lm-mvst"><div class="lm-mvg" aria-hidden="true">{"".join(segs)}</div>'
            f'<button class="lm-mvl" type="button" aria-label="Previous moment"></button>'
            f'<button class="lm-mvr" type="button" aria-label="Next moment"></button>{"".join(slides)}'
            f'<button class="lm-mvx" type="button" aria-label="Close">{_ic("x", 24)}</button></div></div>{JS}')


# The row's seen rings (before the page paints: the script follows the row)
# and the viewer. A phone that can't keep anything (a private window) shows
# every ring unseen and still opens the viewer.
JS = r"""<script>(function(){
var d=document,row=d.getElementById('lm-mos'),v=d.getElementById('lm-mv');if(!row||!v)return;
// Over everything: out of the page's own layers, at the end of the body.
d.body.appendChild(v);
var K='lm-seen',S=null,AGE=1209600000,DUR=6000;try{S=window.localStorage;}catch(e){}
function load(){try{var m=JSON.parse((S&&S.getItem(K))||'{}');return m&&typeof m==='object'?m:{};}catch(e){return {};}}
var cs=[].slice.call(row.querySelectorAll('.lm-mo')),ss=[].slice.call(v.querySelectorAll('.lm-mvs')),
 gs=[].slice.call(v.querySelectorAll('.lm-mvg i')),seen=load();
cs.forEach(function(c){if(seen[c.getAttribute('data-mo')])c.classList.add('seen');});
function mark(i){var c=cs[i],id=c&&c.getAttribute('data-mo'),now=Date.now();if(!id)return;seen=load();seen[id]=now;
 for(var k in seen){if(!(now-seen[k]<AGE))delete seen[k];}
 try{if(S)S.setItem(K,JSON.stringify(seen));}catch(e){}c.classList.add('seen');}
var still=!!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches);
var at=-1,t=null,held=false,pushed=false,from=null,go2=null;
function stop(){clearTimeout(t);t=null;}
function arm(){stop();if(still||held||at<0)return;t=setTimeout(function(){step(1);},DUR);}
function show(i){at=i;ss.forEach(function(s,k){s.hidden=k!==i;});
 gs.forEach(function(g,k){g.className=k<i||(k===i&&still)?'full':'';});
 if(!still&&gs[i]){void gs[i].offsetWidth;gs[i].className='on';}
 mark(i);arm();}
function step(n){var i=at+n;if(i<0)i=0;if(i>=ss.length){close();return;}held=false;show(i);}
function open(i,c){from=c;held=false;v.hidden=false;d.body.classList.add('lm-mvon');
 try{history.pushState({lmmv:1},'');pushed=true;}catch(e){pushed=false;}
 show(i);var x=v.querySelector('.lm-mvx');try{x.focus({preventScroll:true});}catch(e){x.focus();}}
function shut(){stop();gs.forEach(function(g){g.className='';});v.hidden=true;d.body.classList.remove('lm-mvon');at=-1;
 if(from){try{from.focus({preventScroll:true});}catch(e){}}}
function close(){if(pushed){pushed=false;history.back();return;}shut();}
window.addEventListener('popstate',function(){if(v.hidden)return;pushed=false;shut();
 if(go2){var g=go2;go2=null;g();}});
window.addEventListener('pageshow',function(e){if(e.persisted&&!v.hidden){pushed=false;shut();}});
// Leaving the page: nothing left moving in it (a page kept for Back comes back still).
window.addEventListener('pagehide',function(){stop();gs.forEach(function(g){g.className='';});});
cs.forEach(function(c,i){c.addEventListener('click',function(e){
 if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button)return;e.preventDefault();open(i,c);});});
v.querySelector('.lm-mvx').addEventListener('click',close);
v.querySelector('.lm-mvl').addEventListener('click',function(){step(-1);});
v.querySelector('.lm-mvr').addEventListener('click',function(){step(1);});
function hold(){held=true;stop();if(gs[at])gs[at].className='full';}
// Leaving from inside: a link takes the viewer's own history entry (Back from
// its page comes to Home); a form, which can't, lets the entry go first.
function leave(fn){if(!pushed){fn();return;}pushed=false;go2=fn;history.back();}
function away(u){if(pushed){pushed=false;location.replace(u);}else{location.href=u;}}
v.addEventListener('click',function(e){var a=e.target.closest?e.target.closest('a[href]'):null;
 if(!a||e.defaultPrevented)return;hold();
 if(a.classList.contains('lm-share'))return;
 if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();away(a.href);});
v.addEventListener('submit',function(e){var f=e.target;hold();if(e.defaultPrevented||f.classList.contains('nw-rxf'))return;
 e.preventDefault();leave(function(){HTMLFormElement.prototype.submit.call(f);});});
v.addEventListener('pointerdown',function(e){var b=e.target.closest?e.target.closest('button,a,form'):null;
 if(b&&!b.matches('.lm-mvl,.lm-mvr,.lm-mvx'))hold();});
// Keys anywhere while it's open (Safari leaves focus on the page when a button is tapped).
d.addEventListener('keydown',function(e){if(v.hidden)return;
 if(!v.contains(d.activeElement)&&e.key==='Tab'){e.preventDefault();var x=v.querySelector('.lm-mvx');if(x)x.focus();return;}
 if(e.key==='Escape'){e.preventDefault();close();return;}
 if(e.key==='ArrowRight'){step(1);return;}if(e.key==='ArrowLeft'){step(-1);return;}
 if(e.key!=='Tab')return;var f=[].filter.call(v.querySelectorAll('a[href],button'),function(x){return x.offsetParent!==null;});
 if(!f.length)return;var a=f[0],z=f[f.length-1];
 if(e.shiftKey&&d.activeElement===a){e.preventDefault();z.focus();}else if(!e.shiftKey&&d.activeElement===z){e.preventDefault();a.focus();}});
d.addEventListener('visibilitychange',function(){if(at<0)return;if(d.hidden)stop();else arm();});
})();</script>"""


CSS = Template("""
/* Look 5.1: Home's moments and their viewer (member_lumen_stories) */
.lm-mos{display:flex;gap:12px;margin:0 -20px;padding:6px 20px 16px;overflow-x:auto;scrollbar-width:none;
  border-bottom:1px solid var(--lm-line);scroll-padding-inline:20px;}
.lm-mos::-webkit-scrollbar{display:none;}
.lm-mo{flex:none;width:72px;display:flex;flex-direction:column;align-items:center;gap:6px;color:var(--fg);text-decoration:none;
  -webkit-tap-highlight-color:transparent;}
.lm-mor{display:block;width:72px;height:72px;border-radius:50%;padding:2.5px;background:var(--acc-fill);}
.lm-mo.seen .lm-mor{background:var(--lm-line);}
@supports (background:color-mix(in srgb,red 50%,blue)){.lm-mo.seen .lm-mor{background:color-mix(in srgb,var(--fg) 16%,var(--bg));}}
.lm-mor>span{display:block;width:100%;height:100%;border-radius:50%;padding:3px;background:var(--bg);}
.lm-mop{position:relative;display:block;width:100%;height:100%;border-radius:50%;overflow:hidden;background:var(--s2);}
.lm-mop>*{position:absolute;inset:0;z-index:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm-mop img{display:block;width:100%;height:100%;object-fit:cover;}
.lm-mop .mb-def-ic{top:50%;left:50%;right:auto;width:26px;height:26px;transform:translate(-50%,-50%);}
.lm-moini{display:grid;place-items:center;background:var(--acc-fill);color:var(--on-acc);font:italic 500 21px/1 var(--mb-serif);}
.lm-mo>b{max-width:76px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:500 12px/1.2 var(--mb-ui);}
.lm-mo.seen>b{color:var(--fg3);}
.lm-mo:focus-visible{outline:none;}
.lm-mo:focus-visible .lm-mor{box-shadow:0 0 0 2px var(--bg),0 0 0 4px var(--acc);}
@media (prefers-reduced-motion:no-preference){
  .lm-mor{transition:transform .2s ease-out;}
  .lm-mo:active .lm-mor{transform:scale(.94);}
}

/* the viewer: a photo in the dark, white words over a scrim, in every look */
.lm-mv{--mv-ink:#fff;--mv-dim:rgba(255,255,255,.88);position:fixed;inset:0;z-index:300;background:#000;color:var(--mv-ink);}
.lm-mv[hidden],.lm-mvs[hidden]{display:none;}
body.lm.lm-mvon{overflow:hidden;}
.lm-mvst{position:relative;height:100%;max-width:520px;margin:0 auto;overflow:hidden;}
.lm-mvs{position:absolute;inset:0;}
.lm-mvbg{position:absolute;inset:0;background:#111;}
.lm-mvbg>*{position:absolute;inset:0;z-index:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm-mvbg img{display:block;width:100%;height:100%;object-fit:cover;}
.lm-mvbg .mb-def-ic{top:34%;left:50%;right:auto;width:88px;height:88px;transform:translate(-50%,-50%);opacity:.8;}
.lm-mvsh{position:absolute;inset:0;background:linear-gradient(180deg,rgba(0,0,0,.5) 0,rgba(0,0,0,0) 20%,rgba(0,0,0,0) 40%,rgba(0,0,0,.8) 100%);}
.lm-mvg{position:absolute;left:10px;right:10px;top:calc(12px + env(safe-area-inset-top,0px));z-index:5;display:flex;gap:4px;}
.lm-mvg i{flex:1;height:2.5px;border-radius:2px;background:rgba(255,255,255,.35);overflow:hidden;}
.lm-mvg i::after{content:"";display:block;width:0;height:100%;background:var(--mv-ink);}
.lm-mvg i.full::after{width:100%;}
@media (prefers-reduced-motion:no-preference){.lm-mvg i.on::after{animation:lmMvFill 6s linear forwards;}}
@keyframes lmMvFill{from{width:0}to{width:100%}}
.lm-mvhd{position:absolute;left:0;right:0;top:calc(24px + env(safe-area-inset-top,0px));z-index:4;display:flex;align-items:center;
  gap:10px;height:44px;padding:0 56px 0 14px;}
.lm-mvf{position:relative;width:34px;height:34px;flex:none;border-radius:50%;overflow:hidden;background:#222;
  box-shadow:0 0 0 1.5px rgba(255,255,255,.75);}
.lm-mvf>*{position:absolute;inset:0;z-index:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm-mvf img{display:block;width:100%;height:100%;object-fit:cover;}
.lm-mvf .lm-moini{font-size:14px;}
.lm-mvlogo{display:block;padding:4px;background:#fff;}
.lm-mvlogo img{object-fit:contain;}
.lm-mvf .mb-def-ic{top:50%;left:50%;right:auto;width:16px;height:16px;transform:translate(-50%,-50%);}
.lm-mvn{min-width:0;display:flex;align-items:baseline;gap:6px;}
.lm-mvn b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:700 14px/1.2 var(--mb-ui);}
.lm-mvn small{flex:none;font:500 13px/1 var(--mb-ui);opacity:.78;}
.lm-mvx{position:absolute;right:4px;top:calc(24px + env(safe-area-inset-top,0px));z-index:6;width:44px;height:44px;display:grid;
  place-items:center;padding:0;border:0;border-radius:50%;background:none;color:var(--mv-ink);cursor:pointer;}
.lm-mvl,.lm-mvr{position:absolute;top:80px;bottom:170px;z-index:2;padding:0;border:0;background:none;cursor:pointer;
  -webkit-tap-highlight-color:transparent;}
.lm-mvl{left:0;width:32%;}
.lm-mvr{right:0;width:68%;}
.lm-mvbd{position:absolute;left:0;right:0;bottom:calc(92px + env(safe-area-inset-bottom,0px));z-index:3;padding:0 22px;pointer-events:none;}
.lm-mvbd a,.lm-mvbd button,.lm-mvbd form{pointer-events:auto;}
.lm-mvk{margin:0;font:700 11px/1.2 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--mv-dim);}
.lm-mvh{margin:12px 0 10px;font-family:var(--mb-serif);font-weight:var(--lm-dw,400);font-variation-settings:var(--lm-dvar,normal);
  font-stretch:var(--lm-dst,100%);font-size:31px;line-height:1.17;letter-spacing:-.015em;color:var(--mv-ink);text-wrap:pretty;}
.lm-mvp{margin:0;font:400 15px/1.45 var(--mb-ui);color:var(--mv-dim);}
.lm-mvdo{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin-top:18px;}
.lm-mvb{height:40px;padding:0 18px;border:0;border-radius:20px;background:var(--mv-ink);color:#111;font:650 14px/1 var(--mb-ui);
  display:inline-flex;align-items:center;gap:7px;text-decoration:none;cursor:pointer;white-space:nowrap;}
.lm-mvb.on{background:rgba(255,255,255,.18);color:var(--mv-ink);box-shadow:inset 0 0 0 1.5px rgba(255,255,255,.5);}
.lm-mvb.q{background:none;color:var(--mv-dim);padding:0 10px;}
.lm-mvb svg{width:16px;height:16px;}
.lm-mvft{position:absolute;left:0;right:0;bottom:calc(22px + env(safe-area-inset-bottom,0px));z-index:4;display:flex;align-items:center;
  gap:4px;padding:0 8px 0 14px;}
.lm-mvre{flex:1;min-width:0;height:46px;display:flex;align-items:center;padding:0 18px;border-radius:23px;
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.55);color:var(--mv-dim);font:400 14.5px/1 var(--mb-ui);text-decoration:none;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.lm-mvacts{display:flex;align-items:center;margin-left:auto;}
.lm-mvac{width:44px;height:44px;display:grid;place-items:center;padding:0;border:0;border-radius:50%;background:none;color:var(--mv-ink);
  text-decoration:none;cursor:pointer;}
.lm-mvac[aria-pressed=true] svg{fill:currentColor;}
.lm-mvx:focus-visible,.lm-mvac:focus-visible,.lm-mvre:focus-visible,.lm-mvb:focus-visible{outline:2px solid var(--mv-ink);outline-offset:2px;}
.lm-mvl:focus-visible,.lm-mvr:focus-visible{outline:2px solid rgba(255,255,255,.6);outline-offset:-4px;}
@media (prefers-reduced-motion:no-preference){
  .lm-mvs:not([hidden]) .lm-mvbd{animation:lmMvIn .35s ease-out both;}
  .lm-mvb:active,.lm-mvac:active{transform:scale(.94);}
}
@keyframes lmMvIn{from{opacity:0;transform:translateY(8px)}}
""")
