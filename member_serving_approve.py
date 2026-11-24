"""
member_serving_approve.py — To approve, on the member app's Serve page.

The approved canvas "Good News Approvals" (Ktoy4b4qXoCDPCDoRmCGxj), boards
2 to 4, built to look as drawn: good news a member shared for the whole
church waits on top of My serving for the pastors and the leaders the
office picked (news_approvers), with Post it, Edit first and Not now;
Edit first is its own page (her words in a box, her photo kept or left
off, then Post it); what someone else answered first stays a few hours
with who did it, and the buttons go.

  GET  /my/serving                 the section, on top (member_portal_serving)
  GET  /my/serving/approve/<id>    Edit first
  POST /my/serving/approve         {id, action: post|later, body?, drop_photo?}

Someone who approves but isn't on a Sunday team (or at a church that
doesn't schedule Sundays) gets My serving with only this on it, so the
note on their phone always lands somewhere.
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlencode

logger = logging.getLogger("member_serving_approve")

_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

DONE = {
    "ap_posted": "Posted. They get a note on their phone.",
    "ap_later": "Saved for later. They're never told no.",
}
ERRS = {
    "ap_gone": "Someone already answered that one.",
    "ap_empty": "Write something first.",
}
FLAG = {
    "harm": "The check marked some words in this one. Read it closely first.",
    "unchecked": "The check couldn't read this one. Read it closely first.",
    "care": "Words in this one sound like someone hurting. The pastor has been told in Prayer & care.",
}

APPROVE_CSS = """
.ap-sec{margin-top:22px;}
.ap-n{display:inline-block;min-width:22px;height:22px;padding:0 7px;box-sizing:border-box;border-radius:999px;background:var(--h);
  color:var(--on-h);font-size:12px;font-weight:700;line-height:22px;text-align:center;margin-left:8px;vertical-align:2px;}
.ap-card{border-radius:22px;background:var(--s1);border:1px solid var(--h-deep,var(--line));overflow:hidden;}
.ap-card + .ap-card{margin-top:10px;}
.ap-top{display:flex;gap:12px;align-items:center;padding:16px 16px 0;}
.ap-top .t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.ap-top b{font-size:16px;font-weight:650;}
.ap-top small{font-size:13px;color:var(--fg2);}
.ap-kind{display:block;margin:12px 16px 0;font-size:10.5px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--h-ink);}
.ap-body{margin:8px 16px 0;font-size:15.5px;line-height:1.45;white-space:pre-line;overflow-wrap:anywhere;}
.ap-flag{margin:10px 16px 0;padding:10px 12px;border-radius:12px;background:var(--gold-deep);color:var(--gold-ink);font-size:13.5px;line-height:1.4;}
.ap-pic{display:block;margin:12px 16px 0;width:calc(100% - 32px);max-height:240px;object-fit:cover;border-radius:14px;background:var(--s2);}
.ap-acts{display:flex;gap:8px;flex-wrap:wrap;padding:14px 16px 16px;}
.ap-acts form{margin:0;flex:1 1 auto;display:flex;}
.ap-acts .sv-btn{flex:1 1 auto;min-height:44px;}
.ap-acts .pri{background:var(--fg);color:var(--bg);}
.ap-acts .ghost{background:transparent;border:1px solid var(--line);color:var(--fg2);}
.ap-taken{border-color:var(--line);}
.ap-taken .ap-body{color:var(--fg3);}
.ap-who{margin:14px 16px 16px;padding:12px 14px;border-radius:14px;background:var(--s2);font-size:14px;line-height:1.35;color:var(--fg2);}
.ap-note{margin:10px 6px 0;font-size:12.5px;line-height:1.4;color:var(--fg3);}
.ap-edit label{display:block;margin-top:18px;font-size:13px;font-weight:600;color:var(--fg2);}
.ap-edit textarea{display:block;box-sizing:border-box;width:100%;margin-top:8px;padding:14px;border-radius:16px;border:1px solid var(--h-deep,var(--line));
  background:var(--bg);color:var(--fg);font:inherit;font-size:15.5px;line-height:1.45;min-height:180px;resize:vertical;}
.ap-edit .ap-photo{display:flex;gap:12px;align-items:center;margin-top:14px;padding:12px;border-radius:16px;background:var(--s1);}
.ap-edit .ap-photo img{width:64px;height:64px;border-radius:12px;object-fit:cover;flex:none;background:var(--s2);}
.ap-edit .ap-photo label{margin:0;flex:1;display:flex;gap:10px;align-items:center;font-size:14px;color:var(--fg);}
.ap-edit .ap-photo input{width:20px;height:20px;accent-color:var(--h);}
.ap-edit .sv-btn.pri{width:100%;min-height:52px;margin-top:20px;background:var(--fg);color:var(--bg);font-size:16px;}
.ap-edit p{margin:8px 0 0;font-size:13.5px;line-height:1.4;color:var(--fg2);}
"""


def _e(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _initials(name: str) -> str:
    parts = [p for p in str(name or "").split() if p[:1].isalpha()]
    return "".join(p[0] for p in parts[:2]).upper() or "?"


def _ago(iso: str, now: Optional[datetime] = None) -> str:
    try:
        at = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    secs = max(0, int(((now or datetime.now(timezone.utc)) - at).total_seconds()))
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{secs // 60} min ago"
    if secs < 86400:
        h = secs // 3600
        return f"{h} hr ago"
    d = secs // 86400
    return "yesterday" if d == 1 else f"{d} days ago"


def _hidden(**kv: str) -> str:
    return "".join(f'<input type="hidden" name="{_e(k)}" value="{_e(v)}">' for k, v in kv.items())


def _card(c: Dict[str, Any], now: datetime) -> str:
    pid = _e(c["id"])
    pic = f'<img class="ap-pic" src="/my/news/{pid}/photo/0" alt="The photo they added" loading="lazy">' if c.get("photos") else ""
    flag = f'<p class="ap-flag">{_e(FLAG[c["flag"]])}</p>' if c.get("flag") in FLAG else ""
    when = " · ".join(x for x in (f'For {c.get("for") or "the whole church"}', _ago(c.get("created_at") or "", now)) if x)
    return (f'<article class="ap-card" id="ap-{pid}"><div class="ap-top"><span class="sv-av">{_e(_initials(c["name"]))}</span>'
            f'<span class="t"><b>{_e(c["name"])}</b><small>{_e(when)}</small></span></div>'
            f'<span class="ap-kind">{_e(c.get("what") or "Good news")}</span>'
            f'<p class="ap-body">{_e(c.get("body"))}</p>{flag}{pic}'
            f'<div class="ap-acts">'
            f'<form method="post" action="/my/serving/approve">{_hidden(id=c["id"], action="post")}'
            f'<button class="sv-btn pri" type="submit">Post it</button></form>'
            f'<a class="sv-btn" href="/my/serving/approve/{pid}">Edit first</a>'
            f'<form method="post" action="/my/serving/approve">{_hidden(id=c["id"], action="later")}'
            f'<button class="sv-btn ghost" type="submit">Not now</button></form>'
            f'</div></article>')


def _taken(c: Dict[str, Any], now: datetime) -> str:
    did = "posted this" if c.get("status") == "posted" else "saved this for later"
    when = _ago(c.get("decided_at") or "", now)
    return (f'<article class="ap-card ap-taken"><div class="ap-top"><span class="sv-av">{_e(_initials(c["name"]))}</span>'
            f'<span class="t"><b>{_e(c["name"])} · {_e((c.get("what") or "good news").lower())}</b>'
            f'<small>{_e(_ago(c.get("created_at") or "", now))}</small></span></div>'
            f'<p class="ap-body">{_e(c.get("body"))}</p>'
            f'<p class="ap-who">{_e(c.get("by") or "Someone")} {did}{" " + _e(when) if when else ""}.</p></article>')


def section(ap: Optional[Dict[str, Any]]) -> str:
    """To approve, on top of My serving. '' for someone who doesn't approve,
    or with nothing waiting and nothing answered lately."""
    if not ap or not (ap.get("waiting") or ap.get("taken")):
        return ""
    now = datetime.now(timezone.utc)
    waiting = ap.get("waiting") or []
    n = f'<span class="ap-n">{len(waiting)}</span>' if waiting else ""
    cards = "".join(_card(c, now) for c in waiting) + "".join(_taken(c, now) for c in ap.get("taken") or [])
    return (f'<style>{APPROVE_CSS}</style><section class="sv-sec ap-sec" id="approve" aria-labelledby="ap-h">'
            f'<div class="sv-sh"><h2 id="ap-h">To approve{n}</h2><a href="/my/news">Good news</a></div>{cards}'
            f'<p class="ap-note">Whoever answers first decides, and the member is never told no.</p></section>')


def flash(request) -> str:
    """My serving's own flash, which knows these (member_portal_serving
    folds DONE and ERRS in)."""
    from member_portal_serving import _flash
    return _flash(request)


def only_page(biz, site, request, me: Dict[str, Any], ap: Dict[str, Any], tab: str) -> str:
    """My serving for someone who approves but has no Sunday team here."""
    from member_portal import _shell
    from member_portal_serving import SERVING_CSS
    inner = section(ap) or ('<p class="sv-lede" style="padding-top:18px">Nothing is waiting for you to approve. '
                            'When a member shares good news for the church, it shows here first.</p>')
    body = (f'<style>{SERVING_CSS}</style><a class="mb-back" href="/my">Home</a>'
            f'<div class="sv-lt h-teal"><p class="sv-eb">{_e(me.get("name") or "")}</p><h1 class="sv-h">My <em>serving</em></h1></div>'
            f'{flash(request)}{inner}')
    return _shell(biz, site, "My serving", body, tab=tab, who=me)


def edit_page(biz, site, request, me: Dict[str, Any], c: Dict[str, Any], tab: str) -> str:
    """Edit first: their words in a box, their photo kept or left off."""
    from member_portal import _shell
    from member_portal_serving import SERVING_CSS
    first = (str(c.get("name") or "").split() or ["their"])[0]
    pid = _e(c["id"])
    photo = (f'<div class="ap-photo"><img src="/my/news/{pid}/photo/0" alt="">'
             f'<label><input type="checkbox" name="drop_photo" value="1">Leave the photo off</label></div>'
             if c.get("photos") else "")
    flag = f'<p class="ap-flag" style="margin:14px 0 0">{_e(FLAG[c["flag"]])}</p>' if c.get("flag") in FLAG else ""
    body = (f'<style>{SERVING_CSS}{APPROVE_CSS}</style><a class="mb-back" href="/my/serving#approve">Cancel</a>'
            f'<div class="sv-lt h-teal"><p class="sv-eb">{_e(c.get("what") or "Good news")}</p>'
            f'<h1 class="sv-h">Edit <em>{_e(first)}’s</em> good news</h1></div>{flash(request)}'
            f'<form class="ap-edit" method="post" action="/my/serving/approve">{_hidden(id=c["id"], action="post")}'
            f'<p>It goes up under their name, with your changes, for {_e(c.get("for") or "the whole church")}.</p>{flag}'
            f'<label for="ap-body">What they shared</label>'
            f'<textarea id="ap-body" name="body" maxlength="1000" required>{_e(c.get("body"))}</textarea>{photo}'
            f'<button class="sv-btn pri" type="submit">Post it</button>'
            f'<p style="text-align:center">They get a note on their phone when it’s up.</p></form>')
    return _shell(biz, site, "Edit good news", body, tab=tab, who=me)


def _back(**q: str):
    from fastapi.responses import RedirectResponse
    from member_portal import _SECURE_HEADERS
    qs = urlencode({k: v for k, v in q.items() if v})
    return RedirectResponse(f"/my/serving{'?' + qs if qs else ''}#approve", status_code=303, headers=_SECURE_HEADERS)


async def decide(request):
    """POST /my/serving/approve: Post it (as written or edited) or Not now."""
    import news_approvers as nap
    import rate_limit
    from member_portal_church import _signed_in
    church, me, unavailable = await _signed_in(request)
    if unavailable:
        return _back(err="preview" if unavailable == "preview" else "error")
    if not me:
        from fastapi.responses import RedirectResponse
        from member_portal import _SECURE_HEADERS
        return RedirectResponse("/my", status_code=303, headers=_SECURE_HEADERS)
    biz = church["business"]
    form = await request.form()
    pid = str(form.get("id") or "")
    action = str(form.get("action") or "")
    if not _ID.match(pid) or action not in ("post", "later"):
        return _back()
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|{me['id']}"):
        return _back(err="slow")
    # Theirs to decide: they approve here, and may see this one.
    c = await asyncio.to_thread(nap.one, biz, str(me["id"]), pid)
    if c is None:
        return _back(err="error")
    if not c:
        return _back(err="ap_gone")
    body = form.get("body")
    code, _post, _told = await asyncio.to_thread(
        nap.settle, biz, pid, action, decided_by=f"contact:{me['id']}",
        body=str(body) if body is not None else None, drop_photo=bool(form.get("drop_photo")), statuses=("waiting",))
    logger.info("good news decided in the app", extra={"business_id": str(biz["id"]), "post_id": pid, "code": code})
    if code == "posted":
        return _back(done="ap_posted")
    if code == "later":
        return _back(done="ap_later")
    if code == "empty":
        from fastapi.responses import RedirectResponse
        from member_portal import _SECURE_HEADERS
        return RedirectResponse(f"/my/serving/approve/{pid}?err=ap_empty", status_code=303, headers=_SECURE_HEADERS)
    return _back(err="ap_gone" if code == "gone" else "error")
