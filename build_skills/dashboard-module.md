---
name: dashboard-module
description: designing a log whose front page shows what it adds up to
triggers: [log, logs, logging, expense, expenses, spending, spend, spent, income, sales, revenue, receipts, mileage, miles, hours, workouts, workout, meals, habit, habits, journal, entries, totals, total, per month, each month, monthly, weekly, this month, how much, where the money goes, where it goes, breakdown, at a glance, overview, dashboard, summary, add up, adds up]
---
A log is rows that pile up; a dashboard is what they mean. The practitioner
does not open an expense log to read expenses — they open it to see how
much, where it went, and whether it is climbing. Design the front page for
that, then the rows.

THE ARCHETYPE
- Use archetype "composed_dashboard". You choose the blocks; the surface
  draws them. Do not fall back to fallback_generic for anything they log
  and want totalled, trended or broken down.
- If ONE number chases a goal per person (a score, a weight, visits toward a
  reward), that is progress_tracker instead. A budget is a dashboard
  progress block, not a tracker.

THE ROWS
- WHEN: a `date` for when it happened ("spent_on", "worked_on", "sold_on").
  Point archetype_params.date_field at it. Every block that says "this
  month" reads it.
- HOW MUCH: a `currency` for money, a `number` for anything else (minutes,
  miles, reps). Never text — "$40" as a string does not add.
- WHAT KIND: a `select` with the real categories, five to eight options,
  ending in "Other". This is what the breakdown block draws.
- WHO, when rows belong to a person: `contact_link`.
- A `textarea` for notes, a `file` for the receipt or photo when they keep
  one.

THE FRONT PAGE (archetype_params.blocks, 2 to 8, in order)
- Lead with the number they open the page for: one or two "stat" blocks
  ("Spent this month", "Hours this week").
- Then the shape of it: a "series" (by month or week) when the question is
  "is it going up", a "breakdown" by the select when the question is "where
  does it go". Both when the intake asks both.
- A "progress" block only when there is a real limit or goal (a monthly
  budget: direction "down"; a sales target: direction "up").
- "recent" with the three or four fields that identify a row. "upcoming"
  only when rows have a future date that matters (renewals, due dates).
- "notes" only when the notes are the point (a journal), not on an expense
  log.
- Every block's field must exist in schema.fields and be the type the block
  draws. Give each block a short label in the practitioner's words.

A log rarely needs a trigger; add `overdue` only when rows carry a due
date. Every trigger object needs BOTH `type` and `action` or the WHOLE
proposal is rejected. Copy this shape exactly:

    "triggers": [
      {"type": "overdue", "field": "due_on",
       "action": "draft_reminder",
       "template": "{{title}} is {{days_overdue}} days overdue"}
    ]

HOW IT FEELS
- empty_line is the first entry starting the count: "Log the first expense
  and the month starts adding up.", "First workout goes here."
- tone "precise" for money, "warm" for habits and health, "calm" otherwise.

EXAMPLE (an expense log)
  fields: vendor (text, required), amount (currency, required), spent_on
    (date, required), category (select), receipt (file), notes (textarea)
  archetype_params: {"blocks":[
    {"kind":"stat","agg":"sum","field":"amount","window":"month","label":"Spent this month"},
    {"kind":"stat","agg":"count","window":"month","label":"Expenses this month"},
    {"kind":"series","field":"amount","agg":"sum","bucket":"month","label":"By month"},
    {"kind":"breakdown","field":"category","agg":"sum","fields":["amount"],"label":"Where it goes"},
    {"kind":"recent","limit":6,"fields":["spent_on","vendor","category","amount"]}],
   "date_field":"spent_on","title_field":"vendor","item_noun":"Expense"}
