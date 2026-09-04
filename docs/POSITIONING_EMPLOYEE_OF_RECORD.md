# Positioning: from software to employee of record

*A proposal, 2026-09-04. The Later item from the Astra brief. Nothing
here is live; every surface below is Kevin's call, and the sequence at
the end is the order I would push them in.*

## Why now

OpenAI's GPT-6 "Astra" (2026-09-03) put a capable general agent in every
paid ChatGPT plan. The first question a practitioner will ask is "why
do I need Solutionist if my assistant can do it?" The honest answer is
the pitch: a general agent can reconstruct a screen; it cannot be the
place where eighteen months of a business's bookings, invoices,
consent records and decisions live, cannot hold the audit trail that
says who authorised what, and cannot be told to stop in one place.
Solutionist is that place. The vision doc already frames the end
state — *Solutionist stops being software they use and becomes an
employee they hired* — and says pricing follows: an employee is judged
against the labor budget, not the SaaS budget.

What shipped this week makes the framing true rather than aspirational:

| Phrase in the pitch | What backs it |
|---|---|
| "any assistant you already use can run your business through Solutionist" | the connector, open to every owner, read or write scope, from Settings (#810, FE #793) |
| "keeps the books" | the ledger, bookkeeping proposals, and now the bookkeeper earning trust on its own (#828) |
| "holds the consent records" | `consent_records` carried in the export, with the rest of the record (#827) |
| "remembers why" | every action on the ledger with `authorized_by`; the client timeline (#825, FE #794); the memory stack |
| "can be told to stop" | pause automations, revoke a trust grant, `undo_last`, dismiss a proposal — one word each |
| "works for you, not around you" | class C never reaches an agent; every unattended action is recorded; the browser hand runs only what a person approved (#826) |
| "your data leaves with you" | the export is a contract that cannot rot (#827) |

## The line

> Solutionist is the employee of record for your business. A chief of
> staff who keeps the books, holds the consent records, remembers why,
> and can be told to stop. Bring whatever assistant you already use; it
> works through Solutionist.

Shorter, for a tab or a listing: **The one who keeps the record.**

## Surface by surface

Each row is *what it says now → what I would say*. Headlines that carry
the brand stay; the change is in the sentence after them.

### 1. Homepage hero (`marketing_pages.py`, the subhead under "Every Problem Has A Solution.")

Now:
> The Solutionist System is one workspace that runs your whole business: clients, money, marketing, and your site. A chief of staff does the work, all under one subscription.

Proposed:
> Solutionist is the employee of record for your business: a chief of staff who keeps the books, holds the consent records, remembers why, and can be told to stop. Bring whatever assistant you already use; it works through Solutionist.

Keep "Every action logged and reversible" under the buttons; it is the
proof line for "can be told to stop".

### 2. Compare page ("Eight tools that don't know each other. Or one that knows you.")

The stack list names ChatGPT as one of the eight tools Solutionist
replaces. After Astra that reads as a fight we do not need to pick.
Move ChatGPT out of the "replaced" column and into a line under the
table:

> Already use ChatGPT or Claude? Keep it. Connect it from Settings and it works through Solutionist — reading your business, or, with your permission, keeping its records — with every action logged, reversible, and yours to revoke.

### 3. Pricing page

The vision doc's framing, made visible. One line above the tiers:

> Judge it against what a person would cost, not what software costs.

and, per tier, one comparison the practitioner recognises. The numbers
need Kevin's sources before they go live; the shape is:

> *Starter* — a few hours of front-desk work a week. *Professional* — a part-time bookkeeper and a front desk. *Practice* — the office manager you were going to hire.

No dollar comparisons until the sources are settled; a wrong number
here costs more than the framing gains.

### 4. The connector listings (Claude.ai directory, ChatGPT apps — Kevin's submissions)

Name: **Solutionist**
One line: *Run your business through the one who keeps the record.*
Description:
> Solutionist is the employee of record for a small business: bookings, clients, invoices, contracts, texts and email, the books, and the website, with a chief of staff over all of it. Connect your assistant to read the business, or grant it permission to keep records — contacts, tasks, notes, sessions, expenses, time, drafts. It never sends to a client, charges anyone or deletes for good; a draft goes out only when the practitioner approves it. Every action is logged, reversible, and revocable from Settings.

### 5. Settings → Agent Access (frontend `AgentAccessSettings.tsx`)

The screen already explains scopes. One sentence at the top to set the
frame:

> Your assistant works *through* Solutionist, not around it: it can read the business, or keep its records with your permission, and everything it does is logged, reversible, and yours to take back.

### 6. What not to change

- Chief's name and voice. Chief is the face; "employee of record" is
  what the business is, not a new name for Chief.
- No "AI employee", "autonomous", "agentic", "24/7 workforce". The
  pitch is calmer than the market's, on purpose: the words are
  *keeps*, *holds*, *remembers*, *can be told to stop*.
- The trial and price lines. Positioning changes the sentence around
  them, not the offer.

## Sequence

1. Connector listings (new surface, no regression, Kevin's submission
   anyway) and the Settings sentence (FE, one line).
2. The compare page line about ChatGPT and Claude.
3. The homepage subhead.
4. Pricing framing, once the labor comparisons have sources.

Each is one PR; each can be reverted alone. The homepage change is the
one to watch: it is the only one that changes what a first-time
visitor reads before they know what Chief is.
