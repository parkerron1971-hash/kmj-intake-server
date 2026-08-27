"""
Salon bands — the industry figures this vertical is measured against.

OWNED BY THE SALON AGENT. No other vertical's module may edit this
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
VERTICALS = ['personal_services']

# The four this vertical's desk actually renders, in order. Four is what
# the panel draws; a fifth would scroll or silently vanish.
KEYS = ['rebooking_rate', 'chair_utilization', 'retail_attach', 'new_client_return']

BANDS = {
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
}
