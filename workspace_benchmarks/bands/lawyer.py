"""
Lawyer bands — the industry figures this vertical is measured against.

OWNED BY THE LAWYER AGENT. No other vertical's module may edit this
file, and this file may not edit theirs. That isolation is the whole
reason the bands live in a package instead of one dict.

Every band is an EDITORIAL CLAIM this product asserts to a practitioner
who may act on it, so every one carries a citation. A figure that cannot
be attributed does not go in this file -- `source` is checked by
__tests__/test_workspace_benchmarks.py and an unattributed band fails
the build.

`direction` matters more than it looks: a no-show rate and a lockup
figure are better when LOW, and without the flag the panel congratulates
a practice for a 22% no-show rate because 22 is the bigger number.
"""
from workspace_benchmarks._band import HIGHER, LOWER, band as _band

# Which `businesses.type` values are measured against these bands.
VERTICALS = ['lawyer']

# The four this vertical's desk actually renders, in order. Four is what
# the panel draws; a fifth would scroll or silently vanish.
KEYS = ['utilization', 'realization', 'collection', 'realization_lockup']

BANDS = {
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
