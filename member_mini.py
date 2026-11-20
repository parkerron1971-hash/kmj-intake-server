"""member_mini.py — a message keeps playing while the member moves around the
app, with a mini player above the tab bar (Look 5.1).

Kevin, 2026-11-20, approving Look 5.1 of the member app's new look
("Lumen"): "lets build this including the new still to build!", which
includes the mock's mini player (frames a-mini and a-player): the message
goes on playing in a small bar over the tab bar while the member browses
Home, Connect or the Bible: its picture, its title, "Playing · 12:04 of
38:12", play or pause, close, and a hairline of progress. Tapping the bar
goes back to the message, at the same spot.

THE PROBLEM. Every tap in the member app loads a whole new page from the
server, so a message stops the moment its page is left.

HOW IT WORKS: THE APP IN A FRAME, ONLY WHILE SOMETHING PLAYS. The message
page (/my/sermons/<id>) stays the page in the browser, with its player
(an <audio> file, or a YouTube, Vimeo, Loom, Facebook or our own recording's
player in an <iframe>) never moved or reloaded. While a message is playing
(or paused after playing), a tap on one of the app's own links on that page
doesn't leave it: the address bar moves to the link (history.pushState), and
the page it names opens in a full-screen frame laid over the message
(.lm-stagew). Every page in that frame is the ordinary page, loaded the
ordinary way: its scripts, its forms, its own moves, its tab bar. Moving
around inside the frame is ordinary browsing too, with the mini player
laid over the frame's tab bar (it lives on the message page, so it never
reloads and never blinks). The message page watches each page the frame
opens (it is the same site, so it can) and:

  - keeps the address bar, the page's title and the phone's bar colour
    in step with the page in the frame (history.replaceState);
  - wears the frame's page colours on the mini player (Light, Dark, Same
    as my phone, the cinema), and places it 8 px over that page's tab bar
    (on a computer, beside the sidebar at the foot); the page's own foot
    gets room for it (body.lm-mini-pad);
  - hides the bar where it would be in the way: a page with no tab bar
    (the Bible reader, a devotional's day, a conversation), while the
    member types, and the live room, which pauses the message (a video
    player we can't pause stops instead);
  - back to the message itself (the bar, or any link to it), the frame is
    simply hidden: the player is where it was, still playing, and the page
    is scrolled where it was.

Back and forward work the browser's own way: pages inside the frame are
the frame's history; back past the frame's first page shows the message;
forward shows the frame again. Reloading loads the page in the address bar
as an ordinary page, so playback stops cleanly.

WHEN IT LOADS THE ORDINARY WAY (playback stops, as today):

  - nothing has played, or the member closed the bar (the page acts as it
    always has; one tap after closing leaves the frame);
  - another site, a download, a link meant for a new window;
  - Give and recurring gifts (payments run in the page itself), the giving
    statement, a group's live meeting (camera and microphone), a photo,
    Kids, the owner's preview links;
  - another message's page (one message plays at a time; opening another
    one switches to it);
  - anything that isn't one of the new look's pages (signed out, an error,
    Youth or Kids, the old look) or a page that refuses the frame.

WHAT THE BAR CAN SHOW. A file (<audio>, <video>): everything: play,
pause, the time, the progress, and the phone's lock screen (the Media
Session API: title, speaker, picture, play, pause, 15 seconds back and on).
A video player from another site (YouTube and the rest) plays on in the
frame's shadow just the same, but its time can't be read from outside it,
so its bar says "Back to the message" and offers close (which stops it);
the page treats it as playing once the member has tapped into it.

THE CONTRACT (Look 5.1, helper "Watch"): a playable element is marked
data-lm-media, with data-title, data-sub, data-thumb and data-href (on the
<audio>, <video> or <iframe> itself, or on a box around one). This module
marks the message page's player itself (mark()) until the Watch page does.

THE SWITCH. MEMBER_MINI_PLAYER = off | preview | on, preview by default.

  off ...... nobody: every page and every header is what it was.
  preview .. only the platform owner, on a page in the new look (their
             "Preview as a member", or their own sign-in at their church;
             member_lumen's own preview rule).
  on ....... everyone who sees the new look (member_lumen).

What it changes, switched on, for someone it shows to: the message page
gains the marks and one script (page_script); the new look's sheet gains
the bar's rules (CSS). Every other page is byte for byte what it was:
a page loads in the frame exactly as it would on its own. The one server
difference: for that same someone, a page asked for by a frame on the same
site (Sec-Fetch-Dest: iframe, Sec-Fetch-Site: same-origin) answers with
X-Frame-Options: SAMEORIGIN and frame-ancestors 'self' instead of DENY and
'none' (allow_frame, at the end of member_portal.serve, where the session
is known), which still refuses every other site's frame; for anyone else
every header is what it was. And
the service worker leaves a frame's page to the browser
(member_app_install.SW_JS): a page the worker asks for itself, or kept
early, goes out without the frame's Sec-Fetch-Dest and would be refused
(measured: Chromium sends Sec-Fetch-Dest: empty for the worker's copy).
No page under /my was ever in a frame before, so that changes nothing
for anyone else.

COST. No reads: the switch is decided from the session the page already
has (member_lumen's cached church-owner answer for the owner's preview).
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import os
import re
from html import escape
from string import Template
from typing import Any, Mapping, Optional

ENV = "MEMBER_MINI_PLAYER"
MODES = ("off", "preview", "on")
DEFAULT = "preview"

# Whether the member page being drawn carries the mini player (decide()).
CURRENT: contextvars.ContextVar[bool] = contextvars.ContextVar("member_mini", default=False)


def mode() -> str:
    m = (os.environ.get(ENV) or DEFAULT).strip().lower()
    return m if m in MODES else "off"


async def decide(session: Optional[Mapping[str, Any]], biz: Optional[Mapping[str, Any]]) -> bool:
    """Whether this page carries the mini player, kept for it (here()).
    Only a page in the new look can (member_lumen.here, decided just
    before). preview: the platform owner's preview session or their own
    sign-in, at a church they own; under MEMBER_LUMEN=preview that is
    exactly who sees the new look, so no more is asked; otherwise the
    church's owner (member_lumen._platform_church, kept ten minutes) is
    asked only for the platform owner's own sessions. Never raises."""
    yes = False
    try:
        import member_lumen
        m = mode()
        if m != "off" and member_lumen.here():
            if m == "on":
                yes = True
            elif session and session.get("me") and not session.get("unavailable") and (
                    session.get("preview") or member_lumen.is_platform_owner(session)):
                if member_lumen.mode() == "preview":
                    yes = True
                else:
                    yes = bool(await asyncio.to_thread(member_lumen._platform_church, (biz or {}).get("id")))
    except Exception:
        yes = False
    CURRENT.set(bool(yes))
    return bool(yes)


def here() -> bool:
    """Whether the member page being drawn carries the mini player: decided
    yes for this request, and a signed-in Church page in the new look."""
    if not CURRENT.get():
        return False
    try:
        import member_lumen
        return member_lumen.page()
    except Exception:
        return False


# ─── marking the player (the Look 5.1 contract) ─────────────────────────

_MEDIA_TAG = re.compile(r"<(audio|video|iframe)\b(?![^>]*\bdata-lm-media\b)", re.I)


def mark(player: str, *, title: Any, sub: Any = "", thumb: Any = "", href: Any = "") -> str:
    """The player's markup with every <audio>, <video> and <iframe> in it
    marked for the mini player: data-lm-media, data-title, data-sub,
    data-thumb, data-href. One already marked is left alone. Escaped."""
    attrs = (f' data-lm-media data-title="{escape(str(title or ""), quote=True)}"'
             f' data-sub="{escape(str(sub or ""), quote=True)}"'
             f' data-thumb="{escape(str(thumb or ""), quote=True)}"'
             f' data-href="{escape(str(href or ""), quote=True)}"')
    return _MEDIA_TAG.sub(lambda m: f"<{m.group(1)}{attrs}", player or "")


def thumb(biz: Mapping[str, Any], site: Optional[Mapping[str, Any]], series: str, title: str) -> str:
    """The picture for the bar and the lock screen: the series' own art from
    the church's site, else one of the church's photos named for the series
    or the message (member_portal_sermons._art's rules, without the
    generated poster, which is markup, not a picture). '' when there's none
    (the bar then shows the church's colour)."""
    try:
        import member_app_photos as photos
        own = photos.series_art(site, series) if series else ""
        if own:
            return own
        return photos.by_name(photos.photos(dict(biz or {}), site), series or title) or ""
    except Exception:
        return ""


# ─── the script on the message page ────────────────────────────────────

# The mock's icons (Look 5.1, build_hybrid.py): play and pause filled, the
# close cross drawn, the headphones for a message with no picture.
_SVG = ('<svg width="{s}" height="{s}" viewBox="0 0 24 24" fill="{fill}" stroke="{stroke}" stroke-width="1.9" '
        'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">{p}</svg>')
ICONS = {
    "play": _SVG.format(s=19, fill="currentColor", stroke="none", p='<path d="M7 4.5v15l12.5-7.5z"/>'),
    "pause": _SVG.format(s=19, fill="currentColor", stroke="none",
                         p='<rect x="6" y="4.5" width="4" height="15" rx="1"/><rect x="14" y="4.5" width="4" height="15" rx="1"/>'),
    "x": _SVG.format(s=19, fill="none", stroke="currentColor", p='<path d="M18 6 6 18"/><path d="m6 6 12 12"/>'),
    "art": _SVG.format(s=20, fill="none", stroke="currentColor",
                       p='<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2'
                         'h-1a2 2 0 0 1-2-2v-3a2 2 0 0 1 2-2h3"/>'),
}

# Where the frame never goes (see the docstring): these load the ordinary
# way, and so does another message's page.
OUT_RE = r"^\/my\/(give|gifts|statement|groups\/live|photo|kids|preview|signout)(\/|$)"

# The colours the bar takes from the page in the frame.
TOKENS = ("--bg", "--fg", "--fg2", "--fg3", "--s1", "--lm-line", "--lm-shadow", "--acc", "--acc-fill", "--on-acc")

_JS = r"""<script>(function(){
var w=window,d=document,de=d.documentElement;
if(w.__lmMini||w.top!==w||!d.querySelector('[data-lm-media]'))return;w.__lmMini=1;
var HOME=location.pathname,BACK=location.pathname+location.search,I=%ICONS%,TOK=%TOKENS%;
var OUT=new RegExp(%OUT%),MSG=/^\/my\/sermons\/[^\/]+\/?$/,LIVE=/^\/my\/live(\/|$)/;
var items=[],cur=null,on=false,wrap=null,fr=null,doc=null,poll=0,seq=Date.now()%1e6,staged=false,moved=0,live=false,
typing=false,keep=null,locked=[],mini=null,go,th,tt,st,pp,line;
function U(h,b){try{return new URL(h,b||location.href);}catch(e){return null;}}
function inApp(u){var p=u.pathname;return (p==='/my'||p.indexOf('/my/')===0)&&!OUT.test(p)&&!(MSG.test(p)&&p!==HOME);}
function fmt(t){t=Math.max(0,Math.floor(t||0));var h=Math.floor(t/3600),m=Math.floor(t/60)%60,s=t%60;
return (h?h+':'+(m<10?'0':''):'')+m+':'+(s<10?'0':'')+s;}
function rm(n){if(n&&n.parentNode)n.parentNode.removeChild(n);}
function sd(){try{return fr?fr.contentDocument:null;}catch(e){return null;}}
function cancel(e){return e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey;}
/* the players on this page */
[].forEach.call(d.querySelectorAll('[data-lm-media]'),function(b){
var m=/^(AUDIO|VIDEO|IFRAME)$/.test(b.tagName)?b:b.querySelector('audio,video,iframe');if(!m)return;
var it={b:b,m:m,f:m.tagName!=='IFRAME',t:b.getAttribute('data-title')||d.title,s:b.getAttribute('data-sub')||'',
i:b.getAttribute('data-thumb')||'',h:b.getAttribute('data-href')||BACK};items.push(it);
if(it.f){m.addEventListener('play',function(){take(it);});
['pause','timeupdate','loadedmetadata','durationchange'].forEach(function(k){m.addEventListener(k,function(){if(cur===it)draw();});});
m.addEventListener('ended',function(){if(cur===it)close();});}});
if(!items.length)return;
/* a player from another site: playing once the member has tapped into it */
w.addEventListener('blur',function(){setTimeout(function(){var a=d.activeElement;
items.forEach(function(it){if(!it.f&&a===it.m&&cur!==it)take(it);});},0);});
function take(it){if(cur&&cur!==it){if(cur.f)cur.m.pause();else stop(cur);}
cur=it;on=true;build();th.textContent='';
if(it.i){var im=new Image();im.alt='';im.decoding='async';im.src=it.i;th.appendChild(im);}else th.innerHTML=I.art;
tt.textContent=it.t;go.href=it.h;session(it);if(staged&&doc&&doc.body)look(doc);draw();place();}
function stop(it){try{it.m.contentWindow.location.replace(it.m.src);}catch(e){it.m.src=it.m.src;}}
function close(){var it=cur;cur=null;on=false;if(it){if(it.f)it.m.pause();else stop(it);}
var S=navigator.mediaSession;if(S){try{S.metadata=null;}catch(e){}}place();}
function hush(){if(doc)[].forEach.call(doc.querySelectorAll('audio,video'),function(m){if(!m.paused)m.pause();});}
function play(){if(!cur||!cur.f)return;hush();var p=cur.m.play();if(p&&p.catch)p.catch(function(){});}
/* the bar */
function build(){if(mini)return;mini=d.createElement('div');mini.className='lm-mini';mini.hidden=true;
mini.setAttribute('role','region');mini.setAttribute('aria-label','Now playing');
mini.innerHTML='<a class="lm-mini-go" href="#"><span class="lm-mini-th"></span><span class="lm-mini-tx"><b></b><small></small></span></a>'
+'<button class="lm-mini-b" type="button" data-pp></button><button class="lm-mini-b" type="button" data-x aria-label="Stop and close">'+I.x+'</button>'
+'<span class="lm-mini-line" aria-hidden="true"><i></i></span>';
go=mini.querySelector('a');th=mini.querySelector('.lm-mini-th');tt=mini.querySelector('b');st=mini.querySelector('small');
pp=mini.querySelector('[data-pp]');line=mini.querySelector('.lm-mini-line');
go.addEventListener('click',function(e){e.preventDefault();toPage();});
pp.addEventListener('click',function(){if(!cur||!cur.f)return;if(cur.m.paused)play();else cur.m.pause();});
mini.querySelector('[data-x]').addEventListener('click',close);d.body.appendChild(mini);}
function draw(){if(!mini||!cur)return;var m=cur.m;
if(!cur.f){st.textContent='Back to the message';pp.hidden=true;line.hidden=true;return;}
var D=isFinite(m.duration)&&m.duration>0?m.duration:0,k=m.paused?'play':'pause';
st.textContent=(m.paused?'Paused':'Playing')+' · '+fmt(m.currentTime)+(D?' of '+fmt(D):'');
pp.hidden=false;line.hidden=false;line.firstChild.style.width=(D?Math.min(100,m.currentTime/D*100):0)+'%';
if(pp.getAttribute('data-k')!==k){pp.setAttribute('data-k',k);pp.innerHTML=I[k];pp.setAttribute('aria-label',m.paused?'Play':'Pause');}
var S=navigator.mediaSession;if(S&&D&&S.setPositionState){try{S.setPositionState({duration:D,position:Math.min(D,m.currentTime),
playbackRate:m.playbackRate||1});}catch(e){}}}
function session(it){var S=navigator.mediaSession;if(!S||!w.MediaMetadata||!it.f)return;var m=it.m;
try{S.metadata=new MediaMetadata({title:it.t,artist:it.s,artwork:it.i?[{src:U(it.i).href}]:[]});}catch(e){}
[['play',play],['pause',function(){m.pause();}],['seekbackward',function(){m.currentTime=Math.max(0,m.currentTime-15);}],
['seekforward',function(){m.currentTime=Math.min(isFinite(m.duration)?m.duration:m.currentTime+15,m.currentTime+15);}],
['stop',close]].forEach(function(a){try{S.setActionHandler(a[0],a[1]);}catch(e){}});}
/* a tap on this page while something plays: the page it names opens in the frame (heard on the window,
   after the page's own handlers, so a link a page script answers itself, Share, stays theirs) */
w.addEventListener('click',function(e){if(!on||staged||cancel(e))return;
var a=e.target.closest&&e.target.closest('a[href]');if(!a||(mini&&mini.contains(a))||a.hasAttribute('download'))return;
var t=a.getAttribute('target');if(t&&t!=='_self')return;
var u=U(a.href);if(!u||u.origin!==location.origin)return;
if(u.pathname===HOME){if(u.search===location.search&&!u.hash)e.preventDefault();return;}
if(!inApp(u))return;e.preventDefault();open(u);});
function open(u){seq++;try{history.pushState({lmStage:seq},'',u.pathname+u.search+u.hash);}catch(e){location.assign(u.href);return;}
mount(seq,u.href);}
function mount(id,href){clearInterval(poll);rm(wrap);doc=null;moved=-1;
wrap=d.createElement('div');wrap.className='lm-stagew';fr=d.createElement('iframe');fr.className='lm-stage';fr.title=d.title;
fr.setAttribute('allow','autoplay; fullscreen; picture-in-picture; encrypted-media; clipboard-write; web-share');
fr.setAttribute('allowfullscreen','');fr.lmId=id;fr.lmPend=href;fr.lmShown=false;fr.addEventListener('load',loaded);
var bar=d.createElement('i');bar.className='lm-stageload';bar.setAttribute('aria-hidden','true');wrap.appendChild(bar);
fr.src=href;wrap.appendChild(fr);d.body.appendChild(wrap);watch();
/* a frame that never shows its page (refused, lost): the page loads the ordinary way */
setTimeout(function(){var s=history.state;if(fr&&fr.lmId===id&&!fr.lmShown&&s&&s.lmStage===id)out(href,true);},12000);}
/* each page the frame opens, as soon as it starts */
function watch(){clearInterval(poll);var n=0;poll=setInterval(function(){if(++n>500||!fr){clearInterval(poll);return;}
var x=sd();if(!x||x===doc||!x.documentElement||x.URL==='about:blank')return;clearInterval(poll);hook(x);},40);}
function loaded(){var x=sd();if(fr.lmShown&&!staged)return;
if(!x||(x.URL==='about:blank'&&moved>=0)){out(fr.lmPend||location.href,true);return;}
if(x!==doc&&x.URL!=='about:blank'){clearInterval(poll);hook(x);}}
function hook(x){doc=x;moved++;var v=x.defaultView;v.addEventListener('click',inside);x.addEventListener('play',other,true);
x.addEventListener('focusin',keys,true);x.addEventListener('focusout',keys,true);
v.addEventListener('pagehide',function(){if(doc===x){doc=null;watch();}});
if(x.readyState==='loading')x.addEventListener('DOMContentLoaded',function(){ready(x);});else ready(x);}
function out(href,rep){clearInterval(poll);if(rep)location.replace(href);else location.assign(href);}
function inside(e){if(cancel(e))return;var a=e.target.closest&&e.target.closest('a[href]');if(!a||a.hasAttribute('download'))return;
var x=a.ownerDocument,u=U(a.href,x.baseURI);if(!u||!/^https?:$/.test(u.protocol))return;
var t=(a.getAttribute('target')||'').toLowerCase();if(t&&t!=='_self'){if(t==='_top'||t==='_parent'){e.preventDefault();out(u.href);}return;}
var L=x.defaultView.location,same=u.origin===location.origin;
if(same&&u.pathname===L.pathname&&u.search===L.search&&u.hash)return;
if(same&&u.pathname===HOME){e.preventDefault();toPage();return;}
if(!on||!same||!inApp(u)){e.preventDefault();out(u.href);return;}fr.lmPend=u.href;}
function ready(x){if(x!==doc||!fr||(fr.lmShown&&!staged))return;var L=x.defaultView.location,p=L.pathname,b=x.body;
if(!b||!b.classList.contains('lm')){out(L.href,true);return;}
if(p===HOME){if(staged)toPage();return;}
if(OUT.test(p)||MSG.test(p)){out(L.href,true);return;}
live=LIVE.test(p);if(live&&cur){if(cur.f)cur.m.pause();else close();}
safe(x);fr.title=x.title||d.title;
if(!fr.lmShown){fr.lmShown=true;var id=fr.lmId;requestAnimationFrame(function(){requestAnimationFrame(function(){
if(doc===x&&fr&&fr.lmId===id&&history.state&&history.state.lmStage===id)show();});});return;}
if(staged){sync(L);look(x);}place();}
function sync(L){var s=history.state;if(staged&&s&&fr&&s.lmStage===fr.lmId){try{history.replaceState(s,'',L.pathname+L.search+L.hash);}catch(e){}}}
/* the frame's page colours on the bar and at the phone's edges; its title and the phone's bar */
function look(x){if(!keep)keep={m:[].slice.call(d.querySelectorAll('meta[name="theme-color"]')),t:d.title};
[].forEach.call(d.querySelectorAll('meta[name="theme-color"]'),rm);
[].forEach.call(x.querySelectorAll('meta[name="theme-color"]'),function(m){d.head.appendChild(m.cloneNode(true));});
d.title=x.title||keep.t;var cs=x.defaultView.getComputedStyle(x.body);wrap.style.backgroundColor=cs.backgroundColor;
if(mini)TOK.forEach(function(k){var v=cs.getPropertyValue(k).trim();if(v)mini.style.setProperty(k,v);else mini.style.removeProperty(k);});}
function unlook(){if(!keep)return;[].forEach.call(d.querySelectorAll('meta[name="theme-color"]'),rm);
keep.m.forEach(function(m){d.head.appendChild(m);});d.title=keep.t;keep=null;}
function safe(x){if(wrap.lmSafe!==undefined)return;var p=x.createElement('div');
p.style.cssText='position:fixed;left:0;top:0;width:1px;height:env(safe-area-inset-top,0px);visibility:hidden;pointer-events:none';
x.body.appendChild(p);var h=p.getBoundingClientRect().height;rm(p);wrap.lmSafe=h>0;if(h>0)wrap.classList.add('lm-own-safe');}
function lock(y){if(y){[].forEach.call(d.body.children,function(c){if(c!==wrap&&c!==mini&&c.tagName!=='SCRIPT'&&!c.inert){c.inert=true;locked.push(c);}});}
else{locked.forEach(function(c){c.inert=false;});locked=[];}}
function show(){if(!wrap)return;staged=true;wrap.setAttribute('data-on','');de.classList.add('lm-staged');lock(true);
if(doc&&doc.body){look(doc);sync(doc.defaultView.location);}place();try{fr.focus({preventScroll:true});}catch(e){}}
function reveal(){staged=false;if(wrap)wrap.removeAttribute('data-on');de.classList.remove('lm-staged');lock(false);unlook();place();
if(d.activeElement===fr)fr.blur();}
/* back to the message: the bar, or a link to it */
function toPage(){if(!staged)return;var s=history.state;
if(moved<1&&s&&fr&&s.lmStage===fr.lmId){history.back();return;}
try{history.pushState({lmMsg:1},'',BACK);}catch(e){}reveal();}
w.addEventListener('popstate',function(e){var s=e.state;
if(s&&s.lmStage){if(wrap&&fr&&fr.lmId===s.lmStage){if(fr.lmShown)show();}else{seq=Math.max(seq,s.lmStage);mount(s.lmStage,location.href);}}
else if(staged)reveal();});
w.addEventListener('pageshow',function(e){if(!e.persisted)return;var s=history.state;
if(s&&s.lmStage&&fr&&fr.lmId===s.lmStage)show();else if(staged)reveal();draw();});
/* where the bar sits: 8 px over the frame's tab bar; out of the way where there is none, while typing, live */
function place(){if(!mini)return;var x=doc,ok=on&&staged&&!live&&!typing&&!!(x&&x.body),r=null,nav;
if(ok){nav=x.querySelector('.mb-nav');r=nav&&nav.getBoundingClientRect();
ok=!!(r&&r.width&&r.height&&x.defaultView.getComputedStyle(nav).visibility!=='hidden');}
if(x&&x.body)x.body.classList.toggle('lm-mini-pad',ok);mini.hidden=!ok;if(!ok)return;
var f=fr.getBoundingClientRect(),s=mini.style,g;
if(r.height>f.height*0.6){g=f.left+r.right+16;s.left=Math.round(g)+'px';s.width=Math.round(Math.min(420,f.right-g-16))+'px';
s.bottom=Math.round(innerHeight-f.bottom+16)+'px';}
else{g=r.left<4?8:0;s.left=Math.round(f.left+r.left+g)+'px';s.width=Math.round(r.width-2*g)+'px';
s.bottom=Math.round(innerHeight-(f.top+r.top)+8)+'px';}}
function keys(e){var t=e.target,y=e.type==='focusin'&&!!t&&(t.isContentEditable||(/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)
&&!/^(button|submit|checkbox|radio|range|reset|file|image|color|hidden)$/i.test(t.type||'')));if(y!==typing){typing=y;place();}}
function other(e){var t=e.target;if(!cur||!t||!/^(AUDIO|VIDEO)$/.test(t.tagName))return;if(cur.f)cur.m.pause();else close();}
w.addEventListener('resize',place);
if(w.matchMedia){var q=matchMedia('(prefers-color-scheme: dark)');var f2=function(){if(staged&&doc&&doc.body)look(doc);};
if(q.addEventListener)q.addEventListener('change',f2);else if(q.addListener)q.addListener(f2);}
})();</script>"""

JS = (_JS.replace("%ICONS%", json.dumps(ICONS, separators=(",", ":")))
      .replace("%TOKENS%", json.dumps(list(TOKENS), separators=(",", ":")))
      .replace("%OUT%", json.dumps(OUT_RE)))


def page_script(body: str) -> str:
    """What a page in the new look adds at its foot for the mini player: the
    script, on a page with a marked player (data-lm-media) for someone the
    switch shows it to; '' everywhere else, so every other page is what it
    was."""
    if "data-lm-media" not in (body or "") or not here():
        return ""
    return JS


# ─── the bar's look (in /my/lumen.<hash>.css: member_lumen_ui.templates) ──
# The bar lives on the message page, laid over the frame; its colours are
# the frame's page's (the script copies them onto it), so every look works.
# Motion only when the phone allows it.
CSS = Template("""
/* the mini player (member_mini): the message plays on while the member moves around */
body.lm .lm-stagew{position:fixed;inset:0;z-index:2147483000;box-sizing:border-box;margin:0;background:var(--bg);
  padding:env(safe-area-inset-top,0px) env(safe-area-inset-right,0px) env(safe-area-inset-bottom,0px) env(safe-area-inset-left,0px);
  opacity:0;visibility:hidden;pointer-events:none;}
body.lm .lm-stagew[data-on]{opacity:1;visibility:visible;pointer-events:auto;}
body.lm .lm-stagew.lm-own-safe{padding:0;}
body.lm .lm-stage{display:block;width:100%;height:100%;margin:0;border:0;background:transparent;}
body.lm .lm-stageload{position:fixed;left:0;right:0;top:env(safe-area-inset-top,0px);height:2px;visibility:visible;pointer-events:none;
  background:var(--acc-fill);transform-origin:0 50%;transform:scaleX(.7);}
body.lm .lm-stagew[data-on] .lm-stageload{display:none;}
html:has(>body.lm).lm-staged{overscroll-behavior:none;}
body.lm .lm-mini{position:fixed;z-index:2147483001;left:12px;right:auto;bottom:calc(88px + env(safe-area-inset-bottom,0px));
  box-sizing:border-box;height:62px;display:flex;align-items:center;gap:0;padding:0 4px 0 8px;overflow:hidden;border-radius:16px;
  background:var(--bg);color:var(--fg);box-shadow:0 0 0 1px var(--lm-line),0 10px 30px var(--lm-shadow);font-family:var(--mb-ui);
  -webkit-tap-highlight-color:transparent;}
body.lm .lm-mini[hidden],body.lm .lm-mini [hidden]{display:none;}
body.lm .lm-mini-go{flex:1;min-width:0;height:62px;display:flex;align-items:center;gap:10px;color:inherit;text-decoration:none;}
body.lm .lm-mini-th{position:relative;width:46px;height:46px;flex:none;border-radius:10px;overflow:hidden;display:grid;place-items:center;
  background:var(--acc-fill);color:var(--on-acc);}
body.lm .lm-mini-th img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;}
body.lm .lm-mini-tx{min-width:0;}
body.lm .lm-mini-tx b{display:block;font:700 14px/1.25 var(--mb-ui);letter-spacing:-.005em;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
body.lm .lm-mini-tx small{display:block;margin-top:2px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;font-variant-numeric:var(--lm-nvn,tabular-nums);}
body.lm .lm-mini-b{width:44px;height:44px;flex:none;display:grid;place-items:center;margin:0;padding:0;border:0;border-radius:50%;
  background:none;color:var(--fg);cursor:pointer;}
body.lm .lm-mini-line{position:absolute;left:0;right:0;bottom:0;height:2px;pointer-events:none;}
body.lm .lm-mini-line i{display:block;width:0;height:100%;background:var(--acc-fill);}
body.lm .lm-mini-go:focus-visible,body.lm .lm-mini-b:focus-visible{outline:2px solid var(--acc);outline-offset:-2px;}
@media (prefers-reduced-motion:no-preference){
  body.lm .lm-stagew{transition:opacity .2s ease,visibility 0s linear .2s;}
  body.lm .lm-stagew[data-on]{transition:opacity .2s ease;}
  body.lm .lm-mini{animation:lmMiniIn .34s cubic-bezier(.2,.8,.2,1) both;transition:background-color .25s,color .25s;}
  body.lm .lm-mini-b{transition:transform .3s cubic-bezier(.3,1.35,.5,1);}
  body.lm .lm-mini-b:active{transform:scale(.9);}
  body.lm .lm-stageload{animation:lmStageLoad 1.6s cubic-bezier(.2,.8,.2,1) both;}
}
@keyframes lmStageLoad{from{transform:scaleX(0)}to{transform:scaleX(.85)}}
@keyframes lmMiniIn{from{opacity:0;transform:translateY(14px)}}
/* a page in the frame makes room at its foot for the bar */
@media (max-width:1099px){body.lm.lm-mini-pad .mp-shell.mb-has-nav{padding-bottom:calc(188px + env(safe-area-inset-bottom,0px));}}
@media (min-width:1100px){body.lm.lm-mini-pad .mp-shell{padding-bottom:110px;}}
""")


# ─── the frame's headers ───────────────────────────────────────────────


def frame_request(request: Any) -> bool:
    """A page asked for by a frame on the same site (the mini player's
    frame): Sec-Fetch-Dest: iframe and Sec-Fetch-Site: same-origin. A
    browser that sends no fetch metadata never qualifies (the frame is
    refused and the page loads the ordinary way)."""
    try:
        h = request.headers
        return ((h.get("sec-fetch-dest") or "").strip().lower() == "iframe"
                and (h.get("sec-fetch-site") or "").strip().lower() == "same-origin")
    except Exception:
        return False


def allow_frame(request: Any, resp: Any) -> Any:
    """The member page's answer, framed by the mini player: for someone the
    switch shows it to (here(), decided from this request's session) and a
    request from a same-site frame (frame_request), the page's frame
    refusal (X-Frame-Options: DENY, frame-ancestors 'none') becomes "this
    site only" (SAMEORIGIN, 'self'). Every other answer is untouched, so
    another site's frame is still refused, and so is a frame for anyone
    the switch doesn't show it to (their page then loads the ordinary way).
    Any other header value is left alone. Never raises."""
    try:
        if resp is None or not here() or not frame_request(request):
            return resp
        h = resp.headers
        if (h.get("x-frame-options") or "").strip().upper() == "DENY":
            h["X-Frame-Options"] = "SAMEORIGIN"
        if (h.get("content-security-policy") or "").strip() == "frame-ancestors 'none'":
            h["Content-Security-Policy"] = "frame-ancestors 'self'"
    except Exception:
        pass
    return resp
