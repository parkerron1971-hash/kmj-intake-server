"""site_kit_church.py — the kit's sections for gathering and personal-brand pages
(2026-11-10, Kevin: "do all but start on these ones": Bulletin, Magazine, Leader,
Poster).

Same rules as site_kit: facts come only from the data (gatherings are checked
against what the data says, a leader's photo must be one of their own photos),
every section is whole at 390px, content is visible at rest, and a section with
no data is left out. These sections are composed into four layouts at the bottom.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List

from site_kit import (DAYS, _clock, _opt, _raw, board_object, dock, e, footer, hours_object,
                      proof, visit)

# ─── openings ─────────────────────────────────────────────────────────


def _ctas(d, w, second_label="", second_target="") -> str:
    cta = f'<a class="k-btn" href="{e(d["action_url"])}">{e(w["action_label"])}</a>' if d.get("action_url") else ""
    label = str(second_label or "").rstrip(" ↓→>").strip()
    second = f'<a class="k-link" href="#{e(second_target)}">{e(label)} &darr;</a>' if label and second_target else ""
    return f'<div class="k-ctas">{cta}{second}</div>' if cta or second else ""


def _when_card(d, w) -> str:
    """The card a first-time visitor needs above the fold: when and where."""
    rows = [f'<li><b>{e(g["day_label"])}</b><span>{e(g["time_label"])}</span><small>{e(g["label"])}</small></li>'
            for g in d["gatherings"][:4]]
    if d.get("address"):
        rows.append(f'<li class="k-when-where"><b>Where</b><span>{e(d["address"])}</span>'
                    f'<a class="k-link" href="{e(d["map_url"])}" rel="noopener" target="_blank">Directions &rarr;</a></li>')
    return f'<ul class="k-when">{"".join(rows)}</ul>' if rows else ""


def hero_poster(d, w) -> str:
    """The owner's own lines at poster size, their people set inside the words."""
    h = w.get("hero") or {}
    lines = [x for x in (h.get("lines") or []) if str(x).strip()][:4] or [d["name"]]
    insets = [u for u in (h.get("inset_photos") or []) if u in d["photo_urls"]][:2]
    accent = str(h.get("accent_word") or "").strip()
    out = []
    for i, line in enumerate(lines):
        txt = e(line)
        if accent and accent.lower() in line.lower():
            pat = re.compile(re.escape(e(accent)), re.IGNORECASE)
            txt = pat.sub(lambda m: f"<em>{m.group(0)}</em>", txt, count=1)
            accent = ""
        pic = ""
        if i < len(insets):
            pic = f' <span class="sxo-pw-pic"><img src="{e(insets[i])}" alt="" width="600" height="400"></span>'
        out.append(f'<span class="sxo-pw-line">{txt}{pic}</span>')
    ghost = _raw("span", "k-ghost r", e(h.get("ghost") or ""), hidden=True)
    return (f'<section class="k-hero k-hero-poster" id="top">{ghost}<div class="k-wrap">'
            f'{_opt("p", "k-eyebrow", h.get("eyebrow"))}'
            f'<div class="sxo sxo-pwords" data-sx-object="photo-words"><h1>{"".join(out)}</h1></div>'
            f'<div class="k-poster-foot"><div>{_opt("p", "k-lead", h.get("subhead"))}'
            f'{_opt("p", "k-hand", h.get("hand_line"))}</div>'
            f'<div>{_when_card(d, w)}{_ctas(d, w, h.get("secondary"), h.get("secondary_target") or "times")}</div>'
            f'</div></div></section>')


def hero_bulletin(d, w) -> str:
    """A noticeboard: the headline beside this week, on the felt board."""
    h = w.get("hero") or {}
    lines = [x for x in (h.get("lines") or []) if str(x).strip()][:3] or [d["name"]]
    from site_kit import _headline
    rows = [(g["day_label"].upper(), f'{g["time_label"]} · {g["label"]}'.upper()) for g in d["gatherings"][:6]]
    board = ""
    if rows:
        dd = dict(d, board_rows=rows)
        ww = dict(w, board={**(w.get("board") or {}), "board_title": h.get("board_title") or "This week",
                             "board_extra_rows": []})
        board = board_object(dd, ww, split_over=16)
    photo = d["photos"][0] if d["photos"] else None
    pic = (f'<img class="k-bulletin-photo" src="{e(photo["url"])}" alt="{e(photo.get("alt"))}" '
           f'fetchpriority="high">' if photo else "")
    side = f'<div class="k-bulletin-side{" has-photo" if pic else ""}">{pic}<div class="k-pinned">{board}</div></div>'
    glow = " k-glow" if d["tokens"]["glow"] else ""
    return (f'<section class="k-hero k-hero-bulletin{glow}" id="top"><div class="k-wrap"><div class="k-bulletin-grid">'
            f'<div class="k-hero-copy">{_opt("p", "k-eyebrow", h.get("eyebrow"))}'
            f'<h1 class="k-h1">{_headline(lines, h.get("accent_word") or "")}</h1>'
            f'{_opt("p", "k-lead", h.get("subhead"))}'
            f'{_ctas(d, w, h.get("secondary"), h.get("secondary_target") or "visit")}</div>'
            f'{side}</div></div></section>')


_TEASERS = (("leaders", "leaders", "head", "Meet our pastors"), ("story", "story", "headline", "Our story"),
             ("album", "album", "headline", "Our people"), ("events", "events", "headline", "Coming up"),
             ("times", "times", "headline", "When we gather"))


def hero_cover(d, w) -> str:
    """A magazine cover: the cover line set on the lead photo, and a contents rail
    that lists what's inside: the gatherings, the ministries, then the page's own
    sections, so it is never a short list beside empty space."""
    h = w.get("hero") or {}
    from site_kit import _headline
    lines = [x for x in (h.get("lines") or []) if str(x).strip()][:3] or [d["name"]]
    photo = d["photos"][0] if d["photos"] else None
    inside = []
    for g in d["gatherings"][:2]:
        inside.append(f'<li><span class="k-meta">{e(g["day_label"])}s &middot; {e(g["time_label"])}</span>'
                      f'<a href="#times"><b>{e(g["label"])}</b></a></li>')
    kicker = e((w.get("ministries") or {}).get("kicker") or "Ministry")
    for m in d["ministries"][:3]:
        inside.append(f'<li><span class="k-meta">{kicker}</span><a href="#ministries"><b>{e(m["name"])}</b></a></li>')
    for target, key, field, default in _TEASERS:
        if len(inside) >= 5:
            break
        if target in d.get("_present", set()) and not any(f'href="#{target}"' in x for x in inside):
            title = str((w.get(key) or {}).get(field) or "").strip() or default
            inside.append(f'<li><span class="k-meta">Inside</span><a href="#{target}"><b>{e(title)}</b></a></li>')
    rail = (f'<aside class="k-rail"><p class="k-eyebrow">{e(h.get("rail_title") or "In this issue")}</p>'
            f'<ol>{"".join(inside)}</ol></aside>' if inside else "")
    name = (w.get("wordmark") or {}).get("main") or d["name"]
    eyebrow = h.get("eyebrow") if name.lower() not in str(h.get("eyebrow") or "").lower() else ""
    copy = (f'<div class="k-cover-copy">{_opt("p", "k-eyebrow", eyebrow)}'
            f'<h1 class="k-h1">{_headline(lines, h.get("accent_word") or "")}</h1>'
            f'{_opt("p", "k-lead", h.get("subhead"))}{_ctas(d, w, h.get("secondary"), h.get("secondary_target") or "visit")}</div>')
    main = (f'<div class="k-cover-main has-photo"><img class="k-cover-img" src="{e(photo["url"])}" '
            f'alt="{e(photo.get("alt"))}" fetchpriority="high">{copy}</div>' if photo
            else f'<div class="k-cover-main">{copy}</div>')
    glow = " k-glow" if d["tokens"]["glow"] else ""
    return (f'<section class="k-hero k-hero-cover{glow}" id="top"><div class="k-wrap">'
            f'<div class="k-masthead"><span class="k-mast-name">{e(name)}</span>'
            f'{_opt("span", "k-mast-issue", h.get("issue_line"))}</div>'
            f'<div class="k-cover-grid">{main}{rail}</div></div></section>')


def hero_leader(d, w) -> str:
    """A personal brand's opening: the person, their name at billboard size."""
    h = w.get("hero") or {}
    leader = d["leaders"][0] if d["leaders"] else {"name": d["name"], "role": ""}
    alts = {p["url"]: p.get("alt") or "" for p in d["photos"]}
    photo_url = h.get("portrait") if h.get("portrait") in d["photo_urls"] else ""
    if photo_url and not shows_leader(alts.get(photo_url, ""), [leader]):
        photo_url = ""
    if not photo_url:
        photo_url = next((u for u, a in alts.items() if shows_leader(a, [leader])), "")
    alt = alts.get(photo_url) or leader["name"]
    pic = (f'<img class="k-leader-portrait" src="{e(photo_url)}" alt="{e(alt)}" fetchpriority="high">'
           if photo_url else "")
    glow = " k-glow" if d["tokens"]["glow"] else ""
    return (f'<section class="k-hero k-hero-leader{glow}" id="top"><div class="k-wrap"><div class="k-leader-grid">'
            f'<div class="k-hero-copy">{_opt("p", "k-eyebrow", h.get("eyebrow") or leader.get("role"))}'
            f'<h1 class="k-h1 k-leader-name">{e(leader["name"])}</h1>'
            f'{_opt("p", "k-leader-line", h.get("subhead"))}'
            f'{_ctas(d, w, h.get("secondary"), h.get("secondary_target") or "story")}</div>'
            f'<div class="k-leader-pic">{pic}</div></div></div></section>')


# ─── the middle ───────────────────────────────────────────────────────


def times(d, w) -> str:
    if not d["gatherings"]:
        return ""
    t = w.get("times") or {}
    items = []
    for g in d["gatherings"][:6]:
        hh, mm = g["time"].split(":")
        h12 = int(hh) % 12 or 12
        clock = f"{h12}:{mm}" if mm != "00" else f"{h12}"
        items.append(f'<li class="sxo-times-item" data-day="{g["day"]}" data-time="{g["time"]}">'
                     f'<span class="sxo-label">{e(g["day_label"])}</span><b>{clock}<small>{"am" if int(hh) < 12 else "pm"}</small></b>'
                     f'<span class="sxo-times-name">{e(g["label"])}</span><span class="sxo-times-next"></span></li>')
    tz = f' data-tz="{e(d["tz"])}"' if d.get("tz") else ""
    where = (f'<p class="k-note">{e(t.get("note") or "")}</p>' if t.get("note") else "")
    return (f'<section class="k-section k-times" id="times"><div class="k-wrap">'
            f'{_opt("p", "k-eyebrow", t.get("eyebrow"))}<h2 class="k-h2">{e(t.get("headline") or "When we gather")}</h2>'
            f'<div class="sxo sxo-times" data-sx-object="times-strip"{tz}>'
            f'{_strip_label(t)}'
            f'<ol class="sxo-times-row">{"".join(items)}</ol></div>{where}</div></section>')


def _strip_label(t: Dict[str, Any]) -> str:
    label = str(t.get("strip_label") or "").strip()
    said = {str(t.get(k) or "").strip().lower() for k in ("eyebrow", "headline")}
    if not label or label.lower() in said or any(label.lower() in x for x in said if x):
        return ""
    return f'<p class="sxo-times-head sxo-label">{e(label)}</p>'


def marquee(d, w) -> str:
    phrases = [str(x).strip() for x in (w.get("marquee") or []) if str(x).strip()][:8]
    if len(phrases) < 3:
        return ""
    lis = "".join(f"<li>{e(p)}</li>" for p in phrases)
    return (f'<div class="k-marquee"><div class="sxo sxo-marquee" data-sx-object="marquee">'
            f'<p class="sxo-sr">{e(". ".join(phrases))}.</p><div class="sxo-marquee-track" aria-hidden="true">'
            f'<ul class="sxo-marquee-run">{lis}</ul><ul class="sxo-marquee-run">{lis}</ul></div></div></div>')


def album(d, w) -> str:
    """Their own photos, with captions: never a stock picture, never a repeat."""
    a = w.get("album") or {}
    used = {u for u in ((w.get("hero") or {}).get("inset_photos") or [])}
    pics = [p for p in d["photos"] if p["url"] not in used] or d["photos"]
    if len(pics) < 3:
        return ""
    pics = pics[:max(n for n in (3, 6, 9) if n <= len(pics))]
    caps = a.get("captions") or {}
    figs = "".join(f'<figure><img src="{e(p["url"])}" alt="{e(p.get("alt"))}" loading="lazy">'
                   f'{_opt("figcaption", "", caps.get(p["url"]) or "")}</figure>' for p in pics)
    return (f'<section class="k-section k-album" id="album"><div class="k-wrap">'
            f'{_opt("p", "k-eyebrow", a.get("eyebrow"))}<h2 class="k-h2">{e(a.get("headline") or "Our people")}</h2>'
            f'<div class="k-album-grid n{len(pics)}">{figs}</div></div></section>')


def leaders(d, w) -> str:
    if not d["leaders"]:
        return ""
    lw = w.get("leaders") or {}
    names = " &amp; ".join(e(x["name"]) for x in d["leaders"][:2])
    role = d["leaders"][0].get("role") or ""
    photo = lw.get("photo") if lw.get("photo") in d["photo_urls"] else ""
    alt = next((p.get("alt") for p in d["photos"] if p["url"] == photo), "")
    if photo and not shows_leader(alt, d["leaders"]):
        photo, alt = "", ""
    img = f'<img src="{e(photo)}" alt="{e(alt)}" width="900" height="1100" loading="lazy">' if photo else ""
    link = (f'<a href="#{e(lw.get("link_target") or "visit")}">{e(lw.get("link_label"))}</a>'
            if lw.get("link_label") else "")
    return (f'<section class="k-section k-leaders" id="leaders"><div class="k-wrap">'
            f'<article class="sxo sxo-leader{"" if img else " k-no-photo"}" data-sx-object="leader-spotlight">'
            f'{_leader_head(lw)}'
            f'<div class="sxo-leader-body">{img}<div class="sxo-leader-panel">'
            f'{_opt("p", "sxo-label", lw.get("role_label") or role)}<h3>{names}</h3>'
            f'{_opt("p", "", lw.get("body"))}{link}</div></div></article></div></section>')


_LEADER_WORDS = ("pastor", "preach", "minister", "bishop", "founder", "owner", "coach", "speaker", "author",
                 "teacher", "leader", "host", "director")


def shows_leader(alt: str, people: List[Dict[str, Any]]) -> bool:
    """A leader's photo must be them: its description names them or their role."""
    low = str(alt or "").lower()
    names = [part.lower() for p in people for part in str(p.get("name") or "").split() if len(part) > 2]
    return bool(low) and (any(n in low for n in names) or any(x in low for x in _LEADER_WORDS))


def _leader_head(lw: Dict[str, Any]) -> str:
    head = str(lw.get("head") or "").strip()
    script = str(lw.get("head_script") or "").strip()
    if not head and not script:
        head, script = "Meet our", "pastors"
    if script and (script.lower() in head.lower() or len(script) > 24):
        script = ""
    tail = f' <span class="sxo-leader-script">{e(script)}</span>' if script else ""
    return f'<p class="sxo-leader-head">{e(head)}{tail}</p>'


def story(d, w) -> str:
    s = w.get("story") or {}
    paras = [p for p in (s.get("paragraphs") or []) if str(p).strip()][:3]
    if not paras:
        return ""
    polas = [p for p in (s.get("polaroids") or []) if isinstance(p, dict) and p.get("url") in d["photo_urls"]][:2]
    alts = {p["url"]: p.get("alt") or "" for p in d["photos"]}
    row = "".join(f'<figure class="sxo sxo-pola sxo-paper" data-sx-object="polaroid" data-overlap-ok>'
                  f'<span class="sxo-pola-tape" aria-hidden="true"></span>'
                  f'<img src="{e(p["url"])}" alt="{e(alts.get(p["url"]))}" width="600" height="600" loading="lazy">'
                  f'{_opt("figcaption", "", p.get("caption"))}</figure>' for p in polas)
    side = f'<div class="sxo-pola-row">{row}</div>' if row else ""
    ghost = _raw("span", "k-ghost l", e(s.get("ghost") or ""), hidden=True)
    return (f'<section class="k-section k-story" id="story">{ghost}<div class="k-wrap"><div class="k-story-grid{"" if side else " solo"}">'
            f'<div>{_opt("p", "k-eyebrow", s.get("eyebrow"))}<h2 class="k-h2">{e(s.get("headline") or "Our story")}</h2>'
            + "".join(f'<p class="k-story-p">{e(p)}</p>' for p in paras)
            + f'</div>{side}</div></div></section>')


def ministries(d, w) -> str:
    if not d["ministries"]:
        return ""
    m = w.get("ministries") or {}
    cards = []
    for i, x in enumerate(d["ministries"][:8]):
        meta = " &middot; ".join(e(v) for v in (x.get("when"), x.get("who")) if v)
        cards.append(f'<article class="k-min"><span class="k-min-n" aria-hidden="true">{i + 1:02d}</span>'
                     f'<h3 class="k-h3">{e(x["name"])}</h3>{_raw("p", "k-meta", meta)}'
                     f'{_opt("p", "k-min-p", x.get("description"))}</article>')
    return (f'<section class="k-section k-ministries" id="ministries"><div class="k-wrap"><div class="k-head"><div>'
            f'{_opt("p", "k-eyebrow", m.get("eyebrow"))}<h2 class="k-h2">{e(m.get("headline") or "Ministries")}</h2></div>'
            f'{_opt("p", "k-intro", m.get("intro"))}</div><div class="k-min-grid">{"".join(cards)}</div></div></section>')


def events(d, w) -> str:
    if not d["events"]:
        return ""
    ev = w.get("events") or {}
    cards = []
    for x in d["events"][:6]:
        cards.append(f'<article class="k-event"><p class="k-event-date"><span class="k-meta">{e(x.get("date"))}</span>'
                     f'{_opt("b", "", x.get("time"))}</p><h3 class="k-h3">{e(x["title"])}</h3>'
                     f'{_opt("p", "k-meta", x.get("place"))}{_opt("p", "k-min-p", x.get("note"))}</article>')
    return (f'<section class="k-section k-events" id="events"><div class="k-wrap">'
            f'{_opt("p", "k-eyebrow", ev.get("eyebrow"))}<h2 class="k-h2">{e(ev.get("headline") or "Coming up")}</h2>'
            f'<div class="k-event-grid">{"".join(cards)}</div></div></section>')


def topics(d, w) -> str:
    """What a leader speaks on, teaches or sells: from their offerings."""
    if not d["desk"]:
        return ""
    t = w.get("topics") or {}
    rows = []
    for o in d["desk"]:
        meta = " &middot; ".join(x for x in (f"<b>{e(o['price'])}</b>" if o.get("price") else "",
                                             e(o["minutes"]) if o.get("minutes") else "") if x)
        btn = (f'<a class="k-btn" href="{e(o["book_url"])}">{e(w.get("row_label") or "Book")} &rarr;</a>'
               if o.get("book_url") else "")
        rows.append(f'<li class="k-row"><div class="k-row-name"><h3 class="k-h3">{e(o["name"])}</h3>'
                    f'{_raw("span", "k-meta", meta)}</div>{_opt("p", "", o.get("description"))}{btn}</li>')
    return (f'<section class="k-section k-topics" id="topics"><div class="k-wrap"><div class="k-desk-grid">'
            f'<div class="k-stick k-board-head">{_opt("p", "k-eyebrow", t.get("eyebrow"))}'
            f'<h2 class="k-h2">{e(t.get("headline") or "What I do")}</h2>{_opt("p", "k-intro", t.get("intro"))}</div>'
            f'<ul class="k-desk">{"".join(rows)}</ul></div></div></section>')


def ceremony(d, w) -> str:
    c = w.get("ceremony") or {}
    line = str(c.get("line") or "").strip()
    if not line:
        return ""
    accent = str(c.get("accent_word") or "").strip()
    txt = e(line)
    if accent and accent.lower() in line.lower():
        pat = re.compile(re.escape(e(accent)), re.IGNORECASE)
        txt = pat.sub(lambda m: f'<span class="k-under">{m.group(0)}</span>', txt, count=1)
    return (f'<section class="k-ceremony"><div class="k-wrap"><p class="k-ceremony-line">{txt}</p>'
            f'{_opt("p", "k-ceremony-sub", c.get("sub"))}{_ctas(d, w)}</div></section>')


def visit_steps(d, w) -> str:
    """The visit section, with the first-time path when the words give one."""
    html = visit(d, w)
    steps = [s for s in ((w.get("visit") or {}).get("steps") or []) if str(s).strip()][:4]
    if not html or not steps:
        return html
    ol = "<ol class=\"k-steps\">" + "".join(f"<li>{e(s)}</li>" for s in steps) + "</ol>"
    return html.replace('<div class="k-ctas">', ol + '<div class="k-ctas">', 1)


def signoff_footer(d, w) -> str:
    mark = (w.get("wordmark") or {}).get("main") or d["name"]
    return (f'<div class="k-signoff"><div class="k-wrap"><p class="sxo sxo-signoff" data-sx-object="sign-off" '
            f'aria-hidden="true"><span>{e(mark)}</span></p></div></div>' + footer(d, w))


# ─── the layouts ──────────────────────────────────────────────────────

LAYOUTS: Dict[str, List[tuple]] = {
    "poster": [("hero", hero_poster), ("times", times), ("marquee", marquee), ("album", album),
               ("leaders", leaders), ("story", story), ("proof", proof), ("ceremony", ceremony),
               ("visit", visit_steps)],
    "bulletin": [("hero", hero_bulletin), ("times", times), ("events", events), ("ministries", ministries),
                 ("leaders", leaders), ("album", album), ("proof", proof), ("ceremony", ceremony),
                 ("visit", visit_steps)],
    "magazine": [("hero", hero_cover), ("ministries", ministries), ("times", times), ("story", story),
                 ("leaders", leaders), ("events", events), ("album", album), ("proof", proof),
                 ("ceremony", ceremony), ("visit", visit_steps)],
    "leader": [("hero", hero_leader), ("story", story), ("topics", topics), ("proof", proof),
               ("album", album), ("events", events), ("ceremony", ceremony), ("visit", visit_steps)],
}
FOOTERS = {k: signoff_footer for k in LAYOUTS}

CSS = r"""
/* type that's handwritten, for a few words only */
.k-hand{font:400 clamp(1.6rem,2.6vw,2.2rem)/1.2 var(--k-script);color:var(--k-text);margin:14px 0 0}
/* POSTER */
.k-hero-poster{min-height:0;display:block;padding:120px 0 clamp(64px,8vw,104px)}
.k-hero-poster .sxo-pwords h1{font-family:var(--k-display);font-weight:var(--k-dw);text-transform:var(--k-case);
  font-size:clamp(3rem,min(10.5cqi,10rem),10rem);line-height:var(--k-lh1);letter-spacing:-.01em;margin:0}
@media (min-width:900px){.k-hero-poster .sxo-pw-line{white-space:nowrap}}
.k-hero-poster .sxo-pwords em{font-style:normal;color:var(--k-accent)}
.k-hero-poster .sxo-pw-pic{width:1.45em;height:.78em;border-radius:.4em}
.k-poster-foot{display:grid;grid-template-columns:minmax(0,6fr) minmax(0,5fr);gap:clamp(24px,5vw,72px);align-items:start;
  margin-top:clamp(36px,5vw,64px);padding-top:clamp(24px,3vw,36px);border-top:1px solid var(--k-line)}
.k-poster-foot .k-lead{margin-top:0}
.k-hero-poster .k-ghost{opacity:.07}
@media (max-width:1100px){.k-poster-foot{grid-template-columns:minmax(0,1fr)}}
.k-when{list-style:none;margin:0 0 22px;padding:clamp(18px,2.4vw,28px);background:var(--k-surface);border-radius:var(--k-r2);
  display:grid;gap:14px;box-shadow:0 18px 40px -28px rgba(0,0,0,.35)}
.k-when li{display:grid;grid-template-columns:minmax(0,6.5rem) minmax(0,1fr);gap:2px 14px;align-items:baseline}
.k-when b{font:500 12px/1.4 var(--k-label);letter-spacing:.14em;text-transform:uppercase;color:var(--k-second)}
.k-when span{font:var(--k-dw) clamp(1.15rem,1.6vw,1.4rem)/1.15 var(--k-display);text-transform:var(--k-case)}
.k-when small{grid-column:2;color:var(--k-muted);font-size:15px}
.k-when .k-when-where span{font:600 16px/1.4 var(--k-body);text-transform:none}
.k-when .k-when-where .k-link{grid-column:2;padding:6px 0;justify-self:start}
/* BULLETIN */
.k-hero-bulletin{min-height:0;display:block;padding:120px 0 clamp(56px,7vw,96px)}
.k-bulletin-grid{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:clamp(28px,5vw,72px);align-items:center}
.k-bulletin-side{position:relative}
.k-bulletin-side.has-photo{padding:0 0 clamp(90px,10vw,140px) clamp(20px,4vw,56px)}
.k-bulletin-photo{display:block;width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:var(--k-r)}
.k-bulletin-side.has-photo .k-pinned{position:absolute;left:0;bottom:0;width:min(88%,30rem);transform:rotate(-1.5deg)}
.k-glow.k-hero-bulletin .k-bulletin-side::before{content:"";position:absolute;inset:-18% -10% 0;z-index:-1;
  background:radial-gradient(closest-side,color-mix(in srgb,var(--k-accent) 18%,transparent),transparent)}
.k-hero-bulletin .k-ctas,.k-hero-cover .k-ctas,.k-hero-poster .k-ctas{margin-top:30px}
@media (max-width:1100px) and (min-width:761px){.k-bulletin-grid{grid-template-columns:minmax(0,6fr) minmax(0,5fr)}
  .k-bulletin-side.has-photo .k-pinned{width:96%}}
/* MAGAZINE */
.k-hero-cover{min-height:0;display:block;padding:104px 0 clamp(56px,7vw,96px)}
.k-masthead{display:flex;justify-content:space-between;align-items:baseline;gap:16px;border-bottom:2px solid var(--k-text);
  padding-bottom:12px;margin-bottom:clamp(20px,3vw,32px)}
.k-mast-name{font:var(--k-dw) clamp(1.8rem,4.6vw,3.6rem)/1 var(--k-display);text-transform:var(--k-case);letter-spacing:-.01em}
.k-mast-issue{font:500 12px/1.4 var(--k-label);letter-spacing:.14em;text-transform:uppercase;color:var(--k-second);text-align:right}
.k-cover-grid{display:grid;grid-template-columns:minmax(0,8fr) minmax(0,4fr);gap:clamp(24px,3.5vw,48px)}
.k-cover-main{position:relative;min-width:0}
.k-cover-img{display:block;width:100%;aspect-ratio:16/11;object-fit:cover;border-radius:var(--k-r)}
.k-cover-main.has-photo .k-cover-copy{position:absolute;left:0;right:0;bottom:0;padding:clamp(22px,3.4vw,44px);
  border-radius:0 0 var(--k-r) var(--k-r);background:linear-gradient(0deg,rgba(0,0,0,.86),rgba(0,0,0,.66) 55%,rgba(0,0,0,.18) 88%,transparent);color:#fff}
.k-cover-main.has-photo .k-h1{text-shadow:0 2px 18px rgba(0,0,0,.45)}
.k-cover-main.has-photo .k-h1{font-size:clamp(2.4rem,5vw,5.2rem);color:#fff}
.k-cover-main.has-photo .k-eyebrow{color:rgba(255,255,255,.82)}
.k-cover-main.has-photo .k-lead{color:rgba(255,255,255,.88);margin-top:14px}
.k-cover-main.has-photo .k-link{color:#fff}
.k-glow.k-hero-cover::before{content:"";position:absolute;z-index:-1;top:0;right:0;width:60vw;height:70vh;
  background:radial-gradient(closest-side,color-mix(in srgb,var(--k-accent) 14%,transparent),transparent);pointer-events:none}
.k-hero-cover{position:relative;isolation:isolate}
.k-rail{border-left:1px solid var(--k-line);padding-left:clamp(18px,2.4vw,28px)}
.k-rail ol{list-style:none;margin:0;padding:0;display:grid;gap:0}
.k-rail li{padding:16px 0;border-bottom:1px solid var(--k-line);display:grid;gap:6px}
.k-rail b{font:var(--k-dw) clamp(1.2rem,1.7vw,1.5rem)/1.1 var(--k-display);text-transform:var(--k-case)}
.k-rail a{text-decoration:none}
/* LEADER */
.k-hero-leader{min-height:0;display:block;padding:clamp(120px,12vw,150px) 0 clamp(64px,8vw,104px)}
.k-leader-pic{position:relative}
.k-glow .k-leader-pic::before{content:"";position:absolute;inset:-14%;z-index:-1;
  background:radial-gradient(closest-side,color-mix(in srgb,var(--k-accent) 20%,transparent),transparent)}
.k-leader-grid{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:clamp(28px,5vw,72px);align-items:center}
.k-leader-name{font-size:clamp(3.4rem,9vw,8.6rem)}
.k-leader-line{font-size:clamp(1.2rem,1.9vw,1.55rem);line-height:1.4;max-width:30ch;margin:24px 0 30px;color:var(--k-muted)}
.k-leader-portrait{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:var(--k-r)}
/* TIMES */
.k-times{background:var(--k-surface);padding:clamp(64px,8vw,112px) 0}
.k-times .sxo-times{margin-top:clamp(28px,4vw,48px)}
.k-times+.k-leaders,.k-leaders+.k-times,.k-events+.k-leaders{padding-top:clamp(36px,4vw,64px)}
/* MARQUEE */
.k-marquee{background:var(--k-deep);color:var(--k-ink-deep);--obj-ink:var(--k-ink-deep);padding:clamp(18px,2.6vw,30px) 0;overflow:hidden}
.k-marquee .sxo-marquee li{font-family:var(--k-display);font-weight:var(--k-dw);text-transform:var(--k-case)}
/* ALBUM */
.k-album-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:clamp(10px,1.6vw,20px);margin-top:clamp(32px,4vw,52px)}
.k-album-grid figure{margin:0;min-width:0;display:flex;flex-direction:column}
.k-album-grid img{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:var(--k-r)}
.k-album-grid figure:nth-child(1){grid-column:span 2;grid-row:span 2}
.k-album-grid figure:nth-child(1) img{aspect-ratio:auto;flex:1;min-height:0;height:auto}
.k-album-grid figcaption{font-size:14px;color:var(--k-muted);margin-top:8px}
/* LEADERS */
.k-leaders{background:var(--k-surface)}
.k-leaders .sxo-leader::after{display:none}
.k-leaders .sxo-leader-head{max-width:calc(100% - 2rem);line-height:1.15}
.k-leaders .sxo-leader-body{margin-top:1.6rem}
.k-leaders .sxo-leader-panel h3{font-size:clamp(28px,3.4vw,50px);line-height:1.02;overflow-wrap:break-word}
.k-leaders .sxo-leader.k-no-photo .sxo-leader-body{grid-template-columns:minmax(0,1fr)}
/* STORY */
.k-story{overflow:hidden}
.k-story-grid{display:grid;grid-template-columns:minmax(0,6fr) minmax(0,6fr);gap:clamp(28px,5vw,80px);align-items:start}
.k-story-grid>div:first-child{position:sticky;top:110px}
.k-story .sxo-pola-row{grid-template-columns:repeat(2,minmax(0,1fr))}
.k-story-grid{align-items:center}
.k-story-grid.solo{grid-template-columns:minmax(0,1fr);max-width:820px}
.k-story-p{font-size:clamp(17px,1.3vw,19px);max-width:56ch;margin:22px 0 0;color:var(--k-text)}
.k-story .sxo-pola img{border-radius:calc(var(--k-r)/2)}
/* MINISTRIES */
.k-min-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:0;border-top:1px solid var(--k-line)}
.k-min{padding:clamp(22px,2.6vw,32px) clamp(4px,1.4vw,20px) clamp(26px,3vw,36px) 0;border-bottom:1px solid var(--k-line);display:grid;gap:8px;align-content:start}
.k-min-n{font:500 12px/1 var(--k-label);letter-spacing:.14em;color:var(--k-accent)}
.k-min-p{margin:4px 0 0;color:var(--k-muted);max-width:44ch}
/* EVENTS */
.k-events{background:var(--k-surface)}
.k-event-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:clamp(14px,2vw,24px);margin-top:clamp(28px,4vw,48px)}
.k-event{background:var(--k-bg);border-radius:var(--k-r2);padding:clamp(20px,2.4vw,28px);display:grid;gap:8px;align-content:start}
.k-event-date{display:flex;justify-content:space-between;gap:12px;margin:0;align-items:baseline}
.k-event-date b{font:500 13px var(--k-label);letter-spacing:.1em;text-transform:uppercase}
/* CEREMONY */
.k-ceremony{background:var(--k-deep);color:var(--k-ink-deep);text-align:center;padding:clamp(72px,9vw,128px) 0;position:relative;overflow:hidden}
.k-ceremony::before{content:"";position:absolute;inset:auto 10% -40% 10%;height:90%;
  background:radial-gradient(closest-side,color-mix(in srgb,var(--k-accent) 22%,transparent),transparent);pointer-events:none}
.k-ceremony .k-wrap{position:relative}
.k-ceremony-line{margin:0 auto;max-width:16ch;font:var(--k-dw) clamp(3rem,9vw,8.4rem)/calc(var(--k-lh1) + .08) var(--k-display);
  text-transform:var(--k-case);letter-spacing:-.01em;text-wrap:balance}
.k-under{background:linear-gradient(var(--k-accent),var(--k-accent)) 0 92%/100% .09em no-repeat;padding-bottom:.04em}
.k-ceremony-sub{margin:36px auto 0;max-width:46ch;color:color-mix(in srgb,var(--k-ink-deep) 76%,var(--k-deep))}
.k-ceremony .k-ctas{justify-content:center;margin-top:30px}
/* VISIT STEPS */
.k-steps{margin:30px 0 0;padding:0;list-style:none;counter-reset:s;display:grid;gap:12px;max-width:44ch}
.k-steps li{counter-increment:s;display:grid;grid-template-columns:2.2rem minmax(0,1fr);gap:12px;align-items:baseline}
.k-steps li::before{content:counter(s);font:var(--k-dw) 1.5rem/1 var(--k-display);color:var(--k-second-deep)}
/* SIGN-OFF */
.k-signoff{background:var(--k-bg);padding-top:clamp(28px,4vw,56px)}
.sxo-signoff{margin:0;line-height:.98!important;padding:.06em 0 .12em;color:var(--k-text);text-transform:var(--k-case)}
@media (max-width:760px){
  .k-poster-foot,.k-bulletin-grid,.k-cover-grid,.k-leader-grid,.k-story-grid{grid-template-columns:minmax(0,1fr)}
  .k-story-grid>div:first-child{position:static}
  .k-hero-poster .k-poster-foot>div:last-child{order:-1}
  .k-rail{border-left:0;padding-left:0;border-top:1px solid var(--k-line)}
  .k-cover-img{aspect-ratio:4/3}
  .k-cover-main.has-photo .k-cover-copy{position:static;background:none;color:inherit;padding:22px 0 0}
  .k-cover-main.has-photo .k-h1{color:var(--k-text);text-shadow:none}
  .k-cover-main.has-photo .k-eyebrow{color:var(--k-second)}
  .k-cover-main.has-photo .k-lead{color:var(--k-muted)}
  .k-cover-main.has-photo .k-link{color:var(--k-second)}
  .k-album-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
  .k-leader-pic{order:-1}
  .k-hero-leader{min-height:0;padding-top:96px}
  .k-bulletin-side.has-photo{padding:0;display:flex;flex-direction:column;gap:18px}
  .k-bulletin-side.has-photo .k-pinned{position:relative;width:auto;margin:0;transform:none;order:-1}
  .k-bulletin-photo{aspect-ratio:4/3}
}
"""
