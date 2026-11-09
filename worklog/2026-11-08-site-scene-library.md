---
title: The scene library, three pinned scroll scenes the builder can place
date: 2026-11-08
agent: Claude Code (Claude Opus 5.5)
asked: "you can work on what is missing and need upgrading"
status: waiting on Kevin
prs: [kmj-intake-server#1772]
migrations: []
left_undone:
  - "Merged but switched off: SITE_SCENES waits for Kevin's judgment on the proof page and a Thursday."
  - "No real build has run with a scene. It needs one (about $2 to $4) to see what a Director and builder do with them."
  - "The sameness guard does not count scenes yet, so a house style is the risk to watch."
  - "About three more scenes are planned once these three prove themselves."
decisions:
  - "A scene for every photo count: none (scene-lines), one (scene-reveal), six or more (scene-wall)."
  - "Scenes are original, written for this library, on the browser's own scrolling. No animation library: GSAP's license bars competing no-code animation builders."
  - "At rest a scene is a plain stack. The script turns it on, and it stands down under reduced motion, on a very short screen and inside a clipped parent."
related: [2026-11-08-reference-sites-mood-only.md]
---
Measured on four live pages: both hand-built pages open near 200px with real
photos, both builder pages open under 100px with none, and no library piece could
hold the page still. Love City's scene is about 25 lines of plain script, so a
reusable version was realistic.

The scenes live in `site_scenes.py` and join the object registry, so the builder
places words and photos and the server adds the code, the same way objects work.
Checked in a real browser at both widths: the pin holds through each scene, the
page carries on after it, nothing scrolls sideways, and the three stand-down cases
show every word and photo. The proof harness was session-scratch; the rules it
checked are pinned in `__tests__/test_site_scenes.py`.
