"""
member_portal_share.py — Share good news, in the member app.

From the approved canvas "Church News & Celebrations" (Hfrz3Y174kbDmJv1G4puVq),
board 5 "Share good news (a pastor looks first)", built to look as drawn:
"For the whole church · Tell us what God did.", what happened (six kinds,
two a row), the box ("Tell the church", its hint by kind), one photo, who
sees it (the whole church, or just my groups), the guard ("Your pastors read
it first. News about someone else … goes up only with their OK.") and "Send
to the pastors"; then "Sent · We can't wait to celebrate." Board 2's "Have
good news?" card on News opens it (share_card).

  GET  /my/news/share             (member_portal_news.serve)
  POST /my/news/share             the form, with its photo (news_share.share)
  POST /my/news/share/take-back   {id}: theirs, before it's posted

What a member sent and hasn't seen go up yet waits at the foot of the page
("With your pastors"), each with Take it back. The owner's preview shows
the page; nothing saves.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request

import news_share as ns

logger = logging.getLogger("member_portal_share")
router = APIRouter(tags=["member-portal"])

# The kinds' discs, in the family colours the canvas gives them.
HUE = {"baby": "coral", "grad": "violet", "love": "acc", "job": "teal", "bapt": "teal", "pray": "gold"}
ICONS = {
    "baby": ('<path d="M9 12h.01M15 12h.01"/><path d="M10 16c.5.3 1.2.5 2 .5s1.5-.2 2-.5"/><path d="M19 6.3a9 9 0 0 1 1.8 3.9'
             ' 2 2 0 0 1 0 3.6 9 9 0 0 1-17.6 0 2 2 0 0 1 0-3.6A9 9 0 0 1 12 3c2 0 3.5 1.1 3.5 2.5s-.9 2.5-2 2.5c-.8 0-1.5-.4-1.5-1"/>'),
    "grad": ('<path d="M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0'
             ' 1.66 0z"/><path d="M22 10v6"/><path d="M6 12.5V16a6 3 0 0 0 12 0v-3.5"/>'),
    "love": ('<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5'
             'c0 2.3 1.5 4.05 3 5.5l7 7Z"/>'),
    "job": ('<path d="M16 20V4a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/><path d="M2 8a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H4'
            'a2 2 0 0 1-2-2z"/>'),
    "bapt": ('<path d="M7 16.3c2.2 0 4-1.83 4-4.05 0-1.16-.57-2.26-1.71-3.19S7.29 6.75 7 5.3c-.29 1.45-1.14 2.84-2.29 3.76S3 11.1 3'
             ' 12.25c0 2.22 1.8 4.05 4 4.05z"/><path d="M12.56 6.6A10.97 10.97 0 0 0 14 3.02c.5 2.5 2 4.9 4 6.5s3 3.5 3 5.5a6.98 6.98'
             ' 0 0 1-11.91 4.97"/>'),
    "pray": ('<path d="M11 14h2a2 2 0 1 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 16"/><path d="m7 20 1.6-1.4c.3-.4.8-.6 1.4-.6h4c1.1 0 2.1-.4'
             ' 2.8-1.2l4.6-4.4a2 2 0 0 0-2.75-2.91l-4.2 3.9"/><path d="M19.5 8.5c.7-.7 1.5-1.6 1.5-2.7A2.73 2.73 0 0 0 16 4a2.78'
             ' 2.78 0 0 0-5 1.8c0 1.2.8 2 1.5 2.8L16 12Z"/>'),
    "image": ('<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/>'
              '<path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>'),
    "check": '<path d="M20 6 9 17l-5-5"/>',
}

DONE = {
    "shared": "",
    "care": ("You're not alone. If you're thinking about hurting yourself, call or text 988 (the Suicide & Crisis "
             "Lifeline) any time. Your pastor has been told so they can reach out."),
    "taken_back": "Taken back. Nobody will see it.",
}
ERRORS = {
    "share_kind": "Choose what happened first.",
    "share_empty": "Tell the church what happened first.",
    "share_long": f"That's a little long. Keep it under {ns.TEXT_MAX} letters.",
    "share_many": f"You have {ns.WAITING_MAX} waiting with your pastors already. They'll get to them soon.",
    "share_groups": "You're not in a group yet, so this goes to the whole church or not at all.",
    "photo_bad": "That file isn't a photo we can use. Choose a JPG, PNG or WebP under 12 MB.",
    "photo_no": "That photo can't be shared here. Choose another, or send it without one.",
    "photo_busy": "We couldn't check the photo just now, so nothing was sent. Please try again.",
    "share_gone": "That one isn't waiting any more.",
}

SHARE_CSS = """
.sh-lede{margin:8px 0 0;font-size:15px;color:var(--fg2);line-height:1.45;}
.sh-lbl{display:block;margin:24px 0 10px;font-size:12.5px;font-weight:650;letter-spacing:.06em;text-transform:uppercase;color:var(--fg3);}
.sh-kinds{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
.sh-opt,.sh-photo{font-size:15px;font-weight:400;color:var(--fg);}
.sh-opt{position:relative;display:block;cursor:pointer;}
.sh-opt input{position:absolute;opacity:0;width:1px;height:1px;}
.sh-k{display:flex;align-items:center;gap:10px;min-height:56px;height:100%;box-sizing:border-box;padding:8px 12px;border-radius:14px;
  background:var(--s1);font-size:14.5px;font-weight:620;line-height:1.2;}
.sh-disc{width:34px;height:34px;border-radius:11px;flex:none;display:grid;place-items:center;}
.sh-disc.coral{background:var(--coral-deep);color:var(--coral-ink);}
.sh-disc.violet{background:var(--violet-deep);color:var(--violet-ink);}
.sh-disc.acc{background:var(--acc-deep);color:var(--acc);}
.sh-disc.teal{background:var(--teal-deep);color:var(--teal-ink);}
.sh-disc.gold{background:var(--gold-deep);color:var(--gold-ink);}
.sh-opt input:checked+.sh-k,.sh-opt input:checked+.sh-w{background:var(--acc-deep);box-shadow:inset 0 0 0 1.5px var(--acc);}
.sh-opt input:focus-visible+.sh-k,.sh-opt input:focus-visible+.sh-w{outline:2px solid var(--acc);outline-offset:2px;}
.sh-field{margin:14px 0 0;border-radius:var(--r-md);background:var(--s1);padding:4px 16px;}
.sh-field label{display:block;font-size:12.5px;font-weight:650;letter-spacing:.05em;text-transform:uppercase;color:var(--fg3);padding-top:10px;}
.sh-field textarea{display:block;width:100%;box-sizing:border-box;background:transparent;border:0;outline:none;font:inherit;font-size:16px;
  color:var(--fg);padding:6px 0 12px;resize:none;min-height:128px;line-height:1.45;}
.sh-field textarea::placeholder{color:var(--fg3);}
.sh-photo{position:relative;margin:10px 0 0;display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:var(--r-md);
  background:var(--s1);cursor:pointer;}
.sh-photo input{position:absolute;inset:0;opacity:0;cursor:pointer;width:100%;}
.sh-photo input:focus-visible~.sh-pt b{text-decoration:underline;}
.sh-pt{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;}
.sh-pt b{font-size:15px;font-weight:620;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.sh-pt small{font-size:12.5px;color:var(--fg2);}
.sh-sq{width:42px;height:42px;border-radius:12px;flex:none;display:grid;place-items:center;background:var(--acc-deep);color:var(--acc);}
.sh-thumb{width:52px;height:52px;border-radius:12px;overflow:hidden;flex:none;display:none;background:var(--s2);}
.sh-thumb img{width:100%;height:100%;object-fit:cover;display:block;}
.sh-photo.has .sh-thumb{display:block;}
.sh-photo.has .sh-sq{display:none;}
.sh-who{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;}
.sh-who.one{grid-template-columns:minmax(0,1fr);}
.sh-w{display:flex;flex-direction:column;gap:2px;height:100%;box-sizing:border-box;padding:12px;border-radius:14px;background:var(--s1);}
.sh-w b{font-size:14.5px;font-weight:650;}
.sh-w small{font-size:12.5px;color:var(--fg2);line-height:1.3;}
.sh-opt input:checked+.sh-w b{color:var(--acc);}
.sh-guard{display:flex;gap:12px;align-items:flex-start;margin:20px 0 0;padding:14px;border-radius:var(--r-md);background:var(--s1);
  font-size:13.5px;color:var(--fg2);line-height:1.45;}
.sh-guard .mb-ic{flex:none;margin-top:1px;color:var(--acc);}
.sh-guard b{color:var(--fg);font-weight:650;}
.sh-go{display:flex;align-items:center;justify-content:center;width:100%;min-height:54px;margin:20px 0 0;border:0;border-radius:16px;
  background:var(--acc-fill);color:var(--on-acc);font:inherit;font-size:16.5px;font-weight:600;letter-spacing:-.01em;cursor:pointer;}
.sh-go[disabled]{opacity:.65;}
.sh-done{display:flex;gap:14px;align-items:flex-start;margin:20px 0 0;padding:18px;border-radius:var(--r-lg);background:var(--s1);}
.sh-done .sh-disc{background:var(--acc-fill);color:var(--on-acc);border-radius:50%;}
.sh-done .sh-pt{gap:4px;}
.sh-done .sh-pt b{font-size:16.5px;font-weight:660;white-space:normal;}
.sh-done .sh-pt small{font-size:14px;line-height:1.45;}
.sh-acts{display:flex;gap:10px;flex-wrap:wrap;margin:20px 0 0;}
.sh-btn{display:inline-flex;align-items:center;justify-content:center;min-height:46px;padding:0 20px;border-radius:999px;background:var(--s1);
  color:var(--fg);font-size:15.5px;font-weight:600;letter-spacing:-.01em;text-decoration:none;white-space:nowrap;}
.sh-btn.s2{background:var(--s2);}
.sh-mine{margin:0;border-radius:var(--r-md);background:var(--s1);overflow:hidden;}
.sh-row{display:flex;align-items:center;gap:12px;padding:12px 14px;position:relative;}
.sh-row+.sh-row::before{content:"";position:absolute;top:0;left:14px;right:0;height:.5px;background:var(--line);}
.sh-row .sh-pt b{font-size:15px;}
.sh-row .sh-pt small{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.sh-row form{margin:0;flex:none;}
.sh-back{border:0;background:none;padding:0 2px;min-height:36px;font:inherit;font-size:13.5px;font-weight:650;color:var(--acc);cursor:pointer;}
"""

# The hint follows what happened; a chosen photo shows as its thumbnail
# (tap it again to take it off); the button says it's sending.
SHARE_JS = """<script>(function(){
var f=document.getElementById('sh-form');if(!f)return;var t=f.querySelector('textarea');
f.addEventListener('change',function(ev){var r=ev.target;if(r.name==='kind'&&r.getAttribute('data-ph')){t.placeholder=r.getAttribute('data-ph');}});
var pick=document.getElementById('sh-photo');var inp=pick&&pick.querySelector('input');
if(inp){var b=pick.querySelector('.sh-pt b'),s=pick.querySelector('.sh-pt small'),img=pick.querySelector('.sh-thumb img');
 var b0=b.textContent,s0=s.textContent;
 inp.addEventListener('click',function(ev){if(inp.value){ev.preventDefault();inp.value='';pick.classList.remove('has');b.textContent=b0;s.textContent=s0;}});
 inp.addEventListener('change',function(){var x=inp.files&&inp.files[0];if(!x){return;}
  pick.classList.add('has');b.textContent=x.name;s.textContent='Tap to take it off';
  try{img.src=URL.createObjectURL(x);}catch(e){}});}
f.addEventListener('submit',function(ev){if(!(t.value||'').trim()){ev.preventDefault();t.focus();return;}
 var go=f.querySelector('.sh-go');if(go){go.disabled=true;go.textContent='Sending…';}});
})();</script>"""


def _ic(name: str, size: int = 18) -> str:
    import member_portal_news as mpn
    if name in ICONS:
        return (f'<svg class="mb-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')
    return mpn._ic(name, size)


def _e(v: Any) -> str:
    from member_portal import _e as esc
    return esc(v)


def share_card() -> str:
    """Board 2's "Have good news?", under the posts on News (its look is
    member_portal_news.NEWS_CSS's .nw-share)."""
    return (f'<a class="nw-share" href="/my/news/share"><span class="nw-sd">{_ic("cheer", 18)}</span>'
            f'<span class="nw-t"><b>Have good news?</b><small>A new baby, a graduation, an answered prayer. '
            f'Tell us and a pastor will share it.</small></span>{_ic("chevron", 18)}</a>')


def _groups_line(names: List[str]) -> str:
    if len(names) == 1:
        return f"Only {names[0]} sees it"
    if len(names) == 2:
        return f"Only {names[0]} and {names[1]} see it"
    return f"Only your {len(names)} groups see it"


def _flash(request: Request) -> str:
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if request.query_params.get("done") == "taken_back":
        return f'<p class="mp-ok mp-flash" role="status">{_e(DONE["taken_back"])}</p>'
    import member_portal_news as mpn
    return mpn._flash(request)


def _mine(biz: Dict[str, Any], waiting: List[Dict[str, Any]]) -> str:
    import member_portal_news as mpn
    if not waiting:
        return ""
    rows = "".join(
        f'<div class="sh-row"><span class="sh-disc {HUE.get((w.get("attach") or {}).get("share") or "", "gold")}">'
        f'{_ic((w.get("attach") or {}).get("share") or "cheer", 18)}</span><span class="sh-pt"><b>{_e(w.get("title") or "Good news")}</b>'
        f'<small>Sent {_e(mpn.when_label(biz, w.get("created_at")))} · {_e((w.get("body") or "")[:90])}</small></span>'
        f'<form method="post" action="/my/news/share/take-back"><input type="hidden" name="id" value="{_e(w["id"])}">'
        f'<button class="sh-back" type="submit">Take it back</button></form></div>'
        for w in waiting)
    return f'<span class="sh-lbl">With your pastors</span><div class="sh-mine">{rows}</div>'


def render_share(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any],
                 groups: Optional[List[Dict[str, Any]]], waiting: Optional[List[Dict[str, Any]]],
                 phone: bool) -> Tuple[str, int]:
    import member_portal_news as mpn
    from member_portal import _shell
    head = '<a class="mb-back" href="/my/news">News</a>'
    css = f"<style>{mpn.NEWS_CSS}{SHARE_CSS}</style>"
    if groups is None or waiting is None:
        body = f'{head}<p class="mp-err" role="alert">This couldn\'t load just now. Please try again in a moment.</p>'
        return _shell(biz, site, "Share good news", css + body, tab="home", who=me), 503
    q = request.query_params
    if q.get("sent") in ("all", "groups"):
        where = "your groups' News" if q.get("sent") == "groups" else "News"
        note = (f"You'll get a note the moment it's on {where}. Most good news goes up the same day." if phone else
                f"It shows on {where} under your name once it's up. Most good news goes up the same day.")
        care = (f'<p class="mp-ok mp-flash" role="status">{_e(DONE["care"])}</p>' if q.get("done") == "care" else "")
        body = (f'{head}<div class="nw-head"><p class="nw-eb">Sent</p><h1 class="nw-lt">We can\'t wait to <em>celebrate.</em></h1></div>'
                f'{care}'
                f'<div class="sh-done"><span class="sh-disc">{_ic("check", 18)}</span><span class="sh-pt">'
                f'<b>Your pastors have it</b><small>{_e(note)}</small></span></div>'
                f'<div class="sh-acts"><a class="sh-btn" href="/my/news">Back to News</a>'
                f'<a class="sh-btn s2" href="/my/news/share">Share something else</a></div>')
        return _shell(biz, site, "Share good news", css + body, tab="home", who=me), 200
    first = ns.KINDS[1][0]
    kinds = "".join(
        f'<label class="sh-opt"><input type="radio" name="kind" value="{k}" data-ph="{_e(ph)}"{" checked" if k == first else ""}>'
        f'<span class="sh-k"><span class="sh-disc {HUE[k]}">{_ic(k, 18)}</span><span>{_e(label)}</span></span></label>'
        for k, label, ph in ns.KINDS)
    names = [g.get("name") or "Your group" for g in groups]
    who = (f'<label class="sh-opt"><input type="radio" name="who" value="all" checked><span class="sh-w"><b>The whole church</b>'
           f'<small>On News, for every signed-in member</small></span></label>')
    if names:
        who += (f'<label class="sh-opt"><input type="radio" name="who" value="groups"><span class="sh-w"><b>Just my groups</b>'
                f'<small>{_e(_groups_line(names))}</small></span></label>')
    body = (f'{head}<div class="nw-head"><p class="nw-eb">For the whole church</p>'
            f'<h1 class="nw-lt">Tell us what <em>God did.</em></h1></div>'
            f'<p class="sh-lede">A pastor reads it first. Then it\'s posted under your name, and the church can celebrate with you.</p>'
            f'{_flash(request)}'
            f'<form id="sh-form" method="post" action="/my/news/share" enctype="multipart/form-data">'
            f'<span class="sh-lbl" id="sh-l-kind">What happened?</span>'
            f'<div class="sh-kinds" role="radiogroup" aria-labelledby="sh-l-kind">{kinds}</div>'
            f'<div class="sh-field"><label for="sh-text">Tell the church</label>'
            f'<textarea id="sh-text" name="body" maxlength="{ns.TEXT_MAX}" required placeholder="{_e(ns.KINDS[1][2])}"></textarea></div>'
            f'<label class="sh-photo" id="sh-photo"><input type="file" name="photo" accept="image/jpeg,image/png,image/webp">'
            f'<span class="sh-sq">{_ic("image", 18)}</span><span class="sh-thumb"><img alt=""></span>'
            f'<span class="sh-pt"><b>Add a photo</b><small>One picture makes it. Faces of children need a parent\'s OK.</small></span></label>'
            f'<span class="sh-lbl" id="sh-l-who">Who sees it</span>'
            f'<div class="sh-who{"" if names else " one"}" role="radiogroup" aria-labelledby="sh-l-who">{who}</div>'
            f'<p class="sh-guard">{_ic("shield", 18)}<span><b>Your pastors read it first.</b> News about someone else, like '
            f'their health or their family, goes up only with their OK.</span></p>'
            f'<button class="sh-go" type="submit">Send to the pastors</button></form>'
            f'{_mine(biz, waiting)}')
    return _shell(biz, site, "Share good news", css + body, tab="home", who=me, script=SHARE_JS), 200


async def serve_share(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any]) -> Tuple[str, int]:
    import church_news as cn
    import member_push
    business_id, me_id = str(biz["id"]), str(me["id"])
    mine_g, waiting, devices = await asyncio.gather(
        asyncio.to_thread(cn.my_groups, business_id, me_id), asyncio.to_thread(ns.mine, business_id, me_id),
        asyncio.to_thread(member_push.device_count, business_id, me_id))
    groups: Optional[List[Dict[str, Any]]] = None
    if mine_g is not None:
        import sb_clients
        groups = (await asyncio.to_thread(
            sb_clients.sb_get_as_service,
            f"/groups?business_id=eq.{ns._q(business_id)}&id=in.({cn._ids(mine_g)})&active=eq.true"
            f"&select=id,name&order=name.asc")) if mine_g else []
    phone = bool(devices) and "news" in member_push.church_kinds(biz.get("settings"))
    return render_share(biz, site, request, me, groups, waiting, phone)


def _go(**q: str):
    from fastapi.responses import RedirectResponse
    from member_portal import _SECURE_HEADERS
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v)
    return RedirectResponse("/my/news/share" + (f"?{qs}" if qs else ""), status_code=303, headers=_SECURE_HEADERS)


@router.post("/my/news/share", include_in_schema=False)
async def share_route(request: Request):
    import member_photos
    import member_portal_news as mpn
    church, me, form, stop = await mpn._who(request, "/my/news/share")
    if stop:
        return stop
    raw = None
    up = form.get("photo")
    if up is not None and hasattr(up, "read"):
        raw = await up.read(member_photos.MAX_BYTES + 1) or None
    who = "groups" if str(form.get("who") or "") == "groups" else "all"
    ok, code, _pid = await ns.share(church["business"], me, str(form.get("kind") or ""), str(form.get("body") or ""),
                                    who, raw)
    if not ok:
        return _go(err=code)
    return _go(sent=who, done=code if code == "care" else "")


@router.post("/my/news/share/take-back", include_in_schema=False)
async def take_back_route(request: Request):
    import member_portal_news as mpn
    church, me, form, stop = await mpn._who(request, "/my/news/share")
    if stop:
        return stop
    ok, code = await asyncio.to_thread(ns.take_back, str(church["business"]["id"]), str(me["id"]), str(form.get("id") or ""))
    return _go(done=code) if ok else _go(err=code)
