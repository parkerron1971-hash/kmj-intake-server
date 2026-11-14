---
title: Set it up, a church's hand-ins become its real records on the platform owner's press
date: 2026-11-14
agent: Claude Code (Claude Fable 5.2)
asked: "do the not built section because that allows for it to be setup before this pastor gets it"
status: in review
prs: [kmj-intake-server#1848]
migrations: []
left_undone:
  - "The people file is not brought in from here. The church's own import (Bring in a spreadsheet) does it; a file handed in when the church is stuck is still loaded by hand. The server reads no Excel today (no openpyxl), and a wrong column guess makes hundreds of wrong people, so it wants its own preview screen."
  - "Photos and the sermons link are kept, not loaded: photos are for the website (after the first Sunday), and nothing stores a sermons channel; each message is added as a video link."
  - "A PDF logo can't be used (brand_engine takes pictures only). The step says so."
  - "A money login is never invited from here: it is an Admin over the whole church, so the church's owner invites it from Team."
  - "Not run against a real church. The first one signs up Monday the 16th; the plan is read-only, so look at it before pressing."
decisions:
  - "Plan and apply are one pass with a `do` flag, so the list shown is the list done. Apply answers what went and the plan again, after."
  - "Never twice, and never over the church: each step reads what is there first. Check-in already on, a group of that name, a colour or logo already set, a login already invited: left as they are."
  - "A time with no AM or PM is read only from 8 to 12 (morning) and 13 on. 'Wednesday, 7' is almost always the evening, and a test caught it being read as 7 AM, so 7 and below is a `cant` for a person to decide."
  - "Check-in follows one service time (one row a church), so the first Sunday service is used and the step says so. Every service still goes on the calendar, for the next four weeks, public."
  - "Children are placed by age only when they have no room and a birthday; grades are read as that many years past five. The rest is a `cant` with the count."
  - "A group's leader is added only when the name is exactly one adult on file. No one or two is said, never guessed."
  - "An office login's lane comes from church_areas.guess_area on the church's own words. Words that point nowhere are a `cant`, not a default."
  - "The invite route's insert and email became two functions (make_invite_row, send_invite_email) so Move-in sends the very same invitation. The route's own checks (step-up unlock, who may invite, the seat cap) are unchanged; set-up checks the cap and duplicates itself and writes `invited_by` as the church's owner."
  - "Safety officers: an office login that has joined, or a pastor or elder with an active role (the rule messaging_router already holds). Messaging itself is never switched on from here."
  - "Each apply leaves one line in the church's own audit log (verb move_in_setup), since the platform is writing into a tenant's account."
related: [2026-11-14-move-in-ready-for-sunday.md, 2026-11-14-move-in-change-asked-email.md]
---
The last of the three Move-in gaps on Kevin's preparation list: "What a church hands in still has to be set up by
hand." I had advised leaving it until after the first church; Kevin wanted it before the pastor arrives. From
Mission Control's Move-ins, GET /platform/move-in/{church}/setup/{item} plans it and POST does it, for the Sunday
details, the office logins, the safety officers and the look. Ready for Sunday (church_move_ready) is how to see
what it made.
