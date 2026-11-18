---
title: Member app stopwatch — how long member pages take, on the server and on phones (Database card)
date: 2026-11-18
agent: Claude Code (Claude Opus 5.5)
asked: '"the members app move slow when send messages in chat, switching from one tab to another… what is the problem and how can that be sped up?" … "yes build all four" (Kevin, 2026-11-18). This is fix one of four: the stopwatch, so the other three can be measured.'
status: shipped (fixes after review in review)
prs: [kmj-intake-server#1944, solutionist-studio#1638, "kmj-intake-server (the two fixes after review)"]
migrations: []
left_undone:
  - "No signed-in page was timed live yet: nothing timed member pages before this, and a member session can't be made for a real member. The first real numbers come from Railway's [member] lines and the Database card's next reading (Check now any time, Sunday from 7:45 AM)."
  - "Each reading keeps only the numbers of the server copy that took it (the scheduler's leader): a sample, not every visit. Adding all copies up would need somewhere shared to put them (a table: a migration), so it waits unless the sample proves too thin."
  - "A page that another fix turns into a swap inside the page (no full load) would not send phone timing; the server's numbers still count it."
decisions:
  - "Pure ASGI middleware outside gzip (total includes compressing the page), inside the custom-domain cache rule, which stays outermost"
  - "church = member_portal._church_for_request, session = member_portal._session_for (both wrapped by member_stopwatch.timed, every POST goes through them too), rest = everything else"
  - "Log paths are patterns: any part with a digit or anything but lower-case letters and dashes prints as :id; never the query string. Polls, icons, the service worker and the beacon print only when slow (>= 1 s) or failing"
  - "Only a signed-in member's page (200) or save (under 400) counts; sign-in pages and the owner's preview never do"
  - "Phone timing: navigation timing for the page just shown (first byte and DOMContentLoaded, from the tap; prerender measured from activation; back/forward cache sends nothing) via sendBeacon to POST /my/timing. Body is {p (path with digit parts as :id), f, r, t}; checked in Chromium that the beacon carries the page's real Origin under same-origin AND no-referrer"
  - "/my/timing takes a beacon only on a church address (never the API host), from its own page (Origin/Referer/Sec-Fetch-Site rules of member_portal._same_origin, and one of the three must be there), with a valid member session for that church (signature only, no read; the church from what this process saw serve a member page in the last 10 minutes, else one lookup), never with the preview cookie, numbers 0-60 s, at most RL_MEMBER_TIMING_PER_MIN (300) a minute per network"
  - "Numbers live in memory per (side, kind): last 1000 samples each. A db_health reading saves them into metrics.member_app (existing jsonb, no migration): scheduled readings take what this process timed since its last scheduled reading (at most an hour); Check now takes the last hour and never moves that mark"
  - "Readings keep histograms (25-50 ms buckets under half a second, 100 ms to 1.6 s) so Sunday's 15-minute readings add up; typical = the middle, slowest 1 in 10 = the 90th"
  - "MEMBER_STOPWATCH=off turns off the header, the log line, the phone script and the numbers; every piece fails soft"
related: [2026-10-20-member-app-speed.md, 2026-10-20-member-app-lookups-together.md, 2026-11-18-db-health-weekly.md]
---
The first of the four member-app speed fixes Kevin approved on 2026-11-18: a stopwatch,
so "slow" has a number before the other three land and after. `member_stopwatch.py` holds
all of it (read its docstring first):

- **Server-Timing** on every /my page and POST: `total`, `church`, `session`, `rest`.
- **One log line** per member request on Railway: `[member] GET /my/messages/:id 200 412ms church=85 session=90`.
- **Phone timing** from the page itself (`PHONE_JS`, inline in `member_portal._shell` for
  signed-in pages), to POST `/my/timing`.
- **Rolling numbers** per page kind (Home, Watch, Bible, Give, Connect, Messages, a
  conversation, Me, other pages, sending a message, other saves), server and phone.
- **Mission Control → Systems → Database** shows them: each reading (Sunday every 15
  minutes, Wednesday, Check now) saves them in `metrics.member_app`; the card says
  "Tabs open in 0.9 s typical, 1.8 s for the slowest 1 in 10 (last Sunday)", page by page,
  and a later Check now beside it ("Since then: …") for before and after.

**After review (second PR):** a reading's mark now moves only once the reading is saved
(`member_stopwatch.saved`, called by `db_health.take_reading` when the PATCH comes back),
so a failed save on a Sunday hands its quarter hour to the next reading; and the beacon
checks the session cookie's signature, for the church the cookie names, before it reads
anything, so a made-up cookie never costs a database read.

Tests: `__tests__/test_member_stopwatch.py` and the member-app cases in
`__tests__/test_db_health.py`, each rehearsed red (the wiring removed, and 21 one-line
breaks of member_stopwatch.py, each failing its test).
