---
title: Move-in gets "Set up texting", following the church's texting registration
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13: "add the texting step to move-in but first login into twilio i believe we are ready to start"'
status: in review
prs: [kmj-intake-server (this PR), solutionist-studio (the room and the Text hand-off)]
migrations: []
left_undone:
  - "The printed handout ('Your Church's Move to Solutionist') still lists eleven things; texting isn't on it"
  - "Registration is open for Love City only (TEXTING_REGISTRATION_OPEN = its id, set 11-13 on kmj-intake-server and kmj-intake-worker). Every other church sees the eleven until it's opened to them ('*')"
decisions:
  - "Twilio, checked in the console 11-13 with Kevin signed in: ticket #29903903 was answered 10-13 (primary profile set to 'ISV Reseller or Partner'; the approved Direct brand and campaign keep working; nothing else needed on the primary profile). It closed 10-20 only for lack of a reply"
  - "Texting is second, urgent, beside giving: both wait on someone else's review. Its state is read from texting_registrations, never written: todo / started (answers saved) / waiting (sent, 'With the phone companies') / needs (turned down, their reason as the note) / done (approved). Nothing to hand in or mark (400s), like giving (FOLLOWS = giving, texting)"
  - "Sent is the church's part done: waiting counts as in and as finished, so two weeks of review don't keep the room on Home. A later rejection still reaches the owner in the app, by push and by email (texting_registration._tell_owner)"
  - "It shows only where registration is open for the church or a registration row exists, so no church is handed a step it can't take. Room progress and the platform list's per-church total follow what shows"
  - "A registration that can't be read is status None: hidden where closed, 'Not started' where open, never done"
  - "Chief's move_in_status reads it (where it stands, who can send it) and fill_move_in refuses to type into it"
  - "Front end: the door opens Text with 'Text under your own name' already open (textHandoff.handOffToRegistration, the same wait-for-the-room pattern as 'open in Text'); the room's words and note say 'the phone companies'; allChecked counts texting's waiting as in, matching the server"
related: [2026-11-13-church-texting-registration.md, 2026-11-11-church-move-in-room.md, 2026-11-12-move-in-under-home.md]
---
`church_move_in.py`: the `texting` item, `FOLLOWS`, `_texting_live`, `_shows`,
`_settled`, `_is_finished`; `_room`, `_finished`, hand-in, mark and the
platform list follow them. `chief_move_in.py` reads and refuses as above.

Tests: `__tests__/test_church_move_in.py` +6 for texting (the walk-the-list
tests now skip FOLLOWS and use SHOWN while registration is closed), and
`__tests__/test_chief_move_in.py` +1. 328 passed across the move-in, texting,
ownership and related files.
