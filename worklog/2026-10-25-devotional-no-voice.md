---
title: The daily devotional page has no Listen button
date: 2026-10-25
agent: Claude Code (Claude Opus 5.5)
asked: "take the voice away. it doesn't sound natural. (Kevin, 2026-10-25, the evening of the first text)"
status: done
prs: [kmj-intake-server#1585]
migrations: []
left_undone: ["the member app's Listen (devotional_voice.py, the voices Kevin picked) is a different voice and is untouched; the app isn't revealed yet"]
decisions: ["removed, not swapped for a better voice: the page used the phone's own reading voice, which is what sounded like a machine; a natural voice would cost per listen and needs the app's audio path"]
related: [2026-10-25-devotional-daily.md, 2026-10-25-devotional-on-the-list.md]
---
`/daily` no longer shows Listen under the day's title. The button read the
day aloud with the phone's built-in voice (speechSynthesis), which Kevin
heard as unnatural. The button, its style and its script are gone; the day
reads the same.

Checks: the whole-day test now also asserts no Listen button and no
speechSynthesis on the page; 20 daily-page tests pass.
