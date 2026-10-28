---
title: The coaches and consultants section of the site, /coaches and seven product pages, in Stained Glass Light
date: 2026-10-24
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-10-23, after the church section went live (#1565/#1566): "now do the same for the coaches and consultants page upgrade those"'
status: done
prs: [kmj-intake-server (this PR)]
migrations: []
left_undone:
  - "This is a new feature, so it takes one of the two Build slots on Plan (Kevin's click)"
  - "The coach canvas (claude.ai/artifact/GAZfSKBWVfAuNoa5DS1mgV) is private until Kevin shares it"
  - "Its own domain later, the same path-prefix change the church section needs"
decisions:
  - "On when COACH_SITE is unset, like CHURCH_SITE since #1566: 'do the same' covers reaching it from mysolutionist.app now. COACH_SITE=off is the rollback: /coaches and /consultants go back to the #1546 coaches edition and /coaches/<page> to the catch-all"
  - "/consultants serves the same overview; its canonical link is /coaches, so search engines see one page"
  - "coach_site.py reuses church_site's _plan_tokens, _trial_tokens and _founder_strip, so both sections read the same dials as the main site and checkout"
  - "The plan cards are pinned to feature_gates by test_the_plan_cards_match_the_gates: moving a feature between plans fails the test until the card moves too"
  - "Only claims backed by origin/main. Left out: a client login area, video links on bookings, client self-reschedule, automatic session briefs and follow-ups (session_agent runs when Chief is asked, so the copy says 'ask'), Chief sending documents for signature, LinkedIn/Threads/Pinterest posting, quarterly estimated taxes"
  - "Online signing is real (docuseal_router mounted; DOCUSEAL_* set on Railway), so the Proposals page says clients sign from a link. chief_contract_actions' 'no e-signature provider' docstring is out of date"
  - "Deposits and the no-show fee stay: APPLY-2026-07-31-barber-money.sql is not in docs/MIGRATIONS.md, but a read-only query on 10-24 found offerings.requires_deposit and no_show_fee_cents in production"
  - "Sample invoices use the real number format, INV-<year>-<3 digits> (chief_of_staff._next_invoice_number). Every weekday and date pair on the pages matches the 2026 calendar"
  - "Same pass on the church overview: 'Prices for churches and ministries , in US dollars' showed a stray space (a flex row with bare text); the text is now one span"
related: [2026-10-23-church-site.md, 2026-10-23-church-site-on-and-linked.md]
---
The church section's treatment, for coaches and consultants. Each part of a practice gets a glass tile and its own colour, and that colour lights its page: Bookings blue, Clients teal, Proposals and Contracts violet, Billing and Time green, Courses and Classes orange, Marketing and Website pink, Office and Books slate. Chief is the character on every page, and the devices stand still.

Pages: /coaches (overview; /consultants serves it too), plus /coaches/bookings, /clients, /proposals-and-contracts, /billing-and-time, /courses-and-classes, /marketing-and-website and /office-and-books. The sample practice is Reyes Coaching (Dana Reyes), with the same clients, invoices and numbers on every page. Every product claim was checked against the module behind it before it was drawn. Examples:
- booking series, outside calendars and the deposit math: booking_series, outside_calendar, payments_core;
- contract drafts and the agreement library: contract_agent, doc_templates;
- signing: docuseal_router;
- invoices, pay links, retainers and time: handle_create_invoice, customer_balances, billable_time;
- the classroom and live room: academy_join, academy_live_router, academy_class_sum;
- the marketing week and clips: business_marketing_planner, clip_finder;
- the close and 1099s: bookkeeping_close, form_1099.

`coach_site.py` renders a page from `coach_site/*.html`. `public_site.py` changes:
- /coaches and /consultants serve the overview while COACH_SITE is on.
- A new /coaches/{slug} route, ahead of the catch-all, serves the seven product pages.
- The sitemap lists those pages.

Every page's header has the Products menu of all eight pages.

Checked:
- `__tests__/test_coach_site.py`, 19 tests: tokens, the voice, links and anchors, the Products menu, the dials, trial wording, the founding seat, plan cards against feature_gates, routes on and off, /consultants' canonical link, the sitemap, and the billing script under `node --check`.
- With the church, brand-voice, news, Love City, findability and public-site URL test files: 139 passed.
- The rendered templates screenshotted at 1440 and 390 in headless Chromium, the Products menu open included.
