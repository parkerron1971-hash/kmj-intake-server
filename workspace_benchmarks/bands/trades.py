"""
Trades bands — the industry figures this vertical is measured against.

OWNED BY THE TRADES AGENT. No other vertical's module may edit this
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
VERTICALS = ['contractor']

# The four this vertical's desk actually renders, in order. Four is what
# the panel draws; a fifth would scroll or silently vanish.
KEYS = ['first_time_fix', 'tech_utilization', 'estimate_close_rate', 'membership_attach']

BANDS = {
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
}
