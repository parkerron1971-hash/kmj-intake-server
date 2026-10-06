---
title: Covers use a speaker photo and the close-up whose expression fits the title
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "make those changes and fix."
status: done
prs: [kmj-intake-server speaker-photo-expression]
migrations: []
left_undone: ["Frontend: a Speaker photo row in the covers recipe with a picker and upload (follow-up FE PR)"]
decisions: ["The speaker photo is its own image row with a fixed id per business, not part of the saved style, which is wiped when the style is forgotten or replaced", "It is used only when face recognition says the clip's speaker is that person (0.45), so a guest speaker's clip never gets someone else's face", "The expression pick is best effort and asked once per clip; any failure keeps the face picker's order"]
related: [2026-10-06-likeness-meter.md, 2026-10-06-clothing-fade.md]
---
Items 5 and 6 of the list Kevin approved after the shirt fixes. The face
picker chose close-ups by sharpness and size, never by mood, so a cover for
a warning could carry a smile. A vision call now puts the close-up that fits
the title first. A business can also save one real photo of its speaker; it
leads the cover whenever face recognition agrees the clip shows that person.
