# The rail: records questions answered from the records

Kevin, 2026-10-16: the AI is a library and Claude is the librarian. A layer
two should fetch the book so the librarian doesn't have to, the way crypto
layer twos cut cost while raising quality. The design brief is "The Instinct
Layer" (artifact Stx24uZHBXG1RS2ir61LTZ). The rail is its middle tier.

**Status: practice mode only.** The rail never answers anyone. It watches,
answers privately, and keeps score.

## The idea in one example

A barber asks "Did Maria pay?". Today that is a full Sonnet turn (about 19¢
on average for a lookup, 5–10 seconds) and often the paid answer check too.
About a third of the short money and calendar answers came back walled
("I couldn't verify…") even though the answer sits in one table (rail probe,
2026-10-16).

The rail sees the same question, finds Maria's one contact, reads her
invoices, and writes:

> Maria Lopez owes $450.00 on invoice INV-0012, due Oct 10, 6 days overdue.

That sentence passes the same free prover that lets Chief's own sentences
skip the paid check (`chief_truth.fast_lane`): the figure, the name and the
date share one invoice row. No model is called. It takes a fraction of a
second.

## What practice mode does

After Chief's reply has gone out (`chief_fast_track.TwoTrack.finish`, full
turns only), on a worker thread:

1. **Read the question** (`read_question`). A shelf takes it only when the
   whole message is one of its shapes. Otherwise it is declined, with a
   reason (`phrasing`, `no_shelf`, `not_a_name`, …).
2. **Check the owner.** Service-role read of `businesses.owner_id` against
   the asking user. Not the owner (a collaborator, anyone else): nothing is
   read and nothing is kept.
3. **Read fresh** (`read`): one exact query per shape, scoped to the
   business. Never a saved answer.
4. **Compose** (`compose`): only what the read returned, one invoice or one
   session per sentence. Too long (more than 6 clients, 8 sessions or 4 of a
   client's invoices) or an unnamed client: left to Chief.
5. **Prove** (`prove`):
   - `prover`: every sentence passes `chief_truth.fast_lane` against the
     rows, shaped exactly as Chief's answer check sees them. Totals are
     proved against Chief's own `_invoice_summary_lines`, so the rail's sums
     and Chief's sums must agree.
   - `empty_read`: "Nothing is booked tomorrow" is proved by the read itself.
     The read returned every matching row, and there were none.
   - `failed`: neither.
6. **Compare** (`compare`) with what Chief said:
   - money: dollar amounts, plus the yes or no for "did X pay";
   - calendar: clock times.

   The outcomes:

   | Outcome | Meaning |
   |---|---|
   | `agrees` | Chief said the rail's headline and nothing the records lack |
   | `partial` | everything Chief said is in the records, but not the headline |
   | `differs` | Chief said a figure, time or yes/no the records contradict |
   | `withheld` | Chief's reply was walled |
   | `silent` | Chief said no figure (a question back, a hedge) |

7. **Keep one row** in `chief_rail_practice`, and print one `[rail]` line
   (counts and labels, no content).

Records questions off the shelves (the front desk's `kind=lookup`) are kept
too, as declines, so coverage can be measured.

## The shelves

| Shelf | Form | Example | Read |
|---|---|---|---|
| money | `who_owes` | Who owes me? | open invoices (draft, sent, viewed, overdue), fewer than 40 |
| money | `owed_total` | How much am I owed? | same |
| money | `overdue` | Any overdue invoices? | same |
| money | `did_pay` | Did Maria pay? | the one contact, then their invoices (not cancelled) |
| money | `client_balance` | How much does Maria owe me? | same |
| schedule | `day` | What do I have tomorrow? | scheduled sessions on that local day |
| schedule | `next` | When is my next appointment? | the next scheduled session |
| schedule | `client_next` | When is Maria's appointment? | the one contact's next session |

The definitions match Chief's own. "Owed" means sent and unpaid; drafts are
listed apart. "Overdue" means sent and past its due date. Days run on the
business's clock (`mailbox_policy.email_clock`'s order). A weekday that is
today ("Friday" on a Friday) is declined, because it could mean today or a
week away. Availability questions ("am I free Thursday at 3?") are not
taken: `chief_availability` already answers them from the records.

## Reading the record

- `GET /platform/rail/stats?days=7` (platform owner only): per shelf, the
  questions asked, taken and proved, the outcomes, the decline reasons,
  Chief's cost on the questions the rail took, and the time each side took.
- `railway run python -X utf8 scripts/rail_practice_report.py 7`: the same
  summary from a terminal.

## When a shelf may go live (not built)

These are the Kahneman–Klein conditions from the brief:

- a regular question shape asked many times;
- at least 100 practice answers;
- at least 99 in 100 compared answers `agrees`;
- every `differs` read by a person.

When Chief's walled answers (`withheld`) had a proved rail answer, that
counts for the rail. Confidence never counts.

The live step would be one more PR:

- for these shapes, answer from the rail;
- send the rail's facts to Chief whenever it hands over;
- leave Chief's turn unchanged otherwise.

One owner correction or a failed proof moves a shape back to practice. KMJ
goes first.

## Switch

`CHIEF_RAIL=off` stops the rail. Unset means practice. The table is
`supabase/APPLY-2026-10-16-chief-rail-practice.sql`. Without it, the rail
prints one warning and backs off for ten minutes at a time.

## Cost

There are no model calls. A practice run makes two to four small
service-role reads and one insert, after the reply, on records questions
only. At most three run at once; past that, a run is skipped.
