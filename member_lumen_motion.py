"""member_lumen_motion.py — Lumen Next's motion: how the member app's new
look ("Lumen", member_lumen.py) moves, and Watch and Live as a cinema.

Kevin, 2026-11-19, on the Lumen Next mock (artifact 2nFp9X3q…): "go with
font A and build all the moments". The mock's idea is "calm by default,
alive on touch": nothing moves on its own, every tap moves something.

THE MOVES (all CSS, in /my/lumen.<hash>.css; reduced motion gets none):
  - Pages move like a phone's: a pushed page slides in from the right and
    back out to it (a tab change fades up), while the top bar and the tab
    bar stay put. The cross-document view transitions member_app_ui
    turned on (MOTION_CSS) do the work; the script below says which way.
  - Shared elements: a message's picture (Watch's latest, a row's
    thumbnail, Home's tile) grows into the player on its page, and a
    conversation's face and name travel from the inbox row into the bar at
    the top, and back again.
  - The tab bar floats, its highlight springs from tab to tab and the
    tab you land on pops.
  - A main tab's blocks arrive one after another, and a page's serif
    heading settles in with its italic word landing last.
  - Buttons and rows give under a finger and spring back.
  Springs are linear() curves (Chrome 113, Safari 17.2); older browsers
  get a plain ease, and a browser without cross-document view transitions
  (before Chrome 126 or Safari 18.2) changes pages as it always has.

THE CINEMA. Every page under the Watch tab (Watch, a series, a message,
the live room and Live between services: body.pg-watch) goes dark,
whatever base the church picked or look the member chose, through the new
look's one dark switch (body.lm-dark, set by member_portal._shell), in the
cinema's neutral black instead of the reader's warm night: the church's
colour is its "lit" shade
(member_app_ui.palette, readable on black), the family inks their dark
shades. Watch's latest message runs edge to edge under a serif title, the
series are posters on a rail, the messages rows with wide thumbnails.

LIVE. The hearts rise over the video instead of beside the box, and so
does an "Amen" (or "Hallelujah") or praying hands when someone sends that
in the chat: the room's own hearts count and its own chat, read by a
script that watches what the room's script draws (member_portal_live's
ROOM_JS is untouched). Under the title: how many are here with the faces
of who spoke last, and Amen · a heart · Praying, which send the room's
own quick reply (at most one each six seconds; a tap in between only
rises on your phone) and its heart.

Pure functions, no I/O.
"""
from __future__ import annotations

from string import Template
from typing import Optional

# The cinema's page colour (the phone's bar at the top matches it).
CINE_BG = "#050506"


def cine(tab: Optional[str]) -> bool:
    """Whether a page sits under the Watch tab, the cinema's pages. They
    take the new look's one dark switch whatever the member's look
    (member_lumen_look.page_look), and this sheet makes that dark the
    cinema's neutral black rather than the look's near-black or the
    reader's warm night."""
    import member_app_ui as ui
    return ui.TAB_OF.get(tab or "", "") == "watch"


# Which way a page change goes, and what travels. A click on one of our
# links notes the page it leaves (how deep it is: a main tab 0, a pushed
# page 1, a conversation 2) and names what will travel; the next page, as it
# is revealed, compares depths (deeper: push; shallower: pop; a main tab to
# another: tab) and, coming back, names the link that leads to the page it
# came from, so the face or the picture flies back into its row. The names
# are cleared once the move is over, and on a page the browser kept.
# A page carries it in its <head> (member_portal._shell), so it is listening
# when the page is first revealed, which can come before the parser reaches
# the foot of a long page. Give draws its own document, so there it rides at
# the foot (member_portal.lumen_chrome); a second copy would do nothing.
JS = ("<script>(function(){if(window.__lmvt)return;window.__lmvt=1;"
      "var d=document,h=d.documentElement,K='lm-vt',named=[];"
      "var still=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;"
      "function kind(){var c=d.body?d.body.classList:null;"
      "return !c?0:(c.contains('lm-thread')?2:(c.contains('lm-push')?1:0));}"
      "function put(){try{sessionStorage.setItem(K,JSON.stringify({k:kind(),p:location.pathname+location.search,"
      "t:Date.now()}));}catch(e){}}"
      "function got(){try{var v=JSON.parse(sessionStorage.getItem(K)||'null');return v&&Date.now()-v.t<20000?v:null;}"
      "catch(e){return null;}}"
      "function clear(){named.forEach(function(e){e.style.removeProperty('view-transition-name');});named=[];}"
      "function name(ps){clear();ps.forEach(function(p){if(p[0]){p[0].style.setProperty('view-transition-name',p[1]);"
      "named.push(p[0]);}});}"
      "function path(a){try{var u=new URL(a.href,location.href);return u.origin===location.origin?u.pathname+u.search:'';}"
      "catch(e){return '';}}"
      "function from(a){var r=a.closest('.lm-irow');"
      "if(r)return [[r.querySelector('.lm-av,.lm-cl'),'lm-face'],[r.querySelector('.lm-itop b'),'lm-ttl']];"
      "if(/^\\/my\\/sermons\\/[^\\/?#]+$/.test(path(a))){var x=a.closest('.lm-feat');"
      "if(x)return [[x.querySelector('.lm-poster'),'lm-sermon']];"
      "x=a.closest('.lm-lrow');if(x)return [[x.querySelector('.lm-th'),'lm-sermon']];"
      "x=a.closest('.lm-tile');if(x)return [[x.querySelector('.img'),'lm-sermon']];}return [];}"
      "var t=0;d.addEventListener('click',function(e){"
      "if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;"
      "var a=e.target.closest&&e.target.closest('a[href]');if(!a||a.target||!path(a))return;"
      "put();if(still)return;name(from(a));clearTimeout(t);t=setTimeout(clear,4000);},true);"
      "addEventListener('pageswap',put);addEventListener('pagehide',put);"
      "addEventListener('pageshow',function(e){if(e.persisted){clear();h.removeAttribute('data-vt');}});"
      "addEventListener('pagereveal',function(e){var vt=e.viewTransition;if(!vt)return;"
      "var f=got(),me=kind(),dir='tab';"
      "if(f){dir=me>f.k?'push':(me<f.k?'pop':(me?'fade':'tab'));"
      "if(me<f.k){var ls=d.querySelectorAll('a[href]');for(var i=0;i<ls.length;i++){"
      "if(path(ls[i])===f.p){var ps=from(ls[i]);if(ps.length){name(ps);break;}}}}}"
      "h.setAttribute('data-vt',dir);function done(){h.removeAttribute('data-vt');clear();}"
      "vt.finished.then(done,done);});"
      "})();</script>")


# The live room's reactions over the video (see LIVE above). The room's
# script draws a rising heart into #lv-hearts for every heart, yours and
# everyone's; this draws the same heart over the video. A new chat line
# that is just "Amen", "Hallelujah" or "Praying" rises there too (lines the
# page already had never do, nor a list the room redraws).
ROOM_JS = ("<script>(function(){var d=document,rx=d.getElementById('lm-rxl');if(!rx)return;"
           "var tpl=d.getElementById('lm-rx-tpl'),hs=d.getElementById('lv-hearts'),list=d.getElementById('mb-chat'),"
           "bar=d.getElementById('lm-rx'),quick=d.getElementById('lv-quick'),say=d.getElementById('mb-say'),"
           "send=d.getElementById('lv-send'),seen={},last={};"
           "function icon(k){var t=tpl&&tpl.content.querySelector('[data-k='+k+']');return t?t.cloneNode(true):null;}"
           "function rise(k,w){if(rx.childElementCount>18)return;var s=d.createElement('span');s.className='lm-rz '+k;"
           "s.style.setProperty('--x',Math.round(Math.random()*34)+'px');"
           "s.style.setProperty('--dur',(2.6+Math.random()*1.1).toFixed(2)+'s');"
           "if(k==='amen')s.textContent=w;else{var i=icon(k);if(i)s.appendChild(i);}"
           "rx.appendChild(s);setTimeout(function(){s.remove();},4200);}"
           "function kindOf(t){t=String(t||'').toLowerCase().replace(/[^a-z ]/g,' ').replace(/\\s+/g,' ').trim();"
           "if(t==='amen'||t==='amen amen')return ['amen','Amen'];if(t==='hallelujah')return ['amen','Hallelujah'];"
           "if(t==='praying'||t==='praying for you'||t==='praying with you')return ['hands',''];return null;}"
           "function words(li){var p=li.querySelector('p'),n=p&&p.lastChild;return n&&n.nodeType===3?n.nodeValue:'';}"
           "if(hs)new MutationObserver(function(ms){ms.forEach(function(m){[].forEach.call(m.addedNodes,function(n){"
           "if(n.classList&&n.classList.contains('lv-heart'))rise('heart');});});}).observe(hs,{childList:true});"
           "if(list){[].forEach.call(list.querySelectorAll('li[data-id]'),function(li){seen[li.getAttribute('data-id')]=1;});"
           "new MutationObserver(function(ms){var n=0;ms.forEach(function(m){[].forEach.call(m.addedNodes,function(li){"
           "if(li.nodeType!==1||li.tagName!=='LI')return;var id=li.getAttribute('data-id');"
           "if(id){if(seen[id])return;seen[id]=1;}if(++n>3)return;var k=kindOf(words(li));if(k)rise(k[0],k[1]);});});})"
           ".observe(list,{childList:true});}"
           "if(bar)bar.addEventListener('click',function(e){var b=e.target.closest('button');if(!b)return;e.preventDefault();"
           "if(b.hasAttribute('data-heart')){if(!send||!say)return;var t=say.value;"
           "if(t){say.value='';say.dispatchEvent(new Event('input'));}send.click();"
           "if(t){say.value=t;say.dispatchEvent(new Event('input'));}return;}"
           "var v=b.value,now=Date.now(),k=kindOf(v);"
           "if(!quick||now-(last[v]||0)<6000){if(k)rise(k[0],k[1]);return;}last[v]=now;"
           "var q=null,ql=quick.querySelectorAll('button');for(var i=0;i<ql.length;i++)if(ql[i].value===v)q=ql[i];"
           "var tmp=!q;if(tmp){q=d.createElement('button');q.type='submit';q.name='body';q.value=v;q.hidden=true;"
           "quick.appendChild(q);}q.click();if(tmp)q.remove();});"
           "})();</script>")


# The springs (the mock's): --lm-spring overshoots a little and settles,
# --lm-soft eases in without the bounce. A browser without linear() keeps
# the plain curves first written.
_SPRING = ("linear(0,.009,.035 2.1%,.141,.281 6.7%,.723 12.9%,.938 16.7%,1.017,1.077,1.121,1.149 24.3%,1.159,1.163,"
           "1.161,1.154 29.9%,1.129 32.8%,1.051 39.6%,1.017 43.1%,.991,.977 51%,.974 53.8%,.975 57.1%,.997 69.8%,"
           "1.003 76.9%,1.004 83.8%,1)")
_SOFT = ("linear(0,.006,.025 2.8%,.101 6.1%,.539 18.9%,.721 25.3%,.849 31.5%,.937 38.1%,.968 41.8%,.991 45.7%,"
         "1.006 50.1%,1.015 55%,1.017 63.9%,1.001)")

CSS = Template("""
/* Lumen Next: motion and the cinema (member_lumen_motion) */
body.lm{--lm-spring:cubic-bezier(.3,1.35,.5,1);--lm-soft:cubic-bezier(.2,.9,.25,1);--lm-out:cubic-bezier(.2,.8,.2,1);}
@supports (transition-timing-function:linear(0,1)){body.lm{--lm-spring:""" + _SPRING + """;--lm-soft:""" + _SOFT + """;}}

/* pages: a pushed page slides in from the right and back, a tab fades up; the bars stay put */
@media (prefers-reduced-motion:no-preference){
  ::view-transition-group(*){animation-duration:.5s;animation-timing-function:cubic-bezier(.2,.9,.25,1);}
  ::view-transition-old(root),::view-transition-new(root){animation-duration:.36s;animation-timing-function:cubic-bezier(.2,.8,.2,1);}
  html[data-vt=push]::view-transition-old(root){animation-name:lmVtOutL;}
  html[data-vt=push]::view-transition-new(root){animation-name:lmVtInR;}
  html[data-vt=pop]::view-transition-old(root){animation-name:lmVtOutR;}
  html[data-vt=pop]::view-transition-new(root){animation-name:lmVtInL;}
  html[data-vt=tab]::view-transition-old(root){animation-name:lmVtFade;animation-duration:.16s;}
  html[data-vt=tab]::view-transition-new(root){animation-name:lmVtUp;animation-duration:.38s;}
  /* what travels: a message's picture into the player, a face and a name into the bar */
  html:active-view-transition body.lm .mb-player{view-transition-name:lm-sermon;}
  html:active-view-transition body.lm .lm-thead>.lm-av,html:active-view-transition body.lm .lm-thead>.lm-cl{view-transition-name:lm-face;}
  html:active-view-transition body.lm .lm-thead b{view-transition-name:lm-ttl;}
  ::view-transition-group(lm-sermon),::view-transition-group(lm-face),::view-transition-group(lm-ttl){animation-duration:.55s;}
  /* a face and a name fly over the bar they land in (the old page painted them under it) */
  ::view-transition-group(lm-face),::view-transition-group(lm-ttl){z-index:1;}
  ::view-transition-old(lm-sermon),::view-transition-new(lm-sermon){height:100%;width:100%;object-fit:cover;}
  ::view-transition-group(lm-ind){animation-duration:.65s;}
  /* the bars keep today's short change (member_app_ui.MOTION_CSS) */
  ::view-transition-group(mb-top),::view-transition-group(mb-nav){animation-duration:.18s;}
  /* into a conversation (no tab bar) the bar fades away, and back again it fades in */
  ::view-transition-old(mb-nav):only-child{animation:lmVtFade .2s ease both;}
  ::view-transition-new(mb-nav):only-child{animation:lmVtIn .3s ease both;}
}
@supports (transition-timing-function:linear(0,1)){@media (prefers-reduced-motion:no-preference){
  ::view-transition-group(lm-sermon),::view-transition-group(lm-face),::view-transition-group(lm-ttl){animation-timing-function:""" + _SOFT + """;}
  ::view-transition-group(lm-ind){animation-timing-function:""" + _SPRING + """;}
}}
@keyframes lmVtOutL{to{transform:translateX(-24%);opacity:0}}
@keyframes lmVtInR{from{transform:translateX(42%);opacity:0}}
@keyframes lmVtOutR{to{transform:translateX(34%);opacity:0}}
@keyframes lmVtInL{from{transform:translateX(-24%);opacity:0}}
@keyframes lmVtFade{to{opacity:0}}
@keyframes lmVtIn{from{opacity:0}}
@keyframes lmVtUp{from{opacity:0;transform:translateY(10px)}}

/* a main tab's blocks arrive one after another; a serif heading settles, its italic word last */
@media (prefers-reduced-motion:no-preference){
  body.lm.lm-tab .mp-shell>*{animation:lmArrive .7s var(--lm-out) backwards;}
  body.lm.lm-tab .mp-shell>:nth-child(2){animation-delay:.06s;}
  body.lm.lm-tab .mp-shell>:nth-child(3){animation-delay:.12s;}
  body.lm.lm-tab .mp-shell>:nth-child(4){animation-delay:.18s;}
  body.lm.lm-tab .mp-shell>:nth-child(5){animation-delay:.24s;}
  body.lm.lm-tab .mp-shell>:nth-child(n+6){animation-delay:.3s;}
  body.lm .lm-disp{animation:lmSettle .9s var(--lm-out) backwards;}
  body.lm .lm-disp em{display:inline-block;animation:lmSettleEm 1.1s var(--lm-out) .22s backwards;}
  /* a finger presses in; letting go springs back */
  body.lm .lm-btn,body.lm .lm-icb,body.lm .lm-wrow,body.lm .lm-pray,body.lm .lm-room,body.lm .lm-tile,body.lm .lm-acad,
  body.lm .lm-page,body.lm .lm-gcard,body.lm .lm-spost,body.lm .lm-lrow,body.lm .lm-nrow,body.lm .lm-rxb{
    transition:transform .45s var(--lm-spring),background-color .25s,color .25s,box-shadow .25s;}
  body.lm .lm-btn:active,body.lm .lm-icb:active{transform:scale(.94);}
  body.lm .lm-spost:active,body.lm .lm-rxb:active{transform:scale(.95);}
}
@keyframes lmArrive{from{opacity:0;transform:translateY(16px)}}
@keyframes lmSettle{from{opacity:0;transform:translateY(14px);filter:blur(5px)}}
@keyframes lmSettleEm{from{opacity:0;transform:translateY(12px) skewX(-6deg)}}
@keyframes lmTabPop{from{transform:scale(.72) translateY(3px)}}

/* the tab bar floats: a rounded bar off the edges, a soft highlight that springs to your tab */
@media (max-width:1099px){
  .lm .mb-nav.lm-nav{left:12px;right:12px;bottom:max(14px,env(safe-area-inset-bottom,0px));max-width:576px;margin:0 auto;padding:6px;
    border:0;border-radius:24px;background:var(--bg);box-shadow:0 12px 32px -12px var(--lm-shadow),0 0 0 1px var(--lm-line);}
  .lm .lm-nav .mb-tab{position:relative;z-index:1;min-height:54px;gap:4px;border-radius:18px;}
  .lm-ind{top:6px;bottom:6px;left:6px;width:calc((100% - 12px) / var(--n));height:auto;border-radius:18px;background:var(--lm-tint-12);}
  .lm-ind::after{display:none;}
  .lm .mp-shell.mb-has-nav{padding-bottom:calc(118px + env(safe-area-inset-bottom,0px));}
}
@media (max-width:1099px) and (prefers-reduced-motion:no-preference){
  .lm .lm-nav .mb-tab[aria-current] svg{animation:lmTabPop .6s var(--lm-spring) backwards;}
  /* each tab moves on its own, over the highlight sliding under it */
  html:active-view-transition .lm .lm-nav .mb-tab[href="/my"]{view-transition-name:lm-t-home;}
  html:active-view-transition .lm .lm-nav .mb-tab[href="/my/sermons"]{view-transition-name:lm-t-watch;}
  html:active-view-transition .lm .lm-nav .mb-tab[href="/my/bible"]{view-transition-name:lm-t-bible;}
  html:active-view-transition .lm .lm-nav .mb-tab[href="/my/connect"]{view-transition-name:lm-t-connect;}
  html:active-view-transition .lm .lm-nav .mb-tab[href="/my/give"]{view-transition-name:lm-t-give;}
  html:active-view-transition .lm .lm-nav .mb-tab[href="/my/lead"]{view-transition-name:lm-t-lead;}
  html:active-view-transition .lm .lm-nav .mb-tab[href="/my/board"]{view-transition-name:lm-t-board;}
  ::view-transition-group(lm-t-home),::view-transition-group(lm-t-watch),::view-transition-group(lm-t-bible),
  ::view-transition-group(lm-t-connect),::view-transition-group(lm-t-give),::view-transition-group(lm-t-lead),
  ::view-transition-group(lm-t-board){animation-duration:.3s;}
}

/* the cinema: every page under Watch takes the dark switch (lm-dark), in a neutral black */
body.lm.lm-dark.pg-watch{--bg:#050506;--s1:#151517;--s2:#1F1F22;--s3:#2C2C30;--line:rgba(255,255,255,.1);--fg:#F5F3EF;--fg2:#AAA7A2;--fg3:#8C8984;
  --acc:var(--acc-lit);--accent:var(--acc-lit);--focus:var(--acc-lit);--bar:rgba(5,5,6,.82);--hair:rgba(245,243,239,.1);
  --surface:#050506;--input-surface:#151517;--text-primary:#F5F3EF;--text-secondary:#AAA7A2;--text-muted:#8C8984;
  --border:rgba(255,255,255,.1);--mb-surface:#151517;--mb-surface-2:#1F1F22;--mb-line:rgba(255,255,255,.1);--error:#FF6B5E;
  --gold-ink:var(--gold-lit);--teal-ink:var(--teal-lit);--violet-ink:var(--violet-lit);--coral-ink:var(--coral-lit);
  --gold-deep:var(--gold-night);--teal-deep:var(--teal-night);--violet-deep:var(--violet-night);--coral-deep:var(--coral-night);
  --acc-deep:var(--acc-night);--lm-line:rgba(255,255,255,.1);--lm-shadow:rgba(0,0,0,.7);color-scheme:dark;}
@supports (color:color-mix(in oklab,red 50%,blue)){body.lm.lm-dark.pg-watch{--acc:color-mix(in oklab,var(--acc-lit) 62%,#fff);}}
.lm.lm-tab.pg-watch .mb-top::after{display:none;}
html:has(>body.lm.lm-dark.pg-watch){background:#050506;color-scheme:dark;}
@media (max-width:1099px){.lm.pg-watch .mb-nav.lm-nav{background:#161618;box-shadow:0 12px 32px -12px rgba(0,0,0,.7),0 0 0 1px rgba(255,255,255,.08);}}
.lm.pg-watch .lm-ind{background:var(--lm-tint-12);}
@supports (background:color-mix(in srgb,red 50%,blue)){.lm.pg-watch .lm-ind{background:color-mix(in srgb,var(--acc-fill) 28%,#161618);}}

/* Watch: the next live as a card, the latest edge to edge under a serif title, posters on a rail */
.lm.pg-watch .lm-nrow{margin:6px 0 18px;padding:12px 14px;border:0;border-radius:16px;background:var(--s1);}
.lm.pg-watch .lm-nrow .lm-halo{width:40px;height:40px;border-radius:12px;background:var(--s2);}
.lm.pg-watch .lm-nrow.is-live{background:#E11D48;color:#fff;}
.lm.pg-watch .lm-nrow.is-live .lm-kicker,.lm.pg-watch .lm-nrow.is-live .lm-wt>span,.lm.pg-watch .lm-nrow.is-live .lm-chev{color:#fff;}
.lm.pg-watch .lm-nrow.is-live .lm-halo{background:rgba(255,255,255,.18);color:#fff;}
.lm.pg-watch .lm-nrow.is-live .lm-dotlive{background:#fff;}
.lm.pg-watch .lm-feat{margin-top:0;}
.lm.pg-watch .lm-feat .lm-poster{aspect-ratio:auto;height:310px;}
.lm .lm-featk{margin:22px 0 0;color:var(--violet-ink);}
.lm .lm-featk .lm-dot{background:var(--violet-ink);}
.lm .lm-feat .lm-disp{margin-top:10px;}
.lm .lm-feat .lm-disp a{color:inherit;text-decoration:none;}
.lm .lm-feat .lm-acts{margin-top:20px;}
.lm .lm-btn.lm-light{background:#fff;color:#0b0b0c;}
.lm .lm-feat .lm-btn.ghost{background:var(--s1);color:var(--fg);}
.lm .lm-sposts{gap:12px;scroll-padding-inline:20px;}
.lm .lm-spost{position:relative;width:148px;height:214px;border-radius:16px;overflow:hidden;display:flex;flex-direction:column;
  background:var(--s1);color:var(--fg);text-decoration:none;}
.lm .lm-spost .img{position:relative;flex:1;overflow:hidden;background:var(--s2);}
.lm .lm-spost .img>*{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm .lm-spost .img .mb-art-title,.lm .lm-spost .img .mb-titled b,.lm .lm-spost .img .mb-art-kick,.lm .lm-spost .img .mb-art-play{display:none;}
.lm .lm-sptx{display:block;padding:10px 12px 13px;}
.lm .lm-sptx .lm-kicker{font-size:9px;letter-spacing:.16em;margin-bottom:7px;}
.lm .lm-sptx .tt{display:block;font:400 19px/1.02 var(--mb-serif);font-weight:var(--lm-dw,400);letter-spacing:-.02em;
  font-variation-settings:var(--lm-dvar,normal);font-stretch:var(--lm-dst,100%);}
.lm .lm-sptx .tt em{font-style:italic;font-weight:var(--lm-iw,400);color:var(--acc);}
.lm.pg-watch .lm-lrow .lm-th{width:96px;height:60px;border-radius:12px;}
.lm.pg-watch .lm-lrow .lm-wt b{font-size:15px;}

/* a message: the player edge to edge, the title in serif */
.lm.pg-watch.lm-push .mb-player{margin:0 -20px;border-radius:0;overflow:hidden;background:#000;}
.lm.pg-watch.lm-push .mb-player .mb-video,.lm.pg-watch.lm-push .mb-player>.mb-art,.lm.pg-watch.lm-push .mb-player>.mb-ph,
.lm.pg-watch.lm-push .mb-player>.mb-titled{border-radius:0;}
.lm.pg-watch.lm-push .mp-shell>h1{font:400 34px/1.05 var(--mb-serif);font-weight:var(--lm-dw,400);letter-spacing:var(--lm-dtr,-.025em);
  font-variation-settings:var(--lm-dvar,normal);font-stretch:var(--lm-dst,100%);}

/* Live: reactions rising over the video, who's here, Amen · heart · Praying */
.lm .lm-rxl{position:absolute;z-index:2;right:10px;bottom:10px;top:52px;width:96px;overflow:hidden;pointer-events:none;}
.lm .lm-rz{position:absolute;bottom:0;left:var(--x);display:grid;place-items:center;color:#fff;opacity:0;}
.lm .lm-rz svg{display:block;width:28px;height:28px;filter:drop-shadow(0 2px 6px rgba(0,0,0,.35));}
.lm .lm-rz.heart{color:#FF5C7A;}
.lm .lm-rz.hands{color:#FFD27A;}
.lm .lm-rz.amen{left:calc(var(--x) * .5);padding:7px 10px;border-radius:13px;background:rgba(255,255,255,.22);font:700 13px/1 var(--mb-ui);
  white-space:nowrap;-webkit-backdrop-filter:blur(6px);backdrop-filter:blur(6px);}
@media (prefers-reduced-motion:no-preference){.lm .lm-rz{animation:lmFloat var(--dur,3s) var(--lm-out) forwards;}}
@media (prefers-reduced-motion:reduce){.lm .lm-rz{animation:lmRzFade 1.2s ease-out forwards;}}
@keyframes lmFloat{0%{transform:translateY(0) scale(.4);opacity:0}12%{opacity:1;transform:translateY(-22px) scale(1.12)}
  100%{transform:translate(calc(var(--x) * -.4),-230px) scale(.92);opacity:0}}
@keyframes lmRzFade{0%{opacity:0}30%{opacity:1}100%{opacity:0}}
.lm .lv-room .lv-hearts{display:none;}
.lm .lv-info{flex-wrap:wrap;}
.lm .lm-watching{flex-basis:100%;display:flex;align-items:center;gap:10px;margin:12px 0 0;font:500 13.5px/1.35 var(--mb-ui);color:var(--fg2);}
.lm .lm-watching .lv-stack i{width:28px;height:28px;font-size:10px;box-shadow:0 0 0 2.5px var(--bg);}
.lm .lm-watching .lv-stack i+i{margin-left:-8px;}
.lm .lm-watching b{color:var(--fg);font-weight:650;font-variant-numeric:var(--lm-nvn,tabular-nums);}
.lm .lm-rxbar{flex-basis:100%;display:flex;gap:8px;margin:14px 0 2px;}
.lm .lm-rxb{height:44px;padding:0 16px;border:0;border-radius:22px;background:var(--s1);color:var(--fg);font:700 14px/1 var(--mb-ui);
  display:inline-flex;align-items:center;gap:7px;cursor:pointer;}
.lm .lm-rxb svg{width:20px;height:20px;}
.lm .lm-rxb.h{color:#FF5C7A;}
.lm .lm-rxb.p svg{color:#FFD27A;}
.lm .lm-rxb:focus-visible,.lm .lm-spost:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
@media (max-width:999px) and (orientation:landscape) and (max-height:520px){.lm .lm-watching,.lm .lm-rxbar{display:none;}}
""")
