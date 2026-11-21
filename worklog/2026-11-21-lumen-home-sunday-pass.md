---
title: "Member app new look (Look 5.1): Sunday as a pass, the doors' live words, and the greeting's facts"
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin's Home plan (2026-11-21, 'yes to everything'), gaps two and three. Sunday's card is named 'Love City Church': check-in's closed state carries no settings, so the service's title falls back to the church's name; make it carry them without a new read. Make it a pass like the mock: a Tomorrow / Today / weekday chip, I'll be there, Watch live and Add to calendar, each only where its route already exists. The tiles say nothing real: Events 'N coming up', Serve the next serving time else 'N teams', Prayer 'N new' else 'Ask or pray', and a Give tile when giving is on, at most four. The greeting with real facts: when Sunday is, what's ready to watch, what's coming."
status: shipped
prs: ["kmj-intake-server (this PR)"]
migrations: []
left_undone:
  - "I'll be there needs the service's own calendar entry: it is that entry's RSVP (POST /my/rsvp, as Look 5.1's I'm coming). Love City's Sunday service isn't on its calendar (check-in makes the day's occasion only when check-in opens), so its pass shows Watch live and Calendar ahead of the day, and check-in's I'm here / Watching online on the day. No new write route was added for it."
  - "The greeting says 'tomorrow at 11', the way it already says 'tonight at 7', not the plan's '11:00'."
decisions:
  - "church_checkin.card's closed state is {'state': 'closed', 'w', 'settings'}: the settings card() already read ride along, so member_lumen_home.service_next names the service as the office named it ('Love City Experience') all week. Nothing else reads the closed state's keys; today's look and /my/here are unchanged."
  - "The pass is member_lumen_home.pass_card: week_card's picture and date leaf, a chip on the picture (Today, Tomorrow, else the weekday), the kicker, the title, where (or 'In person, or watch live in the app' where the church streams), how many are going, and a row of buttons that wraps. I'll be there is the service's calendar entry's own RSVP (event_act, its words only). Watch live opens the live page (/my/live) where the church streams: it is live now (Home's own live read), or it has gone live in the app before (member_portal_lumen.streams: live_sessions, one id, kept ten minutes per church in a member_cache.Kept; a failed read leaves Watch live out and isn't kept). Calendar is Watch's own .ics (GET /my/sermons/live.ics, download) where the office saved the service's day and time (check-in's settings, saved; the route answers from the same row). On the day, while check-in is open, check-in's buttons lead, Watch live shows only while the church is live, and Calendar goes."
  - "The doors: Prayer 'N new' (the unread count Messages already read) else 'Ask or pray'; Events 'N coming up': the calendar's upcoming occasions (upcoming_for, the list Events shows) and this week's service when it isn't on the calendar, and no number when the calendar read failed; Serve the member's next time, else the asks waiting, else 'N teams' (the serving teams in Home's groups read: theirs and those open to join), else as before; Give ('Give online', /my/give) while giving_router.giving_is_active, as the fourth door. When Kids already makes four (a parent or a kids leader, with Serve on), Give is left out: it is in the tab bar too, and Kids is the one only some people get."
  - "The greeting (member_lumen_home.line): the service tomorrow carries its time, in heavier ink ('Sunday is tomorrow at 11'). With no gathering this week to lead with, two facts follow: the newest message while it's new (member_feed_more.message_of: 'Last week's message is ready to watch') and the next event a week to three weeks out, never a service ('Oh Give Thanks is two weeks out'). Both from what Home already read."
  - "CSS only in member_lumen_home.CSS (the chip, the wrapping button row, the outlined button), every rule under .lm, the page's tokens; the chip sits on the photo on a dark scrim, as the picture pins do."
related: [2026-11-21-lumen-home-stories.md, 2026-11-20-lumen-watch.md]
---
Love City's Sunday now reads "Love City Experience", as a pass with Watch live and Calendar; the doors carry
live words and Give; the greeting says when Sunday is, what's ready to watch and what's coming.

Checked: switch off and MEMBER_LUMEN=preview for a non-owner, 951 page x scene dumps each (Home harness 656,
Bible harness 295), main and this branch dumped back to back: same 951, differ 0 in both modes. Reads with the
switch on (warm), per page and table in four looks: Home harness 1984 / 1984 over 328 page-looks, no page differs;
Bible harness 1282 / 1284 over 236, the only pages that move are /my and /my/directory, by the group feed's own
reads (member_feed_more), and two runs of main differ the same way. Cold (nothing kept): one more GET, the
church's live_sessions id (kept ten minutes per church). Member suites and the check-in tests with -n 2: 1630
passed (16 new in __tests__/test_member_lumen_home_pass.py; two pins updated for the plan's words). Shots before
and after (Chromium and WebKit, light and dark, 390x844 @2x, the rich sample church and a church with no posts)
in the session scratchpad's home-build-shots/pr2-sunday-pass/.
