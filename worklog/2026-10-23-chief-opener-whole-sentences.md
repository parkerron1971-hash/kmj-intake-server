---
title: On a call, Chief's opening line is said in whole sentences or not at all
date: 2026-10-23
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, after a voice session: "cut in sentence and I waited a couple of seconds for it to finish. so the flow seem like it got stuck", then "yes"'
status: shipped
prs: [kmj-intake-server#1551]
migrations: []
left_undone:
  - "Kevin also heard unnatural wording ('prompt', 'one sentence', checker phrasing like 'the testimonial ask ... so don't count on it'). The reply text needs a read of chief_conversations for 2026-10-23 08:03-08:08 UTC; the auto-mode classifier denied that production read, so it waits on Kevin's go-ahead"
  - "The early sentence check still streamed no sentence on those 5 turns: 4 of 7 attempts selected 25-42k characters against the 24k limit, and the final answer check took 2-12 s"
  - "Words appearing as they are spoken is the app's half (solutionist-studio, same day)"
  - "Chat openers keep word-by-word release and the dash; only calls changed"
decisions:
  - "On a call the opener gate releases a sentence only once all of it passed; a sentence that trips it (a name, a figure, 'already', a clause break, a dash, the word limit, or cut off by max_tokens) is dropped whole, so a call never ends its opening on a dash"
  - "No latency cost: the opener's text already reaches the gate a sentence at a time (chief_speech_boundary.SentenceBoundary in _pump)"
  - "The opener prompt now says never to use 'already', the word that cut 2 of the 5 openings ('opener=local(cut:already)' in the route log)"
  - "A sentence held while the local lead ('One second.') went out loses its own 'Sure,' when released, once"
related: [2026-10-22-chief-early-check-rows.md]
---
Five voice turns on 2026-10-23 (08:03-08:07 UTC), the morning after #1550.
Turn one: the local lead "One second.", then Haiku's two-sentence opening,
cut by the opener gate at "already" in "I'll set aside the invoice work
you're already doing" and closed with a dash. The answer was ready at 14.8 s
and the final answer check took 12 s more, so the call sat on "you're —" for
16 s (`max_audio_gap_ms` 16014). The gate stays exactly as strict; on a call
it now drops the sentence instead of saying half of it. Tests:
`test_model_router.py` (the gate) and `test_chief_two_track.py` (the
endpoint; it fails with the call change reverted).
