---
title: An event's sign-up link for people without the church app (server)
date: 2026-11-22
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-22: "when the event is made there is no way for someone to sign up with a link if there don''t have the church app. can we fix this issue?", then "yes to both" on the mock https://claude.ai/artifact/HmdpXJJNgzKefxW5qoAF5e (its four picks), and earlier "yes to both" to an Events line on the Serving page and a field for an event''s helper time'
status: in review
prs: ["kmj-intake-server (this PR, the server)", "solutionist-studio (the office's link card, by-link sign-ups, the Serving page's Events column and Helpers serve about: after this merges)"]
migrations: []
left_undone:
  - "The office app (FE PR): the Sign-up link card on the event page and in the saved note (Copy, QR code, Make a new link), the by-link badge with That's someone on Members / Add to Members / Remove, the Serving page's Events column, and Helpers serve about writing _serve_minutes"
  - "Switch-on: EVENT_SIGNUP_LINKS defaults to owner (Kevin's own church); on for every church is its own call"
  - "Texts: no confirmation text; a phone typed on the page isn't consent to texts (spec 7, 9)"
decisions:
  - "Kevin's four picks as in the mock: every non-kids role by link (the public page still honours open: false), hours only once the office confirms, a page and an email to confirm, the Serving page's Events and helper time"
  - "No migration: the link is _link {n, at} on the event's data; the code is HMAC(derive_key('event-signup-link', church), entry|n) cut to 26 base32 characters, never stored. Reading the row gives the nonce, never the code; writing a nonce only makes a new link the server still hands only to office logins; the revision guard every office save carries stops a stale save bringing a voided link back"
  - "Every event's office link is the coded /e/<code>, public events too: a public event's own page (/events?event=<id>, now showing only that event) keeps the public page's rules, because entry ids are printed on the public list and open: false would otherwise mean nothing"
  - "Every way of not taking sign-ups (wrong code, past, archived, room off, sample church, switch closed) is one 404 page, the same bytes; the POST says the same words"
  - "The page is served before the site's offline and coming-soon checks, on the subdomain and the church's own domain; noindex (meta and header), Referrer-Policy strict-origin, no-store"
  - "Sign-ups by link carry sid, via link and the typed phone (E.164) or email; contact_id is never set from typed data. Confirm sets a person of this church; Add to Members goes through the roll's own add (a guest who found us at an event) behind the roll's gate"
  - "The email goes through church_event_signups._send_email (the church's sender) once, keyed evlink-{entry}-{sid}; Resend is a flat cost, nothing metered per send"
  - "church_serving.event_credits counts a link sign-up only with confirmed true; My serving gains event_minutes (the Serving page had events and event_minutes already)"
related: [2026-11-21-event-volunteers.md, 2026-10-27-church-event-signups.md]
---
Before building I read both repos' event-volunteers logs (the server's
`2026-11-21-event-volunteers.md` and `-chief.md`, the app's S4a-c, switch-on and
no-teams-hint logs) and `2026-10-27-church-event-signups.md`. They left "the
Serving page has no Events line" and "no field for an event's helper minutes";
the server half of both is here (My serving's `event_minutes`), the office half
is the FE PR. Open PRs: #2020 touches `kmj_intake_automation.py` (router lines
only); nothing else overlaps.

New: `event_signup_links.py` (the switch, the code, the page, the public
sign-up and six office routes), `docs/EVENT_SIGNUP_LINKS.md` (the spec),
`__tests__/test_event_signup_links.py`. Changed: `public_site.py` (/e/<code> on
both hosts), `events_rsvp_router.py` (one event's own page), `church_serving.py`
(confirmed link sign-ups count; My serving's event minutes),
`kmj_intake_automation.py`, `.env.example`, `__tests__/test_edge_cache_headers.py`.

Each rule was broken once on purpose and its test went red (38 sabotages,
listed in the PR).
