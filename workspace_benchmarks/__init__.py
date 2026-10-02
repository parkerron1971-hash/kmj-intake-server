"""
workspace_benchmarks — the bands a business is measured against.

WHY THIS IS CODE AND NOT A TABLE

The first cut of this design put the whole benchmark row in Postgres. That
was wrong, and the reason is worth stating: a band is not tenant data, it
is an EDITORIAL CLAIM with a citation attached. "Median first-time fix is
75%, top quintile 86%, Aquant 2025 across 157 service organisations" is a
sentence this product asserts to a practitioner who may act on it. It
belongs in a file that ships with a release and goes through review, not
in rows that can be edited into a false claim with no trace.

So the split is:

  the BAND      average / target / floor / reading / source — here, in
                code, reviewed, citable
  the VALUE     what this particular business actually scores — computed
                per tenant from their own rows, and the only part that
                touches the database

`business_benchmarks` in the field catalog is therefore a PROVIDER rather
than a plain relation: the resolver calls `rows_for()` below instead of
building a query, and gets the two halves already joined.

EVERY BAND CARRIES ITS SOURCE. A benchmark asserted without attribution is
a number we made up, and the panel renders the citation underneath the
reading precisely so that can never be hidden. If a figure cannot be
attributed it does not go in this file.

`direction` matters more than it looks. Most metrics are better when
higher, but a no-show rate and a lockup figure are better when lower —
without the flag the panel congratulates a practice for a 22% no-show
rate because 22 is a bigger number than the 8% target.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("workspace_benchmarks")

# ── the split ────────────────────────────────────────────────────────
# The band DATA lives in bands/<vertical>.py, one module per vertical,
# each owned by one person. Everything below is shared machinery and
# stays here on purpose: the resolver tests monkeypatch
# `workspace_benchmarks._values_for`, and moving that function into a
# submodule would silently break the patch -- the test would still pass
# while exercising the real database call.
from workspace_benchmarks._band import HIGHER, LOWER, band as _band
from workspace_benchmarks.bands import BANDS, KEYS_FOR_VERTICAL

__all__ = [
    "BANDS", "KEYS_FOR_VERTICAL", "HIGHER", "LOWER",
    "keys", "keys_for", "band", "rows_for", "finding_for", "panel_for",
]

def keys() -> List[str]:
    return list(BANDS.keys())


def band(key: str) -> Optional[Dict[str, Any]]:
    b = BANDS.get(key)
    return dict(b) if b else None


def rows_for(business_id: str, wanted: List[str]) -> List[Dict[str, Any]]:
    """The provider the resolver calls for the `business_benchmarks` source.

    Returns one row per requested key, band and value already joined. A key
    with no band is DROPPED rather than rendered bare: the panel's whole
    argument is the comparison, and a lone figure in it would be a stat
    wall pretending to be a benchmark.

    A key whose value cannot be computed still comes back — with `value`
    None — because "we do not know yet" is information, and silently
    hiding a metric the layout asked for would make a missing figure look
    like a figure that is fine.
    """
    values = _values_for(business_id)
    out: List[Dict[str, Any]] = []
    for key in wanted:
        b = BANDS.get(key)
        if not b:
            logger.warning("no band declared for benchmark %r; dropping", key)
            continue
        row = dict(b)
        row["key"] = key
        row["value"] = values.get(key)
        out.append(row)
    return out


def _values_for(business_id: str) -> Dict[str, Optional[float]]:
    """This tenant's own scores, from the computed view.

    Fails SOFT and loudly-in-logs: a benchmark view that is missing or
    erroring must not take the whole workspace down with it. The panel
    renders the bands with empty values, which reads as "not measured
    yet" — correct, and far better than a blank home screen.
    """
    try:
        import sb_clients
        rows = sb_clients.sb_get_as_service(
            "/business_benchmark_values"
            f"?business_id=eq.{business_id}&select=key,value"
        ) or []
    except Exception:
        logger.warning("benchmark values unavailable for %s", business_id,
                       exc_info=True)
        return {}

    out: Dict[str, Optional[float]] = {}
    for r in rows:
        key = r.get("key")
        if not key:
            continue
        try:
            out[key] = float(r["value"]) if r.get("value") is not None else None
        except (TypeError, ValueError):
            out[key] = None
    return out


# ─── which bands a business type is measured against ─────────────────
# Keyed on businesses.type, resolved the same way terminology and the
# vertical desks resolve it. A second mechanism for "what vertical is
# this" is how the two drift apart, so this mirrors the desk's key set
# exactly — which is why salons and barbers are `personal_services`
# here and not `salon`.


def keys_for(vertical: Optional[str]) -> List[str]:
    """The bands this business type is measured against, or none.

    A vertical with no entry gets an EMPTY list rather than a generic
    fallback set. Measuring a business against numbers drawn from a
    different industry is worse than not measuring it — the panel simply
    does not render, which is honest.
    """
    if not vertical:
        return []
    key = str(vertical).strip().lower()
    if key in KEYS_FOR_VERTICAL:
        return list(KEYS_FOR_VERTICAL[key])
    try:
        import vertical_registry
        resolved = vertical_registry.resolve(key)
        if resolved and resolved != "custom":
            return list(KEYS_FOR_VERTICAL.get(resolved, []))
    except Exception:  # pragma: no cover - registry is a soft dependency
        logger.debug("vertical_registry unavailable", exc_info=True)
    return []


def _gap(row: Dict[str, Any]) -> Optional[float]:
    """How far short of target, as a share of the target.

    Normalised so metrics on different scales compare: 41% against a
    target of 50 is a bigger shortfall than 86% against 92, even though
    the raw distance is smaller.
    """
    value, target = row.get("value"), row.get("target")
    if value is None or target in (None, 0):
        return None
    if row.get("direction") == LOWER:
        return (value - target) / abs(target)
    return (target - value) / abs(target)


def finding_for(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The ONE number worth leading with.

    A dashboard shows four figures and leaves the practitioner to work
    out which matters. The whole reason Chief is in front of this data is
    to say which one — so this returns the band furthest short of its
    target, with its own reading as the explanation.

    Returns None when nothing is measured yet. A finding invented from no
    data would be the most confident-sounding lie on the screen.
    """
    scored = [(g, r) for r in rows for g in [_gap(r)] if g is not None and g > 0]
    if not scored:
        return None
    gap, row = max(scored, key=lambda pair: pair[0])
    return {
        "key": row["key"],
        "label": row["label"],
        "value": row["value"],
        "unit": row.get("unit"),
        "target": row.get("target"),
        "average": row.get("average"),
        "reading": row.get("reading"),
        "source": row.get("source"),
        "shortfall": round(gap, 3),
    }


def panel_for(business_id: str, vertical: Optional[str]) -> Dict[str, Any]:
    """Everything a benchmark panel needs, in one call."""
    rows = rows_for(business_id, keys_for(vertical))
    return {"rows": rows, "finding": finding_for(rows),
            "measured": any(r.get("value") is not None for r in rows)}
