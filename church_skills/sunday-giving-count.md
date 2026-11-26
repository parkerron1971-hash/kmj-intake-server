---
name: sunday-giving-count
use_when: someone records a service's giving (the Sunday offering, the plate, the checks and cash) or asks what is in a service's count
triggers: the count, sunday count, offering count, the offering, sunday offering, record the offering, record the giving, record gifts, record sunday, plate cash, checks and cash, tithes and offerings
actions: giving_counts, record_service_gifts, undo_service_gifts
needs: giving_services
---
STEPS
1. Look first with giving_counts for that service and day: whether its count is open, what is in it already, and what is coming up. Online gifts are already placed in the week's service: never type them in again.
2. To record, take the gifts the person names: each giver by name (one of the church's people), or "loose" for plate cash, or "anonymous" for a gift given without a name; the amount; how it was given (cash, check with its number, an app); the fund when they say one. Record them with record_service_gifts for that service's open count, up to 50 gifts at a time.
3. If a name isn't one of the church's people, or two people share it, nothing is recorded. Ask who they mean, or whether to add the person first. Never make a person up, and record a named gift as loose or anonymous only when the person says to.
4. Say what the result says was recorded: how many gifts and their total. For the count's totals afterwards, look again with giving_counts. Use the tools' numbers, never your own sums.
5. If a number was wrong, undo_service_gifts takes that batch back while the count is open; then record it again.

HAND BACK
Say what was recorded and what is still open, and that the count is closed on the screen (Giving, Gifts). Offer to open it.

NEVER
- Never close a count: that is done on the screen.
- Never type an online gift into a count.
