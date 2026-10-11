---
title: "The business brain: owner rules, versions, the nightly pass"
date: 2026-10-11
agent: Claude Code (Claude Opus 5.5)
asked: "approved to build this. great plan ... build the best path forward. and approved to do what is needed to get this working well (Kevin, 2026-10-11, after the Layer Two Phase 0 report)"
status: waiting on review
prs: [kmj-intake-server#1381]
migrations: [supabase/APPLY-2026-10-11-layer-two-foundation.sql]
left_undone: ["the What Chief knows panel in the app (frontend PR, separate)", "ledger rows for chat actions do not yet carry the brain version: lands with the turn-linkage PR's _ai payload", "the brain does not yet replace parts of the five-minute snapshot: that waits for a week of real digests to judge them", "voice rules still live per owner in practitioner_profiles; new voice rules from the nightly pass go to the business profile"]
decisions: ["a rule is an owner fact with a polarity in the existing operating profile, not a new table: per business, versioned, history kept, already read by chat and unattended runs", "rule proposals go through the Approval Queue (push, expiry, ledger), not chief_proposals, whose trust track can auto-approve a type and whose rows feed cross-business pattern counts", "adopt_business_rule is class A but in OWNER_DECISION_VERBS: always the owner's yes, never a standing permission", "the nightly pass gets no tools and never reaches the action door; it writes a digest and at most two proposals", "a failed read never counts as no rows: the run fails and its window is reviewed again, and proposals are held when the guard lists cannot be read", "removing a rule needs the owner's words to name that rule, not just any owner turn", "the digest is treated as third-party text before it reaches the prompt"]
related: []
---
Kevin's Layer Two handoff asked for a path to independence: own the brain, rent
the engine. This is the brain. Each business now has owner rules Chief follows
every time (capped at 25, rendered first), a versioned brain (profile revision +
rules + nightly digest + model lanes, hashed into a fingerprint, one append-only
row per distinct brain), and a nightly pass: one Haiku 5.5 call per business
with activity, capped at 3 cents, that writes a short state-of-the-business
digest into Chief's per-business prompt and proposes at most two rules for the
owner to approve. Idle businesses cost nothing; a same-night retry neither bills
nor writes.

The owner sees and controls all of it through /brain/{business_id}: rules
(add, edit, remove), proposals waiting, what they declined, what Chief has
learned, and last night's notes. Every write is a ledger row with the rule's
words.

The PR reviewer caught that a failed read was treated as no rows in the pass and
on the page; fixed before merge, with tests that fail those reads.
