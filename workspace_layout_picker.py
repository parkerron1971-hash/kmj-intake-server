"""
workspace_layout_picker.py — which desk this business opens on today.

THE POINT

An archetype says which ROOM a business is in. It cannot say what that
room should lead with this fortnight, and those are different questions.
Two law firms both get `law_firm`; one is drowning in filings and the
other has not been paid since June. Before this module they both got the
docket, because the archetype was the only dial there was.

So the layout is picked from the business's OWN NUMBERS — the benchmark
values already computed in `business_benchmark_values` and read against
the cited bands in `workspace_benchmarks`. The rule is deliberately
simple and deliberately explainable: find the band furthest below where
it should be, and open on the desk built for that.

WHY IT MUST EXPLAIN ITSELF

A layout that changes without saying why is a product that moved
somebody's furniture overnight. Every pick returns a `reason` written
for the practitioner, naming the number and its target, and Chief renders
it above the desk. If the pick cannot be justified in one sentence it is
not a pick, it is a guess, and this module returns the default instead.

WHY A USER OVERRIDE IS PERMANENT

Same rule as terminology, for the same reason. A practitioner who has
chosen a desk has told us something we could not compute; re-deciding it
for them next Tuesday is not intelligence, it is forgetting. An override
carries `origin: user_override` and this module will not overrule it —
it only ever says what it WOULD have picked, and the surface offers the
way back.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import workspace_benchmarks
import workspace_layouts

logger = logging.getLogger("workspace_layout_picker")

# ─── which desk answers which failure ────────────────────────────────
# Read as: when THIS band is the worst one, open on THAT layout.
#
# Only bands that a layout can actually DO something about appear here.
# A number with no desk behind it is not a trigger — it would move the
# furniture and leave the practitioner no better placed, which is worse
# than leaving them where they were.
TRIGGERS: Dict[str, Dict[str, Dict[str, str]]] = {
    "law_firm": {
        "collection": {
            "variant": "ledger",
            "because": "collection is the one number that decides whether "
                       "the firm can pay itself, and the docket cannot "
                       "show it",
        },
        "collection_lockup": {
            "variant": "ledger",
            "because": "money is sitting with clients for longer than the "
                       "profession tolerates",
        },
        "utilization": {
            "variant": "diary",
            "because": "an hour that goes unrecorded today cannot be "
                       "billed at all — not next quarter, not ever",
        },
        "realization": {
            "variant": "diary",
            "because": "recorded time is being written off, and that "
                       "happens at the point of recording rather than at "
                       "the point of billing",
        },
    },
}

# How far below its target a band must sit before it is worth moving
# somebody's home screen for. Below this the default stands: a desk that
# reshuffles itself over a two-point drift is a nervous desk.
MOVE_THRESHOLD = 0.15


def _shortfall(row: Dict[str, Any]) -> Optional[float]:
    """Normalised distance below target, or None if not measured.

    Normalised so bands on different scales compare: 39 against 97 is a
    bigger failure than 86 against 92 even though the raw gap is
    smaller, and a lockup measured in days must be comparable with a
    percentage.
    """
    value, target = row.get("value"), row.get("target")
    if value is None or target in (None, 0):
        return None
    if row.get("direction") == workspace_benchmarks.LOWER:
        return (value - target) / abs(target)
    return (target - value) / abs(target)


def pick(archetype: str, rows: List[Dict[str, Any]], *,
         stored: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Which variant this business should open on, and why.

    `rows` are benchmark rows as `workspace_benchmarks.rows_for` returns
    them. `stored` is what is already on the profile, if anything.

    Always returns a dict — never raises and never returns None. A home
    screen that fails to choose must still open.
    """
    key = (archetype or "").strip().lower()
    default = workspace_layouts.default_variant(key)
    out: Dict[str, Any] = {
        "variant": default, "origin": "default", "reason": "",
        "would_have_picked": None, "candidates": workspace_layouts.variants(key),
    }
    if not default:
        # One layout is a real answer, not a gap.
        out["reason"] = "This workspace has one layout."
        return out

    triggers = TRIGGERS.get(key) or {}

    # THE OVERRIDE IS FINAL. Computed first so nothing below can quietly
    # win, and so the surface can still show what Chief would have said.
    stored_variant = (stored or {}).get("variant")
    stored_origin = (stored or {}).get("origin")
    override = (stored_origin == "user_override"
                and workspace_layouts.is_variant(key, stored_variant))

    best = None
    for row in rows or []:
        if row.get("key") not in triggers:
            continue
        gap = _shortfall(row)
        if gap is None or gap < MOVE_THRESHOLD:
            continue
        if best is None or gap > best[0]:
            best = (gap, row)

    if best:
        gap, row = best
        t = triggers[row["key"]]
        unit = row.get("unit") or ""
        fmt = (lambda n: f"{n:g}{unit}") if unit == "%" else (
            lambda n: f"{n:g} {unit}".strip())
        chosen = t["variant"]
        reason = (
            f"{row.get('label', row['key'])} is {fmt(row['value'])} against "
            f"a target of {fmt(row['target'])} — {t['because']}."
        )
        if override:
            out.update(variant=stored_variant, origin="user_override",
                       would_have_picked=chosen,
                       reason=reason)
        else:
            out.update(variant=chosen, origin="chief", reason=reason)
        return out

    # Nothing is far enough below its band to justify moving anything.
    if override:
        out.update(variant=stored_variant, origin="user_override",
                   reason="You chose this desk.")
        return out
    if stored_origin == "chief" and workspace_layouts.is_variant(key, stored_variant):
        # Chief picked this before and nothing now argues against it.
        # Leaving it put matters: a desk that reverts to default the
        # moment a number recovers is a desk that flickers.
        out.update(variant=stored_variant, origin="chief",
                   reason="Nothing is far enough off its band to move this.")
        return out
    out["reason"] = "Everything measured is inside its band."
    return out


def pick_for_business(business_id: str, archetype: str, vertical: Optional[str],
                      *, stored: Optional[Dict[str, Any]] = None
                      ) -> Dict[str, Any]:
    """`pick`, with the benchmark read done for you.

    Fails soft on purpose: if the values cannot be read the business
    still gets its default desk, because a home screen that will not
    open is worse than one that opens on the wrong thing.
    """
    try:
        rows = workspace_benchmarks.rows_for(
            business_id, workspace_benchmarks.keys_for(vertical))
    except Exception:
        logger.warning("benchmark read failed for %s; using the default layout",
                       business_id, exc_info=True)
        rows = []
    return pick(archetype, rows, stored=stored)
