# Continuous voice output

The browser prepares /ai/tts/stream while the model is thinking. Its first message contains the Supabase JWT, business ID and selected el: voice ID; the server verifies the token and business owner before opening ElevenLabs. Credentials never enter the URL. Only bounded text frames can be submitted, with a 180-second session limit and 16,000-character cap. The existing monthly allowance applies.

One provider connection carries the response's phrases and streams PCM at 24 kHz back to the existing player. A short settling timer releases terminal punctuation without waiting for another model delta. The first natural phrase can start before sentence completion. Continuous playback keeps its tail and survives thinking gaps; stop cancels the transport and queued audio. A pre-audio failure uses the existing HTTP fallback; already played audio is never restarted.

Model: ELEVENLABS_TTS_MODEL defaults to eleven_flash_v2_5. Roll back to eleven_turbo_v2_5 if needed. CHIEF_ELEVEN_STREAM=off disables the relay; browser localStorage chief-eleven-stream=off selects legacy sentence HTTP streaming. The selected voice remains unchanged.

[speech flow] logs first provider audio latency without text or credentials. Browser voice-debug milestones separate first speakable phrase, first TTS bytes, and audible playback. Synthetic benchmark: python scripts/chief_voice_smoke.py <selected_voice_id> with provider credentials already in the environment. Outputs are local WAV fixtures.

Factual review no longer returns unverified claim lists. Unsupported side claims are cut, then the remaining claims are checked with the existing evidence. Review metadata keeps the details. Essential missing data and failed/completed actions remain explicit; public rules retain one short qualification. No database migration.
