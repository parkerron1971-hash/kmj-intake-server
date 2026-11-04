---
title: A church's texts are counted by 160-character part, the way Twilio bills them
date: 2026-11-03
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-03, after the measured Twilio bill showed extra texts losing money (1.26 cents a part, 1.93 parts a message, so about 2.43 cents against the 2 cents charged): count what Twilio bills. "go on all"'
status: shipped
prs: [kmj-intake-server (this PR), solutionist-studio (the meter and the announcement line)]
migrations: []
left_undone:
  - "What's New: the church plans entry is being updated in a separate frontend PR (the price change and this), not here"
  - "Inbound texts and Twilio's STOP confirmations are still not recorded (sms_metering's open item); they don't count toward a church's texts"
decisions:
  - "A text is one 160-character part (153 per part once split; 70 / 67 with an emoji or another character outside GSM-7). The plan numbers (500 / 1,500 / 3,000 / 8,000) and the $20 per 1,000 didn't change, only the unit"
  - "The parts are each api_usage row's input_tokens (sms_usage.usage_row writes twilio_sms.segments of the body as it left). A row with 0 or no number counts as 1"
  - "church_texts.counted reads every row (sb_get_all_as_service, key id, strict) and sums the parts; any failed or partial page is None, never a short count or 0. counted_texts stays (parts) for anything that wants only the number"
  - "summary() keeps every field the app reads and adds `messages` (how many messages the texts came from). `used`, `left`, `extra`, `pct` and the bill are all in parts"
  - "The heads-up says what a text is (church_texts.UNIT_LINE) and, when known, how many messages the texts came from; its data carries `messages`. The 80% title says 'used', not 'sent'"
  - "The invoice item says 'Counted by 160-character part: N messages went out as M texts.', with messages and unit in its metadata. A claim recorded before this (no messages) keeps the old wording, since it was counted by message"
  - "Public words, once each: the 'Good to know' line under the /churches plan cards and the FAQ's church answer (which now also lists each plan's texts a month). Nothing changes while PLAN_CHURCH_OFFERED is off"
related: [2026-11-03-church-text-allowance.md, 2026-11-03-sms-metering.md, 2026-11-03-church-site-pricing-by-size.md, 2026-11-03-church-plans-by-size.md]
---
Before building I read `worklog/` in both repos. `church-text-allowance` built
the count, heads-up and bill, counting messages ("Texts, not segments");
`sms-metering` put the billed segments on every row, which is what this sums.
In the frontend, `2026-11-03-church-plan-extras` drew the meter and the
announcement line on the old unit ("counts as 1 text each"); its frontend
follow-up ships with this.

`church_texts.py` (`parts_of`, `counted`, `summary`'s `messages`, the notice,
`item_description`), `church_site._offer_line`, `marketing_pages._church_texts_in_words`,
and the docstrings in `sms_usage.py` and `pricing_config.py` that said the
allowance counted messages.

Tests: `__tests__/test_church_texts.py` (93: parts summed across three pages,
a failed first, second or third page is None, 0/None rows count 1, a 3-part
announcement to 148 plus 10 short texts is 454, a bill from parts, the
invoice line both ways) and
`__tests__/test_church_site.py` (the unit said once under the cards, never on
the product pages, nowhere with the switch off, and in the FAQ). 341 passed
across the church, SMS, plans, marketing, brand voice and FAQ files.
