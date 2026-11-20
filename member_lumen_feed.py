"""member_lumen_feed.py — Home's feed in the member app's new look ("Look 5.1"):
one stream of the church's posts, the newest message, and your groups' posts
and prayer requests, each drawn the way the approved mock draws it.

Kevin approved Look 5.1 on 2026-11-20 ("this is awesome. much better design.
lets build this including the new still to build!"). Earlier, for Look 4.1:
"make sure the people can comment under news feed. i know who ever make the
post can allow whether people can comment or not", and "show 4 post and a
show more tab where people can see other post from another page".

THE STREAM (home_feed). "Share a praise or a prayer…" with the member's face
(it opens /my/news/share, Share good news), a thin band, then the posts edge
to edge, a hairline between them:

  * A POST (card): who posted (their face, or the church's mark), "Maya
    Brooks in Young Adults" for a group's post, the kind and the time, and
    "…", which opens the post. Its photos full width with no frame (two side
    by side, a tall one stays tall, more as an album); double-tap a photo to
    Love it (one soft heart; the Love button stays the control). Then the
    icons: Love · Praying · Comment, and Save at the right (the member's
    own list: member_feed_more.toggle_saved); "Loved by Maya and 6 others"
    (the newest Love by name, read with the post's people:
    church_news._decorate); the words, the poster's name in bold; "View all
    N comments" and the newest comment; the write pill on /my/news/comment,
    its checking, held and crisis (988) answers exactly as before. The
    poster's choice holds: Prayers only is "I'm praying" with how many are;
    Off is a lock line; before the church has its two safety officers,
    "Comments aren't open at <church> yet."
  * A MESSAGE (message_card): the church's newest message while it is
    new (member_feed_more.message_of), or the message a post carries: the
    16:9 picture with a play disc, "Series · Part 3 of 4", the title in
    serif, the speaker and scripture, Watch · Listen · Share (Share hands
    the message's PUBLIC page to the share sheet: contract 1, .lm-share).
    The picture is marked for the mini-player (data-lm-media).
  * AN EVENT a post carries: its picture framed with the date on a leaf,
    the day and time, the title, where and how many are going, Going (the
    post's Sign me up, or the event's own RSVP) and, when the church's
    events page is public and the event is too, Share.
  * A PRAYER REQUEST from one of your groups' walls (prayer_card): "Elena in
    Young Adults" (the wall's own promise: first names), the soft panel, the
    words in serif, "I prayed" (the wall's "I'm praying" mark) and how many
    people prayed, with their faces.
  * A GROUP'S POST from its Board (group_post_card): who posted (by the
    group's name setting), the words, and the way to the group.

Pinned first; then what this member hasn't opened and the newer group
items, "You're all caught up", then the rest (Earlier). Home keeps four of
the church's posts, the new message and two group items; See all posts
opens /my/news (all_posts: the church's posts ten at a time, the same cards).

Members' posts, prayer requests and photos of members' families never get
a Share control: Share is on church messages and events only.

Data: church_news.home_view(previews=True) as before (the comments' words
and the Love by name ride in Home's own reads), Home's sermon library, and
member_feed_more.gather (the groups' items, kept 30 s).

CSS joins /my/lumen.<hash>.css (member_lumen_ui.templates); every rule sits
under .lm and reads the page's tokens, so Light, Dark and Same as my phone
all work. The script rides in the block itself.
"""
from __future__ import annotations

from datetime import date, datetime
from string import Template
from typing import Any, Dict, List, Optional

# The mock's icons (24 grid, 1.75 stroke), drawn by the feed itself.
I = {
    "heart": '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5'
             'c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
    "pray": '<path d="M11.4 4.6 9 10.2v4.6l-3.2 3.1 2.6 2.6L12 17V5.3c0-.4-.3-.7-.6-.7z"/>'
            '<path d="M12.6 4.6 15 10.2v4.6l3.2 3.1-2.6 2.6L12 17"/>',
    "comment": '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z"/>',
    "save": '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "play": '<path d="M7 4.5v15l12.5-7.5z"/>',
    "listen": '<path d="M3 14h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a9 9 0 0 1 18 0v7a2 2 0 0 1-2 2h-1a2 2 0 0 1-2-2v-3'
              'a2 2 0 0 1 2-2h3"/>',
    "share": '<path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"/><path d="m16 6-4-4-4 4"/><path d="M12 2v13"/>',
    "users": '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
             '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "send": '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
    "chevron": '<path d="m9 18 6-6-6-6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/>'
            '<path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/>',
}
FILLED = ("play",)
KIND = {"celebration": "Celebration", "event": "Event", "message": "New message", "photos": "Photos",
        "praise": "Praise report", "milestone": "Milestone", "good_news": "Good news"}


def _e(v: Any) -> str:
    from html import escape
    return escape(str(v if v is not None else ""), quote=True)


def _i(name: str, cls: str = "") -> str:
    """One of the mock's icons. `cls`: s (19px) or xs (15px); 24px else."""
    c = "lf-ic" + (f" {cls}" if cls else "") + (" f" if name in FILLED else "")
    return f'<svg class="{c}" viewBox="0 0 24 24" aria-hidden="true" focusable="false">{I[name]}</svg>'


def _ic(name: str, size: int = 18) -> str:
    import member_portal_news as mpn
    return mpn._ic(name, size)


def _first(person: Dict[str, Any]) -> str:
    import member_portal_news as mpn
    return (mpn._person_name(person).split(" ")[0] or "them") if person else "them"


def _ts(v: Any) -> Optional[datetime]:
    import church_news as cn
    return cn._ts(v)


def _when(p: Dict[str, Any]) -> str:
    import church_news as cn
    return cn.when_of(p)


def _church_face(biz: Dict[str, Any], label: str = "") -> str:
    import member_app_ui as ui
    church = (biz.get("name") or "").strip() or "Your church"
    return f'<span class="lm-logo" aria-hidden="true">{_e(ui.initials(label or church))}</span>'


def _head(face: str, who_html: str, small: str, more_href: str, more_label: str, pin: bool = False) -> str:
    """A post's header: the face, who (trusted markup), the kind and time,
    Pinned, and "…" (opens the item's own page)."""
    chip = '<span class="lf-pin">Pinned</span>' if pin else ""
    return (f'<header class="lf-ph">{face}<div class="lf-who"><b>{who_html}</b><small>{_e(small)}</small></div>{chip}'
            f'<a class="lf-more" href="{_e(more_href)}" aria-label="{_e(more_label)}">{_i("more")}</a></header>')


# ─── a comment ───────────────────────────────────────────────────────


def comment_html(biz: Dict[str, Any], c: Dict[str, Any], pid: str, *, tz: Any = None) -> str:
    """One comment as the mock's line: the writer's name in bold, then the
    words. The member's own comment says when ("Just now"); their held
    one says only they see it (member_portal_news' words). Shared by the
    feed and the comment route's JSON answer. `tz`: (the church's clock,)
    when already looked up."""
    import member_portal_news as mpn
    person = c.get("person") or {}
    name = "You" if c.get("mine") else mpn._person_name(person)
    held = c.get("status") == "held"
    cls = "lf-cm" + (" rep" if c.get("is_reply") else "") + (" mine" if c.get("mine") else "") + (" held" if held else "")
    meta = ""
    if held:
        meta = f'<span class="lf-cmeta">{_i("shield", "xs")}<span>Only you see this until a safety officer looks at it.</span></span>'
    elif c.get("mine"):
        when = mpn.when_label(biz, c.get("created_at"), **({"tz": tz[0]} if tz else {}))
        meta = f'<span class="lf-cmeta"><span>{_e(when)}</span></span>'
    return (f'<div class="{cls}" id="fc-{_e(c.get("id") or "")}"><p><b>{_e(name)}</b> '
            f'<span>{_e(c.get("body") or "")}</span></p>{meta}</div>')


# ─── a post's parts ──────────────────────────────────────────────────


def _photos(p: Dict[str, Any]) -> List[tuple]:
    """The post's own photos (linked by the church, or uploaded with it),
    as member_portal_news draws them: (url, w, h)."""
    att = p.get("attach") or {}
    out = [(u, 0, 0) for u in att.get("photos") or [] if isinstance(u, str)]
    out += [(f"/my/news/{p['id']}/photo/{i}", int(x.get("w") or 0), int(x.get("h") or 0))
            for i, x in enumerate(att.get("pics") or []) if isinstance(x, dict) and x.get("path")]
    return out


def _picture(p: Dict[str, Any]) -> str:
    """The post's photos edge to edge: one (a tall one stays tall), two side
    by side, more as an album with how many more (that tile opens the
    post). Double-tap Loves it (JS); the heart button stays the control."""
    pics = _photos(p)
    if not pics:
        return ""
    heart = f'<span class="lf-heart" aria-hidden="true">{_i("heart")}</span>'
    if len(pics) == 1:
        u, w, h = pics[0]
        size = f' width="{w}" height="{h}"' if w and h else ""
        tall = " tall" if w and h and h > w else ""
        return (f'<div class="lf-pic lf-dbl{tall}"><img src="{_e(u)}" alt="" loading="lazy" decoding="async"{size}>'
                f'{heart}</div>')
    shown = pics[:3]
    more = len(pics) - len(shown)
    cells = []
    for i, (u, _w, _h) in enumerate(shown):
        img = f'<img src="{_e(u)}" alt="" loading="lazy" decoding="async">'
        if more and i == len(shown) - 1:
            cells.append(f'<a class="lf-cell" href="/my/news/{_e(p["id"])}" aria-label="See all {len(pics)} photos">{img}'
                         f'<span class="lf-plus">+{more}</span></a>')
        else:
            cells.append(f'<span class="lf-cell">{img}</span>')
    return f'<div class="lf-alb lf-dbl{" two" if len(shown) == 2 else ""}">{"".join(cells)}{heart}</div>'


def _t12(t) -> str:
    """'9 AM', '7:30 PM'."""
    return f"{t.hour % 12 or 12}{f':{t.minute:02d}' if t.minute else ''} {'AM' if t.hour < 12 else 'PM'}"


def _event(biz: Dict[str, Any], site, p: Dict[str, Any], occ: Dict[str, Dict[str, Any]], pool: List[str],
           used: set, back: str = "/my") -> str:
    """The event a post carries: its picture framed with the date on a leaf
    (the post's own photo, else the church's picture for the event), the day
    and time, the title, where and how many are going, Going (the post's
    Sign me up, else the event's own RSVP), and Share when the church's
    events page and the event are public."""
    import events_rsvp_router as er
    import member_app_photos as photos
    import member_lumen_home as lh
    import member_portal_church as mpc
    att = p.get("attach") or {}
    o = occ.get(str(att.get("event") or ""))
    if not o:
        return ""
    try:
        d: Optional[date] = date.fromisoformat(str(o.get("date"))[:10])
    except ValueError:
        d = None
    t = lh.parse_hm(o.get("time"))
    own = _photos(p)
    pic = own[0][0] if own else photos.choose(biz, mpc.event_key(o.get("title")), pool, title=o.get("title") or "",
                                              used=used)[0]
    leaf = (f'<span class="lf-leaf" aria-hidden="true"><small>{d.strftime("%a").upper()}</small><b>{d.day}</b></span>'
            if d else "")
    eid = _e(o.get("entry_id") or "")
    href = f"/my/events#mp-occ-{eid}"
    if pic:
        box = f'<a class="lf-evimg" href="{href}" tabindex="-1" aria-hidden="true"><img src="{_e(pic)}" alt="" loading="lazy" decoding="async">{leaf}</a>'
    elif leaf:
        box = f'<span class="lf-evbare" aria-hidden="true">{leaf}</span>'
    else:
        box = ""
    kick = " · ".join(x for x in ((f"{d.strftime('%A, %b')} {d.day}" if d else ""), (_t12(t) if t else "")) if x)
    going = int(o.get("attending") or 0)
    meta = " · ".join(x for x in (o.get("location") or "", f"{going} going" if going else "") if x)
    mine = (o.get("mine") or {}).get("status") == "yes"
    paid = ((o.get("signup") or {}).get("mine") or {}).get("status") in ("paid", "confirmed")
    if mine or paid:
        go = f'<a class="lf-pill on" href="{href}">{_i("check", "xs")}Going</a>'
    elif att.get("signup"):
        go = (f'<form method="post" action="/my/news/signup"><input type="hidden" name="id" value="{_e(p["id"])}">'
              f'<input type="hidden" name="back" value="{_e(back)}"><button class="lf-pill pri" type="submit">Going</button></form>')
    elif o.get("signup"):
        go = f'<a class="lf-pill pri" href="/my/events">Sign up</a>'
    elif o.get("full"):
        go = '<span class="lf-pill" aria-disabled="true">Full</span>'
    else:
        go = (f'<form method="post" action="/my/rsvp"><input type="hidden" name="entry_id" value="{eid}">'
              f'<input type="hidden" name="back" value="{"/my" if back == "/my" else "/my/events"}">'
              f'<input type="hidden" name="action" value="coming"><button class="lf-pill pri" type="submit">Going</button></form>')
    share = ""
    if o.get("public") and er.events_settings(biz.get("settings")).get("enabled"):
        share = (f'<a class="lf-pill lm-share" href="/events" data-share-kind="event" data-share-title="{_e(o.get("title") or "")}" '
                 f'data-share-sub="{_e(" · ".join(x for x in (kick, o.get("location") or "") if x))}" '
                 f'data-share-img="{_e(pic)}">{_i("share", "xs")}Share</a>')
    words = (p.get("body") or "").strip()
    return (f'<div class="lf-event">{box}<div class="lf-ev"><p class="lf-kick">{_e(kick)}</p>'
            f'<h3><a href="{href}">{_e(o.get("title") or p.get("title") or "")}</a></h3>'
            f'{f"<p>{_e(meta)}</p>" if meta else ""}{f"<p class=lf-evb>{_e(words)}</p>" if words else ""}</div>'
            f'<div class="lf-btns">{go}{share}</div></div>')


def _thumb(lib: Dict[str, Any], s: Dict[str, Any], site, pool: Optional[List[str]]) -> str:
    """The picture's address for the mini-player and the share sheet: the
    series' own art, else a photo named for it (member_portal_sermons._art's
    order); '' when the art is the church's generated poster."""
    import member_app_photos as photos
    import member_portal_sermons as mps
    series = mps._titles(lib).get(str(s.get("series_id") or ""), "")
    own = photos.series_art(site, series) if series else ""
    if own:
        return own
    return photos.by_name(pool or [], series or s.get("title") or "") if pool else ""


def _message_body(lib: Dict[str, Any], s: Dict[str, Any], pal: Dict[str, str], site, pool: List[str], used: set) -> str:
    """The message itself: the 16:9 picture with the play disc (marked for
    the mini-player), "Series · Part n of m", the title in serif, speaker
    and scripture, Watch · Listen · Share. Sermons keep no running time, so
    the picture carries no duration."""
    import member_portal_sermons as mps
    sid = _e(s["id"])
    href = f"/my/sermons/{sid}"
    title = s.get("title") or "Message"
    series = mps._titles(lib).get(str(s.get("series_id") or ""), "")
    kick = " · ".join(x for x in (series, mps._part(lib, s)) if x) or "Message"
    sub = " · ".join(x for x in (s.get("speaker") or "", s.get("scripture") or "") if x)
    thumb = _thumb(lib, s, site, pool)
    video, audio = (s.get("video_url") or "").strip(), (s.get("audio_url") or "").strip()
    media = (f' data-lm-media data-title="{_e(title)}" data-sub="{_e(sub or series)}" data-thumb="{_e(thumb)}"'
             f' data-href="{href}"')
    pic = (f'<a class="lf-vid" href="{href}"{media} aria-label="Play {_e(title)}">{mps._art(lib, s, pal, site, pool, used)}'
           f'<span class="lf-play" aria-hidden="true">{_i("play")}</span></a>')
    if video:
        main = f'<a class="lf-pill pri" href="{href}">{_i("play", "xs")}Watch</a>'
        listen = f'<a class="lf-pill" href="{href}#listen">{_i("listen", "xs")}Listen</a>' if audio else ""
    elif audio:
        main, listen = f'<a class="lf-pill pri" href="{href}#listen">{_i("listen", "xs")}Listen</a>', ""
    else:
        main, listen = f'<a class="lf-pill pri" href="{href}">Open</a>', ""
    share = (f'<a class="lf-pill lm-share" href="/sermons/{sid}" data-share-kind="message" data-share-title="{_e(title)}" '
             f'data-share-sub="{_e(sub)}" data-share-img="{_e(thumb)}">{_i("share", "xs")}Share</a>')
    return (f'{pic}<div class="lf-msg"><p class="lf-kick">{_e(kick)}</p><h3><a href="{href}">{_e(title)}</a></h3>'
            f'{f"<p>{_e(sub)}</p>" if sub else ""}</div><div class="lf-btns">{main}{listen}{share}</div>')


def _day_word(d: Optional[date], today: date) -> str:
    if not d:
        return ""
    n = (today - d).days
    return "Today" if n == 0 else "Yesterday" if n == 1 else d.strftime("%A") if 1 < n < 7 else f"{d.strftime('%b')} {d.day}"


def message_card(biz: Dict[str, Any], site, lib: Dict[str, Any], s: Dict[str, Any], pal: Dict[str, str],
                 pool: List[str], used: set, today: date) -> str:
    """The church's newest message, while it is new (member_feed_more.message_of)."""
    try:
        d: Optional[date] = date.fromisoformat(str(s.get("preached_on") or "")[:10])
    except ValueError:
        d = None
    church = (biz.get("name") or "").strip() or "Your church"
    small = " · ".join(x for x in ("New message", _day_word(d, today)) if x)
    return (f'<article class="lf-post lf-pmsg" id="msg-{_e(s["id"])}" aria-label="{_e("New message: " + (s.get("title") or ""))}">'
            f'{_head(_church_face(biz), _e(church), small, "/my/sermons/" + str(s["id"]), "Open the message")}'
            f'{_message_body(lib, s, pal, site, pool, used)}</article>')


def _carries(p: Dict[str, Any]) -> str:
    """A link the post carries (a sermon it carries is drawn as the message)."""
    link = (p.get("attach") or {}).get("link")
    if not (isinstance(link, str) and link.startswith("https://")):
        return ""
    from urllib.parse import urlparse
    u = urlparse(link)
    rest = (u.path.rstrip("/") + ("?" + u.query if u.query else ""))[:60]
    return (f'<a class="lf-link" href="{_e(link)}" target="_blank" rel="noopener nofollow ugc"><span class="lf-link-i">'
            f'{_i("link", "s")}</span><span class="lf-link-t"><b>{_e(u.netloc.removeprefix("www."))}</b>'
            f'<span>{_e(rest or "Open the link")}</span></span>{_i("chevron", "xs")}</a>')


def _words(p: Dict[str, Any], who: str, *, caption: bool) -> str:
    """The post's words. Under a photo (`caption`): the poster's name in
    bold, the title, then the words, as one caption. Else the title and the
    words; a praise report as a quote."""
    title, body = (p.get("title") or "").strip(), (p.get("body") or "").strip()
    if p.get("kind") == "praise":
        h = f'<b class="lf-t">{_e(title)}</b>' if title else ""
        q = f'<q class="lf-q">{_e(body)}</q>' if body else ""
        return f'<div class="lf-txt">{h}{q}</div>' if (h or q) else ""
    if caption:
        if not (title or body):
            return ""
        t = f'<span class="lf-t">{_e(title)}</span> ' if title else ""
        return f'<p class="lf-cap"><b>{_e(who)}</b> {t}{_e(body)}</p>'
    h = f'<b class="lf-t">{_e(title)}</b>' if title else ""
    para = f'<p>{_e(body)}</p>' if body else ""
    return f'<div class="lf-txt">{h}{para}</div>' if (h or para) else ""


def _react(p: Dict[str, Any], kind: str, label: str, back: str) -> str:
    """Love or Praying: News' react form (member_portal_news.RX_JS answers it in place)."""
    on = kind in (p.get("my_rx") or [])
    icon = _i("heart") if kind == "love" else _i("pray")
    return (f'<form method="post" action="/my/news/react" class="nw-rxf"><input type="hidden" name="id" value="{_e(p["id"])}">'
            f'<input type="hidden" name="kind" value="{kind}"><input type="hidden" name="back" value="{_e(back)}">'
            f'<button class="lf-act {"lv" if kind == "love" else "pr"}" type="submit" aria-pressed="{"true" if on else "false"}" '
            f'aria-label="{label}">{icon}</button></form>')


def _save(p: Dict[str, Any], saved: set, back: str) -> str:
    """Save, at the right: the member's own list (POST /my/news/save)."""
    on = str(p["id"]) in saved
    return (f'<form method="post" action="/my/news/save" class="lf-savef"><input type="hidden" name="id" value="{_e(p["id"])}">'
            f'<input type="hidden" name="back" value="{_e(back)}"><button class="lf-act sv" type="submit" '
            f'aria-pressed="{"true" if on else "false"}" aria-label="Save">{_i("save")}</button></form>')


def _likes(p: Dict[str, Any], mode: str) -> str:
    """"Loved by Maya and 6 others" (the newest Love that isn't mine, by
    first name, as the post's own page names who reacted), and how many
    are praying unless Prayers only already says it."""
    rx = p.get("rx") or {}
    n, pray = int(rx.get("love") or 0), int(rx.get("pray") or 0)
    bits = []
    if n:
        lover = p.get("lover") or {}
        if lover:
            others = n - 1
            more = f' and <b>{others} other{"" if others == 1 else "s"}</b>' if others > 0 else ""
            bits.append(f'Loved by <b>{_e(_first(lover))}</b>{more}')
        elif "love" in (p.get("my_rx") or []) and n == 1:
            bits.append("Loved by <b>you</b>")
        else:
            bits.append(f'Loved by <b>{n} {"person" if n == 1 else "people"}</b>')
    if pray and mode != "prayers":
        bits.append(f'<span>{pray} praying</span>')
    return f'<p class="lf-likes">{" · ".join(bits)}</p>' if bits else ""


def _composer(p: Dict[str, Any], me: Dict[str, Any]) -> str:
    import church_news as cn
    import member_app_ui as ui
    import member_photos as ph
    pid = _e(p["id"])
    mine = ph.src(me) if me else ""
    face = (f'<span class="lf-cw-me"><img src="{_e(mine)}" alt=""></span>' if mine
            else f'<span class="lf-cw-me" aria-hidden="true">{_e(ui.initials((me or {}).get("name")))}</span>')
    return (f'<form class="lf-cw" method="post" action="/my/news/comment"><input type="hidden" name="id" value="{pid}">{face}'
            f'<label class="lf-cw-in"><span class="mp-sr">Write a comment</span><textarea id="cwt-{pid}" name="body" rows="1" '
            f'maxlength="{cn.COMMENT_MAX}" required placeholder="Add a comment…" aria-describedby="cws-{pid}"></textarea></label>'
            f'<button class="lf-cw-go" type="submit" aria-label="Post comment">{_i("send", "xs")}</button></form>'
            f'<p class="lf-cw-safe" id="cws-{pid}">{_i("shield", "xs")}<span>Every comment is checked before the church sees it</span></p>'
            f'<p class="lf-cw-say" role="status" hidden></p>')


def _prayers(p: Dict[str, Any], back: str = "/my", *, words: bool = True) -> str:
    """Prayers only: the post on the soft panel ("Please pray", its words in
    serif) with a soft "I'm praying" (the pray reaction) and how many are.
    `words`: the post's words go on the panel (not when an event carries them)."""
    on = "pray" in (p.get("my_rx") or [])
    n = int((p.get("rx") or {}).get("pray") or 0)
    base = n - (1 if on else 0)
    title, body = (p.get("title") or "").strip(), (p.get("body") or "").strip()
    said = ""
    if words:
        said = (f'{f"<b class=lf-pt>{_e(title)}</b>" if title else ""}'
                f'{f"<p class=lf-say>{_e(body)}</p>" if body else ""}')
    return (f'<div class="lf-pray lf-cpr"><p class="lf-kick">Please pray</p>{said}<div class="lf-prow">'
            f'<form method="post" action="/my/news/react" class="nw-rxf">'
            f'<input type="hidden" name="id" value="{_e(p["id"])}"><input type="hidden" name="kind" value="pray">'
            f'<input type="hidden" name="back" value="{_e(back)}"><button class="lf-pbtn" type="submit" aria-pressed="{"true" if on else "false"}">'
            f'{_i("pray", "s")}<span class="off">I\'m praying</span><span class="on">You\'re praying</span></button></form>'
            f'<span class="lf-pn"><span class="n0">{f"{base} praying" if base else ""}</span><span class="n1">{base + 1} praying</span></span>'
            f'</div></div>')


def _who(biz: Dict[str, Any], p: Dict[str, Any]):
    """(face, who as markup, who in words, the small line's first bits) for
    a church post."""
    import member_portal_news as mpn
    a = p.get("author") or {}
    church = (biz.get("name") or "").strip() or "Your church"
    if a:
        face, name = mpn._face(a, "lf-face"), mpn._person_name(a)
    else:
        label = (p.get("author_label") or "").strip()
        name = label if label and label != church else church
        face = _church_face(biz, name)
    who = _e(name)
    if p.get("group_id"):
        who += f' <i>in</i> {_e(p.get("group_name") or "Your group")}'
    bits = [KIND.get(p.get("kind") or "", "")]
    if p.get("pastor") and a:
        bits.append("Pastor")
    return face, who, name, bits


def card(biz: Dict[str, Any], p: Dict[str, Any], occ: Dict[str, Dict[str, Any]], *, open_: bool,
         me: Dict[str, Any], pool: List[str], used: set, tz: Any, back: str = "/my", site=None,
         lib: Optional[Dict[str, Any]] = None, pal: Optional[Dict[str, str]] = None, saved: Optional[set] = None) -> str:
    """One church post. `tz` is (the church's clock,), looked up once for the
    feed. `back`: where its forms come back to without JavaScript (Home, or
    the page it sits on). `lib` and `pal` draw a message it carries; `saved`
    the member's saved posts (member_feed_more.saved_ids)."""
    import member_portal_news as mpn
    pid = _e(p["id"])
    mode = p.get("comments") or "on"
    can_say = open_ and mode == "on"
    face, who, name, bits = _who(biz, p)
    small = " · ".join(b for b in bits + [mpn.when_label(biz, _when(p), tz=tz[0])] if b)
    head = _head(face, who, small, f"/my/news/{p['id']}", "Open the post", pin=bool(p.get("pinned")))
    att = p.get("attach") or {}
    s = p.get("sermon")
    full = None
    if s and lib:
        full = next((x for x in lib.get("sermons") or [] if str(x.get("id")) == str(s.get("id"))), None)
    event = _event(biz, site, p, occ, pool, used, back) if att.get("event") else ""
    pics = "" if event else _picture(p)
    if full:
        middle = _words(p, name, caption=False) + _message_body(lib, full, pal or {}, site, pool, used)
    elif event:
        middle = event + (_prayers(p, back, words=False) if mode == "prayers" else "")
    elif mode == "prayers":
        middle = pics + _prayers(p, back)
    elif pics and (p.get("title") or "").strip() and p.get("kind") != "praise":
        middle = pics                                          # the caption follows the likes
    else:
        middle = _words(p, name, caption=False) + pics
    if s and not full:
        # A message the library didn't bring: a plain row to it.
        bits_ = " · ".join(x for x in (s.get("speaker") or "", s.get("scripture") or "") if x)
        middle += (f'<a class="lf-link" href="/my/sermons/{_e(s["id"])}"><span class="lf-link-i">{_i("play", "xs")}</span>'
                   f'<span class="lf-link-t"><b>{_e(s.get("title") or "")}</b><span>{_e(bits_)}</span></span>{_i("chevron", "xs")}</a>')
    middle += _carries(p)
    acts = _react(p, "love", "Love", back)
    if mode != "prayers":
        acts += _react(p, "pray", "Praying", back)
    if can_say:
        acts += f'<label class="lf-act" for="cwt-{pid}"><span class="mp-sr">Comment</span>{_i("comment")}</label>'
    acts += _save(p, saved or set(), back)
    caption = _words(p, name, caption=True) if (pics and not event and not full and mode != "prayers"
                                                 and (p.get("title") or "").strip() and p.get("kind") != "praise") else ""
    under = ""
    if mode == "on" and open_:
        shown = (p.get("preview") or [])[-1:]   # the newest (church_news.preview_of)
        cms = "".join(comment_html(biz, c, str(p["id"]), tz=tz) for c in shown)
        n = int(p.get("comment_n") or 0)
        more = (f'<a class="lf-vall" href="/my/news/{pid}#comments">View all {n} comments</a>' if n > len(shown) else "")
        under = f'{more}<div class="lf-cms">{cms}</div>{_composer(p, me)}'
    elif mode == "on":
        church = (biz.get("name") or "").strip() or "your church"
        under = f'<p class="lf-note">{_i("lock", "xs")}<span>Comments aren\'t open at {_e(church)} yet. You can still react.</span></p>'
    elif mode == "prayers":
        under = f'<p class="lf-note">{_i("lock", "xs")}<span>Comments are off for this one. Tap Praying to let them know.</span></p>'
    else:
        under = f'<p class="lf-note">{_i("lock", "xs")}<span>Comments are off for this post.</span></p>'
    return (f'<article class="lf-post" id="p-{pid}" aria-label="{_e(p.get("title") or "A post")}">{head}{middle}'
            f'<div class="lf-acts" role="group" aria-label="React">{acts}</div>{_likes(p, mode)}{caption}'
            f'<div class="lf-under">{under}</div></article>')


# ─── your groups ─────────────────────────────────────────────────────


def prayer_card(biz: Dict[str, Any], item: Dict[str, Any], groups: Dict[str, Dict[str, Any]], *, tz: Any,
                back: str = "/my") -> str:
    """A request on one of the member's groups' prayer walls: "Elena in
    Young Adults" (first names, as the wall promises), the words in serif on
    the soft panel, "I prayed" (the wall's own "I'm praying" mark: POST
    /my/groups/prayer/mark) and how many people prayed, with their faces.
    Never shared."""
    import group_prayer
    import member_portal_news as mpn
    g = groups.get(item["group_id"]) or {}
    asker = item.get("asker") or {}
    name = "You" if item.get("mine") else group_prayer.first(mpn._person_name(asker) if asker else "")
    face = mpn._face({**asker, "name": name} if asker else {"name": name}, "lf-face")
    who = f'{_e(name)} <i>in</i> {_e(g.get("name") or "Your group")}'
    small = " · ".join(x for x in ("Prayer request", mpn.when_label(biz, item.get("at"), tz=tz[0])) if x)
    head = _head(face, who, small, f"/my/groups/{item['group_id']}/prayer", "Open the prayer wall")
    n, on = int(item.get("n") or 0), bool(item.get("i_pray"))
    base = n - (1 if on else 0)
    faces = "".join(mpn._face(x, "lf-mini") for x in (item.get("faces") or [])[:3])
    faces = f'<span class="lf-faces" aria-hidden="true">{faces}</span>' if faces else ""

    def said(k: int) -> str:
        return f'{k} {"person" if k == 1 else "people"} prayed' if k else ""
    count = f'<span class="lf-pn">{faces}<span class="n0">{said(base)}</span><span class="n1">{said(base + 1)}</span></span>'
    if item.get("mine"):
        btn = ""
        count = f'<span class="lf-pn">{faces}<span>{said(n) or "Your group sees it on the wall"}</span></span>'
    else:
        btn = (f'<form method="post" action="/my/groups/prayer/mark" class="lf-prayf"><input type="hidden" name="id" value="{_e(item["id"])}">'
               f'<input type="hidden" name="kind" value="praying"><input type="hidden" name="back" value="{_e(back)}">'
               f'<button class="lf-pbtn" type="submit" aria-pressed="{"true" if on else "false"}">{_i("pray", "s")}'
               f'<span class="off">I prayed</span><span class="on">You prayed</span></button></form>')
    return (f'<article class="lf-post lf-ppr" id="gp-{_e(item["id"])}" aria-label="A prayer request in {_e(g.get("name") or "your group")}">'
            f'{head}<div class="lf-pray"><p class="lf-kick">Please pray</p><p class="lf-say">{_e(item.get("body") or "")}</p>'
            f'<div class="lf-prow">{btn}{count}</div></div></article>')


def group_post_card(biz: Dict[str, Any], item: Dict[str, Any], groups: Dict[str, Dict[str, Any]], *, tz: Any) -> str:
    """A post on one of the member's groups' Boards: who posted (by the
    group's name setting, a teen by first name), the words, and the way to
    the group. Never shared."""
    import member_portal_groups as mpg
    import member_portal_news as mpn
    g = groups.get(item["group_id"]) or {}
    a = item.get("author") or {}
    name = mpg.display_name(a, g.get("mode") or "full") if a else (g.get("name") or "Your group")
    face = mpn._face({**a, "name": name}, "lf-face") if a else _church_face(biz, g.get("name") or "")
    who = f'{_e(name)} <i>in</i> {_e(g.get("name") or "Your group")}' if a else _e(g.get("name") or "Your group")
    board = f"/my/groups/{item['group_id']}/board"
    head = _head(face, who, mpn.when_label(biz, item.get("at"), tz=tz[0]), board, f"Open {g.get('name') or 'the group'}")
    title, body = (item.get("title") or "").strip(), (item.get("body") or "").strip()
    words = (f'<div class="lf-txt">{f"<b class=lf-t>{_e(title)}</b>" if title else ""}'
             f'{f"<p>{_e(body)}</p>" if body else ""}</div>')
    return (f'<article class="lf-post lf-pgp" id="gpo-{_e(item["id"])}" aria-label="A post in {_e(g.get("name") or "your group")}">'
            f'{head}{words}<div class="lf-btns"><a class="lf-pill" href="{board}">{_i("users", "xs")}'
            f'Open {_e(g.get("name") or "the group")}</a></div></article>')


# ─── the block ───────────────────────────────────────────────────────


def _caught() -> str:
    return (f'<div class="lf-done"><span class="lf-ok">{_i("check")}</span><b>You\'re all caught up</b></div>'
            f'<p class="lf-older">Earlier</p>')


def _group_items(extras: Optional[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """The newest `n` of the member's group items, prayers and Board posts
    together: [{kind, item, at}]."""
    if not extras:
        return []
    got = ([{"kind": "prayer", "item": x, "at": x.get("at")} for x in extras.get("prayers") or []]
           + [{"kind": "gpost", "item": x, "at": x.get("at")} for x in extras.get("posts") or []])
    got.sort(key=lambda x: _stamp(x["at"]), reverse=True)
    return got[:n]


def _stamp(v: Any) -> float:
    t = _ts(v)
    return t.timestamp() if t else 0.0


def _order(posts: List[Dict[str, Any]], items: Optional[List[Dict[str, Any]]] = None) -> List[Any]:
    """Pinned first, then what this member hasn't opened (and the group
    items and the message newer than what they have), "You're all caught
    up", then the rest. No line when it can't be told (the seen read failed)
    or there's nothing on one side of it. `items`: [{kind, item, at}]."""
    items = list(items or [])

    def at(x: Any) -> float:
        return _stamp(x["at"] if isinstance(x, dict) and "kind" in x and "item" in x else _when(x))
    pinned = [p for p in posts if p.get("pinned")]
    rest = [p for p in posts if not p.get("pinned")]
    if any(p.get("seen") is None for p in posts):
        return pinned + sorted(rest + items, key=at, reverse=True)
    new, old = [p for p in rest if not p["seen"]], [p for p in rest if p["seen"]]
    top = max((at(p) for p in old), default=0.0)
    fresh = [x for x in items if not top or at(x) > top]
    stale = [x for x in items if x not in fresh]
    if old and (new or fresh or any(not p["seen"] for p in pinned)):
        return pinned + sorted(new + fresh, key=at, reverse=True) + ["caught"] + sorted(old + stale, key=at, reverse=True)
    return pinned + sorted(rest + items, key=at, reverse=True)


def composer(me: Optional[Dict[str, Any]]) -> str:
    """"Share a praise or a prayer…" with the member's face: Share good news
    (/my/news/share, member_portal_share), then a thin band."""
    import member_app_ui as ui
    import member_photos as ph
    mine = ph.src(me) if me else ""
    face = (f'<span class="lf-cface"><img src="{_e(mine)}" alt=""></span>' if mine
            else f'<span class="lf-cface" aria-hidden="true">{_e(ui.initials((me or {}).get("name")))}</span>')
    return (f'<div class="lf-comp">{face}<a class="lf-comp-in" href="/my/news/share">Share a praise or a prayer…</a>'
            f'<a class="lf-comp-ph" href="/my/news/share" aria-label="Add a photo">{_i("image")}</a></div>'
            f'<div class="lf-band" aria-hidden="true"></div>')


def see_all(total: Optional[int]) -> str:
    """Under Home's posts: a quiet row to the all-posts page (News), with how
    many posts it lists when that is known (church_news.home_view's count,
    from Home's own read) and more than Home shows."""
    n = int(total) if isinstance(total, int) and total > 4 else 0
    said = f"See all {n} posts" if n else "See all posts"
    count = f'<small aria-hidden="true">{n}</small>' if n else ""
    return (f'<a class="lf-see" href="/my/news" aria-label="{said}"><span>See all posts</span>{count}'
            f'{_i("chevron", "xs")}</a>')


def home_feed(biz: Dict[str, Any], site, posts: Optional[List[Dict[str, Any]]], occ, open_: bool,
              rights: Optional[Dict[str, Any]] = None, *, me: Optional[Dict[str, Any]] = None,
              new_n: Optional[int] = None, total: Optional[int] = None, extras: Optional[Dict[str, Any]] = None,
              library: Optional[Dict[str, Any]] = None, today: Optional[date] = None) -> str:
    """Home's feed in the new look. Nothing when the news couldn't be read;
    with no news and nothing from the groups yet, a poster sees where it
    will go. `extras`: the member's group items (member_feed_more.gather);
    `library`: Home's sermon library, for the newest message. Under the
    posts, See all posts (`total`: how many there are)."""
    import group_gatherings as gg
    import member_app_photos as photos
    import member_feed_more as fm
    import member_lumen_ui as lm
    import member_portal_news as mpn
    from member_portal import palette_for
    if posts is None:
        return ""
    # Whether the newest message is still new, by the day as UTC sees it (the
    # church's clock is a read, made below only when there is a feed to draw).
    from datetime import timezone
    msg = fm.message_of(library, today or datetime.now(timezone.utc).date())
    if msg and any(str((p.get("sermon") or {}).get("id") or "") == str(msg["id"]) for p in posts):
        msg = None                                                    # a post already carries it
    items = _group_items(extras, fm.SHOWN)
    if msg:
        items.append({"kind": "message", "item": msg, "at": f"{msg.get('preached_on')}T12:00:00+00:00"})
    if not posts and not items:
        rights = rights or {}
        groups = rights.get("groups") or []
        if rights.get("church"):
            title, sub = "Post the church's first news", f"Everyone at {(biz.get('name') or '').strip() or 'your church'} sees it here, on Home"
        elif groups:
            title, sub = ("Post news for your group" if len(groups) == 1 else "Post news for your groups"), "They see it here, on Home"
        else:
            return ""
        return (f'<section class="lm-feed" aria-labelledby="lm-feed-h">{_sr_head(biz)}'
                f'{lm.row("/my/news/write", lm.round_icon("megaphone"), title, sub, cls="lm-pray")}</section>')
    by = mpn._occasions(occ)
    pool = photos.photos(biz, site)
    pal = palette_for(biz, site)
    used: set = set()
    saved = set(fm.saved_ids(me))
    # The church's clock, once for every label on the feed (it is a read).
    tz = (gg.zone(biz),)
    today = today or (datetime.now(tz[0]).date() if tz[0] else date.today())
    groups = (extras or {}).get("groups") or {}
    out = []
    for x in _order(posts, items):
        if x == "caught":
            out.append(_caught())
        elif isinstance(x, dict) and x.get("kind") == "message" and "item" in x:
            out.append(message_card(biz, site, library or {}, x["item"], pal, pool, used, today))
        elif isinstance(x, dict) and x.get("kind") == "prayer" and "item" in x:
            out.append(prayer_card(biz, x["item"], groups, tz=tz))
        elif isinstance(x, dict) and x.get("kind") == "gpost" and "item" in x:
            out.append(group_post_card(biz, x["item"], groups, tz=tz))
        else:
            out.append(card(biz, x, by, open_=open_, me=me or {}, pool=pool, used=used, tz=tz, site=site,
                            lib=library, pal=pal, saved=saved))
    more = see_all(total) if posts else ""
    return (f'<section class="lm-feed" aria-labelledby="lm-feed-h">{_sr_head(biz)}{composer(me)}'
            f'<div class="lf-list">{"".join(out)}</div>{more}</section>{JS}')


def _sr_head(biz: Dict[str, Any]) -> str:
    import member_portal_church as mpc
    short = mpc._short_name((biz.get("name") or "").strip()) or "your church"
    return f'<h2 class="mp-sr" id="lm-feed-h">What&#x27;s happening at {_e(short)}</h2>'


# ─── the all-posts page ──────────────────────────────────────────────


def page_href(filt: str = "", page: int = 1) -> str:
    """The all-posts page's address: /my/news, with its filter and page."""
    q = [f"f={filt}"] if filt else []
    if page > 1:
        q.append(f"page={page}")
    return "/my/news" + ("?" + "&".join(q) if q else "")


def _today(people: List[Dict[str, Any]]) -> str:
    """Today's birthdays and anniversaries, together (News' "Today we
    celebrate"), each opening its own page of wishes."""
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
            face = (f'<span class="lf-pair">{mpn._face(p.get("person") or {}, "lf-face")}'
                    f'{mpn._face(p.get("partner") or {}, "lf-face")}</span>')
        else:
            small = "Happy birthday" + (f" · {n} wish{'' if n == 1 else 'es'} so far" if n else "")
            act, face = "Wish them well", mpn._face(p.get("person") or {}, "lf-face")
        rows.append(f'<a class="lf-prow-p" href="/my/news/{_e(p["id"])}">{face}<span class="lf-prow-t">'
                    f'<b>{_e(mcl.full_name(p))}</b><small>{_e(small)}</small></span><span class="lf-prow-go">{act}</span></a>')
    return (f'<article class="lf-post lf-today" aria-label="Today we celebrate"><p class="lf-kick">Today we celebrate</p>'
            f'{"".join(rows)}<p class="lf-note">Shown because they said yes</p></article>')


def all_posts(biz: Dict[str, Any], site, request: Any, me: Dict[str, Any], got: Optional[Dict[str, Any]],
              filt: str, occ, open_: bool, poster: bool = False, library: Optional[Dict[str, Any]] = None):
    """The News page in the new look, opened from Home's See all posts: the
    heading and filters as before, then the posts as Home draws them, ten at
    a time (church_news.feed_page), with Show more, a plain link to the next
    ten. Back goes Home. (html, status)."""
    import church_news as cn
    import group_gatherings as gg
    import member_app_photos as photos
    import member_feed_more as fm
    import member_portal_news as mpn
    import member_portal_share as mps
    from member_portal import _shell, palette_for
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
    pal = palette_for(biz, site)
    used: set = set()
    saved = set(fm.saved_ids(me))
    # The church's clock, once for every label on the page (it is a read).
    tz = (gg.zone(biz),) if posts else (None,)

    def one(p: Dict[str, Any]) -> str:
        return card(biz, p, by, open_=open_, me=me, pool=pool, used=used, tz=tz, back=back, site=site, lib=library,
                    pal=pal, saved=saved)
    cards = "".join(one(p) for p in posts if p.get("pinned"))
    cards += _today(people)
    cards += "".join(one(p) for p in posts if not p.get("pinned"))
    earlier = ""
    if page > 1:
        earlier = f'<p class="lf-page"><span>Earlier posts</span><a href="{page_href(filt)}">Back to the newest</a></p>'
    if not cards:
        if page > 1:
            empty = f'That&#x27;s every post. <a href="{page_href(filt)}">Back to the newest</a>'
        else:
            empty = _e("Nothing from your church yet. When your pastors post, it shows here." if not filt
                       else "Nothing here yet. Try All.")
        cards = f'<p class="nw-empty">{empty}</p>'
    more = ""
    if got.get("more"):
        more = (f'<a class="lf-see lf-next" href="{_e(page_href(filt, page + 1))}"><span>Show more</span>'
                f'{_i("down", "xs")}</a>')
    foot = (f'<p class="nw-foot">{_ic("lock", 16)}<span>Only your pastors and the leaders they name can post here. '
            f'{"Everyone can react and comment, and every comment is checked before anyone sees it." if open_ else "Everyone can react."}'
            f'</span></p>')
    body = (f'{head}<nav class="nw-filter" aria-label="Show">{chips}</nav>{mpn._flash(request)}{earlier}'
            f'<div class="lf-list lf-page-list" id="lm-flist">{cards}</div>{more}{mps.share_card()}{foot}')
    title = "News" if page == 1 else f"News, page {page}"
    return _shell(biz, site, title, f'<style>{mpn.NEWS_CSS}</style><div class="lm-nwpage">{body}</div>',
                  tab="news", who=me, script=mpn.RX_JS + (JS if posts else "")), 200


def saved_page(biz: Dict[str, Any], site, request: Any, me: Dict[str, Any], posts: Optional[List[Dict[str, Any]]],
               occ, open_: bool, library: Optional[Dict[str, Any]] = None):
    """Saved posts (/my/news/saved, from Me): the posts this member saved,
    newest saved first, as the feed draws them; Save again takes one off.
    (html, status)."""
    import group_gatherings as gg
    import member_app_photos as photos
    import member_feed_more as fm
    import member_portal_news as mpn
    from member_portal import _shell, palette_for
    head = ('<header class="lm-mast lm-nwhead"><p class="lm-eyebrow">Yours</p>'
            '<h1 class="lm-disp">Saved <em>posts</em></h1></header>')
    if posts is None:
        body = f'{head}<p class="mp-err" role="alert">Your saved posts couldn\'t load just now. Please try again in a moment.</p>'
        return _shell(biz, site, "Saved posts", f'<div class="lm-nwpage">{body}</div>', tab="me", who=me,
                      back=("/my/me", "Me")), 503
    by = mpn._occasions(occ)
    pool = photos.photos(biz, site) if posts else []
    pal = palette_for(biz, site)
    used: set = set()
    tz = (gg.zone(biz),) if posts else (None,)
    saved = {str(p["id"]) for p in posts}
    cards = "".join(card(biz, p, by, open_=open_, me=me, pool=pool, used=used, tz=tz, back="/my/news/saved", site=site,
                         lib=library, pal=pal, saved=saved) for p in posts)
    if not cards:
        cards = ('<p class="nw-empty">Nothing saved yet. Tap the bookmark on a post and it waits for you here.</p>')
    body = f'{head}{mpn._flash(request)}<div class="lf-list lf-page-list">{cards}</div>'
    return _shell(biz, site, "Saved posts", f'<style>{mpn.NEWS_CSS}</style><div class="lm-nwpage">{body}</div>',
                  tab="me", who=me, back=("/my/me", "Me"), script=mpn.RX_JS + (JS if posts else "")), 200


# ─── the script ──────────────────────────────────────────────────────
# A comment: the write pill posts to /my/news/comment asking for JSON (the
# route's answer for a fetch): "Checking…" at once, then the server's own
# line, or its held or crisis words under the box; a refusal or a lost
# answer puts the words back with why. Save and "I prayed" answer at once
# and go in the background (JSON), and turn back if they didn't save.
# Double-tap a photo: Love it (once; a second double-tap doesn't take it
# back), with one soft heart; the phone's reduced motion keeps it still.
JS = r"""<script>(function(){
var d=document;if(!window.fetch||!window.FormData||!window.URLSearchParams||!('content' in d.createElement('template')))return;
function el(t,c,x){var e=d.createElement(t);if(c)e.className=c;if(x!=null)e.textContent=x;return e;}
function fit(t){t.style.height='auto';t.style.height=Math.min(t.scrollHeight,140)+'px';}
d.addEventListener('input',function(e){var t=e.target;if(t&&t.matches&&t.matches('.lf-cw textarea'))fit(t);});
function say(f,text,cls,role){var s=f.parentNode.querySelector('.lf-cw-say');if(!s)return;s.className='lf-cw-say'+(cls?' '+cls:'');
  s.setAttribute('role',role||'status');s.textContent=text;s.hidden=!text;}
function post(f){return fetch(f.getAttribute('action'),{method:'POST',credentials:'same-origin',
  headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams(new FormData(f)).toString()})
  .then(function(r){return r.json().then(function(x){return x;},function(){return null;});},function(){return null;});}
d.addEventListener('submit',function(e){var f=e.target;if(!f||!f.matches)return;
  if(f.matches('form.lf-savef,form.lf-prayf')){e.preventDefault();var b=f.querySelector('button');if(!b||b.disabled)return;
    var was=b.getAttribute('aria-pressed')==='true';b.setAttribute('aria-pressed',was?'false':'true');b.disabled=true;
    post(f).then(function(x){b.disabled=false;
      if(x&&x.ok){if(typeof x.saved==='boolean')b.setAttribute('aria-pressed',x.saved?'true':'false');
        else if(x.code)b.setAttribute('aria-pressed',x.code==='praying'?'true':'false');}
      else{b.setAttribute('aria-pressed',was?'true':'false');}});return;}
  if(!f.matches('form.lf-cw'))return;e.preventDefault();
  var t=f.querySelector('textarea'),v=(t.value||'').replace(/^\s+|\s+$/g,'');if(!v||f.getAttribute('data-sending'))return;
  var card=f.closest('.lf-post'),list=card.querySelector('.lf-cms');say(f,'');
  var p=new URLSearchParams(new FormData(f));
  var li=el('div','lf-cm mine checking'),line=el('p');line.appendChild(el('b',null,'You'));line.appendChild(d.createTextNode(' '));
  line.appendChild(el('span',null,v));li.appendChild(line);li.appendChild(el('span','lf-cmeta','Checking…'));
  list.appendChild(li);t.value='';fit(t);f.setAttribute('data-sending','1');
  fetch(f.getAttribute('action'),{method:'POST',credentials:'same-origin',
    headers:{'Accept':'application/json','Content-Type':'application/x-www-form-urlencoded'},body:p.toString()})
  .then(function(r){return r.json().then(function(x){return x;},function(){return null;});},function(){return null;})
  .then(function(x){f.removeAttribute('data-sending');
    if(x&&x.ok){var tp=d.createElement('template');tp.innerHTML=x.html||'';var n=tp.content.firstElementChild;
      if(n&&li.parentNode){n.classList.add('rise');li.parentNode.replaceChild(n,li);}else{li.classList.remove('checking');}
      if(x.code==='commented'){var m=card.querySelector('.lf-vall');
        if(m){m.textContent='View all '+((parseInt(m.textContent.replace(/\D+/g,''),10)||0)+1)+' comments';}}
      if(x.notice)say(f,x.notice,x.code==='care'?'care':'',x.code==='care'?'alert':'status');}
    else{if(li.parentNode)li.parentNode.removeChild(li);t.value=v+(t.value?'\n'+t.value:'');fit(t);
      say(f,(x&&x.error)||"That didn't go through. Check your connection, then try again.",'err','alert');}});});
var still=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches,last=null;
function love(box){var card=box.closest('.lf-post');if(!card)return;
  var b=card.querySelector('.lf-act.lv');if(b&&b.getAttribute('aria-pressed')!=='true'){var f=b.form;
    if(f.requestSubmit)f.requestSubmit();else f.dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}));}
  var h=box.querySelector('.lf-heart');if(!h)return;h.classList.remove('go','calm');void h.offsetWidth;h.classList.add(still?'calm':'go');}
d.addEventListener('pointerup',function(e){var box=e.target.closest&&e.target.closest('.lf-dbl');if(!box||e.pointerType==='mouse')return;
  if(e.target.closest('a'))return;var now=Date.now();
  if(last&&last.box===box&&now-last.t<320&&Math.abs(e.clientX-last.x)<30&&Math.abs(e.clientY-last.y)<30){last=null;love(box);}
  else{last={box:box,t:now,x:e.clientX,y:e.clientY};}});
d.addEventListener('dblclick',function(e){var box=e.target.closest&&e.target.closest('.lf-dbl');if(!box||e.target.closest('a'))return;
  e.preventDefault();love(box);});
d.addEventListener('animationend',function(e){var h=e.target;if(h.classList&&h.classList.contains('lf-heart'))h.classList.remove('go','calm');});
})();</script>"""


CSS = Template("""
/* Home's feed, Look 5.1: one stream, posts edge to edge (member_lumen_feed) */
.lm .lm-feed{margin:36px -20px 0;}
.lm .lf-ic{width:24px;height:24px;flex:none;display:block;fill:none;stroke:currentColor;stroke-width:1.75;stroke-linecap:round;
  stroke-linejoin:round;}
.lm .lf-ic.s{width:19px;height:19px;}
.lm .lf-ic.xs{width:15px;height:15px;stroke-width:2;}
.lm .lf-ic.f{fill:currentColor;stroke:none;}
/* "Share a praise or a prayer…", then a thin band */
.lm .lf-comp{display:flex;align-items:center;gap:10px;padding:4px 8px 16px 20px;}
.lm .lf-cface{width:40px;height:40px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:var(--s2);
  color:var(--fg2);font:700 13px/1 var(--mb-ui);}
.lm .lf-cface img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lf-comp-in{flex:1;min-width:0;height:44px;border-radius:22px;background:var(--s1);display:flex;align-items:center;padding:0 16px;
  color:var(--fg3);font:400 15px/1 var(--mb-ui);text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm .lf-comp-ph{width:44px;height:44px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--fg);}
.lm .lf-band{height:8px;background:var(--s1);}
/* a post: no frame, a hairline between */
.lm .lf-post{display:block;padding:0 0 20px;scroll-margin-top:76px;}
.lm .lf-post+.lf-post{border-top:1px solid var(--lm-line);}
.lm .lf-ph{display:flex;align-items:center;gap:10px;padding:12px 4px 10px 20px;}
.lm .lf-ph .lm-logo{width:36px;height:36px;font-size:14px;}
.lm .lf-face{width:36px;height:36px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:var(--s2);
  color:var(--fg2);font:650 12px/1 var(--mb-ui);}
.lm .lf-face img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lf-who{flex:1;min-width:0;}
.lm .lf-who b{display:block;font:700 14.5px/1.25 var(--mb-ui);color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.lm .lf-who b i{font-style:normal;font-weight:500;color:var(--fg3);}
.lm .lf-who small{display:block;margin-top:1px;font:500 12.5px/1.25 var(--mb-ui);color:var(--fg3);}
.lm .lf-pin{flex:none;height:22px;padding:0 9px;border-radius:11px;background:var(--s1);color:var(--fg2);
  font:700 10px/22px var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;}
.lm .lf-more{width:44px;height:44px;flex:none;border-radius:50%;display:grid;place-items:center;color:var(--fg);}
/* photos edge to edge: one (a tall one stays tall), two side by side, an album */
.lm .lf-dbl{position:relative;touch-action:manipulation;-webkit-user-select:none;user-select:none;}
.lm .lf-pic{display:block;background:var(--s2);}
.lm .lf-pic img{display:block;width:100%;height:auto;min-height:180px;max-height:488px;object-fit:cover;filter:saturate(.95);}
.lm .lf-pic.tall img{aspect-ratio:4/5;}
.lm .lf-alb{display:grid;grid-template-columns:2fr 1fr;grid-template-rows:118px 118px;gap:2px;}
.lm .lf-alb.two{grid-template-columns:1fr 1fr;grid-template-rows:236px;}
.lm .lf-cell{position:relative;display:block;overflow:hidden;background:var(--s2);}
.lm .lf-alb:not(.two) .lf-cell:first-child{grid-row:1/span 2;}
.lm .lf-cell img{display:block;width:100%;height:100%;object-fit:cover;filter:saturate(.95);}
.lm .lf-plus{position:absolute;inset:0;display:grid;place-items:center;background:rgba(0,0,0,.42);color:#fff;font:650 18px/1 var(--mb-ui);}
.lm .lf-heart{position:absolute;left:50%;top:50%;width:76px;height:76px;margin:-38px 0 0 -38px;opacity:0;pointer-events:none;color:#fff;
  filter:drop-shadow(0 4px 16px rgba(0,0,0,.28));}
.lm .lf-heart .lf-ic{width:76px;height:76px;fill:currentColor;stroke:currentColor;stroke-width:1;}
/* the words */
.lm .lf-txt{padding:0 20px 12px;}
.lm .lf-txt .lf-t{display:block;margin-bottom:4px;font:650 16px/1.3 var(--mb-ui);color:var(--fg);overflow-wrap:anywhere;}
.lm .lf-txt p{margin:0;font:400 15px/1.5 var(--mb-ui);color:var(--fg);white-space:pre-line;overflow-wrap:anywhere;text-wrap:pretty;
  display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lf-q{display:-webkit-box;margin:0;font-family:var(--lm-read,var(--mb-serif));font-style:italic;font-size:19px;line-height:1.45;quotes:none;
  color:var(--fg);white-space:pre-line;overflow-wrap:anywhere;-webkit-line-clamp:7;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lf-cap{margin:0;padding:4px 20px 0;font:400 14.5px/1.45 var(--mb-ui);color:var(--fg);white-space:pre-line;overflow-wrap:anywhere;
  text-wrap:pretty;display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lf-cap b{font-weight:700;}
.lm .lf-cap .lf-t{font-weight:600;}
/* the icons: Love, Praying, Comment; Save at the right */
.lm .lf-acts{display:flex;align-items:center;padding:4px 10px 0;}
.lm .lf-acts form{display:flex;}
.lm .lf-acts .lf-savef{margin-left:auto;}
.lm .lf-act{width:44px;height:44px;flex:none;padding:0;border:0;border-radius:50%;background:none;display:grid;place-items:center;
  color:var(--fg);cursor:pointer;}
.lm .lf-act[aria-pressed=true]{color:var(--acc);}
.lm .lf-act.lv[aria-pressed=true] .lf-ic,.lm .lf-act.sv[aria-pressed=true] .lf-ic{fill:currentColor;}
.lm .lf-act.pr[aria-pressed=true] .lf-ic{fill:var(--lm-tint-12);}
.lm .lf-likes{margin:0;padding:0 20px;font:400 14.5px/1.4 var(--mb-ui);color:var(--fg);}
.lm .lf-likes b{font-weight:700;}
.lm .lf-likes span{color:var(--fg2);}
/* the newest comment, View all, the write pill */
.lm .lf-under{padding:0 20px;}
.lm .lf-vall{display:inline-block;padding:6px 0 0;font:400 14.5px/1.4 var(--mb-ui);color:var(--fg3);text-decoration:none;}
.lm .lf-cms{display:flex;flex-direction:column;gap:6px;}
.lm .lf-cms:not(:empty){margin-top:3px;}
.lm .lf-cm{scroll-margin-top:90px;}
.lm .lf-cm p{margin:0;font:400 14.5px/1.45 var(--mb-ui);color:var(--fg);white-space:pre-line;overflow-wrap:anywhere;
  display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lf-cm p b{font-weight:700;}
.lm .lf-cm.held p{color:var(--fg2);}
.lm .lf-cmeta{display:flex;align-items:center;gap:6px;margin-top:2px;font:500 12px/1.3 var(--mb-ui);color:var(--fg3);}
.lm .lf-cw{display:flex;align-items:flex-end;gap:10px;margin-top:10px;}
.lm .lf-cw-me{width:28px;height:28px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;background:var(--s2);
  color:var(--fg2);font:700 10px/1 var(--mb-ui);}
.lm .lf-cw-me img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lf-cw-in{flex:1;min-width:0;display:flex;}
.lm .lf-cw textarea{flex:1;min-width:0;min-height:28px;max-height:140px;margin:0;padding:4px 0;border:0;outline:none;background:transparent;
  resize:none;font:400 16px/1.25 var(--mb-ui);color:var(--fg);}
.lm .lf-cw textarea::placeholder{color:var(--fg3);opacity:1;font-size:14.5px;}
.lm .lf-cw-go{width:30px;height:30px;flex:none;padding:0;border:0;border-radius:50%;display:grid;place-items:center;background:var(--acc-fill);
  color:var(--on-acc);cursor:pointer;}
.lm .lf-cw:not(:focus-within):has(textarea:placeholder-shown) .lf-cw-go{display:none;}
.lm .lf-cw-safe{display:none;align-items:center;gap:6px;margin:8px 0 0;font:500 12px/1.3 var(--mb-ui);color:var(--fg3);}
.lm .lf-cw:focus-within+.lf-cw-safe,.lm .lf-cw:has(textarea:not(:placeholder-shown))+.lf-cw-safe{display:flex;}
.lm .lf-cw-say{margin:10px 0 0;padding:10px 12px;border-radius:14px;background:var(--s1);font:500 13px/1.45 var(--mb-ui);color:var(--fg2);}
.lm .lf-cw-say[hidden]{display:none;}
.lm .lf-cw-say.care,.lm .lf-cw-say.err{color:var(--fg);}
.lm .lf-cw-say.care{box-shadow:inset 3px 0 0 var(--acc-fill);}
.lm .lf-note{display:flex;align-items:center;gap:7px;margin:10px 0 0;font:500 13px/1.4 var(--mb-ui);color:var(--fg3);}
.lm .lf-note .lf-ic{flex:none;}
/* pills: Watch · Listen · Share, Going, the way to a group */
.lm .lf-btns{display:flex;flex-wrap:wrap;gap:8px;padding:14px 20px 0;}
.lm .lf-btns form{display:flex;}
.lm .lf-pill{height:38px;padding:0 16px;border-radius:19px;display:inline-flex;align-items:center;justify-content:center;gap:7px;
  border:0;box-shadow:inset 0 0 0 1.5px var(--lm-line);background:var(--bg);color:var(--fg);font:650 14px/1 var(--mb-ui);
  text-decoration:none;white-space:nowrap;cursor:pointer;}
.lm .lf-pill.pri{background:var(--acc-fill);color:var(--on-acc);box-shadow:none;}
.lm .lf-pill.on{background:var(--lm-tint-12);color:var(--acc);box-shadow:none;}
.lm .lf-pill[aria-disabled=true]{color:var(--fg3);cursor:default;}
.lm .lf-kick{margin:0;font:700 11px/1.2 var(--mb-ui);letter-spacing:.12em;text-transform:uppercase;color:var(--fg3);}
/* a message: the 16:9 picture with its play disc, the title in serif */
.lm .lf-vid{position:relative;display:block;margin:0 20px;aspect-ratio:16/9;border-radius:16px;overflow:hidden;background:var(--s2);}
.lm .lf-vid>span:not(.lf-play),.lm .lf-vid .mb-art,.lm .lf-vid .mb-ph,.lm .lf-vid .mb-def{position:absolute;inset:0;width:100%;height:100%;
  border-radius:0;aspect-ratio:auto;}
.lm .lf-vid img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lf-play{position:absolute;left:50%;top:50%;z-index:2;width:58px;height:58px;margin:-29px 0 0 -29px;border-radius:50%;
  background:rgba(255,255,255,.94);display:grid;place-items:center;color:#111;box-shadow:0 6px 24px rgba(0,0,0,.2);}
.lm .lf-play .lf-ic{margin-left:3px;}
.lm .lf-msg,.lm .lf-ev{padding:14px 20px 0;}
.lm .lf-msg h3{margin:7px 0 4px;font-family:var(--mb-serif);font-size:25px;line-height:1.15;font-weight:var(--lm-dw,400);
  letter-spacing:var(--lm-dtr,-.015em);font-variation-settings:var(--lm-dvar,normal);font-stretch:var(--lm-dst,100%);color:var(--fg);
  text-wrap:balance;overflow-wrap:anywhere;}
.lm .lf-msg h3 a,.lm .lf-ev h3 a{color:inherit;text-decoration:none;}
.lm .lf-msg p:not(.lf-kick),.lm .lf-ev p:not(.lf-kick){margin:0;font:400 14px/1.4 var(--mb-ui);color:var(--fg2);}
/* an event: its picture framed, the date on a leaf */
.lm .lf-evimg{position:relative;display:block;margin:0 20px;height:186px;border-radius:16px;overflow:hidden;background:var(--s2);}
.lm .lf-evimg img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lf-leaf{position:absolute;left:12px;top:12px;width:46px;padding:6px 0 7px;border-radius:12px;background:var(--bg);text-align:center;
  box-shadow:0 2px 10px rgba(0,0,0,.14);}
.lm .lf-leaf small{display:block;font:750 10px/1 var(--mb-ui);letter-spacing:.12em;color:var(--acc);}
.lm .lf-leaf b{display:block;margin-top:3px;font-family:var(--mb-serif);font-size:21px;line-height:1.05;font-weight:500;color:var(--fg);}
.lm .lf-evbare{position:relative;display:block;margin:0 20px;height:62px;}
.lm .lf-evbare .lf-leaf{left:0;top:0;box-shadow:inset 0 0 0 1px var(--lm-line);}
.lm .lf-ev h3{margin:7px 0 4px;font:650 19px/1.25 var(--mb-ui);letter-spacing:-.012em;color:var(--fg);}
.lm .lf-ev .lf-evb{margin-top:6px;color:var(--fg);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lf-event+.lf-acts{margin-top:6px;}
.lm .lf-link{display:flex;align-items:center;gap:12px;margin:12px 20px 0;padding:10px 12px;border-radius:14px;background:var(--s1);
  color:var(--fg);text-decoration:none;}
.lm .lf-link-i{width:38px;height:38px;flex:none;border-radius:11px;display:grid;place-items:center;background:var(--bg);color:var(--fg);}
.lm .lf-link-t{flex:1;min-width:0;}
.lm .lf-link-t b{display:block;font:650 14.5px/1.25 var(--mb-ui);}
.lm .lf-link-t span{display:block;margin-top:2px;font:400 12.5px/1.3 var(--mb-ui);color:var(--fg2);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
.lm .lf-link>.lf-ic:last-child{color:var(--fg3);}
/* a prayer request: the soft panel, the words in serif, I prayed */
.lm .lf-pray{margin:0 20px;padding:18px 18px 16px;border-radius:18px;background:var(--s1);}
.lm .lf-pray .lf-kick{color:var(--acc);}
.lm .lf-say{margin:10px 0 16px;font-family:var(--lm-read,var(--mb-serif));font-size:19px;line-height:1.45;color:var(--fg);
  white-space:pre-line;overflow-wrap:anywhere;text-wrap:pretty;}
.lm .lf-prow{display:flex;align-items:center;flex-wrap:wrap;gap:12px;}
.lm .lf-prayf{display:flex;}
.lm .lf-pbtn{height:42px;padding:0 18px;border:0;border-radius:21px;display:inline-flex;align-items:center;gap:8px;background:var(--bg);
  box-shadow:inset 0 0 0 1.5px var(--lm-line);color:var(--fg);font:700 14.5px/1 var(--mb-ui);cursor:pointer;}
.lm .lf-pbtn[aria-pressed=true]{background:var(--acc-fill);color:var(--on-acc);box-shadow:none;}
.lm .lf-pbtn .on,.lm .lf-pbtn[aria-pressed=true] .off{display:none;}
.lm .lf-pbtn[aria-pressed=true] .on{display:inline;}
.lm .lf-pn{display:inline-flex;align-items:center;gap:7px;font:400 13.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lf-pn .n1{display:none;}
.lm .lf-prow:has(.lf-pbtn[aria-pressed=true]) .lf-pn .n0{display:none;}
.lm .lf-prow:has(.lf-pbtn[aria-pressed=true]) .lf-pn .n1{display:inline;}
.lm .lf-faces{display:flex;}
.lm .lf-mini{width:24px;height:24px;flex:none;border-radius:50%;display:grid;place-items:center;overflow:hidden;margin-left:-7px;
  background:var(--s2);color:var(--fg2);font:700 9px/1 var(--mb-ui);box-shadow:0 0 0 2px var(--s1);}
.lm .lf-mini:first-child{margin-left:0;}
.lm .lf-mini img{display:block;width:100%;height:100%;object-fit:cover;}
.lm .lf-cpr form{display:flex;}
.lm .lf-pt{display:block;margin-top:10px;font:650 16px/1.3 var(--mb-ui);color:var(--fg);overflow-wrap:anywhere;}
.lm .lf-pt+.lf-say{margin-top:6px;}
.lm .lf-cpr .lf-say{display:-webkit-box;-webkit-line-clamp:7;-webkit-box-orient:vertical;overflow:hidden;}
.lm .lf-cpr .lf-kick+.lf-prow{margin-top:12px;}
.lm .lf-event+.lf-pray,.lm .lf-pic+.lf-pray,.lm .lf-alb+.lf-pray{margin-top:14px;}
.lm .lf-pray+.lf-acts{margin-top:6px;}
/* caught up, then Earlier */
.lm .lf-done{display:flex;flex-direction:column;align-items:center;gap:12px;padding:36px 20px 8px;text-align:center;
  border-top:1px solid var(--lm-line);}
.lm .lf-ok{width:52px;height:52px;border-radius:50%;display:grid;place-items:center;box-shadow:inset 0 0 0 2px var(--acc-fill);color:var(--acc);}
.lm .lf-done b{font:700 16px/1.2 var(--mb-ui);color:var(--fg);}
.lm .lf-older{display:flex;align-items:center;gap:12px;margin:22px 20px 0;padding-bottom:4px;font:650 11px/1 var(--mb-ui);
  letter-spacing:.14em;text-transform:uppercase;color:var(--fg3);}
.lm .lf-older::before,.lm .lf-older::after{content:"";flex:1;height:1px;background:var(--lm-line);}
.lm .lf-older+.lf-post{border-top:0;}
/* See all posts under Home's; Show more on the all-posts page */
.lm .lf-see{display:flex;align-items:center;gap:10px;min-height:52px;margin:6px 20px 0;padding:0 14px 0 18px;border-radius:18px;
  background:var(--bg);box-shadow:inset 0 0 0 1px var(--lm-line);color:var(--fg);text-decoration:none;}
.lm .lf-see span{flex:1;min-width:0;font:650 14.5px/1.2 var(--mb-ui);}
.lm .lf-see small{flex:none;font:500 13.5px/1 var(--mb-ui);color:var(--fg3);font-variant-numeric:tabular-nums;}
.lm .lf-see .lf-ic{color:var(--fg3);}
.lm .lf-see:active{background:var(--s1);}
.lm .lf-next{justify-content:center;gap:8px;margin:20px 0 0;}
.lm .lf-next span{flex:none;}
/* the all-posts and saved pages: the same posts, edge to edge */
.lm .lf-page-list{margin:14px -20px 0;border-top:1px solid var(--lm-line);}
.lm .lf-page-list>.nw-empty{margin:14px 20px 0;}
.lm .lf-page-list>.nw-empty a{color:var(--acc);font-weight:650;text-decoration:none;}
.lm .lf-page{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin:20px 0 0;
  font:650 11px/1.2 var(--mb-ui);letter-spacing:.14em;text-transform:uppercase;color:var(--fg3);}
.lm .lf-page a{font:650 13px/1.2 var(--mb-ui);letter-spacing:0;text-transform:none;color:var(--acc);text-decoration:none;}
.lm .lf-today{padding-top:16px;}
.lm .lf-today>.lf-kick{padding:0 20px 4px;color:var(--acc);}
.lm .lf-today>.lf-note{margin:4px 20px 0;}
.lm .lf-prow-p{display:flex;align-items:center;gap:12px;padding:10px 20px;color:var(--fg);text-decoration:none;}
.lm .lf-prow-t{flex:1;min-width:0;}
.lm .lf-prow-t b{display:block;font:650 15px/1.25 var(--mb-ui);}
.lm .lf-prow-t small{display:block;margin-top:2px;font:500 12.5px/1.3 var(--mb-ui);color:var(--fg2);}
.lm .lf-prow-go{flex:none;font:650 13px/1 var(--mb-ui);color:var(--acc);}
.lm .lf-pair{display:flex;flex:none;}
.lm .lf-pair .lf-face+.lf-face{margin-left:-10px;box-shadow:0 0 0 2px var(--bg);}
@media (prefers-reduced-motion:no-preference){
  .lm .lf-act,.lm .lf-pbtn,.lm .lf-cw-go,.lm .lf-pill{transition:transform .3s cubic-bezier(.3,1.4,.5,1),color .2s,background-color .25s;}
  .lm .lf-act:active,.lm .lf-cw-go:active{transform:scale(.88);}
  .lm .lf-pbtn:active,.lm .lf-pill:active{transform:scale(.97);}
  .lm .lf-heart.go{animation:lfpop .9s cubic-bezier(.2,.9,.3,1.2) both;}
  .lm .lf-cm.checking p{opacity:.6;animation:lfbreathe 1.1s ease-in-out infinite alternate;}
  .lm .lf-cm.rise{animation:lfrise .45s cubic-bezier(.2,.8,.2,1) both;}
  .lm .lf-see{transition:background-color .2s;}
}
@media (prefers-reduced-motion:reduce){.lm .lf-heart.calm{animation:lffade .7s ease both;}}
@keyframes lfpop{0%{opacity:0;transform:scale(.5)}18%{opacity:.95;transform:scale(1.06)}32%{transform:scale(.97)}46%{transform:scale(1)}
  78%{opacity:.95}100%{opacity:0;transform:scale(1)}}
@keyframes lffade{0%{opacity:0}25%{opacity:.9}75%{opacity:.9}100%{opacity:0}}
@keyframes lfbreathe{to{opacity:.35}}
@keyframes lfrise{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.lm .lf-act:focus-visible,.lm .lf-cw-go:focus-visible,.lm .lf-pbtn:focus-visible,.lm .lf-see:focus-visible,.lm .lf-vall:focus-visible,
.lm .lf-more:focus-visible,.lm .lf-pill:focus-visible,.lm .lf-vid:focus-visible,.lm .lf-link:focus-visible,.lm .lf-comp-in:focus-visible,
.lm .lf-comp-ph:focus-visible,.lm .lf-prow-p:focus-visible,.lm .lf-page a:focus-visible,.lm .lf-msg h3 a:focus-visible,
.lm .lf-ev h3 a:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.lm .lf-cw:focus-within .lf-cw-in{box-shadow:0 1px 0 var(--acc-fill);}

/* posting from a phone (member_portal_write): its Comments and When choices in the new look */
.lm .wr-seg{border-radius:14px;}
.lm .wr-seg span{border-radius:11px;font-weight:650;}
.lm .wr-seg input:checked+span{background:var(--bg);color:var(--fg);box-shadow:0 1px 3px rgba(0,0,0,.12),0 0 0 .5px var(--lm-line);}
""")
