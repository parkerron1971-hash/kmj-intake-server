# Automations — Practitioner Guide (Tier 1 Visual Rule Builder)

*Settings → Automations · included free on every plan*

## What it is
Your own "when this happens, do that" rules — built in plain sentences, no
code. Solutionist runs them for you, around the clock, and shows you
everything they did.

## The shape of a rule
**WHEN** something happens · **IF** it matches your conditions (optional) ·
**THEN** do up to three things.

**Triggers (WHEN):**
- *A new booking is made*
- *A new contact is added*
- *An invoice becomes overdue* (you choose how many days)

**Conditions (IF)** — optional filters on the event itself: *is / is not /
contains / doesn't contain / more than / less than / empty / not empty.*
Example: only when the booking `offering` **contains** "discovery".

**Actions (THEN):**
| Action | What happens |
|---|---|
| Notify me | An in-app notification, instantly |
| Tag the contact | Adds a tag (e.g. `new-client`) |
| Create a task for me | A task on your list, due in N days |
| Send a template email to the contact | Sends immediately — write it carefully |
| Draft a follow-up email **(ask me first)** | Becomes a Chief proposal you approve |
| Suggest a task **(ask me first)** | Same — proposal first |
| Suggest tagging the contact **(ask me first)** | Same — proposal first |

**"Ask me first" actions never act on their own.** They appear as Chief
proposals; you approve or dismiss, and Chief learns from every decision
(watch your approval ratios in Bookkeeping → Admin → Trust Track).

## Personalizing messages
Use `{{field}}` in any message — it fills in from the event:
`Hi {{contact_name}}, your invoice {{invoice_number}} is ready.`
Fields available depend on the trigger (the builder shows them). That's all
templates do — they insert data, never run logic.

## Examples
- **Welcome new clients:** WHEN a new contact is added → tag `new-client` +
  notify me.
- **Overdue chaser:** WHEN an invoice becomes overdue (14 days) IF total is
  more than 100 → draft a follow-up email *(ask me first)*.
- **Discovery-call prep:** WHEN a new booking is made IF offering contains
  "discovery" → create a task "Prep for {{contact_name}}" due in 1 day.

## Safety, in plain terms
- Every rule needs a one-sentence "what's it for" — that's what shows in the
  audit trail next to everything it does.
- Rules see and touch **only your business**. That isolation is structural,
  not a setting.
- A rule can never trigger itself, and chains of automations stop at depth 3
  — no runaway loops.
- **Pause all** stops every automation instantly; each rule has its own
  on/off too.
- "What my automations did" (in the panel) lists every run: what fired, what
  matched, what happened.
- A broken rule never breaks the booking or contact that triggered it — the
  business event always wins.

## What it can't do (yet)
Custom calculations, calling other apps, and multi-step branching workflows
are the **Advanced (Tier 2/3)** layer — coming after this one proves itself.
If you hit the wall, tell Chief what you wanted to build; that's exactly the
signal that shapes what ships next.
