---
title: Chief retrieves timestamped weather directly
date: 2026-10-02
agent: Codex (GPT-6)
asked: "Weather keeps searching old pages and asking to retry"
status: in progress
prs: []
migrations: []
left_undone: ["Parent integration and deployment", "Production voice confirmation"]
decisions: ["NWS public API, no paid geocoder", "Current observations and forecasts remain separate evidence", "No business writes in weather evaluation"]
---
Added a Chief-only get_weather read through the existing registry/tool handler and
evidence path. NWS city/state or ZIP search resolves coordinates; its redirect is
parsed without following arbitrary hosts. Fixed-host API reads have a 12-second
total bound, at most six requests, and retain fresh observation/forecast times.
Missing, stale, future, or expired data is withheld. Ambiguous locations need a
city/state; international weather retains existing search guidance.

Weather instructions now prefer this direct read and preserve the last owner
weather request across a short yes/retry. Typed forecast-only evidence cannot
prove current conditions, including early speech. Server-derived local times
and rounded measurements remain citable under the unchanged numeric guard.
Exact weather topic headings no longer pretend to be condition assertions.

The real-model fictional-business evaluation used get_weather, no web search,
for both the direct question and yes retry. Both final answers retained their
observation and passed factual review (12.1s/13.8s, context already prepared;
not production end-to-end timings). The public NWS read itself took about five
seconds. scripts/chief_weather_eval.py is an opt-in repeatable evaluation with
normal provider metering and no business write tools.

Validation: 239 focused weather, provenance, early speech, tool-loop, registry,
and MCP tests passed. Independent review re-ran weather/provenance tests and
cleared the current-versus-forecast evidence boundary.

Official references: https://www.weather.gov/documentation/services-web-api and
https://www.weather.gov/ForecastSearchHelp.html. The public named-location
redirect is an HTML-site interface, so failures are handled as unavailable or
ambiguous rather than guessing coordinates. Backend work logs showed no existing
native weather lookup; the local frontend checkout had no worklog directory.
