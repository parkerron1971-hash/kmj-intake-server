---
title: ChurchSavvy show engine — services, screens, the look, live slides to every screen
date: 2026-10-19
agent: Claude Code (Claude Opus 5.5)
asked: '"keep going with step 2 I want the entire thing built. also can you ahve access inside the system and access outside the system as well. i want this part built so we can ship out soon." (Kevin, 2026-10-19)'
status: in progress
prs: [kmj-intake-server#TBD]
migrations: [supabase/APPLY-2026-10-19-worship-show.sql (applied)]
left_undone: ["the app's Sundays planner, Run Sunday booth, Screens setup and screen pages (solutionist-studio, same arc)", "the Look editor page", "the song finder (public-domain hymns, photo read)", "ChurchSavvy standalone (its own front door for churches without Solutionist)", "media volunteers who aren't staff can't run slides yet (STAFF_ROLES only)", "the lobby loop (lobby screens show the room's slides for now)"]
decisions: ["screens follow the booth over Server-Sent Events from this process (LiveHub), not polling: the class TV's once-a-second poll is too slow for lyrics", "a screen's link is a 32-byte token naming one screen row; the business comes from that row (ownership_sweep HINT screen_from_token, beside the check-in station's station_from_token)", "the booth posts what's on screen; the screens fetch the live service's slides and redraw for their role (room, online lower third, LED wide, stage)", "live state is kept in worship_live so a restart or a late screen picks up; rev = milliseconds since 1970 and only goes up", "a screen never receives the booth's notes"]
related: [kmj-intake-server worklog/2026-10-19-churchsavvy-songs.md, kmj-intake-server academy_slides_router.py]
---
The show engine under ChurchSavvy's screens, the server half. `worship_show.py` defines what a service item may hold: a section, a song (with its arrangement), scripture, text slides, an announcement, a picture or video, or a countdown. It also turns a service into slides in order. Each slide is one of lyric, verse, text, announcement, image/video or countdown, and every screen knows how to draw those. A song that lost its words, or was taken out, says so in `missing` instead of going up blank.

`worship_show_router.py` serves:
- services (plan, start from a template, archive) and the booth's show (slides in the church's look and brand);
- screens with their links (staff only ever see a link; a new link retires the old one);
- the look;
- `/worship/live`, which the booth posts to;
- a screen's own endpoints with no sign-in: info, the live service's slides without the booth's notes, and an event stream that reaches waiting screens at once.

Checks:
- 33 pytest (engine 20, router 13), including a real-uvicorn test where a screen's stream hears slide 0 on connect and slide 1 when the booth posts.
- `__tests__/worship_show_db.mjs`: 32 checks.
- The access ratchet and export list tests pass.
