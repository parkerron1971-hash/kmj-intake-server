---
title: Report a Chief reply from inside the app (Google Play AI-content policy)
date: 2026-11-19
agent: Claude Code (Claude Opus 5.5)
asked: "Google Play's AI-generated content policy: people must be able to report or flag offensive AI output inside the app. Add a Report control on Chief's replies and a backend that stores reports where the owner sees them in Mission Control."
status: in progress
prs: [kmj-intake-server (this PR, branch chief-reply-report), solutionist-studio (companion PR, branch chief-reply-report)]
migrations: []
left_undone:
  - "Merge this backend PR before (or with) the frontend one: until it deploys, Send in the app answers 'That report didn't send'."
  - "No email to the owner when a report arrives: it waits in Mission Control (Support Tickets, and Today's open tickets) like any ticket."
  - "Only Chief's replies carry Report. Other AI text (Design Coach, Strategy Session, Chief's Home one-liners, the voice stage's spoken caption) does not; the voice stage's reply lands in the chat, where it can be reported."
decisions:
  - "No new table: a report is a support_tickets row (context.kind = chief_reply_report), so Mission Control's Support Tickets panel, Today's open-ticket list, triage, replies and the reply email all work on it unchanged."
  - "'Offensive or harmful' gets a support_triage row at severity high on arrival (best effort; the queue seeds its own guess if that write fails). 'Wrong or made up' is category bug; the rest general."
  - "Who may report = who may talk to Chief: the owner, an active seat of any role, or an active collaborator (the businesses RLS read the chat turn relies on). Checked with the service role; fails closed (503); a stranger gets 404."
  - "user_id is set explicitly: its default is auth.uid(), which is null for the service role."
  - "A sample church's report passes sample_church_guard (EXEMPT_PATHS) and is filed under the HOME church: the sample is deleted on start and tickets cascade."
  - "Rate limit: rate_limit bucket chief_reply_report, 20 an hour per login (RL_CHIEF_REPLY_REPORT_PER_HOUR), fails open."
  - "A ticket is tenant-readable by the business owner, so a member's report (the reply, the question before it, the note) is visible to the owner. Nothing in it the owner can't already see."
related: []
---
POST /agents/chief/reply-report (chief_reply_report.py) takes the business, a
reason (offensive | wrong | other), an optional note, the reply as shown, the
message before it, the conversation id and where in the app it was read. It
files one support ticket ("Chief reply reported: <reason>") with the reply cut
to 3000 characters and the message to 5000 (the table's CHECK). Tests:
__tests__/test_chief_reply_report.py. The app's Report link and sheet are in
the companion solutionist-studio PR.
