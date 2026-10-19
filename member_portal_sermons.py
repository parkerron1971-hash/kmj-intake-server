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


def _row(s: Dict[str, Any], lib: Dict[str, Any], pal: Dict[str, str], site=None,
         pool: Optional[List[str]] = None) -> str:
    import member_app_ui as ui
    from member_portal import _e
    return (f'<li><a href="/my/sermons/{_e(s["id"])}"><span class="mb-thumb">{_art(lib, s, pal, site, pool)}</span>'
            f'<span class="mb-list-text"><strong>{_e(s.get("title"))}</strong>'
            f'<span>{meta(s)}</span></span></a></li>')


def latest_card(lib: Optional[Dict[str, Any]], pal: Dict[str, str], *, heading: str = "h2",
                pool: Optional[List[str]] = None, used: Optional[set] = None, site=None) -> str:
    """Home's newest message, Subsplash-style: its art, the title under it.
    '' when nothing is published (Home simply leaves it out)."""
    import member_app_ui as ui
    from member_portal import _e
    if not lib or not lib["sermons"]:
        return ""
    s = lib["sermons"][0]
    series = _titles(lib).get(str(s.get("series_id") or ""), "")
    href = f"/my/sermons/{_e(s['id'])}"
    import member_app_samples as samples
    sample = samples.is_sample(s)
    hint = ui.sample_hint(samples.WHERE["sermons"]) if sample else ""
    sub = " · ".join(_e(x) for x in (series, s.get("speaker") or "") if x)
    from sermons_public import day_label
    when = day_label(s.get("preached_on"))
    sub = " · ".join(x for x in (sub, _e(when)) if x)
    return f"""<section class="h-violet" aria-labelledby="mb-latest">
  {ui.section("Latest message", "/my/sermons", "See all")}{hint}
  <a class="mb-mtile" href="{href}"><span class="mb-mtile-art">{_art(lib, s, pal, site, pool, used)}
  <span class="mb-play" aria-hidden="true">{ui.icon("play", 18)}</span>{ui.sample_tag() if sample else ''}</span>
  <span class="mb-mtile-b"><{heading} class="mp-sr" id="mb-latest">{_e(s.get('title'))}</{heading}>
  <strong aria-hidden="true">{_e(s.get('title'))}</strong><span>{sub}</span></span></a>
</section>"""


def render_library(biz, site, who, lib: Optional[Dict[str, Any]], series_id: str = "", bible: str = "kjv",
                   live: Optional[Dict[str, Any]] = None, next_occ: Optional[Dict[str, Any]] = None) -> str:
    """Watch (the Subsplash app's Messages and On Demand, together): live
    or the next gathering, the latest message, the series, every message."""
    import member_app_ui as ui
    import member_app_photos as photos
    from member_portal import _e, _shell, palette_for
    pal = palette_for(biz, site)
    pool = photos.photos(biz, site)
    head = '<div class="mb-lt"><h1>Watch</h1></div>'
    if lib is None:
        body = (f'{head}{live_card(live, next_occ)}<p class="mp-err" role="alert" style="margin-top:18px">Messages couldn\'t '
                'load just now. Please try again in a moment.</p>')
        return _shell(biz, site, "Watch", body, tab="watch", who=who)
    titles = _titles(lib)
    if series_id and series_id in titles:
        mine = [s for s in lib["sermons"] if str(s.get("series_id")) == series_id]
        about = next((x.get("description") for x in lib["series"] if str(x["id"]) == series_id), "") or ""
        rows = "".join(_row(s, lib, pal, site, pool) for s in mine)
        count = f"{len(mine)} message{'' if len(mine) == 1 else 's'}"
        cover = _art(lib, mine[0], pal, site, pool) if mine else ui.poster(series_id, pal, titles[series_id])
        body = f"""<div class="mb-mtile-art" style="margin-top:4px">{cover}</div>
<p class="mb-kick" style="margin-top:16px">Series · {_e(count)}</p>
<h1 style="margin:2px 0 8px">{_e(titles[series_id])}</h1>
{f'<p class="mb-text" style="color:var(--fg2)">{_e(about)}</p>' if about else ''}
{ui.section("Messages")}
{f'<ul class="mb-list mb-cards" style="--inset:124px">{rows}</ul>' if rows else '<p class="mp-muted">No messages in this series are posted yet.</p>'}"""
        return _shell(biz, site, titles[series_id], body, tab="watch", who=who, back=("/my/sermons", "Watch"))
    if not lib["sermons"]:
        # Nothing posted yet: a designed page with something useful on
        # it, never an empty list.
        import member_portal_bible as mpb
        church = _e(biz.get("name") or "the church")
        pic, look = photos.choose(biz, "watch", pool)
        art = ui.picture(pic, look, "messages", night=True)
        body = (f'{head}{live_card(live, next_occ)}'
                f'<section class="mb-soon" style="margin-top:12px">{art}<div class="mb-soon-in"><span class="mb-kick">Coming soon</span>'
                f'<h2>Messages are on the way</h2><p>When {church} posts a message, it shows up here, '
                f'ready to watch or listen, with the scripture and notes.</p></div></section>'
                f'{mpb.verse_card(bible)}')
        return _shell(biz, site, "Watch", body, tab="watch", who=who)
    used: set = set()
    s = lib["sermons"][0]
    import member_app_samples as samples
    sample = samples.is_sample(s)
    hint = ui.sample_hint(samples.WHERE["sermons"]) if sample else ""
    from sermons_public import day_label
    href = f"/my/sermons/{_e(s['id'])}"
    listen = (f'<a class="mp-go mp-go-2" href="{href}#listen">{ui.icon("headphones", 17)}Listen</a>'
              if (s.get("audio_url") or "").strip() else "")
    feat = f"""<section class="mb-feat" aria-labelledby="mb-feat-h">{hint}
<a class="mb-mtile-art" href="{href}" tabindex="-1" aria-hidden="true">{_art(lib, s, pal, site, pool, used)}
<span class="mb-play">{ui.icon("play", 18)}</span>{ui.sample_tag() if sample else ''}</a>
<span class="mb-kick">Latest · {_e(day_label(s.get("preached_on")))}</span>
<h2 id="mb-feat-h"><a href="{href}">{_e(s.get("title"))}</a></h2>
<p class="mb-meta">{_e(" · ".join(x for x in (s.get("speaker") or "", s.get("scripture") or "") if x))}</p>
<div class="mb-acts"><a class="mp-go" href="{href}">{ui.icon("play", 15)}Watch</a>{listen}
<button class="mp-go mp-go-2 mb-sq" type="button" data-share="/sermons/{_e(s["id"])}" data-title="{_e(s.get("title"))}" aria-label="Share">{ui.icon("share", 18)}</button></div>
</section>"""
    by_series: Dict[str, List[Dict[str, Any]]] = {}
    for x in lib["sermons"]:
        sid = str(x.get("series_id") or "")
        if sid in titles:
            by_series.setdefault(sid, []).append(x)
    order = sorted(by_series, key=lambda k: str(by_series[k][0].get("preached_on")), reverse=True)
    shelf = "".join(
        f'<a class="mb-ser" href="/my/sermons?series={_e(sid)}"><span class="mb-mtile-art">'
        f'{_art(lib, by_series[sid][0], pal, site, pool, used)}</span><span class="mb-mtile-b"><strong>{_e(titles[sid])}</strong>'
        f'<span>{len(by_series[sid])} message{"" if len(by_series[sid]) == 1 else "s"}</span></span></a>'
        for sid in order)
    parts = [head, live_card(live, next_occ), feat]
    if shelf:
        parts.append(f'{ui.section("Series")}<div class="mb-rail">{shelf}</div>')
    parts.append(f'{ui.section("All messages")}<ul class="mb-list mb-cards" style="--inset:124px">'
                 f'{"".join(_row(x, lib, pal, site, pool) for x in lib["sermons"])}</ul>')
    return _shell(biz, site, "Watch", "".join(parts), tab="watch", who=who, script=SHARE_SCRIPT)


def render_sermon(biz, site, who, lib: Optional[Dict[str, Any]], sermon_id: str,
                  give_url: str = "", bible: str = "kjv") -> Optional[str]:
    """One message, or None when it isn't published here (the caller
    sends the member back to Watch)."""
    import member_app_ui as ui
    import member_app_photos as photos
    from member_portal import _e, _shell, palette_for
    from sermons_public import player_html, day_label
    if lib is None:
        body = ('<p class="mp-err" role="alert">This message couldn\'t load just now. Please try again in a moment.</p>'
                '<p><a href="/my/sermons">Watch</a></p>')
        return _shell(biz, site, "Watch", body, tab="watch", who=who, back=("/my/sermons", "Watch"))
    s = next((x for x in lib["sermons"] if str(x["id"]) == sermon_id), None)
    if not s:
        return None
    pal = palette_for(biz, site)
    titles = _titles(lib)
    sid = str(s.get("series_id") or "")
    series = titles.get(sid, "")
    player = player_html(s).replace('class="sm-video"', 'class="mb-video"').replace(
        'class="sm-go"', 'class="mp-go" style="margin:12px 20px 0;width:calc(100% - 40px)"').replace(
        '<audio class="sm-audio"', '<audio id="listen" class="sm-audio"')
    if not (s.get("video_url") or "").strip():
        # Audio only, or nothing posted yet: the series art holds the space.
        player = _art(lib, s, pal, site, photos.photos(biz, site)) + player
    eyebrow = " · ".join(x for x in (series, _part(lib, s), day_label(s.get("preached_on"))) if x) or "Message"
    give = f'<a class="mp-go mp-go-2" href="{_e(give_url)}">{ui.icon("give", 17)}Give</a>' if give_url else ""
    import member_app_samples as samples
    parts = [ui.sample_hint("A sample message. " + samples.WHERE["sermons"]) if samples.is_sample(s) else ""]
    scrip = ""
    if s.get("scripture"):
        import member_portal_bible as mpb
        scrip = f'<span class="mb-scrip">{ui.icon("book", 15)}{mpb.scripture_links(s["scripture"])}</span>'
    parts += [f'<div class="mb-player">{player}</div>',
              f'<p class="mb-kick" style="margin-top:18px">{_e(eyebrow)}</p>',
              f'<h1 style="margin:4px 0 4px">{_e(s.get("title"))}</h1>',
              f'<p class="mb-meta">{_e(s.get("speaker") or "")}</p>{scrip}',
              f'<div class="mb-acts">{give}<button class="mp-go mp-go-2" type="button" data-share="/sermons/{_e(s["id"])}" '
              f'data-title="{_e(s.get("title"))}">{ui.icon("share", 17)}<span>Share</span></button></div>']
    if not (s.get("video_url") or s.get("audio_url") or "").strip():
        parts.append('<p class="mp-muted" style="margin-top:14px">The recording for this message isn\'t posted yet.</p>')
    if s.get("summary"):
        parts.append(f'<p class="mb-text" style="margin-top:20px">{_e(s["summary"])}</p>')
    if s.get("scripture"):
        import member_portal_bible as mpb
        parts.append(mpb.passage_card(s["scripture"], bible))
    if s.get("questions"):
        parts.append('<section class="mb-q" aria-labelledby="mb-q"><h2 id="mb-q">Talk it over this week</h2>'
                     f'<p class="mb-text">{_e(s["questions"])}</p></section>')
    if series:
        others = [x for x in lib["sermons"] if str(x.get("series_id")) == sid and x["id"] != s["id"]]
        if others:
            parts.append(f'{ui.section("More in " + series)}'
                         f'<ul class="mb-list mb-cards" style="--inset:124px">{"".join(_row(x, lib, pal, site) for x in others)}</ul>')
    back = (f"/my/sermons?series={sid}", series) if series else ("/my/sermons", "Watch")
    return _shell(biz, site, s.get("title") or "Message", "".join(parts), tab="watch", who=who,
                  script=SHARE_SCRIPT, back=back)


def _art(lib: Dict[str, Any], s: Dict[str, Any], pal: Dict[str, str], site=None,
         pool: Optional[List[str]] = None, used: Optional[set] = None) -> str:
    """A message's picture: its series' own art from the church's site
    (in colour), else a photo named for the series with the series name on
    it, else a generated poster in the church's colour. Never a photo picked
    by chance (Kevin, 2026-10-19)."""
    import member_app_ui as ui
    import member_app_photos as photos
    series = _titles(lib).get(str(s.get("series_id") or ""), "")
    name = series or s.get("title") or ""
    own = photos.series_art(site, series) if series else ""
    if own:
        return ui.art(own)
    pic = photos.by_name(pool or [], name, used or ()) if pool else ""
    if pic:
        if used is not None:
            used.add(pic)
        return ui.titled_photo(pic, name)
    return ui.poster(_key(lib, s), pal, name)


def live_card(live: Optional[Dict[str, Any]], next_occ: Optional[Dict[str, Any]] = None) -> str:
    """Watch's first row: Live now (red) while the church is live, else the
    next gathering, both opening the live page."""
    import member_app_ui as ui
    from member_portal import _e
    if live:
        return (f'<a class="mb-livecard is-live" href="/my/live"><span class="mb-row-ic">{ui.icon("live", 22)}</span>'
                f'<span class="mb-row-t"><small><span class="mb-live-dot" aria-hidden="true" style="display:inline-block;'
                f'margin-right:6px;vertical-align:1px"></span>Live now</small><strong>{_e(live.get("title"))}</strong>'
                f'<span>Watch and chat with your church</span></span><span class="mp-go">Watch</span></a>')
    when, title = "", "Live services"
    if next_occ:
        import member_portal_church as mpc
        d = mpc._day(next_occ.get("date") or "")
        title = next_occ.get("title") or title
        if d:
            from datetime import date
            soon = mpc._in_days(d, date.today())
            when = soon if soon in ("Today", "Tomorrow") else f"{d.strftime('%A')} · {soon}"
    return (f'<a class="mb-livecard" href="/my/live"><span class="mb-row-ic">{ui.icon("live", 22)}</span>'
            f'<span class="mb-row-t"><small>Next live</small><strong>{_e(title)}</strong>'
            f'<span>{_e(when or "It plays right here")}</span></span>{ui.icon("chevron", 18)}</a>')
