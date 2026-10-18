---
title: Featured voices (server) - Grace, Elijah, Jessica and Reed, on Inworld, included like Nova
date: 2026-10-17
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin: "I want Jessica, Reed, and the other two speed 1.1. can they be options that people choose from?" (step one of the voice switch, after a blind test against ElevenLabs, Cartesia and Rime)'
status: shipped
prs: [kmj-intake-server#1482]
migrations: []
left_undone:
  - "The voice pickers (Settings and the chat's Voice menu) are the solutionist-studio PR that follows"
  - "Step two, a test of Inworld's one-connection speech for call mode with Claude still thinking, is not started"
  - "ElevenLabs voices are unchanged; the account behind the local key has an unpaid invoice, and Kevin has not decided whether to keep it"
decisions:
  - "Included with every plan, like Nova (Kevin): the rows ride /ai/tts, UNIT weight 0, no owner check, no monthly cap"
  - "Flash (inworld-tts-2-flash) for all four; Grace and Elijah speak at 1.1x, Jessica and Reed at 1.0x (Kevin)"
  - "Default voice stays Nova (Kevin)"
  - "The picker stores our slug (iw:grace), never Inworld's voice id, so a voice can be re-made behind it"
  - "Any miss speaks as Nova: unknown slug, no key, a refusal, a timeout, an error before the first audio, text over 4,000 characters"
related: []
---
`whisper_proxy.py`: `iw:<slug>` routes to Inworld's streaming endpoint
(`/tts/v1/voice:stream`, one JSON object per line). The first slice of audio
is read before answering, so a failure can still fall back to Nova; PCM is
headerless (`PCM`, not `LINEAR16`, which puts a WAV header on every slice)
and kept sample-aligned across slices. Short phrases go through the same
phrase cache as the other providers, keyed with the voice's speed, and a
stream cut short is never kept. The keep-warm loop pings Inworld's French
voice list (four voices, ~750 bytes) while a call is live.

`GET /ai/tts/voices` lists the four first (`iw:` ids, label, desc), then the
ElevenLabs voices; without `INWORLD_API_KEY` the four are hidden.

`api_usage_logger.py`: `inworld-tts-2-flash` priced at $15 / 1M characters
(pay-as-you-go; $10 on Inworld's Creator plan) and the `inworld` provider.

Grace and Elijah were made with Inworld's voice design and published to the
workspace of the key on Railway (`INWORLD_API_KEY`, set by Kevin 10/17).
Measured from here: first audio ~0.2 s on the streaming endpoint.
