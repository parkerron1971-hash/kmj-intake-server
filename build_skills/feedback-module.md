---
name: feedback-module
description: designing a feedback, review or satisfaction tracker
triggers: [feedback, review, reviews, rating, ratings, testimonial, testimonials, satisfaction, survey, nps, complaint, complaints]
---
A feedback module exists to be acted on, not archived. Every field should
help decide what to do next.

REQUIRED SHAPE
- A `rating` field for the score. It stores an integer 1-5 and renders as
  stars, so it sorts and filters properly — a text field holding "4/5" or
  "great" does neither.
- A `textarea` for what they actually said. Their words are the reusable
  asset; a score alone cannot become a testimonial.
- A `contact_link` for who said it, so praise can be turned into a
  testimonial request and a complaint into a follow-up.
- A `date` for when it was received.

ACTING ON IT
- A `select` for what happens next — new, responded, resolved,
  published — with the finished states in closed_statuses. Feedback with
  no handling state is a pile, not a process.
- `new_entry` trigger so a low score is seen the day it lands rather than
  at the end of the month.

PERMISSION BEFORE PUBLICATION
- If the practitioner intends to show reviews publicly, add a `checkbox`
  for consent to publish and leave it unchecked by default. Never mark a
  feedback field customer_facing in order to display it — consent is a
  decision the person giving feedback makes, not a rendering flag.

DO NOT
- Do not use `number` for the score. `rating` is the type that renders
  stars and constrains the scale to 1-5; a raw number invites 7/10 and 94%
  in the same column.
- Do not build separate modules for good and bad feedback. One module with
  a rating field sorts both.
