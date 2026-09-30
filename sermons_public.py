"""
sermons_public.py — the church's public sermon library at <site>/sermons.

Kevin's church plan, "Sermons & Live": a sermon library by series; live
streams come next. The app (SermonsPanel) writes public.sermons and
public.sermon_series (APPLY-2026-09-30-sermons.sql); this module renders
what visitors see, served by public_site.py on the church's own host
(subdomain or custom domain), like /events and /give:

  /sermons          the newest message with its player, then every series
                    and the messages outside a series
  /sermons/<id>     one message: player, scripture, summary, questions for
                    small groups, and the rest of its series

Published sermons only. A page with nothing published is a branded 404,
never an empty shelf. Video plays inside the page for YouTube, Vimeo,
Loom and Facebook links; anything else becomes a plain "Watch" link.
Audio uses the browser's own player. Everything interpolated is escaped;
every link was stored as https:// (the table refuses anything else).

Pure functions (no I/O) so the whole page is unit-testable.
"""
from __future__ import annotations

import html as _html
import re
from datetime import date
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")


def _esc(s: Any) -> str:
    return _html.escape(str(s or ""), quote=True)


def _clean_id(v: str) -> str:
    return "".join(c for c in v if c.isalnum() or c in "_-")


def video_embed_src(url: str) -> str:
    """The iframe src for a sermon video link, or '' when the host isn't
    one we can play in the page (the caller then links out)."""
    u = (url or "").strip()
    try:
        p = urlparse(u)
    except ValueError:
        return ""
    if p.scheme != "https":
        return ""
    host = (p.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    path = p.path or ""
    if host in ("youtube.com", "youtube-nocookie.com"):
        vid = ""
        if path == "/watch":
            q = dict(x.split("=", 1) for x in p.query.split("&") if "=" in x)
            vid = q.get("v", "")
        else:
            m = re.match(r"^/(?:live|shorts|embed)/([^/?#]+)", path)
            vid = m.group(1) if m else ""
        vid = _clean_id(vid)
        return f"https://www.youtube-nocookie.com/embed/{vid}" if vid else ""
    if host == "youtu.be":
        vid = _clean_id(path.strip("/").split("/")[0])
        return f"https://www.youtube-nocookie.com/embed/{vid}" if vid else ""
    if host == "vimeo.com":
        vid = _clean_id(path.strip("/").split("/")[0])
        return f"https://player.vimeo.com/video/{vid}" if vid.isdigit() else ""
    if host == "loom.com" and path.startswith("/share/"):
        vid = _clean_id(path[len("/share/"):].split("/")[0])
        return f"https://www.loom.com/embed/{vid}" if vid else ""
    if host in ("facebook.com", "fb.watch"):
        return ("https://www.facebook.com/plugins/video.php?show_text=false&href="
                + quote(u, safe=""))
    return ""


def player_html(s: Dict[str, Any]) -> str:
    parts = []
    video = (s.get("video_url") or "").strip()
    src = video_embed_src(video)
    if src:
        parts.append(f'<div class="sm-video"><iframe src="{_esc(src)}" title="{_esc(s.get("title"))}" '
                     f'loading="lazy" allowfullscreen allow="autoplay; fullscreen; picture-in-picture; encrypted-media">'
                     f'</iframe></div>')
    elif video:
        parts.append(f'<p><a class="sm-go" href="{_esc(video)}" target="_blank" rel="noopener">Watch this message</a></p>')
    audio = (s.get("audio_url") or "").strip()
    if audio:
        parts.append(f'<audio class="sm-audio" controls preload="none" src="{_esc(audio)}">'
                     f'<a href="{_esc(audio)}">Listen</a></audio>')
    return "".join(parts)


def day_label(iso: Any) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return ""
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def sermons_are_public(sermons: List[Dict[str, Any]]) -> bool:
    return any(s.get("published") for s in sermons)


def _meta(s: Dict[str, Any], series_title: str = "") -> str:
    bits = [day_label(s.get("preached_on")), s.get("speaker") or "", s.get("scripture") or ""]
    if series_title:
        bits.append(series_title)
    return " · ".join(_esc(b) for b in bits if b)


def _row(s: Dict[str, Any], base: str) -> str:
    return (f'<li><a class="sm-row" href="{_esc(base)}/sermons/{_esc(s["id"])}">'
            f'<span class="sm-row-title">{_esc(s.get("title"))}</span>'
            f'<span class="sm-muted">{_meta(s)}</span></a></li>')


def _shell(business: Dict[str, Any], site, title: str, description: str, canonical: str, body: str) -> str:
    from public_form_theme import resolve_theme, css_vars as theme_css, font_links
    name = (business.get("name") or "").strip() or "Sermons"
    theme = resolve_theme(business, site)
    logo = theme.get("logo_url") or ""
    logo_html = f'<img class="sm-logo" src="{_esc(logo)}" alt="{_esc(name)} logo">' if logo else ""
    og = (f'<meta property="og:image" content="{_esc(logo)}"><link rel="icon" href="{_esc(logo)}">' if logo else "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_esc(title)}</title>
<meta name="description" content="{_esc(description)}">
<link rel="canonical" href="{_esc(canonical)}">
<meta property="og:title" content="{_esc(title)}">
<meta property="og:description" content="{_esc(description)}">
<meta property="og:url" content="{_esc(canonical)}">
<meta property="og:type" content="website">
{og}
{font_links(theme)}
<style>{theme_css(theme)}</style>
<style>
html,body{{margin:0;padding:0;font-family:var(--font-body);color:var(--text-primary);background:var(--surface);min-height:100vh;}}
*{{box-sizing:border-box;}}
.sm-shell{{max-width:760px;margin:0 auto;padding:28px 16px 48px;}}
.sm-header{{text-align:center;margin-bottom:24px;}}
.sm-logo{{max-width:80px;max-height:80px;display:block;margin:0 auto 10px;}}
.sm-name{{font-family:var(--font-heading);font-size:22px;font-weight:700;margin:0;}}
.sm-name a{{color:inherit;text-decoration:none;}}
.sm-kicker{{font-size:13px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin:6px 0 0;}}
.sm-h1{{font-family:var(--font-heading);font-size:28px;line-height:1.2;margin:4px 0 6px;text-wrap:balance;}}
.sm-h2{{font-family:var(--font-heading);font-size:20px;margin:30px 0 10px;}}
.sm-muted{{color:var(--text-secondary);font-size:14px;line-height:1.5;}}
.sm-when{{font-size:12px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--accent);}}
.sm-video{{position:relative;width:100%;aspect-ratio:16/9;border-radius:var(--radius);overflow:hidden;background:#000;margin:14px 0;}}
.sm-video iframe{{position:absolute;inset:0;width:100%;height:100%;border:0;}}
.sm-audio{{width:100%;margin:10px 0;}}
.sm-card{{border:1px solid var(--border);border-radius:var(--radius);padding:18px 16px;margin-bottom:16px;}}
.sm-card>:first-child{{margin-top:0;}}.sm-card>:last-child{{margin-bottom:0;}}
.sm-text{{font-size:16px;line-height:1.65;white-space:pre-line;}}
.sm-list{{list-style:none;margin:0;padding:0;border-top:1px solid var(--border);}}
.sm-row{{display:flex;flex-direction:column;gap:2px;padding:14px 4px;border-bottom:1px solid var(--border);color:inherit;text-decoration:none;min-height:48px;}}
.sm-row:hover .sm-row-title{{text-decoration:underline;}}
.sm-row-title{{font-weight:700;font-size:16px;}}
.sm-series-about{{margin:-4px 0 10px;}}
.sm-go{{display:inline-block;padding:12px 20px;border-radius:var(--radius);background:var(--accent);color:var(--accent-text);font-weight:700;text-decoration:none;min-height:44px;}}
.sm-back{{display:inline-block;margin-bottom:10px;color:var(--text-secondary);font-size:14px;min-height:32px;}}
.sm-empty{{text-align:center;padding:32px 16px;color:var(--text-secondary);border:1px dashed var(--border);border-radius:16px;}}
.sm-footer{{text-align:center;font-size:11px;color:var(--text-muted);margin-top:32px;padding-top:14px;border-top:1px solid var(--border);}}
.sm-footer a{{color:var(--text-muted);text-decoration:none;}}
a:focus-visible,.sm-row:focus-visible{{outline:2px solid var(--focus);outline-offset:3px;}}
</style>
</head>
<body>
<main class="sm-shell">
  <header class="sm-header">
    {logo_html}
    <p class="sm-name"><a href="/">{_esc(name)}</a></p>
    <p class="sm-kicker">Sermons</p>
  </header>
  {body}
  <footer class="sm-footer">Powered by <a href="https://mysolutionist.app/" target="_blank" rel="noopener">Solutionist</a></footer>
</main>
</body>
</html>"""


def render_library(business: Dict[str, Any], sermons: List[Dict[str, Any]], series: List[Dict[str, Any]],
                   canonical: str, site=None, base: str = "") -> str:
    """/sermons. `sermons` newest first; only published ones are shown."""
    name = (business.get("name") or "").strip() or "Our church"
    pub = [s for s in sermons if s.get("published")]
    titles = {str(x["id"]): x.get("title") or "" for x in series}
    if not pub:
        body = '<div class="sm-empty">No messages are posted yet. Check back soon.</div>'
        return _shell(business, site, f"Sermons — {name}", f"Messages from {name}.", canonical, body)
    latest = pub[0]
    body = [
        '<section aria-labelledby="sm-latest">',
        '<p class="sm-when">Latest message</p>',
        f'<h1 class="sm-h1" id="sm-latest"><a href="{_esc(base)}/sermons/{_esc(latest["id"])}" style="color:inherit">{_esc(latest.get("title"))}</a></h1>',
        f'<p class="sm-muted">{_meta(latest, titles.get(str(latest.get("series_id")), ""))}</p>',
        player_html(latest),
        f'<p class="sm-text">{_esc(latest.get("summary"))}</p>' if latest.get("summary") else "",
        '</section>',
    ]
    by_series: Dict[str, List[Dict[str, Any]]] = {}
    loose: List[Dict[str, Any]] = []
    for s in pub:
        sid = str(s.get("series_id") or "")
        (by_series.setdefault(sid, []) if sid in titles else loose).append(s)
    # Series in the order their newest message was preached.
    for sid in sorted(by_series, key=lambda k: str(by_series[k][0].get("preached_on")), reverse=True):
        about = next((x.get("description") for x in series if str(x["id"]) == sid), "") or ""
        body.append(f'<section aria-labelledby="sm-s-{_esc(sid)}"><h2 class="sm-h2" id="sm-s-{_esc(sid)}">{_esc(titles[sid])}</h2>')
        if about:
            body.append(f'<p class="sm-muted sm-series-about">{_esc(about)}</p>')
        body.append('<ul class="sm-list">' + "".join(_row(s, base) for s in by_series[sid]) + '</ul></section>')
    if loose:
        heading = "More messages" if by_series else "All messages"
        body.append(f'<section aria-labelledby="sm-more"><h2 class="sm-h2" id="sm-more">{heading}</h2>'
                    '<ul class="sm-list">' + "".join(_row(s, base) for s in loose) + '</ul></section>')
    return _shell(business, site, f"Sermons — {name}", f"Watch and listen to messages from {name}.", canonical, "".join(body))


def render_sermon(business: Dict[str, Any], sermon: Dict[str, Any], sermons: List[Dict[str, Any]],
                  series: List[Dict[str, Any]], canonical: str, site=None, base: str = "") -> str:
    """/sermons/<id> — one published message."""
    name = (business.get("name") or "").strip() or "Our church"
    titles = {str(x["id"]): x.get("title") or "" for x in series}
    sid = str(sermon.get("series_id") or "")
    body = [
        f'<a class="sm-back" href="{_esc(base)}/sermons">← All sermons</a>',
        f'<p class="sm-when">{_esc(titles.get(sid) or "Message")}</p>',
        f'<h1 class="sm-h1">{_esc(sermon.get("title"))}</h1>',
        f'<p class="sm-muted">{_meta(sermon)}</p>',
        player_html(sermon),
    ]
    if sermon.get("summary"):
        body.append(f'<section class="sm-card" aria-label="About this message"><p class="sm-text">{_esc(sermon["summary"])}</p></section>')
    if sermon.get("questions"):
        body.append('<section class="sm-card" aria-labelledby="sm-q"><h2 class="sm-h2" id="sm-q" style="margin-top:0">'
                    f'For your group this week</h2><p class="sm-text">{_esc(sermon["questions"])}</p></section>')
    if sid in titles:
        others = [s for s in sermons if s.get("published") and str(s.get("series_id")) == sid and s["id"] != sermon["id"]]
        if others:
            body.append(f'<h2 class="sm-h2">More in {_esc(titles[sid])}</h2><ul class="sm-list">'
                        + "".join(_row(s, base) for s in others) + '</ul>')
    desc = (sermon.get("summary") or f"A message from {name}.")[:180]
    return _shell(business, site, f"{sermon.get('title')} — {name}", desc, canonical, "".join(body))


def render_unavailable(business: Dict[str, Any], canonical: str, site=None) -> str:
    name = (business.get("name") or "").strip() or "This church"
    body = (f'<div class="sm-empty">{_esc(name)} hasn\'t posted any messages here yet. '
            f'<br><a href="/">Back to the home page</a></div>')
    return _shell(business, site, f"Sermons — {name}", f"Messages from {name}.", canonical, body)
