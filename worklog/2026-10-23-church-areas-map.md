---
title: Church areas, step 1 — the map (server)
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "divide up the system as far as workload so each section of the system is viewed by specific people … if we create media team they would be able to get the part when it comes to media like churchsavvy … seats … treasurer oversees a section, Pastor oversees a section"; then, after the artifact "Church Areas and Keys" (7YRKpKa9g2DdFU9mm3WD8L): "lets start building this" (the Ops desk left Build to make room, Kevin''s pick)'
status: in progress
prs: [kmj-intake-server#1562]
migrations: [supabase/APPLY-2026-10-23-church-areas.sql (APPLIED LIVE 10/23 after a rollback probe)]
left_undone:
  - "The office's Areas page (solutionist-studio, the next PR): the eight areas, who works each, who reaches it through an office login, what's missing, and Place for a role or team"
  - "A Media part on ChurchSavvy's team that also opens sermons, the livestream and the media library (server PR next; sermons are written straight to the database today, so they need server routes for a volunteer)"
  - "Work given to a team lands in its area (the artifact's Wednesday): there is no team job list yet"
  - "Step 2 (keepers, the second key for giving names, approval levels for moving money in the app and outside it) and step 3 (seats by area) are not started"
decisions:
  - "The map grants nothing in this step. It reads who already reaches each area and says so, including where a login reaches further than its job: every office login reads member records, every admin sees who gave what"
  - "Eight areas: Worship & media, People & care, Giving & money, Kids & youth, Groups & classes, Messages & safety, Website & outreach, Office"
  - "A role or a Serve team is placed by the church's own pick, else by words in its title (outreach before media so 'Social media' is communications; media before people so 'Worship Pastor' is media), else by its job; a kids or teach job stays where its work is; nothing placed says so"
  - "A team leader goes where their team goes"
  - "A media role whose holder isn't on ChurchSavvy's team (matched by email) is offered with its parts filled in from the title; the office still sends the invite"
  - "Reading the map is a manager's (like the care numbers); placing is an admin's (placement will gate access in a later step); a business that isn't a church gets 404 and no church roles"
  - "Switched by CHURCH_AREAS (off | owner | on), owner until a Thursday"
related: [2026-10-20-churchsavvy-team-server.md, 2026-10-17-role-library.md, 2026-10-17-church-leaders.md]
---
Step 1 of the approved artifact "Church Areas and Keys": the map.

`church_areas.py` (new) holds the eight areas (what each holds, the team that
works it, who usually keeps it, what in it will need a keeper's yes), the
places (`guess_area`, `place_role`, `place_team`), and `build`, which reads
every area's people live from where they already are:
- ChurchSavvy's team (`worship_team`);
- Lead tab roles (`church_leader_roles` on `church_role_defs`);
- kids workers (`space_leaders`);
- group leaders (`group_members`);
- safety officers (`msg_member_officers`, `msg_safety_officers`);
- office logins and the accountant (`business_users`, `business_collaborators`).

Each area answers its people, who reaches it through an office login today,
and its gaps (a treasurer with no way into Giving but an admin login; how many
people see who gave what; every office login reading member records; a kids
worker with no background check date; a group with no leader; fewer than two
safety officers; nobody on ChurchSavvy's team). A failed read is a 503.

Routes: `GET /church/areas` (manager+), `PUT /church/areas/place` (admin).
Table `church_area_places` (server-only), exported with the business.

Checks: `test_church_areas.py` (46), with 9 sabotages caught (giving open to
every login, media matched before outreach, a failed read as empty, no switch,
a member reading, suggesting someone already on the team, a manager placing, a
church pick ignored, a team leader not following their team);
`church_areas_db.mjs` (20 checks on PGlite, in CI).
