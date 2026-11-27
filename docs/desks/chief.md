# Desk: chief

## 1. What it owns

Chief is the chief of staff a practitioner or a church talks to: typed chat, the phone/voice
call, the morning brief, "undo that", the list of what Chief did, and what Chief remembers. This
desk owns how a turn works end to end: what Chief is told (prompt and brief), which model answers,
how it takes actions, how an answer is checked before it is shown, what a turn costs, and how fast
the first words arrive. It also owns the owner-only Platform Chief in Mission Control, shared
with `system`.

It does NOT own the business logic behind each action (giving, invoices, SMS, sites, church
jobs). The domain desks own that. This desk owns the plumbing it plugs into.

## 2. Where the code is

Backend (`kmj-intake-server`):
- `chief_of_staff.py`: the turn. `ACTION_HANDLERS` (332 verbs on main, 2026-11-26; CLAUDE.md's
  266 is stale), `_execute_actions`, `_gather_context`, `_archive_turn`, `_sb` (the caller's
  login) vs `_sb_service` (service role), `_ts()` (`Z` timestamps), `_fail()`,
  `ACTION_TAG_REMINDER`, `handle_queue_build_request` (the build bridge). Routes:
  `POST /agents/chief/chat`, `/agents/chief/chat/stream`, `/prewarm`, `/activity`, `/away`,
  `/undo/{undo_id}`, `/insights/run`, `/health`, `/missions` (all under `/agents/chief/`).
- `chief_prompt.py`: the system prompt in three cache segments: universal → `[[CHIEF_GLOBAL_SPLIT]]`
  → per-business stable → `[[CHIEF_CACHE_SPLIT]]` → dynamic tail. `chief_lean_brief.py`: the short
  manual (`CHIEF_BRIEF=lean`) and its church edition (`CHIEF_CHURCH_EDITION`). `church_skills.py`
  + `church_skills/`: written steps for church jobs (`CHIEF_CHURCH_SKILLS`, off by default).
- `chief_models.py`: lanes (`chat`, `voice`, `deep`, `draft`, `insight`, `background`, `review`,
  `review_fallback`, `repair`, `fast`, `opener`, `route`), `model_for(lane, plan)`, `effort_for`;
  env `CHIEF_MODEL_<LANE>` overrides. `model_ladder.py` (`effort_kwargs`), `llm_call.py`, `chief_llm.py`.
- `chief_tool_loop.py` + `mcp_server.py` (`WRITE_TOOL_SCHEMAS`): native tool calls for the reviewed
  class-A writes, still dispatched through `_execute_actions` (`CHIEF_NATIVE_WRITES=off` = tags
  only). `mcp_server.py` is also the outside-agent MCP surface (`MCP_ENABLED`, `mcp_oauth.py`, `mcp_tokens.py`).
- `action_registry.py`: what each verb does (read / ui / write, A/B/C reversibility).
  `audit_log.py`: the action ledger; `sync_action_types()` seeds `action_types`.
  `action_inverse.py`, `chief_undo_actions.py`: undo.
- The answer check: `chief_truth.py` (`finalize_reply`, `review_reply`, `review_stream_prefix`,
  `has_completion_claim`); `docs/CHIEF_ANSWER_TRUTH.md`.
- Speed: `model_router.py`, `chief_fast_track.py`, `route_ledger.py` (`model_route_log`),
  `chief_headline.py`, `chief_prewarm.py`, `chief_keep_warm.py`. Voice: `chief_voice_bridge.py`,
  `voice_stream.py`, `voice_metrics.py`, `chief_speech_boundary.py`. Docs: `docs/MODEL_ROUTER.md`,
  `docs/VOICE_FIRST_AUDIO.md`.
- Injection boundary: `untrusted_text.py` (`strip_action_tags`, `detect_injection`), `chief_holds.py`,
  `chief_said_again.py`. Who is asking: `chief_areas.py`, `chief_duties.py`. Earned permission:
  `standing_permissions.py`, `docs/CHIEF_AUTHORITY.md`.
- Memory: `chief_memories`, `chief_memory_review.py`, `chief_thread_summary.py`, `chief_last_time.py`,
  `chief_turns_by_login.py`, `chief_brain_pass.py` (nightly digest), `chief_insights.py`,
  `chief_team_conversations.py`.
- Guards in front of it: `spend_guard.py` (`over_budget`, `block_message`), `rate_limit.py`
  (`allow("chief", user_id)`), `api_usage_logger.py` (`log_api_usage` / `log_api_usage_sync`),
  `credit_ledger.py`.
- Reply report: `chief_reply_report.py`, `POST /agents/chief/reply-report` (files a support ticket).
- Platform Chief (owner-only): `platform_console.py` (`POST /platform/chief/message`), `platform_chief_*.py`.
- Tables: `chief_conversations` (now with `user_id`), `chief_memories`, `chief_thread_summaries`,
  `chief_undo_log`, `chief_activity`, `audit_log`, `action_types`, `api_usage`, `model_route_log`.

Frontend (`solutionist-studio`):
- `src/core/components/ChiefOfStaff.tsx` (the chat; sends the last `MAX_API_HISTORY = 30`
  messages), `ChiefCallMode.tsx`, `ChiefVoiceConversation.tsx`, `ChiefWorkLog.tsx`,
  `ChiefReplyReport.tsx`, `WhatChiefKnows.tsx`, `ChiefPreferences.tsx`, `chiefgo/` (phone Chief).
- `src/core/lib/chiefStream.ts`, `chiefVoice.ts`, `chiefConversations.ts`, `chiefActivity.ts`,
  `voiceStream.ts`, `speechChunks.ts`. Platform Chief: `src/modules/platform/pages/ChiefPanel.tsx`.

## 3. Rules that must not break

- Every handler returns `{result, label}` (`_fail()` for errors). A missing `result` blanks the app.
- A new verb goes in `ACTION_HANDLERS` AND in `action_registry.REGISTRY` (with a reason) or
  `UNCLASSIFIED`. Unclassified verbs fail closed.
- Server-owned rows (undo log, activity, ledger, summaries) are written with `_sb_service` /
  `sb_clients.sb_*_as_service`. Practitioner data stays under `_sb`.
- Class-C writes (sends, money) are proposals. The typed request is the yes. A tainted turn holds
  them, and autopilot "full" is not a bypass.
- App-written instructions go in the system prompt's uncached tail, never in the user turn.
  Models read text there as an injection and refuse.
- Keep the cached segments byte-stable. No per-turn data above `[[CHIEF_CACHE_SPLIT]]`, keep the
  tool list stable, and use the same effort on retries (effort is part of the cache key). A
  segment under 1024 tokens silently won't cache.
- Every paid call meters through `api_usage_logger`. Spend guard and rate limit fail OPEN.
- Build bridge: the owner's business files a GitHub `@claude` issue, and anyone else's files a
  support ticket. Practitioners never see builder, GitHub, Claude Code or "AI agent" language.
  Chief mirrors the action result's own words.
- Chief does what the owner can do on request, and leaves a reviewable record (one undo for bulk
  work). What the permission system gates stays gated: money out, sending to people, pricing,
  what enters Build.
- A new Chief capability is a feature. It needs a Build slot and ships behind a switch
  (owner-only until a Thursday flip). Fixes need no slot.
- No state between requests in process memory: the web tier runs several replicas.

## 4. Traps already hit

- A login's JWT write to an owner-only table returned None. "Undo" said "nothing to undo", then
  Chief said the task never happened (#961).
- `+00:00` in a PostgREST filter decodes to a space → 22007, failing soft. Chief's context was
  empty for months. Use `_ts()`.
- PostgREST keeps quotes on `col=eq."value"`: 0 rows matched for a month (#1355).
  Use `quote(str(v), safe='')`.
- Sonnet 5 thinking used up the reviewer's whole `max_tokens`, so every long answer became
  "I couldn't verify". Use `effort_kwargs(model, 'low')`.
- A malformed review (`verdict == 'invalid'`) delivered the draft unchecked. It now gets a second
  review on `review_fallback`.
- Advice numbers ("fewer than 3 by week 1") and counts proved by the names beside them were read
  as business facts and withheld.
- A withheld count is often the list's row limit (`_LIST_LIMITS`), not a bug in the check. The
  evidence must carry exact totals and say what the rows are.
- `_retry_missing_actions` ran with no effort and unpinned tools: a cold cache write, a 47s turn.
- The keep-warm ping was an asyncio task, and every deploy killed it. It now lives in the DB.
- Office logins' turns weren't saved (owner-only policy). Fixed by
  `chief_conversations.user_id` (APPLY-2026-11-24).
- A confirming turn that reads other people's words taints the turn again, so a held write
  never clears (the "say it again" loop on assignments).
- The lean brief deferred a church's giving reads, so Chief "couldn't find" the giving. Check
  which tools a church turn loads. `show_revenue` is loaded as a read but only navigates.
- An empty `review_reply` can be a billing 400 (credits ran out), not a model fault.
- `logging` never reaches Railway. Only `print(..., flush=True)` does.

## 5. How to check work

- Any verb change: `pytest -q __tests__/test_action_registry.py __tests__/test_action_ledger_stage1.py`,
  then the matching `__tests__/test_chief_*.py`.
  - Cache: `test_chief_brief_prefix_stable.py`, `test_chief_cache_holds_still.py`, `test_chief_prompt_shape.py`.
  - Answer check: `test_chief_factual_eval.py`, `test_chief_check_hardening.py`, `test_chief_review_*.py`.
  - Injection and RLS: `test_prose_injection_boundary.py`, `test_untrusted_content_boundary.py`,
    `test_chief_rls_wiring.py`.
  - Speed, MCP, guards: `test_model_router.py`, `test_mcp_writes.py`, `test_per_tenant_spend_ceiling.py`.
- Live evals: `scripts/chief_turn_eval.py`, `chief_factual_eval.py`, `chief_advice_eval.py` and
  the other `scripts/chief_*_eval.py` (weekly: `.github/workflows/chief-eval-weekly.yml`).
  **They bill the production Anthropic account**, and spend_guard does not see them. Running out
  of credits this way has already taken production AI down. State the cost first, keep a running
  total, and never run Opus/Sonnet replays in parallel without saying so.
- Frontend: `npx tsc -p tsconfig.app.json --noEmit` (zero new errors), `npx vite build`, and the
  `scripts/check-chief-*.mjs` checks. `check-chief-conversation.mjs` and
  `check-chief-speech-handoff.mjs` run the real source against a stub env, so add any new free
  function to that env. Phone preview: `npx vite --config tests/chief-go.vite.config.ts`, then
  open `/tests/chief-go-preview.html?state=drawer|call`.
- Live: before blaming the model, read `railway logs` for `[Chief Parser]`,
  `[chief stream result]`, the taint WARNING, and `: 400 ` lines from `_gather_context`.

## 6. Edges

- Domain desks own their Chief modules; this desk owns how they plug in. Agree a handler's
  wording with its domain desk before changing it.
  - `church-office`: `chief_church_*.py`, `chief_academy_actions.py`, `chief_move_in.py`,
    `chief_event_volunteers.py`.
  - `money`: `chief_giving_*.py`, `chief_bookkeeping*.py`, `chief_invoice_*.py`,
    `chief_bills.py`, `chief_reconcile.py`.
  - `messaging`: `chief_sms_actions.py`, `chief_church_mail.py`, `chief_email_setup_actions.py`.
  - `websites`: `chief_site_design.py`, `chief_site_view.py`.
  - `live-media`: `chief_clip_actions.py`, `chief_video_actions.py`.
- `system` owns `spend_guard`, `rate_limit`, `sb_clients`, migrations, Platform Chief's owner gate
  and the GitHub side of the build bridge. `chief_of_staff.py` is one huge shared file: keep edits
  small and rebase often.
- `tickets`: reply reports and the non-owner build-bridge branch land in `support_tickets`.
  Tickets diagnoses Chief complaints and hands them to this desk.
