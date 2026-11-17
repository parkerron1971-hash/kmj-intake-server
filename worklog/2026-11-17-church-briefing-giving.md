---
title: Giving for a church's briefing week, for the people who may see giving
date: 2026-11-17
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-17: "yes to the other plans as well" (giving was left out of the church briefing because office logins that never see giving can open that page)'
status: in review
prs: []
migrations: []
left_undone:
  - "The letter's own words still do not mention giving: that would need a second model call or a letter per reader."
  - "A Giving & money area login without an Admin seat does not get the card: that is today's rule everywhere for gift rows (ministry_finance_access)."
  - "A gift refunded in full is not counted as a gift (the Reports rule), so a gift count on the Giving page can differ by those. The total matches."
decisions:
  - "Giving is never in the letter, its prompt or its stored record: the page reads letters straight from the insights table, which office logins can read."
  - "GET /giving/{business_id}/week is worked out when the page asks and never stored. Gate: require_user, then giving_records.require_finance (owner, active Admin seat, outside accountant), the same rule as the amounts endpoint. Counts and totals only, never a giver."
  - "The week is seven church days ending on the letter's day, and the seven before, on the church's own clock."
related: [2026-11-17-church-weekly-briefing.md]
---
`giving_week.py` (new) reads gifts with `giving_records.read_gifts`, the read
the Giving page's amounts use, and returns the week's total, the gift and
giver counts, the week before, and the week by fund. `giving_router.py` adds
the endpoint. `__tests__/test_giving_week.py`: 15 tests, one checking the
total against the amounts endpoint for the same days, and the gate for an
owner, an admin, an accountant, a member seat and a stranger.

The card on the Briefing page is solutionist-studio's.
