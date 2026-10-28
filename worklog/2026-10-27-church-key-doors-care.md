---
title: Church areas, step 2 — the Kids and Care doors (medical and custody notes, the care inbox and pastors-only notes need the keeper's key)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-26: "go with your picks" (the lock binds the owner too; guarded at the start: giving names and bank, kids medical notes, pastors-only notes) and "go ahead, you build step 2 after the media fixes"'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "Check-in and pickup still show a manager a child's custody note (see decisions)"
  - "Help requests marked pastors only (church_help, a peer's module) still follow its own boss rule, not the People & care keeper"
  - "Chief's reads aren't behind the Kids and Care locks yet"
  - "The app: until Ask for a key lands, the families page shows only that a child has private notes (it already does that for members), and the board leaves out the pastors-only notes"
related: [2026-10-27-church-keys.md, 2026-10-27-church-key-doors-giving.md]
---
Decisions:
- **Kids, once the church names a Kids & youth keeper.**
  - A manager or the owner sees that a child has medical or custody notes, never what they say. That's what a member already sees. The keeper, and a key for its hour, read them.
  - Allergies stay open to the whole team.
- **Kids writes.**
  - Changing an existing medical or custody note needs the key, so nobody writes over a note they can't read.
  - A new child's first notes are still written by whoever registers them, so the welcome desk can record a child's condition on a Sunday.
- **Check-in and pickup are unchanged.** A manager releasing a child reads the custody note at that moment, because a safe release depends on it, and a lock at the pickup desk would only slow one down.
- **Care's inbox.** The owner sees every request until the church names a People & care keeper. From then on the keeper sees every request (and can hand one to a teammate), and so does anyone holding their key. Everyone else sees what was handed to them, the owner included.
- **The Follow-up board.** Where the church named a keeper, anyone else's board leaves out pastors-only notes and says how many there are on each card (`pastors_notes_locked`). Writing one stays open.
- **Failed reads.** A failed read of the keepers is a 503, never an open door.

Changes:
- `church_keys.py`: `opened()` says whether an area is kept at all, for a door whose rule changes once it is (Care's inbox). `is_open` is built on it.
- `kids_router.py`: the families list and the child edit.
- `private_care.care_access`: who sees every request.
- `church_router.py`: `/church/follow-ups`.
- Two strict test fakes learn the keepers table: `test_kids_router.py` and `test_website_forms.py`.

Checks:
- `__tests__/test_church_key_doors_care.py`: 10 tests.
- I removed each lock on purpose, and the tests caught all 10.
- The 59 suites that touch these modules pass (1,277 tests), including the access ratchet, kids, check-in, care, My week and the forms.
