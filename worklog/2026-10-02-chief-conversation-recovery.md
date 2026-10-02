---
title: Chief invoice visuals, current weather, and voice turn recovery
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Check Chief's conversation and fix its issues"
status: shipped
prs: [solutionist-studio#1102]
migrations: []
left_undone: ["Human microphone retest; ambient speaker identity is not established by transcript text"]
decisions: ["Display receipts prove a view was shown but never authorize or prove a write", "Current weather uses timestamped NWS observations and separately identified forecasts", "Transcription identity and cancellation ownership protect turn boundaries without guessing the speaker from language"]
related: []
---
Corrected broad invoice-list scope, disclosed the existing 25-row view cap, and recovered invoice summaries from scoped display rows when model narration fails verification. Paid and draft invoices are no longer called overdue based only on a past due date. Exact call-feedback messages receive a direct acknowledgment without replaying old tasks. The voice relay preserves upstream transcription item identity and commit order for the companion frontend.

The companion frontend deduplicates identified transcripts, orders completions, retires stale recognizers, and invalidates interrupted answers before recovery can resume. Genuine multilingual text is retained. These fixes do not establish ambient speaker identity or prove the reported duplicate playback's sole cause. No migrations or business writes are required. Isolated worktrees preserve unrelated working changes.

Weather retrieval uses only validated NWS hosts and server-resolved coordinates, refuses stale observations, and separates current-condition proof from forecast proof. Public-only synthetic direct/retry turns selected the new read tool and retained the observed conditions and local timestamp after verification. Production health and exact deployed commits are checked after merge; the release PR records CI results.
