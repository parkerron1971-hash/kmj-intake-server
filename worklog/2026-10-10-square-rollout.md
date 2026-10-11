---
title: Square pilot rollout
date: 2026-10-10
agent: Codex (GPT-6)
asked: "ok finish work on it"
status: waiting on Kevin
prs: [kmj-intake-server#1356, solutionist-studio#1183]
migrations: ["APPLY-2026-10-08-square-connections.sql (applied 2026-10-10)", "APPLY-2026-10-09-square-locations.sql (applied 2026-10-10)"]
left_undone: ["approve and activate free sandbox Appointments", "successful live preview and external-revocation acceptance"]
decisions: ["approved read-only pilot; no public production-seller enablement", "preserve current trunk changes"]
related: [2026-10-09-square-location-preview.md]
---
Integrated current trunk and resolved additive release-note/environment-example conflicts, retaining both sides. Revalidated 134 backend tests, 51 isolated PostgreSQL checks, and 22 browser tests; frontend production build passed. Railway target and Supabase project verified. Square developer browser session expired; Kevin has been asked to sign in while deployment preparation continues. No credentials recorded in source or logs.

Release review: fixed stale disconnect completion reporting and reduced consent to the three scopes needed by bookings/locations. Missing status routes now show a retryable error; the global release note explicitly says general access is not open. Official Square documentation does not establish 401/403 as successful revocation, so that case remains fail-closed pending a live test. Sandbox variables and a new encryption key are staged in Railway with SQUARE_ENABLED=false; the allowlist contains only the verified platform owner.

Review fixes validated: 137 backend tests and 23 browser checks passed, including the stale-disconnect and missing-route regressions.

Live navigation preflight found the OAuth return link used an unsupported top-level hash. Corrected it to /#/build/integrations, verified against SolutionistLayout routing, and added coverage to the OAuth round-trip regression.

Rollout: backend #1356 merged as c95fed7311f4739568b741d7a1e59c3df1377667 and Railway deployment c5b1bf4c-57f4-416f-a91b-536b56097e15 succeeded. Frontend #1183 merged as 5e2f91e506277620912ff3a7a24f47216b5e51ab after full frontend CI passed. Both migrations applied to the verified production Supabase project; live results: RLS true, policies 0, location columns 3, service-only SECURITY INVOKER functions 8, browser table access false, service table access true. Status/locations endpoints reject unauthenticated requests with 401; OAuth entry/callback fail closed with 503 while disabled. No Square merchant has been connected and no bookings imported. Sign-in is the remaining external blocker. The SQL editor initially combined text during the second paste; that attempt failed parsing. Replaced the entire editor with verified exact SQL and then successfully applied the location migration.

Frontend production verification: Vercel deployment 7y9ktja9AGdYwMwdMQoxbDpNNzG2 succeeded for merge commit 5e2f91e506277620912ff3a7a24f47216b5e51ab. The public app entry leads to main-D0XPMhsB.js → PractitionerBuild-C1Q1TaIF.js → IntegrationsHub-Bp0sUXql.js; the final asset contains Square Appointments and /square/bookings/preview. Both implementation deployments are complete. The remaining handoff is only private secret configuration and real sandbox acceptance after Square sign-in.

Sign-in continuation: securely transferred the existing Sandbox OAuth application secret into Railway and enabled the sandbox-only, single-owner pilot. Activation deployment bfe499a8-e7d0-4c3f-8a00-6ab8b5326e70 succeeded at the existing backend merge commit. Launched Default Test Account in the Sandbox Seller Dashboard. The deployed Solutionist Square card shows Sandbox / Not connected and its Connect button successfully reaches Square consent with appointment, all-appointment/calendar, and merchant-profile reads only. Browser action-time permission confirmation requested at the actual consent screen; no grant, callback or preview success is claimed while it is pending. No payment settings changed.

Approved-consent continuation: real OAuth callback succeeded; Default Test Account location discovered and saved; disconnect completed with Square grant revocation and cleared location state; reconnect callback succeeded. Booking preview returned the specific Square condition Merchant not onboarded to Appointments (401 UNAUTHORIZED), confirmed in the Square API log. Automatic approval review blocked free sandbox Appointments activation pending specific approval, now requested. Separate backend #1368 and frontend #1195 correct misleading setup/authorization messages; the frontend also guards an existing null email status on the OAuth return page. Focused tests: 49 backend and 26 browser passed; typecheck gates passed with zero live errors and the existing 14 legacy baseline. Successful live preview and external-revocation acceptance remain unverified.

Acceptance fixes: frontend #1195 merged at 91fd5808d319cefda7ef1e6272ac74c151a40552; full CI/review passed and production deployment 6988809946 succeeded. Reloaded live Integrations successfully and verified reconnect cleared saved locations, then restored the test location. Backend #1368 merged at 6bba3d5b09f44b66dae2bb6d5d98a627c9a8a802 after full CI 38098017737 passed. Focused backend count is now 53, including sanitized drift/malformed-response diagnostics. Backend deployment d888ebbd-c9b3-4202-99de-5e85482f8c1a succeeded. Live preview confirmed the corrected fixed setup guidance without losing the connection or saved location.
