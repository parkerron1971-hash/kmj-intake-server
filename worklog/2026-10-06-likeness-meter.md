---
title: The likeness meter, and up to three close-ups per cover
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "it can make my face pixel look much better without changing my face. make sense? (then yes to the likeness meter)"
status: done
prs: [kmj-intake-server likeness-meter]
migrations: []
left_undone: ["The clip service must be redeployed with railway up BEFORE this merges: the API asks /faces with count, which an older clip service refuses", "The app does not show the likeness score yet"]
decisions: ["No upscaling: EDSR left the face identical (0.998) and no sharper; face enhancers invent detail", "Face recognition (SFace) is the meter; LIKENESS_MIN 0.72 sits between the wide-shot cover (0.586) and close-up covers (0.82-0.93)", "The meter only fails a design below the bar and never when it cannot read a face; one repair stays the ceiling and the closer draft is kept", "Three close-ups plus the frame, or two plus the frame and a style picture: a design takes four pictures"]
related: [2026-10-06-face-backfill.md, 2026-10-06-better-face-frame.md]
---
Kevin asked whether the face pixels could be improved without changing his
face. Tested on his sermon: a faithful upscaler changes nothing useful and face
enhancers change the face, so the build gives the designer more real views of
him (up to three close-ups from the clip) and measures the result with face
recognition. The clip service gained POST /likeness (SFace, checksum-pinned at
build) and a count on POST /faces; the Director scores every finished design
with subject photos and sends a face that is not him back for its one repair.
On his covers the meter reads 0.586 for the wide-shot cover and 0.931 for a
close-up-guided thumbnail.
