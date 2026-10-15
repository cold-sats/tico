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
