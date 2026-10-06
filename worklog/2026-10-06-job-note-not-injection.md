---
title: A started job no longer marks Chief's turn as untrusted
date: 2026-10-06
agent: Claude Code (Claude Opus 5.5)
asked: "Kevin: whatever is missing, make the upgrades so it's better (found while fixing Chief's design wording)"
status: done
prs: [kmj-intake-server job-note-not-injection]
migrations: []
left_undone: []
decisions: ["Reword the note rather than loosen the concealment pattern: the pattern is right for third-party text"]
related: [2026-10-06-chief-design-noun-and-said-once.md]
---
The note Chief gets when it starts a job said "Never tell them the rest will
happen later". Tool results pass through the injection filter, whose
concealment pattern matched that sentence, so every turn that started a job
was marked tainted and held confirmable sends for the rest of the turn. The
note now says "Do not promise that the rest will happen later"; a test keeps
it clean and rehearses that the filter still catches the old wording.
