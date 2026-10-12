---
title: "Your name on texts: the form starts from About Your Business"
date: 2026-10-12
agent: Claude Code (Claude Opus 5.5)
asked: "yes make the form start from About Your Business (Kevin, 2026-10-12)"
status: waiting on review
prs: [kmj-intake-server#1396]
migrations: []
left_undone: ["the screen using it: solutionist-studio, the next PR", "nothing is written back to About Your Business when the owner saves the registration form"]
decisions: ["GET /texting/registration/{id} carries `from_about` (legal name, business type, whether an EIN is on file, address) only until the owner saves answers of their own; after that their answers win and from_about is null", "only filed facts: the business's display name standing in for a legal name is left out, and an S-corp (an election an LLC or a corporation makes) leaves the type to the owner", "the EIN itself never goes out in it, only has_ein", "readiness still asks for saved answers: a start is not a registration"]
related: [2026-10-11-isv-step-3.md, 2026-10-11-isv-sole-prop.md]
---
The registration form asked for the legal name and address again, though
About Your Business already keeps them (the same place the EIN lives). The
screen now gets those as its starting answers until the owner saves the form.

For KMJ Creative Solutions, the pilot, the legal name and address were
saved to About Your Business on 2026-10-12 (Kevin: the address is the same
as The Solutionist System LLC's, 2126 Torrent Street, Muskegon, MI 49441;
the name is right; an LLC, single or multi-member not yet said, so
entity_type is left empty).
