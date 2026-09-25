# Chief's two-track reply: the model router

Dev Desk, 2026-09-25: make Sonnet-backed Chief feel as fast as Haiku without
losing answer quality. The first word must arrive within about 500ms on
every request, with no exceptions. The baseline was 8 to 10 seconds to the
first word.

| Piece | File |
|---|---|
| Complexity scoring, routing policy, semantic cache, the opening and fast-answer gates | `model_router.py` (pure logic, no I/O) |
| The first track: Haiku calls, the deadline, the fast lane, escalation, the handoff to the turn, the owner stats route | `chief_fast_track.py` |
| Per-request log, cost tally, first-token SLO and p95 alert | `route_ledger.py` |
| Where the first track runs | `chief_of_staff.chief_chat_stream` |
| Where the full turn continues the opening | `chief_of_staff.chief_chat`, just before its model call |
| Arrival stamp (starts the clock before auth) | `sse_middleware.NoGzipForStreams` |
| Table | `supabase/APPLY-2026-09-25-model-route-log.sql` |

## How a streamed turn runs

1. **Score** the message with cheap heuristics (`model_router.score`, about
   1ms). The score reflects what the request needs as well as how its
   language reads.
2. **Decide** the lane (`model_router.decide`):
   - `fast`: Haiku writes the whole answer and the full turn never runs.
   - `full`: Haiku writes an opening at once, and the full turn (Sonnet,
     unchanged) runs behind it.
   - `cache`: a repeat of an earlier fast answer, sent at once.
   - When the heuristics are unsure, the request goes to the Haiku
     classifier (`/chief/route`, bounded by `ROUTER_CLASSIFIER_TIMEOUT_MS`).
     If the classifier fails or is unsure, the request goes to `full`.
3. **Stream** the first track. A deadline guards the first word: the budget,
   minus `ROUTER_DEADLINE_MARGIN_MS`, from arrival. If no model has produced
   a safe word by then, a local lead ("Sure —", "On it —", "Of course —")
   goes out, and the model's words follow it with its own "Sure," removed.
4. **Continue.** The full turn is told what was said, in the uncached prompt
   tail (`continuation_block`). Its checked sentences and its final answer
   continue the same stream. The final payload's `response` is the reply as
   it was shown.

## What lands where

For Chief, low complexity also means needing no records and no action.
"Did Maria pay?" is four words, but it still needs her invoice and the
answer check. So a request escalates when it needs the business's records,
wants something done, calls for reasoning, involves code, or asks for a long
piece of writing.

Haiku answers alone only for:

- pleasantries: thanks, praise, "how are you";
- short general-knowledge questions that are not about the business.

Some requests always go to the full turn:

- farewells: the full turn closes the chat window;
- a "yes" or "ok" replying to Chief's question: that is the go-ahead;
- sentinels, coach modes and images.

The fast lane also needs a full turn for the same user and business in the
last 30 minutes. The fast lane skips `chief_chat`, and `chief_chat` is what
proves the business is theirs and that they are inside their allowance.

## What the first track may say

The answer check (`docs/CHIEF_ANSWER_TRUTH.md`) holds model prose until it
is proved, because a spoken false success cannot be taken back. The first
track keeps to that rule.

- **The opening** (`OpenerGate`) must start as intent: "Let me…", "I'll…",
  "Checking…". Within that frame, "whether Maria paid" is a question being
  looked into, not a claim. The opening is cut at the first point where it
  could become an answer:
  - a second clause after a break;
  - a figure the practitioner did not say;
  - a name the practitioner did not say;
  - the word "already".

  It streams word by word, so the gate does not cost the budget.
- **A fast answer** (`AnswerGate`) holds its first three words. If they
  deflect ("I don't have access…", or `NEED_RECORDS`), the turn escalates
  before anything is shown. After that, the gate holds back a four-word
  tail, so that a claim the fast lane cannot make ("I've just sent…", "your
  revenue is…") is cut before its first word goes out.

## Silent escalation

The full turn takes over without any message about it in these cases:

- the fast answer deflects, claims something it cannot, errors, or times
  out;
- the finished fast answer looks thin (`looks_thin`: empty, truncated,
  hedged, or too short);
- the practitioner's next message says it missed ("that's not what I
  asked", "try again", "??").

After a message like that, the conversation stays on the full turn for the
next four turns.

## The cache

The cache holds only fast-lane answers to general questions. It is scoped
per user and business, lasts 24 hours, and lives in memory in this process.

Near-repeats match: case, punctuation, fillers and word order don't matter.
A different number, a negation, or a different key term never matches.
Chief's business answers are never cached, following the standing ruling in
`docs/inference_layer.md`. Social replies are not cached either: hearing
the identical "Anytime!" every time is a machine tell.

## The SLO

- Time to first token is measured per request, from the ASGI arrival to the
  first delta the stream yields, and judged against `ROUTER_TTFT_BUDGET_MS`.
  The result is on every row (`slo_met`).
- A 15-minute window computes p95. When p95 is over budget with at least 20
  samples, the owner gets one Mission Control finding and one push. The
  alert re-arms only after p95 recovers.
- App-initiated sentinel turns are exempt.
- A request that errors before any word goes out counts as a miss at its
  total time.
- The local lead holds the budget whatever the models do. So a breach means
  the time was lost before the stream started: auth, the event loop, or the
  host.

## Tuning

Use `GET /platform/routing/stats?hours=24` (owner only). It shows:

- first-token p50, p95 and p99, and the percentage that met the SLO;
- the lane and opener mix;
- the escalation rate;
- cost;
- a table of complexity bands. A band where many fast answers escalate
  means `ROUTER_FAST_MAX_SCORE` is too high.

Every threshold is a Railway variable (see `.env.example`).

To measure "the number to beat" on the same table, set `CHIEF_ROUTER=off`.
Rows keep arriving with lane `off`. The SQL at the bottom of the migration
compares the two.

## Cost

Each routed request tallies every model call it makes:

- the opening, classifier and fast answer (Haiku);
- the full turn's model rounds (the streamed `_call_claude`, the plain
  `_call_claude`, and drafts);
- seam-metered calls such as the answer check (`llm_call._meter`).

Background sweeps that the turn spawns are excluded. `api_usage` stays the
billing ledger, with these endpoints:

- `/chief/opener` and `/chief/route`: `units=0`;
- a fast answer: `/chief/backend`, the same price as any Chief turn.

## Kill switches

| Variable | Effect of `off` |
|---|---|
| `CHIEF_ROUTER` | Turns everything off. Rows are still logged. |
| `CHIEF_ROUTER_FAST_LANE` | Haiku never answers alone. |
| `CHIEF_ROUTER_OPENER` | No Haiku opening. The local lead still goes out. |
| `CHIEF_ROUTER_LOCAL_LEAD` | No local lead. |
| `CHIEF_ROUTER_CACHE` | No cache. |

## Not changed

- The plain `/agents/chief/chat` endpoint.
- Everything inside the full turn: tools, actions, the answer check, and
  sentence streaming.
- The voice call's own spoken opener. When the client already said one,
  no second opening is written.
