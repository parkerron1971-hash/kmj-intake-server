---
name: year-end-giving-statements
use_when: giving statements for a tax year: the January mailing, one person's statement, or the gifts of $250 or more that need a written acknowledgment
triggers: giving statement, giving statements, year-end statement, year-end giving, year end statement, contribution statement, tax letter, giving letter, donation statement, written acknowledgment, written acknowledgement
actions: giving_statements_run, giving_statement
---
STEPS
1. Settle the year first, and pass it as "year" every time: the year they name, or else the last full year. Say which year you used.
2. Run giving_statements_run for that year before anything else. From its result, say: how many people gave, the total, how many need a written acknowledgment (a single gift of $250 or more), and any unattributed total.
3. Unattributed gifts are mostly loose plate cash and gifts given anonymously on purpose: they stay off every statement. Only where the church actually knows a gift's giver should it be put on that person, on the Gifts page.
4. For one person's statement, use giving_statement with that person's contact id (find them the way you find any person first) and the year. It says no goods or services were given unless told otherwise. If something was given in return (a dinner, a gift), put what it was in goods_and_services: the statement then says a good-faith estimate of its value is still needed, which the church supplies before sending. "religious" is only for intangible religious benefits.
5. Sending is done on the Year-end statements page (Giving). Offer to open it.

HAND BACK
Say the year, the count, the total, who needs an acknowledgment, and what to fix before sending.

NEVER
- Never say statements were sent: you don't send them.
- Never estimate an amount, and never give one person's giving to anyone who didn't ask for that person's statement.
