"""
Consultant bands — the industry figures this vertical is measured against.

OWNED BY THE CONSULTANT AGENT. No other vertical's module may edit this
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
VERTICALS = ['consultant', 'coach']

# The four this vertical's desk actually renders, in order. Four is what
# the panel draws; a fifth would scroll or silently vanish.
KEYS = ['utilization_now', 'utilization_projected', 'proposal_win_rate', 'retainer_renewal']

BANDS = {
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
}
