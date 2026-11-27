---
title: The website form door's bot checks (honeypot, signed token, shared limit)
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'M-5 step 1, relayed by KAI: F4 / rank 6, a server honeypot, the signed render-time token, and the shared rate_limit.allow_strict on contact-submit, in place of the per-replica dict'
status: in progress
prs: [kmj-intake-server#2101]
migrations: []
left_undone: ['after a week of ''[contact-submit] no form token'' log lines, decide whether a missing token becomes a Needs-a-look signal (inbound_risk)', 'a bot bin (kept 7 days) was in the proposal; not built: bots are logged, not stored']
decisions: ['a bot is answered {ok: true} and nothing is read, stored, alerted or mailed', 'a missing or stale token never stops a person: frozen composed-site scripts, embeds and old tabs send none', 'the token rides on every served site page through a fetch wrapper, so no site has to be rebuilt', 'site_contact is 10 a minute per address, shared, because a church''s Sunday QR cards can share one wifi address', 'review of #2101: `website` is a honeypot only on the church cards (connect_card, prayer_request); a business form may ask for a real website', 'review of #2101: the page script adds the token only to this church''s own door, and another church''s token counts as none, never a bot (the token carries the church''s first 8 characters in clear to tell them apart)', 'review of #2101: the door limit is per church and address, 30 a minute, shared and fail-open (rate_limit.allow_shared), plus one email 5 times in 10 minutes in-process; this replaces 10 a minute per address', 'the log lines name the form kind, so the no-token count can be read per kind', 'tests: every test starts with empty in-process rate windows (conftest _fresh_rate_windows)']
related: [2026-11-27-inactive-closes-follow-up.md]
---
`POST /sites/{id}/contact-submit` carries every church's connect card and
prayer request. Before this, its only server check was a dict in each
process (5 a minute per address per replica). The hidden "website" field
on Love City's forms was checked only in the visitor's browser.

`site_form_guard.py` adds three checks before anything is read:
- a server honeypot (`website`, `_hp`, `sol-hp`);
- a token signed when the page was served (`_t`, bound to the church),
  refused when it isn't ours or comes back in under 3 seconds;
- `rate_limit.allow_strict("site_contact", ip)`, shared across replicas.

The token is added by a small script that `_inject_brand_meta` puts on
every served site page. It sets `_t` on any JSON POST to contact-submit and
does nothing else. Switch: `SITE_FORM_GUARD=off`. Secret: `SITE_FORM_SECRET`,
else derived from the service key. The Needs-a-look worker's `inbound_risk`
check runs after these and never sees a bot.
