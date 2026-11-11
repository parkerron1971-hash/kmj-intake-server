---
title: The week's birthdays, read alone (for the pastor's band on a church's Home)
date: 2026-11-11
agent: Claude Code (Claude Fable 5.2)
asked: "make the fix" (to: the pastor's band said no birthdays this week while People showed two)
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone: ["Anniversaries on Home still come from the church news' celebrations (both spouses said yes): the roll holds no wedding dates", "The read returns at most 60 names; `n` is the whole count"]
decisions: ["One rule, the roll's: today and the six days after on the church's clock, nobody inactive, a child's day from its child record when its own record has none. A test holds the light read to the roll's own count", "Read from the people with a birthdate and the children's records, not the whole roll (the roll reads Sundays, groups, teams, the register and guests too)", "The roll's gate, unchanged: the switch, a church, a staff seat, the areas", "A child is marked (`minor`), so Home names the birthday and offers no note to draft", "A failed read is a 503, never 'no birthdays'"]
related: [2026-11-01-church-roll.md]
---
The pastor's band on a church's Home (solutionist-studio #1515) read birthdays from
`GET /church/news/celebrations`, which holds only members who said the church may celebrate
them. Seen live on Love City: People said two birthdays this week, the band said none
(#1516 stopped the false claim and pointed to People).

`GET /church/roll/birthdays?business_id=` (church_roll.birthdays) answers
`{today, from, to, n, people: [{id, name, day, minor}]}`, soonest first.

Checks: `python -m pytest __tests__/test_church_roll.py` (20 pass): the same four people as
the roll read whole, an inactive person left out, a child's day from the child record,
a week across the new year, a failed read, and the gate on the new route.
