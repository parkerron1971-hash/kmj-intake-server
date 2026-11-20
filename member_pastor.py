"""member_pastor.py — Meet the pastor, in the member app's new look ("Look 4.1").

Kevin, 2026-11-20, asked whether the app should have a pastor profile for
the Look 4.1 "Meet the pastor" tile: "yes add one."

WHO. The church already names its pastor through its roles (church_roles):
the senior role, called what its tradition calls it ("Lead Pastor",
"Pastor", "Rector, Pastor or Priest", "Elders (Shepherds)"…) or what the
church renamed it. Whoever holds it is the pastor: their name, and the
role's title. When several share it (Elders), the first by name, as
church_follow_up hands a card to the senior role. No one holds it: there
is no pastor in the app, and nothing here shows.

THE PICTURE. The church's Pastor picture spot (member_app_pictures,
settings.member_portal.pictures["pastor"]), set with the same Change flow
as every spot; else the pastor's own profile photo in the app (member_photos:
shown to members as every member photo is, an adult by birthdate); else
their initials.

THE NOTE. A short welcome note, in the church's settings
(settings.member_portal.pastor_note: {text, at, by}); no table of its own.
The owner (from their preview) and the people the owner named to change the
app's pictures (member_app_pictures.may_edit) write it on the page in edit
mode (/my/pastor?edit=pictures): POST /my/pastor/note, the picture route's
checks (same site, signed in, may_edit, the per-person limit), written to
this church's row only. A named member's words are checked first
(msg_screen), as every member's words are; the owner's are the church's.

WHERE. Home's Also for you, for someone new (they told the church it's their
first time): YOUR PASTOR, the name, the title (member_portal_lumen.render_home;
the tile is member_lumen_home.tile). Connect, for everyone: one quiet row by
Directory and News. Its own page, /my/pastor: the picture, YOUR PASTOR, the
name in the serif, the title, the note, and Send a message when member
messages lets this member write to them (/my/messages/to/<id>, the same
rules, member_messaging_rules.direct). Nothing is made up: no bio, no service
times, no phone number.

READS. who(): the church's roles, the senior role's holders, their records
(three reads), kept five minutes per church on each server copy
(member_cache). Home asks only for someone new, after what they told the
church (which Home already reads); Connect and the page ask every time
(kept). The page reads whether this member may message them (member
messages' own reads), only while member messages are on.

CSS (CSS) joins the Lumen sheet (member_lumen_ui.templates), before the type
block; tokens only, so dark mode draws it.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from html import escape
from string import Template
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import member_cache
import sb_clients

logger = logging.getLogger("member_pastor")
router = APIRouter(tags=["member-portal"])

KEY = "pastor"                 # the picture spot, and the settings key's stem
NOTE_MAX = 600
KEEP_SECONDS = 300.0
_KEPT = member_cache.Kept("pastor", KEEP_SECONDS)
DONE = {"note": "Saved. Everyone sees it now."}
ERRORS = {"error": "That didn't save. Please try again.",
          "slow": "That's a lot at once. Please wait a minute.",
          "long": f"That's a little long. Keep it under {NOTE_MAX} characters.",
          "no": "That note can't go in the app. Please change it.",
          "busy": "The note couldn't be checked just now, so nothing was saved. Please try again in a minute."}


def _e(v: Any) -> str:
    return escape(str(v if v is not None else ""), quote=True)


def _q(v: Any) -> str:
    return quote(str(v), safe="")


# ─── who ─────────────────────────────────────────────────────────────


def find(business_id: str) -> Optional[Dict[str, Any]]:
    """The church's pastor: {id, name, title, birthdate, metadata}, {} when no
    one holds the senior role, None when a read failed."""
    import church_follow_up as cfu
    import church_roles as cr
    bid = str(business_id)
    defs = cr.defs(bid)
    if defs is None:
        return None
    titles = {d["key"]: d.get("title") or "" for d in defs if d.get("job") == "senior"}
    # A church still on the first version's key keeps it (church_follow_up's
    # _effective_defs): "pastor", the Lead Pastor.
    if "pastor" not in {d["key"] for d in defs}:
        titles["pastor"] = cr.LEGACY["pastor"]["title"]
    rows = sb_clients.sb_get_as_service(
        f"/church_leader_roles?business_id=eq.{_q(bid)}&role=in.({','.join(_q(k) for k in sorted(titles))})"
        f"&status=eq.active&select=contact_id,role&limit=50")
    if not isinstance(rows, list):
        return None
    ids = sorted({str(r["contact_id"]) for r in rows if r.get("contact_id")})
    if not ids:
        return {}
    people = sb_clients.sb_get_as_service(
        f"/contacts?business_id=eq.{_q(bid)}&id=in.({','.join(_q(i) for i in ids)})&select=id,name,birthdate,metadata")
    if not isinstance(people, list):
        return None
    by = {str(p["id"]): p for p in people if (p.get("name") or "").strip()}
    held = [(by[str(r["contact_id"])], r["role"]) for r in rows if str(r.get("contact_id")) in by]
    if not held:
        return {}
    # The first by name, as church_follow_up's best() picks among the senior role's holders.
    held.sort(key=lambda pr: (cfu._norm(pr[0].get("name") or ""), str(pr[0]["id"])))
    p, role = held[0]
    return {"id": str(p["id"]), "name": cfu._plain(p.get("name") or "").strip(), "title": titles.get(role) or "",
            "birthdate": p.get("birthdate"), "metadata": p.get("metadata") or {}}


def who(biz: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """find(), kept five minutes per church on this server copy. {} for a
    church with no one in the senior role (and for anything that isn't a
    church); None when it couldn't be read (the caller leaves it out).
    Never raises."""
    try:
        import church_follow_up as cfu
        if not biz or not biz.get("id") or not cfu.is_church(biz):
            return {}
        bid = str(biz["id"])
        hit, kept = _KEPT.get(bid)
        if hit:
            return kept
        got = find(bid)
        if got is not None:
            _KEPT.put(bid, got, tag=bid)
        return got
    except Exception:  # noqa: BLE001 — the pastor is never worth a broken page
        logger.warning("pastor: who skipped", exc_info=True)
        return None


def note(biz: Dict[str, Any]) -> str:
    """The pastor's welcome note ('' when none)."""
    cfg = (((biz or {}).get("settings") or {}).get("member_portal") or {})
    got = cfg.get("pastor_note") if isinstance(cfg, dict) else None
    text = got.get("text") if isinstance(got, dict) else None
    return str(text or "").strip()[:NOTE_MAX]


# ─── the picture ─────────────────────────────────────────────────────


def picture(biz: Dict[str, Any], p: Dict[str, Any]) -> Tuple[str, str, str]:
    """(url, look, whose): the church's Pastor spot ("chosen"), else the
    pastor's own profile photo when members may see it ("own"), else
    ("", "", "") for their initials."""
    import member_app_photos as photos
    import member_photos as ph
    got = photos.assigned(biz, KEY)
    if got is not None and got["url"]:
        return got["url"], got["look"], "chosen"
    own = ph.src(p) if ph.shown_to_members(p) else ""
    return (own, "colour", "own") if own else ("", "", "")


def _art(biz: Dict[str, Any], p: Dict[str, Any], cls: str = "") -> str:
    """The pastor's picture for a tile or the page: the photo (the chosen
    one in its look; their own in colour), else their initials."""
    import member_app_ui as ui
    url, look, whose = picture(biz, p)
    if url:
        return ui.photo(url, f"lm-pph {cls}".strip(), look=look if whose == "chosen" else "colour")
    return f'<span class="lm-pini {cls}" aria-hidden="true"><b>{_e(ui.initials(p.get("name")))}</b></span>'


def spot_default(p: Dict[str, Any]) -> Dict[str, str]:
    """What the Pastor spot shows with nothing chosen, for its Change page
    (member_app_pictures.render_spot's `own`): their own photo, or their
    initials, and the words for choosing it."""
    import member_app_ui as ui
    import member_photos as ph
    own = ph.src(p) if ph.shown_to_members(p) else ""
    inner = (f'<img src="{_e(own)}" alt="" loading="lazy" decoding="async">' if own
             else f'<b>{_e(ui.initials(p.get("name")))}</b>')
    return {"preview": f'<span class="pc-prev-def lm-pown" aria-hidden="true">{inner}</span>',
            "swatch": f'<span class="lm-pown" aria-hidden="true">{inner}</span>',
            "title": "Use their own photo" if own else "Use their initials",
            "line": "Their profile photo in the app" if own else "Until they add a profile photo in the app"}


def tile(biz: Dict[str, Any], p: Dict[str, Any], *, href: str, edit: bool = False) -> str:
    """Home's Also for you tile: the picture with the wave badge, YOUR
    PASTOR, the name, the title (member_lumen_home.tile)."""
    import member_lumen_home as lh
    return lh.tile(href, _art(biz, p), "wave", "Your pastor", p.get("name") or "", p.get("title") or "", pin=edit)


def row(biz: Dict[str, Any], p: Dict[str, Any]) -> str:
    """Connect's row: their face, the name, 'Your pastor' and the title."""
    import member_lumen_ui as lm
    face = f'<span class="lm-aic lm-pface">{_art(biz, p)}</span>'
    sub = " · ".join(x for x in ("Your pastor", p.get("title") or "") if x)
    return lm.row("/my/pastor", face, p.get("name") or "", sub, cls="lm-room")


# ─── may this member write to them ───────────────────────────────────


def may_message(biz: Dict[str, Any], me: Dict[str, Any], pastor_id: str) -> bool:
    """Whether Send a message can work: member messages are on at this
    church and its rules let this member start a chat with the pastor
    (member_messaging_rules.direct: both can message, no block, no teen
    and adult). False on any failed read."""
    try:
        import member_messaging_rules as rules
        import member_portal_messaging as mpm
        if not mpm.turned_on(biz) or str(me.get("id")) == str(pastor_id):
            return False
        bid = str(biz["id"])
        folks = mpm.people(bid, [pastor_id, me["id"]])
        links = mpm.guardians(bid, [pastor_id, me["id"]])
        blk = mpm.blocks(bid, str(me["id"]), str(pastor_id))
        if folks is None or links is None or blk is None or str(pastor_id) not in folks:
            return False
        ok, _how = rules.direct(folks.get(str(me["id"]), me), folks[str(pastor_id)], guardians_of=links,
                                blocked=blk, share_group=False)
        return bool(ok)
    except Exception:  # noqa: BLE001
        logger.warning("pastor: may_message skipped", exc_info=True)
        return False


# ─── the page ────────────────────────────────────────────────────────


def _flash(request: Request) -> str:
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


def _paras(text: str) -> str:
    parts = [x.strip() for x in text.replace("\r\n", "\n").split("\n\n") if x.strip()]
    return "".join(f"<p>{_e(x)}</p>" for x in parts)


def render_page(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], p: Dict[str, Any], *,
                edit: bool = False, can_edit: bool = False, write: bool = False) -> str:
    """Meet the pastor: the picture, YOUR PASTOR, the name, the title, the
    note, and Send a message (`write`: may_message). In edit mode (`edit`,
    for someone who may: `can_edit`) the picture carries Change and the note
    is a box with Save; outside it, an editor sees a quiet way in."""
    import member_app_ui as ui
    import member_lumen_ui as lm
    from member_portal import _shell
    church = (biz.get("name") or "").strip() or "your church"
    name = p.get("name") or ""
    text = note(biz)
    edit = edit and can_edit
    url, _look, _whose = picture(biz, p)
    change = (f'<a class="mb-pin" href="/my/pictures/spot?key={KEY}&amp;back=pastor">{ui.icon("camera", 15)}'
              f'<span>Change</span></a>' if edit else "")
    pic = (f'<div class="lm-pp{" has-ph" if url else ""}">{_art(biz, p, "lm-pp-a")}{change}</div>')
    title = f'<p class="lm-pptitle">{_e(p["title"])}</p>' if p.get("title") else ""
    head = (f'<header class="lm-pphead"><p class="lm-eyebrow">Your pastor</p><h1 class="lm-disp">{_e(name)}</h1>'
            f'{title}</header>')
    if edit:
        body_note = (f'<form class="lm-ppform" method="post" action="/my/pastor/note">'
                     f'<label class="lm-pplbl" for="lm-ppnote">A welcome note</label>'
                     f'<textarea id="lm-ppnote" name="note" rows="6" maxlength="{NOTE_MAX}" '
                     f'placeholder="A few words for someone new at {_e(church)}">{_e(text)}</textarea>'
                     f'<p class="lm-ppfine">Everyone who opens this page sees it. Up to {NOTE_MAX} characters.</p>'
                     f'<button class="lm-btn" type="submit">Save</button></form>')
    else:
        body_note = f'<div class="lm-ppnote">{_paras(text)}</div>' if text else ""
    say = (f'<div class="lm-ppact"><a class="lm-btn" href="/my/messages/to/{_e(p["id"])}">Send a message</a></div>'
           if write and not edit else "")
    bar = ""
    if edit:
        bar = (f'<div class="mb-editbar" role="status"><span class="mb-editbar-ic">{ui.icon("camera", 18)}</span>'
               f'<span class="mb-editbar-t"><strong>Changing this page</strong><span>Only you see these buttons.</span></span>'
               f'<a class="mp-go mb-editbar-done" href="/my/pastor">Done</a></div>')
    door = (f'<p class="lm-ppedit"><a href="/my/pastor?edit=pictures">{ui.icon("camera", 15)}'
            f'<span>Change the picture or the note</span></a></p>' if can_edit and not edit else "")
    body = f'{bar}{_flash(request)}<article class="lm-ppage">{pic}{head}{body_note}{say}</article>{door}'
    return _shell(biz, site, "Meet the pastor", body, tab="directory", who=me)


# ─── the note ────────────────────────────────────────────────────────


def clean(raw: Any) -> str:
    """The note as kept: plain text, at most two line breaks in a row,
    trimmed."""
    import re
    text = str(raw or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def save_note(business_id: str, text: str, *, by: str) -> bool:
    """Write the note into this church's settings (read right before the
    write, so nothing changed meanwhile is undone). '' takes it away."""
    fresh = sb_clients.sb_get_as_service(f"/businesses?id=eq.{_q(business_id)}&select=settings&limit=1")
    if not isinstance(fresh, list) or not fresh:
        return False
    settings = dict(fresh[0].get("settings") or {})
    cfg = dict(settings.get("member_portal") or {}) if isinstance(settings.get("member_portal"), dict) else {}
    if text:
        cfg["pastor_note"] = {"text": text, "at": datetime.now(timezone.utc).isoformat(), "by": by}
    else:
        cfg.pop("pastor_note", None)
    settings["member_portal"] = cfg
    return bool(sb_clients.sb_patch_as_service(f"/businesses?id=eq.{_q(business_id)}", {"settings": settings}))


def _back(**q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    qs = "&".join(f"{k}={v}" for k, v in q.items() if v)
    return RedirectResponse("/my/pastor?edit=pictures" + (f"&{qs}" if qs else ""), status_code=303,
                            headers=_SECURE_HEADERS)


@router.post("/my/pastor/note", include_in_schema=False)
async def save_note_route(request: Request):
    """Save the pastor's welcome note (form: note). The picture route's
    checks: this church's address, the same site, a session that may change
    the app's pictures, the per-person limit; and the new look showing to
    this session (member_lumen), as the page it's written on does."""
    import member_app_pictures as mapic
    import member_lumen
    import member_portal as mp
    import rate_limit
    church = await mp._church_or_404(request)
    biz = church["business"]
    sess = await asyncio.to_thread(mp._session_for, request, church)
    by = mapic.may_edit(sess, biz)
    if not by:
        return RedirectResponse("/my", status_code=303, headers=mp._SECURE_HEADERS)
    # Meet the pastor is the new look's: where it doesn't show, there's no note to write.
    if not await member_lumen.decide(request, {"business": biz, "session": sess}):
        return RedirectResponse("/my", status_code=303, headers=mp._SECURE_HEADERS)
    try:
        form = await request.form()
    except Exception:  # noqa: BLE001
        return _back(err="error")
    raw = str(form.get("note") or "")
    if len(raw) > NOTE_MAX + 200:
        return _back(err="long")
    text = clean(raw)
    if len(text) > NOTE_MAX:
        return _back(err="long")
    if not rate_limit.allow_strict("member_action", f"{biz['id']}|pastor_note|{by}"):
        return _back(err="slow")
    if text and not by.startswith("owner:"):
        import msg_screen
        try:
            verdict = await msg_screen.screen(str(biz["id"]), text)
        except msg_screen.ScreenUnavailable:
            return _back(err="busy")
        if verdict == "harm":
            return _back(err="no")
    ok = await asyncio.to_thread(save_note, str(biz["id"]), text, by=by)
    if ok:
        # This copy reads the church (its settings) fresh now; the others within a minute.
        member_cache.forget_church(biz["id"])
        logger.info("member app pastor note saved", extra={"business_id": biz["id"], "by": by})
    return _back(**({"done": "note"} if ok else {"err": "error"}))


CSS = Template("""
/* Meet the pastor (member_pastor): Home's tile picture, Connect's face, the page */
.lm .lm-pini{display:grid;place-items:center;background:var(--lm-tint-12);color:var(--acc);}
.lm .lm-pini b{font-family:var(--mb-serif);font-weight:var(--lm-dw,400);font-size:40px;line-height:1;letter-spacing:-.02em;}
.lm .lm-t4a .mb-ph.lm-pph img{object-position:50% 25%;}
.lm .lm-pface{overflow:hidden;background:var(--lm-tint-12);}
.lm .lm-pface>*{width:100%;height:100%;border-radius:50%;}
.lm .lm-pface .mb-ph img{width:100%;height:100%;object-fit:cover;object-position:50% 25%;}
.lm .lm-pface .lm-pini b{font-size:15px;font-family:var(--mb-ui);font-weight:700;letter-spacing:0;}
.lm .lm-ppage{margin-top:8px;}
.lm .lm-pp{position:relative;width:100%;aspect-ratio:4/3;max-height:360px;border-radius:20px;overflow:hidden;background:var(--s2);
  box-shadow:0 0 0 1px var(--lm-line);}
.lm .lm-pp>.lm-pp-a{position:absolute;inset:0;width:100%;height:100%;border-radius:0;aspect-ratio:auto;}
.lm .lm-pp .mb-ph img{width:100%;height:100%;object-fit:cover;object-position:50% 22%;}
.lm .lm-pp:not(.has-ph){width:112px;height:112px;aspect-ratio:auto;border-radius:50%;box-shadow:none;}
.lm .lm-pp:not(.has-ph) .lm-pini b{font-size:44px;}
.lm .lm-pp .mb-pin{top:auto;bottom:10px;right:10px;}
.lm .lm-pp:not(.has-ph) .mb-pin{bottom:-6px;right:-30px;}
.lm .lm-pphead{margin-top:22px;}
.lm .lm-pphead .lm-disp{margin-top:8px;font-size:38px;line-height:1.05;}
.lm .lm-pptitle{margin:8px 0 0;font:500 15px/1.4 var(--mb-ui);color:var(--fg2);}
.lm .lm-ppnote{margin-top:22px;padding-top:20px;border-top:1px solid var(--lm-line);}
.lm .lm-ppnote p{margin:0 0 14px;font-family:var(--lm-read,var(--mb-serif));font-size:18px;line-height:1.6;color:var(--fg);
  white-space:pre-line;overflow-wrap:anywhere;}
.lm .lm-ppnote p:last-child{margin-bottom:0;}
.lm .lm-ppact{margin-top:24px;}
.lm .lm-ppact .lm-btn{display:inline-flex;align-items:center;text-decoration:none;}
.lm .lm-ppform{display:flex;flex-direction:column;gap:10px;margin-top:22px;padding-top:20px;border-top:1px solid var(--lm-line);}
.lm .lm-pplbl{font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg2);}
.lm .lm-ppform textarea{width:100%;min-height:150px;padding:14px;border:0;border-radius:16px;background:var(--s1);color:var(--fg);
  box-shadow:inset 0 0 0 1px var(--lm-line);font:400 16px/1.5 var(--mb-ui);resize:vertical;}
.lm .lm-ppform textarea:focus{outline:none;box-shadow:inset 0 0 0 1.5px var(--acc-fill);}
.lm .lm-ppform .lm-btn{align-self:flex-start;}
.lm .lm-ppfine{margin:0;font:500 12.5px/1.4 var(--mb-ui);color:var(--fg3);}
.lm .lm-ppedit{margin:28px 0 0;}
.lm .lm-ppedit a{display:inline-flex;align-items:center;gap:8px;font:600 13.5px/1 var(--mb-ui);color:var(--fg2);text-decoration:none;}
.lm .lm-ppedit a:focus-visible{outline:2px solid var(--acc);outline-offset:3px;border-radius:8px;}
/* the Pastor spot's Change page: their own photo or initials as its default */
.lm .lm-pown{position:absolute;inset:0;display:grid;place-items:center;overflow:hidden;background:var(--lm-tint-12);color:var(--acc);}
.lm .pc-prev.is-default>.lm-pown{display:grid;}
.lm .lm-pown img{display:block;width:100%;height:100%;object-fit:cover;object-position:50% 25%;}
.lm .lm-pown b{font-family:var(--mb-serif);font-weight:var(--lm-dw,400);font-size:48px;line-height:1;}
.lm .pc-def-art .lm-pown b{font-size:18px;}
""")
