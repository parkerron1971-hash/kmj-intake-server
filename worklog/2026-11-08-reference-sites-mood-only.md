---
title: A site the owner admires gives the designers its mood, not its identity
date: 2026-11-08
agent: Claude Code (Claude Opus 5.5)
asked: "yes make the reference-site fix as its own PR"
status: shipped
prs: [kmj-intake-server#1771]
migrations: []
left_undone:
  - "A look match is only recorded in the build report (canvas_report.reference_closeness); no screen shows it yet."
  - "The after-build check runs in builder_v2 only. The older canvas and module engines get the prompt fix but no check."
  - "An owner who types a brand name in their own words still reaches the Director, with one line telling it to take the discipline only."
  - "From the same review, not code here: ask Webflow or a lawyer whether GSAP's license covers the video maker, and Kevin files a DMCA agent."
decisions:
  - "Mood words only: a rule saying never copy is weaker than never handing the details over."
  - "Copied wording is soft tier: it costs the repair round and never sends a build to the fallback engine."
  - "The reference's text is fetched at build time, compared in memory and never stored."
  - "The owner's own words never count, so naming your own old site is safe. Scripture, menus, footers and forms are not compared as copying."
related: []
---
Kevin asked how Chief can reach top-tier site quality legally: copy how things
work, never what someone made. The review found the designers were told never
to copy a site the owner admires while being handed its exact colors, font
names, own description and address. The address also let the builder's look
tool screenshot that site, because the dossier digest feeds its real data.

All four routes are closed: `reference_analyzer.compact_summary`, the intake
text in `site_composer`, `discovery.dossier_digest` and, through it, the look
tool. A check after the build then compares the finished page to those sites.
`REFERENCE_CLOSENESS=off` turns the check off. Before extending this, read
`__tests__/test_reference_mood_only.py`.
