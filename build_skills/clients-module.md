---
name: clients-module
description: designing a client, customer or member roster
triggers: [client, clients, customer, customers, member, members, roster, patient list, my people, who i work with, caseload, book of business, prospect, prospects]
---
A client roster is not a copy of the contacts list. Contacts already
hold name, email and phone — this module holds the RELATIONSHIP: where
someone is with you, and what happens next.

REQUIRED SHAPE
- A `contact_link` to the person. This is load-bearing. The name, email
  and phone live on the contact; duplicating them here means two records
  that disagree within a month, and the one in the module is the one
  nobody updates.
- A `select` for lifecycle, ordered the way people actually move:
  prospect, active, paused, former. Four to five options. This is the
  field the whole module is for.
- A `date` for last contact or next check-in — whichever the practitioner
  actually acts on. A roster with no date cannot answer "who have I not
  spoken to in a month", which is the question that makes it worth
  opening.

WHAT EARNS A FIELD
- Something the practitioner would act on differently if it changed.
  Referral source, rate, preferences, a note about their goal.
- NOT a second copy of contact details.
- NOT a free-text "status" alongside the select.

VIEWS
- views ["list","board"] with board_column on the lifecycle field. The
  board answers "how many prospects are sitting there" at a glance; the
  list is better for scanning names. Offer both.

LINK IT TO THE WORK
- If the business has a module for what it DOES for clients (projects,
  matters, programs, engagements), do not add a text field naming it
  here. Put the `module_ref` on THAT module pointing back at the work's
  own subject. A client has many projects; a project has one client, so
  the reference belongs on the project.

TRIGGERS
Every trigger object needs BOTH `type` and `action`. A trigger missing
either fails validation and the WHOLE proposal is rejected. Copy this
shape exactly:

    "triggers": [
      {"type": "field_change", "field": "status",
       "action": "draft_notification",
       "template": "{{title}} moved to {{status}}"}
    ]

`type` is one of new_entry, overdue, field_change. `action` is one of
draft_acknowledgment, draft_reminder, draft_notification. It is `type`,
never `event`.

- Put "former" (and "paused" if the practitioner treats it as dormant) in
  closed_statuses, so nobody is nudged about a client who has left.

DO NOT
- Do not create separate modules for prospects and clients. One select.
- Do not put clinical, diagnostic or treatment fields on a roster. Those
  belong to the restricted-modules surface, and for several verticals
  they are out of scope entirely.
