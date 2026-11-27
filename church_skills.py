"""church_skills.py — written steps for church jobs, loaded only when a job needs them.

Kevin, 2026-11-26, on "Church Skills for Chief": add written, reviewable steps
for church jobs. Chief already knows what each action does (its manual); what
it lacked was the ORDER of a job and its checks: read the count before
recording, never close a count, never say "in the bank" before the match.

    church_skills/*.md ... one skill a file (build_skills' format: frontmatter,
                           then the steps). Fields:
                             name      the skill's name
                             use_when  one line: when it applies
                             triggers  words that select it (word-boundary, as
                                       build_skills matches)
                             actions   the actions its steps use; every one must
                                       be one of Chief's (a test checks)
                             needs     the church features the job rides on
                                       (NEEDS): a church where one isn't
                                       switched on gets no steps for it
    contents_for(biz) .... the CONTENTS: one line per skill (name and use_when),
                           in the per-church cached segment. Kevin's cost idea:
                           only the contents ride every turn, the chapters don't.
    turn_block(biz, message, scope)
                           the chapter for THIS turn, when the message matches a
                           skill's words AND the login may use every action the
                           skill names (chief_areas.refusal is None for each): a
                           login with no key to a job is handed nothing. The
                           turn's tail, never a shared segment.
    lookup(name) ......... the chapter by name for the action_guide lookup
                           (chief_lean_brief), when the words missed. Same gate.

WHAT IT IS NOT
  * Not a gate. The handlers still check who may do what (require_finance,
    the Giving keeper's key). Leaving a chapter out only saves its words.
  * Not a replacement for the manual. Nothing moves out of it: an earlier
    attempt to slim a prompt by keyword-loading its parts was closed because a
    missed match meant nothing worked (docs/PROMPT_EXTRACTION_RULING.md).
    Skills only add.

SWITCH: CHIEF_CHURCH_SKILLS = off (the default) | owner (the platform owner's
own church: Love City first) | on. A skill is kept only if a with/without
comparison on the same church questions shows it helps; that comparison bills
production and has not been run.
"""
from __future__ import annotations

import contextvars
import logging
import os
import pathlib
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("church_skills")

SKILLS_DIR = pathlib.Path(__file__).resolve().parent / "church_skills"
MAX_PER_TURN = 1
CHAPTER_CHARS = 3000

# A job's actions only work where the feature under them is switched on for the church.
def _giving_services(bid: Any) -> bool:
    import giving_ways
    return bool(giving_ways.switched_on(bid))


def _giving_deposits(bid: Any) -> bool:
    import giving_deposits
    return bool(giving_deposits.switched_on(bid))


def _serving_spots(bid: Any) -> bool:
    import chief_serving_spots
    return bool(chief_serving_spots.turn_ready(bid))


NEEDS = {"giving_services": _giving_services, "giving_deposits": _giving_deposits, "serving_spots": _serving_spots}

# This turn's church and login lane, for the action_guide lookup (set in chief_chat).
_TURN: contextvars.ContextVar[Optional[Tuple[Dict[str, Any], Any]]] = contextvars.ContextVar(
    "church_skills.turn", default=None)


def mode() -> str:
    m = (os.environ.get("CHIEF_CHURCH_SKILLS") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(biz: Any) -> bool:
    """Off, the platform owner's own church, or every church. Only where the short manual is on: the contents
    tell Chief to look a job's steps up with its lookup (action_guide), which only it has. It reads (who owns
    the church): call it off the event loop."""
    m = mode()
    if m == "off" or not isinstance(biz, dict) or not biz.get("id"):
        return False
    try:
        import chief_lean_brief
        if not chief_lean_brief.enabled():
            return False
        import church_follow_up as cfu
        if not cfu.is_church(biz):
            return False
        import sample_church
        if sample_church.is_sample(biz["id"]):
            return False
    except Exception:  # noqa: BLE001
        return False
    if m == "on":
        return True
    try:
        import member_asks
        return bool(member_asks.platform_church(biz["id"]))
    except Exception:  # noqa: BLE001 — can't tell: off
        return False


# ─── The skills ───────────────────────────────────────────────────────

def _list(raw: str) -> List[str]:
    return [x.strip().strip("\"'").lower() for x in raw.split(",") if x.strip()]


def parse(text: str, path: str = "") -> Optional[Dict[str, Any]]:
    """A skill off its file, or None when it isn't one."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text or "", re.S)
    if not m:
        return None
    fields: Dict[str, Any] = {}
    for line in m.group(1).splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip()
        if key in ("triggers", "actions", "needs"):
            fields[key] = _list(value)
        elif key:
            fields[key] = value
    body = m.group(2).strip()
    if not fields.get("name") or not fields.get("use_when") or not fields.get("actions") or not body:
        return None
    return {"name": fields["name"], "use_when": fields["use_when"], "triggers": fields.get("triggers") or [],
            "actions": fields["actions"], "needs": fields.get("needs") or [], "body": body, "path": path}


@lru_cache(maxsize=1)
def skills() -> Tuple[Dict[str, Any], ...]:
    out = []
    if SKILLS_DIR.is_dir():
        for p in sorted(SKILLS_DIR.glob("*.md")):
            try:
                s = parse(p.read_text(encoding="utf-8"), str(p))
            except OSError:
                s = None
            if s is None:
                logger.warning(f"church skill {p.name} is malformed: skipped")
                continue
            out.append(s)
    return tuple(out)


@lru_cache(maxsize=512)
def _word(trigger: str) -> "re.Pattern[str]":
    """build_skills' rule: a whole word or phrase, an optional plural s, never inside another word."""
    return re.compile("(?<![a-z0-9])" + re.escape(trigger) + "s?(?![a-z0-9])")


def allowed(skill: Dict[str, Any], scope: Any, ready: Optional[Dict[str, bool]] = None) -> bool:
    """Whether this login may use every action the skill names (its lane; the owner and Admins have every one),
    and every feature the job rides on is switched on (`ready`, from features_on; none named: none needed)."""
    import chief_areas
    if any(not (ready or {}).get(n, False) for n in skill.get("needs") or []):
        return False
    return all(chief_areas.refusal(v, {}, scope) is None for v in skill["actions"])


def features_on(biz: Any) -> Dict[str, bool]:
    """Which of NEEDS are switched on for this church. Reads: call it off the event loop."""
    out: Dict[str, bool] = {}
    bid = (biz or {}).get("id") if isinstance(biz, dict) else None
    for name, fn in NEEDS.items():
        try:
            out[name] = bool(bid) and fn(bid)
        except Exception:  # noqa: BLE001 — can't tell: not on
            out[name] = False
    return out


def matching(message: str) -> List[Dict[str, Any]]:
    text = (message or "").lower()
    scored = []
    for s in skills():
        hits = len({t.rstrip("s") for t in s["triggers"] if t and _word(t).search(text)})
        if hits:
            scored.append((-hits, s["name"], s))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [s for _, _, s in scored]


def _chapter(skill: Dict[str, Any]) -> str:
    body = skill["body"]
    if len(body) > CHAPTER_CHARS:
        body = body[:CHAPTER_CHARS].rsplit("\n", 1)[0]
    return (f"CHURCH JOB STEPS: {skill['name']} (written for this kind of job; follow them, and where they and a "
            f"tool's result disagree, the result is what is true):\n{body}\n")


# ─── What a turn reads ────────────────────────────────────────────────

class Turn:
    """What a turn knows about skills, worked out once off the event loop (prepare), then used without reads."""
    def __init__(self, biz: Any, on: bool, ready: Dict[str, bool]):
        self.biz, self.on, self.ready = biz, on, ready


def prepare(biz: Any) -> "Turn":
    """Whether skills are on for this church and which features are: the reads a turn needs, in one call, for
    asyncio.to_thread."""
    on = switched_on(biz)
    return Turn(biz, on, features_on(biz) if on else {})


def contents_for(turn: "Turn") -> str:
    """The contents, for the per-church cached segment; '' when skills are off for this church. Only the jobs
    whose features are on for it, so a church is never pointed at a job its account can't do."""
    if not turn or not turn.on:
        return ""
    shown = [s for s in skills() if all(turn.ready.get(n, False) for n in s.get("needs") or [])]
    if not shown:
        return ""
    lines = [f"  {s['name']}: {s['use_when']}" for s in shown]
    return ("CHURCH JOBS WITH WRITTEN STEPS (when one applies, its steps come with the message; if they haven't, "
            "look them up with action_guide and the job's name before you start; if the lookup has none, the job "
            "isn't open to this login):\n" + "\n".join(lines) + "\n")


def begin_turn(turn: "Turn", scope: Any) -> None:
    _TURN.set((turn, scope) if turn and turn.on else None)


def turn_block(turn: "Turn", message: str, scope: Any) -> str:
    """The chapter for this turn, or ''. No reads. Never raises."""
    try:
        if not turn or not turn.on:
            return ""
        picked = [s for s in matching(message) if allowed(s, scope, turn.ready)][:MAX_PER_TURN]
        if picked:
            print(f"[church skills] {picked[0]['name']} for this turn", flush=True)
        return "".join(_chapter(s) for s in picked)
    except Exception as e:  # noqa: BLE001 — no chapter is today's Chief
        print(f"[church skills] not read: {type(e).__name__}", flush=True)
        return ""


# ─── Carrying a job's steps to its follow-ups ─────────────────────────
#
# Kevin, 2026-11-27 (through KAI), after the log check found the follow-up turn of a giving job had no steps:
# "carry a skill's steps through the next turn or two of the same job, so follow-ups like 'ok, now record
# it' keep the giving or serving steps", bounded so stale steps never reach an unrelated turn.
#
# A job's steps are carried to THIS message only when every one of these holds:
#   * turns: a user message at most CARRY_TURNS back in this chat (the history the app sends) asked for the
#     job, by the same trigger words a fresh message is matched on, and the login may still use it;
#   * this message, and every message between, reads as a continuation: no other job's words, no new-topic
#     opening ("also", "different question", "by the way"...), not a long new request (CONTINUE_WORDS);
#   * time and the same chat, from this login's own saved turns (chief_conversations, saved by login): its
#     last turn is this chat's last message and ended under CARRY_MINUTES ago, and the job's message ended
#     under CARRY_JOB_MINUTES ago. Any turn after the job's message ran only the job's own actions (or a
#     screen move): a turn that did other work is a new topic. A read that fails, or rows that don't line
#     up with the history (another chat, turns not saved by login), carries nothing.
# The carried steps say they are carried and to be followed only if this message continues the job.
CARRY_TURNS = 2
CARRY_MINUTES = 30
CARRY_JOB_MINUTES = 45
CONTINUE_WORDS = 40
CLOCK_SKEW_SECONDS = 60     # a saved turn a little "in the future" (another replica's clock), never more
# A new question ("who is preaching Sunday?") is a new topic, not more of the job (Codex review).
_NEW_QUESTION = re.compile(r"^\W*(?:who|what|when|where|why|which|how)\b.*\?\s*$", re.I | re.S)
_NEUTRAL_ACTIONS = frozenset({"navigate", "close_view", "show_view", "set_chat_window", "action_guide"})
_NEW_TOPIC = re.compile(
    r"^\W*(?:also\b|and also\b|another (?:thing|question)|different (?:thing|question|topic)|new (?:question|topic)|"
    r"unrelated|switching gears|change of (?:subject|topic)|by the way\b|btw\b|on another note|separate question|"
    r"one more thing|forget (?:that|it)|never mind|nevermind)", re.I)


def _text(m: Any) -> Tuple[str, str]:
    if isinstance(m, dict):
        return str(m.get("role") or ""), str(m.get("content") or "")
    return str(getattr(m, "role", "") or ""), str(getattr(m, "content", "") or "")


def _same(a: Any, b: Any) -> bool:
    """Two copies of one message (the history's and the saved turn's), compared whole, as the saved turn keeps
    it (whitespace folded, at most 4,000 characters: chief_of_staff._conversation_row)."""
    def norm(v: Any) -> str:
        return " ".join(str(v or "").split())[:4000].lower()
    return bool(norm(a)) and norm(a) == norm(b)


def continues(message: str) -> bool:
    """Whether a message reads as more of the same job: short, no new-topic opening, no job's own words."""
    text = re.sub(r"\s+", " ", message or "").strip()
    if (not text or _NEW_TOPIC.match(text) or _NEW_QUESTION.match(text)
            or len(text.split()) > CONTINUE_WORDS):
        return False
    return not matching(text)


def carry_candidate(turn: "Turn", message: str, history: Any, scope: Any
                    ) -> Optional[Tuple[Dict[str, Any], int, List[str]]]:
    """(the job, how many user messages back it was asked, those messages newest first) from the history
    alone, or None. No reads."""
    if not turn or not turn.on or not continues(message):
        return None
    users = [c for r, c in (_text(m) for m in (history or [])) if r == "user" and c.strip()]
    if users and _same(users[-1], message):
        users = users[:-1]                      # the history already holds this message
    seen: List[str] = []
    for back, text in enumerate(reversed(users[-CARRY_TURNS:]), 1):
        seen.append(text)
        picked = [s for s in matching(text) if allowed(s, scope, turn.ready)][:MAX_PER_TURN]
        if picked:
            return picked[0], back, seen
        if not continues(text):
            return None
    return None


def _ended(row: Dict[str, Any]) -> Optional[datetime]:
    try:
        at = datetime.fromisoformat(str(row.get("ended_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=timezone.utc)


def _saved_turns(business_id: Any, user_id: Any, n: int) -> Optional[List[Dict[str, Any]]]:
    """This login's last n saved turns, newest first; None when they can't be read."""
    from urllib.parse import quote
    import sb_clients
    rows = sb_clients.sb_get_as_service(
        f"/chief_conversations?business_id=eq.{quote(str(business_id), safe='')}"
        f"&user_id=eq.{quote(str(user_id), safe='')}&message_count=eq.2&select=ended_at,messages,key_topics"
        f"&order=ended_at.desc&limit={int(n)}")
    return rows if isinstance(rows, list) else None


def _asked(row: Dict[str, Any]) -> Optional[str]:
    """The person's message in one saved turn; None when the row isn't one usable turn."""
    msgs = row.get("messages") if isinstance(row, dict) else None
    if not isinstance(msgs, list) or not msgs or not isinstance(msgs[0], dict) or msgs[0].get("role") != "user":
        return None
    return str(msgs[0].get("content") or "")


def _fresh(at: Optional[datetime], now: datetime, minutes: int) -> bool:
    """Ended under `minutes` ago, and not later than now (beyond a minute of clock skew)."""
    if at is None:
        return False
    age = now - at
    return -timedelta(seconds=CLOCK_SKEW_SECONDS) <= age < timedelta(minutes=minutes)


def carried_block(turn: "Turn", message: str, history: Any, scope: Any, user_id: Any,
                  now: Optional[datetime] = None) -> str:
    """The job's steps carried to this follow-up, or ''. Reads this login's last saved turns only when the
    history names a job (call it off the event loop). Never raises."""
    try:
        found = carry_candidate(turn, message, history, scope)
        if not found or not user_id or not isinstance(turn.biz, dict) or not turn.biz.get("id"):
            return ""
        skill, back, seen = found
        rows = _saved_turns(turn.biz["id"], user_id, back)
        if not rows or len(rows) < back:
            return ""
        now = now or datetime.now(timezone.utc)
        if not (_fresh(_ended(rows[0]), now, CARRY_MINUTES) and _fresh(_ended(rows[back - 1]), now, CARRY_JOB_MINUTES)):
            return ""
        # The saved turns are this chat's own messages, whole, newest first, in step with the history.
        if not all((_asked(rows[i]) is not None) and _same(_asked(rows[i]), seen[i]) for i in range(back)):
            return ""
        # A turn since the job's message counts only when it did some of the job (one of its own actions) and
        # nothing else but a screen move; one that did other work, or only talked, or whose list of actions
        # can't be read, is a new topic (Codex review: "who is preaching Sunday?" ran nothing and passed).
        own = set(skill["actions"])
        for i in range(back - 1):
            kinds = rows[i].get("key_topics")
            if not isinstance(kinds, list) or not all(isinstance(k, str) for k in kinds):
                return ""
            if not (set(kinds) & own) or set(kinds) - own - _NEUTRAL_ACTIONS:
                return ""
        print(f"[church skills] {skill['name']} carried ({back} back)", flush=True)
        return (f"CHURCH JOB STEPS, CARRIED from this chat's message {back} turn{'' if back == 1 else 's'} ago "
                f"(follow them only if this message continues that job; if it is about something else, ignore "
                f"them):\n" + _chapter(skill)[len("CHURCH JOB STEPS: "):])
    except Exception as e:  # noqa: BLE001 — nothing carried is today's Chief
        print(f"[church skills] carry not read: {type(e).__name__}", flush=True)
        return ""


def lookup(name: str) -> Optional[str]:
    """The chapter by name for action_guide, inside a turn whose church has skills on and whose login may use it.
    None otherwise (and for a name that isn't a skill)."""
    try:
        turn = _TURN.get()
        if not turn:
            return None
        key = re.sub(r"[\s_]+", "-", (name or "").strip().lower())
        for s in skills():
            if s["name"] == key:
                return _chapter(s) if allowed(s, turn[1], turn[0].ready) else None
        return None
    except Exception:  # noqa: BLE001
        return None
