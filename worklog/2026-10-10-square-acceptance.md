---
title: Square sandbox acceptance and setup guidance
date: 2026-10-10
agent: Codex (GPT-6)
asked: "yes you can. approved"
status: in progress
left_undone: ["free sandbox Appointments activation approval", "successful live booking preview", "external grant revocation acceptance"]
---
Real OAuth consent and callback passed against Default Test Account. Location discovery/save passed. Booking preview returned Square 401 UNAUTHORIZED: Merchant not onboarded to Appointments. The frontend incorrectly described every 409 as a changed connection/location. Added allowlisted application error codes and fixed local UI copy without echoing provider bodies. No permission changes. Disconnect completed successfully and cleared the selection; reconnect acceptance is in progress. Automatic approval review blocked sandbox Appointments activation pending specific user approval; that question is open. Regression coverage includes the observed provider error, unrelated-endpoint authorization behavior, unknown error codes, diagnostic redaction and mobile wrapping.
