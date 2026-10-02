"""
member_portal_sermons.py — Sermons inside the member app (/my/sermons).

The church's published messages, in the member app's own look, so a
member never leaves the app to watch (Kevin's walk-through of his
church's current app, 2026-09-30: its sermons were a poster grid whose
messages were titled "Love City Experience//11:00am//09.27.26", with no
speaker or scripture). Here every message shows its title, speaker and
scripture, series are posters, and a message page carries its summary
and the questions for small groups.

  /my/sermons              the latest message, every series as a poster,
                           then messages outside a series
  /my/sermons?series=<id>  one series, newest first
  /my/sermons/<id>         one message: the player edge to edge, Share
                           (the public /sermons/<id> link), Give

Reads the same tables as the public /sermons page (sermons_public.py),
published messages only, and reuses its player. A failed read says so —
it never shows "no messages".
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sb_clients

SELECT = "id,series_id,title,preached_on,speaker,scripture,summary,questions,video_url,audio_url,published"

# Share hands the phone's share sheet the message's PUBLIC page (anyone
# can open a published message); without a share sheet it copies the
# link and says so on the button.
SHARE_SCRIPT = """<script>(function(){var b=document.querySelector('[data-share]');if(!b)return;
b.addEventListener('click',function(){var u=new URL(b.getAttribute('data-share'),location.origin).href,t=b.getAttribute('data-title')||'';
if(navigator.share){navigator.share({title:t,url:u}).catch(function(){});return;}
if(navigator.clipboard){navigator.clipboard.writeText(u).then(function(){b.lastChild.textContent='Link copied';},function(){b.lastChild.textContent=u;});}
else{b.lastChild.textContent=u;}});})();</script>"""


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


def meta(s: Dict[str, Any], *, linked: bool = False) -> str:
    """'Pastor Ana · 1 Corinthians 11:3 · September 27, 2026' — escaped;
    `linked` makes the scripture open in the Bible."""
    from sermons_public import day_label, _esc
    bits = [_esc(s.get("speaker") or ""), "", _esc(day_label(s.get("preached_on")))]
    if s.get("scripture"):
        import member_portal_bible as mpb
        bits[1] = mpb.scripture_links(s["scripture"]) if linked else _esc(s["scripture"])
    return " · ".join(b for b in bits if b)


def _part(lib: Dict[str, Any], s: Dict[str, Any]) -> str:
    """'Part 4 of 4' within its series (newest is the highest part), or ''."""
    sid = str(s.get("series_id") or "")
    n = [x for x in lib["sermons"] if str(x.get("series_id")) == sid]
    return f"Part {len(n) - n.index(s)} of {len(n)}" if sid and len(n) > 1 and s in n else ""


def _key(lib: Dict[str, Any], s: Dict[str, Any]) -> str:
    sid = str(s.get("series_id") or "")
    return sid if sid in _titles(lib) else str(s["id"])


def _row(s: Dict[str, Any], lib: Dict[str, Any], pal: Dict[str, str]) -> str:
    import member_app_ui as ui
    from member_portal import _e
    return (f'<li><a href="/my/sermons/{_e(s["id"])}"><span class="mb-thumb" style="{ui.poster_style(_key(lib, s), pal)}">'
            f'{ui.icon("play", 16)}</span><span class="mb-list-text"><strong>{_e(s.get("title"))}</strong>'
            f'<span>{meta(s)}</span></span>{ui.icon("chevron", 16)}</a></li>')


def latest_card(lib: Optional[Dict[str, Any]], pal: Dict[str, str], *, heading: str = "h2") -> str:
    """The newest message under its series poster, for Home and the shelf.
    '' when nothing is published (Home simply leaves it out)."""
    import member_app_ui as ui
    from member_portal import _e
    if not lib or not lib["sermons"]:
        return ""
    s = lib["sermons"][0]
    series = _titles(lib).get(str(s.get("series_id") or ""), "")
    part = _part(lib, s)
    kick = f"Series · {part}" if series and part else ("Series" if series else "Latest message")
    href = f"/my/sermons/{_e(s['id'])}"
    art = ui.poster(_key(lib, s), pal, series or s.get("title") or "", kick, tag="a", play=True,
                    attrs=f'href="{href}" aria-hidden="true" tabindex="-1"')
    return f"""<section aria-labelledby="mb-latest">
  <h2 class="mp-sect">Latest message <a href="/my/sermons">All sermons</a></h2>
  {art}
  <{heading} class="mb-msg-title" id="mb-latest"><a href="{href}">{_e(s.get('title'))}</a></{heading}>
  <p class="mb-meta">{meta(s)}</p>
</section>"""


def render_library(biz, site, who, lib: Optional[Dict[str, Any]], series_id: str = "") -> str:
    import member_app_ui as ui
    from member_portal import _e, _shell, palette_for
    pal = palette_for(biz, site)
    if lib is None:
        body = ('<h1>Sermons</h1><p class="mp-err" role="alert">Sermons couldn\'t load just now. '
                'Please try again in a moment.</p>')
        return _shell(biz, site, "Sermons", body, tab="sermons", who=who)
    titles = _titles(lib)
    if series_id and series_id in titles:
        mine = [s for s in lib["sermons"] if str(s.get("series_id")) == series_id]
        about = next((x.get("description") for x in lib["series"] if str(x["id"]) == series_id), "") or ""
        rows = "".join(_row(s, lib, pal) for s in mine)
        count = f"{len(mine)} message{'' if len(mine) == 1 else 's'}"
        body = f"""<a class="mb-back" href="/my/sermons">{ui.icon('back', 16)}All sermons</a>
<div style="margin-top:8px">{ui.poster(series_id, pal, titles[series_id], count, tag="div", title_tag="h1")}</div>
{f'<p class="mb-text" style="margin-top:14px">{_e(about)}</p>' if about else ''}
<h2 class="mp-sect">Messages</h2>
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
        ui.poster(sid, pal, titles[sid],
                  f'{len(by_series[sid])} message{"" if len(by_series[sid]) == 1 else "s"}{" · Now" if i == 0 else ""}',
                  tag="a", cls="mb-tall", attrs=f'href="/my/sermons?series={_e(sid)}"')
        for i, sid in enumerate(order))
    parts = ['<h1>Sermons</h1>', latest_card(lib, pal)]
    if shelf:
        parts.append(f'<h2 class="mp-sect">All series</h2><div class="mb-shelf">{shelf}</div>')
    if loose:
        parts.append(f'<h2 class="mp-sect">{"More messages" if shelf else "All messages"}</h2>'
                     f'<ul class="mb-list">{"".join(_row(s, lib, pal) for s in loose)}</ul>')
    return _shell(biz, site, "Sermons", "".join(parts), tab="sermons", who=who)


def render_sermon(biz, site, who, lib: Optional[Dict[str, Any]], sermon_id: str,
                  give_url: str = "", bible: str = "kjv") -> Optional[str]:
    """One message, or None when it isn't published here (the caller
    sends the member back to the shelf)."""
    import member_app_ui as ui
    from member_portal import _e, _shell, palette_for
    from sermons_public import player_html
    if lib is None:
        body = ('<p class="mp-err" role="alert">This message couldn\'t load just now. Please try again in a moment.</p>'
                '<p><a href="/my/sermons">All sermons</a></p>')
        return _shell(biz, site, "Sermons", body, tab="sermons", who=who)
    s = next((x for x in lib["sermons"] if str(x["id"]) == sermon_id), None)
    if not s:
        return None
    pal = palette_for(biz, site)
    titles = _titles(lib)
    sid = str(s.get("series_id") or "")
    series = titles.get(sid, "")
    player = player_html(s).replace('class="sm-video"', 'class="mb-video"').replace(
        'class="sm-go"', 'class="mp-go" style="margin:12px 20px 0;width:calc(100% - 40px)"')
    if not (s.get("video_url") or "").strip():
        # Audio only, or nothing posted yet: the series art holds the space.
        player = ui.poster(_key(lib, s), pal, series or s.get("title") or "", tag="div") + player
    eyebrow = " · ".join(x for x in (series, _part(lib, s)) if x) or "Message"
    give = f'<a class="mp-go mp-go-2" href="{_e(give_url)}">{ui.icon("heart", 16)}Give</a>' if give_url else ""
    parts = [f'<a class="mb-back" href="{"/my/sermons?series=" + _e(sid) if series else "/my/sermons"}">'
             f'{ui.icon("back", 16)}{_e(series or "All sermons")}</a>',
             f'<div class="mb-player">{player}</div>',
             f'<p class="mp-when" style="margin-top:18px">{_e(eyebrow)}</p>',
             f'<h1 style="margin:0 0 6px">{_e(s.get("title"))}</h1>', f'<p class="mb-meta">{meta(s, linked=True)}</p>',
             f'<div class="mb-acts"><button class="mp-go mp-go-2" type="button" data-share="/sermons/{_e(s["id"])}" '
             f'data-title="{_e(s.get("title"))}">{ui.icon("share", 16)}<span>Share</span></button>{give}</div>']
    if not (s.get("video_url") or s.get("audio_url") or "").strip():
        parts.append('<p class="mp-muted" style="margin-top:14px">The recording for this message isn\'t posted yet.</p>')
    if s.get("summary"):
        parts.append(f'<p class="mb-text" style="margin-top:18px">{_e(s["summary"])}</p>')
    if s.get("scripture"):
        import member_portal_bible as mpb
        parts.append(mpb.passage_card(s["scripture"], bible))
    if s.get("questions"):
        parts.append('<section class="mb-q" aria-labelledby="mb-q"><h2 id="mb-q">For your group this week</h2>'
                     f'<p class="mb-text">{_e(s["questions"])}</p></section>')
    if series:
        others = [x for x in lib["sermons"] if str(x.get("series_id")) == sid and x["id"] != s["id"]]
        if others:
            parts.append(f'<h2 class="mp-sect">More in {_e(series)}</h2>'
                         f'<ul class="mb-list">{"".join(_row(x, lib, pal) for x in others)}</ul>')
    return _shell(biz, site, s.get("title") or "Message", "".join(parts), tab="sermons", who=who,
                  script=SHARE_SCRIPT)
