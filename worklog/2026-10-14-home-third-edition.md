---
title: Home page, third edition (the S hero, sample customers, thirty-to-three, plan table, film)
date: 2026-10-14
agent: Claude Code (Claude Opus 5.5)
asked: "ok the direction is good... this will work. ship to live"
status: shipped
prs: [kmj-intake-server#1439]
migrations: []
left_undone: ["real customer photos replace the stock stand-ins in static/home/ (Kevin's shoot)", "a support phone line, if Kevin wants one printed beside the contact address"]
decisions: ["the hero shows the S, never a person: a sample customer must not read as the company's owner", "the S holds still; rings, light and the message pulse move around it", "sample customers are diverse and the pastor is shown in his church", "every price, credit, seat count and trial phrase reads the live dials; the plan table is _COMPARE_GROUPS with the gate map", "HOME_EDITION=v2 brings the second edition back without a deploy"]
related: [2026-10-12-site-without-therapists.md]
---
Kevin redesigned mysolutionist.app over six approved passes on a design artifact (Lumino as the reference for the
tech-and-profession mix) and asked to ship it. The page is `marketing_home_v3.html`, rendered by
`marketing_home_v3.py`: price cards, the founding-seat chapter and strip, and the 53-row plan table are built server
side from the dials and the gate map; the flyer, pixel, analytics, structured data, trial and contact sentinels are
the second edition's. Photos are stock stand-ins in `static/home/`, served by `/assets/home/{name}` (pattern-checked,
cannot leave the folder); the film is the live `/assets/film.mp4`. `render_home()` serves the third edition unless
`HOME_EDITION=v2`. Tests: `__tests__/test_home_v3.py`; the second edition's tests now pin it as the rollback.

2026-10-15 follow-up (Kevin: "say not real person or something next to the fake name and business"): the photos are
Unsplash free-license stock, which covers copyright but not the likeness of the people in them (Unsplash terms, section
5). So every made-up name now reads "not a real person", each business carries a Fictional tag and the caption
"is a fictional business", the photo says "Stock photo · a model", and the tag pointing at the person names the role
rather than the made-up name. The design source and the build script were changed with it, so a rebuild keeps the labels.
