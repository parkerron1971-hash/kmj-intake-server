---
title: Chief marks how a spoken reply should sound (tone notes)
date: 2026-10-18
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "take 1 and 2 sound the same, build the tone notes" (after the tone test, artifact TnbYNV74wuE7HytcFmEUkZ, and the plan where Chief judges when a reply needs a note)'
status: shipped
prs: [kmj-intake-server#1494, solutionist-studio#1265]
migrations: []
left_undone:
  - "CHIEF_TONE_NOTES is off. Kevin listens to the sample (artifact HnQSSu2p23i9vLLxUPNAH4) and says owner (his own calls first) or on (everyone with a featured voice)"
  - "The What's New entry goes in with the switch to on for everyone; nothing a practitioner sees or hears changes before then"
  - "The plain /agents/chief/chat endpoint never asks for notes: only the streaming endpoint can carry them to the voice"
  - "FOUND, NOT FIXED: the ElevenLabs per-business monthly cap (_el_chars_this_month) builds its month start with \"+00:00\"; PostgREST reads the + as a space and answers 400 (measured 2026-10-18), the read is taken as zero rows, so that cap has never tripped. Fixing it starts enforcing a live limit, so it is Kevin's call"
decisions:
  - "Chief writes five fixed notes ([pleased] [proud] [gentle] [steady] [breathe]); the speech proxy maps them to the Inworld steering Kevin picked by ear (\"say upbeat and pleased\", \"say upbeat and proud\", a breath with steady)"
  - "A note is never a word downstream: every Chief model answer is stripped in _call_claude (chief_tone.take); the streamer checks sentences without notes and sends them beside the words as a delta's `speech`"
  - "The model is chosen per TTS request: a piece with a tone note on inworld-tts-2, anything else on Flash; a breath alone stays on Flash, which performs it too"
  - "The app carries the tone from piece to piece, so a reply keeps its tone and its model to the end"
  - "A tail the answer check rewrote is said [steady]: a correction never sounds pleased"
  - "Platform-wide cap INWORLD_TONE_MONTHLY_CHARS=200000 (about $5 on TTS-2); past it, notes drop and Flash speaks"
related: [2026-10-18-review-possessive-names]
---
On a spoken turn whose voice is a featured one (the app sends
`tone_notes: true`), and with `CHIEF_TONE_NOTES` on (or `owner`, the
platform owner's businesses only), the voice tail of the prompt gains
`chief_tone.PROMPT_BLOCK`: judge by what the reply leads with, keep
routine replies plain, open with one note, and change at most once, as
`[breathe] [steady]` where good news turns to bad.

Where the notes go:
- `chief_of_staff._call_claude` is decorated (`_without_tone_notes`, with
  `functools.wraps`, so the tests that read its source still read the
  body): every answer comes back without notes (`chief_tone.take`), and the
  tagged answer is recorded on the turn's `ToneTurn`, which the streaming
  endpoint sets before the turn starts.
- `_SentenceStreamer` strips each sentence before the prover and before
  `sent` (so stitching is unchanged), and emits the tagged sentence; a note
  on a line of its own goes with the next words. `_stream_piece_events`
  turns it into `{"type":"delta","text":<words>,"speech":<words with notes>}`.
- The part that did not stream gets its `speech` from
  `chief_tone.tail_speech`: notes go back where the words after them are
  found; a rewritten tail is said `[steady]`; no notes means the app carries
  the tone it has.
- `chief_voice_bridge` compares the preview and the main sentences by their
  words, and a note on a sentence it leaves out moves to the next one.
- The cap counts with a "...T00:00:00Z" month start and treats a failed read
  as a failed read (the last count stands), not as zero rows: the PR's review
  caught the "+00:00" form 400ing, measured live (5,094 Flash characters this
  month read back through the real function after the fix).
- `whisper_proxy`: tone notes go to Inworld only. `_inworld_text` speaks each
  run of words through `normalize_for_speech` and puts the steering back
  between them; OpenAI and ElevenLabs get the words alone. A tone-model miss
  retries the same voice on Flash before Nova. `api_usage` rows carry
  `model=inworld-tts-2` (priced at $25 / 1M chars in api_usage_logger), and
  those rows are what the monthly cap sums.

Tests: `__tests__/test_chief_tone_notes.py` (32): strip parity sentence by
sentence vs whole, the streamer and the stream endpoint end to end, the tail,
the bridge, the proxy's model choice, the cap, the fallback, and who gets the
rules. With the stripping and the model switch reverted, 6 fail. The stream,
bridge, Inworld and PCM suites pass (207 with the new file), and all 72 test files that touch `_call_claude` (1,264).

The judgment, measured: `scripts/chief_tone_eval.py --live`, thirty spoken
questions on a fictional coaching business (half routine, half with news),
with Chief's real system prompt on the voice lane's model and effort. Scored
with one rubric: 23/30 with the first rules, 27/30 after "judge by what the
reply leads with", 28/30 after "small talk and advice stay plain even with
good news in them; the note comes first". Last run: 14/15 routine left plain,
14/15 news given the right note; misses: a "good morning" that became a
briefing was said proud, and a cancellation was left plain. Each run cost
about $0.90 (an 80K-token cached prompt). Replies and logs are kept in
C:\Users\kmccl\Projects\tone-eval\.

The sample (artifact HnQSSu2p23i9vLLxUPNAH4): seven of those replies in
Grace and Elijah, cut and carried the way the app speaks them, through
`_inworld_text` and the per-piece model choice, beside the same words on
Flash. gpt-4o-transcribe heard no note read aloud in any of the 14 toned
clips. Inworld cost $0.30.
