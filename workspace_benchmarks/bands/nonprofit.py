"""
Nonprofit bands — the industry figures this vertical is measured against.

OWNED BY THE NONPROFIT AGENT. No other vertical's module may edit this
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
VERTICALS = ['nonprofit']

# The four this vertical's desk actually renders, in order. Four is what
# the panel draws; a fifth would scroll or silently vanish.
KEYS = ['donor_retention', 'first_time_donor_retention', 'recurring_share', 'grants_on_time']

BANDS = {
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
}
