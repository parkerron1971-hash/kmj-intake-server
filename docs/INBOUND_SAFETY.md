# Inbound safety: "Needs a look"

**Hold the automation, never the person.** A card that looks like a pitch or a
scam is never refused, hidden or thrown away. The visitor sees the same
thank-you. The office can read every word. What waits until a person says
"real" is everything the system would do **on its own** because of the card.

Why: on 2026-11-22 and 11-26 two connect cards from one "Tourist catalogue"
campaign reached Love City's website. Each one became a guest, a volunteer
call, five or more "still waiting" alerts and a morning brief that said to
welcome her first. Kevin's decisions (2026-11-27): build "Needs a look" now. A
held card is a contact with a "held" mark and a badge in Members. Add the shared
cross-church scam list (two-church rule, salted hashes only) and the Haiku
second opinion on mid-score cards, never on prayer. No Turnstile until bots show
up. The member warning is per church, offered by Chief.

## The pieces

| Module | What it does |
|---|---|
| `inbound_risk.py` | One deterministic verdict for every door, `clear`, `needs_look` or `bot`, with plain reasons. It also makes the fingerprints (salted hashes), gathers what the church already knows, and asks for the second opinion. |
| `inbound_hold.py` | The hold, the queue, the three taps and undo, the shared list, Chief's turn block, the send gate's check, and the routes. |
| `chief_inbound.py` | Chief's verbs `mark_real_person`, `mark_not_a_guest` and `undo_inbound_decision` (class A). |
| `supabase/APPLY-2026-11-27-needs-a-look.sql` | Four server-only tables: `inbound_checks`, `inbound_decisions`, `inbound_senders` and `inbound_shared_list`. |

Doors wired today: the website **connect card** and **contact form**
(`/sites/{id}/contact-submit`), plus the website **prayer request**, which is
flagged but never held. Not wired yet: intake forms, booking, website chat,
texts in and church mail (proposal §4.3).

## The signals (inbound_risk.WEIGHTS)

A card at **3 points or more** needs a look (`INBOUND_HOLD_AT`).
`INBOUND_RISK_WEIGHTS='{"sales": 2}'` overrides any weight.

| Code | Points | What staff read |
|---|---|---|
| junk_phone | 2 | The phone number isn't real (under 7 digits, one digit repeated, 1234567890, a digit and nine zeros, an area code starting with 0 or 1) |
| short_phone | 1 | The phone number looks incomplete (7–9 digits: often a local number without its area code) |
| link_foreign / link | 2 / 1 | Asks you to visit x.com (1 point when it is the sender's own domain or a social site; the church's own domains don't count) |
| sales | 2 | Reads like a sales pitch (listing, catalogue, SEO, ranking, backlinks, website traffic, sponsorship, free trial, commission, …). Not "Google Maps", "registration link" or a bare "advertisement": real seekers write those (review should-fix 4). |
| money | 3 | Asks about money or gift cards (gift cards, wire transfer, crypto, "processing/customs/activation fee", …) |
| payment_app | 1 | Mentions a payment app (Zelle, Venmo, Cash App or PayPal on its own; real people ask how to give) |
| reply_yes | 1 | Asks you to reply 'yes' or click a link |
| fake_follow_up | 1 | Says it wrote before; nothing from them is on file |
| impersonation | 3 | Uses Kevin Carter's name from an address that isn't theirs (the church's leaders by name) |
| name_email_mismatch | 1 | The name doesn't match the email address |
| disposable / no_mx / new_domain | 2 / 2 / 1 | A throwaway email address / can't receive mail / the domain is N days old (RDAP, **off** unless `INBOUND_RDAP=on`, because the domain would go to rdap.org). Shared mail (free providers, ISPs like `*.rr.com`, juno.com, `yahoo.co.uk`, and bare public suffixes) is never looked up. |
| seen_here | 2 | The same email, phone or words (or a throwaway/curated domain) as a card already held here in the last 14 days |
| seen_elsewhere | 3 | The same long words at another church, or the same address at two or more, in 7 days |
| shared_list | 3 | Other churches marked this sender as a scam |
| scam_before | 3 | You marked this sender as a scam before |
| known / real_before | −3 / −3 | Already on your roll / You said they're a real person before. A church's own Real **always** wins: the card is clear. |
| bot | → bot | Honeypot filled, or sent in under 3 s. The step-1 Fix (branch m5-contact-submit-bot-checks) catches bots before validate, so contact-submit never passes these. |

On the real shapes: the second card scores 7 (9 once the first one is held),
the first card scores 6, and a real guest ("Loved the worship… my cousin
invited me") scores 0. `__tests__/test_inbound_risk.py` holds the corpus.

**Second opinion.** Only a clear card scoring 1–2 goes to Claude Haiku 5.5, and
never a prayer request. The model answers person, pitch or scam. It can only
raise a card to needs_look, never clear one. It goes through the `llm_call`
seam (metered, `task="inbound_second_opinion"`) and is skipped over the day's
spend cap. A 4 s timeout or any error keeps the deterministic verdict.
`INBOUND_SECOND_OPINION=off` turns it off. A card from a sender this church
said is real is never sent to it (its own Real always wins).

## What a hold holds

| Held (until Real person) | Never held |
|---|---|
| The guest follow-up and its volunteer call, which also stops the "still waiting" alerts (`church_follow_up.on_connect_card`) | The contact, the card in Notes, the event, the email notice to the church |
| The Welcome Path and its texts | The visitor's thank-you |
| The "New connect card" alert, replaced by one quiet line: "1 card needs a look" (12 h dedup, never the sender's name) | Prayer requests: delivered to the people who pray, with `submission.needs_a_look = {label: "May not be genuine", reasons}` |
| Lead scoring and Chief's proposed reply (`chief_agent.nudge`) for a contact form | |
| The morning brief's new leads and guests (held people are taken out; the brief says only how many wait) | |
| Chief suggesting a welcome (its block says they are not guests) | |

The email notice says so too. The subject starts `[Needs a look]`, a banner
lists the reasons, and there is no `reply_to`, so a quick reply can't confirm a
live inbox.

A hold is recorded **before** anything is skipped. If the `inbound_checks` row
can't be saved (before the APPLY file, or in an outage), the card runs as it
always did.

## The three taps

- **Real person** releases each held card, oldest first, exactly as it would
  have run (the follow-up, the Welcome Path with the card's own "Text me" yes,
  or for a contact form, scoring and the nudge). A card released before and
  put back reopens its own follow-up. This church remembers the sender by
  email, phone and words, never by domain, so their next card is clear. The
  "New connect card" alert is **not** replayed, on purpose: the person who
  released the card has just read it.
- **Not a guest** works on anyone, held or not. In this order: it cancels their
  queued Welcome Path texts (marked `last_error = "Needs a look: marked not a
  guest; not sent."`), closes their open follow-ups (through
  `church_follow_up.close_for_contact` from #2097 once that merges, with an
  office note, or its own loop before then), then marks them inactive. If the
  person doesn't save, the texts and follow-ups go back and nothing changed.
  #2097's `reopen_for_contact` only touches its own inactive closes and
  texts, never these.
- **Scam** does the same as Not a guest, and the sender's hashes count toward the
  shared list.

Every tap writes an `inbound_decisions` row (what it changed) and an `audit_log`
line (who, when, which signal codes, never the words). Undo works for a week,
on a person's **latest** tap only, and once. The row is claimed before anything
moves, so two screens can't both put it back. It restores exactly what that tap
took, by the ids it recorded: the follow-ups it closed reopen, the texts it
cancelled are queued again if their time hasn't passed, the status and the
sender memory go back, and after a Real the Welcome Path state is put back so
it can start again.

## The shared list (§4.4)

- Only salted HMAC-SHA256 hashes: the email address, the phone (never a junk
  one), and a fingerprint of what they wrote in their own words (the message
  and notes, never the ticked choices), with names, addresses, links and
  numbers taken out. **A domain is never remembered or shared**, except a
  throwaway inbox or one on the curated abusive list (`INBOUND_ABUSIVE_DOMAINS`).
  An ISP, a free provider or a company's mail would hold every real person who
  shares it (review must-fix 2). The salt is `INBOUND_HASH_SALT`, otherwise one derived
  from the service key. Changing it starts the lists over.
- A sender goes on the list when **two different churches** tap Scam within 30
  days, or when the platform owner adds them (`share: true` on their own Scam
  tap, or `POST /platform/inbound/shared-list`). It ages out 90 days after the
  last tap. One church taking its Scam back below two takes the entry off.
- A hit is **+3 and a reason, never a block**. A church's own Real always wins
  there.

## Chief (§L5)

- **Context.** For the turn's tail, `inbound_hold.turn_line` lists the held
  people by name with their reasons (defused), and nothing they wrote. It tells
  Chief never to suggest welcoming one, and offers `mark_real_person` and
  `mark_not_a_guest`. Scam is never Chief's.
- **Sends.** A class-C send to a held person, or to one marked Not a guest or
  Scam, is held, the same way as a tainted turn. The practitioner's own "go
  ahead" releases it (`chief_holds`).
- **Who may.** The verbs: a signed-in Manager seat or above, never unattended.
  Area: People & care.

## The switch

`INBOUND_SAFETY` on kmj-intake-server:

| Value | Effect |
|---|---|
| `off` (default) | Nothing checked |
| `watch` | Every door checked and recorded, nothing held. Use it to tune the weights against real cards first. |
| `owner` | On for the platform owner's businesses (Love City) |
| `on` | On for every business |
| `<id>,<id>` | On for the listed businesses only |

`INBOUND_RDAP=on` turns the domain-age lookup on (off by default; name rdap.org
on the privacy page first). `INBOUND_ABUSIVE_DOMAINS=a.com,b.net` is the curated
list of abuse-only domains.

## API contract (for the front end)

All routes need a signed-in Manager seat or above at the business. Anything less
gets the same 404 as "no such business" (`business_access`).

### The queue: `GET /inbound/{business_id}/needs-a-look`

```json
{
  "on": true,
  "count": 1,
  "people": [{
    "contact_id": "uuid",
    "name": "Sara Moreno",
    "email": "sara@…", "phone": "1000000000",
    "door": "connect_card",            // or "contact_form"
    "score": 7,
    "reasons": ["The phone number isn't real", "Asks you to visit touristsector.com", "Reads like a sales pitch"],
    "at": "2026-11-26T08:30:00Z",      // newest card
    "cards": 1,                        // how many cards of theirs wait
    "preview": "Hello, I wrote to you a few days ago…"   // up to 280 characters of what they wrote
  }]
}
```

Newest first, one row per person. `on` false means the switch is off for this
business: show nothing.

### The badge (Members)

- `GET /church/roll`: every person row gains `needs_look: bool` and
  `needs_look_reasons: [str]` (up to 4). The roll is kept a little while per
  replica. A tap clears that replica's copy; pass `fresh=1` on the next read if
  needed.
- The mark itself is `contacts.metadata.inbound_hold`: `{state: "needs_look",
  door, score, reasons, at, check_id}`. After a tap, `metadata.inbound_decision`
  is `{verdict, at, by, decision_id}`.

### The buttons: `POST /inbound/{business_id}/people/{contact_id}/{decision}`

`decision` is `real`, `not-a-guest` or `scam`. The body is optional: `{"share":
true}` is honored only for the platform owner, on `scam`.

```json
// real
{"ok": true, "decision_id": "uuid", "verdict": "real", "contact_id": "uuid", "name": "Sara Moreno",
 "released": 1, "follow_ups_opened": 1,
 "said": "Sara Moreno is a real person. Their follow-up has started and their welcome goes on as usual."}
// not-a-guest / scam
{"ok": true, "decision_id": "uuid", "verdict": "scam", "contact_id": "uuid", "name": "Sara Moreno",
 "follow_ups_closed": 1, "texts_cancelled": 0, "shared": false,
 "said": "Sara Moreno is marked a scam: follow-ups closed, off the Welcome Path, inactive. Don't reply to Sara or open any link they sent."}
```

Show `said` as the confirmation. The errors are `{detail}` with words a person
reads: 404 (not here / not allowed), 503 (couldn't save; nothing changed).

### Undo: `POST /inbound/{business_id}/decisions/{decision_id}/undo`

```json
{"ok": true, "decision_id": "uuid", "contact_id": "uuid", "needs_look": true,
 "said": "Put back. They're waiting for a look again."}
```

409 means it was already put back, or the tap is more than a week old.

### The alert

There is one `chief_notifications` row of type `urgent_alert`, titled "1 card
needs a look" or "N cards need a look", with `action_payload {type: "navigate",
tab: "operate", sub: "contacts", filter: "needs_look"}`. Open Members filtered
to the badge.

### Prayer

A website prayer request that scores carries `submission.needs_a_look =
{label: "May not be genuine", reasons: [str], score}` on its
`ministry_care_requests` row. Show it as a quiet badge on the request. It is
never held.

### Platform owner only

- `GET /platform/inbound/shared-list` returns `{total, by_source: {churches: {email: n, …}, platform: {…}}}`. It never returns a hash.
- `POST /platform/inbound/shared-list` with `{business_id, contact_id}` puts that sender on the list.
- `DELETE /platform/inbound/shared-list?business_id=&contact_id=` takes them off.

## Checking it

- `pytest -q __tests__/test_inbound_risk.py __tests__/test_inbound_hold.py`
- `PGLITE_MODULE=… node __tests__/needs_a_look_db.mjs` (the APPLY file on real Postgres)
- Live, after the APPLY file: set `INBOUND_SAFETY=watch` and read `inbound_checks` for a week. Check every held verdict by hand (there are very few cards), then switch to `owner` on a Thursday.
