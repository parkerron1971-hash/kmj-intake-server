---
title: Grace at normal speed (server) - the same voice at 1.0x beside the 1.1x one
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "do i have the normal option for grace? want to see it in real time to see if it was better."'
status: shipped
prs: [kmj-intake-server#1484]
migrations: []
left_undone:
  - "Once Kevin keeps one speed, the other row comes out (a one-line change here)"
  - "The chat's Voice label reads the server's name for it in solutionist-studio#1257"
decisions:
  - "A second featured entry, iw:grace-normal, same Inworld voice at speakingRate 1.0, listed right after Grace"
  - "Its phrase-cache key carries the speed, so the two never share kept audio"
related: [2026-10-17-featured-voices.md]
---
`whisper_proxy.INWORLD_VOICES` gains `grace-normal` ("Grace (normal speed)",
1.0x). Picker order: Grace, Grace (normal speed), Elijah, Jessica, Reed.
Tests: the picker list, the 1.0x request, and that the two speeds never
share a kept phrase.
