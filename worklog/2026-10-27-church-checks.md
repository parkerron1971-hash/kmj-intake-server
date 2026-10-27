---
title: Check requests (money going out) — Get paid back with a receipt, a limit, a keeper's yes, budgets by ministry, paid into the books (server + member app)
date: 2026-10-27
agent: Claude Code (Claude Opus 5.5)
asked: 'Church Office Prototypes (https://claude.ai/artifact/2vGqaUZUynRuiFVKuQEZWo), the "Check requests" tab → Kevin, 2026-10-27: "lets go with your list" (third, after help requests and serving hours) and "make sure that the design is top tier"'
status: shipped, switched off (platform owner only until a Thursday); migration waiting on Kevin
prs: [kmj-intake-server (this PR), solutionist-studio (the office page, its own PR)]
migrations: ["supabase/APPLY-2026-10-27-church-checks.sql (NOT APPLIED: Kevin applies by hand)"]
left_undone:
  - "Apply supabase/APPLY-2026-10-27-church-checks.sql. Until then /church/checks/status says enabled false, the other routes answer 503, and /my/paid-back says it couldn't load"
  - "Switch-on: CHURCH_CHECKS=on on Railway on a Thursday (it defaults to owner), with the app's What's New entry. In owner mode the member side shows only in the platform owner's preview of the member app, where nothing saves: Kevin opens it at <church address>/my/paid-back in the preview"
  - "Nobody is told by phone or email: the office isn't alerted to a new request, and the asker isn't alerted when it's approved, declined or paid (they see it in the app). member_push could carry both"
  - "A church login with no part on the Serve tab (an office seat with no role or team) has no door to Get paid back; it opens at /my/paid-back directly"
  - "Renaming a budget line leaves older requests and expenses under the old name (spent follows the expense's subcategory)"
  - "Chief can't read or act on check requests yet (no action handler)"
  - "The member can't take back or fix a request they sent; the office edits it (while it waits) or declines it with a reason"
decisions:
  - "Lane: Build, under the Build item 'Love City leaves Subsplash (M-1)'"
  - "Who: the treasurer's role, as asked: the owner, admins, the accountant (a collaborator, not a seat) and logins whose areas include Giving & money. With Who sees what off, or a login with every area, money stays with the owner, admins and the accountant. A viewer reads; the owner and admins set the limit and the budgets and take a payment back"
  - "The limit and the keepers follow church_help.py word for word: up to the limit ($250 unless set) the treasurer approves the whole amount; above it is_open(giving_money) from church_keys (a keeper here, or church_keys.ask with the ministry and amount as the reason, then a tap or the code for an hour); no keeper means the limit alone governs; raising the limit needs the same yes. No partial approvals: a reimbursement is paid whole"
  - "Budget lines: business_budgets is six fixed monthly categories (operating, tax, ...) and can't say Kids or Youth, so a small setting holds the lines (church_check_settings.lines: name and this year's budget). Spent is the books' own: every business_expenses row this year whose subcategory is the ministry's name (the same column church_help uses for its fund), so an expense entered in Bookkeeping counts too. Never saved, the lines start from the church's ministry groups (groups.kind = ministry), else Kids, Youth, Worship, Hospitality, Outreach, Building, Office"
  - "Receipts reuse the receipt-capture bucket: private business-documents, under <church id>/check-requests/<random>.jpg|pdf. Photos are made upright, at most 2200px, re-saved as JPEG (the phone's tags, location too, don't travel); PDFs are kept as sent. The server streams them (Cache-Control private, no-store): the office through /church/checks/requests/{id}/receipt, the asker through /my/paid-back/{id}/receipt, never a public or signed link handed out. The paid expense carries receipt_path, so Bookkeeping's Expenses shows the paperclip"
  - "Paid: by check (its number, required) or bank transfer, and the day; one business_expenses row (Operating, subcategory the ministry, vendor who was paid, description 'Check request: <what for> (paid by check #1043)', payment_method 'check' or none for a transfer, the receipt). The request moves from approved only once (status=eq.approved), so a second press removes its own expense. A closed period refuses paying and taking back. Taking back puts the request first back to approved, then deletes the expense, and says so if the expense stays"
  - "Decline needs a reason (300 characters), which the asker reads in the app as 'From the treasurer'"
  - "The member side is server-rendered like the rest of the member app (member_portal_checks.py): one receipt tile (accept image/* and PDF, so the phone offers its camera or its photos), the picture shown at once and shrunk to 2000px in the browser before it's sent, the amount, what for, the ministry as chips, Send to the treasurer; then their own requests with a thumbnail, the status and a decline's reason. The door sits on the Serve tab's pages and My serving (member_portal_lead.PAID_BACK, one line each)"
related: [2026-10-27-church-help.md, 2026-10-27-church-keys.md, 2026-10-23-church-areas-map.md]
---
- `church_checks.py` (new): the switch (`CHURCH_CHECKS` off | owner | on, owner by
  default), who may act, the limit and the keepers, the budget lines and spent
  per ministry, receipts, paying into the books, the member side's reads and
  writes, and twelve routes under `/church/checks` (the docstring lists them).
- `member_portal_checks.py` (new): `/my/paid-back` (the page, a receipt, and the
  POST), and the door. `member_portal.py` sends `/my/paid-back` there;
  `member_portal_serving.py` and `member_portal_lead.py` show the door.
- `supabase/APPLY-2026-10-27-church-checks.sql` (new, NOT applied):
  `church_check_settings`, `church_check_requests`, both server-only, no drops.
  Ledger row in `docs/MIGRATIONS.md`.
- `account_lifecycle.py`: both tables exported; requests skipped on import.
- `kmj_intake_automation.py`: both routers. `.github/workflows/ci.yml`: the
  PGlite check. `.env.example`: `CHURCH_CHECKS`.

Checks:
- `__tests__/test_church_checks.py`: 16 tests (the switch and missing tables,
  the member side's switch, each login's standing, money with Who sees what
  off, a member's own requests and a decline's reason, receipts private and
  through the server, the member POST and a preview, the limit with no keeper,
  a keeper's yes by ask and by code, paid into the books and spent vs budget,
  closed books, two presses of Mark paid, a take-back whose expense stays,
  declines and edits, another church).
  Thirteen rules broken on purpose (no limit, no keeper as open, another
  member's list, any receipt path, no closed books, a take-back that leaves
  the expense, an always-open switch, another church's id, a decline with no
  reason, a photo's tags kept, paying twice, any login as treasurer, a hidden
  reason): all caught.
- `__tests__/church_checks_db.mjs`: 37 checks on PGlite.
- The access ratchet, export/import, the member portal, Serve tab, lead,
  serving, help and keys suites pass. The member page was looked at in a
  headless browser at 375px and 1280px on the black and white bases, empty,
  with a photo added and with a missing field: no sideways scroll, every tap
  target 44px or more.
