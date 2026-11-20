"""member_cache.py — what every member page asked the database again, kept a little while.

Kevin, 2026-11-18: "the members app move slow when send messages in chat,
switching from one tab to another". Fix two of four (the stopwatch,
member_stopwatch.py, was one). Every /my page and POST read the same things
one after another before its own reads: the church on this address
(member_portal._church_for_request: about 140 ms on lovecityc.com, measured
by the stopwatch, the church's settings ride along), the signed-in member's
record (member_portal._session_for → contacts_for_ident), and, for the tab
bar, whether they lead anything and whether they sit on a board. A member
tapping from tab to tab asked the same questions every time.

WHAT IS KEPT, AND FOR HOW LONG (per server copy, in memory):
  - the church on an address: CHURCH_SECONDS (60). Only a row that was
    found: a failed read and "no such site" are never kept. The per-request
    checks still run on every request (a site taken offline, a sample
    church's preview cookie). A change the owner makes (member app off,
    sign-in paused, "sign everyone out", the site taken offline, the theme)
    shows within a minute on every copy; the owner's own member app
    switch (PATCH /member-portal/{id}) forgets it at once on the copy that
    saved it.
  - a signed-in member's record, per (church, email or phone):
    PEOPLE_SECONDS (30). A failed read ("try again") is never kept. A
    member removed from the records, or whose email changed, keeps their
    session at most that long; every other check (the signature, the
    church's sign-out epoch, the one-person-per-email rule) runs on every
    request. The owner's preview never uses it.
  - whether a member gets the Lead tab and the Board tab: TAB_SECONDS (60).
    These only draw the tab bar; the Lead and Board pages read who may see
    what on their own. A "no" is kept only when no read behind it failed
    (sb_clients.failures counts the ones a helper answers as "nothing").
  - Home's feed items from the member's groups (member_feed_more.gather:
    their Board posts and prayer requests), per (church, member):
    FEED_SECONDS (30). Marking a request forgets that member's copy on the
    server copy that saved it; a partial read is never kept.
Left alone, read every time: what is unread (member_portal_threads keeps it
15 s already), a member's spaces (space_leaders decides who reaches the Youth
and Kids rooms: a leader taken off must lose them at once), and every page's
own reads.

A hit hands out a copy, so one request can never change what the next one
reads. Each kind holds at most MAX_ITEMS entries (the oldest go first).
MEMBER_CACHE=off reads everything every time, as before.
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Hashable, Optional, Tuple

ENV = "MEMBER_CACHE"
CHURCH_SECONDS = 60.0
PEOPLE_SECONDS = 30.0
TAB_SECONDS = 60.0
FEED_SECONDS = 30.0
MAX_ITEMS = 2000


def enabled() -> bool:
    return (os.environ.get(ENV) or "on").strip().lower() not in ("off", "0", "false", "no")


def _now() -> float:
    return time.monotonic()


class Kept:
    """A small time-limited store. get() answers (True, a copy) for a live
    entry and (False, None) otherwise; put() never keeps None. Values are
    what PostgREST sent (JSON), so they're kept as JSON text and read back
    fresh on every hit: a few times faster than copy.deepcopy for a
    church's settings, and nothing is shared between requests."""

    def __init__(self, name: str, seconds: float, *, copy_value: bool = True):
        self.name = name
        self.seconds = seconds
        self.copy_value = copy_value
        # key → (expires, tag, value); the tag says whose it is (a church id).
        self._items: "OrderedDict[Hashable, Tuple[float, str, Any]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> Tuple[bool, Any]:
        if not enabled():
            return False, None
        with self._lock:
            hit = self._items.get(key)
            if hit is None:
                return False, None
            if hit[0] <= _now():
                del self._items[key]
                return False, None
            value = hit[2]
        return True, (json.loads(value) if self.copy_value else value)

    def put(self, key: Hashable, value: Any, tag: str = "") -> None:
        if value is None or not enabled():
            return
        kept = json.dumps(value, separators=(",", ":")) if self.copy_value else value
        with self._lock:
            self._items[key] = (_now() + self.seconds, str(tag or ""), kept)
            self._items.move_to_end(key)
            while len(self._items) > MAX_ITEMS:
                self._items.popitem(last=False)

    def forget(self, match: Callable[[Hashable, str], bool]) -> int:
        with self._lock:
            gone = [k for k, (_, tag, _v) in self._items.items() if match(k, tag)]
            for k in gone:
                del self._items[k]
        return len(gone)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        return len(self._items)


churches = Kept("church", CHURCH_SECONDS)
people = Kept("people", PEOPLE_SECONDS)
tabs = Kept("tabs", TAB_SECONDS, copy_value=False)
feed = Kept("feed", FEED_SECONDS)


def forget_church(business_id: Any) -> int:
    """Drop this church's kept site rows (the owner just changed it here)."""
    bid = str(business_id or "")

    return churches.forget(lambda _key, tag: tag == bid)


def forget_all() -> None:
    """For the tests."""
    for k in (churches, people, tabs, feed):
        k.clear()
