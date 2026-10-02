# Chief with Codex and Claude Code

Mission Control stores owner conversations and campaign results in the cloud.
Solution Space polls outbound over HTTPS and opens the selected official CLI
on the paired computer, in a task-specific Git worktree. No inbound computer
port, subscription token upload, model API call or API fallback is introduced.
The phone uses the same owner-authenticated Mission Control page.

## Release order

1. Review and merge the backend and paired frontend changes. Kevin applies
   migrations manually, per `CLAUDE.md`. Required existing schema: August 19
   Dev Bridge, September 16 authority records, September 24 Dev Desk agents,
   September 15 platform marketing and September 26 marketing campaigns.
2. Apply `supabase/APPLY-2026-09-26-chief-local-work.sql` after those dependencies.
   Verify `platform_chief_work` has RLS, no anon/authenticated table privileges,
   and all four `chief_work_*` functions are executable only by service_role.
3. Install the matching Solution Space desktop update and restart it when no
   session needs preserving. Its queue advertises `workbench-v1`, `codex` and
   `claude`. Older desktops never receive subscription tasks.
4. In Solution Space, keep the existing bridge pairing enabled. Sign into each
   official CLI with its subscription. The startup check runs in the actual
   task directory. Unverified logins fail visibly; repair login on the desktop
   and send a new reply to retry. Computer must remain awake and online.
5. Release the frontend. Chief offers **Chief · metered API**, **Codex ·
   subscription**, and **Claude Code · subscription**. Campaign Production
   offers subscription strategy and individual production-item handoffs.
6. Before considering the installation live, submit one owner-authorized test
   request per agent from the phone, observe its desktop session, reply from
   the phone, and verify the final report. Inspect a structured strategy before
   choosing **Use this campaign plan**. No live model turn was run during the
   isolated automated tests.

## Conversation and result guarantees

- Start/reply UUIDs make request retries idempotent. Atomic database claims
  prevent simultaneous desktop pickup. Only the claimed device can send status
  or acknowledge replies for that conversation.
- Task-scoped report credentials stay out of owner browser responses. They are
  embedded only in the brief delivered to a paired desktop and are rotated when
  a finished task is reopened. Invalid/stale reports cannot settle queued work.
- Follow-ups preserve agent selection. After a restart, a reply reconstructs
  the saved brief and recent conversation in the same task worktree; it never
  resumes an unrelated "latest" Codex session. This is conversation recovery,
  not a provider-native shared conversation ID.
- Device heartbeats describe reachability, not subscription entitlement. Login
  is verified at launch using `codex login status` or `claude auth status`.
  Subscription child processes omit API credential/provider environment
  overrides and PowerShell profiles; Codex forces ChatGPT/OpenAI and Claude
  forces claude.ai login with no API-key helper. Raw auth output is not reported.
- A reported plan is a proposal. Applying it checks the result version,
  campaign revision and original brief hash, assigns production IDs, and uses
  the existing campaign audit. Retries do not replace it twice. Stale/archived
  campaigns cannot accept the plan. Existing post approvals remain separate.

## Practical limits and recovery

Provider subscription limits and enabled extra usage remain provider-controlled.
This is not an unlimited compute service or a local model. Agent inference
still uses the provider's cloud. Other media/integration services may have
separate costs and are not granted spending authority by a campaign budget.

CLI permission prompts can require desktop attention; this release does not
forward native approval dialogs to a phone. The task brief limits execution to
draft/build work and owner review, but does not create an OS-enforced publication
sandbox. Existing CLI permissions continue to apply. Do not treat queued/opened
as proof an agent has completed work.

Files and editable masters remain in the local task worktree. Reports show
paths and summaries; they do not upload private files. Upload approved exports
through the existing creative library. Threads show 50 recent conversations,
and each stores up to 200 notes. Start another conversation when full.

After a launch crash, send a reply to the same conversation after restarting
the claimed desktop. Network delivery of terminal input is at-least-once:
an acknowledgement failure may replay a reply. Do not issue irreversible work
through this draft/build route. Existing Dev Desk cancellation records task
cancellation; stopping an already-running terminal still requires Solution Space.

Rollback: disable the desktop bridge and revert application commits while
retaining the additive table/RPCs and saved conversations. Queued subscription
work remains unavailable to old desktop clients; do not delete user records.

## Validation

Python tests cover owner and device boundaries, both agents, request replay,
result validation, stale-plan rejection and task credential checks. PGlite runs
the real migration twice and verifies claims, reply replay, report-key rotation
and grants. Frontend browser fixtures exercise phone layout, offline queue,
both agents, lost-response retry, replies and reviewed plan application.
Desktop tests cover account checks, environment isolation, claim-before-launch,
agent routing, acknowledgment retry, real PowerShell quoting and worktrees.

Official authentication references:
- https://learn.chatgpt.com/docs/auth
- https://learn.chatgpt.com/docs/config-file/config-reference
- https://code.claude.com/docs/en/authentication
