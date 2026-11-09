---
title: Three real test builds, and scenes that survive the builder
date: 2026-11-09
agent: Claude Code (Claude Opus 5.5)
asked: "yes you can test it"
status: waiting on Kevin
prs: [kmj-intake-server#1778, kmj-intake-server#1777]
migrations: []
left_undone:
  - "Merged but switched off: SITE_SCENES, SITE_BOLD_OPENING and SITE_PHOTOS_FIRST wait for Kevin's call and a Thursday."
  - "The fix was proven on the saved page, with no model call. No fresh paid build has run with it, so a Director or builder writing around the new rule is unproven."
  - "Nothing watches a scene move during a real build: the grader and the eyes only see stills, and the grader passed the broken page. The scene's own script now stands down if its pin isn't holding, and the browser tests move it."
  - "A photo in the opening's hidden tiles and again in the wall isn't caught as a repeat: the check skips anything aria-hidden, and photo-words tiles are."
  - "The Director skipped a scene on the two-photo barbershop. The page was strong without one, so the rule stays optional; watch how often scenes get chosen."
decisions:
  - "The server takes off anything a page writes for a scene's classes, free, on every build."
  - "A scene stands down to a plain stack if its pin doesn't hold. A blank scroll is the one thing it must never do."
  - "A page's fade-in may not hide a scene's photos or words."
related: [2026-11-08-site-scene-library.md, 2026-11-09-eyes-room-and-page-edge.md]
---
Three real builds with the switches on for that process only, nothing saved, $9.44 in all
with grading: Love City's public facts and photos $4.14, a barbershop with two photos $2.63,
a counselor on Plain $2.49. The one-look setting finally has numbers: build stage $2.21 to
$3.65.

The Director chose the wall for the church. The builder then restyled it in its own grid,
moved its line inside it, and the page's own fade-in hid the tiles, so a visitor scrolled
through screens of blank black. The grader passed that page, because it sees stills. The
library now holds its structure, and the server strips rules written over it.

Proof without paying: the saved page, with the builder's 27 rules taken off and the fixed
library put back, walks clean at both widths with zero hidden tiles.
