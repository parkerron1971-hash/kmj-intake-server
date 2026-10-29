---
title: Sunday check-in — members count themselves and their family from their phones; the Kids kiosk counts the parent
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, after the research on how churches take attendance: "yes. i like plan. i think the app checkin and online checkin for online view are all good. kiosk is for children." Step 1 of shepherding (canvas 31su6kdYmYecH5b2NxjBJN, boards 10 and 11), so Love City can start counting Sundays'
status: shipped
prs: [kmj-intake-server#1481, solutionist-studio#1253]
migrations: [supabase/APPLY-2026-10-17-sunday-checkin.sql]
left_undone:
  - "Drifting, shepherds, families and the weekly sweep that reads these Sundays are shepherding's next steps (canvas boards 1-9); this only records who came"
  - "Check-in is off until the office turns it on (Operate, Attendance, Sunday check-in); Love City's service is Sundays at 11:00 on the church's clock"
  - "A shepherd's \"they were there\" for someone who forgot to scan comes with the shepherd's Lead tab"
decisions:
  - "Adults never use a kiosk (Kevin): the code on the welcome slide opens the church's /here, which is the member's own page; signed out, the usual passwordless sign-in lands on Home, where the same card waits while check-in is open"
  - "One card, two answers: At church (method self) or Watching online (online); the member ticks who of their family came. Their family is them and the other adults of their household in Families; just them without one. Never anyone else"
  - "Unticking someone, or changing At church to Online, changes only what a member's phone wrote; a check-in at the door, by a station or the kiosk's parent stays as it is"
  - "The window is the church's own clock: it opens 30 minutes before the service and closes 3 hours after (both settable); after it closes the card is next week's"
  - "Each service gets a dated occasion in Services & Events, made once (a unique index on the day), private to the church so a weekly row never crowds the public events page, and named after the church's own undated service (Love City: Sunday Worship). A service the church already dated that day is used instead. An hourly sweep makes it two days ahead so the Kids kiosk and Attendance find it Sunday morning"
  - "The Kids self kiosk counts the parent it found by mobile number (kids_parent), once; a failure there never fails the children's check-in"
  - "Settings are server-only (service role), read by any seat that reads attendance, changed by a manager or above"
related: [2026-10-17-role-library.md]
---
The shepherding design needs Sundays: "missed three Sundays" has nothing to
read at Love City, which had no attendance recorded in the app. Kevin chose
how it's counted after the research (pew pads, Planning Center's app
check-in, Subsplash's kiosks, the three-week absence alert, and the face
recognition to avoid): members check in from their phones, online viewers
with "I'm here", and the kiosk stays for children.

- **`church_checkin.py`**: the settings (defaults until saved: off, Sunday
  11:00 on the church's clock, 30 minutes before to 3 hours after), the
  window, the occasion (find or make once), the member's family, the card's
  state (off / closed / open / error, never "off" on a failed read), the
  write (idempotent, only the member's own rows change), the kiosk's parent,
  the office's counts by method and the overview, and the hourly sweep.
- **`member_portal_checkin.py`**: the card (At church / Watching online, the
  family ticked, Check in; then "Welcome home." with Change it), /my/here
  (open, closed with when it opens, off), and POST /my/here. The owner's
  preview never writes; a closed window refuses.
- **`member_portal.py`**: /my/here, and the card at the top of Home while
  check-in is open (church space only; a failure leaves Home as it was).
- **`public_site.py`**: the church's /here opens /my/here.
- **`kids_station.py`**: the self kiosk counts the parent.
- **`church_router.py`**: GET and PUT /church/checkin for Attendance's panel.
- **`kmj_intake_automation.py`**: the member route and the hourly sweep.
- **`account_lifecycle.py`**: the settings go and come back with the church.
- Tests: `__tests__/test_church_checkin.py` (20), two kiosk tests in
  `test_kids_station.py`, `__tests__/sunday_checkin_db.mjs` on PGlite.
