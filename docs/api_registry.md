# API Registry — every external service the Solutionist System touches

> Companion to Mission Control → System Health → "Connected services",
> which reports live configured/missing status from this same registry
> (`platform_console.py: API_REGISTRY`). Update BOTH when adding a
> dependency. Env var NAMES only — never values.

| Service | Env keys | Powers | Code touchpoints |
|---|---|---|---|
| Supabase | SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_JWT_SECRET | Database, auth, RLS, storage, realtime — system of record | sb_clients.py, every router |
| Anthropic (Claude) | ANTHROPIC_API_KEY | Chief chat + reasoning lanes, site composer, atelier, DRL, module composer | chief_llm.py, chief_models.py, site_composer.py, atelier.py |
| OpenAI | OPENAI_API_KEY | Chief voice (TTS), Whisper transcription, inference-gate embeddings | whisper_proxy.py, inference gate |
| Twilio | TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER | SMS rail — keywords, two-way texting, booking reminders | sms_service.py, sms_routing.py, sms_alerts.py |
| Resend | RESEND_API_KEY | Transactional + nurture email, ticket replies, reports | email senders (chief_of_staff.py, agents) |
| Stripe | STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET | Subscriptions, payment links, PAYG (dormant until enforcement) | billing routers, stripe_webhook_events |
| Meta (FB/IG) | META_APP_ID, META_APP_SECRET | Facebook + Instagram OAuth and publishing | meta integration router |
| Web Push | VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY | Chief notifications to phones (PWA push) | push sender |
| Google Fonts | (no key) | Font pairings on composed sites (css2) | brand_dna.py |

## Platform hosting (not env-driven from this repo)
- **Railway** — this backend (`kmj-intake-server`, main branch auto-deploys)
- **Vercel** — frontend (`solutionist-studio`, module-system branch auto-deploys)
- **Domains** — mysolutionist.app (marketing via Railway), system.mysolutionist.app (app via Vercel), *.mysolutionist.app (published sites + /book)

## Known blind spots (also reported by /platform/health)
See `BLIND_SPOTS` in platform_console.py — error streams, client error reporting, storage usage, Meta token expiry alerts, Resend bounce webhooks.
