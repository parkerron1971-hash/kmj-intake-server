"""member_lumen_feed.py — Home's feed in the member app's new look: "What's
happening at <church>", each post a calm card with its reactions and the
comments under it ("Look 4.1").

Kevin approved the Look 4.1 Home mock (2026-11-19) and asked earlier: "make
sure the people can comment under news feed. i know who ever make the post
can allow whether people can comment or not." So each post on Home carries,
under a thin line:

  * a summary: the reactions as small grey badges (Love in the church's
    colour), how many people reacted, and "N comments";
  * Love · Amen · Praying · Comment, the same react forms as News
    (member_portal_news.RX_JS answers them in place);
  * the newest one or two comments as soft bubbles (one reply in, under
    the comment it answers), then "View all N comments";
  * "Write a comment…" with the member's face: it posts to the same
    /my/news/comment route, asking for a JSON answer, so the comment shows
    as "Checking…" and then as posted, or the page's own held or crisis
    words (988) show under the box, all without leaving Home. Without
    JavaScript the form posts as it always did (the post's own page).
    "Every comment is checked before the church sees it" shows while
    writing.
  * The poster's choice holds: Prayers only is a soft "I'm praying" (the
    pray reaction) with "Comments are off for this one. Tap Praying to let
    them know."; Off is a quiet lock line; before the church has its two
    safety officers, "Comments aren't open at <church> yet. You can still
    react." (member_portal_news' words).

Pictures are the post's own (one as a header, more as an album); an event
post shows its event with the date on a leaf in the church's colour, over
the event's picture spot (member_app_photos.choose, event:<name>) when the
church has one. "You're all caught up" and an Earlier line sit between the
posts this member hasn't opened and the ones they have (church_news
.home_view's seen read).

Data: church_news.home_view(previews=True) brings each post's newest
comments and their writers in the reads Home already made (the comment
count read and the people read), so the feed costs no read of its own.

Home shows four posts. Under the fourth, See all posts (Kevin, 2026-11-20:
"show 4 post and a show more tab where people can see other post from
another page"), with how many there are, counted from Home's own read,
opens the all-posts page: /my/news in the new look (all_posts), the same
cards ten at a time (church_news.feed_page), the filters, and Show more, a
plain link to the next ten (?page=2), so it works without JavaScript.

CSS joins /my/lumen.<hash>.css (member_lumen_ui.templates); every rule sits
under body.lm. The script rides in the block itself (Home only).
"""
from __future__ import annotations

from datetime import date
from string import Template
from typing import Any, Dict, List, Optional

# Love · Amen · Praying, as the mock draws them; Celebrate shows among the badges.
ROW = (("love", "Love"), ("amen", "Amen"), ("pray", "Praying"))
BADGE_ORDER = ("love", "pray", "amen", "cheer")


def _e(v: Any) -> str:
    from html import escape
    return escape(str(v if v is not None else ""), quote=True)


def _ic(name: str, size: int = 18) -> str:
    import member_portal_news as mpn
    return mpn._ic(name, size)


def _first(person: Dict[str, Any]) -> str:
    import member_portal_news as mpn
    return (mpn._person_name(person).split(" ")[0] or "them") if person else "them"


# ─── a comment ───────────────────────────────────────────────────────


def comment_html(biz: Dict[str, Any], c: Dict[str, Any], pid: str, *, tz: Any = None) -> str:
    """One comment as a soft bubble: the writer's face (or initials), name,
    words, and "2h · Reply". The member's own held comment says only they
    see it (member_portal_news' words). Shared by the feed and the comment
    route's JSON answer. `tz`: (the church's clock,) when already looked up."""
    import member_portal_news as mpn
    person = c.get("person") or {}
    name = "You" if c.get("mine") else mpn._person_name(person)
    held = c.get("status") == "held"
    cls = "lm-cm" + (" rep" if c.get("is_reply") else "") + (" mine" if c.get("mine") else "") + (" held" if held else "")
    cid = _e(c.get("id") or "")
    if held:
        meta = f'<span class="lm-cmeta">{_ic("shield", 12)}<span>Only you see this until a safety officer looks at it.</span></span>'
    else:
        when = mpn.when_label(biz, c.get("created_at"), **({"tz": tz[0]} if tz else {}))
        reply = (f'<a href="/my/news/{_e(pid)}?reply={cid}#nw-comp" data-reply="{cid}" data-who="{_e(_first(person) if not c.get("mine") else "yourself")}">'
                 f'Reply</a>') if cid else ""
        meta = f'<span class="lm-cmeta"><span>{_e(when)}</span>{"<i aria-hidden=true>·</i>" + reply if reply else ""}</span>'
    return (f'<div class="{cls}" id="fc-{cid}">{mpn._face(person, "lm-fface")}<div class="lm-cmb">'
            f'<span class="lm-cmbub"><b>{_e(name)}</b><span>{_e(c.get("body") or "")}</span></span>{meta}</div></div>')


# ─── a post ──────────────────────────────────────────────────────────


def _source(biz: Dict[str, Any], p: Dict[str, Any], tz: Any) -> str:
    """Who posted (their face, or the church's mark), when, and Pinned."""
    import member_app_ui as ui
    import member_portal_news as mpn
    a = p.get("author") or {}
    church = (biz.get("name") or "").strip() or "Your church"
    kind = {"celebration": "Celebration", "event": "Event", "message": "New message", "photos": "Photos"}.get(p.get("kind") or "", "")
    if a:
        face, who = mpn._face(a, "lm-fface"), mpn._person_name(a)
    else:
        label = (p.get("author_label") or "").strip()
        who = label if label and label != church else church
        face = f'<span class="lm-logo" aria-hidden="true">{_e(ui.initials(who))}</span>'
    if kind and not p.get("group_id"):
        who = f"{who} · {kind}"
    bits = []
    if p.get("pastor") and a:
        bits.append("Pastor")
    if p.get("group_id"):
        bits.append(p.get("group_name") or "Your group")
    bits.append(mpn.when_label(biz, _when(p), tz=tz[0]))
    pin = '<span class="lm-fpin">Pinned</span>' if p.get("pinned") else ""
    return (f'<div class="lm-fsrc">{face}<span class="lm-fwho"><b>{_e(who)}</b>'
            f'<small>{_e(" · ".join(b for b in bits if b))}</small></span>{pin}</div>')


def _when(p: Dict[str, Any]) -> str:
    import church_news as cn
    return cn.when_of(p)


def _photos(p: Dict[str, Any]) -> List[tuple]:
    """The post's own photos (linked by the church, or uploaded with it),
    as member_portal_news draws them: (url, w, h)."""
    att = p.get("attach") or {}
    out = [(u, 0, 0) for u in att.get("photos") or [] if isinstance(u, str)]
    out += [(f"/my/news/{p['id']}/photo/{i}", int(x.get("w") or 0), int(x.get("h") or 0))
            for i, x in enumerate(att.get("pics") or []) if isinstance(x, dict) and x.get("path")]
    return out


def _picture(p: Dict[str, Any]) -> str:
    """One photo as the card's header (a tall one stays tall); two side by
    side; more as an album with how many more."""
    pics = _photos(p)
    if not pics:
        return ""
    href = f"/my/news/{_e(p['id'])}"
    if len(pics) == 1:
        u, w, h = pics[0]
        size = f' width="{w}" height="{h}"' if w and h else ""
        tall = " tall" if w and h and h > w else ""
        return f'<a class="lm-fpic{tall}" href="{href}"><img src="{_e(u)}" alt="" loading="lazy" decoding="async"{size}></a>'
    shown = pics[:3]
    more = len(pics) - len(shown)
    cells = []
    for i, (u, _w, _h) in enumerate(shown):
        over = f'<span class="lm-fmore">+{more}</span>' if more and i == len(shown) - 1 else ""
        cells.append(f'<a href="{href}"><img src="{_e(u)}" alt="" loading="lazy" decoding="async">{over}</a>')
    return f'<div class="lm-falb{" two" if len(shown) == 2 else ""}">{"".join(cells)}</div>'


def _event(biz: Dict[str, Any], p: Dict[str, Any], occ: Dict[str, Dict[str, Any]], pool: List[str],
           used: set, back: str = "/my") -> str:
    """The event a post carries: its picture spot (when the church has a
    picture there) with the date on a leaf in the church's colour, what and
    where, and Sign me up when the post offers it."""
    import member_app_photos as photos
    import member_portal_church as mpc
    att = p.get("attach") or {}
    o = occ.get(str(att.get("event") or ""))
    if not o:
        return ""
    try:
        d: Optional[date] = date.fromisoformat(str(o.get("date"))[:10])
    except ValueError:
        d = None
    leaf = (f'<span class="lm-leaf" aria-hidden="true"><small>{d.strftime("%a").upper()}</small><b>{d.day}</b></span>'
            if d else "")
    pic = ""
    if not _photos(p):
        pic, _look = photos.choose(biz, mpc.event_key(o.get("title")), pool, title=o.get("title") or "", used=used)
    img = f'<img src="{_e(pic)}" alt="" loading="lazy" decoding="async">' if pic else ""
    box = f'<span class="lm-fev-p{"" if pic else " bare"}">{img}{leaf}</span>' if (img or leaf) else ""
    going = int(o.get("attending") or 0)
    mine = (o.get("mine") or {}).get("status") == "yes"
    bits = [o.get("date_label") or "", o.get("location") or "",
            "You're coming" if mine else (f"{going} coming" if going else "")]
    out = (f'<a class="lm-fev" href="/my/events#mp-occ-{_e(o["entry_id"])}">{box}<span class="lm-fev-t">'
           f'<b>{_e(o.get("title") or "")}</b><span>{_e(" · ".join(b for b in bits if b))}</span></span></a>')
    if att.get("signup"):
        if mine:
            out += (f'<p class="lm-fin">{_ic("check", 16)}<span>You\'re signed up.</span>'
                    f'<a href="/my/events#mp-occ-{_e(o["entry_id"])}">Change</a></p>')
        else:
            out += (f'<form class="lm-fact" method="post" action="/my/news/signup"><input type="hidden" name="id" value="{_e(p["id"])}">'
                    f'<input type="hidden" name="back" value="{_e(back)}"><button class="lm-btn sm" type="submit">Sign me up</button></form>')
    return out


def _carries(p: Dict[str, Any]) -> str:
    """A sermon or a link the post carries."""
    out = []
    s = p.get("sermon")
    if s:
        bits = [s.get("speaker") or "", s.get("scripture") or ""]
        out.append(f'<a class="lm-fatt" href="/my/sermons/{_e(s["id"])}"><span class="lm-fatt-i">{_ic("playtri", 16)}</span>'
                   f'<span class="lm-fatt-t"><b>{_e(s.get("title") or "")}</b><span>{_e(" · ".join(b for b in bits if b))}</span></span>'
                   f'{_ic("chevron", 16)}</a>')
    link = (p.get("attach") or {}).get("link")
    if isinstance(link, str) and link.startswith("https://"):
        from urllib.parse import urlparse
        u = urlparse(link)
        rest = (u.path.rstrip("/") + ("?" + u.query if u.query else ""))[:60]
        out.append(f'<a class="lm-fatt" href="{_e(link)}" target="_blank" rel="noopener nofollow ugc"><span class="lm-fatt-i">'
                   f'{_ic("link", 16)}</span><span class="lm-fatt-t"><b>{_e(u.netloc.removeprefix("www."))}</b>'
                   f'<span>{_e(rest or "Open the link")}</span></span>{_ic("chevron", 16)}</a>')
    return "".join(out)


def _words(p: Dict[str, Any]) -> str:
    title, body = p.get("title") or "", p.get("body") or ""
    href = f"/my/news/{_e(p['id'])}"
    if p.get("kind") == "praise":
        h = f'<h3><a href="{href}">{_e(title)}</a></h3>' if title else ""
        q = f'<q class="lm-fq">{_e(body)}</q>' if body else ""
        return f'<div class="lm-fbody"><span class="lm-fk">Praise report</span>{h}{q}</div>' if (h or q) else ""
    kick = '<span class="lm-fk">Celebrating</span>' if p.get("kind") == "celebration" else ""
    h = f'<h3><a href="{href}">{_e(title)}</a></h3>' if title else ""
    para = f'<p>{_e(body)}</p>' if body else ""
    return f'<div class="lm-fbody">{kick}{h}{para}</div>' if (h or para) else ""


def _react(p: Dict[str, Any], kind: str, label: str, back: str = "/my") -> str:
    """One of Love · Amen · Praying: News' react form (RX_JS answers it in place)."""
    on = kind in (p.get("my_rx") or [])
    icon = {"love": _ic("heart", 15), "pray": _ic("pray", 15)}.get(kind, "")
    return (f'<form method="post" action="/my/news/react" class="nw-rxf"><input type="hidden" name="id" value="{_e(p["id"])}">'
            f'<input type="hidden" name="kind" value="{kind}"><input type="hidden" name="back" value="{_e(back)}">'
            f'<button class="lm-ca{" lv" if kind == "love" else ""}" type="submit" aria-pressed="{"true" if on else "false"}">'
            f'{icon}<span>{label}</span></button></form>')


def _summary(p: Dict[str, Any], mode: str) -> str:
    rx = p.get("rx") or {}
    kinds = sorted((k for k in BADGE_ORDER if int(rx.get(k) or 0) > 0), key=lambda k: (-int(rx.get(k) or 0), BADGE_ORDER.index(k)))[:3]
    icon = {"love": _ic("heart", 11), "pray": _ic("pray", 11), "cheer": _ic("cheer", 11), "amen": "A"}
    badges = "".join(f'<i class="{k}">{icon[k]}</i>' for k in kinds)
    n = int(p.get("rx_people") or 0)
    who = (f'<span class="lm-cbadges" aria-hidden="true">{badges}</span>'
           f'<span class="lm-cwho">{n} {"person" if n == 1 else "people"}</span>') if n and badges else '<span class="lm-cwho"></span>'
    cn_ = int(p.get("comment_n") or 0)
    count = (f'<a class="lm-ccount" href="/my/news/{_e(p["id"])}#comments">{cn_} comment{"" if cn_ == 1 else "s"}</a>'
             if mode == "on" and cn_ else "")
    if not (n and badges) and not count:
        return ""
    return f'<div class="lm-csum">{who}{count}</div>'


def _composer(p: Dict[str, Any], me: Dict[str, Any]) -> str:
    import church_news as cn
    import member_app_ui as ui
    import member_photos as ph
    pid = _e(p["id"])
    mine = ph.src(me) if me else ""
    face = (f'<span class="lm-cw-me"><img src="{_e(mine)}" alt=""></span>' if mine
            else f'<span class="lm-cw-me" aria-hidden="true">{_e(ui.initials((me or {}).get("name")))}</span>')
    return (f'<form class="lm-cw" method="post" action="/my/news/comment"><input type="hidden" name="id" value="{pid}">{face}'
            f'<label class="lm-cw-in"><span class="mp-sr">Write a comment</span><textarea id="cwt-{pid}" name="body" rows="1" '
            f'maxlength="{cn.COMMENT_MAX}" required placeholder="Write a comment…" aria-describedby="cws-{pid}"></textarea></label>'
            f'<button class="lm-cw-go" type="submit" aria-label="Post comment">{_ic("plane", 16)}</button></form>'
            f'<p class="lm-cw-safe" id="cws-{pid}">{_ic("shield", 13)}<span>Every comment is checked before the church sees it</span></p>'
            f'<p class="lm-cw-say" role="status" hidden></p>')


def _prayers(p: Dict[str, Any], back: str = "/my") -> str:
    """Prayers only: a soft "I'm praying" (the pray reaction, with the
    flame) and how many are."""
    import member_lumen_ui as lm
    on = "pray" in (p.get("my_rx") or [])
    n = int((p.get("rx") or {}).get("pray") or 0)
    base = n - (1 if on else 0)
    return (f'<div class="lm-cpr"><form method="post" action="/my/news/react" class="nw-rxf">'
            f'<input type="hidden" name="id" value="{_e(p["id"])}"><input type="hidden" name="kind" value="pray">'
            f'<input type="hidden" name="back" value="{_e(back)}"><button class="lm-cpray" type="submit" aria-pressed="{"true" if on else "false"}">'
            f'{lm.ic("flame", 20)}<span class="off">I\'m praying</span><span class="on">You\'re praying</span></button></form>'
            f'<p class="lm-cpn"><span class="n0">{f"{base} praying" if base else ""}</span><span class="n1">{base + 1} praying</span></p>'
            f'<p class="lm-cnote">Comments are off for this one. Tap Praying to let them know.</p></div>')


def card(biz: Dict[str, Any], p: Dict[str, Any], occ: Dict[str, Dict[str, Any]], *, open_: bool,
         me: Dict[str, Any], pool: List[str], used: set, tz: Any, back: str = "/my") -> str:
    """One post. `tz` is (the church's clock,), looked up once for the feed.
    `back`: where its forms come back to without JavaScript (Home, or the
    all-posts page it sits on)."""
    pid = _e(p["id"])
    mode = p.get("comments") or "on"
    can_say = open_ and mode == "on"
    row = [(k, label) for k, label in ROW if not (mode == "prayers" and k == "pray")]
    acts = "".join(_react(p, k, label, back) for k, label in row)
    if can_say:
        acts += (f'<label class="lm-ca" for="cwt-{pid}">{_ic("comment", 15)}<span>Comment</span></label>')
    under = ""
    if mode == "on" and open_:
        shown = p.get("preview") or []   # church_news.preview_of
        cms = "".join(comment_html(biz, c, str(p["id"]), tz=tz) for c in shown)
        n = int(p.get("comment_n") or 0)
        more = (f'<a class="lm-cmore" href="/my/news/{pid}#comments">View all {n} comments</a>' if n > len(shown) else "")
        under = f'<div class="lm-cms">{cms}</div>{more}{_composer(p, me)}'
    elif mode == "on":
        church = (biz.get("name") or "").strip() or "your church"
        under = f'<p class="lm-cnote">{_ic("lock", 14)}<span>Comments aren\'t open at {_e(church)} yet. You can still react.</span></p>'
    elif mode == "prayers":
        under = _prayers(p, back)
    else:
        under = f'<p class="lm-cnote">{_ic("lock", 14)}<span>Comments are off for this post.</span></p>'
    return (f'<article class="lm-fc" id="p-{pid}" aria-label="{_e(p.get("title") or "A post")}">'
            f'{_source(biz, p, tz)}{_picture(p)}{_words(p)}{_event(biz, p, occ, pool, used, back)}{_carries(p)}'
            f'<div class="lm-cmx">{_summary(p, mode)}<div class="lm-cact" role="group" aria-label="React">{acts}</div>'
            f'{under}</div></article>')


# ─── the block ───────────────────────────────────────────────────────


def _caught() -> str:
    return (f'<div class="lm-caught"><span class="lm-caught-ok">{_ic("check", 20)}</span><b>You\'re all caught up</b></div>'
            f'<p class="lm-older">Earlier</p>')


def _order(posts: List[Dict[str, Any]]) -> List[Any]:
    """Pinned first, then what this member hasn't opened, "You're all caught
    up", then what they have. No line when it can't be told (the seen read
    failed) or there's nothing on one side of it."""
    if any(p.get("seen") is None for p in posts):
        return list(posts)
    pinned = [p for p in posts if p.get("pinned")]
    rest = [p for p in posts if not p.get("pinned")]
    new, old = [p for p in rest if not p["seen"]], [p for p in rest if p["seen"]]
    if old and (new or any(not p["seen"] for p in pinned)):
        return pinned + new + ["caught"] + old
    return list(posts)


def _head(biz: Dict[str, Any], posts: List[Dict[str, Any]], new_n: Optional[int]) -> str:
    import member_portal_church as mpc
    short = mpc._short_name((biz.get("name") or "").strip())
    sub = "From the church and your groups" if any(p.get("group_id") for p in posts) else "From the church"
    if new_n:
        sub += f" · {new_n} new"
    return (f'<header class="lm-fhead"><h2 class="lm-disp s" id="lm-feed-h">What&#x27;s happening at <em>{_e(short)}</em></h2>'
            f'<p class="lm-fsub">{_e(sub)}</p></header>')


def see_all(total: Optional[int]) -> str:
    """Under Home's four posts: a quiet row to the all-posts page (News),
    with how many posts it lists when that is known (church_news.home_view's
    count, from Home's own read) and more than Home shows."""
    n = int(total) if isinstance(total, int) and total > 4 else 0
    said = f"See all {n} posts" if n else "See all posts"
    count = f'<small aria-hidden="true">{n}</small>' if n else ""
    return (f'<a class="lm-fsee" href="/my/news" aria-label="{said}"><span>See all posts</span>{count}'
            f'{_ic("chevron", 16)}</a>')


def home_feed(biz: Dict[str, Any], site, posts: Optional[List[Dict[str, Any]]], occ, open_: bool,
              rights: Optional[Dict[str, Any]] = None, *, me: Optional[Dict[str, Any]] = None,
              new_n: Optional[int] = None, total: Optional[int] = None) -> str:
    """Home's feed in the new look. Nothing when the news couldn't be read;
    with no news yet, a poster sees where it will go (as today's Home).
    Under the four posts, See all posts (`total`: how many there are)."""
    import member_app_photos as photos
    import member_lumen_ui as lm
    import member_portal_news as mpn
    if not posts:
        if posts != []:
            return ""
        rights = rights or {}
        groups = rights.get("groups") or []
        if rights.get("church"):
            title, sub = "Post the church's first news", f"Everyone at {(biz.get('name') or '').strip() or 'your church'} sees it here, on Home"
        elif groups:
            title, sub = ("Post news for your group" if len(groups) == 1 else "Post news for your groups"), "They see it here, on Home"
        else:
            return ""
        return (f'<section class="lm-feed" aria-labelledby="lm-feed-h">{_head(biz, [], None)}'
                f'{lm.row("/my/news/write", lm.round_icon("megaphone"), title, sub, cls="lm-pray")}</section>')
    import group_gatherings as gg
    by = mpn._occasions(occ)
    pool = photos.photos(biz, site)
    used: set = set()
    # The church's clock, once for every label on the feed (it is a read).
    tz = (gg.zone(biz),)
    cards = []
    for p in _order(posts):
        cards.append(_caught() if p == "caught" else
                     card(biz, p, by, open_=open_, me=me or {}, pool=pool, used=used, tz=tz))
    return (f'<section class="lm-feed" aria-labelledby="lm-feed-h">{_head(biz, posts, new_n)}{"".join(cards)}'
            f'{see_all(total)}</section>{JS}')


# ─── the all-posts page ──────────────────────────────────────────────


def page_href(filt: str = "", page: int = 1) -> str:
    """The all-posts page's address: /my/news, with its filter and page."""
    q = [f"f={filt}"] if filt else []
    if page > 1:
        q.append(f"page={page}")
    return "/my/news" + ("?" + "&".join(q) if q else "")


def _today(people: List[Dict[str, Any]]) -> str:
    """Today's birthdays and anniversaries, together on one card (News'
    "Today we celebrate"), each opening its own page of wishes."""
    import member_portal_celebrations as mcl
    import member_portal_news as mpn
    if not people:
        return ""
    rows = []
    for p in people:
        n = int(p.get("comment_n") or 0)
        if p.get("sub") == "anniversary":
            years = (p.get("attach") or {}).get("years")
            small, act = (f"{years} years married today" if years else "Their anniversary is today"), "Congratulate"
            face = (f'<span class="lm-fpair">{mpn._face(p.get("person") or {}, "lm-fface")}'
                    f'{mpn._face(p.get("partner") or {}, "lm-fface")}</span>')
        else:
            small = "Happy birthday" + (f" · {n} wish{'' if n == 1 else 'es'} so far" if n else "")
            act, face = "Wish them well", mpn._face(p.get("person") or {}, "lm-fface")
        rows.append(f'<a class="lm-fprow" href="/my/news/{_e(p["id"])}">{face}<span class="lm-fprow-t">'
                    f'<b>{_e(mcl.full_name(p))}</b><small>{_e(small)}</small></span><span class="lm-fprow-go">{act}</span></a>')
    return (f'<article class="lm-fc lm-ftoday" aria-label="Today we celebrate"><div class="lm-fbody">'
            f'<span class="lm-fk">Today we celebrate</span></div>{"".join(rows)}'
            f'<p class="lm-cnote lm-ftoday-n">Shown because they said yes</p></article>')


def all_posts(biz: Dict[str, Any], site, request: Any, me: Dict[str, Any], got: Optional[Dict[str, Any]],
              filt: str, occ, open_: bool, poster: bool = False):
    """The News page in the new look, opened from Home's See all posts: the
    heading and filters as before, then the posts as Home draws them (the
    reactions, the newest comments, the write pill, the poster's choice,
    an event's date leaf), ten at a time (church_news.feed_page), with Show
    more, a plain link to the next ten. Back goes Home. (html, status)."""
    import church_news as cn
    import group_gatherings as gg
    import member_app_photos as photos
    import member_portal_news as mpn
    import member_portal_share as mps
    from member_portal import _shell
    write = f'<a class="nw-write" href="/my/news/write">{_ic("pencil", 15)}Post</a>' if poster else ""
    head = ('<a class="mb-back" href="/my">Home</a>'
            f'<header class="lm-mast lm-nwhead"><div class="lm-nwrow"><p class="lm-eyebrow">From your church</p>{write}</div>'
            f'<h1 class="lm-disp">What&#x27;s <em>happening</em></h1></header>')
    if got is None:
        body = f'{head}<p class="mp-err" role="alert">The news couldn\'t load just now. Please try again in a moment.</p>'
        return _shell(biz, site, "News", f'<style>{mpn.NEWS_CSS}</style><div class="lm-nwpage">{body}</div>',
                      tab="news", who=me), 503
    page = int(got.get("page") or 1)
    chips = "".join(
        f'<a class="nw-fp" href="{page_href(key)}"{" aria-current=page" if key == filt else ""}>{label}</a>'
        for key, label in cn.FILTERS)
    back = page_href(filt, page)
    posts, people = got.get("posts") or [], got.get("today") or []
    by = mpn._occasions(occ)
    pool = photos.photos(biz, site) if posts else []
    used: set = set()
    # The church's clock, once for every label on the page (it is a read).
    tz = (gg.zone(biz),) if posts else (None,)
    cards = "".join(card(biz, p, by, open_=open_, me=me, pool=pool, used=used, tz=tz, back=back)
                    for p in posts if p.get("pinned"))
    cards += _today(people)
    cards += "".join(card(biz, p, by, open_=open_, me=me, pool=pool, used=used, tz=tz, back=back)
                     for p in posts if not p.get("pinned"))
    earlier = ""
    if page > 1:
        earlier = f'<p class="lm-fpage"><span>Earlier posts</span><a href="{page_href(filt)}">Back to the newest</a></p>'
    if not cards:
        if page > 1:
            empty = f'That&#x27;s every post. <a href="{page_href(filt)}">Back to the newest</a>'
        else:
            empty = _e("Nothing from your church yet. When your pastors post, it shows here." if not filt
                       else "Nothing here yet. Try All.")
        cards = f'<p class="nw-empty">{empty}</p>'
    more = ""
    if got.get("more"):
        more = (f'<a class="lm-fsee lm-fnext" href="{_e(page_href(filt, page + 1))}"><span>Show more</span>'
                f'{_ic("down", 16)}</a>')
    foot = (f'<p class="nw-foot">{_ic("lock", 16)}<span>Only your pastors and the leaders they name can post here. '
            f'{"Everyone can react and comment, and every comment is checked before anyone sees it." if open_ else "Everyone can react."}'
            f'</span></p>')
    body = (f'{head}<nav class="nw-filter" aria-label="Show">{chips}</nav>{mpn._flash(request)}{earlier}'
            f'<div class="lm-flist" id="lm-flist">{cards}</div>{more}{mps.share_card()}{foot}')
    title = "News" if page == 1 else f"News, page {page}"
    return _shell(biz, site, title, f'<style>{mpn.NEWS_CSS}</style><div class="lm-nwpage">{body}</div>',
                  tab="news", who=me, script=mpn.RX_JS + (JS if posts else "")), 200


# ─── the script: a comment from Home ─────────────────────────────────
# The write pill posts to /my/news/comment asking for JSON (the route's
# answer for a fetch): "Checking…" at once, then the server's own bubble,
# or its held or crisis words under the box. A refusal or a lost answer
# puts the words back in the box with why. Reply sets the comment it
# answers; the box grows as they write.
JS = r"""<script>(function(){
var d=document;if(!window.fetch||!window.FormData||!window.URLSearchParams||!('content' in d.createElement('template')))return;
function el(t,c,x){var e=d.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;}
function fit(t){t.style.height='auto';t.style.height=Math.min(t.scrollHeight,140)+'px';}
d.addEventListener('input',function(e){var t=e.target;if(t&&t.matches&&t.matches('.lm-cw textarea'))fit(t);});
function unreply(f){var h=f.querySelector('input[name=reply_to]');if(h)h.parentNode.removeChild(h);
  f.querySelector('textarea').placeholder='Write a comment…';}
d.addEventListener('click',function(e){var a=e.target.closest&&e.target.closest('.lm-fc a[data-reply]');if(!a)return;
  var f=a.closest('.lm-fc').querySelector('form.lm-cw');if(!f)return;e.preventDefault();
  var h=f.querySelector('input[name=reply_to]');if(!h){h=el('input');h.type='hidden';h.name='reply_to';f.appendChild(h);}
  h.value=a.getAttribute('data-reply');var t=f.querySelector('textarea');t.placeholder='Reply to '+a.getAttribute('data-who')+'…';t.focus();});
function say(f,text,cls,role){var s=f.parentNode.querySelector('.lm-cw-say');if(!s)return;s.className='lm-cw-say'+(cls?' '+cls:'');
  s.setAttribute('role',role||'status');s.textContent=text;s.hidden=!text;}
d.addEventListener('submit',function(e){var f=e.target;if(!f||!f.matches||!f.matches('form.lm-cw'))return;e.preventDefault();
  var t=f.querySelector('textarea'),v=(t.value||'').replace(/^\s+|\s+$/g,'');if(!v||f.getAttribute('data-sending'))return;
  var card=f.closest('.lm-fc'),list=card.querySelector('.lm-cms'),rep=f.querySelector('input[name=reply_to]');
  var p=new URLSearchParams(new FormData(f));say(f,'');
  var li=el('div','lm-cm mine checking'+(rep?' rep':'')),me=f.querySelector('.lm-cw-me').cloneNode(true);me.className='lm-fface';me.setAttribute('aria-hidden','true');
  var col=el('div','lm-cmb'),bub=el('span','lm-cmbub');bub.appendChild(el('b',null,'You'));bub.appendChild(el('span',null,v));
  col.appendChild(bub);col.appendChild(el('span','lm-cmeta','Checking…'));li.appendChild(me);li.appendChild(col);
  list.appendChild(li);t.value='';fit(t);unreply(f);f.setAttribute('data-sending','1');
  fetch(f.getAttribute('action'),{method:'POST',credentials:'same-origin',
    headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},body:p.toString()})
  .then(function(r){return r.json().then(function(x){return x;},function(){return null;});},function(){return null;})
  .then(function(x){f.removeAttribute('data-sending');
    if(x&&x.ok){var tp=d.createElement('template');tp.innerHTML=x.html||'';var n=tp.content.firstElementChild;
      if(n&&li.parentNode){n.classList.add('rise');li.parentNode.replaceChild(n,li);}else{li.classList.remove('checking');}
      if(x.code==='commented'){var c=card.querySelector('.lm-ccount'),m=card.querySelector('.lm-cmore');
        if(c){var k=(parseInt(c.textContent,10)||0)+1;c.textContent=k+(k===1?' comment':' comments');}
        if(m){m.textContent='View all '+((parseInt(m.textContent.replace(/\D+/g,''),10)||0)+1)+' comments';}}
      if(x.notice)say(f,x.notice,x.code==='care'?'care':'',x.code==='care'?'alert':'status');}
    else{if(li.parentNode)li.parentNode.removeChild(li);t.value=v+(t.value?'\n'+t.value:'');fit(t);
      if(rep){f.appendChild(rep);}
      say(f,(x&&x.error)||"That didn't go through. Check your connection, then try again.",'err','alert');}});});
})();</script>"""


CSS = Template("""
/* Home's feed: What's happening at <church>, comments under each post (member_lumen_feed) */
.lm .lm-feed{margin-top:44px;}
.lm .lm-fhead::before{content:"";display:block;width:24px;height:3px;border-radius:2px;background:var(--acc-fill);margin-bottom:12px;}
.lm .lm-fhead .lm-disp{margin:0;}
.lm .lm-fsub{margin:8px 0 0;font:500 13.5px/1.4 var(--mb-ui);color:var(--fg2);}
.lm .lm-feed>.lm-pray{margin-top:16px;}
.lm .lm-fc{display:block;margin-top:14px;border-radius:22px;background:var(--bg);box-shadow:0 0 0 1px var(--lm-line);overflow:hidden;
  scroll-margin-top:76px;}
.lm .lm-fsrc{display:flex;align-items:center;gap:10px;padding:14px 16px 0;}
.lm .lm-fsrc .lm-logo{width:34px;height:34px;font-size:13px;}
.lm .lm-fface{width:34px;height:34px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:var(--s1);
  color:var(--fg2);font:650 12px/1 var(--mb-ui);}
.lm .lm-fface img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lm-fwho{flex:1;min-width:0;}
.lm .lm-fwho b{display:block;font:650 13.5px/1.25 var(--mb-ui);color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm .lm-fwho small{display:block;margin-top:2px;font:500 12px/1.2 var(--mb-ui);color:var(--fg3);}
.lm .lm-fpin{flex:none;height:22px;padding:0 9px;border-radius:11px;background:var(--s1);color:var(--fg2);
  font:700 10px/22px var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;}
.lm .lm-fpic{position:relative;display:block;height:196px;margin-top:12px;overflow:hidden;background:var(--s2);}
.lm .lm-fpic.tall{height:auto;aspect-ratio:4/5;max-height:440px;}
.lm .lm-fpic img,.lm .lm-falb img,.lm .lm-fev-p img{display:block;width:100%;height:100%;object-fit:cover;filter:saturate(.92);}
.lm .lm-falb{display:grid;grid-template-columns:2fr 1fr;grid-template-rows:98px 98px;gap:3px;margin-top:12px;}
.lm .lm-falb.two{grid-template-columns:1fr 1fr;grid-template-rows:180px;}
.lm .lm-falb a{position:relative;display:block;overflow:hidden;background:var(--s2);}
.lm .lm-falb:not(.two) a:first-child{grid-row:1/span 2;}
.lm .lm-fmore{position:absolute;inset:0;display:grid;place-items:center;background:rgba(0,0,0,.42);color:#fff;font:650 18px/1 var(--mb-ui);}
.lm .lm-fbody{padding:12px 16px 2px;}
.lm .lm-fk{display:block;margin-bottom:8px;font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--acc);}
.lm .lm-fbody h3{margin:0;font-family:var(--mb-serif);font-size:25px;line-height:1.1;font-weight:var(--lm-dw,400);
  letter-spacing:var(--lm-dtr,-.02em);font-variation-settings:var(--lm-dvar,normal);font-stretch:var(--lm-dst,100%);color:var(--fg);
  text-wrap:balance;overflow-wrap:anywhere;}
.lm .lm-fbody h3 a{color:inherit;text-decoration:none;}
.lm .lm-fbody p{margin:6px 0 0;font:400 15px/1.5 var(--mb-ui);color:var(--fg2);white-space:pre-line;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lm-fq{display:-webkit-box;margin:0;font-family:var(--lm-read,var(--mb-serif));font-style:italic;font-size:20px;line-height:1.42;quotes:none;
  color:var(--fg);white-space:pre-line;overflow-wrap:anywhere;-webkit-line-clamp:7;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lm-fbody h3+.lm-fq{margin-top:8px;}
.lm .lm-fev{display:flex;align-items:center;gap:14px;margin:14px 16px 0;color:var(--fg);text-decoration:none;}
.lm .lm-fev-p{position:relative;width:76px;height:76px;flex:none;border-radius:14px;overflow:hidden;background:var(--s2);}
.lm .lm-leaf{position:absolute;left:4px;bottom:4px;width:36px;height:40px;border-radius:9px;background:var(--acc-fill);color:var(--on-acc);
  display:flex;flex-direction:column;align-items:center;justify-content:center;}
.lm .lm-leaf small{font:700 8px/1 var(--mb-ui);letter-spacing:.14em;}
.lm .lm-leaf b{margin-top:2px;font-family:var(--mb-serif);font-size:17px;line-height:1;font-weight:var(--lm-dw,400);}
.lm .lm-fev-p.bare{width:58px;height:64px;background:var(--acc-fill);}
.lm .lm-fev-p.bare .lm-leaf{inset:0;width:auto;height:auto;border-radius:0;}
.lm .lm-fev-p.bare .lm-leaf small{font-size:10px;}
.lm .lm-fev-p.bare .lm-leaf b{margin-top:3px;font-size:26px;}
.lm .lm-fev-t{flex:1;min-width:0;}
.lm .lm-fev-t b{display:block;font:700 16.5px/1.2 var(--mb-ui);}
.lm .lm-fev-t span{display:block;margin-top:4px;font:500 13px/1.35 var(--mb-ui);color:var(--fg2);}
.lm .lm-fact{display:flex;align-items:center;gap:10px;flex-wrap:wrap;padding:12px 16px 0;}
.lm .lm-fin{display:flex;align-items:center;gap:8px;margin:12px 16px 0;font:600 14px/1.2 var(--mb-ui);color:var(--fg2);}
.lm .lm-fin .mb-ic{color:var(--acc);}
.lm .lm-fin a{margin-left:auto;color:var(--acc);font-weight:650;text-decoration:none;}
.lm .lm-fatt{display:flex;align-items:center;gap:12px;margin:12px 16px 0;padding:10px 12px;border-radius:14px;background:var(--s1);
  color:var(--fg);text-decoration:none;}
.lm .lm-fatt-i{width:38px;height:38px;flex:none;border-radius:11px;display:grid;place-items:center;background:var(--bg);color:var(--fg);}
.lm .lm-fatt-t{flex:1;min-width:0;}
.lm .lm-fatt-t b{display:block;font:650 14.5px/1.25 var(--mb-ui);}
.lm .lm-fatt-t span{display:block;margin-top:2px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
.lm .lm-fatt>.mb-ic:last-child{color:var(--fg3);flex:none;}

/* the reactions, the action row and the comments under a thin line */
.lm .lm-cmx{padding:4px 16px 14px;}
.lm .lm-csum{display:flex;align-items:center;gap:8px;padding:10px 0;font:500 13px/1 var(--mb-ui);color:var(--fg2);}
.lm .lm-cbadges{display:flex;}
.lm .lm-cbadges i{width:20px;height:20px;border-radius:50%;display:grid;place-items:center;margin-left:-5px;background:var(--s2);
  color:var(--fg2);box-shadow:0 0 0 2px var(--bg);font-family:var(--mb-serif);font-style:italic;font-size:11px;font-weight:600;line-height:1;}
.lm .lm-cbadges i:first-child{margin-left:0;}
.lm .lm-cbadges i.love{background:var(--lm-tint-12);color:var(--acc);}
.lm .lm-cbadges .mb-ic{width:11px;height:11px;}
.lm .lm-cbadges i.love .mb-ic{fill:currentColor;}
.lm .lm-cwho{flex:1;min-width:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm .lm-ccount{flex:none;color:var(--fg2);text-decoration:none;}
.lm .lm-cact{display:flex;margin:0 -4px;border-top:1px solid var(--lm-line);border-bottom:1px solid var(--lm-line);}
.lm .lm-cmx>.lm-cact:first-child{margin-top:8px;}
.lm .lm-cact form{flex:1;display:flex;min-width:0;}
.lm .lm-ca{flex:1;min-width:0;height:40px;padding:0;border:0;border-radius:12px;background:none;display:inline-flex;align-items:center;
  justify-content:center;gap:6px;color:var(--fg2);font:650 12.5px/1 var(--mb-ui);cursor:pointer;white-space:nowrap;}
.lm .lm-ca .mb-ic{width:15px;height:15px;flex:none;}
.lm .lm-ca[aria-pressed=true]{color:var(--acc);}
.lm .lm-ca.lv[aria-pressed=true] .mb-ic{fill:currentColor;}
.lm .lm-cms{display:flex;flex-direction:column;gap:12px;}
.lm .lm-cms:not(:empty){margin-top:12px;}
.lm .lm-cm{display:flex;gap:8px;align-items:flex-start;scroll-margin-top:90px;}
.lm .lm-cm.rep{margin-left:40px;}
.lm .lm-cm .lm-fface{width:32px;height:32px;font-size:11px;}
.lm .lm-cm.rep .lm-fface{width:26px;height:26px;font-size:10px;}
.lm .lm-cmb{flex:1;min-width:0;}
.lm .lm-cmbub{display:inline-block;max-width:100%;padding:9px 12px 10px;border-radius:18px;background:var(--s1);}
.lm .lm-cmbub b{display:block;font:700 12.5px/1.2 var(--mb-ui);color:var(--fg);}
.lm .lm-cmbub span{display:block;margin-top:2px;font:400 14.5px/1.4 var(--mb-ui);color:var(--fg);white-space:pre-line;overflow-wrap:anywhere;}
.lm .lm-cmeta{display:flex;align-items:center;gap:6px;margin:5px 0 0 12px;font:600 11.5px/1.2 var(--mb-ui);color:var(--fg3);}
.lm .lm-cmeta .mb-ic{flex:none;}
.lm .lm-cmeta i{font-style:normal;}
.lm .lm-cmeta a{color:var(--fg2);text-decoration:none;}
.lm .lm-cm.mine .lm-cmbub{background:var(--lm-tint-12);}
.lm .lm-cm.held .lm-cmbub{opacity:.65;}
.lm .lm-cmore{display:inline-block;margin-top:12px;font:650 13px/1 var(--mb-ui);color:var(--fg2);text-decoration:none;}
/* the write pill; the shield line while writing */
.lm .lm-cw{display:flex;align-items:flex-end;gap:10px;margin-top:12px;padding:6px;border-radius:22px;background:var(--s1);}
.lm .lm-cw-me{width:32px;height:32px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:var(--acc-fill);
  color:var(--on-acc);font:700 11px/1 var(--mb-ui);}
.lm .lm-cw-me img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lm-cw-in{flex:1;min-width:0;display:flex;}
.lm .lm-cw textarea{flex:1;min-width:0;min-height:32px;max-height:140px;margin:0;padding:6px 4px;border:0;outline:none;background:transparent;
  resize:none;font:400 16px/1.25 var(--mb-ui);color:var(--fg);}
.lm .lm-cw textarea::placeholder{color:var(--fg3);opacity:1;font-size:14.5px;}
.lm .lm-cw-go{width:32px;height:32px;flex:none;padding:0;border:0;border-radius:50%;display:grid;place-items:center;background:var(--acc-fill);
  color:var(--on-acc);cursor:pointer;}
.lm .lm-cw:not(:focus-within):has(textarea:placeholder-shown) .lm-cw-go{display:none;}
.lm .lm-cw-safe{display:none;align-items:center;gap:6px;margin:8px 0 0 8px;font:500 12px/1.3 var(--mb-ui);color:var(--fg3);}
.lm .lm-cw-safe .mb-ic{flex:none;}
.lm .lm-cw:focus-within+.lm-cw-safe{display:flex;}
.lm .lm-cw:has(textarea:not(:placeholder-shown))+.lm-cw-safe{display:flex;}
.lm .lm-cw-say{margin:10px 0 0;padding:10px 12px;border-radius:14px;background:var(--s1);font:500 13px/1.45 var(--mb-ui);color:var(--fg2);}
.lm .lm-cw-say[hidden]{display:none;}
.lm .lm-cw-say.care,.lm .lm-cw-say.err{color:var(--fg);}
.lm .lm-cw-say.care{box-shadow:inset 3px 0 0 var(--acc-fill);}
/* Prayers only; Off; not open yet */
.lm .lm-cpray{display:flex;align-items:center;justify-content:center;gap:9px;width:100%;height:46px;margin-top:12px;padding:0;border:0;
  border-radius:16px;background:transparent;box-shadow:inset 0 0 0 1px var(--lm-line);color:var(--fg);font:650 15px/1 var(--mb-ui);cursor:pointer;}
.lm .lm-cpray .lm-ic{width:20px;height:20px;color:var(--acc);}
.lm .lm-cpray[aria-pressed=true]{background:var(--s1);}
.lm .lm-cpray .on,.lm .lm-cpray[aria-pressed=true] .off{display:none;}
.lm .lm-cpray[aria-pressed=true] .on{display:inline;}
.lm .lm-cpn{margin:10px 0 0;font:600 13px/1.2 var(--mb-ui);color:var(--fg2);}
.lm .lm-cpn .n1{display:none;}
.lm .lm-cpr:has(.lm-cpray[aria-pressed=true]) .lm-cpn .n0{display:none;}
.lm .lm-cpr:has(.lm-cpray[aria-pressed=true]) .lm-cpn .n1{display:inline;}
.lm .lm-cnote{display:flex;align-items:center;gap:7px;margin:10px 0 0;font:500 12.5px/1.4 var(--mb-ui);color:var(--fg3);}
.lm .lm-cnote .mb-ic{width:14px;height:14px;flex:none;}
/* caught up, then Earlier */
.lm .lm-caught{display:flex;flex-direction:column;align-items:center;gap:8px;margin:36px 0 8px;text-align:center;}
.lm .lm-caught-ok{width:46px;height:46px;border-radius:50%;display:grid;place-items:center;background:var(--lm-tint-12);color:var(--acc);}
.lm .lm-caught b{font:700 16px/1.2 var(--mb-ui);color:var(--fg);}
.lm .lm-older{display:flex;align-items:center;gap:12px;margin:22px 0 0;font:650 11px/1 var(--mb-ui);letter-spacing:.14em;
  text-transform:uppercase;color:var(--fg3);}
.lm .lm-older::before,.lm .lm-older::after{content:"";flex:1;height:1px;background:var(--lm-line);}
/* See all posts under Home's four; Show more on the all-posts page: a quiet row, a hairline like the cards */
.lm .lm-fsee{display:flex;align-items:center;gap:10px;min-height:52px;margin-top:14px;padding:0 14px 0 18px;border-radius:18px;
  background:var(--bg);box-shadow:0 0 0 1px var(--lm-line);color:var(--fg);text-decoration:none;}
.lm .lm-fsee span{flex:1;min-width:0;font:650 14.5px/1.2 var(--mb-ui);}
.lm .lm-fsee small{flex:none;font:500 13.5px/1 var(--mb-ui);color:var(--fg3);font-variant-numeric:tabular-nums;}
.lm .lm-fsee .mb-ic{width:16px;height:16px;flex:none;color:var(--fg3);}
.lm .lm-fsee:active{background:var(--s1);}
.lm .lm-fnext{justify-content:center;gap:8px;margin-top:20px;}
.lm .lm-fnext span{flex:none;}
/* the all-posts page (member_lumen_feed.all_posts): the cards as on Home */
.lm .lm-flist{margin-top:6px;}
.lm .lm-flist>.nw-empty{margin-top:14px;}
.lm .lm-flist>.nw-empty a{color:var(--acc);font-weight:650;text-decoration:none;}
.lm .lm-fpage{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:20px 0 0;
  font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg3);}
.lm .lm-fpage a{font:650 13px/1.2 var(--mb-ui);letter-spacing:0;text-transform:none;color:var(--acc);text-decoration:none;}
.lm .lm-ftoday .lm-fbody{padding-bottom:4px;}
.lm .lm-fprow{display:flex;align-items:center;gap:12px;padding:10px 16px;color:var(--fg);text-decoration:none;}
.lm .lm-fprow-t{flex:1;min-width:0;}
.lm .lm-fprow-t b{display:block;font:650 15px/1.25 var(--mb-ui);}
.lm .lm-fprow-t small{display:block;margin-top:2px;font:500 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lm-fprow-go{flex:none;font:650 13px/1 var(--mb-ui);color:var(--acc);}
.lm .lm-fpair{display:flex;flex:none;}
.lm .lm-fpair .lm-fface+.lm-fface{margin-left:-10px;box-shadow:0 0 0 2px var(--bg);}
.lm .lm-ftoday>.lm-ftoday-n{margin:4px 16px 14px;}
@media (prefers-reduced-motion:no-preference){
  .lm .lm-ca,.lm .lm-cpray,.lm .lm-cw-go{transition:transform .35s cubic-bezier(.3,1.4,.5,1),color .2s,background-color .25s;}
  .lm .lm-ca:active,.lm .lm-cw-go:active{transform:scale(.9);}
  .lm .lm-cpray:active{transform:scale(.97);}
  .lm .lm-cm.checking .lm-cmbub{background:linear-gradient(90deg,var(--s1),var(--lm-tint-12),var(--s1));background-size:200% 100%;
    animation:lmfshim 1.1s linear infinite;}
  .lm .lm-cm.rise{animation:lmfrise .45s cubic-bezier(.2,.8,.2,1) both;}
  .lm .lm-fsee{transition:background-color .2s;}
}
@keyframes lmfshim{to{background-position:-200% 0}}
@keyframes lmfrise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.lm .lm-ca:focus-visible,.lm .lm-cw-go:focus-visible,.lm .lm-cpray:focus-visible,.lm .lm-fsee:focus-visible,.lm .lm-cmore:focus-visible,
.lm .lm-ccount:focus-visible,.lm .lm-fev:focus-visible,.lm .lm-fatt:focus-visible,.lm .lm-fprow:focus-visible,
.lm .lm-fpage a:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.lm .lm-cw:focus-within{box-shadow:0 0 0 1px var(--acc-fill);}

/* posting from a phone (member_portal_write): its Comments and When choices in the new look */
.lm .wr-seg{border-radius:14px;}
.lm .wr-seg span{border-radius:11px;font-weight:650;}
.lm .wr-seg input:checked+span{background:var(--bg);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.12),0 0 0 .5px var(--lm-line);}
""")
