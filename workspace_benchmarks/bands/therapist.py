"""
Therapist bands — the industry figures this vertical is measured against.

OWNED BY THE THERAPIST AGENT. No other vertical's module may edit this
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
VERTICALS = ['therapist']

# The four this vertical's desk actually renders, in order. Four is what
# the panel draws; a fifth would scroll or silently vanish.
KEYS = ['client_retention', 'no_show_rate', 'caseload_utilization', 'booked_before_leaving']

BANDS = {
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
}
