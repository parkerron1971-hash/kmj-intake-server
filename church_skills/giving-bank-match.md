---
name: giving-bank-match
use_when: someone asks whether a service's giving reached the bank, or to match the church's recorded gifts to its bank deposits
triggers: made it to the bank, make it to the bank, makes it to the bank, reach the bank, reached the bank, in the bank yet, match the deposits, match deposits, the deposits, giving deposits, sunday deposit, the sunday match, check the matching
actions: giving_deposits, match_giving_deposits, unmatch_giving_deposits
needs: giving_services, giving_deposits
---
STEPS
1. Look first with giving_deposits: the matches made and by whom, the clear matches ready to make, gifts with no deposit yet, deposits with no gifts, and its check of every match.
2. Card and online gifts reach the bank as payouts and are matched on their own: this is about cash, checks and the like.
3. Make the clear matches with match_giving_deposits only when they ask. For a match they name, the deposits must add up to the gifts; if they don't, say by how much and what may be missing.
4. If a check shows a match is no longer right (a gift changed or refunded), say so plainly and offer unmatch_giving_deposits; never change a match without asking.

HAND BACK
Say what matched, what is still waiting for a deposit, and any deposit with no gifts.

NEVER
- Never say cash or checks are in the bank until giving_deposits shows them matched.
- Never force a match that doesn't add up.
