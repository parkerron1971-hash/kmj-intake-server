---
title: The Move-in room, where a new church hands in what its move needs
date: 2026-11-11
agent: Claude Code (Claude Fable 5.2)
asked: "create upload areas of the information that they need to hand into the system and I don't directly have to load it"
status: in progress
prs: [kmj-intake-server#1792]
migrations: [supabase/APPLY-2026-11-11-church-move-in.sql (not applied)]
left_undone:
  - "The office-app page and the Mission Control view are a frontend PR, not built when this was written."
  - "Nothing handed in is loaded automatically yet: services, kids rooms, groups, office logins and safety officers are read and set up by hand from the room."
  - "A church isn't told when we ask for a change; it sees the note the next time it opens the room."
  - "No ready-for-Sunday check (how many people on file can sign in)."
  - "CHURCH_MOVE_IN is unset in production (the platform's own church only). Switch on a Thursday."
decisions:
  - "Its own two tables, not businesses.settings: a room saved item by item would race every other settings write."
  - "Files go to the private business-documents bucket under the church's folder; the church never gets a link back, the platform owner gets 15-minute links."
  - "Giving has no hand-in: its state is Stripe's."
  - "The people list goes through the existing import; the file slot is only for a church that gets stuck."
related: [2026-11-10-move-request-emails-owner.md, 2026-11-06-church-import-families.md, 2026-11-06-church-turn-on-steps.md]
---
The first founding church is signing up and its first Sunday is November 22.
Until now a move was a handout and an inbox. `church_move_in.py` is the
handout's eleven items inside the church's own account: a short form, an
upload slot, or a door to where the real thing is done (Stripe for giving,
the import for people). Each one is handed in; each hand-in emails the
platform owner; `/platform/move-in` reads every church's room, with links to
the files, and marks an item checked or asks for a change.

Before building more here: the list and its words live in `ITEMS` and match
the pastor's handout, so change them together. The existing setup list on
Home (`business_track_actions`) is separate and was left alone.
