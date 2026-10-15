# Dependency, test setup and screen relay validation

Base at task start: `69a6818b18a3fe9056c68fa4e50efb1d70242c0f`. The three commits were rebased onto
current upstream main `ff1ffe58` before merging. The only conflicts
were in the changelog; upstream release notes were retained and this branch's entries moved under
Unreleased. Tested relay/runtime sources are byte-identical after the rebases.
Work: independent branch `mchusma/dependency-test-screen-relay`. The owner subsequently authorized
merging PR #596. No deployment, release tag, shared release journey, image pruning or live-install
access is part of this task.

## Dependencies (#579)

Compatible groups: AWS SDK `1.43.91` → `1.43.114`; cryptography `50.0.1` → `50.0.2` and
PyJWT `2.15.0` → `2.15.1`; desktop rustls `0.23.45` → `0.23.46`; browser Sentry
`10.74.0` → `10.76.2` and PostHog `1.430.3` → `1.438.11`. Development requirements now
include production constraints. All 43 runtime pins match development. Major upgrades, including
Sentry 11 and websockets 17, remain separate work.

The browser bundle is rebuilt with the checked-in lock and esbuild. PostHog's new retry dispatcher
bypasses `_send_request`, so dispatch and enqueue receive their own sign-out fences. The real SDK
regression intercepts all network traffic, checks decoded event bodies, returns delayed failures
following sign-out, advances the browser clock and verifies no retries are sent. Removing the two
new fences makes the regression fail (six requests versus three); with them it passes in one second.

Validation on macOS arm64, dedicated Python 3.12 venv and temporary build/test directories:

- 54 targeted Python tests pass: authentication, credentials, backup bundles, S3 blobs,
  observability and operations (including both deterministic restore tests and insufficient space).
- `cargo check --manifest-path app/Cargo.toml --locked` passes, with one existing dead-code warning.
- Current `cargo audit` reports zero vulnerabilities for desktop and runner. Desktop retains six
  upstream unmaintained dependency notices and yanked `yoke-derive 0.8.3`; runner has no notices.
  These informational items are unresolved and are not suppressed.
- `python app/tests/check_glib_backport.py` passes: 121 files, exact upstream fix, license and both
  Cargo routes. The documented GLib 0.18.5 path patch and provenance remain intact.
- `npm run check:observability` and `node scripts/ui-tests.cjs -j 1 telemetry` pass. Rebuilding the
  bundle twice produces identical bytes. No real telemetry destinations receive test traffic.

Security source: [rustls 0.23.46 release](https://github.com/rustls/rustls/releases/tag/v%2F0.23.46),
released October 14 with four security fixes. [uv constraints documentation](https://docs.astral.sh/uv/pip/compile/#adding-constraints)
explains the shared-pin workflow now recorded in CONTRIBUTING.md.

## Execution boundary observation

Orca created the independent worktree at the requested upstream main. Its create command also
fast-forwarded the clean registered main checkout as part of its automatic base refresh. This was
an unintended effect of the CLI; no manual application changes were made there, and subsequent
application edits and build outputs stay within this task's worktree or dedicated temporary directory.

## Test setup (#580)

Current main already stubs disk capacity in both restore unit tests and explicitly rejects zero
available space before restore begins. Both are covered by the passing operations tests; production
capacity checking is unchanged. No duplicate fix is introduced.

Profiling a representative API test found 1.99 s setup against 0.01 s body with profiling enabled.
Cold create_app: 1.84 s including imports; route registration: 0.46 s; Store.initialize: 0.14 s.
Warm, unprofiled app creation: 0.23 s. No application/route/handler closure is shared between tests.
Database initialization remains significant enough to evaluate a worker-local snapshot.

The new opt-in `--api-database-snapshots` fixture creates a template per worker and invocation,
checks for absence of live rows, non-static generated IDs and stored temporary paths, and takes
consistent copies through SQLite's backup API. Atomic template publication avoids incomplete
reads. No template survives into another invocation or source revision. Each copy still runs normal
initialization; direct migration/upgrade fixtures retain empty database paths. Static General type
and step IDs are intentional schema seeds; no authentication secrets or person/bot IDs are copied.
The fresh path remains the default because snapshots regress the measured high-worker selections.

Three alternating fresh/snapshot samples per worker count, identical dependencies and test selection:

| Tests | Workers | Fresh median | Snapshot median | Change |
|---|---:|---:|---:|---:|
| 13 API contracts | 2 | 4.307 s | 3.526 s | 18.1% faster |
| 13 API contracts | 4 | 2.979 s | 2.574 s | 13.6% faster |
| 13 API contracts | 6 | 2.662 s | 2.502 s | 6.0% faster |
| 13 API contracts | auto (12) | 2.913 s | 3.066 s | 5.2% slower |
| 84 relevant contracts | 4 | 11.595 s | 10.290 s | 11.3% faster |
| 84 relevant contracts | auto (12) | 10.794 s | 12.227 s | 13.3% slower |

Every sample passed the same selected tests. The broader set covers API, auth, credentials,
backups, S3, operations, screen, upgrade, onboarding, display names, route renames and OpenAPI.
An attempt to refine template guard overhead then encountered machine load above 90 and a full
internal disk; its 52–62 s medians cannot be compared to the earlier conditions. Do not infer a
whole-suite speedup or choose a global worker default from these data. Fresh state and coverage
are preserved; the optimization is available for selections where the measured benefit justifies it.

Validation: 27 API/privacy/operations tests and 24 screen/upgrade/onboarding/operations/client tests
pass; the alternating broad comparison passes all 84 tests on every sample. The real-capacity
integration behavior remains unchanged. No tests were removed or skipped for these measurements.

## Rust pilot (#581)

The opt-in Tokio/Axum sidecar owns temporary tickets, prepared/active grants, socket pairing,
buffering, deadlines and cancellation. Python keeps existing human/operator/admin checks,
runner bearer authentication, durable modes and existing audit-event persistence. The existing
public paths and runner event/poll contract are unchanged; there is no persistent session table.
A prepared grant is published only after Python commits its opening audit event.

Versioned private HTTP uses a separate control key, fresh process leases, single-use start challenges,
monotonic command sequences, exact-retry deduplication and per-runner permission generations.
Tickets and runner claims are consumed atomically under one Rust lock. A six-second monotonic
permission lease fails closed; cancellation interrupts stalled pumps and close sends have bounded
deadlines. Revocation is durable even when its RPC fails. Close reports are retained until Python
commits/acknowledges them, and audit-event reconciliation closes abandoned pilot opens after either
process restarts or when rolling back to Python. No old process may reclaim a replacement's lease.

The protocol, resource bounds and fallback-removal milestone are in relay-rs/README.md. The supplied
Compose overlay and actual Caddy configuration cover Docker/Caddy, locally managed Cloudflare
Tunnel, dashboard-managed Tunnel origins and native/local proxy installations. Default installers,
public URLs, authentication and the normal Compose/updater workflow retain Python. The pilot is an
explicit source/image opt-in, and its sidecar is not automatically managed by the released updater.

Validation:

- Ten real-process/socket contract and ingress tests pass; the final review run took 56.45 s under changing shared-machine load. Both implementations exercise
  atomic ticket redemption/replay, hostile origins, wrong and duplicate runner attachments,
  runner-first greeting buffering, binary/text forwarding, view/control changes, three-session
  limits, admission/revocation races, disconnects, server restarts and revocation while consumers
  are stalled. Rust-specific checks cover prepared grants, stale generations/control replay,
  lease expiry, duplicate audit reports, relay restart and rollback to a working Python relay.
- Caddy 2.11.7, downloaded from its official release and checksum-verified, validates the actual
  config and forwards both unchanged socket paths while blocking private control routes. It runs
  only on allocated loopback ports with its admin listener disabled and SSD-local state.
- Thirty targeted default Python tests pass: auth, screens, operations, upgrade, OpenAPI and tunnel
  configuration. The tunnel test verifies both public/runner origins and rejects an arbitrary origin;
  real cloudflared availability probing is deferred to the explicitly slow integration test.
- The existing computer-screen browser script and the real telemetry privacy/retry script both pass.
  Twenty-eight screen/operations/upgrade/onboarding/OpenAPI/tunnel tests also pass with schema snapshots enabled.
- `cargo build --locked` and `cargo clippy --locked -- -D warnings` pass for the relay; current Cargo
  audit reports zero vulnerabilities and no notices. The pilot declares Rust 1.92, matching the
  tested toolchain and its pinned Docker builder; existing runner requirements are unchanged.
- The optional Compose overlay passes `docker compose ... config --quiet` under a unique validation
  project. No Docker containers, images, volumes or networks were created, removed or pruned.

Local relay comparison on macOS arm64, 12 logical CPUs, the same Python 3.12.12 client/environment,
10 fictional computers × 3 paired sessions, 64 KiB payloads, 100 two-direction round trips per pair.
Three samples per implementation alternate order. Median of sample results:

| Relay | p50 RTT | p95 RTT | Relayed throughput |
|---|---:|---:|---:|
| Python | 10.503 ms | 12.100 ms | 347.475 MiB/s |
| Rust (debug build) | 2.819 ms | 5.811 ms | 1,156.703 MiB/s |

This is about 3.3× throughput and 52% lower p95 in the local synthetic run. Client scheduling and
loopback transport are included; CPU/RSS were not isolated. It does not establish a WAN, Cloudflare,
real VNC or production end-to-end benefit. The benchmark is reproducible with
`scripts/benchmark_screen_relay.py`; all six raw samples and load readings are retained on the task SSD.

Unresolved pilot limits: Docker image build/runtime and live Cloudflare routing were not exercised;
release-owner installation rehearsals are required before rollout. Native supervision is explicit,
not installer-managed. Multi-host encrypted control and multiple Python workers are outside the
pilot. Global live/report caps and a five-second stalled-write deadline are additional opt-in bounds;
existing per-computer, ticket, answer, backlog and one-hour limits are retained. Restart-reconciled
close events have duration zero when the process lost its monotonic start time.

Rollback is documented in docs/install.md: restore Python and its ingress, stop only the pilot
services, and restore dashboard-managed tunnel origins if applicable. Modes and audit history stay
in the same database. Validation did not deploy, tag or run the shared release journey.

## Final workspace boundary

After the request to use the SSD, all task-owned temporary files, Python environments, package caches,
Cargo home/targets, downloaded validation tools, fixtures and logs were moved to or created in this
independent SSD worktree's ignored `.tmp-task/` and `.tmp-relay/` directories. The original internal
temporary directory no longer exists. Initial setup measurements used the same internal-disk temp
location on both sides; subsequent relay measurements and final validation use SSD-local paths.
An automatic command guard rejected deletion of task-owned build directories; they were preserved
and moved to the SSD instead. No other agent's files or running installation was edited.

The final desktop advisory scan still reports zero vulnerabilities. Some final registry requests for
yanked-package metadata timed out; the earlier complete audit and its known yoke-derive notice are
retained. This does not claim that every final yanked-status lookup completed.

The post-rebase changelog/screen/operations/upgrade/OpenAPI/tunnel check passes. The final pre-merge
changelog check passes all three tests (2.49 s). Upstream runner-isolation changes do not alter the
previously validated implementation files. Final bundle
SHA-256 is `b8934d68b2c60e0bd59760d0758edde8b7afea436b418a27187341180e27484c`.
