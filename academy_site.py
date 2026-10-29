"""The website's class list and class pages (step 4 of the Class Schedule).

People choose a class knowing what it asks of them: when it meets, how its
lessons open, and what happens each week (class nights, homework past the
slides, discussions, project steps, gatherings), before they sign up. A
program (The Making) leads the list as one journey with its tracks' dates.

public_site._serve_academy reads the rows (service role, published only)
and calls these pure builders for the words and the HTML pieces; nothing
here reads the database. Times are said in the class's own zone
(academy_courses.opens_tz), else the business's.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape as _esc
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


def _when(value: Any) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _local(dt: datetime, zone: str) -> datetime:
    try:
        return dt.astimezone(ZoneInfo(zone)) if ZoneInfo and zone else dt
    except Exception:
        return dt


def clock(dt: datetime) -> str:
    """'6 PM', '6:30 PM'."""
    h = dt.hour % 12 or 12
    return f"{h}{f':{dt.minute:02d}' if dt.minute else ''} {'AM' if dt.hour < 12 else 'PM'}"


def day(dt: datetime) -> str:
    """'Thu Oct 22'."""
    return f"{dt.strftime('%a %b')} {dt.day}"


def together(course: Dict[str, Any]) -> bool:
    return (course.get("drip_mode") in ("weekly", "custom")) and _when(course.get("opens_from")) is not None


def week_opens(course: Dict[str, Any], idx: int, offset_days: int, zone: str) -> Optional[datetime]:
    """When lesson idx opens for everyone in a class that runs together, on its own clock."""
    start = _when(course.get("opens_from"))
    if not together(course) or start is None:
        return None
    days = idx * 7 if course.get("drip_mode") == "weekly" else max(0, int(offset_days or 0))
    return _local(start, course.get("opens_tz") or zone) + timedelta(days=days)


def when_line(course: Dict[str, Any], zone: str, now: Optional[datetime] = None) -> str:
    """The card's first line: when it meets, or how it runs."""
    now = now or datetime.now(timezone.utc)
    drip = course.get("drip_mode") or "none"
    start = _when(course.get("opens_from"))
    if together(course) and start is not None:
        local = _local(start, course.get("opens_tz") or zone)
        if drip == "weekly":
            return f"{local.strftime('%A')}s {clock(local)}, {'from' if start > now else 'since'} {local.strftime('%b')} {local.day}"
        return f"{'From' if start > now else 'Since'} {day(local)}"
    if drip == "weekly":
        return "One lesson a week, start any time"
    if drip == "custom":
        return "On its own schedule, start any time"
    return "Start any time"


def pace_line(course: Dict[str, Any], lesson_count: int) -> str:
    drip = course.get("drip_mode") or "none"
    n = f"{lesson_count} {'week' if drip == 'weekly' else 'lesson'}{'s' if lesson_count != 1 else ''}"
    if drip == "none":
        return f"All {lesson_count} lesson{'s' if lesson_count != 1 else ''} open when you join"
    if together(course):
        return f"One lesson a week, together · {n}" if drip == "weekly" else f"Lessons open together · {n}"
    return f"One lesson a week from the day you join · {n}" if drip == "weekly" else f"Lessons open on a schedule · {n}"


def involves_line(items: List[Dict[str, Any]], lesson_count: int) -> str:
    """What it asks of you, in a few words: homework, discussions, a project, gatherings."""
    homework = [i for i in items if i.get("kind") == "homework" and not i.get("project_id")]
    steps = [i for i in items if i.get("kind") == "homework" and i.get("project_id")]
    projects = {i.get("project_id") for i in steps}
    discussions = [i for i in items if i.get("kind") == "discussion"]
    gatherings = [i for i in items if i.get("kind") == "gathering"]
    parts: List[str] = []
    if homework:
        parts.append("Weekly homework" if lesson_count and len(homework) >= lesson_count * 0.75 else
                     f"{len(homework)} piece{'s' if len(homework) != 1 else ''} of homework")
    if discussions:
        parts.append("a discussion each week" if lesson_count and len(discussions) >= lesson_count * 0.75 else
                     f"{len(discussions)} discussion{'s' if len(discussions) != 1 else ''}")
    if projects:
        parts.append("one project" if len(projects) == 1 else f"{len(projects)} projects")
    if gatherings:
        parts.append("one gathering" if len(gatherings) == 1 else f"{len(gatherings)} gatherings")
    if not parts:
        return ""
    line = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    return line[0].upper() + line[1:]


def week_rows(course: Dict[str, Any], lessons: List[Dict[str, Any]], items: List[Dict[str, Any]],
              sessions: List[Dict[str, Any]], zone: str) -> List[Dict[str, Any]]:
    """Each lesson as a week: its date when the class runs together, and its tags."""
    projects = {i["id"]: i for i in items if i.get("kind") == "project"}
    step_no: Dict[str, int] = {}
    for pid in projects:
        for k, s in enumerate(sorted((i for i in items if i.get("project_id") == pid), key=lambda i: i.get("position") or 0)):
            step_no[s["id"]] = k + 1
    tz = course.get("opens_tz") or zone
    rows = []
    for idx, lesson in enumerate(lessons):
        tags: List[Tuple[str, str]] = []
        for s in sessions:
            at = _when(s.get("starts_at"))
            if s.get("lesson_id") == lesson.get("id") and at and s.get("status") in ("scheduled", "live", "ended"):
                local = _local(at, tz)
                tags.append(("live", f"Class {local.strftime('%a')} {clock(local)}"))
        for i in sorted((i for i in items if i.get("lesson_id") == lesson.get("id")), key=lambda i: i.get("position") or 0):
            kind = i.get("kind")
            title = (i.get("title") or "").strip()
            if kind == "discussion":
                tags.append(("discussion", "Discussion"))
            elif kind == "gathering":
                at = _when(i.get("starts_at"))
                tags.append(("gathering", f"{title} {_local(at, tz).strftime('%a')} {clock(_local(at, tz))}" if at else title))
            elif kind == "homework" and i.get("project_id") in projects:
                tags.append(("project", f"{projects[i['project_id']].get('title') or 'Project'}, step {step_no.get(i['id'], 1)}"))
            elif kind == "homework":
                tags.append(("homework", title if len(title) <= 60 else title[:58].rstrip() + "…"))
        opens = week_opens(course, idx, lesson.get("drip_offset_days") or 0, zone)
        rows.append({"n": idx + 1, "title": lesson.get("title") or f"Lesson {idx + 1}",
                     "date": day(opens) if opens else "", "tags": tags})
    return rows


_TAG_DOT = {"live": "var(--ac)", "discussion": "#2f6f6a", "homework": "#6a4c8c", "project": "#b4532a", "gathering": "#5c3a55"}

SITE_CSS = """
  .ac-facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 0; margin-top: 22px;
    border: 1px solid rgba(29,27,22,0.10); border-radius: 14px; overflow: hidden; }
  .ac-fact { padding: 12px 16px; border-right: 1px solid rgba(29,27,22,0.10); }
  .ac-fact:last-child { border-right: 0; }
  .ac-fact b { display: block; font-size: 16px; }
  .ac-fact span { font-size: 12.5px; }
  .ac-weeks { margin-top: 30px; }
  .ac-weeks h2 { font-size: 22px; margin-bottom: 4px; }
  .ac-week { display: grid; grid-template-columns: 112px minmax(0, 1fr); gap: 14px; padding: 16px 0; border-top: 1px solid rgba(29,27,22,0.10); }
  .ac-week .wn { font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; }
  .ac-week .wd { font-size: 12.5px; }
  .ac-week h3 { font-size: 17px; margin: 0 0 8px; line-height: 1.3; }
  .ac-tags { display: flex; flex-wrap: wrap; gap: 6px; }
  .ac-tag { display: inline-flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; padding: 4px 10px; border-radius: 999px;
    border: 1px solid rgba(29,27,22,0.12); background: rgba(255,255,255,0.6); }
  .ac-tag i { width: 7px; height: 7px; border-radius: 50%; display: inline-block; }
  .ac-late { margin-top: 12px; font-size: 13.5px; }
  .ac-program { margin-top: 26px; padding: 22px 24px; border-radius: 18px; color: #fff; }
  .ac-program .k { font-size: 11px; font-weight: 700; letter-spacing: 2px; text-transform: uppercase; opacity: .85; }
  .ac-program h2 { font-size: clamp(24px, 4vw, 32px); margin: 4px 0 4px; }
  .ac-program p { font-size: 14px; opacity: .9; }
  .ac-tracks { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin: 16px 0; }
  .ac-track { padding: 10px 12px; border-radius: 12px; background: rgba(255,255,255,0.12); text-decoration: none; color: inherit; display: block; }
  .ac-track b { display: block; font-size: 15px; }
  .ac-track span { font-size: 12.5px; opacity: .85; }
  .ac-program .btn { background: #fff !important; color: #1d1b16 !important; padding: 12px 22px; }
  .card .ac-lines { display: flex; flex-direction: column; gap: 4px; margin: 4px 0 12px; font-size: 13px; }
  .card .ac-lines b { font-size: 13.5px; }
  @media (prefers-color-scheme: dark) {
    .ac-facts, .ac-fact, .ac-week, .ac-tag { border-color: rgba(255,255,255,0.10) !important; }
    .ac-tag { background: rgba(255,255,255,0.04); }
  }
  @media (max-width: 560px) {
    .ac-week { grid-template-columns: minmax(0, 1fr); gap: 4px; }
    .ac-fact { border-right: 0; border-bottom: 1px solid rgba(29,27,22,0.10); }
  }
"""


def facts_html(course: Dict[str, Any], lessons: List[Dict[str, Any]], items: List[Dict[str, Any]], zone: str) -> str:
    n = len(lessons)
    drip = course.get("drip_mode") or "none"
    facts = [(when_line(course, zone), "When")]
    facts.append((f"{n} {'week' if drip == 'weekly' else 'lesson'}{'s' if n != 1 else ''}",
                  "One lesson a week, together" if together(course) and drip == "weekly"
                  else "One a week from the day you join" if drip == "weekly" else "All open when you join" if drip == "none" else "On its own schedule"))
    involves = involves_line(items, n)
    if involves:
        facts.append((involves.split(",")[0].split(" and ")[0], "Each week" if "Weekly" in involves else "Along the way"))
    return '<div class="ac-facts">' + "".join(
        f'<div class="ac-fact"><b>{_esc(a)}</b><span class="muted">{_esc(b)}</span></div>' for a, b in facts) + "</div>"


def weeks_html(rows: List[Dict[str, Any]], accent: str, unit: str) -> str:
    if not rows:
        return ""
    out = [f'<section class="ac-weeks" aria-label="{_esc(unit)} by {_esc(unit.lower())}"><h2>{_esc(unit)} by {_esc(unit.lower())}</h2>']
    for r in rows:
        tags = "".join(
            f'<span class="ac-tag"><i style="background:{_TAG_DOT.get(k, accent).replace("var(--ac)", accent)}"></i>{_esc(t)}</span>'
            for k, t in r["tags"])
        out.append(
            f'<div class="ac-week"><div><div class="wn" style="color:{accent}">{_esc(unit)} {r["n"]}</div>'
            f'<div class="wd muted">{_esc(r["date"])}</div></div>'
            f'<div><h3>{_esc(r["title"])}</h3>{f"<div class=ac-tags>{tags}</div>" if tags else ""}</div></div>')
    out.append("</section>")
    return "".join(out)


def program_html(program: Dict[str, Any], tracks: List[Dict[str, Any]], accent: str, course_href, zone: str) -> str:
    """The program as one journey: its tracks with their dates, and where to start."""
    if len(tracks) < 2:
        return ""
    cells = []
    for t in tracks:
        dates = t.get("dates") or ""
        cells.append(f'<a class="ac-track" href="{_esc(course_href(t["id"]))}"><b>{_esc(t["name"])}</b>'
                     f'<span>{_esc(dates)}</span></a>')
    first = tracks[0]
    finish = ""
    fin = _when(program.get("finish_at"))
    if fin:
        local = _local(fin, zone)
        finish = f", ending with {(program.get('finish_title') or 'graduation').lower()} on {local.strftime('%B')} {local.day}"
    return (f'<section class="ac-program" style="background:{accent}" aria-label="{_esc(program.get("title") or "Program")}">'
            f'<div class="k">A program · {len(tracks)} tracks</div><h2>{_esc(program.get("title") or "")}</h2>'
            f'<p>Take the tracks in order{_esc(finish)}.</p>'
            f'<div class="ac-tracks">{"".join(cells)}</div>'
            f'<a class="btn" href="{_esc(course_href(first["id"]))}">Start with {_esc(first["name"])}</a></section>')


def track_name(title: str, program_title: str) -> str:
    """'The Making: Foundation' → 'Foundation' inside its program."""
    t = (title or "").strip()
    p = (program_title or "").strip()
    if p and t.lower().startswith(p.lower()):
        rest = t[len(p):].lstrip(" :–-·")
        return rest or t
    return t
