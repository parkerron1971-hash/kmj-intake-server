---
title: Close the remaining long-conversation voice gaps
date: 2026-10-02
agent: Codex (GPT-6)
asked: "we need to fix those gaps. make every effort to fix those areas please."
status: shipped
prs: [kmj-intake-server#1213]
migrations: []
left_undone: []
decisions: ["Preserve prior scope before speeding up a request", "Exact structured resolver output only", "Unknown or unsupported constraints retain full context", "Measure typed read-aloud separately from microphone latency"]
related: [2026-10-02-chief-conversation-gaps.md, 2026-10-02-chief-invoice-history-scope.md, 2026-10-02-chief-legacy-plan-context.md, 2026-10-02-chief-plan-invoice-priority.md]
---
The first release removed measured playback gaps for simple invoice and short-plan requests. A production retest of an older mixed-topic conversation still measured 6.5 seconds of silence for invoices and 9.8 seconds for a short plan after the opening phrase. This follow-up combines bounded scope resolution, deterministic supported invoice scope, conservative ambiguous-question handling, and better invoice priorities in proposals. The overlapping backend and frontend voice worklogs were reviewed before implementation.

Independent review covered owner scope, replay before spending, the full email-visibility discussion, invoice-to-read-only-plan-to-invoice sequences, the imperative "Open invoices", and replies accepting an assistant's scope question. No actual tasks, reminders, messages, or business record changes are performed by the retest. Normal conversation logging and the existing display actions remain.

Focused regression checks precede full protected CI. Final production measurements and deployment evidence will be recorded in the release PR. The playback test uses typed requests with ElevenLabs read-aloud; it does not measure microphone capture or speech recognition.

Integrated in PR #1213. Final combined validation: 406 focused tests passed; independent invoice review passed 256 related tests. Protected CI and production playback measurements are recorded in the PR. Unsupported or ambiguous constraints intentionally retain the full-context path.
