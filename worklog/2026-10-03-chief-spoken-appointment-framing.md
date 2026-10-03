---
title: Keep natural spoken appointment checks on the direct read path
date: 2026-10-03
agent: Codex (GPT-6)
asked: "Fix the consultation check that fell back to a long unverifiable answer"
status: shipped
prs: []
migrations: []
left_undone: ["Owner microphone retest after this release"]
decisions: ["Preserve full request scope", "Missing meridiem asks a question before any availability verdict", "Only identical complete retries bypass old failed prose"]
related: [2026-10-03-chief-listening-availability.md, 2026-10-03-chief-busy-calendar-read.md]
---
The spoken framing 'I want you to check whether two of my consultation appointments' did not match the existing deterministic parser. Bounded request prefixes and possessive forms now express the same complete appointment check. The full message must still match; extra actions, provider restrictions and unsupported constraints remain on the general path. Unspecified morning/afternoon returns the existing clarification immediately, without calendar reads or model output.

Natural explicit period replies and exact service choices preserve the original date and joint-capacity request. A reply that contradicts an already explicit meridiem defers instead of mixing periods. An unchanged complete check may be retried after failed prose; other unknown historical constraints and pending scope questions still block that shortcut.

Validation:176 focused parser, scheduling, authenticated transport, independent pagination and readout checks passed. Real streaming regressions cover the exact live wording in a fresh greeting and after an identical failed turn: one owner read, no resource check, no model/opener, and the precise AM/PM question. Protected CI, deployment and signed-in browser verification are recorded by the integrating session through the release/Dev Desk; an owner microphone retest remains necessary for acoustic timing.
