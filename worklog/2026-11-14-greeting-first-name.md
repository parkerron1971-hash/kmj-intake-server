---
title: Chief's greeting says the first name, so the short brief (CHIEF_BRIEF=lean) greets "Dre", not "Dre Carter"
date: 2026-11-14
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-14: "yes fix the name and switch today."'
status: shipped
prs: [kmj-intake-server#TBD]
migrations: []
left_undone:
  - "Found 11-13, not fixed (answer check): on some greeting turns the repair cuts the reply to a sentence or two, on both briefs"
  - "The FIRST WEEK (days 2-7) greeting is still not measured by any eval row"
decisions:
  - "The cause was the prompt's own line: tod_guidance said \"Start with 'Good morning, Dre Carter.'\" (the owner's whole practitioner_name), and the advisor-voice example said \"Good morning, {practitioner}.\" Both sat beside the FIRST NAME rule, and the model followed the literal line. Both now say the greeting name"
  - "greeting_name(): the first word, and a title keeps the name after it ('Pastor Kevin McCloud' -> 'Pastor Kevin', not 'Pastor')"
  - "The FIRST NAME rule now names the name ('Address the practitioner as Dre (their first name), never by the full name Dre Carter') and the launch step says 'Welcome them by first name (Dre)'"
  - "Everything changed is in the greeting clause of the uncached turn tail, so both briefs change the same way. _build_assistant_name_block (only when the practitioner named Chief) uses greeting_name too"
  - "The turn eval gains reply:first_name_only on the four day-one greetings"
related: [2026-11-13-lean-brief-greeting.md, 2026-11-03-chief-lean-brief.md]
---
On 11-13 the short brief greeted the barber "Good morning, Dre Carter"
most runs, although the tail says FIRST NAME only. The prompt itself told
it to: the time-of-day line was built from the owner's whole
practitioner_name ("Start with 'Good morning, Dre Carter.'"), and so was
the advisor-voice example. The greeting name is now the first name in
every greeting line, and the rule names it.

Live check (`chief_turn_eval --live --only <row>`, CI-shaped env, metered
in memory), the four day-one greetings x 3 runs on each brief:

| | short brief | full brief |
|---|---|---|
| barber (Dre Carter) | 3/3 pass, "Good morning, Dre" | 3/3 pass, "Good morning, Dre" |
| therapist (Maya Lin) | 3/3, "Maya" | 3/3, "Maya" |
| ministry (James Cole) | 3/3, "James" | 3/3, "James" |
| coach (Tasha Reed) | 3/3, "Tasha" | 3/3, "Tasha" |
| cost | $0.87 | $1.09 |

Every check passed on all 24, the new first_name_only and one_question
included. Test: `test_the_greeting_says_the_first_name[full|lean]` and
`test_a_greeting_name_keeps_a_title_with_the_name` in
`__tests__/test_chief_builds_it_live.py`, sabotage-checked: all three fail
on main's chief_prompt.py and pass here.
