"""
member_portal_sermons.py — Sermons inside the member app (/my/sermons).

The church's published messages, in the member app's own look, so a
member never leaves the app to watch (Kevin's walk-through of his
church's current app, 2026-09-30: its sermons were a poster grid whose
messages were titled "Love City Experience//11:00am//09.27.26", with no
speaker or scripture). Here every message shows its title, speaker and
scripture, series are posters, and a message page carries its summary
and the questions for small groups.

  /my/sermons              latest message, then every series as a poster,
                           then messages outside a series
  /my/sermons?series=<id>  one series, newest first
  /my/sermons/<id>         one message with its player

Reads the same tables as the public /sermons page (sermons_public.py),
published messages only, and reuses its player. A failed read says so —
it never shows "no messages".
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients

SELECT = "id,series_id,title,preached_on,speaker,scripture,summary,questions,video_url,audio_url,published"


def load_library(business_id: str) -> Optional[Dict[str, List[Dict[str, Any]]]]:
    """{'sermons': newest first, 'series': [...]} — published only — or
    None when either read failed."""
    b = quote(str(business_id), safe="")
    sermons = sb_clients.sb_get_as_service(
        f"/sermons?business_id=eq.{b}&published=eq.true&select={SELECT}"
        f"&order=preached_on.desc,created_at.desc&limit=500")
    series = sb_clients.sb_get_as_service(
        f"/sermon_series?business_id=eq.{b}&select=id,title,description&limit=200")
    if not isinstance(sermons, list) or not isinstance(series, list):
        return None
    return {"sermons": [s for s in sermons if s.get("published")], "series": series}


def _titles(lib: Dict[str, Any]) -> Dict[str, str]:
    return {str(x["id"]): x.get("title") or "" for x in lib.get("series") or []}


def meta(s: Dict[str, Any]) -> str:
    """'Pastor Ana · 1 Corinthians 11:3 · September 27, 2026' — escaped."""
    from sermons_public import day_label, _esc
    bits = [s.get("speaker") or "", s.get("scripture") or "", day_label(s.get("preached_on"))]
    return " · ".join(_esc(b) for b in bits if b)


def _row(s: Dict[str, Any], lib: Dict[str, Any]) -> str:
    import member_app_ui as ui
    from member_portal import _e
    sid = str(s.get("series_id") or "")
    key = sid if sid in _titles(lib) else s["id"]
    return (f'<li><a href="/my/sermons/{_e(s["id"])}"><span class="mb-thumb" style="{ui.poster_style(key)}">{ui.icon("play", 18)}</span>'
            f'<span class="mb-list-text"><strong>{_e(s.get("title"))}</strong><span>{meta(s)}</span></span>'
            f'{ui.icon("chevron", 16)}</a></li>')


def latest_hero(lib: Optional[Dict[str, Any]], *, heading: str = "h2") -> str:
    """Home's and the shelf's lead: the newest message under its series
    poster. '' when nothing is published (Home simply leaves it out)."""
    import member_app_ui as ui
    from member_portal import _e
    if not lib or not lib["sermons"]:
        return ""
    s = lib["sermons"][0]
    titles = _titles(lib)
    sid = str(s.get("series_id") or "")
    series = titles.get(sid, "")
    part = ""
    if series:
        n = [x for x in lib["sermons"] if str(x.get("series_id")) == sid]
        part = f" · Part {len(n) - n.index(s)} of {len(n)}" if len(n) > 1 else ""
    poster_title = series or s.get("title") or "Latest message"
    eyebrow = f"Series{part}" if series else "Latest message"
    return f"""<article class="mb-hero" aria-labelledby="mb-latest">
  <a class="mb-poster" href="/my/sermons/{_e(s['id'])}" style="{ui.poster_style(sid or s['id'])}" tabindex="-1" aria-hidden="true">
    <span class="mb-poster-eyebrow">{_e(eyebrow)}</span><span class="mb-poster-title">{_e(poster_title)}</span></a>
  <div class="mb-hero-body">
    <p class="mp-when" style="margin:0">Latest message</p>
    <{heading} class="mb-hero-title" id="mb-latest"><a href="/my/sermons/{_e(s['id'])}">{_e(s.get('title'))}</a></{heading}>
    <p class="mb-meta">{meta(s)}</p>
    <a class="mp-go" href="/my/sermons/{_e(s['id'])}">{ui.icon('play', 14)}Watch</a>
  </div>
</article>"""


def render_library(biz, site, who, lib: Optional[Dict[str, Any]], series_id: str = "") -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell
    if lib is None:
        body = ('<h1>Sermons</h1><p class="mp-err" role="alert">Sermons couldn\'t load just now. '
                'Please try again in a moment.</p>')
        return _shell(biz, site, "Sermons", body, tab="sermons", who=who)
    titles = _titles(lib)
    if series_id and series_id in titles:
        mine = [s for s in lib["sermons"] if str(s.get("series_id")) == series_id]
        about = next((x.get("description") for x in lib["series"] if str(x["id"]) == series_id), "") or ""
        rows = "".join(_row(s, lib) for s in mine)
        body = f"""<a class="mb-back" href="/my/sermons">{ui.icon('back', 16)}All sermons</a>
<div class="mb-hero"><div class="mb-poster" style="{ui.poster_style(series_id)}">
  <span class="mb-poster-eyebrow">{len(mine)} message{'' if len(mine) == 1 else 's'}</span>
  <h1 class="mb-poster-title" style="margin:0">{_e(titles[series_id])}</h1></div>
  {f'<div class="mb-hero-body"><p class="mb-meta">{_e(about)}</p></div>' if about else ''}</div>
{f'<ul class="mb-list">{rows}</ul>' if rows else '<p class="mp-muted">No messages in this series are posted yet.</p>'}"""
        return _shell(biz, site, titles[series_id], body, tab="sermons", who=who)
    if not lib["sermons"]:
        body = ('<h1>Sermons</h1><div class="mp-card"><p class="mp-muted">No messages are posted yet. '
                'When the church posts one, it shows up here.</p></div>')
        return _shell(biz, site, "Sermons", body, tab="sermons", who=who)
    by_series: Dict[str, List[Dict[str, Any]]] = {}
    loose: List[Dict[str, Any]] = []
    for s in lib["sermons"]:
        sid = str(s.get("series_id") or "")
        (by_series.setdefault(sid, []) if sid in titles else loose).append(s)
    order = sorted(by_series, key=lambda k: str(by_series[k][0].get("preached_on")), reverse=True)
    shelf = "".join(
        f'<a href="/my/sermons?series={_e(sid)}" style="{ui.poster_style(sid)}">'
        f'<span class="mb-count">{len(by_series[sid])} message{"" if len(by_series[sid]) == 1 else "s"}'
        f'{" · Now" if i == 0 else ""}</span>'
        f'<span class="mb-poster-title">{_e(titles[sid])}</span></a>'
        for i, sid in enumerate(order))
    parts = ['<h1>Sermons</h1>', latest_hero(lib)]
    if shelf:
        parts.append(f'<h2 class="mp-sect">Series</h2><div class="mb-shelf">{shelf}</div>')
    if loose:
        parts.append(f'<h2 class="mp-sect">{"More messages" if shelf else "All messages"}</h2>'
                     f'<ul class="mb-list">{"".join(_row(s, lib) for s in loose)}</ul>')
    return _shell(biz, site, "Sermons", "".join(parts), tab="sermons", who=who)


def render_sermon(biz, site, who, lib: Optional[Dict[str, Any]], sermon_id: str) -> Optional[str]:
    """One message, or None when it isn't published here (the caller
    sends the member back to the shelf)."""
    import member_app_ui as ui
    from member_portal import _e, _shell
    from sermons_public import player_html
    if lib is None:
        body = ('<p class="mp-err" role="alert">This message couldn\'t load just now. Please try again in a moment.</p>'
                '<p><a href="/my/sermons">All sermons</a></p>')
        return _shell(biz, site, "Sermons", body, tab="sermons", who=who)
    s = next((x for x in lib["sermons"] if str(x["id"]) == sermon_id), None)
    if not s:
        return None
    titles = _titles(lib)
    sid = str(s.get("series_id") or "")
    player = player_html(s).replace('class="sm-video"', 'class="mb-video"').replace('class="sm-go"', 'class="mp-go"')
    parts = [f'<a class="mb-back" href="{"/my/sermons?series=" + _e(sid) if sid in titles else "/my/sermons"}">'
             f'{ui.icon("back", 16)}{_e(titles.get(sid) or "All sermons")}</a>',
             f'<p class="mp-when">{_e(titles.get(sid) or "Message")}</p>',
             f'<h1>{_e(s.get("title"))}</h1>', f'<p class="mb-meta">{meta(s)}</p>',
             player or '<p class="mp-muted">The video for this message isn\'t posted yet.</p>']
    if s.get("summary"):
        parts.append(f'<section class="mp-card" aria-label="About this message"><p class="mb-text">{_e(s["summary"])}</p></section>')
    if s.get("questions"):
        parts.append('<section class="mp-card" aria-labelledby="mb-q"><h2 id="mb-q">For your group this week</h2>'
                     f'<p class="mb-text">{_e(s["questions"])}</p></section>')
    if sid in titles:
        others = [x for x in lib["sermons"] if str(x.get("series_id")) == sid and x["id"] != s["id"]]
        if others:
            parts.append(f'<h2 class="mp-sect">More in {_e(titles[sid])}</h2>'
                         f'<ul class="mb-list">{"".join(_row(x, lib) for x in others)}</ul>')
    return _shell(biz, site, s.get("title") or "Message", "".join(parts), tab="sermons", who=who)
