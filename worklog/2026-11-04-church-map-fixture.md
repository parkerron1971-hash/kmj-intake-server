---
title: Church leaders map, PR 1 — three test churches, today's routing pinned, the four needs, the words lint
date: 2026-11-04
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03: take the leaders flow further, for every church that subscribes ("what i don''t want is what i build works for love city but is broken and messed up for other churches"); design 4V41zJz1kEJGdeo4J9D2Ym approved'
status: in review
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "PR 2: supabase/APPLY-2026-11-04-church-map.sql, its PGlite check and backfill vectors (applied by hand before PR 3 merges)"
  - "PR 3: church_map read core and switches as role data; church_three.build writes db.map_intent into the new tables"
  - "PR 4: switches replace words (shepherding, made_for, the leaders room)"
  - "PR 5: map writes and /church/map routes; then Love City's map from Kevin's department sheet"
  - "PR 6: the person chain (scenario needs 2 and 4)"
  - "PR 7: the church's money levels and office overseers; room asks to the rooms duty (needs 1 and 3)"
  - "PR 8: areas and job guesses stop deciding; PR 9: close-out after CHURCH_MAP=on everywhere (the lint passes)"
decisions:
  - "The fixture runs with Who sees what on (CHURCH_AREAS=on), as production does; a lane's login carries that lane's areas, as an invite on a lane writes them"
  - "No map tables yet: filled=True keeps the map in db.map_intent (by role key and person id); filled=False is the empty map the preservation tests use; CHURCH_MAP follows map_on and nothing reads it"
  - "A scenario case today's code already routes right is a plain test, not a strict xfail (a strict xfail fails when it passes): need 1 at Grace and New Hope, needs 3 and 4 at Love City"
  - "New Hope's Director of Operations has one of its seven logins, so once it is the office overseer it holds Rooms by default: need 1 expects it phoned"
  - "Lint marks: PR 9 for the title regexes, the role-key queries, the stream-word tie-break and read-time _AREA_WORDS; PR 8 for job_for_title's care fallback (§4)"
related: [2026-10-17-church-leaders.md, 2026-10-27-leaders-room-departments.md, 2026-11-01-church-duties.md, 2026-11-02-exec-pastor-oversight.md]
---
Tests and the spec only; no production code. `docs/CHURCH_LEADERS_MAP.md` (the step-1 spec),
`__tests__/church_three.py` (Love City, Grace Baptist and New Hope in one fake, filled by the real
`ensure_library`, plus probes that drive each path's real entry point: the drift sweep's Mondays,
`_sweep_church`, `tell_late`, `ask_room`, the money levels), `test_church_three_today.py` (today's
outputs for all three, WRONG ones marked with the PR that changes them), `test_church_leaders_scenario.py`
(the four needs on the new routing) and `test_church_no_title_words.py` (rule a).

Before building more here: the leaders room today also seats a role another role answers to (Love
City's Intercessor leader, New Hope's Deacons). §2's `can_lead` backfill is the job list alone, so PR 4
must keep that rule or the baseline fails for Ruth and Celia.
