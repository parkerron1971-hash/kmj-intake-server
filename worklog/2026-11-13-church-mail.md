---
title: Church email — every admin and leader gets their own @churchdomain address
date: 2026-11-13
agent: Claude Code (Claude Opus 5.5)
asked: "is the email setup ready? I was seeing about setting email for admin and chief doesn't know about it" / "can we muild what is needed so this can go live right away?"
status: in progress
prs: []
migrations: [supabase/APPLY-2026-11-13-church-mail.sql]
left_undone:
  - "The Email room (read and send in the app, as yourself) waits on a mock and Kevin's yes. Until then each person gets a copy at their own email and replies from there, so a reply comes from their own address, not the church's."
  - "Love City's cut-over is separate from this code: Resend receiving on lovecityc.com, its existing Namecheap forwards brought over as forward boxes, then the MX switch."
  - "Email Setup has no 'Receive mail here' screen yet; the switch is done for each church by hand."
  - "Chief doesn't yet offer an address with a new login invite."
decisions:
  - "Way A, as approved 11-11: the church's MX points at Resend receiving and /email/inbound sorts by CHURCH FIRST (the recipient's domain), then by address. A church address is only ours when the domain's MX really points here (mail_comes_here), so a church merely Cc'd on mail to someone here gets nothing extra."
  - "Church mail never reaches another business's contact match or the Mission Control catch-all. A read it needs that fails answers 503 so Resend retries: it waits rather than going to the wrong place."
  - "A box names who, never copies them: person (login or leader), role, prayer, office (share_with, catch_all), forward. church_mail.reach looks the holder up every time, so a revoked login or a leader out of every role sends their mail to the office box at once, and a role nobody holds goes to the role it answers to (church_roles.chain_above), then the pastor."
  - "prayer@ (a role that handles prayer_shared, or 'prayer') makes a care request shared with the prayer team, handed out by church_prayer.on_new; its words are never copied into an inbox, and danger words stay with the pastor (consent_columns)."
  - "Until the Email room: a copy at the person's own email, sent from the box's address (the church's verified sending domain), Reply-To the sender, the attachments by their download links (25 MB at most), no platform List-Unsubscribe (it's their mail), and an X-Solutionist-Copy header so a copy that comes back is held, not re-sent. Resend's Idempotency-Key and the church_mail_once index make a twice-sent webhook one copy."
  - "Held and never copied: no SPF or DKIM pass, DMARC fail, a spam or virus verdict, our own copy looping back. The church's domain and the platform's sending reputation are never spent on spam."
  - "Chief: church_email (mid-turn read; any login, suggestions and forward targets for the pastor and Admins only), give_church_email (class C: it can email the person; the pastor or an Admin; held on a tainted turn by the door), take_back_church_email (class A). The welcome note goes once (told_at), only after mail to the domain reaches the system."
  - "Names are matched only when they name one person; two people with one first name are never guessed."
related: [2026-11-11-role-hand-back.md, 2026-11-11-email-setup-namecheap.md]
---
Kevin found Chief knew nothing about church email addresses: the plan
(artifact WYc8oLMAerrqDkCBa5Dq2t) was approved on 11-11 and not built. He
asked for whatever makes it live right away.

Built:
- `church_mail.py`: which church a domain is, who a box reaches now,
  sorting incoming mail, copies, the prayer list, held mail, and the
  directory and give/take-back that Chief uses.
- `chief_church_mail.py`: the three Chief verbs. They're wired into
  `chief_of_staff`, `chief_prompt`, `action_registry`, `chief_areas` and
  `chief_tool_loop`.
- `email_sender.inbound_email`: church sorting runs before every other step.
- `supabase/APPLY-2026-11-13-church-mail.sql` adds `church_mailboxes` and
  `church_mail`. Both are server-only and excluded from the export.
- `__tests__/test_church_mail.py`: 32 tests.
