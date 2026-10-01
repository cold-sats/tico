# Product analytics and error reporting for your Tico install (optional)

Tico can send privacy-filtered usage analytics to PostHog and error reports to Sentry. Both are
**off until configured**; a stock install sends nothing. You can use one project per environment, or share
one PostHog project between several apps by filtering on the `app` property (Tico sends
`app=tico`).

## Activation

1. Create a PostHog project (and, optionally, a Sentry project for Tico). Preserve the pinned SDK
   and privacy filters described below.
2. Set the variables below in the API service's environment. In Docker, add them to the install's private `.env` and explicitly
   forward them with the [compose override](#docker-configuration) below; `.env` alone does not pass them into the container. Do not commit populated values.

| Variable | Purpose |
| --- | --- |
| `TICO_OBSERVABILITY_ENVIRONMENT` | Required for either SDK: `production`, `staging`, `development`, or `test` |
| `TICO_OBSERVABILITY_ID_SECRET` | Required for browser telemetry: a securely generated, stable secret of at least 32 characters; server only |
| `TICO_POSTHOG_KEY` | Public `phc_` project key for your PostHog project; enables browser analytics with the host and required common settings |
| `TICO_POSTHOG_HOST` | Exactly `https://us.i.posthog.com` or `https://eu.i.posthog.com`, matching the chosen project's region |
| `TICO_SENTRY_DSN` | Public HTTPS Sentry ingestion DSN for the Tico project; enables browser errors with the required common settings |
| `TICO_SENTRY_SERVER_DSN` | Public HTTPS ingestion DSN for the same Tico project; enables API/scheduler errors with the environment setting |
| `TICO_RELEASE` | Optional release label; only letters, numbers, dots, underscores and hyphens, up to 100 characters |

   Public DSNs must use a Sentry ingestion host, numeric project path, and public hexadecimal
   key; legacy password-bearing DSNs and custom/self-hosted endpoints are rejected. Only
   human/owner sessions can fetch `/api/v2/observability`; responses are not cached. The endpoint
   exposes the public project key/DSN and an opaque identity, never the identity secret.
3. Install the locked Python dependencies. The checked-in browser vendor bundle is ready
   for the existing static-file deployment. To regenerate it: `npm ci` then
   `npm run build:observability`. Commit the generated bundle with source/dependency changes.
4. In a staging deployment, sign in, navigate, create a test task,
   send a test chat, and exercise a safe rejected submission. Inspect `app=tico`, environment,
   outcomes and duration fields in PostHog. Inspect one controlled frontend error and API
   failure in Sentry. Confirm network payloads contain no content or raw URLs. Test logout
   and a different account; check that identities change and prior events do not follow it.
5. Enable it in production only after the staging check. To disable, remove the relevant key/DSN or required environment and restart
   the API. Browser config refreshes every 30 seconds;
   reload open tabs to apply configuration changes immediately.

No `SENTRY_AUTH_TOKEN`, `SENTRY_ORG`, or `SENTRY_PROJECT` is sent to the browser. This
plain JavaScript UI needs no source-map upload for its unminified application files; stack
locations are restricted to known static filenames and line/column numbers. The minified SDK
bundle has no published source maps, and this change does not implement source-map upload.
If upload is added later, its authentication token must remain in CI/build secrets, never in
public config or browser assets. Release/debug mapping needs its own tested privacy policy.

## Event contract and interpretation

Every explicit analytics event uses `app=tico` and the configured `environment`. Where
applicable it includes `workflow`, `action`, `outcome`, `duration_ms`, `active_duration_ms`,
and a fixed `route` template. It never invents a team field.

| Events | Meaning |
| --- | --- |
| `route_viewed` | Authenticated navigation to an allowlisted route; all bot paths become `/bot/:bot`, document subpaths become `/docs`, unknown routes become `/unknown` |
| `active_time` | Incremental route usage, flushed every 30 seconds, on route changes, hidden state and page exit |
| `workflow_started` | A recognized submission began |
| `workflow_completed` | Its API operation returned success after the existing retry cycle |
| `workflow_failed` | The API operation rejected or exhausted retries; no error text or request content accompanies it |

Instrumented submissions: chat sends (including task/conversation and page chat), task
creation/update, approval decisions, note saves, meeting import/edit/delete/send,
bot definition changes, and settings transition requests. JSON and supported multipart
submissions use the same wrapper; individual network retry attempts do not duplicate events.
Unknown endpoints, polling reads, credential checks, and the legacy unauthenticated local
Tico are untracked. Other dedicated UI modules and background workers are not comprehensively
instrumented yet. A submission success means the API accepted it, not that a bot finished its
work or that a settings transition finished applying.

`duration_ms` on workflow events is **submission latency**, including retries. It does not
measure drafting time, bot execution time or end-to-end task completion. `active_duration_ms`
on those events is the portion of submission latency during visible, recent user activity.
Route active time stops 60 seconds after the last pointer/key/scroll/touch activity and
excludes hidden-tab time. It is a proxy for engagement, not verified labor or task effort;
reading without interaction can be undercounted, multiple tabs can overlap, and offline/page
close delivery can be lost. Each active-time event is a delta; sum deltas rather than treating
one as the full visit duration.

Identity is `tico:` plus HMAC-SHA256 of the authenticated server actor using the server-only
secret. It is stable and pseudonymous, not anonymous. The authenticated endpoint optionally returns one bounded staff display name from the
server's admitted roster metadata. Stored names equal to the generated ID title are
ambiguous and omitted; absent/invalid/ambiguous names use the verified Access email
only when it matches the admitted roster row. This fallback intentionally transmits
work email as the display name, without a separate email property. On `route_viewed`
only, the final hook constructs `$set: {name: person_display_name}` from that validated
config; arbitrary event-input person properties are always discarded. Existing people
gain labels on next authenticated use, without backfill, aliases or identity merges.
Name changes refresh the adapter but preserve the same HMAC ID. Sentry stays opaque.
There are no anonymous pageviews or persistent analytics cookies. SDK identity resets on observed
401/403, explicit logout links, and account changes during the 30-second auth/config refresh;
page reload starts with no identity. The refresh compares the complete validated configuration,
including per-SDK enablement, key/host/DSN, environment and release, even for the same identity.
Logout in another tab is observed at the next refresh. Retired PostHog instances discard retries
and fence transport dispatch and late failure callbacks; teardown never flushes old events.
Requests already sent before reset cannot be recalled. The transport fence uses private APIs
from pinned PostHog 1.430.3, so SDK upgrades must pass the real retry regression tests.
Rotating the secret changes historical person continuity. Other apps sharing the project use their own identity
contracts, so cross-app person joins are unavailable; compare app-level workflow aggregates.

## Suggested PostHog insights

If the project is shared, always filter by `app` and `environment` first. Suggested dashboards:

- Daily/weekly distinct authenticated humans from `route_viewed` and workflow events, split
  by app; route popularity and summed active-time deltas show which areas see engagement.
- `workflow_started` → `workflow_completed` funnels grouped by workflow/action, with failed
  event counts and failure rate. A missing completion may also mean tab closure or delivery
  loss; concurrent identical actions mean person funnels are an approximation, not an exact
  transaction ledger.
- Median and p90 `duration_ms` for completed submissions, grouped by workflow/action,
  alongside failure counts. Slow or repeatedly failing steps are candidates for investigation.
- High-frequency actions and large active-time totals suggest where automation or UI changes
  might help. Validate these hypotheses with teammates; this telemetry cannot explain intent
  or distinguish useful reading from unproductive effort on its own.

Sentry receives frontend uncaught errors/unhandled rejections, relevant API 5xx/unhandled
exceptions and scheduler failures. Defaults, request/context capture, logs, tracing, replay,
breadcrumbs and local/source variables are disabled. Events are reconstructed before sending:
fixed error labels, app/environment, status/source on the server and allowlisted stack
locations; frontend events include the same opaque identity. Exception messages, customer
values, URLs, headers, tokens, payload bodies and arbitrary SDK enrichment are discarded.
Server events intentionally have no person identity. Coarse error labels trade diagnostic
richness for privacy; stack locations are the primary grouping evidence.

PostHog autocapture, replay, heatmaps, dead/rage clicks, error capture, surveys, performance,
remote flags and external dependency loading are disabled. The last-mile hook allows only
our named events and fixed properties, plus SDK event IDs/timestamps and the configured
public project token required for ingestion. GeoIP processing is disabled. SDK errors are
contained so analytics failures cannot fail an application operation.

## Deployment notes

The UI's `SERVICE_NAMES.posthog` entry names a bot tool; it is not application
analytics. `TICO_RELEASE` is reused as the release label. Cloud installs use the same Docker configuration below. Native checkout
installs put these variables in the environment's `server.env`, then use `scripts/tico -e <slug> server restart`. For the identity
secret, use 32-256 URL-safe letters, digits, underscores or hyphens. Keep it stable across releases and out of command arguments and logs.

### Docker configuration

Add this `compose.override.yaml` beside the install's `compose.yaml`:

```yaml
services:
  server:
    environment:
      TICO_OBSERVABILITY_ENVIRONMENT: ${TICO_OBSERVABILITY_ENVIRONMENT:-}
      TICO_OBSERVABILITY_ID_SECRET: ${TICO_OBSERVABILITY_ID_SECRET:-}
      TICO_POSTHOG_KEY: ${TICO_POSTHOG_KEY:-}
      TICO_POSTHOG_HOST: ${TICO_POSTHOG_HOST:-}
      TICO_SENTRY_DSN: ${TICO_SENTRY_DSN:-}
      TICO_SENTRY_SERVER_DSN: ${TICO_SENTRY_SERVER_DSN:-}
      TICO_RELEASE: ${TICO_RELEASE:-}
```

Store the selected values in the private `.env` (mode 0600). Recreate the API service to apply the new mapping:

```bash
docker compose up -d server
# Check presence only; never print the values or an expanded compose config.
docker compose exec server python -c 'import os; names = ("TICO_OBSERVABILITY_ENVIRONMENT", "TICO_OBSERVABILITY_ID_SECRET", "TICO_POSTHOG_KEY", "TICO_POSTHOG_HOST", "TICO_SENTRY_DSN", "TICO_SENTRY_SERVER_DSN"); print({n: bool(os.getenv(n)) for n in names})'
```

While signed in as a human, inspect `GET /api/v2/observability` in the browser: it returns validated public configuration,
never the identity secret. Configuration can be present but rejected if it does not meet the requirements above.

Run `npm run check:observability` for the browser source syntax checks. Backend reporting and privacy contracts are covered by
`python -m pytest -q backend/tests/test_observability.py`. The checkout does not ship a separate browser observability test command.
Release validation: `docker/smoke.sh` boots the server image with an
isolated database and telemetry disabled. It checks both browser scripts are served and Sentry
is never imported; arbitrary JavaScript assets remain excluded and all three observability
dependencies are required at build time.
Backend tests: `.venv/bin/python -m pytest backend/tests/test_observability.py
backend/tests/test_auth.py backend/tests/test_api.py backend/tests/test_scheduler.py -q`.

Official SDK references consulted: [PostHog configuration](https://posthog.com/docs/libraries/js/config),
[PostHog JavaScript SDK source/types](https://github.com/PostHog/posthog-js),
[Sentry Python API](https://getsentry.github.io/sentry-python/api.html), and
[Sentry JavaScript SDK](https://github.com/getsentry/sentry-javascript).
