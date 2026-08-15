---
name: grants-module
description: designing a grant pipeline for a nonprofit — funders, deadlines, awards and reporting
triggers: [grant, grants, grantmaker, funder, funders, foundation, foundations, proposal, proposals, loi, rfp, rfa, nofo, notice_of_funding, award, awards, philanthropy]
---
A grant module is a pipeline with two things a normal pipeline does not
have: a deadline that cannot move, and a life AFTER the money arrives.
Design both or it becomes a list of hopes.

THE SHAPE
- Six stages, in this order: researching, applied, awarded, reporting,
  declined, closed. Match these ids if the practitioner has no strong
  preference — the provisioned Grants module uses them, so a hand-built
  one that agrees stays readable by the same surfaces.
- Declined and closed are terminal. Reporting is NOT terminal. An awarded
  grant with reports still owed is the most live work in the pipeline;
  marking it done hides the obligations the module exists to track.
- Put the two terminal options in closed_statuses. Reporting must never
  go in closed_statuses.

THE FIELDS THAT EARN THEIR PLACE
- funder — `text`, required. This is the title: who the money comes from
  is how a practitioner recognises the row.
- amount — `currency`, never `text`. A text amount cannot sort or total,
  and the summary view totals the first `currency` field. "How much have
  we asked for this year" is the second question anyone asks.
- deadline — `date`. The submission date, then the report date. One field,
  reused as the stage moves, because the question is always "what is next
  owed on this grant".
- stage — `select`, the six above.
- program — `module_ref` pointing at the Programs module, never free text.
  A restricted award is restricted TO something, and a renamed program
  must not orphan its grants.
- restricted — `checkbox`. Whether the award may only be spent on that
  program. A legal distinction, not a preference.

DEADLINES ARE THE WHOLE POINT
- Always add an `overdue` trigger on the deadline field with
  `draft_reminder`. A grant pipeline with no overdue trigger is a
  spreadsheet.
- Federal reporting runs on fixed clocks — interim reports commonly fall
  due within 30 days of a period end and finals within 120 days — so the
  reminder matters as much after the award as before it.

    "triggers": [
      {"type": "overdue", "field": "deadline",
       "action": "draft_reminder",
       "template": "{{funder}} — {{deadline}} has passed"}
    ]

Every trigger needs BOTH `type` and `action`; a trigger missing either
rejects the WHOLE proposal. `type` is one of `new_entry`, `overdue`,
`field_change` — never `event`.

VIEWS
- views ['list','board','calendar'], default_view 'board', board_column
  the stage field, calendar_field the deadline field. The `calendar` view
  earns its place here specifically because deadlines are the risk.

WHAT NOT TO PROMISE
- Do NOT design fields that imply the module writes the application. It
  tracks grants; it does not draft them. A "proposal text" area invites
  someone to paste a narrative into a tracker and believe it is filed.
- Do NOT invent outcome or impact numbers as defaults or examples.
  Reported figures go into a grant report under the signature of whoever
  certifies it, so a fabricated number there is a legal exposure, not a
  formatting problem.
- Do not add an AI draft field or trigger. Funders increasingly restrict
  AI-generated application content and several require disclosure;
  nothing here should imply the platform produced the narrative.

DO NOT
- Do not split federal and foundation grants into two modules. They are
  one pipeline with different paperwork; a funder_type `select`
  (foundation, federal, state, corporate, individual) carries the
  difference in one field.
- Do not merge the requested and awarded amounts IF the practitioner
  tracks both — awards frequently differ from asks. Add a second
  `currency` field only when they say they need it; otherwise one amount
  field is less to maintain.
- Do not use a `checkbox` for submitted or not. It collapses six stages
  into two and loses the reporting half entirely.
