---
name: booking-module
description: designing an appointment or booking module
triggers: [appointment, appointments, booking, bookings, schedule, scheduling, calendar, session, sessions, consultation, consultations]
---
A booking module is the practitioner's calendar, not a list of names. Design
it so the next seven days can be read at a glance.

REQUIRED SHAPE
- One `date` field for when the appointment happens. Name it for the event
  (`appointment_at`, `session_at`), never `date` — the module already has a
  created_at and two date columns read as ambiguous.
- A `select` for status. Give it the full lifecycle the practitioner
  actually works: scheduled, confirmed, completed, no_show, cancelled.
  `no_show` matters — it is the field a practitioner uses to decide whether
  to keep taking someone's bookings.
- An `offering_ref` for what is being booked, constrained to
  offering_categories ['service','session']. Never a free-text service name:
  the price and duration then live in two places and drift.
- A `contact_link` for who booked. Not a text name — a text name cannot be
  followed up, invoiced, or counted.

DEFAULTS THAT EARN THEIR PLACE
- default_view 'list', sorted by the date field ascending. A booking module
  opens on "what is next", not "what was entered last".
- Add the board view only if status has been included, with board_column set
  to it. A board with no status column will not render at all.

TRIGGERS
- `overdue` on the date field, with closed_statuses covering every finished
  state (completed, cancelled, no_show). Miss one and the practitioner is
  chased about appointments that already happened.
- `new_entry` for the confirmation the client expects.

DO NOT
- Do not add a price field. Pricing belongs to the offering, and a second
  copy is the one that goes stale.
- Do not add a duration field for the practitioner to type. It is read from
  the picked offering.
