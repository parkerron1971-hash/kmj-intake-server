---
title: Church areas, step 2 — keepers and keys (server; nothing locked yet)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "if Pastor look at money another leader is notified and have to recieve a code from that person to get into money"; 2026-10-26: "go with your picks" (the lock binds the owner too; a tap with a code as the backup; a yes opens an hour) and "go ahead, you build step 2 after the media fixes"'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: ["supabase/APPLY-2026-10-27-church-keys.sql (APPLIED LIVE 10/27 after a rollback rehearsal)"]
left_undone:
  - "The doors (next server PR): who gave what, the bank and payouts (giving records, statements, Chief's giving actions, the donor report and export, Stripe charges, customers and payouts, the bank feed); kids' medical and custody notes; pastors-only notes and prayer"
  - "Asking from an accountant's collaborator login: the routes take an owner or an office login, and an accountant collaborator has neither"
  - "The app: naming keepers on the Areas page, Ask for a key, a keeper's yes or no, entering the code"
  - "The database lock on the giving rows the app reads directly (invoices gift rows through ministry_finance_access)"
  - "Approval levels for money the system sends (contractor payments) and for money paid outside it"
decisions:
  - "Guarded areas: Giving & money, Kids & youth and People & care, each only in its guarded part (church_areas.AREAS guarded); totals stay open"
  - "An area with no keeper has no lock: naming the first keeper turns it on, so no church is locked out by surprise"
  - "The lock binds the owner too. Nobody answers their own ask, even after becoming a keeper"
  - "Every keeper hears an ask by phone alert and email, with a 6-digit code to read out; a tap or the code opens it for 60 minutes; an ask with no answer lapses after 24 hours; five wrong codes close the ask; asking again rings nobody twice"
  - "A keeper change by someone who isn't a keeper waits 7 days, told to the keepers, unless a keeper says yes (now) or no (cancelled); the first keeper of an area and a keeper's own change count at once"
  - "A failed read is a 503, never an open area"
  - "Switch CHURCH_KEYS (off | owner | on, owner until a Thursday): off takes every lock away; owner shows the routes only to the platform owner, while a church with keepers stays locked either way"
related: [2026-10-23-church-areas-map.md]
---
- `church_keys.py` (new): the keepers, the asks, the wall (`is_open` / `wall` for the doors), and six routes under `/church`.
- `supabase/APPLY-2026-10-27-church-keys.sql` (new): `church_keepers` and `church_area_keys`, both server-only.
- `account_lifecycle.py`: both tables in `EXPORT_EXCLUDED`. They hold sign-in ids, and a restored church names its keepers again.
- `kmj_intake_automation.py`: mounts the router after the areas router.
- `.github/workflows/ci.yml`: adds `church_keys_db.mjs`.
- `docs/MIGRATIONS.md`: a ledger row.

Checks:
- `__tests__/test_church_keys.py`: 15 tests.
- I broke each rule on purpose, and the tests caught all nine:
  - the owner walking in;
  - an asker answering their own ask;
  - silence opening the area;
  - a self-made keeper counting at once;
  - a failed read opening the area;
  - endless code tries;
  - a key that never closes;
  - a non-keeper answering;
  - a pending keeper counting.
- `__tests__/church_keys_db.mjs`: 24 checks on PGlite.
- Export/import, the access ratchet, areas, login areas, route type hints and seat access all pass.
