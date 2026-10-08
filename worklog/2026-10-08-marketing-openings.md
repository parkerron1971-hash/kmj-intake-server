---
title: "Boss: the barber-sized week: open chairs, work photos, pulled posts (marketing suite B11)"
date: 2026-10-08
agent: Claude Code (Claude Opus 5.5)
asked: "This will work. let's build this."
status: waiting on Kevin
prs: []
migrations: []
left_undone:
  - "Kevin: nothing runs until MARKETING_DESK covers a Boss business (worker AND web) and nothing sends unless MARKETING_DESK_PUBLISHING=on and the owner approves; the first open-chairs week should go to a test barbershop with weekly hours, a bookable offering and a connected Instagram"
  - "Not seen live: the most-booked offering. Production had no bookings with an appointment in the last 60 days on 2026-10-07 (read-only probe), so every week falls back to the shortest bookable offering until bookings that carry data->>offering_id exist"
  - "Not measured: the open-chairs week's caption call (estimated 1-2 cents on the draft lane); the pictures are local composer renders (cost 0)"
  - "booking_widget_router.py selects the module_entries column duration_min that does not exist (around lines 650 and 1323: the widget's slot read and the double-book guard's read). This PR fixed only agent_site.slots_for; how the widget's two reads handle the failed read was not checked. Worth its own PR soon: it may mean booked times show as open"
  - "No count of chairs is ever said: concurrent_capacity is still unverified (D5); open_count counts start times, not seats"
  - "Frontend F5 (the Boss view: work photos picker, pulled posts on the desk) is not built; the desk API already returns opening, status pulled and work_photo_ids"
decisions:
  - "Offering: most-booked active bookable offering over 60 days by module_entries.data->>offering_id (the field booking_widget_router._maybe_denormalize_offering and Chief's create_booking write; module_entries has no offering_id column, 400 on a read-only probe); else the shortest bookable (marketing_signals.chair_offering); bookings unreadable: shortest too. Recorded as signals.calendar.offering_from"
  - "Windows: strict slots_for starts on one local day no further apart than slot_granularity_min; window = first start to last start + offering length; open_count = starts in it"
  - "Rank: minutes x (2 - weekday share of the busiest weekday's 60-day bookings); no history: minutes alone; ties by earlier start. Pick 3, at most one per day, only if schedulable; returned in time order"
  - "Schedule on the business's clock: day before at the desk hour, else day before 3 PM, else that morning 8 AM; >= 1 h from now, not taken, >= 30 min before the cut-off; cut-off = start - max(2 h, calendar lead time); expires_at = min(run_at + 6 h, cut-off); compared in UTC (DST-safe, tested on both 2026 changes); a replan's own old drafts do not count as taken"
  - "Targets: Instagram first, Facebook too, from the desk's accounts; link = the booking page (/book) with the post's short link"
  - "Captions: one draft-lane call for the three (task business_marketing_openings, units=0); business checks + no seat count/scarcity words + its own day only + no today/tonight/tomorrow; a failed or missing caption gets the plain one ('Open chairs Thursday 2 to 5 pm. Book your time online...'); flyer words are built in code"
  - "Pictures: the desk's work photos (newest first, cycled) full-bleed 1080x1350 with a brand-colour panel and the words by the free composer (cost 0, build actor); no photo: the branded flyer and the Today item says so; never the image model"
  - "work_photo_ids in PUT /settings: owner only; each a ready upload of this business (other business 404, not ready/failed 409, made by the image model or composer 422), max 12, newest first, [] clears; a failed read 503"
  - "Pull: watch every 15 min (worker, scheduler_lock.gate, max_instances=1, MARKETING_DESK only) over approved/draft opening posts going out in 48 h, and the B5 sender just before the hand-off: fewer starts than open_count -> pulled 'fewer', none -> 'full', within the gap -> 'late'; status pulled + revision+1 + error words; never needs a yes. A failed read: the watch changes nothing, the sender holds (back to approved, retried). One Today item + one push per pulled post, keyed marketing_opening:<post id>"
  - "agent_site.slots_for (all surfaces): dropped the non-existent duration_min column from its module_entries select (it made every production read a 400 that counted as 'no bookings'); booked length from duration_min_at_booking or data->>duration_min_at_booking; strict= raises on a failed or full read; now= for tests. outside_calendar busy reads gained strict= (raise unless the feature is not set up)"
  - "Owner's request: kind openings (the old 409 OPENINGS_LATER is gone; run_week answers OPENINGS_LEVEL for a Boss chair business); week's rules: two replans (429), not over an approved/sent post (409), pulled posts do not hold the week, save new before retiring old, a request that writes nothing keeps the week"
  - "B8/B9 tests changed only where they pinned the old 409 for Boss: the planner suite drops that route case, the week suite's Boss test now asserts the open-chairs week instead"
related: [2026-10-07-marketing-weekly-plan.md, 2026-10-07-marketing-weekly-suggestion.md, 2026-10-07-marketing-signals.md, 2026-10-07-marketing-desk-send.md, 2026-10-07-marketing-desk-api.md]
---
B11 of docs/plans/MARKETING_SUITE_PLAN_2026-10-07.md (D5). A Boss chair
business (the desk's `openings` level) gets its weekly plan from the chair
calendar: business_marketing_planner.run_openings on the week's machinery
(claim kind 'openings', fan-out, jitter, headroom, owner's request), with
business_marketing_openings.py for the calendar's half (windows, rank, pick,
schedule, caption checks, the photo layout, work photos, the pull, the
watch). The B5 sender re-checks an opening post's window just before
sending; openings_watch_tick does so every 15 minutes and tells the owner
once per pulled post. PUT /settings takes work_photo_ids. The shared slot
computation stops reading a column module_entries does not have. No
migration, no Chief action, no frontend. Tests:
__tests__/test_business_marketing_openings.py (no live calls). Docs:
docs/MARKETING_DESK.md, "The barber-sized week (B11)".
