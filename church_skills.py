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
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("church_skills")

SKILLS_DIR = pathlib.Path(__file__).resolve().parent / "church_skills"
MAX_PER_TURN = 1
CHAPTER_CHARS = 3000

# This turn's church and login lane, for the action_guide lookup (set in chief_chat).
_TURN: contextvars.ContextVar[Optional[Tuple[Dict[str, Any], Any]]] = contextvars.ContextVar(
    "church_skills.turn", default=None)


def mode() -> str:
    m = (os.environ.get("CHIEF_CHURCH_SKILLS") or "off").strip().lower()
    return m if m in ("off", "owner", "on") else "off"


def switched_on(biz: Any) -> bool:
    """Off, the platform owner's own church, or every church."""
    m = mode()
    if m == "off" or not isinstance(biz, dict) or not biz.get("id"):
        return False
    try:
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
        if key in ("triggers", "actions"):
            fields[key] = _list(value)
        elif key:
            fields[key] = value
    body = m.group(2).strip()
    if not fields.get("name") or not fields.get("use_when") or not fields.get("actions") or not body:
        return None
    return {"name": fields["name"], "use_when": fields["use_when"], "triggers": fields.get("triggers") or [],
            "actions": fields["actions"], "body": body, "path": path}


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


def allowed(skill: Dict[str, Any], scope: Any) -> bool:
    """Whether this login may use every action the skill names (its lane; the owner and Admins have every one)."""
    import chief_areas
    return all(chief_areas.refusal(v, {}, scope) is None for v in skill["actions"])


def matching(message: str) -> List[Dict[str, Any]]:
    text = (message or "").lower()
    scored = []
    for s in skills():
        hits = sum(1 for t in s["triggers"] if t and _word(t).search(text))
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

def contents_for(biz: Any) -> str:
    """The contents, for the per-church cached segment; '' when skills are off for this church."""
    if not switched_on(biz) or not skills():
        return ""
    lines = [f"  {s['name']}: {s['use_when']}" for s in skills()]
    return ("CHURCH JOBS WITH WRITTEN STEPS (when one applies, its steps come with the message; if they haven't, "
            "look them up with action_guide and the job's name before you start):\n" + "\n".join(lines) + "\n")


def begin_turn(biz: Any, scope: Any) -> None:
    _TURN.set((biz, scope) if switched_on(biz) else None)


def turn_block(biz: Any, message: str, scope: Any) -> str:
    """The chapter for this turn, or ''. Never raises."""
    try:
        if not switched_on(biz):
            return ""
        picked = [s for s in matching(message) if allowed(s, scope)][:MAX_PER_TURN]
        if picked:
            print(f"[church skills] {picked[0]['name']} for this turn", flush=True)
        return "".join(_chapter(s) for s in picked)
    except Exception as e:  # noqa: BLE001 — no chapter is today's Chief
        print(f"[church skills] not read: {type(e).__name__}", flush=True)
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
                return _chapter(s) if allowed(s, turn[1]) else None
        return None
    except Exception:  # noqa: BLE001
        return None
