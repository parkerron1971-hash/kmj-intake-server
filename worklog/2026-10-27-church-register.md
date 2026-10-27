---
title: The church register — baptisms, dedications, weddings, funerals and membership, with certificates (server)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Church Office Prototypes (https://claude.ai/artifact/2vGqaUZUynRuiFVKuQEZWo), the "Church register" tab → Kevin, 2026-10-27: "lets go with your list" (the register fourth; "make sure that the design is top tier")'
status: shipped, switched off (platform owner only until a Thursday); migration waiting on Kevin
prs: [kmj-intake-server (this PR), solutionist-studio (the page, its own PR)]
migrations: ["supabase/APPLY-2026-10-27-church-register.sql (NOT APPLIED: Kevin applies by hand)"]
left_undone:
  - "Apply supabase/APPLY-2026-10-27-church-register.sql. Until then /church/register/status says enabled false and the other routes answer 503"
  - "Switch-on: CHURCH_REGISTER=on on Railway on a Thursday (it defaults to owner), with the app's What's New entry"
  - "No member view: a member doesn't see their own milestones in the app yet (v1's member side is the existing 'Plan a life event' ask)"
  - "Chief can't read or add register entries (no action handler); the year's numbers aren't in the reports pack (not built)"
  - "The import offer reads contacts.metadata.imported via PostgREST's json path (imported:metadata->imported, metadata->>imported_from); checked on the fake and the shapes member_directory already uses, not against production"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "Who: the owner, admins and logins whose areas include People & care see everything; an Office login sees the register without funerals or membership removals (not even their counts: null) and can't add or turn an entry into one; asks are People & care's (they come from Prayer & care, which is confidential). While Who sees what is off, every login sees the whole church, as before. A viewer reads; member-level and up write; only the owner and admins remove"
  - "Removing marks removed_at/removed_by: the entry leaves the page and the numbers and stays on file (a register is kept for good)"
  - "People are kept as the day recorded them ([{role, contact_id, name}]); contact_ids beside them for a person's page. A later rename on Members doesn't rewrite the register or a certificate; a person who leaves the list keeps their name on old entries"
  - "Asks: a life-event ask (ministry_care_requests, submission.kind 'life_event', member_asks.py's contract) waits on the page until the office marks it planned (a date) or records it; then it is one entry (care_request_id unique, on_conflict ignore-duplicates) and its Prayer & care row moves: reviewed once planned, closed once it happened (a planned entry recorded later closes it). Reading writes nothing; a closed ask or a youth's ask (for anyone but the owner and admins) writes nothing"
  - "Existing baptism dates: a one-time import the office presses, not a read-through. GET /church/register/import offers the people with metadata.imported['Baptism date'] (Subsplash) and no baptism in the register; POST adds them as baptism entries once each (import_key unique per church), all at once or one person from their page. A removed import entry is never offered again; a baptism recorded by hand covers the person. Chosen over a read-through so the register is a real record (editable, with certificates) and a removed one stays removed"
  - "Certificates: baptisms, dedications and weddings that happened. GET …/certificate returns the entry's own words (people as recorded, the day, officiant, place) and the church's name, brand-kit colours and logo; never notes, never anyone's record (it reads no contact)"
related: [2026-10-27-church-help.md, 2026-10-23-church-areas-map.md, 2026-10-27-member-asks.md]
---
- `church_register.py` (new): the switch (`CHURCH_REGISTER` off | owner | on,
  owner by default, like `church_keys.py`), who sees what, the year's numbers,
  entries, asks, the import and the certificate, and ten routes under
  `/church/register` (the module docstring lists them). `/church/register/status`
  answers `{enabled, view, write, remove, asks}` and is quietly false for a
  closed switch, a business that isn't a church, a login outside People & care
  and the Office, or the table not made yet.
- `supabase/APPLY-2026-10-27-church-register.sql` (new, NOT applied):
  `church_register_entries`, server-only; a trigger keeps an entry's people and
  its ask its own church's (`create or replace trigger`, no drop statements).
  Ledger row in `docs/MIGRATIONS.md`.
- `account_lifecycle.py`: exported (before Prayer & care and contacts), skipped
  on import (it cites people and asks by id).
- `kmj_intake_automation.py`: mounts the router after Help requests.
- `.github/workflows/ci.yml`: adds `church_register_db.mjs`. `.env.example`: `CHURCH_REGISTER`.

Checks:
- `__tests__/test_church_register.py`: 23 tests (the switch and the missing
  table, what each login may do, funerals and removals by area, another church
  unreachable, an ask becoming one entry and its Prayer & care row moving, an
  ask nobody can act on writing nothing, the import offered and pressed once,
  a removed import not offered again, a hand-recorded baptism covering the
  person, Subsplash's date shapes, an entry's checks, removing, the year's
  numbers, a person who left the list, the certificate's words).
  Ten rules broken on purpose: nine caught by the tests; the tenth (an ask
  answered twice) is held by the unique constraint too.
- `__tests__/church_register_db.mjs`: 37 checks on PGlite.
- Export/import, the access ratchet, route type hints, seat access and step-up
  routes pass.
