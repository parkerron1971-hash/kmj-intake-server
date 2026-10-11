---
title: "Chief makes offers and turns refer a friend on or off"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "continue to build the next steps that you just shared (Kevin, 2026-10-11: a way for Chief to make an offer or switch on refer-a-friend); build in the right order so it's fixed"
status: waiting on review
prs: [kmj-intake-server#1373]
migrations: []
left_undone: ["no read verb for offers: Chief opens Grow, Offers to show them (a read would join the outside agent's read surface and its counts)", "Chief can't send a client their own refer-a-friend link; the owner copies it on the Offers page"]
decisions: ["class C for all three: an offer changes what customers pay at booking, and refer a friend sends thank-you codes worth money by itself once on, so Chief acts only on the owner's word in this turn and a voice turn is held for a spoken yes", "tags, not native write tools, like the marketing desk: each is the owner's alone against the turn's signed-in person, which an outside agent doesn't carry, and class C is never a tool", "through the Offers page's own functions (offers.create_offer / change_offer, refer_a_friend.set_referral), so every check (card payments, codes, who and when) is the page's; their refusals come back in their own words", "schedule_action refuses them up front, and an unattended run is refused in the handler"]
related: [2026-10-10-offers.md, 2026-10-11-refer-a-friend.md, 2026-10-11-thank-you-words.md]
---
Chief could open Offers but not change anything there. Now, when the owner
asks in chat, Chief makes an offer ("a $10 first-visit offer", "15% off
for regulars on slow Tuesday to Thursday afternoons"), pauses or turns one
back on by its code, and turns refer a friend on or off with what each side
gets. The reply gives the code and the link, and says nothing goes out until
they share it.
