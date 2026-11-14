---
title: Chief in the sample church answers ten questions in its own lane (sample church, BE-4)
date: 2026-11-15
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14, approved the sample church signup: "top tier, no cut corners". BE-4 of the plan: Chief in the sample church, ten questions, its own small lane.'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "FE-3: the ten-question counter, the draft cards and the thread history, built against the contract below (sample.questions_left, sample.drafts, sample.capped; GET /sample-church/questions)."
  - "The live eval has never been run (it bills real model calls). Run python scripts/sample_chief_eval.py --live by hand: about 30 calls, roughly 30-50 cents. It reads a freshly built digest from BE-2's sample_church_data, else the fixture."
  - "After the first real questions, check api_usage rows with endpoint sample_chief: cache_read_tokens should be above 0 from the second question on. The cached prefix (rules + digest) is about 1.8k tokens by estimate, above the model's minimum, but nobody has measured it live."
  - "The digest says Today is the day it was seeded; BE-2 re-seeds when the week or month turns, so within a week a returning visitor reads the seed day's week."
  - "A spoken turn gets the same text answer (FE-1 keeps the sample text-only), and attached images are ignored in the sample."
  - "No server-side refusal fallback on this lane: a refusal is simply not counted, and the visitor is told to ask another way."
decisions:
  - "The divert is the very first statement of chief_chat and chief_chat_stream (_is_sample_turn, sample_church.is_sample_async, cached for good per business). Nothing of the real turn runs first: no JWT bind, rate limit, chief_fast_track, sweep, recurring invoice, action, tool loop, memory, archive, chief_truth or chief_activity. Fails open like is_sample: an unreadable answer is the normal turn, where BE-3's seams still refuse every send and AI call billed to a sample."
  - "Owner check: a service-role read of the sample's owner_id against the JWT user, 404 'Business not found' otherwise (what the handler's RLS read answers a stranger), 503 when unreadable. Then rate_limit.allow('chief', user), the handler's own limit and wording. The stream does both before any byte streams, so they are real HTTP errors."
  - "Not counted and no model call: a message starting [SYSTEM: (the opening greeting gets a welcome with the questions left; any other a one-line 'I'm here'), any mode but none/chief/chat (the coaches), a sample with no digest or not ready ('Grace Street is still being set up. Try again in a moment.'), a sample marked ending, AI paused by spend_guard, a question the table couldn't take, and a model call that failed (the claim is deleted)."
  - "The cap is atomic by construction: n is the smallest number in 1..cap the person's rows don't hold, UNIQUE(user_id, n) lets one insert through per n, and a loser re-reads once (twice taken: 'busy', not counted). n never exceeds the cap, so no race can make an eleventh row. The row id is made here, so an insert whose response was lost is recognised as ours. Smallest-free, not count+1: after a hole, count+1 would collide with an existing n for ever."
  - "An unanswered claim older than 5 minutes (a deploy cut the turn) is deleted at the person's next question, so it never costs them a question for good."
  - "The cap is per PERSON (user_id) across samples. SAMPLE_CHIEF_QUESTIONS sets it (1..50, default 10) through sample_church.questions_of(), which /billing/access's sample block and its fallback now read too, so the two always agree."
  - "The prompt: Chief's sample rules, then 'GRACE STREET'S RECORDS' + the digest with the one cache breakpoint, then (after it) the visitor's greeting name (chief_prompt.greeting_name of the sample's practitioner_name) and, on the last question, 'don't end by offering more'. History is the server's own rows for THIS sample asked since its seeded_at (the last 4 answered), never the client's conversation_history: BE-2 re-seeds when the week turns, and last week's answers quote last week's records."
  - "Chief answers only a sample that reads ready with a digest. BE-2's re-seed marks it seeding, and the app shows its setting-up screen meanwhile (FE-1 reads ready), so the two never disagree."
  - "The call: llm_call.apost inside sample_church.allow_sample_chief(), model chief_models.model_for('chat') (Sonnet 5.5), output_config effort low (SAMPLE_CHIEF_EFFORT low/medium/high) plus format json_schema {answer, drafts[{kind text|email|post|note, to_label, subject?, body}]}, max_tokens 4000 as a ceiling, 45 s. A max_tokens or refusal stop, an unparsable reply or an HTTP error is a failure: not counted."
  - "Held to the sample's promises in code, not only the prompt: a first-person claim of sending, saving, scheduling or changing is replaced by 'This is a sample church, so nothing was sent, saved or changed. In your own church, Chief does this for real once you say so.'; a reply with drafts always carries 'This is a sample church, so nothing was sent.'; a reply to 'send it' or 'delete everyone' always says it is a sample."
  - "Metering: one api_usage row per billed call, endpoint and task_type and lane sample_chief, business_id the sample, units 0 (no one is charged credits), cache counts and the 1-hour write split, response_id, turn_id the request id. A failed but billed call (max_tokens, refusal) is metered ok false. sample_chief is in llm_call._SELF_METERING so the seam doesn't count it twice. The Money room's AI costs read every api_usage row, so it shows there."
  - "The question's row gets question, answer (after the fix-ups), drafts, model, input_tokens (fresh + cache read + cache write), output_tokens and cost_cents (the same _compute_cost_cents the api_usage row uses). Nothing else is written: no chief_conversations, memories, notifications, chief_activity, agent_queue or ACTION_HANDLERS."
  - "Logs are counts and codes only (question number, model, tokens, cost, ms, drafts, fix-ups, rule-check codes), never the question, the answer or a name."
  - "A plain re-POST of a streamed turn whose final event was lost gets the same answer (chief_stream_replay, the real stream's registry), never a second counted question. The stream never cancels the turn when the client goes away."
related: [2026-11-15-sample-church-be1.md, 2026-11-15-sample-church-be3.md]
---
The sample's Chief lives in `sample_chief.py`; `chief_of_staff.chief_chat`
and `chief_chat_stream` hand a sample to it on their first line.
`GET /sample-church/questions` is mounted beside the church billing routes.
`scripts/sample_chief_eval.py` holds 31 visitor questions and 8 negative
controls with fixed replies, scored offline by `sample_chief.check_reply`
(39/39; the test suite runs it). `--live` asks the real model, by hand only.

Overlaps: BE-1 (#1851) made `sample_church_questions` and the sample block;
BE-3 (#1855) made `allow_sample_chief` and exempts `/agents/chief/chat`,
`/stream` and `/sample-church/*` from the write guard. BE-2 (#1854, the
seed) writes `settings.sample_church.digest`, `seeded_at` and status
`ready`; this PR reads only those and edits `sample_church.py` in one place
(`questions_of()`, beside `questions_left`). FE-1 (solutionist-studio #1561)
lets the chat, the stream and `/sample-church/*` through its guard and turns
the room strips off; the opening greeting (`[SYSTEM:opening_greeting:…]`)
still fires and gets the welcome line.

## The contract for FE-3

`POST /agents/chief/chat` with a sample's `business_id` answers 200 with the
shape the Chief panel already renders, plus `sample`:

```json
{
  "response": "Here are the four notes, one each. This is a sample church, so nothing was sent.\n\n**Draft text to Denise Carter**\n> Hi Denise, ...",
  "actions_taken": [],
  "grounding": {"status": "sample", "sources": ["sample_church"]},
  "sample": {
    "questions_left": 6,
    "questions_of": 10,
    "drafts": [{"kind": "text", "to_label": "Denise Carter", "body": "Hi Denise, ..."},
               {"kind": "email", "to_label": "the greeting team", "subject": "Thank you", "body": "..."}],
    "capped": false,
    "counted": true,
    "n": 4,
    "answer": "Here are the four notes, one each. This is a sample church, so nothing was sent.",
    "reason": null
  }
}
```

- `response` is `answer`, then (when there are drafts) a blank line and the
  drafts as markdown, so a screen that doesn't know `sample` still shows
  everything. FE-3 draws `sample.answer` and a card per `sample.drafts` item.
- `drafts[]`: `kind` is `text`, `email`, `post` or `note`; `to_label` is who
  it's for, as the records name them; `subject` only on an email; at most 4.
- `questions_left` is after this question (null when unreadable);
  `questions_of` is the cap; `n` is this question's place (1..cap), null
  when not counted.
- `counted` false and `reason` say why nothing was counted: `system` (a
  `[SYSTEM:` turn), `coaching` (a coach mode), `setting_up` (no digest yet),
  `closing` (the sample is ending), `paused` (AI paused), `capped`, `busy`
  (the table couldn't take it), `failed` (the model couldn't answer). The
  `response` is then one plain line, for example capped:
  "That's your 10. Chief keeps going in your own church once you choose a plan."
  with `capped: true`, `questions_left: 0`.
- Errors as today: 404 `Business not found` (not the owner), 429 (too fast),
  400 (empty message), 503 (the church couldn't be read).

`POST /agents/chief/chat/stream` (SSE, same request): 404/429/503 come back
as plain HTTP errors before the stream opens. Then:

```
:<16 KB of spaces>                                    (the edge-flush preamble)
data: {"type":"status","text":"reading Grace Street"}  (only when the model is asked)
: keep-alive                                          (every 15 s while it works)
data: {"type":"delta","text":"<sample.answer>"}
data: {"type":"delta","text":"\n\n<drafts as markdown>"}   (only with drafts)
data: {"type":"final","payload":{...the JSON above, sample included...}}
```

The deltas joined are exactly `payload.response`; the first delta is exactly
`payload.sample.answer`. **The `sample` object is on the `final` event's
`payload`** (chiefStream.ts already returns `evt.payload`). A turn that fails
inside the stream sends `{"type":"error","status":4xx,"detail":"..."}`; the
client's plain re-POST then gets the same turn's answer, never a second
counted question.

`GET /sample-church/questions?business_id=<sample>` (the sample's owner;
404 for anyone else, 401 without a login):

```json
{"ok": true,
 "questions": [{"n": 1, "question": "Who's been drifting?", "answer": "...", "drafts": [],
                "created_at": "2026-11-15T15:02:11.204Z"}],
 "questions_left": 9, "questions_of": 10}
```

Answered questions only, oldest first, per person (all their samples); `n`
is the place in that order. `questions_left` counts a question still being
answered, like `/billing/access`.

## What a church costs

Sonnet 5.5 as api_usage prices it: input $2, output $10, cache write $2.50,
cache read $0.10 per million tokens. Ten questions, the cache written once:

| | cached prefix | per church (10 questions) |
|---|---|---|
| the brief's assumption | 9k written once, read 9 times; 1.5k fresh in and 700 out each | $0.023 + $0.008 + $0.030 + $0.070 = **$0.13** |
| the real digest (BE-2's, 2.7k chars) + these rules (3.6k chars) | about 1.8k tokens | $0.005 + $0.002 + $0.030 + $0.070 = **$0.11** |

The answers are most of it (about two thirds). If the 5-minute cache lapses
before every question (a slow visitor), the cache is written ten times:
$0.15 with the real digest, $0.33 on the brief's 9k. Turns that aren't
questions cost nothing.
