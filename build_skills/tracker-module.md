---
name: tracker-module
description: designing a progress tracker — a number measured over time against a goal
triggers: [tracker, track, progress, score, scores, credit, weight, weigh, savings, balance, goal, goals, target, milestone, milestones, streak, streaks, over time, month by month, week by week, toward, towards, reward, rewards, loyalty, punch card, visits, attendance, improve, improvement, trend, chart, graph]
---
A progress tracker answers three questions the moment it opens: how close
is each person to the goal, which way are they moving, and who just
crossed the line. Design for those; a table of readings answers none of
them.

THE ARCHETYPE
- Use archetype "progress_tracker". It draws the chart, the goal line, the
  milestone marks and the "reached" state itself. A generic module with a
  number column is the failure this archetype exists to replace — do not
  fall back to fallback_generic for anything that is a number chasing a
  goal.
- Pick the mode. "reading" when each row is a measurement (score, weight,
  balance, blood pressure, revenue). "count" when each row is one unit
  toward a total (a visit, a class, a donation) — the reward card.

THE THREE FIELDS THAT MAKE IT WORK
- WHO: a `contact_link`, first in the schema, named for the person
  ("client", "member", "student"). Point `subject_field` at it. Text here
  breaks the grouping — "J. Smith" and "John Smith" become two people.
- THE NUMBER (reading mode): a `number` (or `currency` for money). Point
  `value_field` at it. Never text, never select — "720" as a string does
  not chart and "improving" is not a reading.
- WHEN: a `date` named for the act ("pulled_on", "weighed_on",
  "visited_on"). Point `date_field` at it. Without it the chart orders by
  entry time, which is wrong the first time someone backfills history.

THE GOAL
- One "target" for everyone (720, 7 visits, 10000) OR a per-person
  `target_field` (a `number` field on the row) when each client has their
  own — never both.
- "direction" is the decision that decides what "reached" means: "up"
  for a score, balance or count; "down" for weight, debt or days to close.
  Getting it wrong congratulates the wrong movement.
- "milestones" are the intermediate marks worth naming, in order, in the
  goal's units. Three is plenty.
- "unit" is what the number is ("pts", "lbs", "$", "visits").

WHAT NOT TO ADD
- No "status" / "progress" / "on track" `select`. The state is computed
  from the numbers; a stored copy goes stale the next reading and disagrees
  with the chart.
- No `board` view — there is nothing to group by. views ["list"] and the
  archetype does the rest. `summary` is fine when there is a `currency`.
- No separate module per client. One tracker, one row per reading, the
  contact link tells them apart.

THE ALERT
- Add a `target_reached` trigger so the practitioner is told the day
  someone crosses the goal — that moment is the whole point of tracking.
  It needs no `field`; it reads the archetype params. Both `type` and
  `action` are required or the WHOLE proposal is rejected:

    "triggers": [
      {"type": "target_reached", "action": "draft_notification",
       "template": "Goal reached"}
    ]

- In count mode with a reward, add a `checkbox` named "redeemed"; the
  count restarts after the row where it is ticked. Do NOT add a workflow
  to "reset the count" — the archetype does that.

EXAMPLE (reading mode, a credit-repair consultant)
  archetype_params: {"mode":"reading","subject_field":"client",
    "value_field":"score","date_field":"pulled_on","target":720,
    "direction":"up","milestones":[620,680,720],"unit":"pts",
    "item_noun":"Reading","subject_noun":"Client"}
  fields: client (contact_link, required), score (number, required),
    pulled_on (date, required), bureau (select), notes (textarea)
