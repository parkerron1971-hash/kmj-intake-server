# Lane buyer integration: connection verification

This document describes the read-only connection probe. The private purchase pilot
is documented in LANE_PILOT_SETUP.md. Neither integration installs Lane seller auth
or changes Solutionist's existing inbound MCP authentication.

## Private pilot configuration

Set these in the backend secret store, not browser configuration or Git:

- LANE_PILOT_ENABLED=true
- LANE_PILOT_BUSINESS_ID: the authorized business UUID
- LANE_PILOT_USER_ID: that business owner's user UUID
- LANE_PILOT_API_KEY: a personal Lane wallet key from
  https://wallet.getonlane.com (Settings > API)

Never paste a key into Chief chat. A key acts as its wallet owner. Do not share
one owner's key across customers. Turning the enable flag off blocks verification;
rotate/revoke the key in Lane to revoke the credential itself.

GET /lane/wallet/{business_id} reports configuration only. It does not contact
Lane or claim a verified connection. POST .../verify initializes an MCP session,
lists tools, and closes the session. Only a verified Supabase user who owns the
configured business can run it. Results are not persisted or cached.

A successful check proves that Lane accepted the key and advertised tools.
It does not prove card enrollment, eligible business cards, merchant coverage,
affordable pricing, or successful checkout. The authorized owner's real key passed
a read-only connection check on 2026-09-24. Unit tests use a mocked transport and
synthetic credentials; no live purchase has been tested.

## Purchase safeguards and rollout requirements

- Tenant-bound durable purchase records and a single execution claim per approved
  purchase; no blind retry after a timeout or an unconfirmed order.
- Render Lane's exact terms, selected funding method, and maximum total.
- The real user approves; provider output or model text is never consent.
- For Visa passkey cards, use the returned Lane approval URL. An in-chat yes
  cannot replace that verification. Confirm supported embedding with Lane.
- Relay login/password/code requests through Lane's own secure URL, not AI chat.
- Distinguish approved/chargeable from placed; only checkout confirmation proves
  an order. Support cancellation, refunds, and receipt reconciliation.
- Use separate customer credentials through paid organization onboarding before
  customer rollout. Confirm Lane's business-card eligibility and commercial terms.

Lane's intent_submit test flag has no effect in production. Never treat it as
a safeguard against real purchases. The probe never calls tools; the purchase module
uses a separate allowlisted adapter and an explicit checkout activation flag.

## Sources

- https://docs.getonlane.com/buy/mcp/quickstart
- https://docs.getonlane.com/buy/mcp/best-practices
- https://docs.getonlane.com/buy/organizations/basics
- https://docs.getonlane.com/api-reference/mcp/intent_get_terms
- https://docs.getonlane.com/api-reference/mcp/intent_submit
