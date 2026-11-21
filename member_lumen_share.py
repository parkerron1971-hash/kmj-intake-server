"""member_lumen_share.py — Share, in the member app's new look (Look 5.1).

Kevin, 2026-11-20, approving Look 5.1: a member may share the CHURCH'S OWN
content out to their own socials (its messages, series, events, verses and
the church's own moments), each with its public link and a "Your story"
picture. Members' posts, prayer requests and photos of members' families are
never shareable: nothing here draws a share control for them, and the story
picture refuses every kind but the church's.

THE SHEET (the mock's "a-share" frame). One script for every new-look page
that carries a share control (_shell adds it, with the sheet's markup in a
<template>, only when the page's markup has one). A tap on any .lm-share
opens a bottom sheet:

  the card ......... the thing's picture, title and line
  Your story ....... a 1080 x 1920 picture of it (story(), below), handed to
                     the phone's share list (Instagram, Facebook, …) or saved
  Text a friend .... sms:?&body= with the title and the link
  Copy link ........ the link, then "Link copied"
  More apps ........ the phone's own share list (navigator.share); a phone
                     without one copies the link instead
  the note ......... one line saying where the link opens

"Send to someone at church" (the mock's last row: "Inside the app, to a member
or a group") opens Messages' picker, /my/messages?say=<the title and the
public link>: choosing a person or a group opens that conversation with the
note in the box, unsent; the member presses Send. Only while Messages' own
count for the page says the church's chats are on and this member may chat
(send_open: no read); hidden otherwise.

It closes on a tap on the dim, a swipe down, or Escape while the sheet has
the focus (its own listener; nothing listens to the whole page's keys). The
sheet is a dialog: the focus moves into it and back to the control that
opened it, and Tab stays inside it. Reduced motion: it appears without the
slide.

THE MARKUP (the contract every new-look surface follows; link() writes it):

  <a class="lm-share" href="<the PUBLIC page>" data-share-kind="message|series|event|verse|moment"
     data-share-title="…" data-share-sub="…" data-share-img="<a picture the page already shows>"
     data-share-id="<the story picture's id>" data-share-text="<words for the message (a verse)>"
     data-share-tr="<a verse's translation>">

Without the script it is a plain link to the public page. data-share-id and
data-share-text are optional: without an id, Your story is left out (a
message's id is read from its /sermons/<id> link; a verse's id is
BOOK.chapter.verse[-verse], JOH.1.5). The Bible reader's Share
(data-share-from="reader") reads the verse the member tapped.

THE PUBLIC LINKS: a message /sermons/<id> (sermons_public), a series
/sermons#sm-s-<id> (its heading on the public library), an event /events
(events_rsvp_router's page, which has no page per event) for a public event
while the church's public events page is on, a verse the church's own site
(/) with the verse written in the message. The member app lives on the
church's own address, so each is relative and opens on it.

STORY PICTURES. GET /my/story/<kind>/<id>.png (t=<translation> for a verse):
a PNG drawn here with Pillow and the self-hosted faces (member_lumen_fonts,
the church's pairing): the content's picture (series art, the church's photo
named for it, a message's own video picture, an event's picture spot) under a calm scrim of the church's
deep colour, the church's mark and name, a small capital line, the title in
the serif, its line, a short rule and the public link as words. A verse is
the church's deep colour, the verse in the reading face, its reference and
version (KJV, WEB, BSB, ASV: the public-domain texts the reader serves,
bible_text). Kinds: message (published), series (with a published message),
event (public, the public events page on), verse, moment (<kind>:<id> of one
of the three it shows). Looked up by id AND the church whose address it is,
so another church's id is a 404. Only for a signed-in member (or the owner's
preview) who sees the new look; rate-limited per member; pictures are read
only from the church's own site files or its public storage folder (or, for
a message's own video picture, from YouTube's picture host through
member_yt_pictures), at most 12 MB and 40 megapixels each; the drawn picture is kept in memory (by what
it shows) and by the phone (Cache-Control, ETag).

COST. A page reads nothing more: the share control is built from what its
page already has. The story picture reads the one thing it shows (kept five
minutes), only when a sheet is opened.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from functools import lru_cache
from html import escape
from pathlib import Path
from string import Template
from typing import Any, Dict, Mapping, Optional, Tuple
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import Response

import member_lumen_ui as _lm

logger = logging.getLogger("member_lumen_share")
router = APIRouter(tags=["member-portal"])

# The church's own kinds. Nothing else is ever shareable.
KINDS = ("message", "series", "event", "verse", "moment")
# What a moment may stand for: the church's own public things.
MOMENT_OF = ("message", "series", "event")
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
VERSE_RE = re.compile(r"^([0-9A-Z]{3})\.(\d{1,3})\.(\d{1,3})(?:-(\d{1,3}))?$")
VERSES_MAX = 6          # verses on one picture
VERSE_CHARS = 640       # a longer passage ends with …

W, H = 1080, 1920
PAD = 96
IMAGE_BYTES_MAX = 12 * 1024 * 1024
IMAGE_PIXELS_MAX = 40_000_000
FETCH_TIMEOUT_S = 6.0
KEEP_S = 300            # a looked-up thing, per server copy
PNG_BUDGET = 48 * 1024 * 1024
VERSION = "1"           # bump when the drawing changes, so kept pictures go


def _e(v: Any) -> str:
    return escape(str(v if v is not None else ""), quote=True)


# ─── the markup ──────────────────────────────────────────────────────


def message_href(sermon_id: Any) -> str:
    return f"/sermons/{quote(str(sermon_id), safe='')}"


def series_href(series_id: Any) -> str:
    return f"/sermons#sm-s-{quote(str(series_id), safe='')}"


EVENTS_HREF = "/events"
VERSE_HREF = "/"


def attrs(kind: str, href: str, title: Any, *, sub: Any = "", img: Any = "", sid: Any = "", text: Any = "",
          tr: str = "") -> str:
    """The share control's attributes (contract 1), escaped. `tr` is a
    verse's translation for its story picture (kjv, web, bsb, asv). A
    moment's `sid` is "<message|series|event>:<id>": the thing it shows."""
    if kind not in KINDS:
        raise ValueError(f"not a church kind: {kind!r}")
    if kind == "moment":
        of, _, rid = str(sid or "").partition(":")
        if of not in MOMENT_OF or not rid:
            raise ValueError(f"not a church moment: {sid!r}")
    out = [f'class="lm-share" href="{_e(href)}" data-share-kind="{kind}" data-share-title="{_e(title)}"']
    if sub:
        out.append(f'data-share-sub="{_e(sub)}"')
    if img:
        out.append(f'data-share-img="{_e(img)}"')
    if sid:
        out.append(f'data-share-id="{_e(sid)}"')
    if text:
        out.append(f'data-share-text="{_e(text)}"')
    if tr:
        out.append(f'data-share-tr="{_e(tr)}"')
    return " ".join(out)


def link(kind: str, href: str, title: Any, inner: str, *, sub: Any = "", img: Any = "", sid: Any = "",
         text: Any = "", tr: str = "", cls: str = "", label: str = "") -> str:
    """A share control: <a class="lm-share {cls}" …>{inner}</a>. `label`
    names it for a screen reader when `inner` is only an icon."""
    a = attrs(kind, href, title, sub=sub, img=img, sid=sid, text=text, tr=tr)
    if cls:
        a = a.replace('class="lm-share"', f'class="lm-share {_e(cls)}"', 1)
    aria = f' aria-label="{_e(label)}"' if label else ""
    return f"<a {a}{aria}>{inner}</a>"


def events_on(biz: Mapping[str, Any]) -> bool:
    """Whether the church's public events page is switched on
    (events_rsvp_router: settings.events_public.enabled; a church whose
    members see occasions has the rooms behind it)."""
    import events_rsvp_router as er
    return bool(er.events_settings((biz or {}).get("settings")).get("enabled"))


def event_picture(biz: Mapping[str, Any], site, title: str) -> str:
    """The picture an occasion carries (its picture spot, else the church's
    photo named for it), only when it is already public on the church's own
    website (its media library shown there, its site's files): a picture
    uploaded only into the app stays in the app. '' otherwise."""
    import member_app_photos as photos
    import member_portal_church as mpc
    pool = photos.photos(dict(biz), site, limit=None)
    pic, _look = photos.choose(dict(biz), mpc.event_key(title), pool, title=title, look="colour")
    return pic if pic and pic in pool else ""


def event_shareable(biz: Mapping[str, Any], o: Mapping[str, Any]) -> bool:
    """A member may share this occasion: it is public (upcoming_for marks
    it), the public events page is on, and it isn't a sample."""
    import member_app_samples as samples
    return bool(o.get("public")) and not samples.is_sample(dict(o)) and events_on(biz)


def message_art(lib: Mapping[str, Any], s: Mapping[str, Any], site, pool) -> str:
    """The picture a message already shows (member_portal_sermons._art):
    its series' own art, else the church's photo named for it, else its own
    video picture (member_yt_pictures, the small one); '' for the generated
    poster."""
    import member_app_photos as photos
    import member_portal_sermons as mps
    import member_yt_pictures as myp
    series = mps._titles(dict(lib)).get(str(s.get("series_id") or ""), "")
    own = photos.series_art(site, series) if series else ""
    if own:
        return own
    named = photos.by_name(pool or [], series or s.get("title") or "") if pool else ""
    return named or myp.picture_url(s.get("video_url"))


def message_link(lib: Mapping[str, Any], s: Mapping[str, Any], site, pool, inner: str, *, cls: str = "",
                 label: str = "") -> str:
    """A message's share control, from what its page already read."""
    import member_portal_sermons as mps
    series = mps._titles(dict(lib)).get(str(s.get("series_id") or ""), "")
    sub = " · ".join(x for x in (s.get("speaker") or "", series) if x)
    return link("message", message_href(s["id"]), s.get("title") or "Message", inner, sub=sub,
                img=message_art(lib, s, site, pool), sid=s["id"], cls=cls, label=label)


def story_url(kind: str, sid: Any, tr: str = "") -> str:
    return f"/my/story/{kind}/{quote(str(sid), safe='')}.png" + (f"?t={quote(tr, safe='')}" if tr else "")


# ─── the sheet ───────────────────────────────────────────────────────

_ICONS = {
    "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/>'
             '<path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "comment": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
            '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
    "more": '<circle cx="5" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/>'
            '<circle cx="19" cy="12" r="1.3" fill="currentColor"/>',
    "play": '<path d="M8 5.5v13l10.5-6.5z"/>',
    "calendar": '<rect x="3" y="4.5" width="18" height="16.5" rx="3"/><path d="M3 9.5h18M8 2.5v4M16 2.5v4"/>',
    "book": '<path d="M12 6.5C10 5 7 4.5 3.5 5v13.5c3.5-.5 6.5 0 8.5 1.5 2-1.5 5-2 8.5-1.5V5C17 4.5 14 5 12 6.5z"/>'
            '<path d="M12 6.5V20"/>',
    "share": '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="m16 6-4-4-4 4"/><path d="M12 2v13"/>',
    "send": '<path d="M21 3 10 14"/><path d="M21 3 14.5 21l-4.5-7-7-4.5z"/>',
    "chev": '<path d="m9 6 6 6-6 6"/>',
}


def icon(name: str, size: int = 22) -> str:
    return (f'<svg class="lm-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
            f'{_ICONS[name]}</svg>')


def _target(key: str, ic: str, label: str, cls: str = "") -> str:
    return (f'<button type="button" class="lm-shs-t{cls}" data-sh="{key}"><span>{icon(ic, 22)}</span>'
            f'<b>{label}</b></button>')


SHEET = (
    '<div class="lm-shs" hidden>'
    '<div class="lm-shs-dim" data-sh="close"></div>'
    '<div class="lm-shs-sheet" role="dialog" aria-modal="true" aria-labelledby="lm-shs-h" tabindex="-1">'
    '<span class="lm-shs-grab" aria-hidden="true"></span>'
    '<h2 class="lm-shs-h" id="lm-shs-h">Share</h2>'
    '<button type="button" class="lm-shs-x mp-sr" data-sh="close">Close</button>'
    '<div class="lm-shs-card"><span class="lm-shs-pic" data-k="message">'
    f'<i class="k-play">{icon("play", 22)}</i><i class="k-cal">{icon("calendar", 22)}</i>'
    f'<i class="k-book">{icon("book", 22)}</i><i class="k-img">{icon("image", 22)}</i>'
    '<img alt="" hidden></span><span class="lm-shs-tx"><b></b><small></small></span></div>'
    '<div class="lm-shs-tg">'
    + _target("story", "image", "Your story", " is-story")
    + _target("text", "comment", "Text a friend")
    + _target("copy", "link", "Copy link")
    + _target("more", "more", "More apps")
    + '</div><button type="button" class="lm-shs-in" data-sh="send" hidden>'
    f'<span class="lm-shs-ini">{icon("send", 20)}</span><span class="lm-shs-int"><b>Send to someone at church</b>'
    f'<small>Inside the app, to a member or a group</small></span>{icon("chev", 18)}</button>'
    '<p class="lm-shs-note"></p></div></div>'
    '<p class="lm-shs-toast" role="status" aria-live="polite" hidden></p>'
)

# The words under the targets: where the link opens (%h = this address).
NOTES = {
    "message": "Your link opens this message on %h, so anyone can watch, no app needed. More apps opens your "
               "phone’s list: Instagram, Facebook, WhatsApp and the rest.",
    "series": "Your link opens the series on %h. Your story makes a picture with the series art and the "
              "church’s name.",
    "event": "Your link opens the event on %h, where friends can say they’re coming. Your story uses only "
             "pictures already on the church’s website; photos members post never leave the app.",
    "verse": "Your story makes a picture of the verse in the church’s colours. Your link opens %h, with the "
             "verse written in your message.",
    "moment": "Only the church’s own moments can be shared. Your link opens it on %h.",
}

_JS = r"""(function(){
if(window.__lmShare)return;window.__lmShare=1;var T=document.createElement('template');T.innerHTML=__SHEET__;
var SC=document.currentScript,SEND=!!(SC&&SC.getAttribute('data-send')==='1'),SAY=__SAY__;
var NOTES=__NOTES__,B=document.body,R=null,S=null,toast=null,back=null,cur=null,pic=null,picFor='',busy=null,tt=null,y0=null,dy=0;
function q(s){return R.querySelector(s);}
function abs(h){try{return new URL(h||'/',location.href).href;}catch(e){return location.origin+'/';}}
function say(t){toast.textContent=t;toast.hidden=false;clearTimeout(tt);tt=setTimeout(function(){toast.hidden=true;},2200);}
function build(){var n=T.content.cloneNode(true);R=n.querySelector('.lm-shs');toast=n.querySelector('.lm-shs-toast');
 B.appendChild(R);B.appendChild(toast);S=q('.lm-shs-sheet');
 var im=q('.lm-shs-pic img');im.addEventListener('error',function(){im.hidden=true;});
 R.addEventListener('click',function(e){var b=e.target.closest('[data-sh]');if(!b)return;var a=b.getAttribute('data-sh');
  if(a==='close')close();else if(a==='story')story(b);else if(a==='text')text();else if(a==='copy')copy();else if(a==='more')more();
  else if(a==='send')send();});
 S.addEventListener('keydown',function(e){if(e.key==='Escape'){e.preventDefault();close();return;}
  if(e.key!=='Tab')return;var f=[].slice.call(S.querySelectorAll('button')).filter(function(b){return !b.hidden;});if(!f.length)return;
  var i=f.indexOf(document.activeElement);
  if(e.shiftKey&&(i<=0)){e.preventDefault();f[f.length-1].focus();}else if(!e.shiftKey&&i===f.length-1){e.preventDefault();f[0].focus();}});
 S.addEventListener('touchstart',function(e){y0=S.scrollTop>0?null:e.touches[0].clientY;dy=0;},{passive:true});
 S.addEventListener('touchmove',function(e){if(y0===null)return;dy=Math.max(0,e.touches[0].clientY-y0);
  S.classList.add('is-drag');S.style.transform=dy?'translateY('+dy+'px)':'';},{passive:true});
 S.addEventListener('touchend',function(){if(y0===null)return;y0=null;S.classList.remove('is-drag');S.style.transform='';if(dy>90)close();dy=0;});}
function verse(a){var rd=document.querySelector('.bb-read'),s=rd&&rd.querySelector('.bb-v.is-sel');if(!s)return null;
 var c=s.cloneNode(true);c.querySelectorAll('sup,.bb-nm,.bb-bm').forEach(function(x){x.remove();});
 var t=c.textContent.replace(/\s+/g,' ').trim(),v=s.getAttribute('data-v'),tr=rd.getAttribute('data-tr')||'',TR=tr.toUpperCase();
 var ref=(rd.getAttribute('data-label')||'')+':'+v,cut=t.length>96?t.slice(0,94).replace(/\s+\S*$/,'')+'…':t;
 return {kind:'verse',url:abs(a.getAttribute('href')||'/'),title:ref+(TR?' · '+TR:''),sub:'“'+cut+'”',img:'',
  text:'“'+t+'” '+ref+(TR?' ('+TR+')':''),
  story:'/my/story/verse/'+encodeURIComponent(rd.getAttribute('data-book')+'.'+rd.getAttribute('data-ch')+'.'+v)+'.png?t='+encodeURIComponent(tr)};}
function read(a){if(a.getAttribute('data-share-from')==='reader')return verse(a);
 var g=function(n){return a.getAttribute('data-share-'+n)||'';},k=g('kind');
 var o={kind:k,url:abs(a.getAttribute('href')),title:g('title'),sub:g('sub'),img:g('img'),text:g('text'),story:''};
 var id=g('id');if(!id&&k==='message'){var m=(a.getAttribute('href')||'').match(/\/sermons\/([0-9a-fA-F-]{36})/);if(m)id=m[1];}
 if(id)o.story='/my/story/'+k+'/'+encodeURIComponent(id)+'.png'+(g('tr')?'?t='+encodeURIComponent(g('tr')):'');
 return o;}
function words(){return (cur.text||cur.title)?(cur.text||cur.title)+' '+cur.url:cur.url;}
function open(a){var o=read(a);if(!o)return false;if(!R)build();cur=o;back=a;
 q('.lm-shs-tx b').textContent=o.title;var sm=q('.lm-shs-tx small');sm.textContent=o.sub;sm.hidden=!o.sub;
 var p=q('.lm-shs-pic'),im=p.querySelector('img');p.setAttribute('data-k',o.kind);
 if(o.img){im.hidden=false;im.src=o.img;}else{im.hidden=true;im.removeAttribute('src');}
 q('.lm-shs-note').textContent=(NOTES[o.kind]||NOTES.moment).replace('%h',location.host);
 q('[data-sh=story]').hidden=!o.story;q('[data-sh=send]').hidden=!SEND;
 R.hidden=false;B.classList.add('lm-shs-on');S.style.transform='';S.scrollTop=0;
 try{S.focus({preventScroll:true});}catch(e){S.focus();}
 if(o.story&&picFor!==o.story){pic=null;picFor=o.story;busy=null;get();}
 return true;}
function get(){var want=picFor;busy=fetch(want,{credentials:'same-origin'}).then(function(r){if(!r.ok)throw r.status;return r.blob();})
 .then(function(b){if(picFor===want)pic=b;return b;},function(){if(picFor===want){picFor='';busy=null;}return null;});return busy;}
function close(){if(!R||R.hidden)return;R.hidden=true;B.classList.remove('lm-shs-on');
 if(back&&back.focus){try{back.focus({preventScroll:true});}catch(e){back.focus();}}}
function name(){return ((cur.title||'').replace(/[^A-Za-z0-9]+/g,'-').replace(/^-+|-+$/g,'').slice(0,60)||'story')+'.png';}
function save(b){var u=URL.createObjectURL(b),x=document.createElement('a');x.href=u;x.download=name();B.appendChild(x);x.click();x.remove();
 setTimeout(function(){URL.revokeObjectURL(u);},4000);say('Saved to your phone');}
function hand(b){var f=null;try{f=new File([b],name(),{type:'image/png'});}catch(e){}
 if(f&&navigator.canShare&&navigator.canShare({files:[f]})){navigator.share({files:[f],title:cur.title}).then(close,function(e){
   if(e&&e.name==='AbortError')return;if(e&&e.name==='NotAllowedError'){say('Your picture is ready. Tap Your story again.');return;}save(b);});return;}
 save(b);}
function story(btn){if(pic){hand(pic);return;}
 btn.classList.add('is-busy');btn.setAttribute('aria-busy','true');
 (busy||(picFor?get():Promise.resolve(null))).then(function(b){btn.classList.remove('is-busy');btn.removeAttribute('aria-busy');
  if(!b){say('That picture couldn’t be made just now.');if(cur&&cur.story)picFor='';return;}hand(b);});}
function text(){var u='sms:?&body='+encodeURIComponent(words());close();location.href=u;}
function send(){var u=cur.url,t=(cur.title||'').replace(/\s+/g,' ').trim(),room=SAY-u.length-1;
 if(t.length>room)t=room>1?t.slice(0,room-1).replace(/\s+\S*$/,'')+'…':'';
 close();location.href='/my/messages?say='+encodeURIComponent((t?t+' ':'')+u);}
function old(t){return new Promise(function(ok,no){var x=document.createElement('textarea');x.value=t;x.setAttribute('readonly','');
 x.style.position='fixed';x.style.opacity='0';B.appendChild(x);x.select();var d=false;try{d=document.execCommand('copy');}catch(e){}x.remove();d?ok():no();});}
function put(t){if(navigator.clipboard&&navigator.clipboard.writeText)return navigator.clipboard.writeText(t).catch(function(){return old(t);});return old(t);}
function copy(){var verse=!!cur.text;put(verse?words():cur.url).then(function(){close();say(verse?'Verse and link copied':'Link copied');},
 function(){say('Copying was blocked');});}
function more(){if(navigator.share){var d={title:cur.title,url:cur.url};if(cur.text)d.text=cur.text;navigator.share(d).then(close,function(){});return;}copy();}
document.addEventListener('click',function(e){if(e.defaultPrevented||e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
 var a=e.target.closest?e.target.closest('.lm-share'):null;if(!a)return;e.preventDefault();e.stopPropagation();
 if(!open(a)&&a.tagName==='A'&&a.getAttribute('href'))location.href=a.href;},true);
})();"""

# "Send to someone at church" carries the title and the public link, at most
# this long (member_portal_messaging.say_of cuts it again on the way in).
SAY_MAX = 300

JS_TEXT = (_JS.replace("__SHEET__", json.dumps(SHEET, ensure_ascii=False))
           .replace("__NOTES__", json.dumps(NOTES, ensure_ascii=False)).replace("__SAY__", str(SAY_MAX)))


@lru_cache(maxsize=None)
def js_file() -> Tuple[bytes, str]:
    """The script's bytes and the 12-hex hash in its address."""
    data = JS_TEXT.encode("utf-8")
    return data, hashlib.sha256(data).hexdigest()[:12]


def js_url() -> str:
    return f"/my/share.{js_file()[1]}.js"


def page_js(body: str, *, send: bool = False) -> str:
    """What a new-look page adds at its foot when its markup has a share
    control: the script (its own file, kept a year by the phone; the sheet
    is drawn on the first tap). '' otherwise, so no other page carries it.
    `send` (send_open()) puts "Send to someone at church" on its sheet."""
    if "lm-share" not in (body or ""):
        return ""
    mark = ' data-send="1"' if send else ""
    return f'\n<script src="{js_url()}" defer{mark}></script>'


def send_open() -> bool:
    """Whether this page's sheet offers "Send to someone at church": Messages'
    own count for the page (member_portal_threads.counts, read for the
    header's bubble and kept 15 s) says the church's chats are on and this
    member may chat (a birthdate, their switch on, the guidelines agreed:
    member_messaging_rules). No read here; when that count wasn't read
    (church threads closed, Kids, a failed read), no."""
    import member_portal_threads as mpt
    return bool((mpt.NOW.get() or {}).get("chats"))


@router.get("/my/share.{tag}.js", include_in_schema=False)
async def share_js(tag: str):
    """The sheet's script, from our own address: kept a year when the hash
    is today's; another hash (a page from before a deploy) gets today's
    file, kept by nobody (as the fonts are, member_lumen_fonts.serve)."""
    data, digest = js_file()
    keep = "public, max-age=31536000, immutable" if tag == digest else "no-store"
    return Response(data, media_type="text/javascript; charset=utf-8",
                    headers={"Cache-Control": keep, "X-Content-Type-Options": "nosniff"})


CSS = Template("""
/* Share (member_lumen_share): the sheet, its card and targets, the toast */
body.lm{--lm-dim:rgba(0,0,0,.42);}
body.lm.lm-shs-on{overflow:hidden;}
body.lm .lm-shs{position:fixed;inset:0;z-index:400;}
body.lm .lm-shs[hidden],body.lm .lm-shs-toast[hidden],body.lm .lm-shs-t[hidden],body.lm .lm-shs-in[hidden],
body.lm .lm-shs-pic img[hidden],
body.lm .lm-shs-tx small[hidden]{display:none;}
body.lm .lm-shs-dim{position:absolute;inset:0;background:var(--lm-dim);}
body.lm .lm-shs-sheet{position:absolute;left:0;right:0;bottom:0;max-width:600px;max-height:calc(100% - 24px);margin:0 auto;overflow:auto;
  overscroll-behavior:contain;padding:0 0 calc(14px + env(safe-area-inset-bottom,0px));border-radius:22px 22px 0 0;
  background:var(--bg);color:var(--fg);box-shadow:0 -10px 40px var(--lm-shadow);outline:0;}
body.lm .lm-shs-grab{display:block;width:38px;height:5px;margin:8px auto 0;border-radius:3px;background:var(--s3);}
body.lm .lm-shs-h{margin:10px 0 0;padding:0 16px 12px;border-bottom:1px solid var(--lm-line);text-align:center;
  font:700 15px/1.2 var(--mb-ui);letter-spacing:0;color:var(--fg);}
body.lm .lm-shs-card{display:flex;gap:12px;align-items:center;margin:16px 16px 0;padding:12px;border-radius:16px;background:var(--s1);}
body.lm .lm-shs-pic{position:relative;width:64px;height:64px;flex:none;border-radius:12px;overflow:hidden;display:grid;place-items:center;
  background:var(--lm-tint-12);color:var(--acc);}
body.lm .lm-shs-pic i{display:none;}
body.lm .lm-shs-pic[data-k=message] .k-play,body.lm .lm-shs-pic[data-k=series] .k-play,body.lm .lm-shs-pic[data-k=event] .k-cal,
body.lm .lm-shs-pic[data-k=verse] .k-book,body.lm .lm-shs-pic[data-k=moment] .k-img{display:block;}
body.lm .lm-shs-pic img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;}
body.lm .lm-shs-tx{min-width:0;flex:1;}
body.lm .lm-shs-tx b,body.lm .lm-shs-tx small{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden;overflow-wrap:anywhere;}
body.lm .lm-shs-tx b{font:700 15px/1.3 var(--mb-ui);color:var(--fg);}
body.lm .lm-shs-tx small{margin-top:2px;font:500 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-shs-tg{display:flex;justify-content:space-around;gap:6px;padding:20px 12px 4px;}
body.lm .lm-shs-t{flex:1 1 0;min-width:0;display:flex;flex-direction:column;align-items:center;gap:8px;padding:0;border:0;background:none;
  color:var(--fg);text-align:center;cursor:pointer;-webkit-tap-highlight-color:transparent;}
body.lm .lm-shs-t>span{width:58px;height:58px;border-radius:50%;display:grid;place-items:center;background:var(--s1);color:var(--fg);}
body.lm .lm-shs-t>b{font:600 12.5px/1.2 var(--mb-ui);}
body.lm .lm-shs-t.is-story>span{background:var(--acc-fill);color:var(--on-acc);}
body.lm .lm-shs-t.is-busy>span{opacity:.62;}
body.lm .lm-shs-t:focus-visible{outline:0;}
body.lm .lm-shs-t:focus-visible>span{outline:2px solid var(--acc);outline-offset:3px;}
body.lm .lm-shs-in{display:flex;align-items:center;gap:12px;width:calc(100% - 32px);margin:16px 16px 0;padding:14px 0;border:0;
  border-top:1px solid var(--lm-line);background:none;color:var(--fg);text-align:left;cursor:pointer;
  -webkit-tap-highlight-color:transparent;}
body.lm .lm-shs-ini{width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;background:var(--s1);
  color:var(--fg);}
body.lm .lm-shs-int{flex:1;min-width:0;}
body.lm .lm-shs-int b{display:block;font:650 14.5px/1.3 var(--mb-ui);color:var(--fg);}
body.lm .lm-shs-int small{display:block;margin-top:1px;font:500 12.5px/1.35 var(--mb-ui);color:var(--fg2);}
body.lm .lm-shs-in>.lm-ic{flex:none;color:var(--fg3);}
body.lm .lm-shs-in:focus-visible{outline:2px solid var(--acc);outline-offset:2px;border-radius:12px;}
body.lm .lm-shs-note{margin:16px 16px 0;padding:14px 0 10px;border-top:1px solid var(--lm-line);
  font:400 12.5px/1.45 var(--mb-ui);color:var(--fg3);}
body.lm .lm-shs-toast{position:fixed;left:50%;bottom:calc(104px + env(safe-area-inset-bottom,0px));z-index:410;transform:translateX(-50%);
  max-width:calc(100% - 40px);margin:0;padding:11px 18px;border-radius:22px;background:var(--fg);color:var(--bg);
  font:550 14px/1.3 var(--mb-ui);text-align:center;box-shadow:0 8px 28px var(--lm-shadow);}
/* Coming up: a quiet share icon beside an occasion's title */
body.lm .lm-evt.has-share{position:relative;}
body.lm .lm-evt.has-share>h2{padding-right:44px;}
body.lm .lm-evshare{position:absolute;top:-8px;right:-10px;width:44px;height:44px;display:grid;place-items:center;
  border-radius:50%;color:var(--fg2);-webkit-tap-highlight-color:transparent;}
body.lm .lm-evshare:active{background:var(--s1);}
body.lm .lm-evshare:focus-visible{outline:2px solid var(--acc);outline-offset:-2px;}
@media (prefers-reduced-motion:no-preference){
  body.lm .lm-shs:not([hidden]) .lm-shs-dim{animation:lm-shs-fade .25s ease backwards;}
  body.lm .lm-shs:not([hidden]) .lm-shs-sheet{animation:lm-shs-up .42s cubic-bezier(.2,.8,.2,1) backwards;}
  body.lm .lm-shs-sheet:not(.is-drag){transition:transform .22s cubic-bezier(.2,.8,.2,1);}
  body.lm .lm-shs-t>span{transition:transform .15s ease;}
  body.lm .lm-shs-t:active>span{transform:scale(.94);}
  body.lm .lm-shs-t.is-busy>span{animation:lm-shs-beat 1.1s ease-in-out infinite;}
}
@keyframes lm-shs-fade{from{opacity:0}}
@keyframes lm-shs-up{from{transform:translateY(100%)}}
@keyframes lm-shs-beat{50%{opacity:.4}}
""" + "".join(_lm.dark(r) for r in (
    "body.lm.lm-dark{--lm-dim:rgba(0,0,0,.62);}"
    "body.lm.lm-dark .lm-shs-sheet{background:var(--s1);box-shadow:0 0 0 1px var(--lm-line);}"
    "body.lm.lm-dark .lm-shs-card,body.lm.lm-dark .lm-shs-t>span,body.lm.lm-dark .lm-shs-ini{background:var(--s2);}"
    "body.lm.lm-dark .lm-shs-t.is-story>span{background:var(--acc-fill);}"
    "body.lm.lm-dark .lm-shs-grab{background:var(--s3);}",
)))


# ─── story pictures: what one shows ──────────────────────────────────


class Unavailable(Exception):
    """A read failed: the picture says "try again" (503), never "not found"."""


def _rows(path: str):
    import sb_clients
    rows = sb_clients.sb_get_as_service(path)
    if not isinstance(rows, list):
        raise Unavailable(path.split("?")[0])
    return rows


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _message(biz: Mapping[str, Any], site, sid: str) -> Optional[Dict[str, Any]]:
    """A published message of this church."""
    import member_app_photos as photos
    b = _q(biz["id"])
    rows = _rows(f"/sermons?id=eq.{_q(sid)}&business_id=eq.{b}&published=eq.true"
                 f"&select=id,series_id,title,speaker,scripture,video_url,published&limit=1")
    if not rows or rows[0].get("published") is not True:
        return None
    s = rows[0]
    series = ""
    if s.get("series_id"):
        got = _rows(f"/sermon_series?id=eq.{_q(s['series_id'])}&business_id=eq.{b}&select=id,title&limit=1")
        series = (got[0].get("title") or "").strip() if got else ""
    pic, look = (photos.series_art(site, series) if series else ""), "colour"
    if not pic:
        pic, look = photos.by_name(photos.photos(dict(biz), site), series or s.get("title") or ""), "bw"
    if not pic:
        # Its own video picture, the wide one (member_yt_pictures), in colour.
        import member_yt_pictures as myp
        pic, look = myp.picture_url(s.get("video_url"), wide=True), "colour"
    return {"kind": "message", "kicker": series or "A message", "title": (s.get("title") or "").strip() or "Message",
            "sub": " · ".join(x for x in ((s.get("speaker") or "").strip(), (s.get("scripture") or "").strip()) if x),
            "href": message_href(s["id"]), "pic": pic, "look": look if pic else ""}


def _series(biz: Mapping[str, Any], site, sid: str) -> Optional[Dict[str, Any]]:
    """A series of this church with at least one published message (the
    public library shows no other)."""
    import member_app_photos as photos
    b = _q(biz["id"])
    rows = _rows(f"/sermon_series?id=eq.{_q(sid)}&business_id=eq.{b}&select=id,title&limit=1")
    if not rows:
        return None
    msgs = _rows(f"/sermons?series_id=eq.{_q(sid)}&business_id=eq.{b}&published=eq.true&select=id,published&limit=200")
    n = sum(1 for m in msgs if m.get("published") is True)
    if not n:
        return None
    title = (rows[0].get("title") or "").strip() or "Series"
    pic, look = photos.series_art(site, title), "colour"
    if not pic:
        pic, look = photos.by_name(photos.photos(dict(biz), site), title), "bw"
    return {"kind": "series", "kicker": f"A series · {n} message{'' if n == 1 else 's'}", "title": title, "sub": "",
            "href": series_href(rows[0]["id"]), "pic": pic, "look": look if pic else ""}


def _event(biz: Mapping[str, Any], site, eid: str) -> Optional[Dict[str, Any]]:
    """A public occasion of this church, while its public events page is on."""
    import events_rsvp_router as er
    import member_app_photos as photos
    import member_portal_church as mpc
    if not events_on(biz):
        return None
    b = _q(biz["id"])
    rows = _rows(f"/module_entries?id=eq.{_q(eid)}&business_id=eq.{b}&status=eq.active&select=id,module_id,data&limit=1")
    if not rows:
        return None
    data = rows[0].get("data") or {}
    if not isinstance(data, dict) or not er.is_public(data):
        return None
    mods = _rows(f"/custom_modules?id=eq.{_q(rows[0].get('module_id'))}&business_id=eq.{b}&archetype=eq.event_roster"
                 f"&is_active=eq.true&select=id,archetype_params&limit=1")
    if not mods:
        return None
    f = er.resolve_fields(mods[0].get("archetype_params"))
    title = str(data.get(f["title_field"]) or "").strip() or "Event"
    d = er._parse_day(data.get(f["date_field"]))
    when = f"{d.strftime('%A, %B')} {d.day}" if d else ""
    clock = mpc.clock_of(data.get(f["date_field"]))
    if when and clock:
        hh, mm = (int(x) for x in clock.split(":"))
        when += f" · {(hh % 12) or 12}{'' if mm == 0 else f':{mm:02d}'} {'AM' if hh < 12 else 'PM'}"
    pic = event_picture(biz, site, title)
    return {"kind": "event", "kicker": when or "Coming up", "title": title,
            "sub": str(data.get(f["location_field"]) or "").strip(), "href": EVENTS_HREF, "pic": pic,
            "look": "colour" if pic else ""}


def _clean_verse(text: str) -> str:
    t = re.sub(r"\[([^\[\]]*)\]", r"\1", str(text or "").replace("¶", "")).replace("[", "").replace("]", "")
    return re.sub(r"\s+", " ", t).strip()


def _verse(ref: str, tr: str) -> Optional[Dict[str, Any]]:
    """Verses from the reader's public-domain texts (bible_text): no
    picture, the church's colours."""
    import bible_text as bt
    import member_portal_bible as mpb
    m = VERSE_RE.match(ref or "")
    if not m or m.group(1) not in bt.NAME:
        return None
    tr = bt.translation((tr or "").lower())
    code, ch, a = m.group(1), int(m.group(2)), int(m.group(3))
    z = int(m.group(4) or a)
    if z < a or z - a + 1 > VERSES_MAX:
        return None
    chap = bt.chapter(code, ch, tr)
    if not chap:
        return None
    got = [_clean_verse(t) for n, t in chap if a <= n <= z]
    if len(got) != z - a + 1 or not all(got):
        return None
    words = " ".join(got)
    if len(words) > VERSE_CHARS:
        words = words[:VERSE_CHARS].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    where = f"{mpb.where_label(code, ch)}:{a}" + (f"-{z}" if z > a else "")
    return {"kind": "verse", "kicker": f"{where} · {bt.TRANSLATIONS[tr]['short']}", "title": words, "sub": "",
            "href": VERSE_HREF, "pic": "", "look": ""}


def lookup(biz: Mapping[str, Any], site, kind: str, ref: str, tr: str = "") -> Optional[Dict[str, Any]]:
    """What the picture of (kind, ref) shows at this church, or None (not
    the church's, not published, not public, not a kind we share). Raises
    Unavailable on a failed read."""
    if kind not in KINDS:
        return None
    if kind == "verse":
        return _verse(ref, tr)
    if kind == "moment":
        inner, _, rid = str(ref or "").partition(":")
        if inner not in MOMENT_OF:
            return None
        got = lookup(biz, site, inner, rid)
        return dict(got, kind="moment") if got else None
    if not UUID_RE.match(str(ref or "")):
        return None
    return {"message": _message, "series": _series, "event": _event}[kind](biz, site, str(ref).lower())


_FOUND: "OrderedDict[Tuple[str, str, str, str], Tuple[float, Dict[str, Any]]]" = OrderedDict()
_FOUND_LOCK = threading.Lock()


def lookup_kept(biz: Mapping[str, Any], site, kind: str, ref: str, tr: str = "") -> Optional[Dict[str, Any]]:
    """lookup(), kept five minutes per server copy (a sheet opened twice
    reads once). A miss and a failed read are never kept."""
    key = (str(biz.get("id")), kind, str(ref), str(tr or ""))
    now = time.monotonic()
    with _FOUND_LOCK:
        hit = _FOUND.get(key)
        if hit and now - hit[0] < KEEP_S:
            return dict(hit[1])
    got = lookup(biz, site, kind, ref, tr)
    if got:
        with _FOUND_LOCK:
            _FOUND[key] = (now, dict(got))
            _FOUND.move_to_end(key)
            while len(_FOUND) > 512:
                _FOUND.popitem(last=False)
    return got


# ─── story pictures: the church's marks ──────────────────────────────


def church_marks(biz: Mapping[str, Any], site, host: str) -> Dict[str, Any]:
    """The church's name, initials, logo, colours and type for its picture."""
    import member_app_ui as ui
    import member_lumen_fonts as lmf
    from public_form_theme import resolve_theme
    theme = resolve_theme(dict(biz), site)
    pal = ui.palette(dict(biz), theme)
    name = (biz.get("name") or "").strip() or "Your church"
    return {"name": name, "mark": ui.initials(name), "logo": theme.get("logo_url") or "", "fill": pal["fill"],
            "on_fill": pal["on_fill"], "night": pal["night"], "lit": pal["lit"], "pair": lmf.pick(biz),
            "host": (host or "").lower()}


def _shown_link(host: str, href: str) -> str:
    path = "" if href == "/" else href
    return f"{host}{path}" if host else (path or "/")


# ─── story pictures: reading a picture ───────────────────────────────


def _site_file(url: str) -> Optional[Path]:
    """A hand-built site's own asset (/public/site-assets/<slug>/<file>) on disk."""
    import member_app_photos as photos
    m = re.fullmatch(r"/public/site-assets/([\w.-]+)/([\w.%-]+)", url or "")
    if not m:
        return None
    d = photos._site_dir({"slug": m.group(1)})
    if d is None:
        return None
    p = d / unquote(m.group(2))
    try:
        p.resolve().relative_to(d.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


def _storage_ok(url: str, business_id: str) -> bool:
    """A file in this church's folder of our own public storage: the only
    address a picture is fetched from (no other host, so nothing inside our
    network can be asked for)."""
    import sb_clients
    base = sb_clients.sb_url()
    try:
        u, b = urlsplit(url), urlsplit(base)
        port = u.port
    except ValueError:
        return False
    if u.scheme != "https" or not b.hostname or (u.hostname or "").lower() != b.hostname.lower() or port not in (None, 443):
        return False
    if u.username or u.password or u.query or not u.path.startswith("/storage/v1/object/public/"):
        return False
    parts = unquote(u.path).split("/")
    return ".." not in parts and str(business_id).lower() in (p.lower() for p in parts)


def _fetch(url: str) -> Optional[bytes]:
    """Our own storage's file, capped (tests replace this)."""
    import httpx
    with httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=False, trust_env=False) as c:
        with c.stream("GET", url, headers={"Accept": "image/*"}) as r:
            if r.status_code != 200:
                return None
            try:
                if int(r.headers.get("content-length") or 0) > IMAGE_BYTES_MAX:
                    return None
            except ValueError:
                return None
            out = bytearray()
            for chunk in r.iter_bytes():
                out.extend(chunk)
                if len(out) > IMAGE_BYTES_MAX:
                    return None
            return bytes(out)


def picture_bytes(url: str, business_id: str) -> Optional[bytes]:
    """A picture's bytes when it is the church's own (its site's files, its
    storage folder) or a message's own video picture (member_yt_pictures:
    read from YouTube's picture host only, kept); None for anything else."""
    if not url:
        return None
    try:
        import member_yt_pictures as myp
        if url.startswith(myp.PREFIX):
            return myp.bytes_for(url)
        local = _site_file(url)
        if local is not None:
            return local.read_bytes() if local.stat().st_size <= IMAGE_BYTES_MAX else None
        if _storage_ok(url, business_id):
            return _fetch(url)
    except Exception:  # noqa: BLE001
        logger.info("story picture: a picture couldn't be read", exc_info=True)
    return None


def open_picture(raw: Optional[bytes], longest: int = 2200):
    """Bytes → an upright RGB picture, or None (not a photo we take, too big)."""
    if not raw:
        return None
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(raw))
        if im.format not in ("JPEG", "PNG", "WEBP", "MPO") or im.width * im.height > IMAGE_PIXELS_MAX:
            return None
        if im.format in ("JPEG", "MPO"):
            im.draft("RGB", (longest, longest))
        im.load()
        im = ImageOps.exif_transpose(im)
        im.thumbnail((longest, longest))
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.getchannel("A"))
            return flat
        return im.convert("RGB")
    except Exception:  # noqa: BLE001
        return None


# ─── story pictures: drawing ─────────────────────────────────────────

# Each pairing's faces for the picture (member_lumen_fonts.PAIRS): the
# heading face and its axes, the reading face's italic (a verse), the face
# for small words.
FACES = {
    "a": ("literata-normal", {"wght": 500}, "literata-italic", "figtree-normal"),
    "b": ("fraunces-normal", {"wght": 560, "SOFT": 50, "WONK": 0}, "literata-italic", "onest-normal"),
    "c": ("mona-sans-normal", {"wght": 760, "wdth": 112}, "source-serif-4-italic", "mona-sans-normal"),
}
_AXIS_TAGS = {"weight": "wght", "width": "wdth", "optical size": "opsz", "softness": "SOFT", "wonky": "WONK"}
# The latin file covers Latin-1 and the punctuation a title uses; anything
# past it takes the latin-ext file.
_LATIN_MORE = set("‘’“”–—…·•€™Œœı")


def _font_file(stem: str, text: str = "") -> str:
    import member_lumen_fonts as lmf
    ext = any(ord(c) > 0xFF and c not in _LATIN_MORE for c in text)
    return str(lmf.FONT_DIR / f"{stem}-{'latin-ext' if ext else 'latin'}.woff2")


_FONTS: Dict[Tuple[str, int, Tuple[Tuple[str, float], ...]], Any] = {}


def font(stem: str, size: int, axes: Optional[Mapping[str, float]] = None, text: str = ""):
    """One face at one size and weight (the variable fonts, set by axis)."""
    from PIL import ImageFont
    path = _font_file(stem, text)
    want = dict(axes or {})
    key = (path, int(size), tuple(sorted(want.items())))
    got = _FONTS.get(key)
    if got is not None:
        return got
    f = ImageFont.truetype(path, int(size))
    try:
        vals = []
        for ax in f.get_variation_axes():
            nm = ax.get("name")
            nm = nm.decode() if isinstance(nm, bytes) else str(nm)
            tag = _AXIS_TAGS.get(nm.lower(), nm)
            v = want.get(tag, ax.get("default"))
            if tag == "opsz" and "opsz" not in want:
                v = size * 0.75
            vals.append(max(ax["minimum"], min(ax["maximum"], v)))
        if vals:
            f.set_variation_by_axes(vals)
    except Exception:  # noqa: BLE001  (a face with no axes draws as it is)
        pass
    if len(_FONTS) > 256:
        _FONTS.clear()
    _FONTS[key] = f
    return f


def _rgb(hex_: str, fallback=(20, 20, 20)) -> Tuple[int, int, int]:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", str(hex_ or "").strip())
    if not m:
        return fallback
    h = m.group(1)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _mix(a, b, t: float):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def _wrap(text: str, f, width: int):
    out, line = [], ""
    for w in str(text or "").split():
        trial = f"{line} {w}" if line else w
        if line and f.getlength(trial) > width:
            out.append(line)
            line = w
        else:
            line = trial
    if line:
        out.append(line)
    return out


def _balanced(text: str, f, width: int):
    """_wrap at the narrowest width that keeps the same number of lines, so
    a title's lines are even and none is left with one word."""
    lines = _wrap(text, f, width)
    if len(lines) < 2:
        return lines
    lo, hi = width * 0.5, float(width)
    for _ in range(12):
        mid = (lo + hi) / 2
        if len(_wrap(text, f, mid)) <= len(lines):
            hi = mid
        else:
            lo = mid
    return _wrap(text, f, hi)


def _fit_end(text: str, f, width: int) -> str:
    if f.getlength(text) <= width:
        return text
    while len(text) > 1 and f.getlength(text + "…") > width:
        text = text[:-1]
    return text.rstrip(" ,;:") + "…"


def _tracked(draw, xy, text: str, f, fill, spacing: float) -> None:
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill, anchor="ls")
        x += f.getlength(ch) + spacing


def _tracked_len(text: str, f, spacing: float) -> float:
    return sum(f.getlength(c) for c in text) + spacing * max(0, len(text) - 1)


def _cover(im, w: int, h: int, bias: float = 0.38):
    from PIL import Image
    r = max(w / im.width, h / im.height)
    nw, nh = max(w, round(im.width * r)), max(h, round(im.height * r))
    im = im.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = int((nh - h) * bias)
    return im.crop((x, y, x + w, y + h))


# The scrim, top to bottom: a veil for the church's name (as deep as the
# picture behind it is bright), clear through the middle, deep under the
# words.
SCRIM = ((0.0, 1.0), (0.2, 0.74), (0.36, 0.08), (0.46, 0.4), (0.58, 0.8), (1.0, 0.94))


def _scrim_mask(top: float):
    """The scrim's strength per row: SCRIM, its first two stops scaled by
    `top` (the veil behind the name)."""
    from PIL import Image
    stops = [(t, v * top if i < 2 else v) for i, (t, v) in enumerate(SCRIM)]
    col = Image.new("L", (1, H))
    for y in range(H):
        t = y / (H - 1)
        for (a, va), (b, vb) in zip(stops, stops[1:]):
            if a <= t <= b:
                col.putpixel((0, y), int(round(255 * (va + (vb - va) * (t - a) / (b - a)))))
                break
    return col.resize((W, H))


def _photo_layer(photo, look: str, marks: Mapping[str, Any]):
    """The content's picture under its calm scrim of the church's deep colour."""
    from PIL import Image, ImageEnhance, ImageOps, ImageStat
    base = _cover(photo, W, H)
    if look in ("bw", "church"):
        g = ImageOps.grayscale(base)
        base = (ImageOps.colorize(g, black=_mix(_rgb(marks["night"]), (0, 0, 0), 0.4), white=(250, 248, 244))
                if look == "church" else g.convert("RGB"))
    else:
        base = ImageEnhance.Color(base).enhance(0.9)
    # how bright the picture is behind the church's name: 0.42 for a dark one, up to 0.8
    band = ImageStat.Stat(base.convert("L").crop((0, 170, W, 370))).mean[0]
    top = max(0.42, min(0.8, 0.42 + (band - 90) / 330))
    night = _mix(_rgb(marks["night"]), (8, 8, 10), 0.35)
    return Image.composite(Image.new("RGB", (W, H), night), base, _scrim_mask(top))


def _plain_layer(marks: Mapping[str, Any]):
    """No picture: the church's deep colour with one soft light of its own."""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("RGB", (W, H), _rgb(marks["night"]))
    glow = Image.new("L", (W // 4, H // 4), 0)
    ImageDraw.Draw(glow).ellipse(((W - 560) // 4, -380 // 4, (W + 560) // 4, 700 // 4), fill=52)
    glow = glow.filter(ImageFilter.GaussianBlur(16)).resize((W, H), Image.BILINEAR)
    return Image.composite(Image.new("RGB", (W, H), _rgb(marks["fill"])), im, glow)


def _disc(r: int):
    from PIL import Image, ImageDraw
    big = Image.new("L", (8 * r, 8 * r), 0)
    ImageDraw.Draw(big).ellipse((0, 0, 8 * r - 1, 8 * r - 1), fill=255)
    return big.resize((2 * r, 2 * r), Image.LANCZOS)


def _mark(im, marks: Mapping[str, Any], logo, cx: int, cy: int, r: int) -> None:
    """The church's mark: its logo on a white disc, else its initials in
    the serif's italic on its colour (the top bar's .lm-logo)."""
    from PIL import Image, ImageDraw
    if logo is not None:
        plate = Image.new("RGB", (2 * r, 2 * r), (255, 255, 255))
        lg = logo.copy()
        lg.thumbnail((int(r * 1.42), int(r * 1.42)))
        plate.paste(lg, (r - lg.width // 2, r - lg.height // 2))
        im.paste(plate, (cx - r, cy - r), _disc(r))
        return
    im.paste(Image.new("RGB", (2 * r, 2 * r), _rgb(marks["fill"])), (cx - r, cy - r), _disc(r))
    disp, axes, _ital, _ui = FACES.get(marks.get("pair"), FACES["a"])
    face = disp if marks.get("pair") == "c" else disp.replace("-normal", "-italic")
    f = font(face, int(r * 0.82), axes, marks["mark"])
    ImageDraw.Draw(im).text((cx, cy + 1), marks["mark"], font=f, fill=_rgb(marks["on_fill"], (255, 255, 255)), anchor="mm")


def render(spec: Mapping[str, Any], marks: Mapping[str, Any], photo=None, logo=None) -> bytes:
    """The story picture, 1080 x 1920, as PNG bytes. `spec` is lookup()'s,
    `marks` church_marks()'s; `photo` and `logo` opened pictures or None.
    Everything that matters sits inside a story's safe area (the top and
    foot 250 px carry the phone's own bars)."""
    from PIL import Image, ImageDraw
    disp, daxes, ital, uist = FACES.get(marks.get("pair"), FACES["a"])
    verse = spec.get("kind") == "verse"
    im = (_photo_layer(photo, spec.get("look") or "colour", marks) if photo is not None and not verse
          else _plain_layer(marks))
    ink = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(ink)
    white = (255, 255, 255, 255)
    soft = (255, 255, 255, 212)
    lit = _rgb(marks.get("lit"), (255, 255, 255)) + (255,)
    width = W - 2 * PAD

    # the church: its mark and name
    r, cy = 42, 270
    _mark(im, marks, logo, PAD + r, cy, r)
    nf = font(uist, 38, {"wght": 650}, marks["name"])
    name = _fit_end(marks["name"], nf, width - 2 * r - 24)
    if photo is not None and not verse:
        # a soft shadow under the name, so a bright picture never washes it out
        from PIL import ImageFilter
        sh = Image.new("L", (W, 2 * cy), 0)
        ImageDraw.Draw(sh).text((PAD + 2 * r + 24, cy + 2), name, font=nf, fill=150, anchor="lm")
        sh = sh.filter(ImageFilter.GaussianBlur(10))
        im.paste(Image.new("RGB", sh.size, (0, 0, 0)), (0, 0), sh)
    d.text((PAD + 2 * r + 24, cy), name, font=nf, fill=white, anchor="lm")

    # the foot: a short rule in the church's colour, the public link as words
    size = 30
    link = _shown_link(marks.get("host") or "", spec.get("href") or "/")
    lf = font(uist, size, {"wght": 600}, link)
    while size > 22 and lf.getlength(link) > width:
        size -= 2
        lf = font(uist, size, {"wght": 600}, link)
    base = H - 300
    d.text((PAD, base), _fit_end(link, lf, width), font=lf, fill=soft, anchor="ls")
    d.rectangle((PAD, base - size - 32, PAD + 72, base - size - 28), fill=lit)
    bottom = base - size - 28 - 62

    kick = (spec.get("kicker") or "").upper()
    kf = font(uist, 28, {"wght": 700}, kick)
    while kick and _tracked_len(kick, kf, 3.9) > width:
        kick = kick[:-2].rstrip(" ·,") + "…"
    if verse:
        # the verse in the reading face, its reference under it, the block centred
        words = spec.get("title") or ""
        vs, lines = 84, []
        for vs in range(84, 40, -2):
            lines = _wrap(words, font(ital, vs, {"wght": 420}, words), width)
            if len(lines) * vs * 1.36 <= 940:
                break
        vf = font(ital, vs, {"wght": 420}, words)
        lines = _balanced(words, vf, width)
        lh = int(vs * 1.36)
        quote_h = 96
        block = quote_h + (len(lines) - 1) * lh + vs + 86
        top = max(430, (400 + bottom) // 2 - block // 2)
        qf = font(disp.replace("-normal", "-italic") if marks.get("pair") != "c" else ital, 210, daxes)
        d.text((PAD - 6, top + 150), "“", font=qf, fill=lit, anchor="ls")
        y = top + quote_h + vs
        for ln in lines:
            d.text((PAD, y), ln, font=vf, fill=white, anchor="ls")
            y += lh
        _tracked(d, (PAD, y - lh + 86), kick, kf, lit, 3.9)
    else:
        # from the foot up: the line, the title in the serif, the small capitals
        y = bottom
        sub = spec.get("sub") or ""
        if sub:
            sf = font(uist, 34, {"wght": 500}, sub)
            sl = _balanced(sub, sf, width)
            if len(sl) > 2:
                sl = _wrap(sub, sf, width)
                sl = [sl[0], _fit_end(" ".join(sl[1:]), sf, width)]
            for ln in reversed(sl):
                d.text((PAD, y), ln, font=sf, fill=soft, anchor="ls")
                y -= 46
            y -= 22
        title = spec.get("title") or ""
        ts, tl = 120, []
        for ts in range(120, 58, -4):
            tl = _wrap(title, font(disp, ts, daxes, title), width)
            if len(tl) <= 4 and len(tl) * ts * 1.06 <= 620:
                break
        tf = font(disp, ts, daxes, title)
        if len(tl) > 4:
            tl = tl[:3] + [_fit_end(" ".join(tl[3:]), tf, width)]
        else:
            tl = _balanced(title, tf, width)
        lh = int(ts * 1.06)
        for ln in reversed(tl):
            d.text((PAD, y), ln, font=tf, fill=white, anchor="ls")
            y -= lh
        y += lh - ts - 38
        _tracked(d, (PAD, y), kick, kf, lit, 3.9)
    im = Image.alpha_composite(im.convert("RGBA"), ink).convert("RGB")
    out = io.BytesIO()
    im.save(out, "PNG", compress_level=6)
    return out.getvalue()


# ─── story pictures: kept ────────────────────────────────────────────

_PNG: "OrderedDict[str, bytes]" = OrderedDict()
_PNG_LOCK = threading.Lock()
# One drawing at a time per server copy: the faces are shared objects.
_DRAW = threading.Lock()


def tag_of(spec: Mapping[str, Any], marks: Mapping[str, Any]) -> str:
    raw = json.dumps([VERSION, dict(spec), dict(marks)], sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def picture(spec: Mapping[str, Any], marks: Mapping[str, Any], business_id: str) -> Tuple[str, bytes]:
    """(tag, PNG) for what it shows, drawn once per server copy and kept
    within PNG_BUDGET. A message's video picture comes over the network
    (member_yt_pictures): drawn without it when YouTube didn't answer, that
    PNG is neither kept nor tagged (tag ''), so the next ask tries again."""
    import member_yt_pictures as myp
    tag = tag_of(spec, marks)
    with _PNG_LOCK:
        got = _PNG.get(tag)
        if got is not None:
            _PNG.move_to_end(tag)
            return tag, got
    photo = open_picture(picture_bytes(spec.get("pic") or "", business_id)) if spec.get("pic") else None
    logo = open_picture(picture_bytes(marks.get("logo") or "", business_id), longest=400) if marks.get("logo") else None
    with _DRAW:
        png = render(spec, marks, photo, logo)
    if photo is None and str(spec.get("pic") or "").startswith(myp.PREFIX):
        return "", png
    with _PNG_LOCK:
        _PNG[tag] = png
        while sum(len(v) for v in _PNG.values()) > PNG_BUDGET and len(_PNG) > 1:
            _PNG.popitem(last=False)
    return tag, png


# ─── the route ───────────────────────────────────────────────────────

_NO = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


@router.get("/my/story/{kind}/{name}", include_in_schema=False)
async def story(request: Request, kind: str, name: str):
    """A story picture (module docstring). 404 for anything that isn't
    this church's own published or public thing, for someone signed out,
    and wherever the new look doesn't show; 429 past the member's limit;
    503 when a read failed."""
    import member_lumen
    import member_portal as mp
    import public_site
    import rate_limit
    if kind not in KINDS or not name.endswith(".png") or len(name) > 120:
        return Response(status_code=404, headers=_NO)
    ref = name[:-4]
    church = await mp._church_or_404(request)
    biz, site = church["business"], church.get("site")
    sess = await asyncio.to_thread(mp._session_for, request, church)
    if not sess or sess.get("unavailable") or not sess.get("me"):
        return Response(status_code=404, headers=_NO)
    if not await member_lumen.decide(request, {"business": biz, "session": sess}):
        return Response(status_code=404, headers=_NO)
    who = str((sess.get("me") or {}).get("id") or "")
    if not rate_limit.allow("member_story", f"{biz['id']}|{who}"):
        return Response(status_code=429, headers={**_NO, "Retry-After": str(rate_limit.retry_after("member_story"))})
    tr = str(request.query_params.get("t") or "")[:8]
    try:
        spec = await asyncio.to_thread(lookup_kept, biz, site, kind, ref, tr)
    except Unavailable:
        return Response(status_code=503, headers=_NO)
    if not spec:
        return Response(status_code=404, headers=_NO)
    marks = church_marks(biz, site, public_site.public_host(request))
    tag = tag_of(spec, marks)
    keep = {"Cache-Control": "private, max-age=600", "ETag": f'"{tag}"', "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == f'"{tag}"':
        return Response(status_code=304, headers=keep)
    tag, png = await asyncio.to_thread(picture, spec, marks, str(biz["id"]))
    if not tag:
        # drawn without its video picture (YouTube didn't answer): not kept by the phone either
        return Response(content=png, media_type="image/png", headers=_NO)
    return Response(content=png, media_type="image/png", headers=keep)
