---
title: The marketing desk API for one business (marketing suite B4)
date: 2026-10-07
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: [kmj-intake-server#1313]
migrations: []
left_undone: ["B5 sends: nothing claims or posts the approved rows yet, and post now refuses until MARKETING_DESK_PUBLISHING=on", "B6 tracked links: publish_text is the caption, with no /go/ short link yet; link_code is stored", "business_marketing_desk.today_items and chief_digest are built and tested but nothing calls them yet (Today and Chief wiring)", "Frontend F1/F2: no screen reads /marketing/{business_id}/* yet", "Not proven against production PostgREST: the tests use an in-memory fake (the RPCs themselves are covered by __tests__/business_marketing_db.mjs)"]
decisions: ["Reads are for the owner and members (business_access viewer); every write is require_user plus a service-role owner_id check", "A post id is a uuid5 of the business and the caller's idea id: a retry is the same post and two businesses cannot collide", "A new post goes to the desk's accounts still connected, else every connected Post for Me account; Instagram is left out without a picture and TikTok/YouTube without a video, with a plain note", "The next open time is a weekday at the desk's hour or 3:00 PM on the business's clock (availability, then the owner's profile, then PLATFORM_DEFAULT_TZ, then UTC), at least an hour out; the window is six hours, as on the platform", "Post now refuses before any write unless MARKETING_DESK_PUBLISHING=on (B5's switch), the pilot is on, the desk is not paused, the accounts are connected, Instagram has a picture and the caption fits", "A landing link must be https on the business's own host: its mysolutionist.app subdomain or its verified custom domain (a pending domain has no DNS)", "openings = marketing_week on a personal_services business whose booking page is published and has an active booking_calendar module (booking_is_live's rule, read fail-closed)", "upgrade = the next level's feature and upgrade_plan_for's plan, so Boss and Professional are pointed at Solutionist for autopilot", "marketing_desk's wording helpers take tz; the platform desk's default and its tests are unchanged", "The business desk promises no weekly plan until a planner exists (next_run is passed in, None for now)"]
related: [2026-10-07-marketing-suite-storage.md, 2026-10-07-marketing-plan-gates.md, 2026-10-02-marketing-desk.md]
---
B4 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md: Mission Control's
marketing desk for every business, on the marketing_* tables (applied).
business_marketing.py mounts /marketing/{business_id}: engine (the desk read,
with level, upgrade and the connected accounts), ideas and ideas/next-slot,
approve, slot/edit, slot/cancel, post-now, posts/{id}/not-sent and settings.
business_marketing_desk.py says where the desk stands from rows (Chief's read,
masthead, attention, Today items, digest) on the business's own clock. Nothing
sends, schedules, or calls a model; no Chief action, job or migration. Tests:
__tests__/test_business_marketing_api.py and
__tests__/test_business_marketing_desk.py (no live calls). The API section is
in docs/MARKETING_DESK.md.
