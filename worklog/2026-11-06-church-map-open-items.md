---
title: Leaders map open items - Love City's admins move duties, one Undo for an ask's change, ten a day held by the database
date: 2026-11-06
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin: close #1761's open items: Love City's admin can't move a duty (duties page, Chief, a From your team suggestion); an answered ask's change has two Undos that disagree; the ten-a-day cap can be passed by two saves at once"
status: in progress
prs: [kmj-intake-server#1762]
migrations: [supabase/APPLY-2026-11-06-church-map-asks-cap.sql (not yet applied)]
left_undone:
  - "Kevin applies supabase/APPLY-2026-11-06-church-map-asks-cap.sql by hand after the PR merges (verify query in docs/MIGRATIONS.md); until then the code's check-before and recount-after hold the cap as before"
  - "Frontend (solutionist-studio): Recent changes can say “From Tiara's suggestion” from `ask.who` and, where `ask.duty` is set, that Undo puts back the duty move too; read the change undo's `both`/`note`; nothing else changes shape (`cant_apply` words changed, the field didn't)"
  - "No What's New: the map and the duties are still `owner` (Love City only)"
decisions:
  - "church_duties.office_open(user, biz) = open_to(user) or church_open(biz), the map's pattern: the duties routes, Chief's duty verbs (chief_duties._duties_open), both asks' _gates and so _can_undo / _undo_checks follow it; seats unchanged (owner or admin moves, money only to a money login, nobody answers their own); other churches stay closed, their own owners too"
  - "DUTY_CLOSED and MAP_CLOSED say the switch is off at this church (it is, for everyone there), not that this login can't"
  - "One Undo: only a change that saying yes to an ask made together with a duty move (_both: the ask's change by whoever said yes, and the duty change the yes made) is the ask's; POST /church/map/changes/{id}/undo and Chief's undo_map_change run the ask's undo then (undo_answer / undo_ask), both or neither, and Recent changes' can_undo is the ask's own. An ask with no duty part: the change's own undo is the same thing. A duty moved again since: neither Undo is offered (the map change is changed directly)"
  - "undo_ask calls the map change's own undo (chief_map._undo_alone), never the ask-aware undo_map_change, so it can't recurse"
  - "The cap's trigger raises SQLSTATE PT429 (PostgREST answers 429) with a message starting church_map_asks_cap; sb_clients keeps each sync call's PostgREST refusal per thread (last_error) and church_map_asks._insert answers it with the cap's own words; the helpers still return None"
  - "The trigger counts with now() (not the row's asked_at) under pg_advisory_xact_lock(hashtextextended('church_map_asks_cap:<business>:<login>')), security invoker, empty search_path, volatile so the count after the lock sees the save it waited for"
related: [2026-11-06-church-map-fixes.md, 2026-11-05-church-is-this-right.md, 2026-11-02-chief-duties.md, solutionist-studio 2026-11-06-church-map-fixes-fe.md]
---
Three of #1761's open items, in church_duties.py, chief_duties.py, church_map_asks.py, church_map_router.py,
church_map_batch.py, chief_map.py and sb_clients.py, with the migration and its PGlite check. The new response
fields are in the PR body and docs/CHURCH_LEADERS_STEP2.md §10 ("Fixed 2026-11-06, round two"). Before building
more here: check the migration is applied (docs/MIGRATIONS.md) before relying on the database's cap.
