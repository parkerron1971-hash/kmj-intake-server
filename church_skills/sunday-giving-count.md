---
name: sunday-giving-count
use_when: someone records or checks a service's giving (the Sunday count, the plate, the checks and cash), or asks whether it reached the bank
triggers: count, counting, offering, offerings, plate, tithe, tithes, the giving, sunday giving, record the giving, record gifts, checks and cash, deposit, deposits, the bank
actions: giving_counts, record_service_gifts, undo_service_gifts, giving_deposits, match_giving_deposits, unmatch_giving_deposits
---
STEPS
1. Look first with giving_counts for that service and day: whether its count is open, what is in it already, and what is coming up. Online gifts are already placed in the week's service: never type them in again.
2. To record, take the gifts the person names: each giver by name (one of the church's people), or "loose" for plate cash, or "anonymous"; the amount; how it was given (cash, check with its number, an app); the fund when they say one. Record them with one record_service_gifts for that service's open count.
3. If a name isn't one of the church's people, nothing is recorded. Ask who they mean. Never make a person up, and never record that gift as loose instead.
4. Read back what the result says was recorded: how many gifts, their total, and the count's totals by way. Use its numbers, never your own sums.
5. If a number was wrong, undo_service_gifts takes that batch back while the count is open; then record it again.
6. Later in the week, for the bank: look with giving_deposits. Make the clear matches with match_giving_deposits only when they ask. For a match they name, the deposits must add up to the gifts (online: less the fee); if they don't, say by how much and what may be missing.

HAND BACK
Say what was recorded, what is still open, and that two counters close the count on the screen (Giving, Gifts). Offer to open it.

NEVER
- Never close a count: two counters do that on the screen.
- Never say the giving is in the bank until giving_deposits shows it matched.
- Never force a match that doesn't add up.
