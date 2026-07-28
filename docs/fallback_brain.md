# The Backup Brain — provider failover for Chief

**Ruled by Kevin 2026-07-12.** If something happens to Anthropic — an
outage, rate limiting, a retired model, a missing key — Chief must
degrade, never go mute. The business rails (bookings, invoices,
bookkeeping, SMS, Tier-1 autopilot rules) never depended on an LLM;
this closes the last gap: the conversation itself.

## How it works

`chief_of_staff._call_claude` is the single funnel every Chief turn
goes through (chat, voice, coach, drafts). It now has four failover
seams — all of its previously-mute failure paths:

| Failure | Behavior |
|---|---|
| No `ANTHROPIC_API_KEY` | straight to fallback |
| Request error (network, timeout) | one fallback attempt |
| HTTP ≥ 400 (incl. 429/529 overload) | one fallback attempt |
| Stream died before ANY text | one fallback attempt (partial replies are still preferred over fallback) |

The fallback (`fallback_brain.py`) replays the same system prompt +
conversation against OpenAI chat completions. Chief's operating manual
and the `[ACTION:{...}]` protocol are plain text, so they port
verbatim — only Anthropic's cache-split markers are stripped. Voice
streaming turns receive the fallback reply as one chunk through the
same SSE sink.

## What Kevin sees

First engagement per 6-hour window: a push notification ("Chief
switched to the backup brain") + a `platform_changelog` entry
(pending) so it shows in Mission Control's operator log. Individual
turns after that are logged, not re-alerted. Every fallback call is
metered in `api_usage` under endpoint `/chief/backend-fallback` with
real OpenAI pricing.

## Honest limitations (by design, v1)

- **Quality dips.** The fallback model runs Chief's manual but has its
  own instincts — action-tag reliability and tone were tuned on
  Claude. Good enough to keep practitioners moving; not the same brain.
- **No prompt cache** on the fallback path — fallback turns cost more
  per token and run slower. Fine for an outage posture.
- **No web search** on fallback turns.
- Chat path only. Weekly insights / composer already fail soft
  (skip-and-retry-later) and don't need a second brain.

## Controls

| Env | Default | Meaning |
|---|---|---|
| `FALLBACK_BRAIN` | `on` | kill switch (`off` restores old mute behavior) |
| `FALLBACK_BRAIN_MODEL` | `gpt-4o` | any OpenAI chat model id |
| `OPENAI_API_KEY` | (already set) | shared with TTS + inference gate |

## The bigger resilience picture

The fallback brain is layer one. Layer two (queued arc): compounding
API-free intelligence — write-time embeddings on chief_memories
(pgvector), draft→template residue, playbook distillation, and wider
Tier-1 rule graduation — so each API call leaves behind an artifact
that makes future calls unnecessary. Chief's per-business smarts then
live in OUR database, portable across any provider.
