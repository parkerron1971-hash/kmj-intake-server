---
title: "Church Savvy: one Sunday hub, the backend (M-7 step 1): switch, Sunday roles, walls, summary, live changes, leaders, ministry ops, stream, announcements"
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin said GO on mission M-7 "Church Savvy: one Sunday hub" (through KAI, 2026-11-27): build the backend from the final review kai/reviews/church-savvy-sunday-structure.md, small PRs with tests, one APPLY file, the API contract first; push, wait for green, do not merge'
status: waiting on Kevin
prs: [kmj-intake-server#2111, kmj-intake-server#2113, kmj-intake-server#2114, kmj-intake-server#2115, kmj-intake-server#2116, kmj-intake-server#2117]
migrations: [supabase/APPLY-2026-11-27-sunday-hub.sql (not applied)]
left_undone:
  - "Merge order: #2111 (part 1) first. #2113-#2117 are drafts carrying part 1's commits (CI runs only on PRs to main; PRs are never stacked); once #2111 is on main, merge main into each and mark it ready. Checked: the five cherry-pick onto part 1 with no conflict, in any order"
  - "Kevin applies supabase/APPLY-2026-11-27-sunday-hub.sql before the launch (the live-changes PR reads its columns only with the hub on)"
  - "The launch: SUNDAY_HUB=on on both Railway services (kmj-intake-server and kmj-intake-worker), every church at once, after the frontend (M-7 step 2) is in; off is the safety switch"
  - "Day-one list read from production (read-only, scripts/sunday_hub_day_one.py): nobody loses the Sunday pages at launch; the full list with names is kai/reviews/M-7-day-one-roles.md, never the repo"
  - "Not done (optional, not needed for launch): tying a stream to its Sunday (stream_sessions.worship_service_id). The News feed's own list doesn't show a post's screens pairing; the board's list and both create answers do"
  - "chief_serving_spots calls Planning's routes as the login, so the new walls apply to Chief too (a team leader's Chief can now ask on their own team in the office); no Chief code changed"
decisions:
  - "One launch: everything merges dark (SUNDAY_HUB off answers byte-for-byte as before; /worship/status gains no key); on turns the hub, the roles and every wall on for every church at once; after that the switch is only a safety off"
  - "Roles come from what a church already gives out, never titles: owner/Admin seat -> every role (pastor); Planner or ChurchSavvy Admin part (or sunday_plan, production_schedule, churchsavvy_team) -> planner; the Worship part -> leader of the church's worship team (planner where it has none); leading a Sunday team's group -> team leader; Booth/Media part or the stream duty -> media & tech; ministry_ops -> ministry operations. A reader holds a role, a Sunday duty or a team part"
  - "ministry_ops is a new duty in the Sunday & Serving lane, so the lane's logins hold it from day one; it gives the Scheduler part; the whole Ministry operations role is the lane's nine duties given together. It fills worship and production only on a team opened to it (serve_teams.open_to_ops), by the owner, an Admin or that team's own leader, and that team's leaders are told"
  - "The wall sits in worship_team.roles_of (403 'Sunday plans open to the church's Sunday roles.'); only a login with no part is asked; the status routes and New here's screen card pass wall=False"
  - "Plan writes with the hub on: pastor/planner the whole plan; media & tech only on a Sunday the pastor opened (to the end of that day on the church's clock); a team leader only their own team's items, never the order, title, time, notes or an item's team; the booth's typo fix stays open every Sunday"
  - "The offering in the summary only through giving_services._gate (Giving > by service's own gate): the key is absent, never null, without it"
  - "Stream settings: a manager seat as before, plus the team's live part with the hub on (live-media desk's file; one gate)"
  - "Announcements: each side by its own create route and its own permission; asking twice never makes two; editing one never changes the other by itself"
  - "POST /planning/sundays was listed as a door fix. Reading it: it adds blank Sunday placeholders, and the Volunteers board's 'Add the next five Sundays' button relies on it, so limiting it to ChurchSavvy's door would strand the volunteer coordinator. Kept as is (whoever schedules either door), pinned by a test"
  - "'This Sunday' or 'Next service': worked out from when the church's plans fall on its own clock (half or more on a Sunday reads as Sunday), or the church's own choice (worship_settings.service_word)"
related: [2026-11-27-chief-fills-a-serving-spot.md, 2026-10-23-sunday-planning-teams.md, 2026-11-02-volunteers-door.md]
---
The backend for Church Savvy's one Sunday hub (Kevin's decisions church-office-1, 2026-11-27), in six PRs: #2111
the switch, roles and migration; #2113 the read wall and the Sunday's summary; #2114 live changes and who changes
which part of the plan; #2115 team leaders in the office and ministry operations; #2116 the stream for media & tech;
#2117 announcements once, two places. The API contract the frontend builds against is in #2111's description and in
kai/reviews/M-7-api-contract.md.
