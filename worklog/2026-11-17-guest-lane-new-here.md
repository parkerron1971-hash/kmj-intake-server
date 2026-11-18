---
title: New here opens to the first-time guests' login (Tiara), its Sunday slide asks Media (who hear), and her Sunday has the cards
date: 2026-11-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-17: "can you make sure that Tiara also has the ability to make sure that things like qr code and stuff is made for guest as well." Then, on the two follow-ups (Media told; the Sunday cards): "I approve your ideas. make this happen"'
status: in review
prs: [kmj-intake-server#1905, solutionist-studio#1616]
migrations: []
left_undone:
  - "Merge order: this backend first, then the frontend PR (the room's button calls POST /new-here/{biz}/screen; the Sunday line's door opens New here)"
  - "The printed connect card and the bulletin's QR code live in Media's website area (Website & outreach) and the print pieces: not opened to the guests' lane here"
  - "Texting hours (the days and times every automatic text goes) stays the weekly text's login's (texting_hours._may_edit); the room's 'Change the days and times' link opens it read-only for Tiara"
  - "Owner and admin settings saves (the church's own texting number, the keyword) are unchanged"
  - "New here is OFF at Love City (settings.new_here.on unset): Tiara's Sunday line says to switch it on in Text, New here"
  - "The waiting slide's push is the only push; no email. The walk-through counts the Sunday cards line as one of her jobs"
decisions:
  - "The guests' lane is church_duties first_guests (People & Care's by default; whoever it's moved to). new_here._may_edit keeps sms_routing._may_announce (owner, admin, weekly_text) and adds a Manager that holds first_guests; the weekly text itself stays the Office's (the test pinning Tiara's 403 from _may_announce stays, on purpose)"
  - "A failed duties read is a 503 on the PUT and the slide, never a yes; the GET still reads, with can_edit false"
  - "The slide is made server-side (new_here.put_on_screen) from the church's word, number and /new, never the caller's words. Whoever has the plan's part (worship_team.can(roles_of, 'plan'): planner, worship leader, admin, the owner; a Manager by sunday_plan/production_schedule/churchsavvy_team) puts it straight on as before; anyone else the New here gate lets through (Tiara; Naiya, whose press was a 403 from /worship/announcements before) sends it status waiting, source typed, source_ref new_here, sent_by {ministry: 'New here', name, from: the lane}"
  - "Who approves: the board's decide route, the plan's part, unchanged (Media & Communications' login by sunday_plan, the owner, admins, ChurchSavvy planners). A typed waiting row emails no one on decide (tell_leader is only for a ministry's request)"
  - "One waits at a time: pressing again while one waits, or while it's on and showing, says so and adds nothing. A declined or retired one can be asked again"
  - "Media told (existing channels only): one push after the answer (FastAPI background task, push_notifications.send_to_user, nav operate:worship-announcements, as church_office_tasks pushes) to new_here.deciders: the Manager logins holding a plan-part duty and the ChurchSavvy team's planners/worship leaders/admins, else the owner (the late-task pattern); never the sender. And a My week line (kind screen, kicker 'Before Sunday') while it waits, for every login new_here.decides (owner and admins too: they can put it on). Words: 'A guest slide from People & Care is waiting for you to put on Sunday's screen.' (Office & Leadership when the weekly text's login sent it)"
  - "Tiara's Sunday: not a new duty and not a second day on first_guests (the catalog's day drives due dates and church_work_checks' judging); a line church_my_week.rhythm adds to Sunday for whoever holds first_guests (SUNDAY_CARDS): never judged done, never movable, not in the count, door Text opened on New here (DOOR['new_here'] with view new-here; the app's textHandoff). Only where the NEW_HERE switch is open for the church; while New here is off there, it says to switch it on first"
  - "No migration: source stays one of typed/calendar/ministry (the table's check)"
  - "church_duties CATALOG first_guests `opens` names New here, so the duties page says it"
related: [2026-11-14-new-here-guest-texts.md, 2026-11-01-church-duties.md, 2026-11-01-office-gates-duties.md]
---
Before building I read both repos' `worklog/`: the New here room (BE 11-14,
FE 11-14) and the duties work; nothing had opened New here past the weekly
text.

`new_here.py`: `_may_edit` (+ `_may_edit_quietly` for the GET), the PUT's
refusal words (`NOT_YOURS`), `POST /new-here/{business_id}/screen`
(`screen_slide`, `_asker`, `_from_lane`), who hears (`decides`, `deciders`,
`tell_deciders`, `waiting_line`, `week_item`) and `sunday_cards`.
`church_my_week.py`: the `screen` need, `DOOR["new_here"]`, `SUNDAY_CARDS` in
the rhythm. `church_duties.py`: first_guests' `opens`. `docs/CHURCH_DUTIES.md`:
"New here (2026-11-17)".

Tests: `__tests__/test_sms_announcements.py` (who changes New here by the
duties, moving them, a 503; who decides and hears, the push, the My week
line), `__tests__/test_new_here.py` (the slide on or waiting, one at a time,
told once, the gate, no number, the screens shut, no https address, an unread
duty) and `__tests__/test_church_week_rhythm.py` (the Sunday cards line).
