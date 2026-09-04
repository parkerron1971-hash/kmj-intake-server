# The agent-readable site — every practitioner's site, legible to a customer's agent

**Status:** shipped 2026-09-04 (`agent_site.py`, wired through `public_site.py`).
Strategy: `future_architecture.md` §3 "Inbound (customers' agents)" and §7 Arc 1.
Companion to `AGENT_CONNECTOR.md` (the practitioner's own agent, outbound) — this is
the other direction.

## What a customer's agent finds

| Where | What | Cost to us |
|---|---|---|
| Every served page, `<head>` | schema.org JSON-LD: `LocalBusiness` (contact, address, `openingHoursSpecification` from the **booking engine's** weekly hours, `sameAs`, `ReserveAction` → `/book`) plus one `Service` / `Product` / `Course` / `Event` node per active offering, with an `Offer` only when the practitioner shows the price. Replaces the builder's build-time `LocalBusiness` block, which read a free-text hours string that disagreed with the engine. | 3 service-role reads per business, cached 60 s |
| `https://<site>/.well-known/agent.json` | The manifest: name, contact, hours, the offerings, a `capabilities` block, and the API endpoints below by absolute URL. When the vertical refuses a client surface (therapy, law, counselling — `vertical_scope`), the booking endpoints are **absent**, not refused later. | same bundle |
| `https://<site>/llms.txt` | The same facts as a plain-language sheet an LLM crawler reads first. | same bundle |
| `GET /public/agent/{slug}/services` | Offerings, customer-safe shape. | one cached bundle |
| `GET /public/agent/{slug}/availability?offering_id=&from=&to=` | Open slots for **one** offering on a bounded run of days (≤ 14). The widget's `config-anon` computes 30 days for every offering; an agent asking about Thursday pays for Thursday. | one bookings read + the slot engine |
| `POST /public/agent/{slug}/book` | Books on a customer's behalf, riding the **same** walk-in flow the human widget uses (`book_anon`): contact dedupe, offering denormalization, the double-book guard, confirmation email + `.ics`, SMS-consent record. `agent` is a required field; the ledger row says `actor_type=client`, `actor_id=agent:<name>`, `authorized_by=client:agent`. | the walk-in flow |

## The rules every endpoint applies, in order

1. `rate_limit.allow_strict("agent_site", ip)` — **fails closed** (`RL_AGENT_SITE_PER_MIN`, default 60).
2. Slug → business (404 otherwise).
3. `policy_engine.evaluate_client(actor="client_agent")` — the client layer's own evaluator, fails closed. The vertical gate it carries is the reason a therapist's manifest has no booking door.
4. For `availability` and `book`: booking must be live (`booking_is_live`), and the offering must be a bookable category with a duration.

The page-level artifacts (JSON-LD, manifest, llms.txt) carry only what the public page already prints, so they are not gated — but they **fail soft**: any error returns the page unchanged or falls through to the normal handler.

## What it deliberately does not do

- **No model call anywhere.** The Site Concierge is a fenced conversational agent behind LLM spend and daily caps; a crawler-facing surface that invoked a model would be a bill. Nothing here does.
- **No change or cancellation of an existing booking, no message to the business, no payment.** The manifest says so in `capabilities` and `rules`, so an agent is told rather than refused.
- **No 24/7 claim.** An open-default business (no weekly hours set) is bookable any time by the engine's rule, and gets **no** `openingHoursSpecification` rather than "open around the clock".
- **No new permission model.** The verdict is the client layer's; the ledger vocabulary is the ledger's.

## Operating notes

- The bundle cache is 60 s per business, in-process. An offering edit shows up on the next cache miss.
- The manifest names the API host from `MCP_PUBLIC_BASE_URL` (default Railway prod) — the same origin the MCP discovery documents use.
- `book` shares the walk-in limiter too (`book-anon`, 10/hour/IP, in-memory) on top of the agent bucket.
- To widen: a new capability is a new key in `manifest()["capabilities"]` and a new endpoint here, gated the same way. Never add a capability the endpoint does not exist for.
