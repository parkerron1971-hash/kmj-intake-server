---
title: The Light Table, step 1 (Studio brief and proof, backend)
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: "this design is good. let's go with it."
status: in progress
prs: [kmj-intake-server#1784]
migrations: []
left_undone: ["The app's Light Table screen (solutionist-studio, next PR)", "Free word fixes: the Director leaves room and the composer sets date, place and last line (step 3)", "Three looks: three Medium sketches before the full drawing (step 4)", "Every size and the Series shelf (step 5)", "The ~$6 engine test was offered, not run", "Turn STUDIO_LIGHT_TABLE on, on a Thursday, once the screen is in"]
decisions: ["Kevin approved the Light Table canvas https://claude.ai/artifact/Vcma193TFunxdNoUnEKwLv", "The Studio's brief goes through Chief's own design_flyer path, so credits, the daily limit, the owner check and the replay guard are the same", "STUDIO_LIGHT_TABLE off | owner | on, default owner, like CHURCH_AREAS", "The calendar suggestion skips services and private occasions and invents nothing"]
related: [2026-10-05-creative-director-every-business.md, 2026-11-07-packs-say-flyers.md]
---
`studio_light_table.py` adds the Studio's two calls. `GET /ai/images/studio/{biz}`
says whether the Light Table is open, what a flyer costs, and the next occasion in
Services & Events to start the brief from. `POST /ai/images/studio/{biz}/design`
turns the brief (kind, headline, a line under it, when, where, a last line, where it
goes, up to four photos) into the design_flyer action Chief sends and hands it to
`creative_director.handle_design_flyer`, with the request id as the turn identity.

The review now keeps each check (`checks`: words, readable, layout, brand, likeness)
and `public_state` shows them, so the proof can list what was checked. Designs
checked before this change show no breakdown. A low likeness score also fails the
likeness check.

Before building more here: the canvas's build order is engine test, this screen,
free word fixes, three looks, then sizes and Series. Prices on the canvas (three more
looks 10 credits, a new size 10 credits) are proposals Kevin has not set.
