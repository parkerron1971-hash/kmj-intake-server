---
title: Someone on the devotional text list isn't asked to sign up again
date: 2026-10-25
agent: Claude Code (Claude Opus 5.5)
asked: "reason I ask because after reading the devotion is has the text alert sign up again.... Thoughts (Kevin, 2026-10-25, the evening before the first text; 23 people signed up)"
status: done
prs: [kmj-intake-server#1584]
migrations: []
left_undone: ["a new phone or browser that never opened a texted link still sees the sign-up (nothing in the URL names the person, by design); signing up again there is harmless, the row is one per church and phone", "a link forwarded to a friend carries t=1 too, so the friend sees 'You're on the text list' with 'Not on the list yet? Sign up here' right under it"]
decisions: ["every link we text (the evening text, the welcome, the DAILY reply) ends t=1; the page remembers it on the phone (localStorage) and strips it from the address bar so a copied link is clean", "the flag is set in a script in the head, so the form never flashes before it steps aside", "a sign-up problem (bad number, box not ticked, STOP before) always shows the form, whatever the phone remembers"]
related: [2026-10-25-devotional-daily.md]
---
The sign-up box at the bottom of `/daily` now has two faces. Someone who came
from a texted link, or who just signed up on the page, sees "You're on the
text list: each evening at 7:30, the next day comes to your phone. No need to
sign up again." with a "Not on the list yet? Sign up here" link that opens the
form (a spouse's number, or a friend the link was forwarded to). Everyone else
sees the form as before.

Checks: two new tests in test_devotional_daily.py (the texted link says t=1;
the box's three states), the evening-text and DAILY-reply expectations moved
to the new link; 143 devotional/SMS tests pass. In Chromium at 390px, light
and dark: first visit asks, ?t=1 shows the list box and drops t from the
address, a later visit without t still shows it, the link reopens the form
with the phone field focused, no sideways scroll.
