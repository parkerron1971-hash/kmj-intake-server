---
title: What a church's payer receives says bill, and "the latest invoice" is never a gift
date: 2026-11-17
agent: Claude Code (Claude Fable 5.2)
asked: 'Kevin, 2026-11-17: "yes to the other plans as well" (the email a bill''s recipient gets still said Invoice)'
status: in review
prs: []
migrations: []
left_undone:
  - "Pay links already made keep the name 'Invoice …' on Stripe's page: only new links are named Bill (renaming would change live Stripe objects)."
  - "Chief's own result lines to the office ('Invoice INV-… sent by text', 'Invoice … voided') and the 'opened Invoice …' notification still say invoice: the answer checks match on the word, and no eval was run."
  - "The server's word list is unchanged, so in chat Chief still says invoice for what a church sends (it uses bills for what the church owes)."
  - "A reminder the model writes is not deterministic: the church-only menu block tells Chief to say bill to the payer. Not tested against a real model."
decisions:
  - "The words are chosen in one place, bill_words.py; only the word changes. The number and its INV- prefix, the amounts, dates, line items and Stripe metadata are untouched."
  - "A gift (is_gift, or a GIVE- number) keeps its wording even at a church: a gift receipt is not a bill."
  - "'latest' in send_invoice, mark_invoice_paid and the text send now skips gifts for everyone: a church's gifts are paid invoices, and the newest row at a church is almost always one."
related: []
---
For a church: the email Chief sends (subject, the label over the number, the
opening line, the line over the pay buttons), the text's first line, the name
on Stripe's pay page and receipt, and the overdue reminder say bill. A
business's wording is held to the letter by `__tests__/test_bill_words.py`
(16 tests), which drives each path as a coach against the old text.

The app's half (the email the app itself sends, the PDF, the share title) is
solutionist-studio's.
