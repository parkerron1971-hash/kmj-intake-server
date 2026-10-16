"""
ops_desk.py — Kevin's operating system for running Solutionist alone
(2026-10-15, Kevin: "make my operation easy … create a task list that can
connect to calendar on my phone … build path for KAI … turn what you found
into a system for myself").

The team plan (artifact 1aZ4dpUZVvknD8V2bUCSwN) turned into working parts.
docs/OPERATIONS.md is the plain-words version.

  lanes      every piece of work sits in Fix (no limit), Build (two at a
             time, enforced here), Try (ideas; never merges) or Ops (the
             chores that keep the company running). Moving work into Build
             passes "the door": five answers, stored on the task.
  rhythm     the week, computed rather than stored: a morning queue on
             weekdays, build blocks Tuesday and Thursday, the Thursday
             release, the Friday scorecard, the monthly close and agent
             check, and a quiet week (the last full week of the month).
  calendar   one private .ics feed of the rhythm and Kevin's dated tasks, so
             the week lives in his phone's calendar. The link is an HMAC of
             a version number: no secret is stored, and rotating the link
             bumps the version.
  scorecard  the Friday page, measured: queue age, tickets, night alerts,
             Chief's errors, AI spend against revenue, Build in flight,
             switches left off, open PRs, paying businesses, Kevin's hours,
             and the signals for the first hire.
  KAI        the device line (/dev-bridge/ops/*). KAI reads the brief, files
             Fix/Try/Ops tasks, keeps its own, writes the note on Today, and
             is prompted at the rhythm's moments. It can never move work into
             Build: those two slots are Kevin's.
  keeper     the Scope keeper agent: a daily pass that snapshots the
             scorecard and flags the rules being broken.

Storage: platform_ops_tasks + platform_ops_settings
(supabase/APPLY-2026-10-16-ops-desk.sql). RLS on, no policies: only the
service role reads or writes them. Owner endpoints use require_owner; the
device endpoints take the paired Solution Space's token; the calendar feed
is public by necessity (a phone calendar can't sign in), so it is read-only
and keyed by an unguessable link.

Kill switch: OPS_DESK=off quiets the keeper, the moments and the Today
block. The pages and the feed keep working.
"""
from __future__ import annotations

import asyncio
import base64
import hmac
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Literal, Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

import dev_redact
from lead_admin import SUPABASE_URL, _service_headers, require_owner

router = APIRouter(tags=["ops-desk"])

MIGRATION = "supabase/APPLY-2026-10-16-ops-desk.sql"
AGENT = "scope_keeper"
HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=15.0, pool=10.0)
DEFAULT_TZ = "America/New_York"
BUILD_SLOTS = 2
# A Build item that has sat this long is not "in progress", it is parked.
BUILD_STALE_DAYS = 21
# KAI may file this many tasks a day; past it, it tells Kevin instead.
KAI_TASKS_PER_DAY = 20
SCORE_CACHE_S = 300
NOTE_FRESH_H = 18

LANES = ("fix", "build", "try", "ops")
STATUSES = ("open", "doing", "waiting", "done", "dropped")
ACTIVE = ("open", "doing", "waiting")
KINDS = ("task", "decision", "switch", "hire")
SEATS = ("owner", "product", "code", "support", "money", "growth", "safety")
HOLDERS = ("kevin", "kai", "agent", "hire")
SOURCES = ("kevin", "kai", "plan", "agent")

LANE_WORDS = {
    "fix": "Fix: broken things, always first, no limit",
    "build": "Build: new features, two at a time",
    "try": "Try: ideas, prototypes and proposals; nothing here merges",
    "ops": "Ops: the chores that keep the company running",
}
SEAT_WORDS = {
    "owner": "Owner", "product": "Product", "code": "Code & deploys",
    "support": "Support & onboarding", "money": "Money & admin",
    "growth": "Growth", "safety": "Trust & safety",
}

# The door into Build. Every answer is required, in a few words.
DOOR: Tuple[Tuple[str, str], ...] = (
    ("who_asked", "Who asked for it?"),
    ("owner_seat", "Who owns it when it breaks at night?"),
    ("monthly_cost", "What does it cost a month to run?"),
    ("off_switch", "What switches it off?"),
    ("what_waits", "What waits because of it?"),
)

RULES = [
    "Fix first, any day. Build holds two things at a time; a feature leaves Build only when it is live, "
    "switched on, used by a real customer, and on the scorecard.",
    "Work enters Build through the door: who asked, who owns it at night, what it costs a month, "
    "what switches it off, what waits because of it.",
    "Anything built and switched off for 30 days is switched on or taken out.",
    "Three build sessions at a time, at most, each on a named lane item.",
    "Features switch on on Thursdays. Fixes merge whenever they're ready.",
    "The last full week of the month is the quiet week: fixes, deletions and docs only.",
    "Until 100 paying businesses, new Build items come from customers or measurements. Ideas go to Try.",
]

# Kevin's week. Weekdays are Python's (Monday 0). `monthly` events land on
# the first such weekday of the month. Times are local to settings.tz.
RHYTHM: Dict[str, Dict[str, Any]] = {
    "morning": {"label": "Morning queue", "at": "07:30", "minutes": 20, "days": [0, 1, 2, 3, 4],
                "what": "Mission Control → Today, on your phone. Read KAI's note, then approve, send "
                        "and decide. Twenty minutes, then close it.",
                "nav": "platform-today", "alarm": 5},
    "build": {"label": "Build block", "at": "09:00", "minutes": 180, "days": [1, 3],
              "what": "Open the two Build items. Brief the sessions, check what landed since the last "
                      "block, merge what's green. Then let them work.",
              "nav": "platform-plan", "alarm": 10},
    "release": {"label": "Release", "at": "12:00", "minutes": 15, "days": [3],
                "what": "Switch on what's finished in Build. The release editor writes What's New.",
                "nav": "platform-plan", "alarm": 0},
    "scorecard": {"label": "Friday scorecard", "at": "15:00", "minutes": 30, "days": [4],
                  "what": "Read the scorecard (Platform Chief can read it to you), log your hours, and "
                          "pick what moves from Try into Build.",
                  "nav": "platform-plan", "alarm": 10},
    "close": {"label": "Close the month", "at": "10:00", "minutes": 45, "monthly": 0,
              "what": "Bookkeeping → Close the month, and read the Money auditor's month.",
              "nav": "platform-money", "alarm": 10},
    "audit": {"label": "Check the agents", "at": "15:30", "minutes": 30, "monthly": 4,
              "what": "Read ten outputs from each agent on Systems → Agents. Retire any agent you keep "
                      "overriding.",
              "nav": "platform-agents", "alarm": 0},
}
QUIET_WHAT = ("No new features this week. Fixes, deletions, docs, and making what's built easier to "
              "support.")

# When KAI is prompted, ahead of the rhythm event it prepares for.
MOMENTS: Dict[str, Dict[str, Any]] = {
    "morning_prep": {
        "before": "morning", "lead": 30,
        "text": ("Morning prep: Kevin's queue is at {at}. Call ops_brief. Then (1) clear what you can "
                 "without him: CI failures on your workers, PRs that only need updating, tasks you "
                 "hold; (2) file anything new as a Fix, Try or Ops task with ops_task; (3) write "
                 "today's note with ops_note in three short lines at most: what needs him, what you "
                 "handled, what you're watching. Don't alert his phone for this."),
    },
    "block_prep": {
        "before": "build", "lead": 20,
        "text": ("Kevin's build block starts at {at}. Call ops_brief and fleet. Write a note with "
                 "ops_note: the two Build items, where each stands (branches, PRs, CI), and the first "
                 "thing to do on each when he sits down. If a Build slot is open, name the best "
                 "candidate from Try and why, in one line. Open no workers until he says go."),
    },
    "scorecard_prep": {
        "before": "scorecard", "lead": 30,
        "text": ("The Friday scorecard is at {at}. Call ops_brief. Write a note with ops_note in four "
                 "lines at most: the number that moved most, any rule being broken (Build over two, "
                 "a switch past its date, a hiring signal), what you would move from Try into Build "
                 "next and why, and what you handled this week."),
    },
}


def enabled() -> bool:
    return (os.environ.get("OPS_DESK") or "on").strip().lower() not in ("0", "off", "false", "no")


def mission_control_url(page: str = "platform-today") -> str:
    from app_base import app_base_url
    return f"{app_base_url().rstrip('/')}/?nav=studio:{page}"


def api_base_url() -> str:
    """Where this backend is reached from outside (the calendar feed's host)."""
    return (os.environ.get("PUBLIC_API_BASE")
            or "https://kmj-intake-server-production.up.railway.app").rstrip("/")


# ─── Time ─────────────────────────────────────────────────────────────

def zone(name: Optional[str]) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TZ)


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _parse_day(v: Any) -> Optional[date]:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _z(t: datetime) -> str:
    # Z form: '+00:00' reads as a space in a PostgREST query string. Whole
    # seconds, so the value also reads cleanly inside an or=(...) filter.
    return t.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clock_words(hhmm: str) -> str:
    """'07:30' → '7:30 AM'; '15:00' → '3 PM'."""
    h, m = (int(x) for x in hhmm.split(":"))
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"


def week_key(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def quiet_week(d: date) -> Tuple[date, date]:
    """The last Monday–Friday that fits inside d's month."""
    nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    last = nxt - timedelta(days=1)
    friday = last - timedelta(days=(last.weekday() - 4) % 7)
    return friday - timedelta(days=4), friday


def is_quiet(d: date) -> bool:
    mon, fri = quiet_week(d)
    return mon <= d <= fri


def first_weekday(d: date, weekday: int) -> date:
    first = d.replace(day=1)
    return first + timedelta(days=(weekday - first.weekday()) % 7)


# ─── The rhythm ───────────────────────────────────────────────────────

_HHMM = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def resolve_rhythm(overrides: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """The defaults with Kevin's overrides laid on top. Anything malformed in
    an override is ignored, never trusted."""
    out: Dict[str, Dict[str, Any]] = {}
    over = overrides if isinstance(overrides, dict) else {}
    for kind, base in RHYTHM.items():
        e = {**base, "on": True}
        o = over.get(kind) if isinstance(over.get(kind), dict) else {}
        if isinstance(o.get("at"), str) and _HHMM.match(o["at"]):
            e["at"] = o["at"]
        if isinstance(o.get("minutes"), int) and 5 <= o["minutes"] <= 600:
            e["minutes"] = o["minutes"]
        if "days" in base and isinstance(o.get("days"), list):
            days = sorted({d for d in o["days"] if isinstance(d, int) and 0 <= d <= 6})
            e["days"] = days
        if isinstance(o.get("on"), bool):
            e["on"] = o["on"]
        out[kind] = e
    return out


def _event(kind: str, spec: Dict[str, Any], d: date, tz: ZoneInfo, *, label: Optional[str] = None,
           what: Optional[str] = None, quiet: bool = False) -> Dict[str, Any]:
    h, m = (int(x) for x in spec["at"].split(":"))
    start = datetime(d.year, d.month, d.day, h, m, tzinfo=tz)
    end = start + timedelta(minutes=spec["minutes"])
    return {
        "key": f"{kind}:{d.isoformat()}", "kind": kind, "date": d.isoformat(),
        "label": label or spec["label"], "what": what or spec["what"], "nav": spec["nav"],
        "at": spec["at"], "at_words": clock_words(spec["at"]), "minutes": spec["minutes"],
        "start": start.astimezone(timezone.utc).isoformat(),
        "end": end.astimezone(timezone.utc).isoformat(),
        "alarm": spec.get("alarm", 0), "all_day": False, "quiet": quiet,
    }


def rhythm_for_day(d: date, rhythm: Dict[str, Dict[str, Any]], tz: ZoneInfo) -> List[Dict[str, Any]]:
    quiet = is_quiet(d)
    out: List[Dict[str, Any]] = []
    for kind, spec in rhythm.items():
        if not spec.get("on", True):
            continue
        if "monthly" in spec:
            if d != first_weekday(d, spec["monthly"]):
                continue
        elif d.weekday() not in spec.get("days", []):
            continue
        if quiet and kind == "release":
            continue
        if quiet and kind == "build":
            out.append(_event(kind, spec, d, tz, label="Fix block", quiet=True,
                              what="Quiet week: work the Fix lane. No new features."))
            continue
        out.append(_event(kind, spec, d, tz, quiet=quiet))
    out.sort(key=lambda e: e["start"])
    return out


def quiet_event(d: date) -> Dict[str, Any]:
    mon, fri = quiet_week(d)
    return {"key": f"quiet:{mon.isoformat()}", "kind": "quiet", "date": mon.isoformat(),
            "end_date": (fri + timedelta(days=1)).isoformat(), "label": "Quiet week: fixes only",
            "what": QUIET_WHAT, "nav": "platform-plan", "all_day": True, "quiet": True}


def events_between(start: date, end: date, rhythm: Dict[str, Dict[str, Any]],
                   tz: ZoneInfo) -> List[Dict[str, Any]]:
    """Every rhythm event from start to end inclusive, plus each quiet week
    that touches the range as one all-day event."""
    out: List[Dict[str, Any]] = []
    seen_quiet = set()
    d = start
    while d <= end:
        out.extend(rhythm_for_day(d, rhythm, tz))
        if is_quiet(d):
            q = quiet_event(d)
            if q["key"] not in seen_quiet:
                seen_quiet.add(q["key"])
                out.append(q)
        d += timedelta(days=1)
    return out


def due_moments(now: datetime, tz: ZoneInfo, rhythm: Dict[str, Dict[str, Any]],
                acked: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The KAI prompts whose time has come today and that KAI hasn't had.
    A moment stays due from its lead time until its event ends, so a desktop
    that wakes at 7:15 still gets the 7:00 morning prep, but not at noon."""
    local = now.astimezone(tz)
    events = {e["kind"]: e for e in rhythm_for_day(local.date(), rhythm, tz)}
    out = []
    for name, m in MOMENTS.items():
        e = events.get(m["before"])
        if not e:
            continue
        start, end = _parse_ts(e["start"]), _parse_ts(e["end"])
        at = start - timedelta(minutes=m["lead"])
        key = f"{local.date().isoformat()}:{name}"
        if at <= now < end and key not in (acked or {}):
            text = m["text"].format(at=e["at_words"])
            if e.get("quiet"):
                text += " It is the quiet week: fixes only."
            out.append({"key": key, "moment": name, "event": e["label"], "at": e["start"],
                        "text": text})
    return out


# ─── The lanes ────────────────────────────────────────────────────────

class OpsRefusal(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def door_missing(door: Optional[Dict[str, Any]]) -> List[str]:
    d = door if isinstance(door, dict) else {}
    return [q for k, q in DOOR if len(str(d.get(k) or "").strip()) < 2]


_LINK = re.compile(r"^(?:https://[^\s<>\"']{3,490}|[\w][\w./#-]{0,490})$")


def clean_link(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    if not _LINK.match(s):
        raise OpsRefusal(422, "A link is an https:// address or a repo path like docs/OPERATIONS.md.")
    return s


def clean_door(v: Any) -> Dict[str, str]:
    d = v if isinstance(v, dict) else {}
    keys = {k for k, _ in DOOR}
    return {k: str(d[k]).strip()[:300] for k in d if k in keys and str(d[k] or "").strip()}


def apply_change(before: Dict[str, Any], change: Dict[str, Any], build_active: List[Dict[str, Any]],
                 actor: str, now: datetime) -> Dict[str, Any]:
    """The row update for one change to a task (or a new task, with `before`
    empty), after the lane rules. Raises OpsRefusal when a rule says no.

    actor is 'kevin' or 'kai'. KAI never moves work into Build, never moves
    a Build item out, and only changes tasks it holds or filed."""
    is_new = not before.get("id")
    out: Dict[str, Any] = {}
    for k, v in change.items():
        if k == "link":
            out[k] = clean_link(v)
        elif k == "door":
            out[k] = clean_door(v)
        elif k in ("due_on",):
            out[k] = v.isoformat() if isinstance(v, date) else (v or None)
        elif k == "starts_at":
            out[k] = v.astimezone(timezone.utc).isoformat() if isinstance(v, datetime) else (v or None)
        else:
            out[k] = v
    lane_before = before.get("lane")
    lane_after = out.get("lane", lane_before or "try")
    status_after = out.get("status", before.get("status") or "open")
    door_after = {**(before.get("door") or {}), **out.get("door", {})} if "door" in out else (
        before.get("door") or {})

    if actor == "kai":
        if not is_new and before.get("holder") != "kai" and before.get("source") != "kai":
            raise OpsRefusal(403, "That task is Kevin's. Tell him what you found instead.")
        if lane_after == "build" and lane_before != "build":
            raise OpsRefusal(403, "Only Kevin moves work into Build. File it in Try and say why it should go next.")
        if lane_before == "build" and lane_after != "build":
            raise OpsRefusal(403, "Only Kevin moves work out of Build.")

    entering = lane_after == "build" and (is_new or lane_before != "build")
    if entering and status_after in ACTIVE:
        others = [t for t in build_active if t.get("id") != before.get("id")]
        if len(others) >= BUILD_SLOTS:
            names = " and ".join(f"“{t.get('title')}”" for t in others[:BUILD_SLOTS])
            raise OpsRefusal(409, f"Both Build slots are taken by {names}. Finish one, or move it back "
                                  "to Try, first.")
        missing = door_missing(door_after)
        if missing:
            raise OpsRefusal(422, "Into Build through the door first. Still to answer: "
                                  + " ".join(missing))
    reopening = (lane_before == "build" and before.get("status") not in ACTIVE
                 and status_after in ACTIVE and lane_after == "build")
    if reopening:
        others = [t for t in build_active if t.get("id") != before.get("id")]
        if len(others) >= BUILD_SLOTS:
            raise OpsRefusal(409, "Both Build slots are taken. Finish one before reopening this.")

    if is_new or lane_after != lane_before:
        out["lane_since"] = now.isoformat()
    if "status" in out:
        if out["status"] in ("done", "dropped") and before.get("status") not in ("done", "dropped"):
            out["done_at"] = now.isoformat()
        elif out["status"] in ACTIVE:
            out["done_at"] = None
    out["updated_at"] = now.isoformat()
    return out


_STATUS_ORDER = {"doing": 0, "open": 1, "waiting": 2}


def _task_key(t: Dict[str, Any]) -> Tuple:
    due = _parse_day(t.get("due_on"))
    return (_STATUS_ORDER.get(t.get("status"), 9), due or date(2100, 1, 1), t.get("sort") or 0,
            t.get("created_at") or "")


def lanes_view(tasks: List[Dict[str, Any]], now: datetime, tz: ZoneInfo) -> Dict[str, Any]:
    today = now.astimezone(tz).date()
    active = [t for t in tasks if t.get("status") in ACTIVE]
    lanes = {lane: sorted([t for t in active if t.get("lane") == lane], key=_task_key) for lane in LANES}
    week_ago = now - timedelta(days=7)
    done = sorted([t for t in tasks if t.get("status") == "done"
                   and (_parse_ts(t.get("done_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= week_ago],
                  key=lambda t: t.get("done_at") or "", reverse=True)
    due = [t for t in active if t.get("holder") == "kevin" and _parse_day(t.get("due_on"))
           and _parse_day(t.get("due_on")) <= today]
    build = lanes["build"]
    stale = [t for t in build if (_parse_ts(t.get("lane_since")) or now) <= now - timedelta(days=BUILD_STALE_DAYS)]
    return {
        "lanes": lanes,
        "done_this_week": done[:20],
        "build_slots": {"used": len(build), "of": BUILD_SLOTS, "open": max(0, BUILD_SLOTS - len(build))},
        "build_stale": [{"id": t["id"], "title": t.get("title"),
                         "days": (now - (_parse_ts(t.get("lane_since")) or now)).days} for t in stale],
        "due": sorted(due, key=_task_key),
        "counts": {lane: len(v) for lane, v in lanes.items()},
    }


# ─── The calendar ─────────────────────────────────────────────────────

def calendar_token(version: int, root: Optional[bytes] = None) -> str:
    """The link's secret part: HKDF from the platform's token root, under a
    purpose of its own, so it cannot verify anything else. 32 characters
    of base64url (192 bits). Raises RuntimeError when the root isn't set."""
    import customer_token
    key = customer_token.derive_key("ops-calendar", f"owner|{int(version)}", root=root)
    return base64.urlsafe_b64encode(key).decode("ascii").rstrip("=")[:32]


def token_ok(given: str, version: int, root: Optional[bytes] = None) -> bool:
    try:
        want = calendar_token(version, root=root)
    except RuntimeError:
        return False
    return hmac.compare_digest((given or "").encode("utf-8"), want.encode("utf-8"))


def ics_escape(s: Any) -> str:
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", ""))


def ics_fold(line: str) -> str:
    """RFC 5545 §3.1: lines of at most 75 octets, continued with a space,
    never splitting a character."""
    parts: List[str] = []
    cur, size, limit = "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            parts.append(cur)
            cur, size, limit = ch, n, 74
        else:
            cur += ch
            size += n
    parts.append(cur)
    return "\r\n ".join(parts)


def _stamp(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _vevent(uid: str, now: datetime, summary: str, description: str, *, start: Optional[datetime] = None,
            end: Optional[datetime] = None, day: Optional[date] = None, end_day: Optional[date] = None,
            url: str = "", alarm: int = 0, transparent: bool = False) -> List[str]:
    lines = ["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{_stamp(now)}"]
    if day is not None:
        lines.append(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(end_day or day + timedelta(days=1)).strftime('%Y%m%d')}")
    else:
        lines.append(f"DTSTART:{_stamp(start)}")
        lines.append(f"DTEND:{_stamp(end)}")
    lines.append(f"SUMMARY:{ics_escape(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{ics_escape(description)}")
    if url:
        lines.append(f"URL:{url}")
    lines.append("TRANSP:TRANSPARENT" if transparent else "TRANSP:OPAQUE")
    if alarm and day is None:
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{ics_escape(summary)}",
                  f"TRIGGER:-PT{int(alarm)}M", "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def calendar_ics(events: List[Dict[str, Any]], tasks: List[Dict[str, Any]], now: datetime,
                 tz: ZoneInfo, link_for=mission_control_url) -> str:
    """The feed: the rhythm, and every open task Kevin holds that has a date.
    A timed task is a block; a dated one is an all-day reminder; one that is
    past due shows on today so it can't slip into the past unseen."""
    today = now.astimezone(tz).date()
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Solutionist//Ops desk//EN",
             "CALSCALE:GREGORIAN", "METHOD:PUBLISH", "X-WR-CALNAME:Solutionist · your week",
             f"X-WR-TIMEZONE:{getattr(tz, 'key', DEFAULT_TZ)}",
             "X-WR-CALDESC:Your rhythm and dated tasks from Mission Control → Build → Plan.",
             "REFRESH-INTERVAL;VALUE=DURATION:PT1H", "X-PUBLISHED-TTL:PT1H"]
    for e in events:
        if e.get("all_day"):
            lines += _vevent(f"ops-{e['key']}@solutionist", now, e["label"], e["what"],
                             day=_parse_day(e["date"]), end_day=_parse_day(e.get("end_date")),
                             url=link_for(e["nav"]), transparent=True)
        else:
            lines += _vevent(f"ops-{e['key']}@solutionist", now, e["label"], e["what"],
                             start=_parse_ts(e["start"]), end=_parse_ts(e["end"]),
                             url=link_for(e["nav"]), alarm=e.get("alarm", 0))
    for t in tasks:
        if t.get("status") not in ACTIVE or t.get("holder") != "kevin":
            continue
        title = t.get("title") or "Task"
        desc = (t.get("detail") or "").strip()
        desc = f"{desc}\n\n{LANE_WORDS.get(t.get('lane'), '')}".strip()
        url = link_for("platform-plan")
        start = _parse_ts(t.get("starts_at"))
        due = _parse_day(t.get("due_on"))
        if start:
            lines += _vevent(f"ops-task-{t['id']}@solutionist", now, title, desc, start=start,
                             end=start + timedelta(minutes=int(t.get("minutes") or 30)), url=url, alarm=10)
        elif due:
            label = f"Due: {title}" if due >= today else f"Past due: {title}"
            lines += _vevent(f"ops-task-{t['id']}@solutionist", now, label, desc,
                             day=max(due, today), url=url, transparent=True)
    lines.append("END:VCALENDAR")
    return "\r\n".join(ics_fold(l) for l in lines) + "\r\n"


# ─── The scorecard ────────────────────────────────────────────────────

def _state(value: Optional[float], ok_max: float, warn_max: float) -> str:
    if value is None:
        return "unknown"
    return "ok" if value <= ok_max else ("warn" if value <= warn_max else "bad")


def _money(cents: Optional[float]) -> str:
    if cents is None:
        return "—"
    d = cents / 100
    return f"${d:,.0f}" if d >= 100 else f"${d:,.2f}"


def _hours_ago(t: Optional[datetime], now: datetime) -> Optional[float]:
    return None if not t else (now - t).total_seconds() / 3600


def _at_night(t: Optional[datetime], tz: ZoneInfo) -> bool:
    if t is None:
        return False
    hour = t.astimezone(tz).hour
    return hour >= 22 or hour < 7


def compose_scorecard(x: Dict[str, Any], now: datetime, tz: ZoneInfo) -> Dict[str, Any]:
    """The Friday page from gathered inputs. Every input may be None (its
    source failed); that metric then reads "couldn't read", never zero."""
    today = now.astimezone(tz).date()
    metrics: List[Dict[str, Any]] = []

    def add(key, label, value, detail, goal, state, source):
        metrics.append({"key": key, "label": label, "value": value, "detail": detail,
                        "goal": goal, "state": state, "source": source})

    q = x.get("queue")
    if q is None:
        add("queue_waiting", "Waiting more than a day", None, "Couldn't read Today.", "0", "unknown", "Today")
    else:
        old = [i for i in q if (_hours_ago(_parse_ts(i.get("at")), now) or 0) > 24]
        add("queue_waiting", "Waiting more than a day", len(old), f"{len(q)} open in Today.", "0",
            "ok" if not old else ("warn" if len(old) <= 2 else "bad"), "Today")

    tk = x.get("tickets")
    if tk is None:
        add("tickets", "Support tickets open", None, "Couldn't read the support queue.",
            "answered within a day", "unknown", "Support")
    else:
        ages = [h for h in (_hours_ago(_parse_ts(t.get("created_at")), now) for t in tk) if h is not None]
        oldest = max(ages) if ages else 0
        add("tickets", "Support tickets open", len(tk),
            f"Oldest {round(oldest)} hours." if tk else "None waiting.", "answered within a day",
            "ok" if oldest <= 24 else ("warn" if oldest <= 48 else "bad"), "Support")

    pages = x.get("pages")
    if pages is None:
        add("night_alerts", "Phone alerts at night", None, "Couldn't read the alert log.",
            "1 a week at most", "unknown", "Dev Desk alerts")
    else:
        night = [p for p in pages if _at_night(_parse_ts(p.get("created_at")), tz)]
        add("night_alerts", "Phone alerts at night", len(night),
            "Pushed between 10 PM and 7 AM, last 7 days.", "1 a week at most",
            _state(len(night), 1, 2), "Dev Desk alerts")

    ch = x.get("chief")
    if not ch or ch.get("error_rate") is None:
        add("chief_errors", "Chief turns that errored", None, "No Chief quality run to read.",
            "under 5%", "unknown", "Chief quality")
    else:
        pct = round(float(ch["error_rate"]) * 100, 1)
        add("chief_errors", "Chief turns that errored", f"{pct}%",
            f"{ch.get('turns') or 0} turns in the last day.", "under 5%",
            "ok" if pct < 5 else ("warn" if pct < 10 else "bad"), "Chief quality")

    spend7, mrr = x.get("spend_7d_cents"), x.get("mrr_cents")
    if spend7 is None:
        add("ai_spend", "AI spend against revenue", None, "Couldn't read AI costs.", "under 30% of revenue",
            "unknown", "AI costs")
    else:
        month = spend7 * 30 / 7
        if not mrr:
            add("ai_spend", "AI spend against revenue", f"{_money(month)} a month",
                "No subscription revenue yet to set it against.", "under 30% of revenue", "warn", "AI costs")
        else:
            ratio = month / mrr
            add("ai_spend", "AI spend against revenue", f"{round(ratio * 100)}%",
                f"{_money(month)} a month at this week's pace, against {_money(mrr)} MRR.",
                "under 30% of revenue", "ok" if ratio < 0.3 else ("warn" if ratio < 0.6 else "bad"),
                "AI costs")

    lv = x.get("lanes") or {}
    slots = lv.get("build_slots") or {"used": 0, "of": BUILD_SLOTS}
    stale = lv.get("build_stale") or []
    names = ", ".join(t.get("title") or "" for t in (lv.get("lanes") or {}).get("build", []))
    add("build", "Build slots in use", f"{slots['used']} of {slots['of']}",
        (f"{stale[0]['title']} has been in Build {stale[0]['days']} days. " if stale else "") + (names or "Both open."),
        "2 at most, and moving", "bad" if slots["used"] > BUILD_SLOTS else ("warn" if stale else "ok"), "Plan")

    tasks = x.get("tasks") or []
    switches = [t for t in tasks if t.get("kind") == "switch" and t.get("status") in ACTIVE]
    late_sw = [t for t in switches if (_parse_day(t.get("due_on")) or date(2100, 1, 1)) < today]
    add("switches", "Built but switched off", len(switches),
        (f"{len(late_sw)} past the date to decide." if late_sw else
         ("Each has a decide-by date." if switches else "Nothing left switched off.")),
        "decided within 30 days", "bad" if late_sw else ("warn" if switches else "ok"), "Plan")

    overdue = [t for t in tasks if t.get("status") in ACTIVE and t.get("holder") == "kevin"
               and (_parse_day(t.get("due_on")) or date(2100, 1, 1)) < today]
    add("overdue", "Your tasks past due", len(overdue),
        "; ".join(t.get("title") or "" for t in overdue[:3]) or "Nothing late.", "0",
        "ok" if not overdue else ("warn" if len(overdue) <= 3 else "bad"), "Plan")

    prs = x.get("prs")
    if prs is None:
        add("prs", "Open pull requests", None, "Couldn't read GitHub.", "under 15", "unknown", "GitHub")
    else:
        total = sum(prs.values())
        add("prs", "Open pull requests", total,
            f"Backend {prs.get('backend', 0)}, frontend {prs.get('frontend', 0)}.", "under 15",
            "ok" if total < 15 else ("warn" if total <= 30 else "bad"), "GitHub")

    paying = x.get("paying")
    hist = (x.get("history") or {}).get("daily") or []
    week_ago = next((h for h in reversed(hist) if _parse_day(h.get("date"))
                     and _parse_day(h.get("date")) <= today - timedelta(days=7)), None)
    if paying is None:
        add("paying", "Paying businesses", None, "Couldn't read subscriptions.", "growing", "unknown", "Stripe")
    else:
        delta = ""
        if week_ago and isinstance(week_ago.get("paying"), int):
            d = paying - week_ago["paying"]
            delta = f" {'+' if d >= 0 else ''}{d} on last week."
        add("paying", "Paying businesses", paying, f"MRR {_money(mrr)}.{delta}", "growing", "ok", "Stripe")

    hours = x.get("hours")
    add("hours", "Your hours this week", hours,
        "As you logged them." if hours is not None else "Log them on Friday.", "10 to 15",
        _state(hours, 15, 20), "You")

    sig = hire_signals(x, hist, today)
    worst = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
    metrics.sort(key=lambda m: worst.get(m["state"], 9))
    return {"generated_at": now.isoformat(), "week": week_key(today), "metrics": metrics, "signals": sig}


def hire_signals(x: Dict[str, Any], hist: List[Dict[str, Any]], today: date) -> Dict[str, Any]:
    """The plan's signals for the first hire (part-time ops & support). Move
    when any two hold for two weeks. One can't be measured; it says so."""
    tickets_14d = x.get("tickets_14d")
    paying = x.get("paying")
    last7 = [h for h in hist if _parse_day(h.get("date")) and _parse_day(h.get("date")) > today - timedelta(days=7)]
    waited_days = sum(1 for h in last7 if (h.get("queue_waiting") or 0) > 0)
    items = [
        {"key": "tickets", "text": "Tickets average 5 or more a day",
         "met": None if tickets_14d is None else tickets_14d / 14 >= 5,
         "now": None if tickets_14d is None else f"{round(tickets_14d / 14, 1)} a day over two weeks"},
        {"key": "queue", "text": "Queue items wait more than a day, three days in a week",
         "met": waited_days >= 3 if last7 else None, "now": f"{waited_days} of the last 7 days" if last7 else None},
        {"key": "paying", "text": "About 25 paying businesses",
         "met": None if paying is None else paying >= 25, "now": None if paying is None else f"{paying} paying"},
        {"key": "support_hours", "text": "More than 5 hours a week answering customers",
         "met": None, "now": "Only you can say. Count it on Friday."},
    ]
    met = sum(1 for i in items if i["met"])
    return {"next_hire": "Part-time operations & support", "items": items, "met": met,
            "rule": "Move when any two hold for two weeks running."}


# ─── Storage ──────────────────────────────────────────────────────────

def _missing(detail: str) -> HTTPException:
    return HTTPException(503, f"The ops desk needs {MIGRATION} applied. {detail[:200]}")


async def _select(c: httpx.AsyncClient, table: str, params: Dict[str, str]) -> List[Dict[str, Any]]:
    r = await c.get(f"{SUPABASE_URL}/rest/v1/{table}", headers=_service_headers(), params=params)
    if r.status_code >= 400:
        raise _missing(r.text) if table.startswith("platform_ops") else HTTPException(502, r.text[:200])
    out = r.json()
    return out if isinstance(out, list) else []


async def _insert(c: httpx.AsyncClient, table: str, row: Dict[str, Any]) -> Dict[str, Any]:
    r = await c.post(f"{SUPABASE_URL}/rest/v1/{table}",
                     headers={**_service_headers(), "Prefer": "return=representation"}, json=row)
    if r.status_code >= 400:
        raise _missing(r.text) if table.startswith("platform_ops") else HTTPException(502, r.text[:200])
    out = r.json()
    return out[0] if isinstance(out, list) and out else {}


async def _update(c: httpx.AsyncClient, table: str, params: Dict[str, str],
                  body: Dict[str, Any]) -> List[Dict[str, Any]]:
    r = await c.patch(f"{SUPABASE_URL}/rest/v1/{table}", params=params,
                      headers={**_service_headers(), "Prefer": "return=representation"}, json=body)
    if r.status_code >= 400:
        raise _missing(r.text) if table.startswith("platform_ops") else HTTPException(502, r.text[:200])
    out = r.json()
    return out if isinstance(out, list) else []


async def _count(c: httpx.AsyncClient, table: str, params: Dict[str, str]) -> int:
    r = await c.get(f"{SUPABASE_URL}/rest/v1/{table}",
                    headers={**_service_headers(), "Prefer": "count=exact", "Range": "0-0"},
                    params={**params, "select": "id"})
    if r.status_code >= 400:
        raise HTTPException(502, r.text[:200])
    rng = r.headers.get("content-range", "*/0")
    return int(rng.split("/")[-1]) if rng.split("/")[-1].isdigit() else 0


TASK_COLUMNS = ("id,created_at,updated_at,title,detail,lane,lane_since,status,kind,seat,holder,source,"
                "due_on,starts_at,minutes,link,door,done_at,sort")


async def load_tasks(c: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Every active task, and the finished ones of the last two weeks."""
    since = _z(datetime.now(timezone.utc) - timedelta(days=14))
    return await _select(c, "platform_ops_tasks", {
        "select": TASK_COLUMNS,
        "or": f"(status.in.(open,doing,waiting),done_at.gte.{since})",
        "order": "sort.asc,created_at.asc", "limit": "500"})


async def load_task(c: httpx.AsyncClient, task_id: str) -> Dict[str, Any]:
    try:
        tid = str(UUID(str(task_id)))
    except ValueError:
        raise HTTPException(404, "No such task")
    rows = await _select(c, "platform_ops_tasks", {"id": f"eq.{tid}", "select": TASK_COLUMNS})
    if not rows:
        raise HTTPException(404, "No such task")
    return rows[0]


async def load_settings(c: httpx.AsyncClient) -> Dict[str, Any]:
    rows = await _select(c, "platform_ops_settings", {"id": "eq.owner", "select": "*"})
    if rows:
        return rows[0]
    return await _insert(c, "platform_ops_settings", {"id": "owner"}) or {"id": "owner"}


async def save_settings(c: httpx.AsyncClient, body: Dict[str, Any]) -> Dict[str, Any]:
    rows = await _update(c, "platform_ops_settings", {"id": "eq.owner"},
                         {**body, "updated_at": datetime.now(timezone.utc).isoformat()})
    return rows[0] if rows else {}


async def _build_active(c: httpx.AsyncClient) -> List[Dict[str, Any]]:
    return await _select(c, "platform_ops_tasks", {
        "lane": "eq.build", "status": "in.(open,doing,waiting)", "select": "id,title"})


async def write_task(c: httpx.AsyncClient, before: Dict[str, Any], change: Dict[str, Any],
                     actor: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    needs_build = change.get("lane") == "build" or before.get("lane") == "build"
    build = await _build_active(c) if needs_build else []
    try:
        row = apply_change(before, change, build, actor, now)
    except OpsRefusal as e:
        raise HTTPException(e.status, e.message)
    if before.get("id"):
        rows = await _update(c, "platform_ops_tasks", {"id": f"eq.{before['id']}"}, row)
        out = rows[0] if rows else {**before, **row}
    else:
        out = await _insert(c, "platform_ops_tasks", row)
    _score_cache["at"] = 0.0
    return out


# ─── Gathering the scorecard ──────────────────────────────────────────

_score_cache: Dict[str, Any] = {"at": 0.0, "data": None, "inputs": None}


async def _guard(fn, default=None, timeout: float = 15.0):
    try:
        return await asyncio.wait_for(fn(), timeout)
    except Exception as e:  # every source fails soft and on its own
        print(f"[ops_desk] source failed: {type(e).__name__}: {str(e)[:160]}", flush=True)
        return default


async def _today_data() -> Dict[str, Any]:
    """Today, read as the server. No owner id, so Chief's pending approvals
    (filtered by owner) are left out; everything else is the same read."""
    import platform_today
    from lead_admin import PLATFORM_OWNER_EMAIL
    return await platform_today.build_today(SimpleNamespace(id="", email=PLATFORM_OWNER_EMAIL),
                                            with_ops=False)


async def _open_prs(c: httpx.AsyncClient) -> Dict[str, int]:
    import unfinished_work
    if not os.environ.get("GITHUB_TOKEN"):
        raise RuntimeError("GITHUB_TOKEN not set")
    be, fe = await asyncio.gather(unfinished_work._pr_list(c, "parkerron1971-hash/kmj-intake-server"),
                                  unfinished_work._pr_list(c, "parkerron1971-hash/solutionist-studio"))
    return {"backend": len(be), "frontend": len(fe)}


async def gather(c: httpx.AsyncClient, settings: Dict[str, Any], tasks: List[Dict[str, Any]],
                 now: datetime) -> Dict[str, Any]:
    tz = zone(settings.get("tz"))
    day7, day14 = _z(now - timedelta(days=7)), _z(now - timedelta(days=14))

    async def spend():
        rows = await _select(c, "api_usage", {"created_at": f"gte.{day7}", "select": "cost_cents",
                                              "limit": "100000"})
        return sum(float(r.get("cost_cents") or 0) for r in rows)

    async def chief():
        rows = await _select(c, "platform_agent_runs", {"agent": "eq.chief_quality", "select": "details,started_at",
                                                        "order": "started_at.desc", "limit": "1"})
        day = ((rows[0].get("details") or {}).get("day") or {}) if rows else {}
        return {"error_rate": day.get("error_rate"), "turns": day.get("turns"),
                "at": rows[0].get("started_at") if rows else None}

    today_data, tickets, tickets_14d, pages, ch, spend7, prs = await asyncio.gather(
        _guard(_today_data, None, 20.0),
        _guard(lambda: _select(c, "support_tickets", {"status": "eq.open", "select": "id,created_at",
                                                      "limit": "200"})),
        _guard(lambda: _count(c, "support_tickets", {"created_at": f"gte.{day14}"})),
        _guard(lambda: _select(c, "dev_alerts", {"delivered": "eq.pushed", "created_at": f"gte.{day7}",
                                                 "select": "created_at", "limit": "500"})),
        _guard(chief),
        _guard(spend),
        _guard(lambda: _open_prs(c)),
    )
    pulse = (today_data or {}).get("pulse") or {}
    week = week_key(now.astimezone(tz).date())
    hours = (settings.get("hours") or {}).get(week)
    return {
        "queue": (today_data or {}).get("needs_you") if today_data is not None else None,
        "tickets": tickets, "tickets_14d": tickets_14d, "pages": pages, "chief": ch,
        "spend_7d_cents": spend7, "mrr_cents": pulse.get("mrr_cents"),
        "paying": pulse.get("active_subscriptions"), "prs": prs,
        "hours": float(hours) if isinstance(hours, (int, float)) else None,
        "history": settings.get("history") or {}, "tasks": tasks,
        "lanes": lanes_view(tasks, now, tz),
    }


async def scorecard(c: httpx.AsyncClient, settings: Dict[str, Any], tasks: List[Dict[str, Any]],
                    force: bool = False) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(scorecard, inputs), cached five minutes per replica. A derived read,
    so a replica disagreeing for a few minutes costs nothing."""
    if not force and _score_cache["data"] and time.time() - _score_cache["at"] < SCORE_CACHE_S:
        return _score_cache["data"], _score_cache["inputs"]
    now = datetime.now(timezone.utc)
    inputs = await gather(c, settings, tasks, now)
    data = compose_scorecard(inputs, now, zone(settings.get("tz")))
    _score_cache.update(at=time.time(), data=data, inputs=inputs)
    return data, inputs


# ─── The whole desk ───────────────────────────────────────────────────

def _note(settings: Dict[str, Any], now: datetime) -> Optional[Dict[str, Any]]:
    n = settings.get("kai_note")
    if not isinstance(n, dict) or not n.get("text"):
        return None
    at = _parse_ts(n.get("at"))
    return {**n, "fresh": bool(at and now - at <= timedelta(hours=NOTE_FRESH_H))}


def _task_day(t: Dict[str, Any], tz: ZoneInfo) -> Optional[date]:
    start = _parse_ts(t.get("starts_at"))
    return start.astimezone(tz).date() if start else _parse_day(t.get("due_on"))


def week_view(now: datetime, settings: Dict[str, Any], tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    tz = zone(settings.get("tz"))
    rhythm = resolve_rhythm(settings.get("rhythm"))
    today = now.astimezone(tz).date()
    monday = today - timedelta(days=today.weekday())
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        dated = [t for t in tasks if t.get("status") in ACTIVE and t.get("holder") == "kevin"
                 and _task_day(t, tz) == d]
        days.append({"date": d.isoformat(), "weekday": d.strftime("%a"), "today": d == today,
                     "quiet": is_quiet(d), "events": rhythm_for_day(d, rhythm, tz),
                     "tasks": [{"id": t["id"], "title": t.get("title"), "lane": t.get("lane")} for t in dated]})
    upcoming = [e for e in events_between(today, today + timedelta(days=7), rhythm, tz)
                if not e.get("all_day") and _parse_ts(e["end"]) > now]
    mon, fri = quiet_week(today)
    if today > fri:
        mon, fri = quiet_week(date(today.year + (today.month == 12), today.month % 12 + 1, 1))
    return {"tz": getattr(tz, "key", DEFAULT_TZ), "today": today.isoformat(), "days": days,
            "next": upcoming[0] if upcoming else None,
            "quiet_week": {"from": mon.isoformat(), "to": fri.isoformat(), "now": mon <= today <= fri},
            "rhythm": rhythm}


async def desk(c: httpx.AsyncClient, *, force: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    settings = await load_settings(c)
    tasks = await load_tasks(c)
    tz = zone(settings.get("tz"))
    score, _ = await scorecard(c, settings, tasks, force=force)
    return {
        "ok": True, "generated_at": now.isoformat(),
        "lanes": lanes_view(tasks, now, tz),
        "week": week_view(now, settings, tasks),
        "scorecard": score,
        "kai_note": _note(settings, now),
        "rules": RULES, "door": [{"key": k, "question": q} for k, q in DOOR],
        "seats": SEAT_WORDS, "lane_words": LANE_WORDS,
        "calendar": {"ready": _calendar_ready()},
        "hours_week": week_key(now.astimezone(tz).date()),
    }


def _calendar_ready() -> bool:
    try:
        calendar_token(1)
        return True
    except RuntimeError:
        return False


# ─── Owner: the Plan page ─────────────────────────────────────────────

class TaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    detail: str = Field(default="", max_length=4000)
    lane: Literal["fix", "build", "try", "ops"] = "try"
    status: Literal["open", "doing", "waiting", "done", "dropped"] = "open"
    kind: Literal["task", "decision", "switch", "hire"] = "task"
    seat: Literal["owner", "product", "code", "support", "money", "growth", "safety"] = "owner"
    holder: Literal["kevin", "kai", "agent", "hire"] = "kevin"
    due_on: Optional[date] = None
    starts_at: Optional[datetime] = None
    minutes: Optional[int] = Field(default=None, ge=5, le=600)
    link: str = Field(default="", max_length=500)
    door: Dict[str, str] = Field(default_factory=dict)
    sort: int = 0


class TaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    detail: Optional[str] = Field(default=None, max_length=4000)
    lane: Optional[Literal["fix", "build", "try", "ops"]] = None
    status: Optional[Literal["open", "doing", "waiting", "done", "dropped"]] = None
    kind: Optional[Literal["task", "decision", "switch", "hire"]] = None
    seat: Optional[Literal["owner", "product", "code", "support", "money", "growth", "safety"]] = None
    holder: Optional[Literal["kevin", "kai", "agent", "hire"]] = None
    due_on: Optional[date] = None
    starts_at: Optional[datetime] = None
    minutes: Optional[int] = Field(default=None, ge=5, le=600)
    link: Optional[str] = Field(default=None, max_length=500)
    door: Optional[Dict[str, str]] = None
    sort: Optional[int] = None


def _patch_fields(body: BaseModel) -> Dict[str, Any]:
    """Only what the caller sent. Dates and times may be sent as null to
    clear them; the other fields may not."""
    raw = body.model_dump(exclude_unset=True)
    clearable = {"due_on", "starts_at", "minutes"}
    return {k: v for k, v in raw.items() if v is not None or k in clearable}


@router.get("/platform/ops")
async def ops_desk_get(fresh: bool = False, _owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        return await desk(c, force=fresh)


@router.post("/platform/ops/tasks")
async def ops_task_create(body: TaskIn, _owner=Depends(require_owner)):
    change = {**body.model_dump(), "source": "kevin"}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        return {"ok": True, "task": await write_task(c, {}, change, "kevin")}


@router.patch("/platform/ops/tasks/{task_id}")
async def ops_task_update(task_id: str, body: TaskPatch, _owner=Depends(require_owner)):
    change = _patch_fields(body)
    if not change:
        raise HTTPException(422, "Nothing to change.")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        before = await load_task(c, task_id)
        return {"ok": True, "task": await write_task(c, before, change, "kevin")}


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tz: Optional[str] = Field(default=None, max_length=64)
    rhythm: Optional[Dict[str, Dict[str, Any]]] = None


@router.put("/platform/ops/settings")
async def ops_settings_put(body: SettingsIn, _owner=Depends(require_owner)):
    patch: Dict[str, Any] = {}
    if body.tz is not None:
        try:
            ZoneInfo(body.tz)
        except (ZoneInfoNotFoundError, ValueError):
            raise HTTPException(422, "That isn't a time zone name. Use one like America/New_York.")
        patch["tz"] = body.tz
    if body.rhythm is not None:
        unknown = [k for k in body.rhythm if k not in RHYTHM]
        if unknown:
            raise HTTPException(422, f"No such rhythm event: {', '.join(unknown)}.")
        patch["rhythm"] = body.rhythm
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await load_settings(c)
        saved = await save_settings(c, patch) if patch else await load_settings(c)
    return {"ok": True, "tz": saved.get("tz"), "rhythm": resolve_rhythm(saved.get("rhythm"))}


class HoursIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hours: float = Field(ge=0, le=120)
    week: Optional[str] = Field(default=None, pattern=r"^\d{4}-W\d{2}$")


@router.post("/platform/ops/hours")
async def ops_hours(body: HoursIn, _owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        settings = await load_settings(c)
        tz = zone(settings.get("tz"))
        week = body.week or week_key(datetime.now(timezone.utc).astimezone(tz).date())
        hours = dict(settings.get("hours") or {})
        hours[week] = round(body.hours, 1)
        # Keep a year of weeks.
        hours = dict(sorted(hours.items())[-53:])
        await save_settings(c, {"hours": hours})
    _score_cache["at"] = 0.0
    return {"ok": True, "week": week, "hours": hours[week]}


def _feed_urls(version: int) -> Dict[str, str]:
    base = api_base_url()
    token = calendar_token(version)
    https = f"{base}/ops/calendar/{token}.ics"
    return {"https": https, "webcal": "webcal://" + https.split("://", 1)[1]}


@router.get("/platform/ops/calendar")
async def ops_calendar_link(_owner=Depends(require_owner)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        settings = await load_settings(c)
    try:
        urls = _feed_urls(int(settings.get("calendar_version") or 1))
    except RuntimeError:
        raise HTTPException(503, "The calendar link needs CUSTOMER_TOKEN_SECRET set on the server.")
    return {"ok": True, **urls, "version": int(settings.get("calendar_version") or 1)}


@router.post("/platform/ops/calendar/rotate")
async def ops_calendar_rotate(_owner=Depends(require_owner)):
    """A new link; the old one stops working at once. For a leaked link."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        settings = await load_settings(c)
        version = int(settings.get("calendar_version") or 1) + 1
        await save_settings(c, {"calendar_version": version})
    try:
        return {"ok": True, **_feed_urls(version), "version": version}
    except RuntimeError:
        raise HTTPException(503, "The calendar link needs CUSTOMER_TOKEN_SECRET set on the server.")


# ─── The phone's calendar ─────────────────────────────────────────────

@router.get("/ops/calendar/{token}.ics")
async def ops_calendar_feed(token: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{32}", token or ""):
        raise HTTPException(404, "Not found")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        settings = await load_settings(c)
        if not token_ok(token, int(settings.get("calendar_version") or 1)):
            raise HTTPException(404, "Not found")
        tasks = await load_tasks(c)
    now = datetime.now(timezone.utc)
    tz = zone(settings.get("tz"))
    today = now.astimezone(tz).date()
    events = events_between(today - timedelta(days=7), today + timedelta(days=56),
                            resolve_rhythm(settings.get("rhythm")), tz)
    body = calendar_ics(events, tasks, now, tz)
    return Response(content=body, media_type="text/calendar; charset=utf-8", headers={
        "Cache-Control": "private, max-age=900",
        "Content-Disposition": 'inline; filename="solutionist-week.ics"',
        "X-Robots-Tag": "noindex",
        "Referrer-Policy": "no-referrer",
    })


# ─── KAI: the device line ─────────────────────────────────────────────

async def _device(c: httpx.AsyncClient, authorization: Optional[str]) -> Dict[str, Any]:
    from dev_bridge import _require_device
    return await _require_device(c, authorization)


def _brief_task(t: Dict[str, Any]) -> Dict[str, Any]:
    keep = ("id", "title", "lane", "status", "kind", "seat", "holder", "source", "due_on", "starts_at",
            "link", "lane_since")
    out = {k: t.get(k) for k in keep}
    out["detail"] = (t.get("detail") or "")[:400]
    return out


def compose_brief(now: datetime, settings: Dict[str, Any], tasks: List[Dict[str, Any]],
                  score: Dict[str, Any], inputs: Dict[str, Any]) -> Dict[str, Any]:
    tz = zone(settings.get("tz"))
    lv = lanes_view(tasks, now, tz)
    wk = week_view(now, settings, tasks)
    today_events = next((d["events"] for d in wk["days"] if d["today"]), [])
    queue = []
    for i in (inputs or {}).get("queue") or []:
        age = _hours_ago(_parse_ts(i.get("at")), now)
        queue.append({"title": i.get("title"), "source": i.get("source"), "room": i.get("room"),
                      "tone": i.get("tone"), "hours_old": None if age is None else round(age)})
    return {
        "ok": True,
        "now": now.astimezone(tz).isoformat(), "tz": wk["tz"],
        "your_job": ("Until the first hire you hold the routine half of every seat: you prepare Kevin's "
                     "morning queue and build blocks, keep the lanes honest, watch PRs, CI and deploys, "
                     "and file what you find. Kevin decides; you never move work into Build."),
        "today": [{k: e.get(k) for k in ("label", "at_words", "minutes", "what", "quiet")} for e in today_events],
        "next": {k: (wk["next"] or {}).get(k) for k in ("label", "date", "at_words")} if wk["next"] else None,
        "quiet_week": wk["quiet_week"],
        "build_slots": lv["build_slots"], "build_stale": lv["build_stale"],
        "lanes": {lane: [_brief_task(t) for t in items[:15]] for lane, items in lv["lanes"].items()},
        "kevin_due": [_brief_task(t) for t in lv["due"][:10]],
        "done_this_week": [{"title": t.get("title"), "lane": t.get("lane")} for t in lv["done_this_week"][:10]],
        "queue": queue[:15],
        "scorecard": [{k: m.get(k) for k in ("label", "value", "detail", "state")} for m in score.get("metrics", [])],
        "hire_signals": score.get("signals"),
        "kai_note": _note(settings, now),
        "rules": RULES,
    }


@router.get("/dev-bridge/ops/brief")
async def kai_brief(fresh: bool = False, authorization: Optional[str] = Header(None)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _device(c, authorization)
        settings = await load_settings(c)
        tasks = await load_tasks(c)
        score, inputs = await scorecard(c, settings, tasks, force=fresh)
    brief = compose_brief(datetime.now(timezone.utc), settings, tasks, score, inputs)
    return await asyncio.to_thread(dev_redact.deep, brief)


class KaiTaskIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=3, max_length=200)
    detail: str = Field(default="", max_length=2000)
    lane: Literal["fix", "try", "ops"] = "fix"
    kind: Literal["task", "decision", "switch"] = "task"
    seat: Literal["owner", "product", "code", "support", "money", "growth", "safety"] = "code"
    holder: Literal["kai", "kevin"] = "kai"
    due_on: Optional[date] = None
    link: str = Field(default="", max_length=500)


class KaiTaskPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: Optional[str] = Field(default=None, min_length=3, max_length=200)
    detail: Optional[str] = Field(default=None, max_length=2000)
    lane: Optional[Literal["fix", "try", "ops"]] = None
    status: Optional[Literal["open", "doing", "waiting", "done", "dropped"]] = None
    holder: Optional[Literal["kai", "kevin"]] = None
    due_on: Optional[date] = None
    link: Optional[str] = Field(default=None, max_length=500)


@router.post("/dev-bridge/ops/tasks")
async def kai_task_create(body: KaiTaskIn, authorization: Optional[str] = Header(None)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _device(c, authorization)
        day = _z(datetime.now(timezone.utc) - timedelta(hours=24))
        filed = await _select(c, "platform_ops_tasks", {"source": "eq.kai", "created_at": f"gte.{day}",
                                                        "select": "id", "limit": str(KAI_TASKS_PER_DAY + 1)})
        if len(filed) >= KAI_TASKS_PER_DAY:
            raise HTTPException(429, f"You have filed {KAI_TASKS_PER_DAY} tasks today. Tell Kevin the rest "
                                     "in your note instead.")
        text = dev_redact.text(body.title), dev_redact.text(body.detail or "")
        change = {**body.model_dump(), "title": text[0], "detail": text[1], "source": "kai"}
        return {"ok": True, "task": _brief_task(await write_task(c, {}, change, "kai"))}


@router.patch("/dev-bridge/ops/tasks/{task_id}")
async def kai_task_update(task_id: str, body: KaiTaskPatch, authorization: Optional[str] = Header(None)):
    change = _patch_fields(body)
    for k in ("title", "detail"):
        if k in change:
            change[k] = dev_redact.text(change[k])
    if not change:
        raise HTTPException(422, "Nothing to change.")
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _device(c, authorization)
        before = await load_task(c, task_id)
        return {"ok": True, "task": _brief_task(await write_task(c, before, change, "kai"))}


class KaiNoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=3, max_length=1200)
    moment: Optional[Literal["morning_prep", "block_prep", "scorecard_prep", "other"]] = None


@router.post("/dev-bridge/ops/note")
async def kai_note(body: KaiNoteIn, authorization: Optional[str] = Header(None)):
    """KAI's note at the top of Today: what needs Kevin, what it handled,
    what it's watching. One note; the newest replaces the last."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _device(c, authorization)
        note = {"text": dev_redact.text(body.text.strip()), "moment": body.moment or "other",
                "at": datetime.now(timezone.utc).isoformat()}
        await load_settings(c)
        await save_settings(c, {"kai_note": note})
    return {"ok": True, "note": note}


@router.get("/dev-bridge/ops/moments")
async def kai_moments(authorization: Optional[str] = Header(None)):
    """The rhythm prompts KAI is due now. Solution Space polls this and hands
    each to KAI as a [Solution Space] message, then acks it."""
    if not enabled():
        return {"ok": True, "moments": [], "off": True}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _device(c, authorization)
        settings = await load_settings(c)
    tz = zone(settings.get("tz"))
    return {"ok": True, "moments": due_moments(datetime.now(timezone.utc), tz,
                                               resolve_rhythm(settings.get("rhythm")),
                                               settings.get("moments") or {})}


class AckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}:(morning_prep|block_prep|scorecard_prep)$")


@router.post("/dev-bridge/ops/moments/ack")
async def kai_moment_ack(body: AckIn, authorization: Optional[str] = Header(None)):
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
        await _device(c, authorization)
        settings = await load_settings(c)
        acked = dict(settings.get("moments") or {})
        acked[body.key] = datetime.now(timezone.utc).isoformat()
        cutoff = (datetime.now(timezone.utc) - timedelta(days=8)).date().isoformat()
        acked = {k: v for k, v in acked.items() if k[:10] >= cutoff}
        await save_settings(c, {"moments": acked})
    return {"ok": True}


# ─── Today's block ────────────────────────────────────────────────────

async def today_block(c: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """What Today shows from the desk: KAI's note, today's rhythm, Kevin's
    tasks due, and the Build slots. None when the desk is off or unreadable."""
    if not enabled():
        return None
    now = datetime.now(timezone.utc)
    settings = await load_settings(c)
    tasks = await load_tasks(c)
    tz = zone(settings.get("tz"))
    lv = lanes_view(tasks, now, tz)
    wk = week_view(now, settings, tasks)
    events = next((d["events"] for d in wk["days"] if d["today"]), [])
    return {
        "kai_note": _note(settings, now),
        "today": [{k: e.get(k) for k in ("kind", "label", "at_words", "minutes", "start", "end", "nav", "quiet")}
                  for e in events],
        "next": wk["next"] and {k: wk["next"].get(k) for k in ("label", "date", "at_words", "start", "nav")},
        "due": [{"id": t["id"], "title": t.get("title"), "due_on": t.get("due_on"), "lane": t.get("lane"),
                 "late": (_parse_day(t.get("due_on")) or now.astimezone(tz).date()) < now.astimezone(tz).date()}
                for t in lv["due"][:8]],
        "build": [{"id": t["id"], "title": t.get("title"), "status": t.get("status")}
                  for t in lv["lanes"]["build"]],
        "build_slots": lv["build_slots"],
        "quiet_week": wk["quiet_week"]["now"],
    }


# ─── The Scope keeper ─────────────────────────────────────────────────

def keeper_findings(score: Dict[str, Any], lv: Dict[str, Any], tasks: List[Dict[str, Any]],
                    hist: List[Dict[str, Any]], today: date) -> List[Dict[str, str]]:
    """The rules being broken today, as findings for Today. Plain sentences;
    platform_today dedupes repeats by their wording."""
    out: List[Dict[str, str]] = []
    if lv["build_slots"]["used"] > BUILD_SLOTS:
        out.append({"title": f"Build holds {lv['build_slots']['used']} items; the limit is {BUILD_SLOTS}",
                    "detail": "Move the extra back to Try. Two slots only work if they hold."})
    for s in lv["build_stale"]:
        out.append({"title": f"“{s['title']}” has been in Build {s['days']} days",
                    "detail": "Finish it, cut it smaller, or move it back to Try."})
    for t in tasks:
        due = _parse_day(t.get("due_on"))
        if t.get("kind") == "switch" and t.get("status") in ACTIVE and due and due < today:
            out.append({"title": f"“{t.get('title')}” is past its decide-by date",
                        "detail": f"The date was {due:%b} {due.day}. Switch it on or take it out."})
    sig = score.get("signals") or {}
    if (sig.get("met") or 0) >= 2:
        two_weeks = next((h for h in reversed(hist) if _parse_day(h.get("date"))
                          and _parse_day(h.get("date")) <= today - timedelta(days=14)), None)
        if two_weeks and (two_weeks.get("signals_met") or 0) >= 2:
            out.append({"title": "Two hiring signals have held for two weeks",
                        "detail": "The plan says it's time to bring in the part-time ops & support person."})
    return out


async def keeper_tick() -> Dict[str, Any]:
    """The daily pass. Never raises (scheduler-safe). Writes one
    platform_agent_runs row every pass, so its card on Agents is honest."""
    if not enabled():
        return {"skipped": True}
    started = datetime.now(timezone.utc)
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
            settings = await load_settings(c)
            tasks = await load_tasks(c)
            tz = zone(settings.get("tz"))
            today = started.astimezone(tz).date()
            score, inputs = await scorecard(c, settings, tasks, force=True)
            lv = inputs["lanes"]
            history = dict(settings.get("history") or {})
            daily = [h for h in (history.get("daily") or []) if h.get("date") != today.isoformat()]
            byk = {m["key"]: m for m in score["metrics"]}
            daily.append({"date": today.isoformat(),
                          "queue_waiting": byk.get("queue_waiting", {}).get("value"),
                          "tickets": byk.get("tickets", {}).get("value"),
                          "paying": byk.get("paying", {}).get("value"),
                          "signals_met": (score.get("signals") or {}).get("met", 0),
                          "build_used": lv["build_slots"]["used"]})
            history["daily"] = daily[-60:]
            await save_settings(c, {"history": history})

            findings = keeper_findings(score, lv, tasks, daily, today)
            pending = await _select(c, "platform_changelog", {"agent": f"eq.{AGENT}", "status": "eq.pending",
                                                              "select": "title", "limit": "200"})
            have = {p.get("title") for p in pending}
            written = 0
            for f in findings:
                if f["title"] in have:
                    continue
                await c.post(f"{SUPABASE_URL}/rest/v1/platform_changelog",
                             headers={**_service_headers(), "Prefer": "return=minimal"},
                             json={"category": "pending", "status": "pending", "agent": AGENT,
                                   "title": f["title"][:300], "detail": f["detail"][:2000]})
                written += 1
            bad = [m["label"] for m in score["metrics"] if m["state"] == "bad"]
            summary = (f"Build {lv['build_slots']['used']} of {BUILD_SLOTS} · "
                       f"{len(lv['due'])} of your tasks due or late · "
                       f"{(score.get('signals') or {}).get('met', 0)} hiring signals"
                       + (f" · red: {', '.join(bad)}" if bad else ""))
            await c.post(f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                         headers={**_service_headers(), "Prefer": "return=minimal"},
                         json={"agent": AGENT, "started_at": started.isoformat(),
                               "finished_at": datetime.now(timezone.utc).isoformat(),
                               "ok": True, "findings": written, "summary": summary[:500],
                               "details": {"scorecard": score["metrics"], "signals": score.get("signals")}})
        print(f"[ops_desk] keeper: {summary}", flush=True)
        return {"ok": True, "summary": summary, "findings": written}
    except Exception as e:
        print(f"[ops_desk] keeper failed: {type(e).__name__}: {str(e)[:200]}", flush=True)
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as c:
                await c.post(f"{SUPABASE_URL}/rest/v1/platform_agent_runs",
                             headers={**_service_headers(), "Prefer": "return=minimal"},
                             json={"agent": AGENT, "started_at": started.isoformat(),
                                   "finished_at": datetime.now(timezone.utc).isoformat(),
                                   "ok": False, "findings": 0, "summary": f"Failed: {str(e)[:200]}"})
        except Exception:
            pass
        return {"ok": False, "error": str(e)[:300]}
