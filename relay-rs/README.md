# Computer screen relay pilot

Opt-in Tokio/Axum sidecar. Python retains every permission check, runner authentication, durable
screen mode and audit event. Rust owns temporary tickets, admission limits, socket pairing,
buffers, deadlines and cancellation. No session table is added. Default installations retain Python.

## Routing contract

Only these existing WebSocket paths go to Rust, with their query strings and Authorization/Origin
headers intact. All other requests go to Python, including creation, mode changes and pending lists.

- `/api/v2/runners/{rid}/screen/ws?ticket=...` (browser)
- `/api/v2/runners/me/screen/{session_id}/ws` (runner)

Python's `/_tico/screen/v1/authorize` and Rust's `/control/v1/*` are private and require an independent
32-byte-or-longer shared secret. Ingress must refuse the private prefixes. Bind to loopback or an
isolated container network, never publish a control port. Both hops use the trusted local network;
remote multi-host deployment is outside this pilot. Never reuse an owner or runner token as the key.
The runner and browser URLs, TLS termination, cookies, Cloudflare Access and public hostnames stay
as configured. Native/direct installations opt in through a local reverse proxy; the normal installer
and direct Python entrypoint remain supported with the default implementation.

## Version 1 control protocol

All JSON responses identify the Rust `boot` UUID. Commands carry a monotonic sequence number; stale sequences fail and the most recent exact retry is
idempotent, so delayed grant/control requests cannot resurrect closed sessions. All commands require the shared secret in
`Authorization: Bearer ...`. Commands are serialized in Python and applied atomically in Rust.

1. `GET /control/v1/hello` returns a one-use `challenge` and boot ID. `POST /control/v1/start`
   consumes the challenge with a fresh Python `lease` UUID, closes every previous session, clears
   mode generations and returns the boot ID. A delayed start with a used challenge cannot take over
   a newer lease. Repeating the currently active start is harmless.
2. `POST /control/v1/command` carries `lease` and a tagged `op`. Every operation refuses an expired
   or superseded lease. `heartbeat` renews a six-second monotonic lease, acknowledges durably
   recorded close IDs and returns at most 256 unacknowledged reports. Python renews every two
   seconds. Lease loss closes all sockets; a new lease cannot revive old tickets or sessions.
3. `mode` carries `runner_id`, a monotonically increasing `generation`, `mode` and `reason`.
   Stale generations are refused. Disallowed sessions are removed atomically and cancellation
   reaches sockets within the bounded close deadline. Allowed view sessions survive an upgrade.
4. `grant` carries a Python-generated session `id`, runner/actor/control, current generation and
   mode. Rust creates the temporary ticket. Matching retries return the same unused ticket;
   conflicting retries fail. Grants are prepared and invisible until `activate` follows Python's
   audit transaction commit. Failed commits use `end`. Mode changes fence stale activation.
5. `pending` lists only active, unanswered sessions for that runner. `end` is duplicate-safe.
   A ticket is consumed atomically once, even if subsequent pairing fails. Runner claims are
   atomic and require Python to validate the original bearer against the exact existing path.
   Origin permission is also checked by Python, keeping local aliases/demo/CORS semantics intact.
6. Close reports contain session ID, actor, runner, control, seconds and close code. Python inserts
   at most one close event per open session, under its SQLite write lock, then acknowledges it.
   Reports are retried until acknowledged. Audit events carrying the pilot lease allow Python to
   reconcile unclosed opens after either process restarts; they do not confer session authority.

Bounds: three sessions per computer (unchanged); 1 MiB pre-browser backlog (unchanged), one-minute
unused ticket, 30-second answer and one-hour session deadlines (unchanged). The pilot additionally
caps global live sessions at 1,024, retained close reports at 8,192, individual messages at 16 MiB (matching uvicorn),
and stalled writes at five seconds. Saturation refuses admission instead of growing memory.
Cancellation interrupts stalled pumps; close handshakes have a one-second deadline per socket.
A failed revocation RPC stops lease renewal, so durable revocation still closes sockets within the
six-second lease plus close deadline. HTTP control calls have two-second deadlines.

## Rollout gate

Use the installation matrix in `docs/install.md`. Roll back by selecting Python and restoring its
WebSocket ingress, then stop this sidecar; existing screens close and reopen with fresh tickets.
No database rollback is needed. Never fall back automatically during an active Rust lease.

Python fallback removal milestone: after native, Docker/Caddy and both Cloudflare ingress modes
pass the shared contract and restart/slow-consumer tests in release-owner rehearsals, and two
successive releases have no relay regressions. At that milestone ship the sidecar through the
normal installer/updater, make Rust the default, and remove the Python socket implementation in
the following release. Until then, keep rollback and measure both implementations. Language alone
is not evidence of lower latency or CPU for this I/O-bound workload.
