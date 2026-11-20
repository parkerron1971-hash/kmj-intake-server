---
title: The roll edits in place, adds whole families, and tidies itself (server)
date: 2026-11-20
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-20: "the ability to edited names and enter new people is off and some others things that should be on here needs to be on here", then "build and push to churches as well" on the mock (artifact 8UafD2wJsRm9cq5HhoB9h7), and "we need to include when a person doesn''t have a name that they are in a visitor or a certain list until they have a profile ... get those that are members to be recognized as members and not be lost"'
status: shipped
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Text and email preferences (the mock's toggles) are not on the page: texting opt-outs and the devotional list live elsewhere, so nothing here pretends to switch them."
  - "A merge moves the tables in church_roll_edit.MOVE plus the register; anything else stays on the hidden record (never lost, only not moved). A second phone number is kept in metadata.other_phones, which texting doesn't match on yet."
decisions:
  - "New module church_roll_edit.py, router prefix /church/roll beside church_roll's reads, the roll's own gate, CHURCH_ROLL_EDIT off|owner|on default on (every church, Kevin's word). The person's page says can_edit, so off is read-only again."
  - "Writes go as the server: a staff seat's own JWT write is swallowed by row security."
  - "Nameless = the name is only a phone number (church_roll.is_number). The roll flags them noname, This week never counts them, Chief's card asks who it is, and naming one makes a guest even when the old record said active."
  - "Member is never set automatically. confirmed = the office marked them (metadata.member_confirmed, set by the page's Member/Leader and by Add people as members), the register has a joined/transferred_in entry, they came over in an import, or they lead. Tidy up's Members to confirm lists the rest."
  - "Nothing is deleted. A merge copies what the kept record lacks, re-points the MOVE tables and the register's contact_ids/people, and keeps the other record hidden (inactive, metadata.merged_into), which the roll skips."
  - "People who may be on twice: the same name, or a shared phone/email only when the first names agree or one has no name, and never two people in one family (a family shares a phone)."
  - "GET /person/{id} takes fresh=1 after a save: the roll is cached per replica for 90 seconds."
related: [2026-11-01-church-roll.md, 2026-11-20-roll-names-and-texters.md]
---
The server half of the Members rebuild. A person's page edits in place: their name as
first, last and goes by, their status in church words, every About line, a child's
grade and allergies, and their family. Add people takes one person or a whole family.
Tidy up names the numbers that texted in, fixes names typed in small letters, splits
records that hold two people, merges people who are on twice, and lists members with
no reason on file. History tabs read notes, texts and emails.

Routes: PATCH /church/roll/person/{id}, GET /church/roll/person/{id}/history,
POST /church/roll/people, POST /church/roll/merge, GET /church/roll/tidy,
POST /church/roll/tidy/{caps,split,not-same,numbers-guests,confirm}. The roll adds
noname, confirmed and tidy counts; a person adds can_edit and edit.

Checks: `python -m pytest __tests__/test_church_roll_edit.py __tests__/test_church_roll.py
__tests__/test_church_roll_names_and_texters.py`.
