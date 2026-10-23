"""
member_portal_news.py — the church's news in the member app.

From the approved canvas "Church News & Celebrations" (Hfrz3Y174kbDmJv1G4puVq),
boards 1–3, built to look as drawn:

  Home      "From the church": the pinned (or newest) post as a card, then
            the next few as rows, with "All news" (render_home places it
            under the quick ways in). The bell at the top right opens News,
            with how many posts are new.
  /my/news  "What's happening.": filters (All, Announcements, Celebrations,
            Photos, Events), each post as a card in the church colour when
            pinned, with what it carries (an event, a sermon, photos), its
            reactions and its comment count.
  /my/news/<id>  one post, every reaction, and the comments with replies.
            A comment shows "Checking it first…" while it's checked
            (msg_screen, church_news.comment); the box at the foot says so.

POST, each acting as the signed-in member (same-origin form, a live
session, the per-person limit, a redirect back with a short code):
  /my/news/react           Love, Praying, Amen or Celebrate, on or off
  /my/news/comment         a comment or a reply
  /my/news/comment/love    Love on a comment
  /my/news/comment/report  report a comment to the safety officers
  /my/news/comment/remove  its writer, or whoever posted the post
The owner's preview reads everything and saves nothing.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

import church_news as cn

logger = logging.getLogger("member_portal_news")
router = APIRouter(tags=["member-portal"])

DONE = {
    "commented": "Posted.",
    "comment_held": "Thanks. A safety officer looks at this one before it shows.",
    "care": "You're not alone. If you're thinking about hurting yourself, call or text 988 (the Suicide & Crisis "
            "Lifeline) any time. Your pastor has been told so they can reach out.",
    "reported": "Reported. The safety officers will look. They won't say who told them.",
    "comment_down": "Your comment is down.",
}
ERRORS = {
    "error": "That didn't go through. Please try again.",
    "preview": "This is a preview, so nothing saves. Members can react and comment.",
    "slow": "That was a lot at once. Wait a moment and try again.",
    "news_gone": "That post isn't there any more.",
    "comment_gone": "That comment isn't there any more.",
    "comment_empty": "Write your comment first.",
    "comment_busy": "We couldn't check your comment just now, so it wasn't posted. Please try again.",
    "comments_closed": "Comments aren't open at your church yet.",
    "comments_off": "Comments are off for this post.",
    "not_yours": "Only the person who wrote it, or whoever posted, can take it down.",
}
REACT_LABEL = {"love": "Love", "pray": "Praying", "amen": "Amen", "cheer": "Celebrate"}
# Which reactions a card in the feed offers, by what the post is (the post
# itself offers all four).
CARD_RX = {"message": ("amen", "pray"), "celebration": ("cheer", "love"), "milestone": ("cheer", "love"),
           "good_news": ("cheer", "love"), "praise": ("amen", "love")}
CARD_RX_DEFAULT = ("love", "amen")
_BACK_RE = re.compile(r"^/my(/news(/[0-9a-fA-F-]{36})?)?$")

# The canvas's sheet (news.css) on the member app's tokens: the church colour
# is --acc-fill / --acc / --acc-deep; gold, teal, violet and coral are the
# family (member_app_ui.FAMILY). nw-* names.
NEWS_CSS = """
.nw-head{margin:4px 0 0;}
.nw-eb{margin:0;font-size:12.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--acc);}
.nw-lt{margin:2px 0 0;font-size:34px;font-weight:720;letter-spacing:-.035em;line-height:1.05;}
.nw-lt em{font-family:var(--mb-serif);font-style:italic;font-weight:500;letter-spacing:-.02em;color:var(--acc);}
.nw-filter{display:flex;gap:8px;overflow-x:auto;margin:14px calc(var(--g) * -1) 0;padding:0 var(--g) 2px;scrollbar-width:none;}
.nw-filter::-webkit-scrollbar{display:none;}
.nw-fp{flex:none;display:inline-flex;align-items:center;min-height:36px;padding:0 14px;border-radius:999px;background:var(--s1);
  font-size:14px;font-weight:600;color:var(--fg2);text-decoration:none;}
.nw-fp[aria-current]{background:var(--fg);color:var(--bg);}
.nw-list{display:flex;flex-direction:column;gap:12px;margin-top:16px;}
.nw-post{border-radius:var(--r-lg);background:var(--s1);padding:16px;display:flex;flex-direction:column;gap:12px;scroll-margin-top:80px;}
.nw-post.church{background:var(--acc-deep);}
.nw-post.gold{background:var(--gold-deep);}
.nw-ph{display:flex;align-items:center;gap:10px;}
.nw-ph .nw-t{flex:1;min-width:0;display:flex;flex-direction:column;}
.nw-ph .nw-t b{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:14.5px;font-weight:650;}
.nw-ph .nw-t small{font-size:12.5px;color:var(--fg2);}
.nw-av{width:32px;height:32px;border-radius:50%;flex:none;display:grid;place-items:center;overflow:hidden;font-size:12px;font-weight:650;
  background:var(--acc-deep);color:var(--acc);}
.nw-av img{width:100%;height:100%;object-fit:cover;display:block;}
.nw-av.church{background:var(--acc-fill);color:var(--on-acc);font-weight:750;}
.nw-av.s{width:32px;height:32px;}
.nw-tag{display:inline-flex;align-items:center;height:19px;padding:0 7px;border-radius:6px;font-size:11px;font-weight:700;letter-spacing:.02em;
  background:var(--acc-deep);color:var(--acc);}
.nw-post.church .nw-tag.pastor{background:transparent;padding:0 2px;}
.nw-tag.office{background:var(--violet-deep);color:var(--violet-ink);}
.nw-tag.min{background:var(--coral-deep);color:var(--coral-ink);}
.nw-pin{color:var(--acc);flex:none;}
.nw-kind{display:inline-flex;align-items:center;gap:5px;font-size:11.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--gold-ink);}
.nw-post h3{margin:0;font-size:19px;font-weight:700;letter-spacing:-.022em;line-height:1.2;}
.nw-post p.nw-body{margin:0;font-size:15px;line-height:1.48;white-space:pre-line;overflow-wrap:anywhere;}
.nw-att{display:flex;align-items:center;gap:12px;padding:10px;border-radius:14px;background:var(--bg);color:inherit;text-decoration:none;}
.nw-att .nw-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:1px;}
.nw-att .nw-t b{font-size:15px;font-weight:640;}
.nw-att .nw-t small{font-size:12.5px;color:var(--fg2);}
.nw-att>.mb-ic:last-child{color:var(--fg3);}
.nw-date{width:52px;padding:7px 0 8px;border-radius:13px;background:var(--coral);color:var(--on-coral);text-align:center;line-height:1;
  display:flex;flex-direction:column;align-items:center;flex:none;}
.nw-date .m{font-size:10.5px;font-weight:750;letter-spacing:.08em;}
.nw-date .d{font-size:22px;font-weight:750;letter-spacing:-.03em;margin-top:3px;}
.nw-disc{width:42px;height:42px;border-radius:13px;flex:none;display:grid;place-items:center;background:var(--violet);color:var(--on-violet);}
.nw-pics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:4px;border-radius:16px;overflow:hidden;}
.nw-pics a{position:relative;display:block;aspect-ratio:1/1;background:var(--s2);}
.nw-pics img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;display:block;}
.nw-pics .nw-more{position:absolute;inset:0;display:grid;place-items:center;background:rgba(0,0,0,.45);color:#fff;font-size:20px;font-weight:700;}
.nw-pics.one{grid-template-columns:minmax(0,1fr);}
.nw-pics.one a{aspect-ratio:16/10;}
.nw-rxbar{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;}
.nw-rxs{display:flex;gap:6px;flex-wrap:wrap;}
.nw-rxs form{margin:0;}
.nw-rx{display:inline-flex;align-items:center;gap:5px;height:34px;padding:0 11px;border-radius:999px;border:0;background:var(--s2);
  font:inherit;font-size:13px;font-weight:650;color:var(--fg2);cursor:pointer;}
.nw-rx .mb-ic{width:15px;height:15px;}
.nw-post.church .nw-rx,.nw-post.gold .nw-rx{background:rgba(127,127,127,.18);color:var(--fg);}
.nw-rx[aria-pressed=true],.nw-post .nw-rx[aria-pressed=true]{background:var(--acc-fill);color:var(--on-acc);}
.nw-cl{display:inline-flex;align-items:center;gap:6px;min-height:34px;font-size:13.5px;font-weight:600;color:var(--fg2);text-decoration:none;}
.nw-cl .mb-ic{width:16px;height:16px;}
.nw-off{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;color:var(--fg3);}
.nw-off .mb-ic{width:14px;height:14px;}
.nw-foot{display:flex;gap:10px;align-items:flex-start;font-size:13px;color:var(--fg3);line-height:1.45;margin:18px 0 0;}
.nw-foot .mb-ic{width:16px;height:16px;margin-top:1px;flex:none;}
.nw-empty{border-radius:var(--r-md);background:var(--s1);padding:18px 16px;color:var(--fg2);font-size:14.5px;}
.nw-rows{border-radius:var(--r-md);background:var(--s1);margin-top:12px;overflow:hidden;}
.nw-row{display:flex;align-items:center;gap:12px;padding:12px 14px;position:relative;color:inherit;text-decoration:none;}
.nw-row+.nw-row::before{content:"";position:absolute;top:0;left:14px;right:0;height:.5px;background:var(--line);}
.nw-thumb{width:58px;height:58px;border-radius:13px;overflow:hidden;flex:none;display:grid;place-items:center;background:var(--s2);}
.nw-thumb img{width:100%;height:100%;object-fit:cover;display:block;}
.nw-thumb.violet{background:var(--violet-deep);color:var(--violet-ink);}
.nw-thumb.gold{background:var(--gold-deep);color:var(--gold-ink);}
.nw-thumb.coral{background:var(--coral-deep);color:var(--coral-ink);}
.nw-thumb.brand{background:var(--acc-deep);color:var(--acc);}
.nw-row .nw-t{flex:1;min-width:0;display:flex;flex-direction:column;gap:2px;}
.nw-row .nw-t b{font-size:15.5px;font-weight:620;letter-spacing:-.012em;line-height:1.25;}
.nw-row .nw-t span{font-size:13px;color:var(--fg2);}
.nw-row>.mb-ic:last-child{color:var(--fg3);}
.nw-who{display:flex;align-items:center;gap:8px;margin:12px 0 0;font-size:13.5px;color:var(--fg2);}
.nw-faces{display:flex;}
.nw-faces .nw-av{width:26px;height:26px;font-size:10.5px;margin-left:-8px;box-shadow:0 0 0 2px var(--bg);}
.nw-faces .nw-av:first-child{margin-left:0;}
.nw-ch{display:flex;align-items:baseline;justify-content:space-between;margin:26px 0 14px;}
.nw-ch h2{margin:0;font-size:19px;font-weight:700;letter-spacing:-.02em;}
.nw-ch span{font-size:13.5px;color:var(--fg3);}
.nw-cmts{display:flex;flex-direction:column;gap:14px;}
.nw-cm{display:flex;gap:10px;align-items:flex-start;scroll-margin-top:90px;}
.nw-cm.rep{margin-left:46px;}
.nw-cm-col{flex:1;min-width:0;display:flex;flex-direction:column;gap:3px;}
.nw-cm-b{align-self:flex-start;max-width:100%;padding:9px 13px 10px;border-radius:18px;background:var(--s1);font-size:15px;line-height:1.4;
  overflow-wrap:anywhere;white-space:pre-line;}
.nw-cm-who{display:flex;align-items:center;gap:6px;font-size:13px;font-weight:650;margin-bottom:2px;white-space:normal;}
.nw-cm.pending .nw-cm-b,.nw-cm.held .nw-cm-b{opacity:.65;}
.nw-cm-meta{display:flex;align-items:center;gap:14px;padding:0 6px;font-size:12.5px;color:var(--fg3);flex-wrap:wrap;}
.nw-cm-meta form{margin:0;}
.nw-cm-meta button,.nw-cm-meta a{border:0;background:none;padding:0;font:inherit;font-size:12.5px;font-weight:650;color:var(--fg2);min-height:28px;
  cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;}
.nw-cm-meta button[aria-pressed=true]{color:var(--acc);}
.nw-cm-meta .flag{color:var(--fg3);}
.nw-checking{display:inline-flex;align-items:center;gap:6px;font-size:12px;color:var(--fg3);padding:0 6px;}
.nw-checking .mb-ic{width:13px;height:13px;}
.nw-reported{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;font-weight:600;color:var(--acc);padding:0 6px;}
.nw-comp{position:sticky;bottom:0;z-index:5;margin:24px calc(var(--g) * -1) 0;padding:8px 10px calc(14px + env(safe-area-inset-bottom,0px));
  background:var(--bar);-webkit-backdrop-filter:blur(22px) saturate(1.6);backdrop-filter:blur(22px) saturate(1.6);box-shadow:0 -.5px 0 var(--hair);
  display:flex;flex-direction:column;gap:8px;}
.nw-comp form{margin:0;display:flex;flex-direction:column;gap:8px;}
.nw-comp-row{display:flex;align-items:flex-end;gap:8px;}
.nw-comp-in{flex:1;min-width:0;min-height:44px;display:flex;align-items:center;border-radius:22px;background:var(--s1);padding:0 14px;
  box-shadow:inset 0 0 0 1px var(--line);}
.nw-comp-in textarea{flex:1;min-width:0;background:transparent;border:0;outline:none;font:inherit;font-size:16px;color:var(--fg);resize:none;
  min-height:44px;max-height:140px;padding:11px 0;line-height:1.35;}
.nw-comp-in textarea::placeholder{color:var(--fg3);}
.nw-send{width:44px;height:44px;border-radius:50%;border:0;display:grid;place-items:center;background:var(--acc-fill);color:var(--on-acc);flex:none;cursor:pointer;}
.nw-send[disabled]{opacity:.6;}
.nw-safe{display:flex;align-items:center;gap:6px;justify-content:center;font-size:12px;color:var(--fg3);margin:0;}
.nw-safe .mb-ic{width:13px;height:13px;}
.nw-replying{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 6px;font-size:13px;color:var(--fg2);}
.nw-replying a{font-size:13px;font-weight:650;color:var(--acc);text-decoration:none;min-height:32px;display:inline-flex;align-items:center;}
.nw-me{width:32px;height:32px;border-radius:50%;flex:none;display:grid;place-items:center;overflow:hidden;font-size:12px;font-weight:650;
  background:var(--acc-fill);color:var(--on-acc);align-self:center;}
.nw-me img{width:100%;height:100%;object-fit:cover;}
.nw-closed{display:flex;gap:10px;align-items:flex-start;margin:20px 0 0;padding:14px;border-radius:var(--r-md);background:var(--s1);
  font-size:13.5px;color:var(--fg2);line-height:1.45;}
.nw-closed .mb-ic{flex:none;margin-top:1px;color:var(--acc);}
.mb-bell{position:relative;}
"""

_EXTRA = {
    "pin": ('<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76'
            'a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>'),
    "pray": ('<path d="M11 14h2a2 2 0 1 0 0-4h-3c-.6 0-1.1.2-1.4.6L3 16"/><path d="m7 20 1.6-1.4c.3-.4.8-.6 1.4-.6h4'
             'c1.1 0 2.1-.4 2.8-1.2l4.6-4.4a2 2 0 0 0-2.75-2.91l-4.2 3.9"/><path d="m2 15 6 6"/><path d="M19.5 8.5'
             'c.7-.7 1.5-1.6 1.5-2.7A2.73 2.73 0 0 0 16 4a2.78 2.78 0 0 0-5 1.8c0 1.2.8 2 1.5 2.8L16 12Z"/>'),
    "cheer": ('<path d="M5.8 11.3 2 22l10.7-3.79"/><path d="M11 13c1.93 1.93 2.83 4.17 2 5-.83.83-3.07-.07-5-2-1.93-1.93-2.83-4.17-2-5'
              ' .83-.83 3.07.07 5 2Z"/><path d="m22 2-2.24.75a2.9 2.9 0 0 0-1.96 3.12c.1.86-.57 1.63-1.45 1.63h-.38c-.86 0-1.6.6'
              '-1.76 1.44L14 10"/><path d="M4 3h.01M22 8h.01M15 2h.01M22 20h.01"/>'),
    "comment": '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "shield": ('<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72'
               'a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>'),
    "flag": '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><path d="M4 22v-7"/>',
    "plane": '<path d="m3 3 3 9-3 9 19-9Z"/><path d="M6 12h16"/>',
    "megaphone": '<path d="m3 11 18-5v12L3 14v-3z"/><path d="M11.6 16.8a3 3 0 1 1-5.8-1.6"/>',
    "award": ('<path d="m15.477 12.89 1.515 8.526a.5.5 0 0 1-.81.47l-3.58-2.687a1 1 0 0 0-1.197 0l-3.586 2.686a.5.5 0 0 1'
              '-.81-.469l1.514-8.526"/><circle cx="12" cy="8" r="6"/>'),
    "tv": '<rect x="2.5" y="4" width="19" height="13" rx="3"/><path d="m10.5 8.3 4 2.2-4 2.2z"/><path d="M8 21h8"/>',
    "playtri": '<path d="m7 4 13 8-13 8z"/>',
    "heart": ('<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5'
              'c0 2.3 1.5 4.05 3 5.5l7 7Z"/>'),
}


def _ic(name: str, size: int = 18) -> str:
    import member_app_ui as ui
    if name in _EXTRA:
        return (f'<svg class="mb-ic" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
                f'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{_EXTRA[name]}</svg>')
    return ui.icon(name, size)


def _e(v: Any) -> str:
    from member_portal import _e as esc
    return esc(v)


def _flash(request: Request) -> str:
    done = DONE.get(request.query_params.get("done") or "")
    err = ERRORS.get(request.query_params.get("err") or "")
    if err:
        return f'<p class="mp-err mp-flash" role="alert">{_e(err)}</p>'
    if done:
        return f'<p class="mp-ok mp-flash" role="status">{_e(done)}</p>'
    return ""


# ─── words ───────────────────────────────────────────────────────────


def _local(biz: Dict[str, Any], ts: Any) -> Optional[datetime]:
    import group_gatherings as gg
    t = cn._ts(ts)
    if t is None:
        return None
    tz = gg.zone(biz)
    return t.astimezone(tz) if tz is not None else t


def when_label(biz: Dict[str, Any], ts: Any, now: Optional[datetime] = None) -> str:
    """'Just now', '20m', '3h', 'Monday at 9:14 AM', 'Oct 20' — on the church's clock."""
    t = _local(biz, ts)
    if t is None:
        return ""
    now = now or datetime.now(timezone.utc)
    mins = int((now - t).total_seconds() // 60)
    if mins < 2:
        return "Just now"
    if mins < 60:
        return f"{mins}m"
    if mins < 60 * 12:
        return f"{mins // 60}h"
    local_now = now.astimezone(t.tzinfo) if t.tzinfo else now
    days = (local_now.date() - t.date()).days
    clock = t.strftime("%I:%M %p").lstrip("0")
    if days == 0:
        return f"Today at {clock}"
    if days == 1:
        return f"Yesterday at {clock}"
    if days < 7:
        return f"{t.strftime('%A')} at {clock}"
    return f"{t.strftime('%b')} {t.day}"


def _person_name(person: Dict[str, Any]) -> str:
    import member_portal_groups as mpg
    return mpg.display_name(person, "full")


def _face(person: Dict[str, Any], cls: str = "nw-av") -> str:
    import member_photos as ph
    shown = _person_name(person) if person.get("name") else ""
    return ph.avatar({**person, "name": shown}, show=ph.shown_to_members(person), cls=cls)


def _author(biz: Dict[str, Any], p: Dict[str, Any]) -> Tuple[str, str]:
    """(face, name with its tag) — a member who posted, or the office."""
    import member_app_ui as ui
    a = p.get("author") or {}
    if a:
        tag = ""
        if p.get("pastor"):
            tag = '<span class="nw-tag pastor">Pastor</span>'
        elif p.get("group_name"):
            tag = f'<span class="nw-tag min">{_e(p["group_name"])}</span>'
        return _face(a), f'{_e(_person_name(a))} {tag}'.strip()
    church = (biz.get("name") or "").strip() or "Your church"
    label = (p.get("author_label") or "").strip()
    if label and label != church:
        return (f'<span class="nw-av" aria-hidden="true" style="background:var(--violet-deep);color:var(--violet-ink)">'
                f'{_e(ui.initials(label))}</span>', f'{_e(label)} <span class="nw-tag office">Office</span>')
    return f'<span class="nw-av church" aria-hidden="true">{_e(ui.initials(church))}</span>', _e(church)


def _meta(biz: Dict[str, Any], p: Dict[str, Any]) -> str:
    bits = [when_label(biz, cn.when_of(p))]
    if p.get("pinned"):
        bits.append("pinned")
    elif p.get("group_id"):
        bits.append(f"for {p.get('group_name') or 'your group'}")
    else:
        bits.append("whole church")
    return " · ".join(b for b in bits if b)


def _occasions(occ: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    return {str(o.get("entry_id")): o for o in (occ or []) if o.get("entry_id")}


def _attachments(p: Dict[str, Any], occ: Dict[str, Dict[str, Any]]) -> str:
    out = []
    att = p.get("attach") or {}
    o = occ.get(str(att.get("event") or ""))
    if o:
        try:
            d = date.fromisoformat(str(o.get("date"))[:10])
            box = f'<span class="nw-date" aria-hidden="true"><span class="m">{d.strftime("%b").upper()}</span><span class="d">{d.day}</span></span>'
        except ValueError:
            box = f'<span class="nw-disc" aria-hidden="true">{_ic("calendar", 18)}</span>'
        going = int(o.get("attending") or 0)
        bits = [o.get("location") or "", f"{going} coming" if going else "", "you're coming" if (o.get("mine") or {}).get("status") == "yes" else ""]
        sub = " · ".join(_e(b) for b in bits if b)
        out.append(f'<a class="nw-att" href="/my/events#mp-occ-{_e(o["entry_id"])}">{box}<span class="nw-t"><b>{_e(o.get("title"))}</b>'
                   f'<small>{_e(o.get("date_label") or "")}{(" · " + sub) if sub else ""}</small></span>{_ic("chevron", 18)}</a>')
    s = p.get("sermon")
    if s:
        bits = [s.get("speaker") or "", s.get("scripture") or ""]
        out.append(f'<a class="nw-att" href="/my/sermons/{_e(s["id"])}"><span class="nw-disc" aria-hidden="true">{_ic("playtri", 18)}</span>'
                   f'<span class="nw-t"><b>{_e(s.get("title"))}</b><small>{" · ".join(_e(b) for b in bits if b)}</small></span>'
                   f'{_ic("chevron", 18)}</a>')
    photos = [u for u in att.get("photos") or [] if isinstance(u, str)]
    if photos:
        shown = photos[:2]
        more = len(photos) - len(shown)
        cells = []
        for i, u in enumerate(shown):
            over = f'<span class="nw-more">+{more}</span>' if more and i == len(shown) - 1 else ""
            cells.append(f'<a href="{_e(u)}" target="_blank" rel="noopener"><img src="{_e(u)}" alt="" loading="lazy">{over}</a>')
        out.append(f'<div class="nw-pics{" one" if len(shown) == 1 else ""}">{"".join(cells)}</div>')
    return "".join(out)


def _rx_button(p: Dict[str, Any], kind: str, back: str) -> str:
    on = kind in (p.get("my_rx") or [])
    n = int((p.get("rx") or {}).get(kind) or 0)
    icon = {"love": _ic("heart", 15), "pray": _ic("pray", 15), "cheer": _ic("cheer", 15)}.get(kind, "")
    word = {"amen": "Amen", "cheer": "Celebrate"}.get(kind, "")
    count = f'<span data-n="{n - (1 if on else 0)}">{n if n else ""}</span>' if kind in ("love", "pray") else \
        f'<span data-n="{n - (1 if on else 0)}" data-word="{word}">{word}{(" " + str(n)) if n else ""}</span>'
    return (f'<form method="post" action="/my/news/react" class="nw-rxf"><input type="hidden" name="id" value="{_e(p["id"])}">'
            f'<input type="hidden" name="kind" value="{kind}"><input type="hidden" name="back" value="{_e(back)}">'
            f'<button class="nw-rx" type="submit" aria-pressed="{"true" if on else "false"}" aria-label="{REACT_LABEL[kind]}">'
            f'{icon}{count}</button></form>')


def _comment_link(p: Dict[str, Any], open_: bool) -> str:
    if p.get("comments") == "off":
        return f'<span class="nw-off">{_ic("lock", 14)}<span>Comments are off for this post</span></span>'
    if p.get("comments") == "prayers":
        return f'<span class="nw-off">{_ic("pray", 14)}<span>Tap Praying to let them know</span></span>'
    n = int(p.get("comment_n") or 0)
    if not open_ and not n:
        return ""
    label = f"{n} comment{'' if n == 1 else 's'}" if n else "Comment"
    return f'<a class="nw-cl" href="/my/news/{_e(p["id"])}#comments">{_ic("comment", 16)}<span>{label}</span></a>'


def card(biz: Dict[str, Any], p: Dict[str, Any], occ: Dict[str, Dict[str, Any]], *, back: str, open_: bool,
         full: bool = False) -> str:
    """One post. In the feed it offers two reactions that fit it; on its own
    page, all four."""
    face, who = _author(biz, p)
    pin = f'<span class="nw-pin">{_ic("pin", 18)}</span>' if p.get("pinned") else ""
    cls = "nw-post church" if p.get("pinned") else "nw-post"
    if p.get("kind") in ("celebration", "milestone", "good_news") and not p.get("pinned"):
        cls = "nw-post gold" if p.get("kind") == "celebration" else "nw-post"
    title = f'<h3>{_e(p["title"])}</h3>' if p.get("title") else ""
    body = f'<p class="nw-body">{_e(p["body"])}</p>' if p.get("body") else ""
    kinds = cn.REACTIONS if full else CARD_RX.get(p.get("kind") or "", CARD_RX_DEFAULT)
    if p.get("comments") == "prayers" and "pray" not in kinds:
        kinds = ("pray",) + tuple(k for k in kinds if k != "pray")[:1]
    rxs = "".join(_rx_button(p, k, back) for k in kinds)
    link = "" if full else _comment_link(p, open_)
    return (f'<article class="{cls}" id="p-{_e(p["id"])}" aria-label="{_e(p.get("title") or "A post")}">'
            f'<div class="nw-ph">{face}<span class="nw-t"><b>{who}</b><small>{_e(_meta(biz, p))}</small></span>{pin}</div>'
            f'{title}{body}{_attachments(p, occ)}'
            f'<div class="nw-rxbar"><div class="nw-rxs" role="group" aria-label="React">{rxs}</div>{link}</div></article>')


# The reaction and Love buttons answer at once; the page doesn't jump.
RX_JS = """<script>(function(){
document.addEventListener('submit',function(ev){
 var f=ev.target;if(!f||!f.matches||!f.matches('form.nw-rxf,form.nw-lovef'))return;
 ev.preventDefault();var b=f.querySelector('button');if(!b||b.disabled)return;
 var on=b.getAttribute('aria-pressed')!=='true';b.setAttribute('aria-pressed',on?'true':'false');
 var s=b.querySelector('[data-n]');if(s){var n=parseInt(s.getAttribute('data-n'),10)+(on?1:0);var w=s.getAttribute('data-word');
  if(s.hasAttribute('data-love')){s.textContent=n?('Love · '+n):'Love';}else if(w){s.textContent=n?(w+' '+n):w;}else{s.textContent=n?String(n):'';}}
 b.disabled=true;fetch(f.action,{method:'POST',body:new FormData(f),credentials:'same-origin',redirect:'manual'})
  .catch(function(){}).then(function(){b.disabled=false;});
});
})();</script>"""

# A comment shows "Checking it first…" while it's checked.
COMMENT_JS = """<script>(function(){
var f=document.getElementById('nw-say');if(!f)return;var t=f.querySelector('textarea');
t.addEventListener('input',function(){t.style.height='auto';t.style.height=Math.min(t.scrollHeight,140)+'px';});
f.addEventListener('submit',function(ev){var v=(t.value||'').trim();if(!v){ev.preventDefault();return;}
 var list=document.getElementById('nw-cmts');var b=f.querySelector('button[type=submit]');if(b){b.disabled=true;}
 if(list){var d=document.createElement('div');d.className='nw-cm pending';
  var me=document.querySelector('.nw-comp .nw-me');var av=me?me.cloneNode(true):document.createElement('span');av.className='nw-av s';
  var col=document.createElement('div');col.className='nw-cm-col';var bub=document.createElement('div');bub.className='nw-cm-b';
  var who=document.createElement('span');who.className='nw-cm-who';who.textContent='You';var tx=document.createElement('span');tx.textContent=v;
  bub.appendChild(who);bub.appendChild(tx);var ck=document.createElement('span');ck.className='nw-checking';ck.textContent='Checking it first…';
  col.appendChild(bub);col.appendChild(ck);d.appendChild(av);d.appendChild(col);list.appendChild(d);
  var empty=document.getElementById('nw-cm-empty');if(empty){empty.remove();}d.scrollIntoView({block:'center'});}
});
})();</script>"""


# ─── Home ────────────────────────────────────────────────────────────


def _row(biz: Dict[str, Any], p: Dict[str, Any]) -> str:
    att = p.get("attach") or {}
    photos = [u for u in att.get("photos") or [] if isinstance(u, str)]
    if photos:
        thumb = f'<span class="nw-thumb"><img src="{_e(photos[0])}" alt="" loading="lazy"></span>'
    elif p.get("sermon") or p.get("kind") == "message":
        thumb = f'<span class="nw-thumb violet">{_ic("tv", 22)}</span>'
    elif att.get("event") or p.get("kind") == "event":
        thumb = f'<span class="nw-thumb coral">{_ic("calendar", 22)}</span>'
    elif p.get("kind") in ("celebration", "milestone", "good_news"):
        thumb = f'<span class="nw-thumb gold">{_ic("award", 22)}</span>'
    else:
        thumb = f'<span class="nw-thumb gold">{_ic("megaphone", 22)}</span>'
    a = p.get("author") or {}
    who = _person_name(a) if a else ((p.get("author_label") or "").strip() or (biz.get("name") or ""))
    extra = f"{len(photos)} photo{'' if len(photos) == 1 else 's'}" if photos else (p.get("group_name") or when_label(biz, cn.when_of(p)))
    sub = " · ".join(x for x in (who, extra) if x)
    title = p.get("title") or (p.get("body") or "")[:80]
    return (f'<a class="nw-row" href="/my/news#p-{_e(p["id"])}">{thumb}<span class="nw-t"><b>{_e(title)}</b>'
            f'<span>{_e(sub)}</span></span>{_ic("chevron", 18)}</a>')


def home_block(biz: Dict[str, Any], posts: Optional[List[Dict[str, Any]]], occ: Optional[List[Dict[str, Any]]],
               open_: bool) -> str:
    """'From the church' on Home: the pinned or newest post as a card, then
    up to three more as rows. Nothing at all when there's no news (Home
    never says "nothing yet")."""
    import member_app_ui as ui
    if not posts:
        return ""
    lead, rest = posts[0], posts[1:4]
    rows = "".join(_row(biz, p) for p in rest)
    return (f'<section aria-labelledby="nw-home-h">{ui.section("From the church", "/my/news", "All news", hid="nw-home-h")}'
            f'{card(biz, lead, _occasions(occ), back="/my", open_=open_)}'
            f'{f"<div class=nw-rows>{rows}</div>" if rows else ""}</section>')


# ─── the pages ───────────────────────────────────────────────────────


def render_news(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any],
                posts: Optional[List[Dict[str, Any]]], filt: str, occ, open_: bool) -> Tuple[str, int]:
    from member_portal import _shell
    head = ('<a class="mb-back" href="/my">Home</a>'
            '<div class="nw-head"><p class="nw-eb">From your church</p><h1 class="nw-lt">What\'s <em>happening.</em></h1></div>')
    if posts is None:
        body = f'{head}<p class="mp-err" role="alert">The news couldn\'t load just now. Please try again in a moment.</p>'
        return _shell(biz, site, "News", f"<style>{NEWS_CSS}</style>{body}", tab="home", who=me), 503
    chips = "".join(
        f'<a class="nw-fp" href="/my/news{"?f=" + key if key else ""}"{" aria-current=page" if key == filt else ""}>{label}</a>'
        for key, label in cn.FILTERS)
    by = _occasions(occ)
    back = "/my/news" + (f"?f={filt}" if filt else "")
    cards = "".join(card(biz, p, by, back=back, open_=open_) for p in posts)
    if not cards:
        empty = ("Nothing from your church yet. When your pastors post, it shows here." if not filt
                 else "Nothing here yet. Try All.")
        cards = f'<p class="nw-empty">{empty}</p>'
    foot = (f'<p class="nw-foot">{_ic("lock", 16)}<span>Only your pastors and the leaders they name can post here. '
            f'{"Everyone can react and comment, and every comment is checked before anyone sees it." if open_ else "Everyone can react."}'
            f'</span></p>')
    body = (f'{head}<nav class="nw-filter" aria-label="Show">{chips}</nav>{_flash(request)}'
            f'<div class="nw-list">{cards}</div>{foot}')
    return _shell(biz, site, "News", f"<style>{NEWS_CSS}</style>{body}", tab="home", who=me, script=RX_JS), 200


def _comment(biz: Dict[str, Any], c: Dict[str, Any], pid: str, *, can_take_down: bool) -> str:
    person = c.get("person") or {}
    name = "You" if c.get("mine") else _person_name(person)
    tag = '<span class="nw-tag pastor">Pastor</span>' if c.get("pastor") and not c.get("mine") else ""
    held = c.get("status") == "held"
    cls = "nw-cm" + (" rep" if c.get("is_reply") else "") + (" held" if held else "")
    back = f"/my/news/{pid}"
    cid = _e(c["id"])
    if held:
        meta = f'<span class="nw-checking">{_ic("shield", 13)}<span>Only you see this until a safety officer looks at it.</span></span>'
    elif c.get("i_reported"):
        meta = (f'<span class="nw-reported">{_ic("flag", 13)}<span>Reported. The safety officers will look. '
                f'They won\'t say who told them.</span></span>')
    else:
        n = int(c.get("loves") or 0)
        on = bool(c.get("i_loved"))
        love = (f'<form method="post" action="/my/news/comment/love" class="nw-lovef"><input type="hidden" name="id" value="{cid}">'
                f'<input type="hidden" name="back" value="{_e(back)}"><button type="submit" aria-pressed="{"true" if on else "false"}">'
                f'<span data-love data-n="{n - (1 if on else 0)}">{("Love · " + str(n)) if n else "Love"}</span></button></form>')
        reply = f'<a href="/my/news/{_e(pid)}?reply={cid}#nw-comp">Reply</a>'
        report = ("" if c.get("mine") else
                  f'<form method="post" action="/my/news/comment/report"><input type="hidden" name="id" value="{cid}">'
                  f'<button class="flag" type="submit">Report</button></form>')
        down = (f'<form method="post" action="/my/news/comment/remove"><input type="hidden" name="id" value="{cid}">'
                f'<button class="flag" type="submit">{"Delete" if c.get("mine") else "Take down"}</button></form>'
                if (c.get("mine") or can_take_down) else "")
        meta = f'<div class="nw-cm-meta"><span>{_e(when_label(biz, c.get("created_at")))}</span>{love}{reply}{report}{down}</div>'
    return (f'<div class="{cls}" id="c-{cid}">{_face(person, "nw-av s")}<div class="nw-cm-col"><div class="nw-cm-b">'
            f'<span class="nw-cm-who"><span>{_e(name)}</span>{tag}</span><span>{_e(c.get("body") or "")}</span></div>'
            f'{meta}</div></div>')


def _reactors(p: Dict[str, Any]) -> str:
    """'Dana, Monique and 89 others reacted', their faces first."""
    n = int(p.get("reactors_n") or 0)
    if not n:
        return ""
    shown = [r for r in (p.get("reactors") or [])][:2]
    firsts = [(_person_name(r).split(" ")[0] or "Someone") for r in shown]
    others = n - len(firsts)
    if not firsts:
        words = f"{n} {'person' if n == 1 else 'people'} reacted"
    elif others <= 0:
        words = " and ".join(firsts) + " reacted"
    else:
        words = f"{', '.join(firsts)} and {others} {'other' if others == 1 else 'others'} reacted"
    faces = "".join(_face(r) for r in shown)
    return f'<p class="nw-who"><span class="nw-faces" aria-hidden="true">{faces}</span><span>{_e(words)}</span></p>'


def render_post(biz: Dict[str, Any], site, request: Request, me: Dict[str, Any], p: Optional[Dict[str, Any]], occ,
                open_: bool) -> Tuple[str, int]:
    from member_portal import _shell
    import member_photos as ph
    import member_app_ui as ui
    head = '<a class="mb-back" href="/my/news">News</a>'
    if p is None:
        body = f'{head}<p class="mp-err" role="alert">This post couldn\'t load just now. Please try again in a moment.</p>'
        return _shell(biz, site, "News", f"<style>{NEWS_CSS}</style>{body}", tab="home", who=me), 503
    if not p:
        body = (f'{head}<div class="mb-lt"><h1>Not here</h1></div>'
                f'<p class="mp-muted">That post isn\'t there any more. See what\'s new on News.</p>')
        return _shell(biz, site, "News", f"<style>{NEWS_CSS}</style>{body}", tab="home", who=me), 404
    pid = str(p["id"])
    thread = p.get("thread") or []
    i_posted = str(p.get("posted_by") or "") == str(me["id"])
    shown_n = sum(1 for c in thread if c.get("status") == "shown")
    who_rx = _reactors(p)
    cms = "".join(_comment(biz, c, pid, can_take_down=i_posted) for c in thread)
    mode = p.get("comments") or "on"
    can_say = open_ and mode == "on"
    if not cms:
        cms = (f'<p class="nw-empty" id="nw-cm-empty">{"Be the first to say something." if can_say else "No comments."}</p>')
    count = f'{shown_n} comment{"" if shown_n == 1 else "s"} · oldest first' if shown_n else ""
    section = (f'<div class="nw-ch" id="comments"><h2>Comments</h2><span>{count}</span></div>'
               f'<div class="nw-cmts" id="nw-cmts">{cms}</div>') if (mode != "off" and (open_ or thread)) else ""
    comp = ""
    if can_say:
        reply_to = str(request.query_params.get("reply") or "")
        target = next((c for c in thread if str(c["id"]) == reply_to and c.get("status") == "shown"), None)
        replying = ""
        hidden = ""
        if target:
            tname = "yourself" if target.get("mine") else _person_name(target.get("person") or {}).split(" ")[0]
            replying = (f'<div class="nw-replying"><span>Replying to {_e(tname)}</span>'
                        f'<a href="/my/news/{_e(pid)}#nw-comp">Cancel</a></div>')
            hidden = f'<input type="hidden" name="reply_to" value="{_e(target["id"])}">'
        mine = ph.src(me)
        me_face = (f'<span class="nw-me"><img src="{_e(mine)}" alt=""></span>' if mine
                   else f'<span class="nw-me" aria-hidden="true">{_e(ui.initials(me.get("name")))}</span>')
        comp = (f'<div class="nw-comp" id="nw-comp">{replying}<form id="nw-say" method="post" action="/my/news/comment">'
                f'<input type="hidden" name="id" value="{_e(pid)}">{hidden}<div class="nw-comp-row">{me_face}'
                f'<label class="nw-comp-in"><span class="mp-sr">Write a comment</span>'
                f'<textarea name="body" rows="1" maxlength="{cn.COMMENT_MAX}" required placeholder="Write a comment…"'
                f'{" autofocus" if target else ""}></textarea></label>'
                f'<button class="nw-send" type="submit" aria-label="Post comment">{_ic("plane", 18)}</button></div>'
                f'<p class="nw-safe">{_ic("shield", 13)}<span>Every comment is checked before the church sees it</span></p>'
                f'</form></div>')
    elif mode == "on" and not open_:
        comp = (f'<p class="nw-closed">{_ic("lock", 16)}<span>Comments aren\'t open at '
                f'{_e(biz.get("name") or "your church")} yet. You can still react.</span></p>')
    elif mode == "prayers":
        comp = f'<p class="nw-closed">{_ic("pray", 16)}<span>Comments are off for this one. Tap Praying to let them know.</span></p>'
    elif mode == "off":
        comp = f'<p class="nw-closed">{_ic("lock", 16)}<span>Comments are off for this post.</span></p>'
    body = (f'{head}{_flash(request)}<div style="margin-top:6px">'
            f'{card(biz, p, _occasions(occ), back="/my/news/" + pid, open_=open_, full=True)}</div>'
            f'{who_rx}{section}{comp}')
    title = p.get("title") or "Post"
    return _shell(biz, site, title, f"<style>{NEWS_CSS}</style>{body}", tab="home", who=me,
                  bar=not can_say, script=RX_JS + (COMMENT_JS if can_say else "")), 200


async def serve(request: Request, biz: Dict[str, Any], site, me: Dict[str, Any], sub: str) -> Tuple[str, int]:
    """GET /my/news and /my/news/<id>."""
    import member_portal_church as mpc
    rest = sub[len("/my/news"):].strip("/")
    business_id, me_id = str(biz["id"]), str(me["id"])
    if not rest:
        filt = str(request.query_params.get("f") or "")
        filt = filt if filt in dict(cn.FILTERS) else ""
        posts, occ, open_ = await asyncio.gather(asyncio.to_thread(cn.feed, business_id, me_id, filt),
                                                 asyncio.to_thread(mpc.upcoming_for, business_id, me),
                                                 asyncio.to_thread(cn.comments_open, biz))
        if posts:
            await asyncio.to_thread(cn.mark_seen, business_id, me_id, [str(p["id"]) for p in posts])
        return render_news(biz, site, request, me, posts, filt, occ, open_)
    p, occ, open_ = await asyncio.gather(asyncio.to_thread(cn.one, business_id, me_id, rest),
                                         asyncio.to_thread(mpc.upcoming_for, business_id, me),
                                         asyncio.to_thread(cn.comments_open, biz))
    if p:
        await asyncio.to_thread(cn.mark_seen, business_id, me_id, [str(p["id"])])
    return render_post(biz, site, request, me, p, occ, open_)


# ─── routes ──────────────────────────────────────────────────────────


def _go(target: str, anchor: str = "", **q: str) -> RedirectResponse:
    from member_portal import _SECURE_HEADERS
    path, _, query = (target or "").partition("?")
    if not _BACK_RE.match(path):
        path, query = "/my/news", ""
    keep = [kv for kv in query.split("&") if kv.startswith("f=")] if query else []
    qs = "&".join(keep + [f"{k}={v}" for k, v in q.items() if v])
    url = f"{path}?{qs}" if qs else path
    return RedirectResponse(url + (f"#{anchor}" if anchor else ""), status_code=303, headers=_SECURE_HEADERS)


async def _who(request: Request, back: str):
    import member_portal_church as mpc
    church, me, unavailable = await mpc._signed_in(request)
    if unavailable:
        return None, None, None, _go(back, err="preview" if unavailable == "preview" else "error")
    if not me:
        return None, None, None, mpc._back("/my")
    if not mpc._allowed(church, me):
        return None, None, None, _go(back, err="slow")
    form = await request.form()
    return church, me, form, None


@router.post("/my/news/react", include_in_schema=False)
async def react_route(request: Request):
    form0_back = "/my/news"
    church, me, form, stop = await _who(request, form0_back)
    if stop:
        return stop
    back = str(form.get("back") or "/my/news")
    ok, code, pid = await asyncio.to_thread(cn.react, str(church["business"]["id"]), str(me["id"]),
                                            str(form.get("id") or ""), str(form.get("kind") or ""))
    return _go(back, f"p-{pid}" if pid and not back.startswith("/my/news/") else "", **({} if ok else {"err": code}))


@router.post("/my/news/comment", include_in_schema=False)
async def comment_route(request: Request):
    church, me, form, stop = await _who(request, "/my/news")
    if stop:
        return stop
    pid = str(form.get("id") or "")
    ok, code, pid = await cn.comment(church["business"], me, pid, str(form.get("body") or ""), str(form.get("reply_to") or ""))
    target = f"/my/news/{pid}" if pid else "/my/news"
    return _go(target, "comments" if ok else "nw-comp", **({"done": code} if ok else {"err": code}))


async def _comment_action(request: Request, act):
    church, me, form, stop = await _who(request, "/my/news")
    if stop:
        return stop
    ok, code, pid = await asyncio.to_thread(act, str(church["business"]["id"]), str(me["id"]), str(form.get("id") or ""))
    target = f"/my/news/{pid}" if pid else "/my/news"
    return _go(target, "comments", **({"done": code} if ok and code else {} if ok else {"err": code}))


@router.post("/my/news/comment/love", include_in_schema=False)
async def love_route(request: Request):
    return await _comment_action(request, cn.love)


@router.post("/my/news/comment/report", include_in_schema=False)
async def report_route(request: Request):
    return await _comment_action(request, cn.report)


@router.post("/my/news/comment/remove", include_in_schema=False)
async def remove_route(request: Request):
    return await _comment_action(request, cn.remove_comment)
