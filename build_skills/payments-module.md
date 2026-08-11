---
name: payments-module
description: designing a payments, invoicing or getting-paid tracker
triggers: [payment, payments, invoice, invoices, invoicing, billing, bill, paid, unpaid, owe, owes, owed, owing, money, deposit, deposits, retainer, fee, fees, get paid, getting paid, outstanding, balance, receipt, receipts]
---
A payments module answers one question the practitioner asks constantly:
what am I owed, and by whom. Build it so that question is answerable
without a spreadsheet.

REQUIRED SHAPE
- The amount is a `currency` field, never `text` and never `number`.
  Currency stores a real number and renders formatted, so a column of
  amounts can be sorted and later totalled. "$1,200" typed into a text
  field is a string that sorts alphabetically and adds up to nothing.
- A `contact_link` for who owes it. A typed name cannot be chased.
- A `date` for when it is due — not when it was created. "Overdue" is
  meaningless without a due date.
- A `select` for state, in the order money actually moves:
  draft, sent, paid, overdue. Include `overdue` as a real option even
  though a trigger can compute it; the practitioner filters on it.

LINK IT TO THE WORK — this is the point
- If the business has a module for the WORK (matters, projects, jobs,
  engagements, courses), add a `module_ref` field pointing at it:
      {"name":"matter","type":"module_ref","label":"Matter",
       "module_slug":"matters"}
  Never a text field holding the job's name. With text, "what is unbilled
  on the Nakamura matter" cannot be answered, renaming the matter orphans
  every payment, and a typo breaks the link silently. This one field is
  the difference between a payment list and a books.

TRIGGERS
Every trigger object needs BOTH `type` and `action`. A trigger missing
either fails validation and the WHOLE proposal is rejected. Copy this
shape exactly:

    "triggers": [
      {"type": "overdue", "field": "due_date",
       "action": "draft_reminder",
       "template": "{{title}} is {{days_overdue}} days overdue"}
    ]

`type` is one of new_entry, overdue, field_change. `action` is one of
draft_acknowledgment, draft_reminder, draft_notification. It is `type`,
never `event`.

- closed_statuses MUST include every settled state (paid, and refunded or
  written_off if present). Miss one and the practitioner is chased about
  money they have already received — the fastest way to make them turn
  the reminders off entirely.

DO NOT
- Do not build separate modules for paid and unpaid. That is one select.
- Do not add a "customer name" text field next to the contact_link.
- Do not mark an amount field customer_facing on a customer form unless
  the customer is genuinely entering it (a tip, a pledge). What they owe
  is something you tell them, not something they type.
