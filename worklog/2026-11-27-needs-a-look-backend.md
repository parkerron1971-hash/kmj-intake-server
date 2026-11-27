---
title: "Needs a look: a risky website card is saved and marked, and nothing runs on its own until a person says it's real (backend)"
date: 2026-11-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Kevin, 2026-11-27 (through KAI), after the Sofia Marino / Julien Mercier connect cards: yes to every decision in kai/reviews/inbound-safety-proposal.md. Build "Needs a look" now; a held card is a contact with a held mark (badge in Members); the shared cross-church scam list with the two-church rule and salted hashes only; Turnstile later, only if bots show; the Haiku second opinion on mid-score cards, never on prayer; the member warning per church, offered by Chief. This session: the backend (ranks 2-4, the shared list, the second opinion, a switch per church)'
status: in progress
prs: [kmj-intake-server (this PR)]
migrations: [supabase/APPLY-2026-11-27-needs-a-look.sql (not applied)]
left_undone:
  - "Not merged: review on account 2 first, then Kevin. The APPLY file waits on Kevin; INBOUND_SAFETY defaults off (set watch for a week, then owner on a Thursday)"
  - "The front end (badge, queue, three buttons, undo, the prayer badge): another worker builds it from the contract in docs/INBOUND_SAFETY.md and the PR description"
  - "Other doors not wired: intake forms (/intake/submit and its Sonnet draft, F2 is the step-1 Fix's), booking, website chat, texts in, church mail (proposal §4.3, L6)"
  - "The member warning template (L7), offered by Chief per church, is not built"
  - "Not-a-guest and Scam contacts are not deleted after 30 days (L8); inbound_checks rows are not purged (reads filter by time)"
  - "W4's close_for_contact (#2097) is called once it exists; until it merges, inbound_hold closes follow-ups with its own loop. Once #2097 is in, its leave_path cancels the queued welcome texts itself, so an undo of Not a guest reopens the follow-ups but can't requeue those texts (it doesn't see their ids)"
  - "No live evals run (Chief's block was checked by unit tests only)"
decisions:
  - "inbound_risk.assess is pure and deterministic; weights from the proposal §4.2 with two splits found by the seeker corpus: Zelle/Venmo/Cash App/PayPal alone is 1 (people ask how to give), the hard money words are 3; a link to the sender's own domain or a social site is 1, elsewhere 2. Threshold 3. On the real shapes (made-up details): second card 7 (9 once the first was held), first card 6, real guests 0"
  - "Repeats here count only against a card that already needed a look (a guest filling the card twice isn't a campaign); elsewhere: the same long words at one other church, or the same address at two or more, in 7 days. Junk phones and free-mail domains are never fingerprints"
  - "A church's own Real always wins (clear); a shared-list hit is +3 and a reason, never a block; a Real never records the domain"
  - "A hold is recorded before anything is skipped: if the inbound_checks row can't be saved (before the APPLY file), the card runs as it always did"
  - "Hold = the contact carries metadata.inbound_hold; on_connect_card (follow-up + Welcome Path), alert_church, lead scoring and the nudge are skipped; one quiet urgent_alert 'N cards need a look' (12 h dedup, never the name); the email notice gets a [Needs a look] subject, a banner and no reply_to. The texts_ok consent row is still kept at submission (W4 owns that block); the Welcome Path enrolment waits"
  - "Real replays each held card exactly (on_connect_card with the card's own texts_ok; scoring and the nudge for a contact form). Not a guest and Scam work on anyone, held or not: inactive first, then follow-ups closed and queued Welcome Path texts cancelled. Every tap is undoable for a week from inbound_decisions.before"
  - "Prayer: checked deterministically only, never held, never to the model; a scoring request carries submission.needs_a_look"
  - "Chief: a tail block names held people with their reasons (defused), never their words; class-A verbs mark_real_person / mark_not_a_guest / undo_inbound_decision (People & care area, Manager seat and up, never unattended); Scam is never Chief's. A class-C send to a held, Not-a-guest or Scam person holds for the practitioner's own go-ahead, like a tainted turn"
  - "The morning and evening briefs drop held people from new leads/contacts and say only how many wait"
  - "Switch INBOUND_SAFETY = off (default) | watch | owner | on | <ids>. Salt INBOUND_HASH_SALT, else derived from the service key"
related: [2026-11-26-desk-playbooks.md]
---
Read both repos' work logs first: nothing earlier touches inbound checks; the
step-1 Fixes run in parallel (W4: #2097 close_for_contact and the inactive
sweep; branch m5-contact-submit-bot-checks for the honeypot, token and shared
limiter). We agreed to split contact-submit: theirs runs before validate, mine
after it.

New: `inbound_risk.py`, `inbound_hold.py` (routes `/inbound/*`,
`/platform/inbound/shared-list`), `chief_inbound.py`,
`supabase/APPLY-2026-11-27-needs-a-look.sql`, `docs/INBOUND_SAFETY.md` (the
design and the front-end contract). Wired: `public_site.py` (contact-submit),
`website_forms.save_prayer`, `notification_engine` (briefs), `church_roll`
(`needs_look`), `chief_of_staff` (handlers, tail block, send gate),
`action_registry`, `action_inverse`, `chief_areas`, `kmj_intake_automation`.
Tests: `__tests__/test_inbound_risk.py`, `__tests__/test_inbound_hold.py`,
`__tests__/needs_a_look_db.mjs` (in CI's test-db job).
