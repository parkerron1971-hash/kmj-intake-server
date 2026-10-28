"""The growth report in a church's or a nonprofit's words (2026-10-16).

A gift is stored as a paid invoice, so the growth report measures a
church's giving with a shop's arithmetic. The arithmetic is right; its
labels were not: Chief read "First-time buyers", "Purchase value" and
"paid invoices" back to a pastor about the offering.

`re_say` relabels one finished report for its business's voice: the
driver labels, the repeat-rate definition and the coverage warnings, and
adds a vocabulary note for the field names, which stay shared. The
numbers are untouched. Every driver also gets a stable `key`, in every
voice, so nothing has to match on wording. The business voice is
otherwise returned exactly as the report built it.

Mirror of the frontend's src/core/components/growth/growthWords.ts: the
driver labels here are the ones the page shows.
"""
from __future__ import annotations

import vertical_family
import vertical_registry

DRIVER_KEYS = {
    "First-time buyers": "first_time",
    "Returning buyers": "returning",
    "Purchase frequency": "frequency",
    "Purchase value": "average",
    "Unlinked invoices": "unlinked",
}

# None drops a warning that has no meaning for gifts (capacity is not shown).
WARNINGS = {
    "Collections use paid invoice totals; partial payments and refunds need reconciliation in Revenue.":
        "Each gift counts at its full amount; refunds show in the giving ledger.",
    "Capacity combines Sessions and dated booking-calendar records, deduplicating mirrored online bookings.": None,
    "Costs are analytical allocations, not additional bookkeeping entries. Contributions use recorded direct costs only.":
        "Costs recorded here are for this report only; they are not entries in the books.",
}


def voice_of(business_type: str | None) -> str:
    """'church', 'nonprofit' or 'business'. The registry's aliases (a
    "pastor" is a ministry) and the accounting family (a "congregation"
    is nonprofit-like) both count, so nothing that reads as giving falls
    through to the business voice."""
    key = vertical_registry.resolve(business_type or "")
    if key == "ministry":
        return "church"
    if key == "nonprofit" or vertical_family.is_nonprofit_like(business_type):
        return "nonprofit"
    return "business"


def giving_is_private(business_type: str | None) -> bool:
    """The one test for both the words and the finance gate: whatever this
    report calls giving is read per person by finance roles only."""
    return voice_of(business_type) != "business"


def re_say(report: dict, voice: str) -> dict:
    """The same report, labelled for its voice."""
    for d in report.get("drivers", []):
        d.setdefault("key", DRIVER_KEYS.get(d.get("label"), d.get("label")))
    if voice == "business":
        return report
    givers = "givers" if voice == "church" else "donors"
    labels = {
        "first_time": f"New {givers}", "returning": f"Returning {givers}",
        "frequency": "How often they give", "average": "Average gift", "unlinked": "Anonymous gifts",
    }
    for d in report.get("drivers", []):
        d["label"] = labels.get(d["key"], d["label"])
    health = report.get("retention_health")
    if isinstance(health, dict) and isinstance(health.get("definitions"), dict):
        health["definitions"] = {**health["definitions"], "repeat_rate": (
            f"All-time share of {givers} with at least two dated gifts in the reporting currency. "
            "This is not the 30/60/90-day cohort rate.")}
    quality = report.get("quality")
    if isinstance(quality, dict) and isinstance(quality.get("warnings"), list):
        quality["warnings"] = [said for said in (WARNINGS.get(t, t) for t in quality["warnings"]) if said]
    report["voice"] = voice
    report["vocabulary"] = (
        f"Gifts are stored as paid invoices, so the field names are shared: collected means given, invoices means "
        f"gifts, buyers means {givers}, revenue means giving. Speak of gifts and {givers}; never buyers, customers, "
        f"invoices, sales or revenue.")
    return report
