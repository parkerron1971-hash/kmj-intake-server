"""
Ministry bands — the industry figures this vertical is measured against.

OWNED BY THE MINISTRY AGENT. No other vertical's module may edit this
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
VERTICALS = ['ministry']

# The four this vertical's desk actually renders, in order. Four is what
# the panel draws; a fifth would scroll or silently vanish.
KEYS = ['first_time_return', 'second_time_return', 'third_time_stay', 'giving_participation']

BANDS = {
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
}
