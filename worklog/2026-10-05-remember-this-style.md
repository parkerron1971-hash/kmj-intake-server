---
title: Remember this style (a saved look for a business's flyers and clip covers)
date: 2026-10-05
agent: Claude Code (Claude Opus 5.5)
asked: 'build the remember this style button and question the thumbnail you made for the videos. you made that on the system made that?'
status: in progress
prs: [kmj-intake-server saved-design-style, solutionist-studio remember-this-style]
migrations: []
left_undone: []
decisions: ["One saved style per business; a current style reference still wins", "A saved style replaces the seven-direction list, so a series reads as one set", "Placements for a subject/style picture are dropped, not fatal (they stopped every clip cover at planning)"]
related: [2026-10-05-creative-director-every-business.md, 2026-10-05-clip-covers.md]
---
Kevin asked whether the sermon covers on the plan page were made by the system.
They were not: they were direct GPT calls with hand-written prompts. Running the
same three moments through the real Make cover request showed every cover
failing at planning: the planner also "placed" the speaker's photo, and only
logos/product shots may be placements. Stray placements are now dropped. After
the fix all three system covers finished (two passed first time, one after its
repair; $0.05-0.12 each); private drafts in KMJ Creative Solutions (agency).

Remember this style: the saved style now leads new designs (instead of a hint
under the seven directions); GET/DELETE /ai/images/director/{business}/style
show and clear it; the app gets the button on design cards and clip covers.
