---
title: One calendar of everything that goes out (GET /calendar?month=)
date: 2026-10-09
agent: Claude Code (Claude Opus 5.5)
asked: "work on this in order (Kevin, 2026-10-09; step 1 of the approved plan: one calendar)"
status: done
prs: [kmj-intake-server#1364, solutionist-studio#1190]
migrations: []
left_undone: ["offers join the calendar with step 3 (they do not exist yet)", "one-off SMS broadcasts and Chief's single emails are not on it; only desk posts and Outreach campaign touches", "the week board (This week / Next week) still shows posts only, with its review actions; Month is where everything shows together"]
decisions: ["the calendar is one month on the business's own clock (business_tz, as /engine): desk posts that are not cancelled, and Outreach touches on the campaign's start day plus their offset (the sweep's rule), from running, paused or completed campaigns; a draft has no day and is not shown", "a touch is planned, sending (due, still going out), sent (finished) or paused, with how many people it went to (campaign_sends)", "a failed read is named in sources and its items left out, never an empty month; a month at its row limit is partial"]
related: [2026-10-09-outreach-links.md, 2026-10-09-booking-follows-the-link.md]
---
The Reach plan's step 1, third part (after #1362 bookings follow the link and
#1363 Outreach links). The desk's Calendar read two weeks of posts; Outreach
emails and texts lived on their own screen. Calendar → Month now shows any
month of both together (solutionist-studio#1190), and Mission Control's desk
reads the same through /platform/marketing/suite/calendar.
