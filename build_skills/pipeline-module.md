---
name: pipeline-module
description: designing a stage-based pipeline or tracker
triggers: [pipeline, stages, stage, kanban, board, leads, lead, prospects, deals, applications, matters, cases, projects, tickets]
---
A pipeline module answers "where is everything, and what is stuck". Its
whole value is the stage field; design that first and the rest follows.

THE STAGE FIELD
- One `select`, named `status` or `stage`. It drives the board, so it must
  exist before a board view is worth adding.
- Between four and six options. Three is a list with extra clicks; eight
  columns do not fit on a laptop and never fit on a phone.
- Order the options as work actually flows, first to last. The board renders
  columns in option order, so a scrambled list produces a board that reads
  backwards.
- End with an explicit terminal state (won/lost, closed, delivered). Without
  one, nothing ever leaves the board and the oldest column grows forever.

VIEWS
- views ['list','board'], default_view 'board', board_column set to the
  stage field. The board is the point; opening on the list hides it.
- board_column MUST name a select field that exists. If there is no stage
  field, do not ask for a board — the module will refuse to render.

MOVEMENT, NOT JUST STATE
- Add a `date` field for when the item last moved, and a `field_change`
  trigger on the stage field. A pipeline without movement data cannot
  answer "what is stuck", which is the question it exists for.
- Put every terminal option in closed_statuses so finished work stops
  being chased.

DO NOT
- Do not use a checkbox for done. A checkbox cannot show a board and
  collapses the middle of the process, which is the part worth seeing.
- Do not create separate modules per stage. Stages are values of one field.
