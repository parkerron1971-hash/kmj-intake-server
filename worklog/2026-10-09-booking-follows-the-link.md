---
title: A tap on a post's link, followed to the booking and its payment
date: 2026-10-09
agent: Claude Code (Claude Opus 5.5)
asked: "work on this in order (Kevin, 2026-10-09; next per the approved plan: one record of everything that goes out, results that follow a tap to a booking and a payment)"
status: done
prs: [kmj-intake-server#1362, solutionist-studio#1188]
migrations: []
left_undone: ["tracked links/codes on texts, emails and offers (campaign touches carry plain text today; marketing_link_clicks is keyed to marketing_posts)", "one calendar for posts, texts, emails and offers for any month (the desk's Calendar reads two weeks of posts only)", "site forms on a business's own site still send no campaign tags, so form leads stay a floor", "Stripe metadata carries no source: a payment is traced through its booking row, not on its own"]
decisions: ["a booking keeps the server's reading of the visit's campaign tags in module_entries.data.attribution (lead_attribution's whitelist; the page address wins over the widget's copy; what the form sent under that key is dropped)", "the hosted /book page carries the page-view beacon, so its visits count and the tab keeps first-touch tags (sol_c) for the widget to send", "results count bookings per post and paid_cents = data.amount_charged_cents once paid_at is set (a deposit counts as what was paid); unread is None and named, never 0", "a booking weighs 8 in a play's score (a lead 4, a look 1)", "static/embed.js rebuilt from solutionist-studio; no visitor-widget source had changed since the last bundle (#562) apart from this"]
related: [2026-10-09-desk-several-pictures.md, 2026-10-08-marketing-open-to-all.md]
---
The Reach plan's step 1, first part. Before: /book had no beacon, the
booking widget posted cross-origin with no attribution (the Referer is
only the origin), and only a new contact kept attribution, never the
booking, so a post's results stopped at leads. Now the trail runs click →
visit (/book counted) → booking (data.attribution) → payment (paid_at and
amount_charged_cents on that booking), and Grow → Marketing → Results shows
bookings and "paid online" per post (solutionist-studio#1188).

Mapped first by a read-only survey of sends, links and attribution (texts:
campaign_sends, sms_messages; emails: events only; coupons: Stripe only,
no source on a redemption; desk calendar: two weeks of marketing_posts).
That map is what the rest of step 1 builds on.
