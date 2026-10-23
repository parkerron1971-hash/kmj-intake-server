"""
chat_polls.py — polls in a group's chat.

From the approved canvas "Church Groups, Together" (board Chat: "Potluck
theme for Nov 19? · Soul food 9 · Breakfast for dinner 4 · Taco bar 3 ·
16 votes · closes Friday"; board Settings: "Photos and polls").

  * anyone who can write in a group's chat, or the leaders' room, starts a
    poll from the composer's +: a question and 2-4 choices. A poll is a
    message (member_portal_messaging.send): the question is its text, and
    the question and choices are checked together like any message; a held
    poll is held whole
  * everyone in the chat sees the counts, never who voted. Tap a choice to
    vote, tap it again to take it back, tap another to change; voting
    closes after CLOSE_DAYS
  * a group's leaders turn polls off on the People tab (groups.chat_extras);
    the office's chat switches still decide who writes

Tables: msg_polls, msg_poll_votes (supabase/APPLY-2026-10-20-chat-polls.sql).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

import sb_clients

logger = logging.getLogger(__name__)

CLOSE_DAYS = 7
CHOICES_MAX = 4
CHOICE_MAX = 60
QUESTION_MAX = 200


def _q(v: Any) -> str:
    return quote(str(v), safe="")


def choices_from(values: Iterable[Any]) -> List[str]:
    """The choices a person typed: trimmed, each at most CHOICE_MAX, blanks
    and repeats dropped, at most CHOICES_MAX."""
    out: List[str] = []
    seen = set()
    for v in values:
        c = " ".join(str(v or "").split())[:CHOICE_MAX].strip()
        if c and c.casefold() not in seen:
            seen.add(c.casefold())
            out.append(c)
    return out[:CHOICES_MAX]


def attach(business_id: str, message_id: str, choices: List[str], now: Optional[datetime] = None) -> bool:
    """The poll on a message just sent."""
    closes = (now or datetime.now(timezone.utc)) + timedelta(days=CLOSE_DAYS)
    row = sb_clients.sb_post_as_service("/msg_polls", {
        "message_id": str(message_id), "business_id": str(business_id), "choices": choices,
        "closes_at": closes.isoformat()})
    return isinstance(row, list) and bool(row)


def _at(iso: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None


def for_messages(business_id: str, message_ids: Iterable[str], me_id: str,
                 now: Optional[datetime] = None) -> Optional[Dict[str, Dict[str, Any]]]:
    """{message_id: {'choices', 'counts', 'total', 'mine' (index or None),
    'open', 'closes_at'}} for the polls among these messages; None on a
    failed read."""
    ids = sorted({str(i) for i in message_ids if i})
    if not ids:
        return {}
    now = now or datetime.now(timezone.utc)
    out: Dict[str, Dict[str, Any]] = {}
    for i in range(0, len(ids), 150):
        part = ",".join(ids[i:i + 150])
        polls = sb_clients.sb_get_as_service(
            f"/msg_polls?business_id=eq.{_q(business_id)}&message_id=in.({part})&select=message_id,choices,closes_at")
        if not isinstance(polls, list):
            return None
        for p in polls:
            closes = _at(p.get("closes_at"))
            choices = [str(c) for c in (p.get("choices") or [])]
            out[str(p["message_id"])] = {"choices": choices, "counts": [0] * len(choices), "total": 0, "mine": None,
                                         "closes_at": closes, "open": bool(closes and closes > now)}
    asked = sorted(out)
    for i in range(0, len(asked), 150):
        votes = sb_clients.sb_get_as_service(
            f"/msg_poll_votes?business_id=eq.{_q(business_id)}&message_id=in.({','.join(asked[i:i + 150])})"
            f"&select=message_id,contact_id,choice&limit=20000")
        if not isinstance(votes, list):
            return None
        for v in votes:
            p = out.get(str(v["message_id"]))
            n = int(v.get("choice") or 0)
            if p is None or not 0 <= n < len(p["counts"]):
                continue
            p["counts"][n] += 1
            p["total"] += 1
            if str(v["contact_id"]) == str(me_id):
                p["mine"] = n
    return out


def vote(business_id: str, message_id: str, me_id: str, choice: int,
         now: Optional[datetime] = None) -> str:
    """'voted' | 'unvoted' | 'poll_closed' | 'poll_gone' | 'error'. The same
    choice again takes the vote back; another changes it."""
    rows = sb_clients.sb_get_as_service(
        f"/msg_polls?message_id=eq.{_q(message_id)}&business_id=eq.{_q(business_id)}&select=choices,closes_at&limit=1")
    if not isinstance(rows, list):
        return "error"
    if not rows or not 0 <= choice < len(rows[0].get("choices") or []):
        return "poll_gone"
    closes = _at(rows[0].get("closes_at"))
    if not closes or closes <= (now or datetime.now(timezone.utc)):
        return "poll_closed"
    where = (f"/msg_poll_votes?message_id=eq.{_q(message_id)}&contact_id=eq.{_q(me_id)}"
             f"&business_id=eq.{_q(business_id)}")
    had = sb_clients.sb_get_as_service(where + "&select=choice&limit=1")
    if not isinstance(had, list):
        return "error"
    if had and int(had[0].get("choice") or 0) == choice:
        return "unvoted" if sb_clients.sb_delete_as_service(where) else "error"
    saved = sb_clients.sb_post_as_service(
        "/msg_poll_votes?on_conflict=message_id,contact_id",
        {"message_id": str(message_id), "contact_id": str(me_id), "business_id": str(business_id), "choice": choice},
        prefer="return=representation,resolution=merge-duplicates")
    return "voted" if isinstance(saved, list) and saved else "error"


def closes_text(closes: Optional[datetime], now: datetime, tz) -> str:
    """'closes Friday' in the church's time; 'closed' once it has."""
    if not closes or closes <= now:
        return "closed"
    c, n = closes.astimezone(tz or timezone.utc), now.astimezone(tz or timezone.utc)
    days = (c.date() - n.date()).days
    if days <= 0:
        return "closes tonight" if c.hour >= 17 else "closes today"
    if days == 1:
        return "closes tomorrow"
    if days < 7:
        return f"closes {c.strftime('%A')}"
    return f"closes {c.strftime('%a')}, {c.strftime('%b')} {c.day}"


def card(p: Dict[str, Any], *, question_html: str, tid: str, mid: str, here: str, esc, now: datetime, tz,
         can_vote: bool) -> str:
    """The poll under its question: a bar per choice with its count, the
    person's own vote marked; one form, a button per choice."""
    total = p["total"]
    rows = []
    for i, (label, n) in enumerate(zip(p["choices"], p["counts"])):
        on = p["mine"] == i
        pct = round(100 * n / total) if total else 0
        inner = (f'<span class="gc-fill" style="width:{pct}%"></span><span class="gc-pl">{esc(label)}</span>'
                 f'<span class="gc-pn">{n}</span>')
        said = f'{esc(label)}, {n} {"vote" if n == 1 else "votes"}{", your vote" if on else ""}'
        if can_vote and p["open"]:
            rows.append(f'<button class="gc-po{" on" if on else ""}" type="submit" name="choice" value="{i}" '
                        f'aria-pressed="{"true" if on else "false"}" aria-label="{said}">{inner}</button>')
        else:
            rows.append(f'<span class="gc-po{" on" if on else ""}" role="img" aria-label="{said}">{inner}</span>')
    votes = f'{total} {"vote" if total == 1 else "votes"}'
    note = " · ".join(x for x in ("You voted" if p["mine"] is not None else "", votes, closes_text(p["closes_at"], now, tz)) if x)
    opts = "".join(rows)
    if can_vote and p["open"]:
        opts = (f'<form class="gc-pf" method="post" action="/my/messages/{esc(tid)}/vote">'
                f'<input type="hidden" name="message_id" value="{esc(mid)}"><input type="hidden" name="back" value="{esc(here)}">{opts}</form>')
    else:
        opts = f'<div class="gc-pf">{opts}</div>'
    return f'<div class="gc-poll">{question_html}{opts}<small>{esc(note)}</small></div>'


def form(tid: str, here: str, place: str, alert: str, *, esc, ic) -> str:
    """The new-poll form, in place of the composer (`?make=poll`)."""
    choices = "".join(
        f'<label class="mp-sr" for="gc-c{i}">Choice {i + 1}</label>'
        f'<input id="gc-c{i}" name="choice" maxlength="{CHOICE_MAX}" autocomplete="off" placeholder="Choice {i + 1}'
        f'{"" if i < 2 else " (optional)"}"{" required" if i < 2 else ""}>' for i in range(CHOICES_MAX))
    return (f'<form class="gc-compose gc-newpoll" id="gc-pollform" method="post" action="/my/messages/{esc(tid)}/send">'
            f'<input type="hidden" name="back" value="{esc(here)}"><input type="hidden" name="poll" value="1">'
            f'<div class="gc-np-h"><b>{ic("poll", 16)}New poll</b><a href="{esc(here)}#gc-compose">Cancel</a></div>'
            f'<label class="mp-sr" for="gc-pq">Question</label>'
            f'<input id="gc-pq" name="body" maxlength="{QUESTION_MAX}" autocomplete="off" required placeholder="Ask {esc(place)} something">'
            f'{choices}{alert}'
            f'<p class="gc-safe">{ic("shield", 13)}<span>Everyone sees the counts, never who voted. Voting closes in a week.</span></p>'
            f'<button class="gs-btn" type="submit">{ic("send", 16)}Post the poll</button></form>')


POLL_CSS = """
.gc-poll{width:min(290px,100%);border-radius:18px;background:var(--s1);padding:12px;display:flex;flex-direction:column;gap:8px;}
.gc-m.mine .gc-poll{background:color-mix(in srgb,var(--teal) 22%,var(--s1));}
.gc-poll .gc-d{align-items:stretch;}
.gc-pq{margin:0;font-size:15px;font-weight:650;line-height:1.35;overflow-wrap:anywhere;padding:2px 2px 0;}
.gc-pf{display:flex;flex-direction:column;gap:6px;margin:0;}
.gc-po{position:relative;display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:42px;padding:0 12px;
  border-radius:11px;border:0;background:var(--s2);color:var(--fg);font:inherit;font-size:14px;text-align:left;overflow:hidden;
  box-sizing:border-box;width:100%;}
button.gc-po{cursor:pointer;}
.gc-po .gc-fill{position:absolute;left:0;top:0;bottom:0;background:var(--teal-deep);}
.gc-po .gc-pl,.gc-po .gc-pn{position:relative;}
.gc-po .gc-pl{min-width:0;overflow-wrap:anywhere;}
.gc-po .gc-pn{font-weight:700;font-variant-numeric:tabular-nums;color:var(--fg2);}
.gc-po.on{box-shadow:inset 0 0 0 1.5px var(--teal-ink);}
.gc-po.on .gc-pn{color:var(--teal-ink);}
.gc-poll small{font-size:12px;color:var(--fg3);padding:0 2px;}
.gc-tray{position:relative;flex:none;}
.gc-tray>summary{list-style:none;width:46px;height:46px;border-radius:50%;display:grid;place-items:center;background:var(--s1);
  color:var(--fg2);cursor:pointer;box-shadow:inset 0 0 0 1px var(--line);}
.gc-tray>summary::-webkit-details-marker{display:none;}
.gc-tray>summary:focus-visible{outline:2px solid var(--acc);outline-offset:2px;}
.gc-tray[open]>summary{background:var(--teal-deep);color:var(--teal-ink);}
.gc-tray[open]>summary .mb-ic{transform:rotate(45deg);}
.gc-tray-in{position:absolute;left:0;bottom:calc(100% + 8px);display:flex;gap:8px;padding:8px;border-radius:18px;background:var(--s2);
  box-shadow:0 8px 28px rgba(0,0,0,.28);z-index:7;}
.gc-tray-in a{display:flex;flex-direction:column;align-items:center;gap:4px;min-width:64px;padding:6px 4px;border-radius:12px;
  color:var(--fg);text-decoration:none;font-size:12.5px;font-weight:600;}
.gc-tray-in a:hover{background:var(--s1);}
.gc-tray-in .gc-disc{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;background:var(--teal-deep);color:var(--teal-ink);}
.gc-newpoll input{min-height:44px;border:0;outline:none;border-radius:14px;background:var(--s1);color:var(--fg);padding:0 14px;
  font:inherit;font-size:16px;box-shadow:inset 0 0 0 1px var(--line);}
.gc-newpoll #gc-pq{font-weight:650;}
.gc-np-h{display:flex;align-items:center;justify-content:space-between;}
.gc-np-h b{display:inline-flex;align-items:center;gap:6px;font-size:15px;}
.gc-np-h a{color:var(--fg3);font-weight:600;text-decoration:none;font-size:14px;}
.gc-newpoll .gs-btn{align-self:stretch;justify-content:center;}
"""
