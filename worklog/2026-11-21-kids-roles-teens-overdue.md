---
title: Teens as junior helpers on an event's kids roles, and The week flags a check that ran out
date: 2026-11-21
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-21, "yes and yes" to: "Should teens be allowed as junior helpers on kids roles? Right now anyone under 18 is refused." and "Should The week flag volunteers whose background check has expired? Today it only flags people with no check on file."'
status: in review
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "The member app's refusal words for a child under 13 are still \"Needs a background check. Ask the office.\" (unchanged; the office's picture says \"Under 13\")"
  - "The office's picture shows a junior helper like anyone cleared (no chip); a \"Junior helper\" chip would need a frontend change"
decisions:
  - "Teens are 13 to 17. The age comes from the birthdate checks_of already reads for `teen`, carried on its row as `age`; church_serving.kids_status reads it (junior / child), and cleared lets in KIDS_ROLE_OK (ok, due, junior). No new read"
  - "An adult's overdue check is still refused for an event's kids role"
  - "The week: an overdue check is the same state, cant_serve_kids, as none on record, so every reader of a row's state (the office chip and tone, the counts, Look at first, My department's office line, Chief's serving_week) works unchanged; a new row field check_status says which, and the words are its own (\"Check overdue\"). No frontend change: the office page shows state_words and Look at first verbatim"
  - "No switch changes: event kids roles under EVENT_VOLUNTEERS; The week's flag under CHURCH_WEEK (and church_serving's own rule for who may read checks)"
related: [2026-11-21-event-volunteers.md, 2026-11-18-church-schedule.md]
---
Before building I read both repos' work logs: the backend's
`2026-11-21-event-volunteers.md` left these two questions for Kevin (S3 kept the
stricter rule until he answered), and nothing in the frontend's logs touches them.
No open PR touched these files.

`church_serving.py`: `checks_of` carries `age`; `kids_status`, `JUNIOR_AGE`,
`KIDS_ROLE_OK`; `cleared` reads them. `event_volunteers.py`: the picture's words
("Under 13"; a junior helper is `checked`). `church_week.py`: `FLAGGED_CHECKS`,
`check_status`, "Check overdue" and its Look at first line. The specs:
`docs/EVENT_VOLUNTEERS.md` 6.10 and section 11 ("Kevin's two calls"),
`docs/CHURCH_SCHEDULE.md` 8.3 and 8.4. Each new rule was broken once on purpose and
its tests went red (the PR lists them).
