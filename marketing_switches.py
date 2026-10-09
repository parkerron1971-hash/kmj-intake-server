"""marketing_switches.py — the tenant marketing suite's two server switches, read in ONE place.

Kevin, 2026-10-08: "open to everyone because right now no one is using it so
you can set how it will work for everyone." Since then both switches are ON
when unset, and each is a kill switch. Every reader asks this module:
business_marketing_planner (desk_scope, desk_on_for: the fan-out, the
scheduled and queued runs, the flyer and open-chairs ticks, the owner's
request, the preview), platform_suite (whether the flag lookup that keeps
Solutionist's own business out is needed), Chief's desk verbs (through
desk_on_for), business_marketing (Post now, GET /engine's `sending`) and
business_marketing_dispatch (the sender and the delivery watch).

  MARKETING_DESK             unset or empty: every business ('*').
                             'off' (or false, no, 0): nobody.
                             '*' or 'on': every business.
                             A comma-separated list: those business ids. A
                             token that is not a business id is ignored, and
                             a value with no id in it switches nobody on: a
                             typo never widens the desk.
  MARKETING_DESK_PUBLISHING  unset or empty: on (the worker hands approved
                             posts to the posting service and watches them).
                             'off' (or false, no, 0): approved posts wait,
                             "Post now" refuses, nothing is checked or
                             announced. Any other value: on.

Neither switch ever posts anything by itself: a post still needs the owner's
OK (or, on the Solutionist plan, a standing OK the owner granted), the
posting pilot (POST_FOR_ME_PILOT_BUSINESSES), a connected account and the
fan-out's per-tick cap, jitter and spend headroom. Solutionist's own business
stays out while its marketing runs on the Mission Control desk
(platform_suite.kept_out, #1345), whatever MARKETING_DESK says.
"""
from __future__ import annotations

import os
from typing import Any
from uuid import UUID

DESK_ENV = 'MARKETING_DESK'
PUBLISHING_ENV = 'MARKETING_DESK_PUBLISHING'
EVERY = '*'
OFF_WORDS = frozenset({'off', 'false', 'no', '0'})
EVERY_WORDS = frozenset({EVERY, 'on'})


def _raw(name: str) -> str:
    return (os.environ.get(name) or '').strip()


def desk_scope() -> Any:
    """MARKETING_DESK as written: '*' (every business: unset, empty, '*' or
    'on'), None (nobody: 'off'), or the frozenset of business ids it names
    (None when it names none)."""
    raw = _raw(DESK_ENV)
    if not raw or raw.lower() in EVERY_WORDS:
        return EVERY
    if raw.lower() in OFF_WORDS:
        return None
    ids = set()
    for part in raw.split(','):
        try:
            ids.add(str(UUID(part.strip())))
        except ValueError:
            continue
    return frozenset(ids) or None


def desk_names(business_id: Any) -> bool:
    """MARKETING_DESK, as written, covers this business."""
    scope = desk_scope()
    if scope is None:
        return False
    if scope == EVERY:
        return True
    try:
        return str(UUID(str(business_id))) in scope
    except ValueError:
        return False


def publishing_on() -> bool:
    """MARKETING_DESK_PUBLISHING: on unless it says off."""
    return _raw(PUBLISHING_ENV).lower() not in OFF_WORDS
