# Tico's Antigravity runner

Tico (`coo`) uses `runtime: gemini`, `harness: antigravity`, model
`gemini-3.8-flash`, and low effort. Its fallback is the Gemini CLI on the same
model, set in Settings and visible as `gemini`. Other Gemini bots keep their
existing CLI unless their configuration explicitly selects this harness.
OpenRouter is not a bot harness.

Install and authenticate Google's `agy` CLI on the assigned runner machine.
The current machine uses Antigravity's existing Google account sign-in. Its
global settings are not changed by Tico. A Gemini API key alone does not select
Antigravity's API-key provider; follow Google's CLI settings documentation if
switching that authentication mode. Preflight checks the executable; a real
turn verifies authentication.

The runner keeps a separate NDJSON process per bot, person, conversation, session
epoch, model, and effort. Idle processes expire after 15 minutes; the cache is
bounded to eight idle sessions. Provider conversation IDs are saved locally so
an evicted session can resume. Failed or interrupted turns are never replayed
automatically. Changing the model or starting a new chat creates a separate session.

Only the initial turn gets the recent conversation bootstrap (up to 30 messages).
Later turns send messages after the last successfully delivered user request,
including relevant intervening bot messages, without repeating the current
request. Bot instructions and current execution restrictions still accompany
each turn.

The child process never receives the machine registration credential. Its
`HUB_TOKEN` is a `tico-file:` reference to a mode-600 local lease file. The Hub
Python client reads that file on every request; it is rotated to the current
attempt credential and cleared when the turn ends. Bots must use the Hub client
or `dispatcher/hubcli.py`, rather than treating `$HUB_TOKEN` as a literal bearer
token. The server continues to enforce the current attempt's permissions.
Changed environment credentials discard the warm process. External service
credentials granted to a bot remain in that process until it expires or stops.

Runner readiness probes run separately from the 250 ms claim loop. Tico flushes
streaming output every 150 ms. Voice playback consumes bounded PCM chunks from
`/api/v2/voice/speech/stream`; stop cancels both playback and generation. Completed
sentences may endpoint after 500 ms of silence, while other speech retains the
800 ms window. The microphone noise calibration is retained between turns.
Telemetry distinguishes endpoint delay, model completion, provider first audio,
and browser playback start. Browser playback timing measures the AudioContext
clock, not the physical speaker. Speech still begins after the final model reply.

Run the backend and Chromium/WebKit streaming checks before deploying
merged main changes. A runner upgrade must wait for active work to finish before
restarting its launchd service; the server's deployment drain is separate.

Google documentation: [headless CLI](https://www.antigravity.google/docs/cli/headless/),
[authentication settings](https://www.antigravity.google/docs/cli/settings/).
