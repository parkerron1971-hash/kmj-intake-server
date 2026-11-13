---
title: A church registers for texting as a church, with a /texts sign-up page
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-13, after the text-alert cost questions: "I need the text alert structure with twilio to be set for churches to have the ability to send text alerts", then "let''s finish setting up the text structure so that is done."'
status: shipped
prs: [kmj-intake-server#1818, solutionist-studio#1533, kmj-intake-server (church words in the owner's updates)]
migrations: []
left_undone:
  - "Going live is still gated on Twilio relabeling our primary profile 'ISV Reseller or Partner' (ticket #29903903, filed 2026-10-11; status unknown to this session), then TEXTING_REGISTRATION_OPEN naming the pilot church. TEXTING_REGISTRATION_OPEN is unset on kmj-intake-server (checked 11-13, names only)"
  - "Until a church is registered and approved, its announcements still go out on the platform's one campaign from its number, which Twilio's rules don't allow for words a church writes (error 30926). Plan step 5, moving everyone, is not done"
  - "Registration screen (solutionist-studio TextingRegistration.tsx): it says 'clients' and doesn't show the sign-up link yet. GET /texting/registration now returns pages.signup and signup_live for a church"
  - "The Move-in room has no texting item. A church only finds registration under Text, the gear, 'Text under your own name'"
  - "Consent scope to decide: the member app's 'Text me important news' yes ('only posts your pastors mark important') also counts for every announcement (sms_alerts.said_yes_to_texts reads all of a church's sms_consents)"
  - "A church website's connect card records no text consent (public_site records sms_consent only for non-church forms); /texts is the church's sign-up for now"
decisions:
  - "A fix, not a Build item: as it stood a church couldn't pass readiness without a booking page, and its campaign would describe bookings and offers it never sends, which is a rejection and two weeks lost"
  - "Church = church_follow_up.is_church (vertical 'ministry'). A church gets church_campaign_words (same keys, same Low Volume Mixed use case), church terms and privacy pages (no bookings, Home not Book), and readiness that asks for its sign-up page instead of a booking page. Businesses are unchanged"
  - "The opt-in reviewers can open: /texts on the church's own site, a plain no-script form (name, mobile, an unchecked box that's never required, terms and privacy links, a hidden field for bots). The message flow quotes the box word for word"
  - "/texts exists only for a church whose registration is sent. From then on a yes given there names the church itself, so it counts under its own registration (own_registration's `since` is the moment it was sent). Before that, a sign-up would have fallen before `since` and silently stopped counting at approval"
  - "POST /texting/signup/{biz}: the contact form's rate limit; the person found by number (lead_identity.find, strict) or added as a guest (status lead, source texts_signup); sms_consents source texts_page with time, trusted client address and browser; one confirming text (compose_outbound_body leads with the church's name), skipped if they already signed up there or said STOP. A failed text never undoes the yes. The redirect is relative and carries only a note key, never the name or number"
  - "The sign-up route is a deliberate public door like the contact form: recorded as (texting_registration, church_signup) in ownership_sweep.PUBLIC_BY_DESIGN with its reason; MAX_UNGUARDED_TOTAL 48 -> 49 and both allowlist caps 15 -> 16 in the same commit; the residual stays at zero"
  - "Someone who said STOP is told to text START: Twilio blocks texts to them on that service until they do, whatever our records say"
related: [2026-10-11-isv-step-1.md, 2026-10-11-isv-step-3.md, 2026-10-11-isv-step-4b.md, 2026-10-28-news-reach-the-rest.md]
---
Before building I read both repos' `worklog/`. The ISV entries (10-11) built
registration end to end for a booking business. News reach (10-28) waits on
a church being registered, and Love City has no registration. Nothing had made
registration fit a church.

`texting_registration.py`: `is_church`, `church_box`, `church_campaign_words`,
`campaign_words(church=)`, `terms_html`/`privacy_html(church=)`, `signup_html`,
readiness and overview for a church, `page_for(kind="signup", note=)`, and
`church_signup`. `public_site.py` serves `/texts` (never cached) and adds it to
`_ALWAYS_WINS_PATHS`.

Tests: `__tests__/test_texting_church.py` (23). 619 passed across the texting,
SMS, news-reach, announcement and church-texts files, and 470 across the files
that touch the site's paths and the booking/contact boxes.

Later the same day (Kevin: "go ahead and fix the wording"): the owner's
updates said a church "texts its clients" and that "your business is
verified". A church now gets CHURCH_UPDATES for those two, through one picker
(`update_words`, which `_tell_owner` uses for the app, the push and the
email), and the screen's step and readiness labels say church. Businesses keep
their words. Tests: 4 more in `test_texting_church.py`.
