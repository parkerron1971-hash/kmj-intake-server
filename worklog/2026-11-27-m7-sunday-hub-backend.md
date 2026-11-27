---
title: "Church Savvy: one Sunday hub, the backend (M-7 step 1): switch, Sunday roles, walls, summary"
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin said GO on mission M-7 "Church Savvy: one Sunday hub" (through KAI, 2026-11-27): build the backend from the final review kai/reviews/church-savvy-sunday-structure.md, small PRs with tests, one APPLY file, the API contract first; push, wait for green, do not merge'
status: in progress
prs: [kmj-intake-server (this PR, part 1 of the backend)]
migrations: [supabase/APPLY-2026-11-27-sunday-hub.sql (not applied)]
left_undone:
  - "Part 1 is this PR: SUNDAY_HUB (off|owner|on, default off), sunday_hub.standing (the day-one roles), /worship/status's sunday block, PUT /worship/service-word, the ministry_ops duty, the one migration and its PGlite check, scripts/sunday_hub_day_one.py, the API contract"
  - "Next PRs (each needs this one merged first: CI runs only on PRs to main, and PRs are never stacked): the read wall and GET /worship/services/{id}/sunday (offering through giving_services' gate); the live-changes mark with the plan-write scope (media & tech on an opened Sunday, team leaders their own items, the typo fix every Sunday); team leaders in the office and ministry operations with open_to_ops; stream settings for the Media part (live-media desk); announcements once, two places"
  - "Kevin applies the migration before the launch; the day-one list (scripts/sunday_hub_day_one.py) is read before SUNDAY_HUB goes on"
decisions:
  - "One launch: everything merges dark (SUNDAY_HUB off answers byte-for-byte as before; /worship/status gains no key); on turns the hub, the roles and every wall on for every church at once; after that the switch is only a safety off"
  - "Roles come from what a church already gives out, never titles: owner/Admin seat -> every role (pastor); Planner or ChurchSavvy Admin part (or sunday_plan, production_schedule, churchsavvy_team) -> planner; the Worship part -> leader of the church's worship team (planner where it has none); leading a Sunday team's group -> team leader; Booth/Media part or the stream duty -> media & tech; ministry_ops -> ministry operations. A reader holds a role, a Sunday duty or a team part"
  - "ministry_ops is a new duty in the Sunday & Serving lane, so the lane's logins hold it from day one; the whole Ministry operations role is the lane's nine duties given together"
  - "POST /planning/sundays was listed as a door fix. Reading it: it adds blank Sunday placeholders, and the Volunteers board's 'Add the next five Sundays' button relies on it, so limiting it to ChurchSavvy's door would strand the volunteer coordinator. Kept as is (whoever schedules either door), pinned by a test"
  - "'This Sunday' or 'Next service': worked out from when the church's plans fall on its own clock (half or more on a Sunday reads as Sunday), or the church's own choice (worship_settings.service_word)"
related: [2026-11-27-chief-fills-a-serving-spot.md, 2026-10-23-sunday-planning-teams.md, 2026-11-02-volunteers-door.md]
---
The backend for Church Savvy's one Sunday hub (Kevin's decisions church-office-1, 2026-11-27). This file is updated
as each part lands. The API contract the frontend builds against is in this PR's description and in
kai/reviews/M-7-api-contract.md.
