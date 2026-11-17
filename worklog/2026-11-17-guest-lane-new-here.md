---
title: New here opens to the first-time guests' login (Tiara), and its Sunday slide asks Media instead of failing
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17: "can you make sure that Tiara also has the ability to make sure that things like qr code and stuff is made for guest as well."'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (NewHereRoom calls the new route)]
migrations: []
left_undone:
  - "Merge order: this backend first, then the frontend PR (the room's button calls POST /new-here/{biz}/screen)"
  - "The printed connect card and the bulletin's QR code live in Media's website area (Website & outreach) and the print pieces: not opened to the guests' lane here"
  - "Texting hours (the days and times every automatic text goes) stays the weekly text's login's (texting_hours._may_edit); the room's 'Change the days and times' link opens it read-only for Tiara"
  - "Owner and admin settings saves (the church's own texting number, the keyword) are unchanged"
  - "Media hears of a waiting New here slide only on the Announcements board (its Waiting for you count); no email or My week line was added"
decisions:
  - "The guests' lane is church_duties first_guests (People & Care's by default; whoever it's moved to). new_here._may_edit keeps sms_routing._may_announce (owner, admin, weekly_text) and adds a Manager that holds first_guests; the weekly text itself stays the Office's (the test pinning Tiara's 403 from _may_announce stays, on purpose)"
  - "A failed duties read is a 503 on the PUT and the slide, never a yes; the GET still reads, with can_edit false"
  - "The slide is made server-side (new_here.put_on_screen) from the church's word, number and /new, never the caller's words. Whoever has the plan's part (worship_team.can(roles_of, 'plan'): planner, worship leader, admin, the owner; a Manager by sunday_plan/production_schedule/churchsavvy_team) puts it straight on as before; anyone else the New here gate lets through (Tiara; Naiya, whose press was a 403 from /worship/announcements before) sends it status waiting, source typed, source_ref new_here, sent_by {ministry: 'New here', name}"
  - "Who approves: the board's decide route, the plan's part, unchanged (Media & Communications' login by sunday_plan, the owner, admins, ChurchSavvy planners). A typed waiting row emails no one on decide (tell_leader is only for a ministry's request)"
  - "One waits at a time: pressing again while one waits, or while it's on and showing, says so and adds nothing. A declined or retired one can be asked again"
  - "No migration: source stays one of typed/calendar/ministry (the table's check)"
  - "church_duties CATALOG first_guests `opens` names New here, so the duties page says it"
related: [2026-11-14-new-here-guest-texts.md, 2026-11-01-church-duties.md]
---
Before building I read both repos' `worklog/`: the New here room (BE 11-14,
FE 11-14) and the duties work; nothing had opened New here past the weekly
text.

`new_here.py`: `_may_edit` (+ `_may_edit_quietly` for the GET), the PUT's
refusal words (`NOT_YOURS`), and `POST /new-here/{business_id}/screen`
(`screen_slide`, `_asker`). `church_duties.py`: first_guests' `opens`.
`docs/CHURCH_DUTIES.md`: "New here (2026-11-17)".

Tests: `__tests__/test_sms_announcements.py` (who changes New here by the
duties, moving them, a 503) and `__tests__/test_new_here.py` (the slide on or
waiting, one at a time, the gate, no number, the screens shut, no https
address, an unread duty). 115 passed across new_here, sms_announcements,
worship_announce, church_duties and texting_hours.
