# The anonymous usage count

Tico's goal is 100 companies trying it and 100 still using it 30 days later. To know, it counts installs. This page is
the design and its research; [PRIVACY.md](../PRIVACY.md) is what an owner reads.

## What other projects do

The rule was to follow established open-source practice, not invent one. Every project below does the same few things,
and Tico does all of them.

| Project | Practice | Source |
|---|---|---|
| **Homebrew** | Anonymous aggregate analytics, on by default, opt out with `brew analytics off`. Shows a notice first, and does not send anything until it has been shown. The payload has no user identifier or IP field. Retention is 365 days. The aggregate numbers are public. | [docs.brew.sh/Analytics](https://docs.brew.sh/Analytics) |
| **Next.js** | Anonymous telemetry, opt out with `next telemetry disable` or `NEXT_TELEMETRY_DISABLED=1`. Prints a notice the first time. `NEXT_TELEMETRY_DEBUG=1` prints each payload to stderr and sends nothing. Says what it collects. | [nextjs.org/telemetry](https://nextjs.org/telemetry) |
| **Astro** | Anonymous, opt out with `astro telemetry disable` or `ASTRO_TELEMETRY_DISABLED=1`; a public page lists the data. | [astro.build/telemetry](https://astro.build/telemetry/) |
| **Gatsby** | Opt out with `gatsby telemetry --disable` or `GATSBY_TELEMETRY_DISABLED=1`; a public page lists the data. | [gatsbyjs.com/docs/telemetry](https://www.gatsbyjs.com/docs/telemetry/) |
| **VS Code** | One setting, `telemetry.telemetryLevel`, and `off` silences everything. Documents what is collected. | [code.visualstudio.com/docs/configure/telemetry](https://code.visualstudio.com/docs/configure/telemetry) |
| **`DO_NOT_TRACK`** | A convention for command-line tools: one environment variable that turns off telemetry and other non-essential phone-home. Adopted by Homebrew and Syncthing, among others. | [consoledonottrack.com](https://consoledonottrack.com/) |
| **Plausible** | Counts visitors without storing IP addresses or user agents: the address is hashed with a salt that is rotated and deleted every 24 hours, so nothing identifies a person and nothing is kept that could. | [plausible.io/data-policy](https://plausible.io/data-policy) |

The common practice: **opt-out and anonymous; a notice on first run; several ways to switch it off, including an
environment variable and a standard one; a debug mode that shows the payload; a public statement of the fields; public or
aggregate results; no IP address kept.** Tico follows each. Where it differs it is stricter: a random ID rather than a
machine hash, four fields, two of them booleans, and the count is invisible to a company that turns it off (the update
check goes straight to GitHub).

## How it works

```
Tico server ── GET /v1/latest?install_id&version&active_people&active_bots ──> HQ ──> installs table (6 columns)
     │                                                                      └──> GitHub release, cached 15 minutes
     └── counting off, HQ down, or TICO_RELEASES_URL set ──> GitHub, no ID
```

- **Client:** `backend/census.py` decides whether anything may be sent and builds the payload; `backend/releases.py`
  makes the request. HQ answers with the same body GitHub does, so the update notice works the same either way.
  `TICO_HQ_URL` moves the base URL (default `https://hq.tico.team`); `TICO_RELEASES_URL` still replaces the whole check
  with a GitHub-shaped mirror and sends nothing extra.
- **`active_people`** is set from the last time a person (not an API token, not the Assistant acting for someone) made a
  request; it is written at most once an hour. **`active_bots`** is a query over finished bot turns.
- **The ID** is `uuid4()`, stored in the `usage-count` row of `registry_metadata`. It is generated on first use, not derived
  from `TICO_ENVIRONMENT_ID` or anything else, and rotates on request.
- **A note on flags:** they are yes/no over 7 days rather than counts, so HQ cannot learn how large a company is.
- **Demo mode** never sends.

## HQ, the collector

`hq/` is a separate service: its own FastAPI app (`hq/app.py`), SQLite database (`hq/db.py`), image (`hq/Dockerfile`) and
compose file (`hq/compose.yaml`). It is not in the Tico server image and refuses to start without `TICO_HQ_KEY` (16 or
more characters), so it cannot be turned on by accident. The key is an enable switch: it is not sent by installs and does
not gate the public endpoints.

**Storage** (`installs`): `install_id`, `first_seen`, `last_seen`, `last_version`, `last_people`, `last_bots`. Dates are UTC
days. Nothing else is stored, and rows older than 13 months (by `last_seen`) are deleted daily.

**Endpoints**

- `GET /v1/latest?install_id=&version=&active_people=&active_bots=` records the ping and returns the latest release,
  cached from GitHub for 15 minutes. Any of the four fields present but invalid, missing or repeated: `422`, nothing
  stored. No fields: the release only, nothing recorded. Over 60 requests an hour from one address: `429`.
- `GET /v1/stats`, public: `tried` (IDs whose two flags have both been true at some time), `active_7d` (heard from in the
  last 7 days), `retained_30d` (first seen at least 30 days ago and a bot active in the last 7 days) and `by_version`
  (active installs by major version; before 1.0 by `0.minor`). The totals are exact. A version count under 5 is folded into
  `other`, and `other` is left out if it is still under 5.
- `GET /healthz`.

**No addresses.** The rate limiter keeps a salted hash of the address in memory, with a random salt made at start, and
forgets it. The server runs with `access_log=False`, so no address or query string is logged. Behind a proxy set
`HQ_CLIENT_IP_HEADER` (`X-Forwarded-For` behind Caddy, `CF-Connecting-IP` behind Cloudflare) so the limit is per client;
the proxy in front must not log query strings either (Caddy does not by default). Do not put Cloudflare Access in front:
installs call HQ without signing in.

### Deploy HQ

On the server (next to an existing Tico is fine: HQ has its own compose project, volume and hostname). This is the Tico
team's `hq.tico.team`; anyone can run their own the same way.

```
git clone https://github.com/ticoteam/tico && cd tico
cp hq/.env.example hq/.env
$EDITOR hq/.env          # TICO_HQ_KEY=$(openssl rand -hex 24); pick a front door; optional backup
docker compose -f hq/compose.yaml --env-file hq/.env up -d --build
curl -fsS http://127.0.0.1:8770/healthz
```

Front door, one of (set in `hq/.env`):

- `COMPOSE_PROFILES=cloudflared`, `HQ_TUNNEL_TOKEN=...`, `HQ_CLIENT_IP_HEADER=CF-Connecting-IP`: an HQ-only Cloudflare
  tunnel. In the tunnel's Public Hostname tab route `hq.tico.team` to `http://hq:8770`, and do not add an Access
  application. This is the right choice on a server whose Tico already holds ports 80 and 443.
- `COMPOSE_PROFILES=caddy`, `HQ_DOMAIN=hq.tico.team`, `HQ_CLIENT_IP_HEADER=X-Forwarded-For`: HTTPS on ports 80 and 443 of a
  host of its own.

Then check `curl -fsS https://hq.tico.team/v1/stats` and `curl -fsS https://hq.tico.team/v1/latest`.

**Backups** are optional: add `,backup` to `COMPOSE_PROFILES` and set `HQ_BACKUP_URL` (and `HQ_BACKUP_ENDPOINT`,
`LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY` for R2 or MinIO). Litestream copies `hq.db` continuously;
restoring is the command at the top of `hq/litestream.yml`. Update HQ with `git pull` and the same `up -d --build`.

## Testing

`backend/tests/test_usage_count.py` (the payload has exactly the four fields; nothing is sent when off by
`TICO_TELEMETRY`, `DO_NOT_TRACK`, the toggle, demo mode or before the notice; HQ down falls back to GitHub; debug sends
nothing; owner-only controls) and `hq/tests/test_hq.py` (no address stored or logged; bad input refused; the stats math,
suppression and retention; no start without the key). They add about ten seconds to the suite.
