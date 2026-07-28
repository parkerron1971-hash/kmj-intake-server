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
| `FALLBACK_BRAIN_MODEL` | `gpt-4o-mini` | any OpenAI chat model id |
| `OPENAI_API_KEY` | (already set) | shared with TTS + inference gate |

## The bigger resilience picture

The fallback brain is layer one. Layer two (queued arc): compounding
API-free intelligence — write-time embeddings on chief_memories
(pgvector), draft→template residue, playbook distillation, and wider
Tier-1 rule graduation — so each API call leaves behind an artifact
that makes future calls unnecessary. Chief's per-business smarts then
live in OUR database, portable across any provider.


## Why `gpt-4o-mini` and not `gpt-4o`

Changed after the first live test (2026-07-28), which is the only reason
we know.

Chief's prompt is ~33,500 tokens — the operating manual, the business
context, and the dynamic state block. Anthropic caches that, so on the
primary path it is cheap. OpenAI has no equivalent cache, and `gpt-4o` on
this org's tier carries a **30,000 TPM** ceiling.

So one Chief turn is larger than the entire per-minute budget:

```
Request too large for gpt-4o … on tokens per min (TPM):
Limit 30000, Requested 33565
```

That is not an intermittent rate-limit. It is arithmetic — the backup
brain could never once have answered, on any turn, for any practitioner.
It had been merged and unmerged for two weeks looking fine.

`gpt-4o-mini`'s ceiling on the same tier is far higher, so 33.5k fits.
It is also roughly **17× cheaper per turn** (~$0.005 vs ~$0.084) on a
path that pays full price for the whole manual every time.

The quality dip is the trade this document always described. If it stops
being worth it: raise the OpenAI tier, then set
`FALLBACK_BRAIN_MODEL=gpt-4o`.

**The general lesson**, worth more than the fix: a fallback that is never
exercised is a fallback that does not work. This one was wired correctly
at four call sites, metered, documented, and completely non-functional.
Nothing short of running it would have shown that.
