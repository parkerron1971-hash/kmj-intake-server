---
title: Square pilot rollout
date: 2026-10-10
agent: Codex (GPT-6)
asked: "ok finish work on it"
status: waiting on Kevin
prs: [kmj-intake-server#1356, solutionist-studio#1183]
migrations: ["APPLY-2026-10-08-square-connections.sql (applied 2026-10-10)", "APPLY-2026-10-09-square-locations.sql (applied 2026-10-10)"]
left_undone: ["Square developer sign-in", "store Sandbox OAuth application secret", "enable owner-only sandbox pilot and complete real OAuth/preview/disconnect acceptance"]
decisions: ["approved read-only pilot; no public production-seller enablement", "preserve current trunk changes"]
related: [2026-10-09-square-location-preview.md]
---
Integrated current trunk and resolved additive release-note/environment-example conflicts, retaining both sides. Revalidated 134 backend tests, 51 isolated PostgreSQL checks, and 22 browser tests; frontend production build passed. Railway target and Supabase project verified. Square developer browser session expired; Kevin has been asked to sign in while deployment preparation continues. No credentials recorded in source or logs.

Release review: fixed stale disconnect completion reporting and reduced consent to the three scopes needed by bookings/locations. Missing status routes now show a retryable error; the global release note explicitly says general access is not open. Official Square documentation does not establish 401/403 as successful revocation, so that case remains fail-closed pending a live test. Sandbox variables and a new encryption key are staged in Railway with SQUARE_ENABLED=false; the allowlist contains only the verified platform owner.

Review fixes validated: 137 backend tests and 23 browser checks passed, including the stale-disconnect and missing-route regressions.

Live navigation preflight found the OAuth return link used an unsupported top-level hash. Corrected it to /#/build/integrations, verified against SolutionistLayout routing, and added coverage to the OAuth round-trip regression.

Rollout: backend #1356 merged as c95fed7311f4739568b741d7a1e59c3df1377667 and Railway deployment c5b1bf4c-57f4-416f-a91b-536b56097e15 succeeded. Frontend #1183 merged as 5e2f91e506277620912ff3a7a24f47216b5e51ab after full frontend CI passed. Both migrations applied to the verified production Supabase project; live results: RLS true, policies 0, location columns 3, service-only SECURITY INVOKER functions 8, browser table access false, service table access true. Status/locations endpoints reject unauthenticated requests with 401; OAuth entry/callback fail closed with 503 while disabled. No Square merchant has been connected and no bookings imported. Sign-in is the remaining external blocker. The SQL editor initially combined text during the second paste; that attempt failed parsing. Replaced the entire editor with verified exact SQL and then successfully applied the location migration.

Frontend production verification: Vercel deployment 7y9ktja9AGdYwMwdMQoxbDpNNzG2 succeeded for merge commit 5e2f91e506277620912ff3a7a24f47216b5e51ab. The public app entry leads to main-D0XPMhsB.js → PractitionerBuild-C1Q1TaIF.js → IntegrationsHub-Bp0sUXql.js; the final asset contains Square Appointments and /square/bookings/preview. Both implementation deployments are complete. The remaining handoff is only private secret configuration and real sandbox acceptance after Square sign-in.
