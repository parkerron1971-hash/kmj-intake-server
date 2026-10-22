---
title: Professional gets its own texting number and three logins; Solutionist seven
date: 2026-10-22
agent: Claude Code (Claude Opus 5.5)
asked: "yes add the texting number to Professional as well. also include people being able to login 3 for professional sizes and solutionist size 7. pick the best number of logins. I go with your judgement. with the different levels I [think] 79 a month should have something else less [than] the 149 besides credits for chief."
status: waiting on Kevin
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "No What's New entry yet: practitioners on Professional now get a texting number and three logins, worth a line in solutionist-studio's whatsNew.ts when this goes live"
  - "The founding seat follows Professional ('everything but the tank is Professional's'), so founders get three logins and a texting number too"
  - "More businesses can now ask for a number. The Twilio campaign cap guard stops at 49 numbers; past it Twilio needs a number-pool request"
decisions:
  - "Logins 1/3/7: Starter is one person, Professional is a pastor, an admin and a treasurer, Solutionist is a staffed church. Kevin proposed 3 and 7 and left the call to me; I kept them, and Starter stays at 1 so it differs from Professional in more than credits"
  - "multi_seat moves to Professional with the seats, since it means 'more than one login'; the caps stay plan_limits() max_seats"
  - "dedicated_sms_number moves to Professional. Booked and Boss (the barber plans, still off) keep it"
  - "When a 402 names no plan, the texting number's 'comes with the X plan' reads the gate map and the plan's display name (it said 'Practice', a key no customer sees)"
  - "No Stripe change: prices and credits are the same; only what each plan includes moved"
related: [2026-10-22-one-brand-three-front-pages.md]
---
After the brand page, Kevin asked what separates the plans, then decided:
Professional gets its own texting number, and logins go 1 / 3 / 7. He also
wanted $79 to differ from $149 by more than Chief's credits. After this,
Starter has one login and no texting number of its own, on top of the books,
website chat and marketing week it already lacked.

`feature_gates`: `dedicated_sms_number` and `multi_seat` now start at
Professional, and `plan_limits()` gives `max_seats` 1/3/7. The home page's
plan cards move "A texting number of your own" to Professional (the cards
filter through the gate map, and the compare table follows by itself). The
team FAQ says "Professional includes three team seats and Solutionist seven."
The app reads seats and features from /billing/plans, so it needs no code
change. Tests that pinned 1/1/5 or Practice for the number were updated, and
`__tests__/test_plan_logins_and_texting.py` pins the new ladder.
