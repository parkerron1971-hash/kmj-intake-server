---
title: Church areas, step 1 — a Media part on ChurchSavvy's team opens the livestream, video clips and sermons (server)
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23: "if we create media team they would be able to get the part when it comes to media like churchsavvy part and any that is related to that field already setup for them"; "lets start building this" (artifact "Church Areas and Keys", 7YRKpKa9g2DdFU9mm3WD8L, step 1)'
status: shipped
prs: [kmj-intake-server#1563, solutionist-studio#1336 (the app: Team page invite and the Media tab)]
migrations: [supabase/APPLY-2026-10-23-churchsavvy-media-part.sql (APPLIED LIVE 10/23 after a rollback probe)]
left_undone:
  - "A clip finder push for a volunteer opens the office's Video Clips page (grow:video-clips), which a volunteer can't open; it should open ChurchSavvy"
decisions:
  - "A fifth part, Media: the livestream, video clips, sermons and the screens' library; never the plan, the screens or the setup"
  - "The booth also runs the livestream (the person in the booth usually does both); the planner and the worship leader don't"
  - "The livestream's whole page opens to the parts that run it, chat moderation included: running a service and keeping its chat are one job on a Sunday"
  - "A part opens these routes only while ChurchSavvy is open to that person (WORSHIP_SONGS), so a team made while it was on opens nothing once it's off"
  - "A seat is checked first and works exactly as before; only a seat's 403 turns into the team's question. An outage on the seat check stays a 503"
  - "Approving a clip to post (it speaks for the church) and importing from the church's Drive stay with a seat; posting and covers already have their own owner checks"
  - "Finding clips with AI spends the church's clip minutes like a manager's run does"
  - "Sermons for the team go through the server (worship_sermons.py, /worship/sermons and /worship/sermon-series): the office's Sermons page keeps writing the tables under its seat rules, but a volunteer has no seat. Media and Admin write; every part and seat reads"
related: [2026-10-23-church-areas-map.md, 2026-10-20-churchsavvy-team-server.md]
---
Step 1 of the artifact, its second piece: Kevin's Media team.

**`worship_team.py`:**
- `ROLES` adds `media`.
- `CAN` adds `live` (admin, media, booth), `clips` (admin, media) and `sermons` (admin, media). Media also changes the screens' library (`media`).
- `parts_of` reads a person's parts by sign-in alone.
- `team_can` asks whether those parts open something outside ChurchSavvy, only while ChurchSavvy is open to them.

**Other files:**
- `live_router.require` wraps the seat check: a 403 becomes "does their part run the livestream?".
- `media_library.access(..., team=True)` does the same for clip work. `approve` and `import_drive` pass `team=False`.
- `worship_sermons.py` (new): the sermons and series routes for the team, with the tables' own limits said in words. A series must be the church's own.
- `live_router` calls the seat check as `kids_router.require` (no alias), so `ownership_sweep` follows the gate. With an alias the ratchet counted five live routes as unguarded.
- Migration: `worship_team_roles_check` is replaced, so the five parts are allowed.

**Checks:**
- `test_churchsavvy_media_part.py` (8 tests). 7 sabotages caught:
  - the team ignoring the switch;
  - removed members counting;
  - the booth on clips;
  - approve or Drive import opening to the team;
  - a seat outage turning into the team's yes;
  - the livestream opening to every part.
- `test_worship_sermons.py` (19 tests). 5 sabotages caught:
  - writes taking the plan's parts;
  - another church's series taken;
  - a failed read shown as an empty library;
  - no switch;
  - http links.
- `worship_team_db.mjs` gains 5 checks: the old check is replaced, not stacked; media and all five parts go in; a made-up part doesn't.
- The worship, live, media library and clip finder suites pass (140). Their pinned part lists were updated for the fifth part.
