---
name: program-module
description: designing a program, course, class or offering people enrol in
triggers: [program, programs, course, courses, class, classes, cohort, cohorts, curriculum, enrol, enroll, enrolment, enrollment, students, intake group, workshop series, membership tier]
---
A program is a CONTAINER other things point at — sessions belong to it,
enrolments belong to it, payments belong to it. Design the container
first and keep it thin; the volume lives in the modules that reference
it.

REQUIRED SHAPE
- A `text` title, required. This is what every referencing dropdown shows,
  so put it first — a `module_ref` labels its options from the target's
  first field.
- A `select` for state: planned, open, running, closed. The practitioner
  needs to know what is currently taking enrolments.
- `date` fields for start and end. A program without dates cannot be
  sorted into "what is running now".
- A `currency` price field IF the program is sold at a single fixed
  price. If pricing varies, leave it off and let the offering carry it —
  two places holding a price is one place holding a stale one.

THE CONTAINER RULE — this is the whole design
- Sessions, enrolments and payments each get a `module_ref` pointing AT
  the program:
      {"name":"program","type":"module_ref","label":"Program",
       "module_slug":"programs"}
- The program does NOT list its members. A roster field on the container
  goes stale the moment someone joins or leaves, and it cannot be
  filtered or counted. The reference always lives on the MANY side.
- So: do not add "students", "attendees" or "sessions" fields here.

CAPACITY
- If enrolment is capped, a `number` for capacity is worth having — but
  do not add a "spaces left" field. A stored count drifts from the truth
  every time an enrolment is added or removed anywhere else.

TRIGGERS
Every trigger object needs BOTH `type` and `action`. A trigger missing
either fails validation and the WHOLE proposal is rejected. Copy this
shape exactly:

    "triggers": [
      {"type": "new_entry", "action": "draft_acknowledgment",
       "template": "New program: {{title}}"}
    ]

`type` is one of new_entry, overdue, field_change. `action` is one of
draft_acknowledgment, draft_reminder, draft_notification. It is `type`,
never `event`.

- closed_statuses gets "closed", so a finished program stops appearing in
  the practitioner's live work.

DO NOT
- Do not build one module per cohort. Cohorts are rows.
- Do not duplicate the session schedule here; that is the sessions module,
  pointing back with a module_ref.
