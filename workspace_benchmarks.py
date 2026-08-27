"""
workspace_benchmarks.py — the bands a business is measured against.

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

HIGHER = "higher_better"
LOWER = "lower_better"


def _band(label, average=None, target=None, floor=None, unit="%",
          direction=HIGHER, scale_max=None, reading="", source=""):
    return {
        "label": label, "average": average, "target": target, "floor": floor,
        "unit": unit, "direction": direction, "scale_max": scale_max,
        "reading": reading, "source": source,
    }


BANDS: Dict[str, Dict[str, Any]] = {

    # ── salon ────────────────────────────────────────────────────────
    "rebooking_rate": _band(
        "Rebooking rate", average=52, target=80, floor=60,
        reading="Clients who leave with the next appointment booked come back "
                "at 70-80%. Those who leave without one come back at 30-40%. "
                "The industry sits at 52%; top performers clear 80%, and 60% "
                "is the line below which a book stops replacing itself. Most "
                "booking systems never surface this — you have to dig it out "
                "of a report.",
        source="Blvd + Callpad salon benchmarks, 2026"),
    "chair_utilization": _band(
        "Chair utilisation", average=48, target=65, floor=55,
        reading="The median salon runs 47-49%, so most of the industry sits "
                "well under the healthy band, which starts at 65%. Everything "
                "below it is chair time nobody paid for.",
        source="Zenoti + Blvd, 2026"),
    "retail_attach": _band(
        "Retail attach", average=12, target=20, floor=8,
        reading="Retail as a share of service revenue. Median independents run "
                "8-15%; the top quartile clears 20-30%. A client who takes "
                "product home is markedly likelier to be back inside 30 days.",
        source="Dall Italia benchmarking, ~1,800 operators"),
    "new_client_return": _band(
        "New clients who come back", average=50, target=65, floor=40,
        reading="About half of first-timers never return for a second visit. "
                "This sits upstream of every other number here — it is the "
                "single biggest leak in the business.",
        source="Callpad + Zylu, 2026"),

    # ── trades ───────────────────────────────────────────────────────
    "first_time_fix": _band(
        "First-time fix rate", average=75, target=86, floor=70,
        reading="Median across 157 service organisations is 75%; the top fifth "
                "reach 86% and the bottom fifth sit at 53%. Under 70% is a "
                "dispatch and parts problem, not a skill problem — the tech "
                "arrived without what the job needed.",
        source="Aquant service benchmarks, 2025"),
    "tech_utilization": _band(
        "Technician utilisation", average=55, target=75, floor=50,
        reading="Share of paid hours that end up on an invoice. The benchmark "
                "is 75-85%. Below that, a third of what you pay for is never "
                "billable.",
        source="VSight + Simpro field-service KPIs, 2025"),
    "estimate_close_rate": _band(
        "Estimate close rate", average=50, target=60, floor=40,
        reading="Healthy residential sits at 40-60%. Below 40% is almost "
                "always follow-up rather than price: 90% of contractors stop "
                "after the first or second touch.",
        source="ContractorAccelerator, Sept 2025"),
    "membership_attach": _band(
        "Membership attach", average=45, target=60, floor=40,
        reading="The number that predicts next year rather than this one. "
                "Baseline is 40-50%; best-in-class runs 60-90%, and members "
                "are worth several times a one-off customer over their life.",
        source="Home-services operator benchmarks, 2025"),

    # ── therapist ────────────────────────────────────────────────────
    "client_retention": _band(
        "Clients reaching 8+ sessions", average=85, target=90, floor=75,
        reading="A healthy practice holds 80-85% of clients to eight sessions "
                "or more; strong group practices reach 90-95%. Early drop-off "
                "is the expensive kind — the intake work is already spent.",
        source="Private-practice KPI benchmarks, 2025"),
    "no_show_rate": _band(
        "No-show and late cancellation", average=15, target=8, floor=20,
        direction=LOWER, scale_max=30,
        reading="Lower is better here. Under 15% keeps a schedule and its "
                "income stable; high performers sit at 5-8%. Behavioural "
                "health runs far worse than primary care, so the ceiling is "
                "real.",
        source="Curogram + SimplePractice, 2025"),
    "caseload_utilization": _band(
        "Caseload utilisation", average=70, target=80, floor=65,
        reading="75-85% balances a full book against documentation, "
                "coordination and supervision. Above 85% is a hiring signal, "
                "not a win — it is the number that precedes burnout.",
        source="Therapy clinic KPI benchmarks, 2025"),
    "booked_before_leaving": _band(
        "Next session booked in the room", target=80, floor=50,
        reading="No published benchmark exists for this one, so none is "
                "shown. It is the same mechanism as a salon rebook, and "
                "practices that do it hold caseloads visibly better than "
                "those that email later.",
        source="No industry benchmark — measured against your own practice"),

    # ── ministry ─────────────────────────────────────────────────────
    "first_time_return": _band(
        "First-timers who come back", average=10, target=20, floor=6,
        reading="The average church sees 6-15% of first-time guests return for "
                "a second visit; growing churches reach about 20%. Around 70% "
                "of leaders say they have no effective process here, and 36% "
                "have none at all.",
        source="Nieuwhof / PastorMentor / Unstuck Group"),
    "second_time_return": _band(
        "Second-timers who come back", average=25, target=40, floor=20,
        reading="Once somebody comes twice, most of the work is done. Growing "
                "churches convert about 40% of second-time guests into third "
                "visits.",
        source="Church retention benchmarks"),
    "third_time_stay": _band(
        "Third-timers who stay", average=35, target=60, floor=30,
        reading="About 35% of third-time guests become regulars; in growing "
                "churches it approaches 60%. Three visits is the threshold "
                "worth designing around.",
        source="Church retention benchmarks"),
    "giving_participation": _band(
        "Households giving", average=40, target=45, floor=25,
        reading="The number a giving total hides. Income can be flat while "
                "participation falls, which means a handful of large gifts are "
                "masking disengagement across the base — a very different "
                "problem from a bad year.",
        source="ChurchTechToday"),

    # ── consultant ───────────────────────────────────────────────────
    "utilization_now": _band(
        "Utilisation, this month", average=70, target=78, floor=60,
        reading="75-85% is the working band. Above 90% you have no bench, and "
                "the next urgent client request has nowhere to go but your "
                "weekend.",
        source="Consulting-firm KPI benchmarks, 2026"),
    "utilization_projected": _band(
        "Utilisation, next six weeks", target=70, floor=40,
        reading="Forward capacity — the number no other business here needs. "
                "At half booked you can take work on; near full you cannot, "
                "and the time to say so is now rather than in three weeks when "
                "you are already late.",
        source="No industry benchmark — this is your own forward book"),
    "proposal_win_rate": _band(
        "Proposal win rate", average=40, target=55, floor=25,
        reading="Proposals out against engagements signed. A leading "
                "indicator: it moves months before revenue does.",
        source="Consulting-firm KPI benchmarks, 2026"),
    "retainer_renewal": _band(
        "Retainer renewal", average=75, target=90, floor=60,
        reading="Winning a new client costs five to seven times what keeping "
                "one does, so this number is worth more attention than the "
                "pipeline above it.",
        source="Professional-services benchmarks, 2026"),

    # ── nonprofit ────────────────────────────────────────────────────
    "donor_retention": _band(
        "Donor retention", average=45, target=55, floor=35,
        reading="Sector average lands between the mid-forties and mid-fifties "
                "depending on how it is counted; the top quartile reaches "
                "about 70%.",
        source="Fundraising Effectiveness Project / Virtuous, 2026"),
    "first_time_donor_retention": _band(
        "First-time donors who give again", average=24, target=35, floor=18,
        reading="Three out of four first-time donors never give a second gift. "
                "It is the largest and quietest loss in the sector, and a "
                "total-raised figure will look healthy right up until the base "
                "has gone.",
        source="Fundraising Effectiveness Project, 2025"),
    "recurring_share": _band(
        "Income that recurs", average=20, target=35, floor=12,
        reading="Recurring donors are retained at about 83% against 45% for "
                "single-gift donors, and are worth several times as much over "
                "their life. Every point moved here compounds.",
        source="Dataro + Bloomerang, 2025"),
    "grants_on_time": _band(
        "Reports filed on time", target=100, floor=85,
        reading="No industry benchmark, and it does not need one — a late "
                "acquittal does not cost a late fee, it costs the next grant. "
                "The only acceptable target is all of them.",
        source="No industry benchmark — the target is 100%"),

    # ── law firm ─────────────────────────────────────────────────────
    "utilization": _band(
        "Utilisation — hours captured", average=38, target=50, floor=30,
        reading="The average lawyer records 3.0 billable hours in an "
                "eight-hour day. A solo records 2.1; a lawyer in a firm of "
                "twenty-plus records 3.6. This is the stage with the most room "
                "in it.",
        source="Clio Legal Trends Report, 2025"),
    "realization": _band(
        "Realisation — hours billed", average=88, target=92, floor=80,
        reading="What you invoice against what you recorded. Write-downs "
                "happen at the invoice, and they are far easier to prevent "
                "than to recover.",
        source="Clio Legal Trends Report, 2025"),
    "collection": _band(
        "Collection — invoices paid", average=93, target=97, floor=85,
        reading="What you bank against what you billed. The last stage, and "
                "the one clients control.",
        source="Clio Legal Trends Report, 2025"),
    "realization_lockup": _band(
        "Days of work not yet billed", average=43, target=30, floor=60,
        unit="days", direction=LOWER, scale_max=120,
        reading="Days of annual revenue sitting as work you have done and not "
                "invoiced. This is the half you control directly — it is a "
                "billing habit, not a client problem.",
        source="Clio Legal Trends Report, 2025 (median 43 days)"),
    "collection_lockup": _band(
        "Days of invoices unpaid", average=32, target=25, floor=50,
        unit="days", direction=LOWER, scale_max=120,
        reading="Days sitting as invoices nobody has paid. Median total lockup "
                "across firms is 93 days — better than three months of revenue "
                "somewhere between done and banked.",
        source="Clio Legal Trends Report, 2025 (median 32 days)"),
}


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
KEYS_FOR_VERTICAL: Dict[str, List[str]] = {
    "personal_services": ["rebooking_rate", "chair_utilization",
                          "retail_attach", "new_client_return"],
    "contractor":        ["first_time_fix", "tech_utilization",
                          "estimate_close_rate", "membership_attach"],
    "therapist":         ["client_retention", "no_show_rate",
                          "caseload_utilization", "booked_before_leaving"],
    "ministry":          ["first_time_return", "second_time_return",
                          "third_time_stay", "giving_participation"],
    "consultant":        ["utilization_now", "utilization_projected",
                          "proposal_win_rate", "retainer_renewal"],
    "coach":             ["utilization_now", "utilization_projected",
                          "proposal_win_rate", "retainer_renewal"],
    "nonprofit":         ["donor_retention", "first_time_donor_retention",
                          "recurring_share", "grants_on_time"],
    "lawyer":            ["utilization", "realization", "collection",
                          "realization_lockup"],
}


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
