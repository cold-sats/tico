# Install Tico

Tico has two parts. The **server** holds the app, the company's data and the sign-in; it runs no bots. The
**computers** run the bots: a Mac, or any Linux or cloud machine, each joined to the server with a one-time code.
Both parts are Docker images (linux/amd64 and linux/arm64):

| Image | Holds | Size (pull / on disk) |
|---|---|---|
| `ghcr.io/ticoteam/tico` | the server and Litestream backups | 106 MB / 450 MB |
| `ghcr.io/ticoteam/tico-runner` | a runner with git, gh, node, python, build tools, ripgrep, jq and curl; no model CLIs (it installs them itself, see [harnesses](harnesses.md)) | 268 MB / 1.1 GB |
| `ghcr.io/ticoteam/tico-updater` | the one-click updater | 74 MB / 310 MB |

```
browser -> caddy (HTTPS) or cloudflared --> server :8765 (data volume)
                                                 ^
                    Mac (native) and Linux runners join from anywhere over https://<your domain>
```

## Install the server

One command, run on the Linux server itself. It takes about 15 minutes, most of it waiting for DNS.

### Before you start

- [ ] **A Linux server**, about 2 GB of memory and 10 GB of disk (1 GB is the minimum). Ubuntu 24.04 or Debian 12 on
      x86_64 or arm64 is what is tested. You need root or `sudo`. See "Where to get a server" below.
- [ ] **A domain name** you can add a DNS record to, such as `tico.yourcompany.com`. The wizard tells you which
      provider serves it and the exact record to add.
- [ ] **A way to sign in.** A Google or Microsoft account that can create an OAuth client (Google Workspace,
      Microsoft Entra ID) for your people. If the server has no public IP address (an office or home machine),
      use a **Cloudflare Tunnel** instead: it needs the domain on Cloudflare and no open ports.
- [ ] **A model subscription** for the bots (ChatGPT/Codex, Claude, Gemini and others). You sign the bots in after the
      install, on the computer that runs them; the server never holds it.

### Where to get a server

Any Linux machine works. If you need one, these are the cheap always-on options (list prices as of September 2026;
check the provider before you commit):

| | Size | Price, 24/7 | Notes |
|---|---|---|---|
| Hetzner Cloud | `cax11` (2 vCPU Arm, 4 GB, 40 GB) or `cx23` (2 vCPU x86, 4 GB) | about EUR 5.99 or EUR 5.49, plus the IPv4 | Lowest price. Arm sizes only in Germany and Finland (`nbg1`, `fsn1`, `hel1`); take `cx23` or `cx33` elsewhere. |
| DigitalOcean | `s-1vcpu-2gb` (1 vCPU, 2 GB, 50 GB), Ubuntu 24.04 x64 | $12 | `s-2vcpu-2gb` is $18. A Reserved IP is free while assigned. |
| AWS EC2 | `t4g.small` (2 GB, Arm), 30 GB gp3 | about $18 with disk and IPv4 | Ubuntu 24.04 or Amazon Linux 2023, in a public subnet (route to an internet gateway; a subnet whose 0.0.0.0/0 goes to a NAT gateway is unreachable from outside). The bot box (runner) may sit in a private subnet since it only connects outbound. Open 80 and 443 in the security group (nothing for a tunnel), and set the metadata hop limit to 1 so containers cannot read the instance role: `aws ec2 modify-instance-metadata-options --instance-id i-... --http-tokens required --http-put-response-hop-limit 1`. Backups from the container then need explicit keys limited to the backup bucket: the server has no AWS credentials that could create them, so run `python3 -m setup backup-storage --domain tico.example.com --aws-region us-west-2` from a clone on your laptop (with your AWS credentials) first; it creates the bucket and key and prints the two `export` lines and the `existing` answer to give the installer. |
| Any Linux box | 2 GB or more | your own | Give it a stable public IP (Caddy) or no public IP at all (tunnel). |

Whatever you pick, allow inbound 80 and 443 in the provider's firewall (not needed with a tunnel), and add an SSH
key or console access so you can reach a shell. The installer does not touch the firewall.

**Shortcut.** If you would rather not click through a provider's console, `tico setup --cloud hetzner|digitalocean|aws`
creates the server for you from your laptop, through your own `hcloud`, `doctl` or AWS credentials, and the new server
runs this same installer as its first boot step (`infra/cloud-init/`). Run it from a clone of the repository:
`python3 -m setup --cloud hetzner --domain tico.example.com`. It is optional; everything below is what it automates.

### The command

Open a shell on the server and run the installer of the release you want (see
[Releases](https://github.com/ticoteam/tico/releases); the tag is part of the address, so the script and the
software it installs always match):

```
curl -fsSL https://github.com/ticoteam/tico/releases/download/vX.Y.Z/install.sh | sh
```

It asks for `sudo` if you are not root, and it prints each step. In order it:

1. **Checks the machine:** Linux on x86_64 or arm64, root or sudo, at least 1 GB of memory and 1 GB of free disk, and
   ports 80 and 443 free (skipped with `--tunnel`).
2. **Installs Docker** if it is missing or too old (Compose v2.20 or newer is needed): from Docker's own apt
   repository on Debian and Ubuntu, and with Docker's convenience script (`get.docker.com`) on other distributions.
3. **Downloads that release's compose bundle** (`tico-bundle-vX.Y.Z.tar.gz`) and checks it against the release's
   `SHA256SUMS`. A bundle that does not match is refused and nothing is installed.
4. **Runs the `tico setup` wizard** on the server, interactively, with the release pinned in `.env` as `TICO_TAG`.

Everything lives in `/opt/tico` (`compose.yaml`, `.env`, the wizard). Options, after `sh` or `sh -s --` when piping:

| Flag | Meaning |
|---|---|
| `--version vX.Y.Z` | Install this release instead of the one the script came from |
| `--dir PATH` | Install somewhere other than `/opt/tico` |
| `--yes` | Do not ask for confirmation |
| `--tunnel` | Cloudflare Tunnel: no public ports, so 80 and 443 are not checked |
| `--docker-only` | Only install Docker and Compose (runner boxes) |
| `-- FLAGS` | Everything after `--` goes to `tico setup` (see Automation below) |

Exit codes: 0 done, 2 bad usage, 3 the machine does not qualify, 4 download or checksum failed, 5 Docker or Python
could not be set up, 6 the wizard or the health check failed.

**Running it again is safe.** With an existing `.env` it does not ask anything and never rewrites your settings: the
same version is repaired (bundle restored, stack restarted), a different `--version` upgrades (only `TICO_TAG` changes),
and an installer older than what the updater already installed leaves the newer version alone. If the wizard stopped
half way, running the command again resumes it.

### What the wizard asks

1. **How do people reach it?** Caddy (automatic HTTPS, opens ports 80 and 443) or a Cloudflare tunnel (no open
   ports). With a scoped Cloudflare API token (Cloudflare Tunnel: Edit, and DNS: Edit on the one zone) it creates the
   tunnel, its route and the DNS record; without one it shows the exact dashboard steps and asks for the tunnel token.
2. **Domain and DNS.** It looks up which nameservers the internet actually uses for your domain and names the provider
   (Route 53, Cloudflare, Netlify/NS1, Vercel, Google, GoDaddy, Namecheap, ...). With Cloudflare and a token (or Route 53
   and AWS credentials) it offers to create the record; anywhere else it prints the exact record and where to add it. Then
   it polls public resolvers (8.8.8.8, 1.1.1.1, 9.9.9.9) and only starts Caddy once they agree, because a certificate
   requested before DNS is live fails without a visible error. It suggests this server's public IPv4 address; confirm it.
3. **Sign-in.** Google or Microsoft (OIDC), or Cloudflare Access. It opens the right console page, prints the redirect
   URI to paste (`https://<domain>/auth/callback`, character for character), and asks for the client ID and secret
   (hidden). Optionally limit sign-in to one email domain.
4. **Company.** Name, owner email (it must be the account you will sign in with), and an optional model key for the
   server's own decision model.
5. **Backups.** A bucket (an S3 or R2 bucket it can create, one `setup backup-storage` created from your laptop, or one you already have) or local only, with the warning
   that local copies do not survive losing the server. See [Backups and restore](#backups-and-restore).

Then it shows the plan and asks "Go ahead?". `--dry-run` prints the plan and changes nothing (it only reads DNS):

```
$ python3 -m setup --dry-run --non-interactive --target local --front-door caddy --domain tico.example.com \
    --server-ip 203.0.113.7 --auth google --client-id 1234-abc.apps.googleusercontent.com --company Acme --owner-email you@example.com
tico setup (dry run: nothing will be created or changed)
Sign-in: create a Google OAuth client at https://console.cloud.google.com/auth/clients/create
  with redirect URI exactly https://tico.example.com/auth/callback

Plan
Tico at https://tico.example.com: one server running the Tico server in Docker. Bots run on computers you add afterwards.

  1. On this server: install Docker if missing, write /opt/tico/compose.yaml and /opt/tico/.env (0600), `docker compose up -d`
  2. DNS: tico.example.com is served by <your DNS provider>
       A tico.example.com -> 203.0.113.7
  3. Wait until public resolvers (8.8.8.8, 1.1.1.1, 9.9.9.9) answer with those records, before anything asks for a certificate
  4. Sign-in: Google OIDC; OAuth client redirect URI must be exactly https://tico.example.com/auth/callback
  5. Backups: local only
  6. Company 'Acme', owner you@example.com
  7. Verify: HTTPS certificate, /healthz, sign-in redirect, server container up
```

Secrets never appear on the command line, in the plan, in logs or in the repository. They go to the server's `.env`
(mode 0600) and to a private copy under `/opt/tico/.setup/` so a re-run can resume.

### What you will see after about 15 minutes

- The installer finishes with `Done. Open https://tico.example.com and sign in as you@example.com.`, after checks for
  the HTTPS certificate, `/healthz`, the sign-in redirect (provider host and exact redirect URI), and the server
  container. Any failed check prints a fix beside it.
- Most of the time goes to DNS: seconds with Route 53 or Cloudflare and a token, and up to your DNS provider's
  propagation time (the wizard waits up to 20 minutes and can be resumed) when you add the record yourself.
- Opening the URL shows Google or Microsoft sign-in, then the app with a **first-run checklist**: add a computer,
  enable a model provider, create your first bot. Nothing runs bots yet: the next section is the step that does.

### When something fails

- **The certificate does not appear.** DNS was not live when Caddy first asked. Check the record is at the provider
  `tico setup` named (a Route 53 zone can exist while another provider serves the domain), then
  `docker compose restart caddy` in `/opt/tico`.
- **"redirect_uri_mismatch" at sign-in.** The OAuth client must list exactly `https://<domain>/auth/callback`.
- **Sign-in says you are not on the roster.** The owner email must match the account you sign in with.
- **Ports 80/443 time out from outside, though everything looks healthy on the server.** The server is probably in a
  private subnet: its route table's `0.0.0.0/0` goes to a NAT gateway instead of an internet gateway (`igw-...`).
  Launch it in a public subnet (or fix the route), and Let's Encrypt can then reach it.
- **A port is in use.** The installer stops before changing anything; free the port or use `--tunnel`.
- **Check again later:** `cd /opt/tico && sudo ./scripts/tico-setup doctor --domain tico.example.com` re-runs the checks
  with a fix for each failure.

### Automation

Run the installer with no terminal (a provisioning script, cloud-init, CI) and the wizard never prompts: a missing
value is an error that names the flag. Flags after `--` go to `tico setup`; secrets come from the environment only, so
they never appear in a process list:

```
TICO_OIDC_CLIENT_SECRET=... sh install.sh --yes --version v0.2.3 -- --domain tico.example.com --front-door caddy \
  --server-ip 203.0.113.7 --auth google --client-id 1234-abc.apps.googleusercontent.com --company Acme \
  --owner-email you@example.com --backup local
```

Flags: `--domain`, `--front-door caddy|cloudflared`, `--server-ip`, `--tico-version`, `--auth google|microsoft|cloudflare`,
`--tenant`, `--client-id`, `--allowed-domain`, `--company`, `--owner-email`, `--decisions-provider` (the old `--judge-provider` still works), `--backup`,
`--backup-url`, `--backup-endpoint`, `--backup-region`, `--no-updater`, `--dns-timeout MINUTES`, `--skip-dns-wait`.
Secrets: `TICO_OIDC_CLIENT_SECRET`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_TUNNEL_TOKEN`, `OPENAI_API_KEY` (or
`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`). `python3 -m setup --help` lists all of them.

**cloud-init.** `infra/cloud-init/tico-server.yaml` and `tico-runner.yaml` are paste-ready user data for any Ubuntu 24.04
cloud that accepts it (Hetzner, DigitalOcean, AWS, Vultr, Linode, OCI). Edit the block between the two `inputs` markers
(release, domain, owner email, company, sign-in). They write `/opt/tico/.env` from it, turn on `ufw`, keep containers away
from the provider's metadata service, and call this same `install.sh` for the pinned release, which sees the existing `.env`
and installs and starts without asking. They are safe to run again and delete their inputs when done. Provider user data is
stored by the provider and readable from the server through its metadata service, so the OIDC client secret sits there for the
life of the server: use a client secret you can rotate. Progress is in `/var/log/tico-setup.log`.

### Sign-in

| `TICO_AUTH_PROXY` | Also set | Use |
|---|---|---|
| `oidc` | `TICO_OIDC_ISSUER`, `TICO_OIDC_CLIENT_ID`, `TICO_OIDC_CLIENT_SECRET`; optionally `TICO_OIDC_ALLOWED_DOMAINS` (comma-separated, such as `acme.com`) | Google, Okta, Microsoft Entra or any OpenID Connect provider. Register `https://<TICO_DOMAIN>/auth/callback` as the redirect URI with the provider. |
| `cloudflare` | `TICO_ACCESS_ISSUER`, `TICO_ACCESS_AUDIENCE` | Cloudflare Access in front of the tunnel |
| `none` | nothing; leave `TICO_DOMAIN` and `COMPOSE_PROFILES` empty | Local testing only. The server answers on `http://127.0.0.1:8765` and the owner signs in with the token from `docker compose exec server cat /data/local-owner.token` (`Authorization: Bearer <token>`, or `GET /api/v2/local-signin?token=...`). Never put this behind a public address. |

The owner is the first person on the roster; add the others in the app. The wizard writes these settings; to change
one later, edit `/opt/tico/.env` and run `docker compose up -d` there. `.env.example` in the bundle lists every setting.

### Cloudflare Tunnel

No open ports, and Cloudflare Access can do the sign-in. The wizard creates the tunnel when you give it a token; by hand:

1. In Cloudflare Zero Trust, create a tunnel (Networks > Tunnels > Create > Cloudflared) and copy its token.
2. In the tunnel's **Public Hostname** tab, route your hostname to `HTTP` `server:8765`.
3. Create an Access application for the hostname with your identity provider and a policy for your people.
   Note the team URL (`https://<team>.cloudflareaccess.com`) and the application's Audience tag.
4. In `.env`: `COMPOSE_PROFILES=cloudflared,updater`, `TICO_DOMAIN=<hostname>`, `CLOUDFLARE_TUNNEL_TOKEN=<token>`,
   `TICO_AUTH_PROXY=cloudflare`, `TICO_ACCESS_ISSUER=<team URL>`, `TICO_ACCESS_AUDIENCE=<AUD tag>`.
5. `docker compose up -d`

Computers join through the same hostname. If Access sits in front of all of it, give the runners a bypass or a
service token for `/api/v2/runners/*` (the runner authenticates itself with its own token).

### Sizing

- **Server:** 1 to 2 GiB of memory and 10 GiB of disk is plenty (it is a web app and a SQLite database).
- **Runners:** plan roughly 0.5 to 1 GiB of memory for each bot working at the same time, and disk for the bots'
  repositories (20 GiB and up). When bots queue, add another runner box rather than a bigger one. More in
  [sizing](sizing.md).

## Add computers to run your bots

In the app open **Settings > Devices > Add computer** (or step 4 of the first-run wizard, "Add the computer that
runs your bots"), pick the kind of computer, and copy the commands it shows. The one-time code works once and
expires after 15 minutes. Adding a computer never assigns bots to it: choose it for each bot afterwards.

### Linux or cloud server (Docker)

On any Linux machine, run the line the app shows. It downloads the installer of the release your server runs, so the
runner and its updater start on that same release:

```
curl -fsSL https://github.com/ticoteam/tico/releases/download/vX.Y.Z/install.sh | \
  sh -s -- --runner --url https://tico.example.com --code <code> --label "Build box"
```

`vX.Y.Z` is your server's release (Settings and Settings > Health show it); `--runner` exists from v0.2.1.

`install.sh --runner` installs Docker if it is missing, puts that release's `runner.compose.yaml` and a `.env`
(`TICO_URL`, `TICO_CODE`, `TICO_RUNNER_LABEL`, and `TICO_TAG` and `TICO_UPDATER_TAG` pinned to the release) in
`/opt/tico-runner` (`--dir` changes it), and runs `docker compose -f runner.compose.yaml up -d`. The compose file has
an **updater sidecar**, which is what keeps the runner on the server's release ([updates](updates.md#a-docker-runner));
a runner started any other way never follows it. Run the line again any time: it keeps the `.env` and repairs the
stack, and `--version vX.Y.Z` moves the pinned tag.

The runner enrolls, starts, and comes back by itself after a reboot or a server restart. Its model logins and the
bots' repositories live in a Docker volume, so running the line again never enrolls a second runner. If the server no
longer knows the runner (a wiped database), start it again with a new code.

**Moving a runner that was started with a bare `docker run`.** Run the line above on the same machine. It finds the
`tico-runner` volume, points the compose file at it (`TICO_RUNNER_HOME_VOLUME=tico-runner` in `.env`), removes the old
container, and starts the compose one: the login, the bots' repositories and the enrollment carry over, and the runner
now has its updater.

**Plain `docker run` (an alternative that does not update itself).** If you would rather manage the container yourself:

```
docker run -d --name tico-runner --restart unless-stopped -v tico-runner:/home/runner \
  ghcr.io/ticoteam/tico-runner:v0.2.3 join --url https://tico.example.com --code <code> --label "Build box"
```

It has no updater: it stays on the release you pinned until you pull a newer image and recreate the container, and
Settings > Health says so.

The image holds no model CLI. Once the company has enabled a provider (Settings > AI providers), the runner installs
that provider's CLI into `/home/runner/tools` in the volume (a minute or two; Settings > Devices shows the progress),
keeps it current between turns, and lets the owner pin a version. See [harnesses](harnesses.md).

Sign the bots in to a model once, from Settings > Devices or inside the container (the login stays in the volume):

```
docker exec -it tico-runner codex login --device-auth      # ChatGPT subscription: open the URL, enter the code
docker exec -it tico-runner claude setup-token             # Claude: prints a long-lived token
```

API keys and other secrets go in the runner's shared file, readable by the runner only:

```
docker exec tico-runner sh -c 'umask 077; printf "%s\n" "CLAUDE_CODE_OAUTH_TOKEN=<token>" "GH_TOKEN=<fine-grained token>" >> /home/runner/workspace/secrets/_shared.env'
```

`GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `XAI_API_KEY` and `OPENROUTER_API_KEY` work the same way; `GH_TOKEN` is used by `git` and `gh`
to push the bots' repositories. Check with **Settings > Bots**, or
`docker exec tico-runner python -m runner --config /home/runner/runner.json doctor`.

To write the compose setup by hand instead of using the installer, copy `docker/runner.compose.yaml` from the release
to the machine, write a `.env` next to it with `TICO_URL=https://tico.example.com`, `TICO_CODE=<code>`,
`TICO_RUNNER_LABEL=<name>`, and `TICO_TAG` and `TICO_UPDATER_TAG` set to the server's release (`v0.2.3`, not `latest`), and run
`docker compose -f runner.compose.yaml up -d`.

**Meeting importers and Close calls run here too, with nothing extra to start.** The runner container also runs the
`importers` and `close-calls` jobs that a Mac runs as launchd jobs, as children of the runner with restart and backoff,
and only while they are wanted:

- *Meeting importers* (Fireflies, Zoom, Google Meet, Granola): in **Settings > Cloud services > Meeting importers**
  tick **Enabled** and choose this computer. The job starts within a minute and stops again when you switch it off
  or pick another computer. Put the tool's credential in the runner's secrets folder, for example
  `docker exec tico-runner sh -c 'umask 077; printf "%s\n" "FIREFLIES_API_KEY=<key>" | tee /home/runner/workspace/secrets/fireflies.env >/dev/null'`
  (the file names are in [meetings](meetings.md#meeting-importers)); `docker exec tico-runner python -m runner
  --config /home/runner/runner.json importers-doctor` says which are present.
- *Close calls*: put `CLOSE_API_KEY=<key>` in `/home/runner/workspace/secrets/close-calls.env` the same way. The job
  starts when that file appears; keep it on one computer only. See [meetings](meetings.md#close).

`docker logs tico-runner` carries the jobs' lines (`Tico side jobs: started importers`), and each importer's health
shows on its Settings card and the Meetings Sources strip.

*Mail and calendar (`connectors`)* run on a Linux runner the same way, from the company's Google service-account
key ([mail](mail.md#works-on-linux-runners) has the Google Workspace setup). Put the key in the runner's secrets folder
and keep it on one computer only:
`docker exec -i tico-runner sh -c 'umask 077; tee /home/runner/workspace/secrets/google-sa.json >/dev/null' < google-sa.json`
(the runner refuses a key that is not mode 0600).
The job starts within a minute of the file appearing, builds its Python environment into the volume the first time
(about a minute; `docker logs` shows it), and stops when the file is removed. On a VM the key goes to
`/var/lib/tico-runner/workspace/secrets/google-sa.json` (mode 0600, owner `ticorun`). Instead of the key, an owner who
sets `TICO_PROCESSING_OPERATORS` on the server assigns the job to that operator's runners. `docker exec tico-runner
python -m runner --config /home/runner/runner.json connectors-doctor` says whether the key is found.
`TICO_SIDE_JOBS=0` in the container's environment turns the supervisor off.

Update a runner with `docker pull ghcr.io/ticoteam/tico-runner:latest`, then remove and re-run the container
(`docker rm -f tico-runner`, then the same `docker run` line; the volume keeps everything). With the compose file it
is `docker compose -f runner.compose.yaml pull && docker compose -f runner.compose.yaml up -d`. The runner
finishes turns in progress (up to 15 minutes) before it stops.
With the compose file the runner also updates itself to the release its server runs, through an `updater` sidecar
(the only container with the Docker socket); see [updates.md](updates.md).

The runner container is not a sandbox between bots: all bots on one runner run as the same user. It cannot see
the server or its data (they are on other machines), and bots cannot reach a Docker socket. On AWS, keep the
instance metadata hop limit at 1 for runner boxes too.

### Mac

The native runner is unchanged and fully supported: a Mac keeps its own logins, desktop apps and files. Choose **Mac**
in Add computer, then in the Tico checkout on that Mac run the command it prints
(`scripts/setup-runner.sh "$HOME/Downloads/<setup-file>.json"`, or `scripts/tico -e <env> enroll --code-file <file>
--label "Studio Mac"`, then `scripts/tico -e <env> install bot`; see the README). It connects to
`https://<TICO_DOMAIN>`, runs under launchd, and reconnects on its own after the server restarts.

## Slack

Add `slack` to `COMPOSE_PROFILES` to run the Slack service, then paste the app's tokens in Settings. Steps and troubleshooting: [slack.md](slack.md).

## Update

Server: `docker compose pull && docker compose up -d`, or run the newer release's `install.sh` again (it upgrades in place and
keeps your `.env`). Pin a release with `TICO_TAG=v1.2.3` in `.env` (default
`latest`); images are tagged `vX.Y.Z` and `latest`, and `edge` follows `main`. Data lives in named volumes and
survives updates. Runners: see above.

### One-click updates

With `updater` in `COMPOSE_PROFILES` and `TICO_UPDATER_URL=http://updater:8080` in `.env` (both are in
`.env.example`), the app's **Update now** button works. The `updater` service:

- listens on the compose network only (no published port); the server calls it with a shared secret that the
  server generates into the `tico-control` volume on first start, which only the server and updater mount;
- `POST /update {"version": "vX.Y.Z" | "latest"}` downloads and verifies that release's compose bundle and replaces the files in it (never `.env`), pulls that image, recreates the server, waits up to 3 minutes for
  `/healthz`, rolls back the image and the bundle if it does not come back, and otherwise writes `TICO_TAG` into `.env`;
- `GET /status` returns `{"state": "idle|pulling|restarting|healthy|rolled_back|failed", "from", "to", "message"}`;
- both calls need `Authorization: Bearer <token>`. The server gets `TICO_UPDATER_URL` and `TICO_UPDATER_TOKEN`, and
  the running version as `TICO_VERSION` (also the image label `org.opencontainers.image.version`).

Tradeoff: the updater mounts the Docker socket, which is root on the host. The server runs no bots, so nothing
untrusted shares that host, and the updater runs nothing but `docker compose` for the `server` service. To turn it
off, delete `updater` from `COMPOSE_PROFILES` and `TICO_UPDATER_URL` from `.env`. It does not update itself (see [updates.md](updates.md#the-servers-own-updater));
`docker compose pull && docker compose up -d` does. Computers follow the server's release by themselves; see
[updates.md](updates.md).

## Backups and restore

Backups are on from the first start. Inside the server container, Litestream copies the database within seconds
and attachments (`/data/blobs`) follow every 30 seconds.

| `.env` | Where the copies go | Survives |
|---|---|---|
| `TICO_BACKUP_URL` set | your S3, R2 or S3-compatible bucket | losing the server |
| nothing set (default) | the `tico-backups` Docker volume on the same server | deleting `tico-data`, not losing the server |
| `TICO_BACKUP=off` | nowhere | nothing |

Without a bucket the server logs a warning at start and every hour, and the config payload
(`GET /api/v2/config`) carries `backup: {mode, last_replicated_at, target_kind, warning}` with `mode` one of
`remote`, `local-only` or `off`, so the app can show it to the owner. Point it at a bucket when you can:

```
TICO_BACKUP_URL=s3://my-bucket/tico
TICO_BACKUP_ENDPOINT=https://<account>.r2.cloudflarestorage.com   # R2 or another S3-compatible store; omit for AWS
TICO_BACKUP_REGION=auto                                            # omit for AWS
LITESTREAM_ACCESS_KEY_ID=...
LITESTREAM_SECRET_ACCESS_KEY=...
```

`python3 -m setup` offers to create that storage: on AWS a versioned, encrypted, private S3 bucket and an IAM user
limited to it, on Cloudflare an R2 bucket (with an API token that has Workers R2 Storage: Edit), or a bucket you
already have. Turn on bucket versioning yourself if you make one by hand; a deleted or overwritten backup is then
still recoverable. With `TICO_BLOB_BUCKET` set, attachments already live in S3 and are not copied again.

**Restore** into an empty data volume, from the bucket or, with no `TICO_BACKUP_URL`, from `tico-backups`:

```
docker compose stop server
docker compose run --rm --no-deps server restore    # database and attachments
docker compose up -d
```

`restore` refuses a volume that already holds data. To roll an existing install back to the backup, add `--force`;
the current database is kept beside it as `hub.sqlite.before-restore.<time>`. The install's permanent id
(`TICO_ENVIRONMENT_ID`) is stored in the database, so it comes back with the restore and the Macs and runners
already enrolled keep working.

**Move to a new server:** install Docker on the new machine, copy the same `.env` (and `compose.yaml`), then

```
docker compose pull
docker compose run --rm --no-deps server restore
docker compose up -d
```

and point the domain at the new machine (Cloudflare tunnel: run the same tunnel token there). Stop the old server
first; two servers writing to one bucket corrupt the replica. A fresh volume that finds a backup also restores the
database by itself on first start, but run `restore` so attachments and any error are visible. This needs the
bucket, so with the default local-only backups you can only rebuild on the same machine; that is the reason to set
`TICO_BACKUP_URL`.

Runners hold no company data that is not in a git remote, but back up their volume if bots keep local work.

## Operating it

| | |
|---|---|
| Status | `docker compose ps` (the server shows `healthy`) |
| Logs | `docker compose logs -f server`; on a runner box `docker logs -f tico-runner` |
| Restart | `docker compose restart server` (runners reconnect by themselves) |
| Stop and keep data | `docker compose down` |
| Remove everything | `docker compose down -v` (deletes the data volume) |

Every service restarts automatically (`restart: unless-stopped`), including after the host reboots.

## Building the images yourself

```
docker build --target server  -t tico:local .
docker build --target runner  -t tico-runner:local .
docker build --target updater -t tico-updater:local .
TICO_IMAGE=tico TICO_TAG=local docker compose up -d
TICO_RUNNER_IMAGE=tico-runner docker/smoke.sh     # the checks CI runs
```

Tool versions and their sha256 digests are in `docker/versions.env` and are checked during the build. The
model CLIs are not in the image; the runner installs them (see [harnesses](harnesses.md)).

## Advanced installs

Everything above is the one way to install: Docker is the only supported way to run the server. Driving the wizard from a
laptop, pasting cloud-init by hand, and putting your own load balancer or Cloudflare Access in front are in
[install-advanced.md](install-advanced.md).
