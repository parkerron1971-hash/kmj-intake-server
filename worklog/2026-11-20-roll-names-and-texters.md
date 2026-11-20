---
title: Church texters file as guests, and renamed people sort by their new name
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20: "first lets do it with members the ability to edited names and enter new people is off", then "build and push to churches as well" after the Members mock (artifact 8UafD2wJsRm9cq5HhoB9h7)'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Numbers already filed as Members stay Members until the Members page's Tidy up files them (the next PRs)."
decisions:
  - "A number nobody knows that texts a church gets status lead (Guest), via sms_service.new_texter_status, in both places a contact is made for a texter (record_inbound_sms and sms_routing._ensure_contact). Other businesses keep active. An unreadable business gets lead: a stranger is never wrongly a member or an active client."
  - "church_roll: an import's metadata first_name / last_name counts only while every word of it is still in the full name (_still_in). A rename on the Members page or by Chief changes only the name, so the stored part went stale and the person stayed filed under the old last name."
related: [2026-11-01-church-roll.md]
---
Two server fixes under the Members page rebuild. On the live roll, people texting
the church from a new number were saved under the number and filed as Members, and
people renamed after an import kept sorting by the old last name.

Checks: `python -m pytest __tests__/test_church_roll_names_and_texters.py __tests__/test_church_roll.py __tests__/test_sms_numbers_inbound.py`
(55 pass); the sms / roll / texting / inbound suites (872 pass).
