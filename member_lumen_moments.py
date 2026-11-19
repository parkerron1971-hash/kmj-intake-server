"""member_lumen_moments.py — the moments in the member app's new look
("Lumen Next"): Prayer, Give and Messages.

Kevin, 2026-11-19, on the Lumen Next mock (artifact 2nFp9X3q…): "go with
font A and build all the moments". This file holds three areas' moments:
each one a small move that answers a tap, on the data the pages already
read (no new reads, no new records):

  PRAYER  Sending lights the flame: the request in, "Your pastors have
          it." rises over a flame that kindles, flickers and sends out
          three soft rings (member_portal_church's sent page). On a
          group's prayer wall, "I'm praying" turns flame-coloured, and the
          page that comes back from the tap lights the very request it
          was (the tap is still the plain form post; this script only
          remembers which request, in the tab's session storage).
  GIVE    The amount rolls like a counter, in tabular figures, as the
          giver taps amounts (member_lumen_give.GIVE_JS draws the digits;
          the give page's own payment script is untouched, byte for byte).
          While the payment form loads, the Give button spins; back from
          a gift, the thank-you draws its ring, fills, draws the check, and
          only then says "Thank you, <first name>."
  MESSAGES A message just sent flies up from the box (instant send draws
          the bubble; its ids, its answer and its behaviour are
          unchanged), and when the church's answer replaces it mid-flight
          the new bubble finishes the same flight. In a group's chat, the
          reaction picker (Love, Praying, Amen) springs open and a
          reaction lands in place: the same /react route, asking for its
          JSON answer (which it already gives), the chip popping in; a
          refusal falls back to the plain post, a lost answer reloads.

Everything moves only when the phone allows motion (prefers-reduced-
motion); with motion off the pages read the same, at rest.

CSS joins /my/lumen.<hash>.css (member_lumen_ui.templates); every rule sits
under body.lm. JS rides only on the pages that use it: a conversation
(member_portal._lumen_frame's head) and a group's prayer wall.
"""
from __future__ import annotations

from string import Template

CSS = Template("""
/* Lumen Next moments: Prayer, Give, Messages (member_lumen_moments) */
body.lm{--lmo-spring:linear(0,.009,.035 2.1%,.141,.281 6.7%,.723 12.9%,.938 16.7%,1.017,1.077,1.121,1.149 24.3%,1.159,1.163,
  1.161,1.154 29.9%,1.129 32.8%,1.051 39.6%,1.017 43.1%,.991,.977 51%,.974 53.8%,.975 57.1%,.997 69.8%,1.003 76.9%,1.004 83.8%,1);
  --lmo-out:cubic-bezier(.2,.8,.2,1);--lmo-flame:#D9481F;--lmo-flame-in:#FFC46E;}

/* Prayer: the flame that answers a request */
body.lm .lm-flamewrap{position:relative;width:150px;height:150px;margin:0 auto 14px;display:grid;place-items:center;}
body.lm .lm-hl{position:absolute;inset:0;border-radius:50%;border:1.5px solid color-mix(in srgb,var(--lmo-flame) 45%,transparent);opacity:0;}
body.lm .lm-fl{width:70px;height:90px;transform-origin:50% 100%;}
body.lm .lm-fl .lm-fo{fill:var(--lmo-flame);}
body.lm .lm-fl .lm-fi{fill:var(--lmo-flame-in);}
body.lm .lm-sent.is-lit .lm-disp em{color:var(--acc);}
/* a group's prayer wall: I'm praying, lit */
body.lm .gp-btn{transition:transform .45s var(--lmo-spring),background-color .35s,color .35s,box-shadow .35s;}
body.lm .gp-btn:active{transform:scale(.93);}
body.lm .gp-acts form:has(input[value="praying"]) .gp-btn.on{position:relative;background:var(--lmo-flame);color:#fff;box-shadow:none;}

/* Give: the amount rolls like a counter (a long amount steps down a size to stay on one line) */
body.lm .lm-amt{white-space:nowrap;}
body.lm .lm-amt[data-n="6"]{font-size:80px;}
body.lm .lm-amt[data-n="7"]{font-size:70px;}
body.lm .lm-amt[data-n="8"]{font-size:62px;}
body.lm .lm-amt[data-n="9"]{font-size:54px;}
body.lm .lm-amt [data-amt]{display:inline-flex;align-items:flex-start;margin:-.05em 0;}
body.lm .lm-od{display:inline-block;height:1em;line-height:1em;overflow:hidden;vertical-align:top;}
body.lm .lm-os{display:flex;flex-direction:column;}
body.lm .lm-os>span{display:block;height:1em;line-height:1em;}
body.lm .lm-odp{display:inline-block;line-height:1em;}
/* the Give button while the payment form loads */
body.lm .lm-gvform .gv-give:disabled{position:relative;color:transparent;}
body.lm .lm-gvform .gv-give:disabled::after{content:"";position:absolute;left:50%;top:50%;width:22px;height:22px;margin:-11px 0 0 -11px;
  box-sizing:border-box;border-radius:50%;border:2.5px solid color-mix(in srgb,var(--on-acc,#fff) 35%,transparent);
  border-top-color:var(--on-acc,#fff);animation:lmoSpin .8s linear infinite;}
/* the thank-you: the ring draws, fills, the check draws */
body.lm .lm-okring.lm-okdraw{box-shadow:none;}
body.lm .lm-okdraw svg{width:84px;height:84px;overflow:visible;}
body.lm .lm-okdraw .lm-okbg{fill:var(--acc-fill);}
body.lm .lm-okdraw .lm-okc{fill:none;stroke:var(--acc-fill);stroke-width:3;stroke-linecap:round;}
body.lm .lm-okdraw .lm-okp{fill:none;stroke:var(--on-acc,#fff);stroke-width:4.5;stroke-linecap:round;stroke-linejoin:round;}

/* Messages: a sent bubble's flight, the send button, reactions */
body.lm .lm-send{transition:opacity .2s,transform .45s var(--lmo-spring);}
body.lm .lm-send:active{transform:scale(.86);}

@media (prefers-reduced-motion:no-preference){
  body.lm .lm-fl{animation:lmoIgnite 1.2s var(--lmo-spring) both,lmoFlicker 2.4s ease-in-out 1.2s infinite;}
  body.lm .lm-hl{animation:lmoHalo 2.8s var(--lmo-out) .7s 3;}
  body.lm .lm-hl:nth-child(2){animation-delay:1.6s;}
  body.lm .lm-hl:nth-child(3){animation-delay:2.5s;}
  body.lm .lm-sent.is-lit .lm-disp,body.lm .lm-sent.is-lit .lm-disp+p{animation:lmoRise .7s var(--lmo-out) .45s both;}
  body.lm .gp-btn.lm-lit{animation:lmoLit .6s var(--lmo-spring);}
  body.lm .gp-btn.lm-lit .mb-ic{animation:lmoPop .55s var(--lmo-spring);}
  body.lm .gp-btn.lm-lit::after{content:"";position:absolute;inset:-5px;border-radius:999px;border:2px solid var(--lmo-flame);
    opacity:0;animation:lmoRing .9s var(--lmo-out);pointer-events:none;}
  body.lm .lm-os{transition:transform .8s var(--lmo-spring);}
  body.lm dialog.lm-gave[open] .lm-okring.lm-okdraw{animation:none;}
  body.lm dialog.lm-gave[open] .lm-okdraw .lm-okc{stroke-dasharray:252;transform-box:fill-box;transform-origin:center;
    animation:lmoArc 1s var(--lmo-out) both;}
  body.lm dialog.lm-gave[open] .lm-okdraw .lm-okbg{transform-box:fill-box;transform-origin:center;animation:lmoPop .6s var(--lmo-spring) .9s both;}
  body.lm dialog.lm-gave[open] .lm-okdraw .lm-okp{stroke-dasharray:48;animation:lmoDraw .42s var(--lmo-out) 1.15s both;}
  body.lm dialog.lm-gave[open] h2,body.lm dialog.lm-gave[open] .gv-banner{animation:lmoRise .6s var(--lmo-out) 1.3s both;}
  body.lm .mis-pending,body.lm .lm-flew{animation:lmoFly .7s var(--lmo-spring) both;transform-origin:100% 100%;}
  body.lm .gc-d[open]>.gc-acts{animation:lmoTap .42s var(--lmo-spring) both;transform-origin:16px 0;}
  body.lm .gc-m.mine .gc-d[open]>.gc-acts{transform-origin:calc(100% - 16px) 0;}
  body.lm .gc-d[open]>.gc-acts>*{animation:lmoTb .5s var(--lmo-spring) both;}
  body.lm .gc-d[open]>.gc-acts>:nth-child(2){animation-delay:.04s;}
  body.lm .gc-d[open]>.gc-acts>:nth-child(3){animation-delay:.08s;}
  body.lm .gc-d[open]>.gc-acts>:nth-child(n+4){animation-delay:.12s;}
  body.lm .gc-chip.lm-pop{animation:lmoPop .55s var(--lmo-spring) both;}
}
@keyframes lmoIgnite{0%{transform:scale(.05,0);opacity:0}35%{opacity:1}100%{transform:none;opacity:1}}
@keyframes lmoFlicker{0%,100%{transform:none}25%{transform:scale(.97,1.04) skewX(1.6deg)}50%{transform:scale(1.02,.97) skewX(-1.2deg)}
  75%{transform:scale(.99,1.03) skewX(.8deg)}}
@keyframes lmoHalo{0%{transform:scale(.42);opacity:.9}100%{transform:scale(1.12);opacity:0}}
@keyframes lmoRise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
@keyframes lmoLit{0%{transform:scale(.9)}100%{transform:none}}
@keyframes lmoPop{from{transform:scale(.3);opacity:0}to{transform:none;opacity:1}}
@keyframes lmoRing{0%{opacity:.8;transform:scale(.92)}100%{opacity:0;transform:scale(1.25)}}
@keyframes lmoSpin{to{transform:rotate(360deg)}}
@keyframes lmoArc{0%{stroke-dashoffset:214;transform:rotate(0)}60%{stroke-dashoffset:150;transform:rotate(430deg)}
  100%{stroke-dashoffset:0;transform:rotate(720deg)}}
@keyframes lmoDraw{from{stroke-dashoffset:48}to{stroke-dashoffset:0}}
@keyframes lmoFly{from{transform:translate(-18px,64px) scale(.55);opacity:.2}to{transform:none;opacity:1}}
@keyframes lmoTap{from{transform:scale(.3);opacity:0}to{transform:none;opacity:1}}
@keyframes lmoTb{from{transform:scale(.2) translateY(12px);opacity:0}to{transform:none;opacity:1}}
""")


def flame() -> str:
    """The prayer's flame: three soft rings and the flame inside them."""
    return ('<span class="lm-flamewrap" aria-hidden="true"><span class="lm-hl"></span><span class="lm-hl"></span>'
            '<span class="lm-hl"></span><svg class="lm-fl" viewBox="0 0 78 100">'
            '<path class="lm-fo" d="M39 2c7 13 30 27 30 56a30 30 0 0 1-60 0c0-12 5-21 12-28 1 10 6 16 13 17-4-12-3-29 5-45z"/>'
            '<path class="lm-fi" d="M39 50c4 6 14 12 14 25a14 14 0 0 1-28 0c0-6 3-10 6-13 1 5 3 7 6 8-2-6-1-13 2-20z"/>'
            '</svg></span>')


def check() -> str:
    """The thank-you's mark: a ring that draws round, fills, and the check
    drawn over it."""
    return ('<span class="lm-okring lm-okdraw" aria-hidden="true"><svg viewBox="0 0 84 84">'
            '<circle class="lm-okbg" cx="42" cy="42" r="40"/><circle class="lm-okc" cx="42" cy="42" r="40"/>'
            '<path class="lm-okp" d="M27 43.5l10.5 10.5L58 32"/></svg></span>')


# The pages' few lines of script. A conversation: a sent bubble that the
# answer replaces mid-flight finishes its flight, and a reaction lands in
# place. A group's prayer wall: the request that was just prayed for is
# lit on the page that comes back. Storage can be missing (a private
# window); then nothing is remembered and nothing breaks.
JS = r"""<script>(function(){
var d=document,K='lm-moment',S=null,ORDER=['love','pray','amen'];
try{S=window.sessionStorage;}catch(e){}
function keep(v){try{if(S)S.setItem(K,JSON.stringify(v));}catch(e){}}
function take(){try{var v=S&&S.getItem(K);if(!v)return null;S.removeItem(K);v=JSON.parse(v);
  return v&&Date.now()-v.t<20000?v:null;}catch(e){return null;}}
var born=window.WeakMap?new WeakMap():null;
if(born&&window.MutationObserver)[].forEach.call(d.querySelectorAll('.mb-chat,.gc-list'),function(list){
  new MutationObserver(function(rs){var now=Date.now();rs.forEach(function(r){[].forEach.call(r.addedNodes,function(n){
    if(n.nodeType!==1)return;if(n.classList.contains('mis-pending')){born.set(n,now);return;}
    var o=r.removedNodes[0],t=o&&born.get(o);
    if(t&&now-t<700){n.style.animationDelay=(t-now)+'ms';n.classList.add('lm-flew');}});});}).observe(list,{childList:true});});
function pop(b){b.classList.remove('lm-pop');void b.offsetWidth;b.classList.add('lm-pop');}
function react(li,k,on){if(!li)return;
  var pi=li.querySelector('.gc-acts input[name=kind][value="'+k+'"]'),pk=pi&&pi.form.querySelector('button');
  if(pk){pk.classList.toggle('on',on);pk.setAttribute('aria-pressed',on?'true':'false');}
  var lab=pk?(pk.getAttribute('aria-label')||''):'',col=li.querySelector('.gc-col')||li,rx=col.querySelector('.gc-rx');
  var ci=rx&&rx.querySelector('input[name=kind][value="'+k+'"]'),cf=ci&&ci.form,cb=cf&&cf.querySelector('button');
  if(cb){var sp=cb.querySelectorAll('span'),c=sp[sp.length-1],n=Math.max(0,(parseInt(c.textContent,10)||0)+(on?1:-1));
    if(!n&&!on)cf.parentNode.removeChild(cf);
    else{c.textContent=n;cb.classList.toggle('on',on);cb.setAttribute('aria-pressed',on?'true':'false');cb.setAttribute('aria-label',lab+', '+n);if(on)pop(cb);}}
  else if(on&&pk){cf=pk.form.cloneNode(true);cb=cf.querySelector('button');cb.className='gc-chip on';
    var s=d.createElement('span');s.textContent='1';cb.appendChild(s);cb.setAttribute('aria-label',lab+', 1');
    if(!rx){rx=d.createElement('div');rx.className='gc-rx';col.appendChild(rx);}
    var at=null;[].some.call(rx.children,function(x){var i=x.querySelector('input[name=kind]');
      if(i&&ORDER.indexOf(i.value)>ORDER.indexOf(k)){at=x;return true;}return false;});
    rx.insertBefore(cf,at);pop(cb);}
  if(rx&&!rx.children.length)rx.parentNode.removeChild(rx);
  var det=li.querySelector('details.gc-d');if(det&&det.open){det.open=false;var su=det.querySelector('summary');if(su)su.focus();}}
d.addEventListener('submit',function(e){var f=e.target;if(!f||!f.matches)return;
  if(f.matches('form[action="/my/groups/prayer/mark"]')){var k=f.querySelector('input[name=kind]'),i=f.querySelector('input[name=id]'),
    b=f.querySelector('button');if(k&&k.value==='praying'&&i&&b&&!b.classList.contains('on'))keep({k:'pray',id:i.value,t:Date.now()});return;}
  if(!f.matches('.gc-d form[action$="/react"],.gc-rx form[action$="/react"]')||!window.fetch||!window.FormData||!window.URLSearchParams)return;
  e.preventDefault();if(f.getAttribute('data-busy'))return;f.setAttribute('data-busy','1');
  var li=f.closest('li'),kind=(f.querySelector('input[name=kind]')||{}).value;
  fetch(f.getAttribute('action'),{method:'POST',credentials:'same-origin',
    headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(f)).toString()})
  .then(function(r){return r.json().then(function(x){return x||{lost:1};},function(){return {lost:1};});},function(){return {lost:1};})
  .then(function(x){f.removeAttribute('data-busy');
    if(x.ok){react(li,kind,!!x.on);return;}
    if(x.lost){location.reload();return;}
    HTMLFormElement.prototype.submit.call(f);});});
var m=take();
if(m&&m.k==='pray'&&/[?&]done=praying(&|$)/.test(location.search))
  [].some.call(d.querySelectorAll('form[action="/my/groups/prayer/mark"] input[name=id]'),function(i){
    if(i.value!==m.id)return false;var b=i.form.querySelector('button.on');
    if(b){var c=b.closest('article')||b;if(c.scrollIntoView)c.scrollIntoView({block:'center'});b.classList.add('lm-lit');}return true;});
})();</script>"""
