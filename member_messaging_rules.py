"""
member_messaging_rules.py — who may message whom. The ONE place.

Kevin's settled rules (2026-10-02, on top of 2026-09-29):

  · Someone can message only with BOTH a birthdate on their record and
    the church's "Can use messaging" switch on. Under 18 = teen rules.
    No birthdate = can't message yet.
  · A TEEN privately messages only their linked parents and other teens.
    There are no private messages between a teen and any other adult.
  · A linked parent can read all of their teen's chats, any time; the
    teen is told.
  · A group chat with a teen in it opens only with two approved adult
    leaders in it (leaders of the group who are adults and can message) —
    the same two-adult rule as youth video meetings.
  · Between members who share a group, a direct message just arrives;
    anyone else sends a request the other person accepts or ignores.
  · A block (either way) means no direct messages, and the blocked person
    isn't told.

Pure functions over plain dicts — no I/O — so every rule is unit-tested.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Iterable, Optional, Set, Tuple

ADULT_AGE = 18


def age(birthdate: Any, today: Optional[date] = None) -> Optional[int]:
    """Whole years, or None without a usable birthdate."""
    if not birthdate:
        return None
    try:
        b = birthdate if isinstance(birthdate, date) else date.fromisoformat(str(birthdate)[:10])
    except ValueError:
        return None
    t = today or date.today()
    if b > t:
        return None
    return t.year - b.year - ((t.month, t.day) < (b.month, b.day))


def is_teen(person: Dict[str, Any], today: Optional[date] = None) -> bool:
    a = age(person.get("birthdate"), today)
    return a is not None and a < ADULT_AGE


def can_message(person: Dict[str, Any], today: Optional[date] = None) -> bool:
    """The church's switch AND a usable birthdate."""
    return bool(person.get("enabled")) and age(person.get("birthdate"), today) is not None


def why_not(person: Dict[str, Any], today: Optional[date] = None) -> str:
    """'' when they can message; else a code for the member page."""
    if age(person.get("birthdate"), today) is None:
        return "no_birthdate"
    if not person.get("enabled"):
        return "not_enabled"
    return ""


def direct(sender: Dict[str, Any], recipient: Dict[str, Any], *,
           guardians_of: Dict[str, Set[str]], blocked: Set[Tuple[str, str]],
           share_group: bool, today: Optional[date] = None) -> Tuple[bool, str]:
    """May `sender` start (or keep) a private chat with `recipient`?
    Returns (ok, how): how = "direct" | "request" when ok, else a reason —
    "self", "sender_off", "recipient_off" (never says why), "blocked"
    (said as recipient_off: a block is never revealed), "teen_adult".

    `guardians_of[teen_id]` = the ids of that teen's linked parents.
    `blocked` = (blocker, blocked) pairs touching these two people."""
    s, r = str(sender["id"]), str(recipient["id"])
    if s == r:
        return False, "self"
    if not can_message(sender, today):
        return False, "sender_off"
    if not can_message(recipient, today):
        return False, "recipient_off"
    if (s, r) in blocked or (r, s) in blocked:
        return False, "recipient_off"
    s_teen, r_teen = is_teen(sender, today), is_teen(recipient, today)
    s_parent_of_r = s in guardians_of.get(r, set())
    r_parent_of_s = r in guardians_of.get(s, set())
    if s_parent_of_r or r_parent_of_s:
        return True, "direct"                    # a teen and their own parent
    if s_teen != r_teen:
        return False, "teen_adult"               # no private adult-teen messages
    return True, ("direct" if share_group else "request")


def group_chat(members: Iterable[Dict[str, Any]], today: Optional[date] = None) -> Tuple[bool, str]:
    """Is this group's chat open? `members` are the group's people, each
    with role, birthdate and enabled. Open unless a teen is in the group
    and fewer than two approved adult leaders are."""
    people = list(members)
    if not any(is_teen(p, today) for p in people):
        return True, ""
    leaders = [p for p in people if p.get("role") == "leader" and can_message(p, today) and not is_teen(p, today)]
    return (True, "") if len(leaders) >= 2 else (False, "two_adults")


def may_read_as_parent(guardian_id: str, teen: Dict[str, Any], guardians_of: Dict[str, Set[str]],
                       today: Optional[date] = None) -> bool:
    """A linked parent reads their teen's chats — while the teen is a teen."""
    return is_teen(teen, today) and str(guardian_id) in guardians_of.get(str(teen["id"]), set())
