"""
member_instant_send.py — a member's message shows in the conversation the
moment they tap Send (Kevin, 2026-11-18: "the members app move slow when
send messages in chat … how can that be sped up?", then "yes build all four").

Before this, sending was a full form post: the safety check (msg_screen,
about half a second to two), the save, a redirect, and a reload of the whole
conversation, while the screen sat frozen. Now, with JavaScript:

  1. the member's bubble goes into the conversation at once, marked
     "Sending…"; the box clears and keeps the keyboard up
  2. the same form posts by fetch with Accept: application/json, so the
     route answers JSON instead of a redirect
  3. sent: the bubble is swapped for the server's own (the same renderer
     the page uses) and says "Sent" for a moment
     held: the server's bubble carries "Held for review", and the page's
     own held notice shows above the box (until the next send)
     care: the page's own crisis notice (988, 911) shows above the box,
     exactly as the reloaded page showed it, and stays
     not sent (a cap, too soon, the check down, offline): the bubble goes,
     the words go back in the box, today's message says why, with Try again

Nothing about the rules moves. The safety check still runs on the server
before anyone else can see the message ("nothing goes out unchecked"); only
the sender's own screen stops waiting. Every cap, gap, block and preview
rule answers exactly as before, in words. The fetch goes through the same
route, so the same same-origin check (member_portal._same_origin; a fetch
always sends its real Origin) and the same SameSite=Lax session cookie hold.

No double sends: the box empties on the first tap, so a second tap has
nothing to send, and messages go one at a time in the order written. A
retry after a lost answer (offline, a proxy error: the server may have
saved it) posts retry=1, and the route answers with the message already
saved (the same words from the same person in the same conversation within
RETRY_WINDOW) instead of saving it twice.

Without JavaScript nothing changes: the same routes, the same 303s.

MEMBER_INSTANT_SEND=off is the way back: pages render the scripts they had
before (a conversation posts and reloads). Any other value, or none, is on.

The script carries its own few styles (it adds them to the page itself), so
it does not depend on the member app's stylesheet.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

RETRY_WINDOW = timedelta(minutes=10)
GENERIC = "That didn't send. Please try again."
OFFLINE = "That didn't send. Check your connection, then try again."


def on() -> bool:
    """MEMBER_INSTANT_SEND: anything but off (or 0, false, no) is on."""
    return (os.environ.get("MEMBER_INSTANT_SEND") or "on").strip().lower() not in ("off", "0", "false", "no")


def wants_json(request: Request) -> bool:
    return "application/json" in (request.headers.get("accept") or "")


def is_retry(form: Any) -> bool:
    return form is not None and str(form.get("retry") or "") == "1"


def words_for(code: str, own: Optional[Dict[str, str]] = None) -> str:
    """Today's message for a refused send: the page's own flash words."""
    import member_portal_church as mpc
    return (own or {}).get(code) or mpc.ERRORS.get(code) or GENERIC


def refused(code: str, status: int = 400, own: Optional[Dict[str, str]] = None) -> JSONResponse:
    """A send that didn't happen, with why in the page's words."""
    return JSONResponse({"ok": False, "code": code, "error": words_for(code, own)}, status_code=status)


def notice(code: str) -> str:
    """The page's own notice for a held or crisis send (the flash the
    reloaded page showed, the same markup and words), else ''."""
    if code not in ("held", "care"):
        return ""
    import member_portal_church as mpc
    return mpc.flash_html(done=code)


def same_recent(rows: Iterable[Dict[str, Any]], text: str, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """The newest row whose words are `text`, written within RETRY_WINDOW
    (rows newest first), else None. Only a retry asks."""
    cutoff = (now or datetime.now(timezone.utc)) - RETRY_WINDOW
    for r in rows or []:
        if str(r.get("body") or "") != text:
            continue
        try:
            at = datetime.fromisoformat(str(r.get("created_at")).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at >= cutoff:
            return r
    return None


def since() -> str:
    """The start of the retry window, for a created_at=gte. filter."""
    return (datetime.now(timezone.utc) - RETRY_WINDOW).isoformat()


# ─── The page's script ───────────────────────────────────────────────

CSS = (".mis-pending .mb-msg-body,.mis-pending .gc-b{opacity:.7}"
       ".mis-st{display:block;margin-top:2px;font-size:11.5px;line-height:1.25;transition:opacity .6s}"
       ".mb-msg .mis-st{opacity:.8;align-self:flex-end}"
       ".gc-col .mis-st{color:var(--fg3);padding:0 4px}"
       ".mis-st.mis-fade{opacity:0}"
       ".mis-again{margin-left:6px;padding:0;border:0;background:none;color:inherit;font:inherit;font-weight:700;"
       "text-decoration:underline;cursor:pointer}"
       ".mis-notice{margin:10px 0}")

# One conversation's sending (C: form, list, box, err ids; kind: ct the
# church's conversation, mb a private chat, gc a group chat; seen: the
# newest message on the page, for chats whose poll counts messages). The
# poll scripts listen for "mb:sent" on the form and skip a poll while the
# form says data-sending.
JS = r"""(function(){
var C=__CFG__,d=document,f=d.getElementById(C.form),list=d.getElementById(C.list),box=d.getElementById(C.box);
if(!f||!list||!box||!window.fetch||!window.FormData||!window.URLSearchParams||!('content' in d.createElement('template')))return;
var err=d.getElementById(C.err);
if(!err){err=d.createElement('p');err.className='mp-err mis-err';err.id=C.err;err.setAttribute('role','alert');err.hidden=true;
  f.parentNode.insertBefore(err,f.nextSibling);}
if(!d.getElementById('mis-css')){var st=d.createElement('style');st.id='mis-css';st.textContent=__CSS__;d.head.appendChild(st);}
f.noValidate=true;
var q=[],busy=false,seen=C.seen||'',again=null,TA=box.tagName==='TEXTAREA';
var go=f.querySelector('button[type=submit]');
// The send button never takes the focus from the box, so the keyboard stays up.
if(go)go.addEventListener('mousedown',function(e){e.preventDefault();});
function el(tag,cls,text){var e=d.createElement(tag);if(cls)e.className=cls;if(text!=null)e.textContent=text;return e;}
function down(){var o=getComputedStyle(list).overflowY;if(o==='auto'||o==='scroll')list.scrollTop=list.scrollHeight;
  window.scrollTo(0,d.documentElement.scrollHeight);}
function fit(){if(TA){box.style.height='auto';box.style.height=Math.min(box.scrollHeight,160)+'px';}}
function spot(li){return li.querySelector('.gc-col')||li;}
function mark(li,t,cls){var s=li.querySelector('.mis-st');if(!s){s=el('span');spot(li).appendChild(s);}
  s.className='mis-st'+(cls?' '+cls:'');s.textContent=t;return s;}
function bubble(t){var li;
  if(C.kind==='gc'){li=el('li','gc-m mine mis-pending');var c=el('div','gc-col');c.appendChild(el('p','gc-b',t));li.appendChild(c);}
  else{li=el('li','mb-msg mb-mine mis-pending');li.appendChild(el('span','mb-msg-body',t));}
  mark(li,'Sending…');return li;}
function parse(h){var t=d.createElement('template');t.innerHTML=h||'';return t.content.firstElementChild;}
function say(m){err.textContent='';err.appendChild(d.createTextNode(m+' '));var b=el('button','mis-again','Try again');b.type='button';
  b.addEventListener('click',function(){send();});err.appendChild(b);err.hidden=false;}
function tell(h,code){var p=parse(h);if(!p)return;p.classList.add('mis-notice');p.setAttribute('data-code',code);
  var old=f.parentNode.querySelector('.mis-notice[data-code="'+code+'"]');if(old)old.parentNode.removeChild(old);
  f.parentNode.insertBefore(p,f);}
function send(){
  var raw=box.value,t=raw.replace(/^\s+|\s+$/g,'');if(!t)return;
  err.hidden=true;
  // A held notice was about the last message; the crisis words always stay.
  var hn=f.parentNode.querySelector('.mis-notice[data-code="held"]');if(hn)hn.parentNode.removeChild(hn);
  var p=new URLSearchParams(new FormData(f));
  if(again&&again===raw)p.set('retry','1');
  again=null;
  var it={raw:raw,p:p,li:bubble(t),reply:f.querySelector('input[name=reply_to]'),bar:f.querySelector('.gc-reply'),
          ah:f.querySelector('input[name=after_hours]:checked')};
  var e=list.querySelector('.mb-chat-empty,.gs-empty');if(e){it.empty=e;e.parentNode.removeChild(e);}
  list.appendChild(it.li);
  box.value='';fit();
  // A reply and an after-hours alert go with this message only.
  if(it.reply)it.reply.parentNode.removeChild(it.reply);
  if(it.bar)it.bar.parentNode.removeChild(it.bar);
  if(it.ah)it.ah.checked=false;
  if(/[?&](reply|done|err)=/.test(location.search)&&history.replaceState)history.replaceState(null,'',location.pathname);
  down();q.push(it);next();}
f.addEventListener('submit',function(e){e.preventDefault();send();});
function next(){
  if(busy||!q.length)return;var it=q[0];busy=true;f.setAttribute('data-sending','1');
  if(C.seen!==undefined)it.p.set('seen',seen);
  fetch(f.getAttribute('action'),{method:'POST',credentials:'same-origin',
    headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},body:it.p.toString()})
  .then(function(r){return r.json().then(function(x){return {x:x};},function(){return {x:null};});},function(){return {x:null};})
  .then(function(o){busy=false;f.removeAttribute('data-sending');q.shift();
    if(o.x&&o.x.ok)sent(it,o.x);else failed(it,o.x);next();});}
function sent(it,x){
  var li=it.li,n=parse(x.html);
  if(n&&li.parentNode){li.parentNode.replaceChild(n,li);li=n;}else{li.classList.remove('mis-pending');}
  if(x.day&&x.day_html){var ds=list.querySelectorAll('.ct-day'),ld=ds.length?ds[ds.length-1].textContent:'';
    if(ld!==x.day){var sep=parse(x.day_html);if(sep)li.parentNode.insertBefore(sep,li);}}
  if(x.id)seen=x.id;
  if(x.notice)tell(x.notice,x.code);
  if(x.code!=='held'&&x.code!=='care'){var s=mark(li,'Sent');setTimeout(function(){s.classList.add('mis-fade');},1600);
    setTimeout(function(){if(s.parentNode)s.parentNode.removeChild(s);},2400);}
  else{var w=li.querySelector('.mis-st');if(w)w.parentNode.removeChild(w);}
  try{f.dispatchEvent(new CustomEvent('mb:sent',{detail:x}));}catch(_){}
  down();}
function failed(it,x){
  // Nothing was saved, or the answer was lost: the words go back in the box.
  var rest=q.splice(0),all=[it].concat(rest),typed=box.value;
  all.forEach(function(r){if(r.li.parentNode)r.li.parentNode.removeChild(r.li);});
  box.value=all.map(function(r){return r.raw;}).concat(typed?[typed]:[]).join(TA?'\n':' ');fit();
  if(!x&&!rest.length&&!typed)again=box.value;
  if(it.reply&&!f.querySelector('input[name=reply_to]')){f.insertBefore(it.reply,f.firstChild);
    if(it.bar)f.insertBefore(it.bar,f.firstChild);}
  if(it.ah)it.ah.checked=true;
  if(it.empty&&!list.children.length)list.appendChild(it.empty);
  say((x&&x.error)||(x?__GENERIC__:__OFFLINE__));}
})();"""


def script(form: str, chat: str, box: str, err: str, kind: str, *, seen: Optional[str] = None) -> str:
    """The <script> for one conversation's box ('' while switched off).
    `seen` is the newest message on the page, for a chat whose poll counts
    messages (the route says whether nobody else wrote in between)."""
    if not on():
        return ""
    cfg: Dict[str, Any] = {"form": form, "list": chat, "box": box, "err": err, "kind": kind}
    if seen is not None:
        cfg["seen"] = seen
    js = (JS.replace("__CFG__", json.dumps(cfg)).replace("__CSS__", json.dumps(CSS))
          .replace("__GENERIC__", json.dumps(GENERIC)).replace("__OFFLINE__", json.dumps(OFFLINE)))
    return "<script>" + js.replace("</", "<\\/") + "</script>"
