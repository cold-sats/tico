# Dependency, test setup and screen relay validation

Base: `69a6818b18a3fe9056c68fa4e50efb1d70242c0f` (current upstream main at task start).
Work: independent branch `mchusma/dependency-test-screen-relay`. No merge, deployment, release tag,
shared release journey, image pruning or live-install access is part of this task.

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
