"""
group_study.py — this week's study: questions from Sunday's message.

From the approved canvas "Church Groups, Together" (boards Meet, Lead,
Settings and Main: "Questions from Sunday's message: Chief drafts them each
week; Tasha approves before the group sees them").

  * each week, for the church's newest published message in Sermons
    (preached in the last 8 days), every group with study on and a leader
    gets a draft: the office's own "questions for small groups" when the
    message has them, else four Chief drafts from its title, passage and
    summary (one model call per message, shared by every group)
  * a group's leaders see the draft on the Meet tab: post it as it is, or
    change, add or take out questions first. Nothing reaches the group
    until a leader posts it, and what's posted is checked like a Board post
  * the group sees "From Sunday" on the Meet tab and a line on the group's
    Home: the message, its passage (a link into the Bible), the questions,
    who approved them, the way to the message itself; one note when it's
    posted; the 5 PM reminder names it
  * the office turns it off per group (groups.study_on)

A draft is made once per group per message: changing the message's
questions in Sermons afterwards doesn't redraft. The scheduled job is
group_study_drafts (kmj_intake_automation); the routes live in
member_portal_groups (/my/groups/meet/study).
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

MODEL = os.environ.get("GROUP_STUDY_MODEL") or "claude-sonnet-5-5"
RECENT = timedelta(days=8)     # "Sunday's message": preached in the last 8 days
SHOWN = timedelta(days=14)     # a posted study stays up two weeks at most
Q_MAX, QS_MAX, DRAFT_N = 300, 8, 4

PROMPT = """You help a church small group talk through the message their pastor preached on Sunday.

You get the message's title, its scripture passage, the series it belongs to, and the church office's short summary when there is one. Write exactly 4 questions the group's leader can ask at this week's gathering.

- Ground every question in the passage and in what the title and summary say. Never invent what the pastor said, quote the sermon, or add teaching of your own.
- Open questions people answer from their own lives, never yes or no. Plain words a new believer understands.
- In order: one about what the passage says, one about what it means, one about where it meets this week, one practical step to take before the group meets again.
- Each question is one sentence, at most 25 words. No numbering, no names, no emoji.
- Capitalize He, His and Him when they mean God or Jesus.

Return only a JSON array of 4 strings."""


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clean(questions: List[str]) -> List[str]:
    """Trimmed, de-numbered, non-empty, at most 8 of at most 300 characters."""
    out: List[str] = []
    for q in questions:
        q = re.sub(r"^\s*(?:\d{1,2}\s*[.)]|[-•*–])\s*", "", str(q or ""))
        q = " ".join(q.split())[:Q_MAX].rstrip()
        if q:
            out.append(q)
    return out[:QS_MAX]


def split_questions(text: str) -> List[str]:
    """The office's "questions for small groups": one per line, or several
    on a line each ending in a question mark."""
    parts: List[str] = []
    for line in re.split(r"[\r\n]+", text or ""):
        parts += re.split(r"(?<=\?)\s+(?=\S)", line.strip()) if line.count("?") > 1 else [line]
    return clean(parts)


def parse_draft(raw: str) -> Optional[List[str]]:
    """The model's JSON array, or None when it isn't one (3 to 8 questions)."""
    a, b = (raw or "").find("["), (raw or "").rfind("]")
    if a < 0 or b <= a:
        return None
    try:
        got = json.loads(raw[a:b + 1])
    except ValueError:
        return None
    if not isinstance(got, list) or not all(isinstance(x, str) for x in got):
        return None
    qs = clean(got)
    return qs if 3 <= len(qs) else None


def draft(business_id: str, sermon: Dict[str, Any], series: str) -> Optional[List[str]]:
    """Four questions from Chief, or None (no key, an outage, a refusal):
    the next run tries again, and nothing shows until then."""
    import httpx
    import llm_call
    import model_ladder
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    facts = "\n".join(f"<{k}>{str(v)[:2000]}</{k}>" for k, v in (
        ("title", sermon.get("title")), ("scripture", sermon.get("scripture")), ("series", series),
        ("summary", sermon.get("summary"))) if v)
    payload = {"model": MODEL, "max_tokens": 900, **model_ladder.thinking_off_kwargs(MODEL),
               "system": [{"type": "text", "text": PROMPT, "cache_control": {"type": "ephemeral"}}],
               "messages": [{"role": "user", "content": facts}]}
    try:
        with httpx.Client() as client:
            # Proactive work nobody asked for: counted, never billed (units=0).
            resp = llm_call.post_with(client, payload, timeout=60, task="group_study", business_id=str(business_id),
                                      units=0)
        if resp.status_code != 200:
            logger.warning("group study draft: http %s", resp.status_code)
            return None
        body = resp.json()
        if body.get("stop_reason") == "refusal":
            return None
        return parse_draft(llm_call.text_of(body))
    except Exception:
        logger.warning("group study draft failed", exc_info=True)
        return None


# ─── the weekly drafts (scheduled: group_study_drafts) ───────────────


def _series_title(business_id: str, series_id: Any) -> Optional[str]:
    if not series_id:
        return ""
    rows = sb_clients.sb_get_as_service(
        f"/sermon_series?id=eq.{_q(series_id)}&business_id=eq.{_q(business_id)}&select=title&limit=1")
    if not isinstance(rows, list):
        return None
    return str(rows[0].get("title") or "") if rows else ""


def sweep_tick(today: Optional[date] = None) -> int:
    """Drafts for every church's newest message. Returns how many groups got
    one."""
    today = today or _now().date()
    sermons = sb_clients.sb_get_as_service(
        f"/sermons?published=eq.true&preached_on=gte.{(today - RECENT).isoformat()}&preached_on=lte.{today.isoformat()}"
        f"&select=id,business_id,series_id,title,scripture,summary,questions,preached_on"
        f"&order=preached_on.desc,created_at.desc&limit=1000")
    if not isinstance(sermons, list):
        return 0
    newest: Dict[str, Dict[str, Any]] = {}
    for s in sermons:
        newest.setdefault(str(s["business_id"]), s)
    made = 0
    for biz_id, s in newest.items():
        try:
            made += _drafts_for(biz_id, s)
        except Exception:
            logger.warning("group study drafts failed for one church", exc_info=True)
    return made


def _drafts_for(biz_id: str, s: Dict[str, Any]) -> int:
    b = _q(biz_id)
    groups = sb_clients.sb_get_as_service(f"/groups?business_id=eq.{b}&active=eq.true&study_on=eq.true&select=id&limit=1000")
    leads = sb_clients.sb_get_as_service(f"/group_members?business_id=eq.{b}&role=eq.leader&select=group_id&limit=5000")
    have = sb_clients.sb_get_as_service(
        f"/group_studies?business_id=eq.{b}&sermon_id=eq.{_q(s['id'])}&select=group_id,source,drafted&limit=1000")
    if not isinstance(groups, list) or not isinstance(leads, list) or not isinstance(have, list):
        return 0
    led = {str(r["group_id"]) for r in leads}
    done = {str(r["group_id"]) for r in have}
    want = [str(g["id"]) for g in groups if str(g["id"]) in led and str(g["id"]) not in done]
    if not want:
        return 0
    qs, source = split_questions(s.get("questions") or ""), "office"
    if not qs:
        source = "chief"
        qs = next((clean(h["drafted"]) for h in have if h.get("source") == "chief" and h.get("drafted")), [])
        if not qs:
            series = _series_title(biz_id, s.get("series_id"))
            if series is None:
                return 0
            qs = draft(biz_id, s, series) or []
    if not qs:
        return 0
    rows = sb_clients.sb_post_as_service(
        "/group_studies?on_conflict=group_id,sermon_id",
        [{"business_id": biz_id, "group_id": g, "sermon_id": str(s["id"]), "source": source, "drafted": qs, "questions": qs}
         for g in want],
        prefer="resolution=ignore-duplicates,return=representation")
    return len(rows) if isinstance(rows, list) else 0


# ─── reading ─────────────────────────────────────────────────────────

SERMON = "id,title,scripture,series_id,preached_on,video_url,audio_url,published"


def view(business: Dict[str, Any], g: Dict[str, Any], *, leader: bool, today: Optional[date] = None
         ) -> Optional[Dict[str, Any]]:
    """{'study', 'sermon', 'series'} for this group, {} when there's none to
    show, None when a read failed. Members see a posted study only; a leader
    also sees the draft waiting for them."""
    if g.get("study_on") is False:
        return {}
    today = today or _now().date()
    biz_id = str(business["id"])
    rows = sb_clients.sb_get_as_service(
        f"/group_studies?business_id=eq.{_q(biz_id)}&group_id=eq.{_q(g['id'])}"
        f"&select=id,sermon_id,source,questions,posted_at,posted_by,created_at&order=created_at.desc&limit=3")
    if not isinstance(rows, list):
        return None
    for r in rows:
        if not r.get("posted_at") and not leader:
            continue
        got = sb_clients.sb_get_as_service(
            f"/sermons?id=eq.{_q(r['sermon_id'])}&business_id=eq.{_q(biz_id)}&published=eq.true&select={SERMON}&limit=1")
        if not isinstance(got, list):
            return None
        if not got:
            continue
        s = got[0]
        if date.fromisoformat(str(s["preached_on"])[:10]) < today - SHOWN:
            return {}
        series = _series_title(biz_id, s.get("series_id"))
        if series is None:
            return None
        return {"study": r, "sermon": s, "series": series}
    return {}


def posted_title(business_id: str, group_id: str, today: Optional[date] = None) -> str:
    """The posted study's message title, for the 5 PM reminder ('' when
    none, or the read failed)."""
    st = view({"id": business_id}, {"id": group_id}, leader=False, today=today) or {}
    return str((st.get("sermon") or {}).get("title") or "")


# ─── writing ─────────────────────────────────────────────────────────


async def post(business: Dict[str, Any], me: Dict[str, Any], group_id: str, study_id: str,
               questions: Optional[List[str]]) -> Tuple[bool, str]:
    """A leader posts the draft as it is (`questions` None), or their own
    version of it; after posting, a change saves without a second note."""
    import asyncio
    import group_gatherings as gg
    import msg_screen
    g, _, role = await asyncio.to_thread(gg._ready, business, me, group_id, leader=True)
    if not g:
        return False, role
    biz_id = str(business["id"])
    rows = await asyncio.to_thread(
        sb_clients.sb_get_as_service,
        f"/group_studies?id=eq.{_q(study_id)}&business_id=eq.{_q(biz_id)}&group_id=eq.{_q(g['id'])}"
        f"&select=id,sermon_id,questions,posted_at&limit=1")
    if not isinstance(rows, list):
        return False, "error"
    if not rows:
        return False, "study_gone"
    row = rows[0]
    qs = clean(questions) if questions is not None else clean(row.get("questions") or [])
    if not qs:
        return False, "study_empty"
    try:
        verdict = await msg_screen.screen(biz_id, "\n".join(qs))
    except msg_screen.ScreenUnavailable:
        return False, "post_busy"
    if verdict != "ok":
        return False, "post_no"
    first = not row.get("posted_at")
    now = _now().isoformat()
    body: Dict[str, Any] = {"questions": qs, "updated_at": now}
    if first:
        body.update(posted_at=now, posted_by=str(me["id"]))
    saved = await asyncio.to_thread(
        sb_clients.sb_patch_as_service, f"/group_studies?id=eq.{_q(row['id'])}&business_id=eq.{_q(biz_id)}", body)
    if not isinstance(saved, list) or not saved:
        return False, "error"
    if not first:
        return True, "study_saved"
    await asyncio.to_thread(_tell, business, g, row, str(me["id"]))
    return True, "study_posted"


def _tell(business: Dict[str, Any], g: Dict[str, Any], row: Dict[str, Any], me_id: str) -> None:
    """One note to the group (never the leader who posted it)."""
    import member_push
    members = sb_clients.sb_get_as_service(
        f"/group_members?business_id=eq.{_q(business['id'])}&group_id=eq.{_q(g['id'])}&select=contact_id&limit=5000")
    sermon = sb_clients.sb_get_as_service(
        f"/sermons?id=eq.{_q(row['sermon_id'])}&business_id=eq.{_q(business['id'])}&select=title&limit=1")
    who = [str(m["contact_id"]) for m in (members or []) if str(m["contact_id"]) != me_id]
    if not who:
        return
    title = str((sermon or [{}])[0].get("title") or "Sunday’s message")
    member_push.send(business, "groups", title=str(g.get("name") or "Your group"),
                     body=f"This week’s study: {title}. Questions from Sunday’s message.",
                     url=f"/my/groups/{g['id']}/meet", contact_ids=who, ref_id=f"study:{row['id']}", tag=f"study-{g['id']}")


# ─── the Meet tab ────────────────────────────────────────────────────

STUDY_CSS = """
.gy-chief{background:var(--violet-deep);gap:10px;}
.gy-chief-h{display:flex;align-items:center;gap:8px;font-size:12.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--violet-ink);}
.gy-chief p{margin:0;font-size:15px;line-height:1.45;}
.gy-study{background:var(--gold-deep);}
.gy-eb{margin:0;font-size:12.5px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--gold-ink);}
.gy-study h3{margin:0;font-size:20px;font-weight:700;letter-spacing:-.022em;line-height:1.2;}
.gy-ref{margin:0;font-family:var(--mb-serif);font-style:italic;font-size:15.5px;color:var(--fg2);}
.gy-ref a{color:inherit;}
.gy-qs{display:flex;flex-direction:column;gap:10px;margin:0;padding:0;list-style:none;counter-reset:q;}
.gy-qs li{display:flex;gap:12px;font-size:15px;line-height:1.42;}
.gy-qs li::before{counter-increment:q;content:counter(q);flex:none;width:26px;height:26px;border-radius:50%;background:var(--gold);color:var(--on-gold);
  font-size:13px;font-weight:750;display:grid;place-items:center;}
.gy-by{margin:0;padding-top:6px;border-top:.5px solid var(--line);font-size:12.5px;color:var(--fg2);}
.gy-edit summary{list-style:none;cursor:pointer;}
.gy-edit summary::-webkit-details-marker{display:none;}
.gy-edit form{display:flex;flex-direction:column;gap:8px;margin-top:10px;}
.gy-edit textarea{min-height:64px;border:0;outline:none;border-radius:var(--r-md);background:var(--bg);color:var(--fg);padding:10px 12px;
  font:inherit;font-size:15px;line-height:1.4;resize:vertical;box-shadow:inset 0 0 0 1px var(--line);}
.gy-edit label{font-size:12.5px;font-weight:650;color:var(--fg2);}
.gy-acts{display:flex;gap:8px;flex-wrap:wrap;align-items:center;}
.gy-acts form{margin:0;}
"""


def _questions_form(gid: str, sid: str, qs: List[str], label: str, esc) -> str:
    boxes = "".join(
        f'<label for="gy-q{i}">Question {i + 1}</label>'
        f'<textarea id="gy-q{i}" name="q" maxlength="{Q_MAX}">{esc(q)}</textarea>' for i, q in enumerate(qs))
    n = len(qs)
    if n < QS_MAX:
        boxes += (f'<label for="gy-q{n}">Add a question (optional)</label>'
                  f'<textarea id="gy-q{n}" name="q" maxlength="{Q_MAX}"></textarea>')
    return (f'<form method="post" action="/my/groups/meet/study"><input type="hidden" name="group_id" value="{gid}">'
            f'<input type="hidden" name="study" value="{sid}"><input type="hidden" name="edited" value="1">{boxes}'
            f'<p class="gm-fine">Empty a box to take that question out.</p>'
            f'<button class="gs-btn sm" type="submit">{label}</button></form>')


def render(g: Dict[str, Any], st: Optional[Dict[str, Any]], *, leader: bool, people: List[Dict[str, Any]],
           next_day: Optional[date], ic, esc, name) -> str:
    """The Chief card for a leader's draft, or the group's study card."""
    import group_gatherings as gg
    import member_portal_bible as mpb
    if not st or not st.get("study"):
        return ""
    r, s = st["study"], st["sermon"]
    gid, sid = esc(g["id"]), esc(r["id"])
    qs = clean(r.get("questions") or [])
    title = esc(s.get("title") or "Sunday’s message")
    if not r.get("posted_at"):
        when = f"for {gg.DAYS[next_day.weekday()]}" if next_day else "for your next gathering"
        n = len(qs)
        said = (f"Sunday’s message, <b>{title}</b>, came with {n} question{'s' if n != 1 else ''} from the church office {when}."
                if r.get("source") == "office" else
                f"Sunday’s message, <b>{title}</b>, has {n} question{'s' if n != 1 else ''} ready {when}. You can change any of them.")
        return (f'<section class="gs-card gy-chief" aria-label="This week’s study, waiting for you">'
                f'<span class="gy-chief-h">{ic("sparkles", 15)}<span>Chief</span></span><p>{said}</p>'
                f'<div class="gy-acts"><form method="post" action="/my/groups/meet/study">'
                f'<input type="hidden" name="group_id" value="{gid}"><input type="hidden" name="study" value="{sid}">'
                f'<button class="gs-btn sm" type="submit">Post them as they are</button></form></div>'
                f'<details class="gy-edit"><summary class="gs-mini">Review the questions</summary>'
                f'{_questions_form(gid, sid, qs, "Post these", esc)}</details>'
                f'<p class="gm-fine">Nobody in the group sees them until you post.</p></section>')
    series = esc(st.get("series") or "")
    ref = mpb.scripture_links(s.get("scripture") or "") if s.get("scripture") else ""
    items = "".join(f"<li>{esc(q)}</li>" for q in qs)
    by = next((name(p) for p in people if p["id"] == str(r.get("posted_by") or "")), "")
    origin = "From the church office" if r.get("source") == "office" else "Drafted from Sunday’s message"
    by_line = origin + (f" · {esc(by)} {'shared' if r.get('source') == 'office' else 'approved'} them" if by else "")
    links = []
    import bible_text as bt
    refs = [x for _, _, x in bt.find_refs(s.get("scripture") or "")]
    if refs:
        first = refs[0]
        label = f"{'Psalm' if first.book == 'PSA' else bt.NAME[first.book]} {first.chapter}"
        links.append(f'<a class="gs-btn soft sm" href="{esc(first.href())}">{ic("book", 15)}Read {esc(label)}</a>')
    watch = "Watch the message" if s.get("video_url") else ("Listen to the message" if s.get("audio_url") else "Open the message")
    links.append(f'<a class="gs-btn soft sm" href="/my/sermons/{esc(s["id"])}">{ic("play", 15)}{watch}</a>')
    edit = (f'<details class="gy-edit"><summary class="gs-mini">Change the questions</summary>'
            f'{_questions_form(gid, sid, qs, "Save changes", esc)}</details>' if leader else "")
    return (f'<section class="gs-card gy-study" aria-labelledby="gy-title">'
            f'<p class="gy-eb">From Sunday{f" · {series}" if series else ""}</p><h3 id="gy-title">{title}</h3>'
            f'{f"<p class=gy-ref>{ref}</p>" if ref else ""}<ol class="gy-qs">{items}</ol>'
            f'<p class="gy-by">{by_line}</p><div class="gy-acts">{"".join(links)}</div>{edit}</section>')


def home_line(g: Dict[str, Any], st: Optional[Dict[str, Any]], ic, esc, href: str) -> str:
    """The group's Home: a posted study, one line."""
    if not st or not st.get("study") or not st["study"].get("posted_at"):
        return ""
    n = len(clean(st["study"].get("questions") or []))
    return (f'<a class="gs-row" href="{esc(href)}"><span class="gs-disc gold">{ic("book", 20)}</span>'
            f'<span class="gs-t"><b>This week’s study</b><span>{esc(st["sermon"].get("title") or "")} · '
            f'{n} question{"s" if n != 1 else ""} from Sunday</span></span>{ic("chevron", 18)}</a>')
