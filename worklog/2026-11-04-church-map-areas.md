---
title: Church leaders map, PR 8 — areas and job guesses stop deciding (stored area guesses, the department's area, guess_job)
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: shipped
prs: [kmj-intake-server#1718]
migrations: [supabase/APPLY-2026-11-04-church-map.sql (applied 2026-11-03 with PR 2; nothing new here)]
left_undone:
  - "CHURCH_MAP defaults to owner (Love City only). When it goes on, set it on BOTH Railway services (server and worker); nothing was set here"
  - "church_serving._kids_teams still reads _places and the words for Sunday teams (groups, which the places don't key): PR 9"
  - "PR 9: delete read-time _AREA_WORDS (place_role/place_team's closed path), the title regexes, the key query and the word tie-break once CHURCH_MAP is on everywhere"
decisions:
  - "Open map order: the church's pick, the active department's area (role unit or serve option), a kids/teach job, the stored guess (church_area_places by='guess'), the job's area"
  - "Guesses are stored when a role is made (create_role, ensure_library, set_type) and by any read that places something with no row; a serve option's first read is its 'new'"
  - "A team is keyed by its name, so a renamed team is a new team that gets its own guess once; a renamed role keeps its area"
  - "PUT /church/areas/place writes by='church' once migrated; putting back deletes only a pick"
  - "guess_job adds prophet|apostle|overseer -> pastoral as the last line; no match is None; job_for_title returns '' and chief_draft asks the owner to pick a job (400 -> Chief's _fail)"
  - "Separate commit: save_settings compares the effective money levels (null is the platform's) when a level changes"
  - "Separate commit, #1717 review: church_map.once() reads each church's map once per holders_of / manager_holders / duties page / room request (was once per Manager seat); a failed draft mark is logged and its 503 says to archive the empty department; a retry stays a draft until its units save"
related: [2026-11-04-church-map-fixture.md, 2026-11-04-church-map-core.md, 2026-11-04-church-map-switches.md, 2026-11-04-church-map-writes.md, 2026-11-04-church-map-chain.md, 2026-11-04-church-map-settings.md]
---
Where `church_map.opened(biz)` is a Map, words no longer place a role or a Serve team at read time.
`church_areas.places_for` reads the church's picks and its stored guesses apart, adds the area of the
active department each role or serve option hangs from, and stores Chief's guess once for anything with
no row. The areas page, a login's own view (`view_for`) and the login default areas (`_guesses`) all
read through it. Closed, or before the migration, it is today's `_places`.

`church_roles.guess_job` says None when no title or word matches. `job_for_title` returns "" instead of
"care", and `chief_draft` refuses with "Chief can’t tell what job a … does here. Pick one: …". Chief's
action already turns that into a fail, so Chief asks the owner.

Open and empty, all three churches' areas and logins equal today's. New tests are in
`test_church_map_areas.py`. The lint row for job_for_title's "care" now passes. The areas' rows stay
xfail until PR 9.
