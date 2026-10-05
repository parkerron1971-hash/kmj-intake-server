# Chief's cases: the open-problem record

Solutionist Intelligence, step one (Dev Desk, 2026-10-05). Kevin asked
what would make SI different from a generic AI, not just in name. The
answer: a generic AI gives advice and forgets it. SI takes on the problem
and follows it until it is solved. A case is how Chief follows a problem.

## What happens

A salon owner says "Tuesdays are dead."

1. Chief finds the cause in her records ("your booking page shows you
   open around the clock") and says it in one sentence, with the one fix
   it would make and why.
2. She agrees to the fix. The fix itself goes through its normal action
   and approval, unchanged.
3. Chief opens a case: the symptom in her words, the cause, the record
   that shows it, the fix, and a forecast. The forecast is a measure (here
   bookings on Tuesdays and Wednesdays), the number BEFORE (the same
   measure over the same length of time just before, read when the case
   opens), the number Chief EXPECTS, and the day it will look.
4. Chief says it in one sentence: "Tuesdays and Wednesdays had 4 bookings
   in the last three weeks. I expect 9 in the next three, and I'll check
   on the 27th."
5. On that day the tick reads the records (no model) and records what
   they show and a verdict: met, partly (moved, short of the forecast),
   not_met, or unmeasured. She gets one notification, an activity row and
   a push. For the next week the result sits in Chief's context marked
   RESULT, and Chief tells her plainly: before, forecast, now. If it fell
   short, it says so and offers one next fix.
6. She closes it as solved or dropped (or Chief does, when she says so).

## What a case is not

- Not permission. Opening a case sends, books and charges nothing.
- Not a causal claim. The result is what the records show beside what
  was expected. Chief reports it as observed, never as proof the fix did
  it (the same rule as Codex's responsibilities, docs/CHIEF_FOLLOW_THROUGH.md).
- Not work between conversations. If the owner wants Chief to chase the
  number, that is `start_business_responsibility`, unchanged.

## The pieces

| Piece | Where |
|---|---|
| Table `chief_cases` (service-role only, RLS on, no policies, cascades with the business) | `supabase/APPLY-2026-10-05-chief-cases.sql` |
| Validation, the number before, the check, the owner's notice | `chief_cases.py` |
| Verbs `open_case`, `close_case` (class A, tags) | `ACTION_HANDLERS` in `chief_of_staff.py`, `action_registry.py` |
| When to open one, how to report a result | the CASES section in `chief_prompt.py` |
| Open cases and last week's results in every turn | `_gather_context` → `OPEN CASES` block |
| The answer check sees them as records | `chief_truth.py` context fields + `_FAST_CONTEXT` (`open_cases`) |
| The check, every six hours | scheduler job `chief_cases` in `kmj_intake_automation.py` |
| The app's card | `GET /agents/chief/cases?business_id=` (owner only) |
| Export and deletion | `account_lifecycle.py` table list |

## The rules the code holds

- Measures: `sessions_scheduled`, `sessions_completed` (optionally on given
  weekdays, counted in the business's own day), `new_contacts`,
  `revenue_collected`, `invoice_paid`. Counting reuses the assignment
  engine's reads.
- The window is the time after the fix: it starts today or later, lasts
  3 to 90 days, and defaults to the next three weeks. The check is the day
  after it ends. An invoice case checks in two weeks unless told otherwise.
- The forecast must beat the number before. A read that fails opens
  nothing; it never becomes a zero.
- One open case per problem, ten open per business.
- A check that cannot read tries again on the next ticks; after three
  failures the verdict is unmeasured and the owner is told so.

Kill switch: `CHIEF_CASES=off` stops the check; the verbs still record.

## What is deliberately not here yet

- The case is not one of the sources in Codex's responsibility report
  (`chief_responsibilities.py`). Adding a source there changes a report
  the app and its tests read whole; it is a separate change.
- The SI score (graded advice, hidden-cause cases, live wall rate) and
  the "are you an AI" rule ship as their own pull requests.
