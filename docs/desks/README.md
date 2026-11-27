# Desks — the map

A desk is one area of the Solutionist System with its own playbook: what
it owns, where the code is in both repos, the rules that must not break,
the traps already hit, how to check work, and where it meets the other
desks. A fresh worker reads its desk's playbook first and starts already
knowing the area.

The playbooks are knowledge, not policy. `CLAUDE.md` and `AGENTS.md` in
each repo still apply to every worker on every desk, and win if a playbook
disagrees with them. If a playbook is wrong, fix it in the same PR as the
work that found it out.

## The nine desks

| id | Owns | Routing keywords | Repos |
|---|---|---|---|
| [member-app](member-app.md) | The church members' phone app at `<church site>/my` (server-rendered HTML, the Lumen look): Home, Watch, Connect, Bible, Give, sign-in and join, plus the office's Member page set-up | member app, Lumen, member portal, `/my`, members' phone, join, sign-in code, moments, plans, devotional, Bible marks, Lead tab, Member page settings | backend (pages) + frontend (set-up only) |
| [church-office](church-office.md) | The church staff side: church Home and briefing, the members roll, Serve and volunteers, office logins and roles, classes, care, kids check-in, guests, Move-in | church Home, roll, members list, volunteers, Serve, office login, admin, roles, duties, assignments, classes, academy, care, prayer, kids, guests, visitor, Move-in, schedule, meetings | backend + frontend |
| [chief](chief.md) | Chief, the AI chief of staff: actions, prompt, model lanes, memory, answer check, cost and speed | Chief, action, ACTION_HANDLERS, prompt, cache, model, lane, answer check, slow turn, Chief forgot, Chief said, tool call, platform Chief | backend + frontend |
| [websites](websites.md) | The site builder and composer, church and practitioner sites, hand-built sites, forms on sites, custom domains, the Solutionist's own public pages | site, website, composer, builder, kit, page, publish, custom domain, DNS, form on my site, ChurchSavvy site, marketing page | backend + frontend |
| [money](money.md) | Plans and billing, Stripe, giving, bookkeeping, bank statements, bills, funds, payments and payroll | billing, plan, trial, Stripe, checkout, webhook, giving, gift, donation, statement, bank, Plaid, bookkeeping, ledger, bill, payroll, invoice, receipt, refund | backend + frontend |
| [messaging](messaging.md) | Texting, email, church mail, alerts and push notifications | SMS, text, Twilio, texting registration, email, Resend, mailbox, church mail, Gmail, alert, push, notification, opt-out | backend + frontend |
| [live-media](live-media.md) | The stream relay, the live room, LiveKit video (live classes, group meetings), service clips, recordings and storage, Video Studio, the ChurchSavvy presenter | stream, live, LiveKit, relay, OBS, YouTube, recording, clip, video, storage, presenter, lyrics, slides, screens, lower thirds | backend + frontend |
| [system](system.md) | Database and migrations, auth, security and RLS, deploys and CI, background agents, Mission Control, Solution Space, the work log | migration, SQL, RLS, policy, auth, JWT, owner check, deploy, Railway, Vercel, CI, agent, watchdog, Mission Control, Dev Desk, Solution Space, env var | backend + frontend + Solution Space |
| [tickets](tickets.md) | The front door for problems: reads support tickets, diagnoses with evidence, hands the fix to the owning desk | ticket, support, bug report, "it's broken", help request, error, customer says | backend + frontend |

When a request fits two desks, pick the desk that owns the file being
changed; the other desk's playbook goes in the brief as reading. A problem
report with no clear owner goes to **tickets** first, and tickets names the
desk.

## How KAI uses these

When KAI (the owner's orchestrator in Solution Space) opens a Claude Code
or Codex worker in an area, it attaches `docs/desks/<id>.md` to the
worker's brief, so the worker starts with the area's map and its traps
instead of rediscovering them. Ideas that come up while working, and are
not the task at hand, go to that desk's notebook in Solution Space, not
into code. A worker that learns something a later worker needs (a new
trap, a moved file, a new check) adds it to the playbook in its own PR.
