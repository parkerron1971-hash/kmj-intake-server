---
title: In a church, media's jobs and ChurchSavvy's parts follow the duties each login holds
date: 2026-11-01
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-01: "church savvy should be connected with shapretta mcclain right from the list since she over media" (step 2b of docs/CHURCH_DUTIES.md, approved)'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "FE: the marketing desk, Video Clips and the site builder show their buttons to a church login whose duties open them (GET /engine can_edit already says so); ChurchSavvy's team list shows each office login's lane and parts (the new staff fields)"
  - "Step 2a (the weekly text, boards, chat rules, rooms, event sign-ups, the leaders note) is another session's"
  - "The livestream (live_router) and the media library (media_library.access) still take a Manager seat, not the stream or clips duty"
decisions:
  - "Only churches change: a gate opens to the owner, an Admin, or a login holds() says yes for (church_duties.does_job); a Manager whose job it isn't hears refusal(); a Member, Viewer or stranger gets the gate's own words; a failed duties read is a 503"
  - "Offers (business_marketing._owner_row) stay the owner's; the desk's writes use _poster_row, which the planner's run and preview share"
  - "A domain key in smart-config stays the owner's and the admins'; the composer's routes (domain connect too) are untouched"
  - "Covers for a clips login are made as the owner's, on the church's credits, through the same build actor the cover worker uses (the image engine reserves only for the owner)"
  - "ChurchSavvy parts: churchsavvy_team admin; sunday_plan or serve_schedule planner; stream media and booth; plus the team's own parts; none, reads only"
  - "Clip alerts go to every login holding clips, admins included (the treasurer too), once each, the starter first"
related: [2026-11-01-church-duties.md, 2026-10-20-churchsavvy-team-server.md, 2026-10-23-churchsavvy-media-part.md]
---
`church_duties.does_job` and `holders_of`; the posts gate in `business_marketing`,
`chief_marketing_actions`, `image_posting` and `chief_social_actions`; the clips gate in
`clip_posting`, `chief_clip_actions`, `clip_finder` (covers, alerts) and `clip_covers`; the website
gate in `public_site` and `events_rsvp_router`; ChurchSavvy parts from duties and the named team
list in `worship_team`. Tests in `__tests__/test_church_media_duties.py`; the pins that said every
Manager is a ChurchSavvy admin, and that only the starter hears about clips, were updated. The
plan's step 2b section in `docs/CHURCH_DUTIES.md` lists each gate and what stayed owner/admin.
