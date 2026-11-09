---
title: The Design Coach hears what the owner asked Chief for, and knows what the page still needs
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: "make sure chief can interpret what everyone is asking like you can so the design could be good ... learn how to ask the right questions to get the proper prompt"
status: shipped
prs: []
migrations: []
left_undone:
  - "Layouts still ignore the ask until the layout PR lands."
  - "Chief still answers a website ask with the booking page until the Chief routing PR lands."
decisions:
  - "The ask is saved on the dossier when Chief opens the Coach, not sent by the front end, so every turn, a resumed session and voice all get it. It goes stale after 30 days."
  - "An address told to the Coach stays in the dossier and is a fallback for the page. It does not overwrite settings.address."
  - "No regex rewrites the Coach's replies about Instagram: 'the designer can pull your best ones from there' never names the place. The rule, a per-turn reminder and the bench are the guard."
related: [2026-11-09-coach-brings-its-styles.md, 2026-11-08-photos-first.md]
---
Talking to Chief as a test shop: "nothing fancy, I just want people to find me and
book" reached the blueprint at the end of the session and never the Coach. So the
Coach asked again for services it had on file (they were not in its context), never
asked where the shop was, and told the owner the designer could pull photos from
Instagram, which nothing can do.

The Coach's context now opens with what they asked for in their words, what is on
file, and what is still missing. "Still missing" is computed: an address and hours
for a trade people walk into, or for anyone who says "find me"; what they sell when
nothing has a price. The Coach's rules now teach how to read what people say ("nothing
fancy" is not the Plain setting), and name what nobody here can do. Naming where the
photos live brings the upload card back. The blueprint card says when a walk-in
business has no address.
