# Calls: audible within a second

Dev Desk, 2026-09-25, the voice output brief: build a low-latency voice output pipeline on top of the model router (`docs/MODEL_ROUTER.md`). The target is audible speech within one second of the practitioner finishing their turn. Time to first audio is logged per turn as the primary metric, kept apart from time to first token, with an SLO of one second at the 95th percentile.

This builds on the 2026-09-08 voice latency arc. That arc already delivered the streaming speech relay, streamed PCM playback, the call's cached openers and per-sentence speech. The table below shows what each of the brief's items needed on top of it.

| The brief asks for | Was already there | Added now |
|---|---|---|
| Sentence-boundary chunking | The app speaks the first sentence alone, then about 180-character groups (`createStreamSpeaker`). The server streams checked sentences (`_SentenceStreamer`). | The first track (`chief_fast_track`) puts a first sentence on the wire within 500ms, so there is a sentence to speak. |
| A warm persistent TTS connection | No. Each sentence group opened a new HTTP client, paying a fresh TCP and TLS handshake to OpenAI or ElevenLabs. | `whisper_proxy._tts_http()` keeps one keep-alive pool per event loop. While a call is going, a free request every 45s keeps the connection open between turns (`TTS_KEEP_WARM`). |
| A pre-generated opening phrase cached as audio | Yes, in the app: 11 openers are preloaded when a call opens (`chiefVoice.preloadPhrases`). | The server keeps the audio of short phrases (60 characters or fewer) once rendered, so a hit costs no provider call or charge (`TTS_PHRASE_CACHE`). The server's call leads are preloaded with the openers, and the stream speaker plays a sentence that exactly matches a preloaded phrase from memory. |
| A buffer and playback queue that doesn't stutter, with backpressure | An ordered queue with gapless PCM scheduling, but every group's fetch started at once, and an underrun restarted at "now" (a click each network read). | At most two TTS requests at once, the sentence being said and the next (`MAX_TTS_AHEAD`). Sentences written while synthesis is behind merge into the waiting request (`TTS_MERGE_MAX_CHARS`). An underrun rebuffers a quarter-second before resuming (`PCM_REBUFFER_S`): one short pause instead of a stutter. |
| Barge-in: cancel the generation, the playback and the queue | Only on the final transcript, about 1.5s into the interruption. | Chief's voice drops the moment the relay reports `speech_started` (`chiefVoice.duck`). The first words that aren't Chief's own echo stop everything: the playback, the queued and in-flight TTS, and the SSE read of the reply. If no words come within 1.4s, the voice comes back up. |
| Time to first audio as the metric, 1s p95 SLO | A debug HUD only. It was hung on the orb's "speaking" event, which fires before any sound, so `tts=` always read 0. | The first audible sample is announced from every playback path (`FIRST_AUDIO_EVENT`). Each call turn is reported to `POST /agents/chief/voice/turn` and stored in `voice_turn_log`. It gets its own p95 window and owner page (`voice_metrics.py`). |

## The clock

- **Start.** The relay's `speech_stopped`: the moment the system knows the turn is over.
- **Stop.** The first audible sample of anything Chief says: the cached opener, the server's lead, or the reply.
- **`reply_audio_ms`.** The same clock, stopped instead at the first audio that came from the server's stream. It is logged beside the main figure, so a fast opener can't hide a slow answer.
- **What the clock does not include.** The relay waits `vad_silence_ms` (900) of silence before it fires `speech_stopped`. That silence happens before the clock starts, so it is not in the figure. The practitioner's felt wait is the sum, and both numbers are on the row.
- **Which turns are judged.** A turn replaced before it spoke is kept on its row but is out of the SLO. A turn cut off by barge-in is recorded as `interrupted`, with `barge_in_ms` (onset to silence).

Join `voice_turn_log` to `model_route_log` on `request_id` to see the first-token and first-audio numbers for the same turn. The SQL is in the migration.

## On a call, the lead is a sentence

On screen, the first track's local lead is an interjection ("Okay —") that the next words continue.

Spoken, a fragment followed by a pause sounds like a dropped line. So on the voice surface the lead is a whole short sentence:

- "One second." by default;
- "On it." for an action;
- "Okay." for a yes.

Thanks and goodbyes get no lead. That follows Kevin's 2026-09-08 rule that those are answered directly, and the fast lane answers them in about half a second. When the call already spoke its own opener (`spoken_opener`), the server adds nothing.

## Why a pooled connection rather than a socket

The brief names "a websocket or streaming session". The two providers don't share one:

- OpenAI's speech endpoint is plain HTTP.
- ElevenLabs has an input-streaming socket per voice.

What the brief wants gone is the per-turn handshake. A kept-alive HTTP/1.1 connection removes that for both providers, with no second protocol to keep alive.

## Barge-in and the server

Barge-in stops the reply's words: the audio, the queue, the fetches, and the stream read. It does not cancel the server's turn. Actions already taken stay taken. Cancelling a turn on disconnect is what once made a re-ask run its actions twice (`chief_stream_replay`).

## Switches

| Variable | Default | Controls |
|---|---|---|
| `VOICE_TTFA_BUDGET_MS` | `1000` | The first-audio budget. |
| `VOICE_SLO_WINDOW_S` | `900` | The p95 window. |
| `VOICE_SLO_MIN_SAMPLES` | `20` | Samples needed before the SLO can page. |
| `VOICE_SLO_ALERT_COOLDOWN_S` | `3600` | Minimum time between pages. |
| `VOICE_LOG_DB` | `on` | Writing rows to `voice_turn_log`. |
| `TTS_KEEP_WARM` | `on` | The keep-warm request during calls. |
| `TTS_PHRASE_CACHE` | `on` | The server's phrase audio cache. |

The app's pacing constants are in `chiefVoice.ts`: `MAX_TTS_AHEAD`, `TTS_MERGE_MAX_CHARS`, `PCM_REBUFFER_S` and `DUCK_LEVEL`. The barge-in release (`BARGE_RELEASE_MS`) is in `ChiefCallMode.tsx`.

Owner stats: `GET /platform/voice/stats?hours=24`.
