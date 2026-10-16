# The rail: records questions answered from the records

Kevin, 2026-10-16: the AI is a library and Claude is the librarian. A layer
two should fetch the book so the librarian doesn't have to, the way crypto
layer twos cut cost while raising quality. The design brief is "The Instinct
Layer" (artifact Stx24uZHBXG1RS2ir61LTZ). The rail is its middle tier.

**Status: practice mode only, and off until switched on.** The rail never
answers anyone. When `CHIEF_RAIL=practice` is set, it watches, answers
privately, and keeps score.

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
   session per sentence. These are left to Chief:
   - too long: more than 6 clients, 8 sessions or 4 of a client's open
     invoices;
   - an unnamed client;
   - any amount not in dollars (a mix included).

   Invoices are aged on the business's own date, not UTC's. At 02:00 UTC it
   is still yesterday in Detroit, so an invoice due yesterday there is not
   overdue yet.
5. **Prove** (`prove`):
   - `prover`: every sentence passes `chief_truth.fast_lane` against the
     rows, shaped exactly as Chief's answer check sees them. Totals are
     proved against Chief's own `_invoice_summary_lines`, so the rail's sums
     and Chief's sums must agree.
   - `empty_read`: "Nothing is booked tomorrow" is proved by the read itself.
     The read returned every matching row, and there were none.
   - `failed`: neither. A read that did not return every row proves
     nothing, whatever it says.
6. **Compare** (`compare`) with what Chief said, against a **strict
   grammar of supported claims**. Every sentence of the reply must parse
   whole into claims of a supported shape, or be on a short whitelist of
   harmless text. The whitelist covers an offer that is a question ("Want me
   to send reminders?"), "here's the breakdown", "hope that helps". A
   sentence with no figure is still a claim: "All invoices are paid.",
   "Maria owes nothing.", "She has cancelled." and "Your calendar is clear"
   are each checked or kept out of agreement, never skipped. Each claim
   binds its figure to:
   - a subject: one client, matched in any case against the business's
     whole contact list; "she"/"he" when there is one client in play; or
     the business;
   - a status: owed, overdue, paid, booked;
   - where said, an invoice number, a count, a due date, days overdue, a
     payment date or a day.

   The parser splits a sentence at a comma, colon, semicolon or "and" only
   where both sides are supported claims. A short "and $300" or "Tasha
   $200" takes the subject and status of the claim before it, and "...and
   still owes $100 on INV-0001" takes its client.

   Each claim is then checked against what the read holds (the ledger:
   every invoice with its number, client, amount, status, due date, days
   overdue and payment date; each client's balance; the totals):
   - "$1,200" said as Maria's, when $1,200 is Tasha's, differs;
   - "$300 across 99 invoices" differs on the count;
   - "You have $300 overdue", when nothing is overdue, differs;
   - "Maria paid $100 on INV-0001", when INV-0001 is open, differs;
   - "Maria is next on Saturday, October 18", when Oct 18 is a Sunday,
     differs, because every part of a day phrase must hold at once;
   - "$300 across 2 overdue invoices" is an overdue claim: the count keeps
     its qualifier;
   - a due date or an age said with a client's total binds only when that
     total is one invoice, and is unverified otherwise;
   - a service named for the next session must be its title.

   Supported statements with no figure are checked the same way: "Maria
   hasn't paid", "Nothing is overdue", "Nobody owes you", "Nothing is booked
   tomorrow", "Maria has nothing booked". When the rail found nothing, a
   reply agrees only when such a statement checks out.

   **Anything outside the grammar is `unverified`, never agreement.** That
   covers "each", "both", "respectively", "except", "isn't booked", "was due
   yesterday", a range ("$100–$300"), "$300k", "$300 million", "$300.009",
   "about $300", a table, and a pronoun with no single client in play. Some
   claims the read can't settle are `unverified` too: a payment other than
   the latest (only the latest is read), or a client whose invoices this
   read didn't cover.

   Money also compares the yes or no of "did X pay".

   The tests hold this as a property.
   `test_no_false_reply_is_ever_scored_as_agreement` and its calendar twin
   generate 6,169 replies across client (any case, unknown, pronoun),
   wording, status, amount or time, day (combined weekday and date phrases
   included) and word order. Every true reply is also tried with a sentence
   after it, in two kinds:
   - a contradiction ("All invoices are paid.", "Nothing is booked
     tomorrow."), which must stop agreement;
   - a harmless offer, which must not.

   Not one false reply scores `agrees` or `partial`, and at least 80% of
   true ones do. Today it is 83 to 90%; the rest are `unverified`.

   The grammar grows from what Chief actually says: the practice rows'
   `unverified` share shows which shapes to add next. A shape is added only
   with its own true and false tests. The known limit: a lower-case name
   the business has no contact for reads as an ordinary word.

   The outcomes:

   | Outcome | Meaning |
   |---|---|
   | `agrees` | Chief said the rail's headline, and every claim is supported and true |
   | `partial` | every claim supported and true, but not all of the headline |
   | `differs` | a supported claim the records contradict (figure, count, client, status, invoice, day, yes/no) |
   | `unverified` | a figure in a sentence the grammar doesn't cover, or a claim the read can't settle: never agreement |
   | `withheld` | Chief's reply was walled |
   | `silent` | Chief said no figure (a question back, a hedge) |

7. **Keep one row** in `chief_rail_practice`, and print one `[rail]` line
   (counts and labels, no content). A failed read or insert logs the path
   with its filter values hidden and no error body
   (`sb_clients.redacted_path`), because PostgREST errors echo the failing
   row. A typed client name never goes into any URL: the business's
   contacts are read by its id alone (fewer than 5,000; at 5,000 or more
   the question is Chief's), and the name is matched
   in the process. HTTPX logs every request URL at INFO, so a name in a
   query string would reach the logs even when nothing failed.

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

- `GET /platform/rail/stats?days=7` (platform owner only): per shelf and
  per form, the questions asked, taken and proved, the outcomes, the
  decline reasons, Chief's cost on the questions the rail took, and the
  time each side took. **Agreement counts proved answers only.** A refused
  proof is listed as `proof_failed` and never raises the percentage.
- `railway run python -X utf8 scripts/rail_practice_report.py 7`: the same
  summary from a terminal.

## When a shelf may go live (not built)

These are the Kahneman–Klein conditions from the brief:

- a regular question shape asked many times;
- at least 100 practice answers;
- at least 99 in 100 compared, proved answers `agrees` (`partial`,
  `differs` and `unverified` all count against it);
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

Only `CHIEF_RAIL=practice` turns the rail on. Unset, empty or any other
value is off, so a deploy without the variable reads nothing. Features
switch on on Thursdays: set it then, on purpose.

The table is `supabase/APPLY-2026-10-16-chief-rail-practice.sql`. Without
it, the rail prints one warning and backs off for ten minutes at a time.

Rows are kept 90 days (`chief_rail.prune_tick`, daily at 08:45 UTC, behind
`scheduler_lock.gate`). A foreign key deletes them with their business. The
account export leaves them out (`account_lifecycle.EXPORT_EXCLUDED`): they
are tuning data derived from records the export already carries.

## Cost

There are no model calls. A practice run makes two to four small
service-role reads and one insert, after the reply, on records questions
only. At most three run at once; past that, a run is skipped.
