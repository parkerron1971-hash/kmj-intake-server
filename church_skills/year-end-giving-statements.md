---
name: year-end-giving-statements
use_when: giving statements for a tax year: the January mailing, one person's statement, or the gifts of $250 or more that need a written acknowledgment
triggers: statement, statements, year-end, year end, end of year, tax letter, tax letters, contribution statement, giving letter, giving letters, acknowledgment, acknowledgement, 1771
actions: giving_statements_run, giving_statement
---
STEPS
1. Settle the year first: the year that has closed, unless they name another. Say which year you used.
2. Run giving_statements_run for that year before anything else. From its result, say: how many people gave, the total, how many need a written acknowledgment (a single gift of $250 or more), and any unattributed total.
3. Unattributed gifts have no giver, so they can't go on anyone's statement. Say the amount, and suggest putting a giver on those gifts before the statements go out.
4. For one person's statement, use giving_statement with their contact. It says no goods or services were given unless told otherwise. If something was given in return (a dinner, a gift), put what it was in goods_and_services: the statement then says a good-faith estimate of its value is still needed, which the church supplies before sending. "religious" is only for intangible religious benefits.
5. Sending is done on the Year-end statements page (Giving). Offer to open it.

HAND BACK
Say the year, the count, the total, who needs an acknowledgment, and what to fix before sending.

NEVER
- Never say statements were sent: you don't send them.
- Never estimate an amount, and never give one person's giving to anyone who didn't ask for that person's statement.
