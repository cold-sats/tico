# Harnesses: the model CLIs a runner uses

A **harness** is the program a runner starts for a bot's run: Codex, Claude Code, Gemini CLI, Grok Build, Cursor Agent, or pi.
Tico does not ship them. Model CLIs release every few days and Tico has to work with many providers, so each runner
installs the harnesses its team needs, keeps them current, and lets the owner pin one when a release misbehaves.

Where bots run: on a Mac (native runner) or on a Linux computer (the `tico-runner` Docker image). The server runs no bots
and holds no harness.

## Supported harnesses

| Harness | Manifest | Providers | Installed with | Signs in with |
|---|---|---|---|---|
| Codex | `runner/harnesses/codex.toml` | OpenAI | npm `@openai/codex` | ChatGPT subscription (device code, from Settings) or `OPENAI_API_KEY` |
| Claude Code | `claude-code.toml` | Anthropic | npm `@anthropic-ai/claude-code` | Claude subscription (link and pasted code, from Settings), `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` |
| Gemini CLI | `gemini-cli.toml` | Google | npm `@google/gemini-cli` | `GEMINI_API_KEY` |
| Grok Build | `grok.toml` | xAI | npm `@xai-official/grok` (xAI's own package) | Grok subscription (`grok login` in a terminal) or `XAI_API_KEY` |
| Cursor Agent | `cursor-agent.toml` | Cursor | Cursor's install script, run with `HOME` inside the tools directory | Cursor subscription (`cursor-agent login` in a terminal) or `CURSOR_API_KEY` |
| pi (catch-all) | `pi.toml` | DeepSeek, Kimi (Moonshot), Meta Llama, Mistral, OpenRouter | npm `@earendil-works/pi-coding-agent` | `OPENROUTER_API_KEY` |

xAI has an official CLI (Grok Build, `docs.x.ai/build`; also an install script at `x.ai/cli/install.sh`), so xAI does
not go through the catch-all. Tico uses the npm package because it installs into a directory of our choosing and npm
checks the tarball's integrity hash; the script installs into `~/.grok`.

`runtime: cursor` was retired in v0.1.0. It is back as an
ordinary harness: `runner/hosts/cursor.py` runs `cursor-agent -p --output-format stream-json --force --trust` once per
run, with the prompt on stdin and the chat made by `cursor-agent create-chat`, so a restart resumes it. Cursor picks
the model itself on `auto` (`cursor-auto` in the model list); a bot's config may name any other model Cursor offers.
Cursor's installer only ever installs the newest release, so this harness follows `latest` and cannot be pinned to an
older version (Pin to this version pins the one installed).

### Why pi is the catch-all

Providers with no CLI of their own (DeepSeek, Kimi, Llama, Mistral, and whatever comes next) share one harness that
takes an API key. Candidates:

- **pi** (already a Tico host, `runner/hosts/pi.py`): one non-interactive process per run (`pi -p --mode json`), a
  JSON event stream Tico already parses, resumable sessions, read/bash/edit/write/grep tools (the bot reaches Tico
  with the `hub` CLI over bash), no permission prompts, an npm package, and keys for many providers by environment
  variable. Tico reaches every model through OpenRouter, so one key covers all of them.
- **OpenCode**: also capable and widely used, with a large provider list, but it would need a new host adapter and its
  own event format, and ships a per-platform native binary. Nothing in a headless run needs what it adds.
- **aider**: edits a git repository well, but it is a chat-driven editor, not an agent with a shell; a bot's run
  (read the repo, call Tico, run tests, commit) does not fit.

pi is the one that best fits a headless run in a git repository with the least new code. If it stops being
maintained, replacing the catch-all is a manifest and a host adapter, described below.

## How providers map to harnesses

The owner enables providers in **Settings > AI providers** (`backend/providers.py`). Each provider names its runtime
(the host adapter) and its harness (the manifest). The runner reads the enabled providers from the server
(`GET /api/v2/config`, `enabled_providers`) and installs the harnesses they need, plus the harness of any bot
assigned to it that names a runtime. A runner whose team has no provider yet installs nothing and still joins and
goes online.

A model with no CLI of its own has a row in `MODEL_CATALOG` with `runtime: "pi"` and an entry in
`runner/hosts/pi.py` `MODELS` that gives its OpenRouter id (for example `kimi-k3` is `moonshotai/kimi-k3`). Enabling
the `openrouter` provider offers every such model; enabling one vendor offers that vendor's models only.

## Where installs go, and what is left alone

Installs go into the runner's **tools directory**, never system-wide: `TICO_TOOLS_DIR`, else `tools_dir` in the
registration, else `tools/` beside `runner.json`. In the Docker image that is `/home/runner/tools`, inside the runner
volume, so harnesses survive a restart or a new image. The directory is put last on `PATH`.

- **Mac**: a harness already on `PATH` (Homebrew, `npm -g`) is used as it is. The runner installs into its tools
  directory only when the harness is missing, and never updates one it did not install. Installing needs `node` and
  `npm` on the Mac.
- **Linux (Docker)**: the image has node, npm, python, pip, git, gh, build tools, ripgrep, jq and curl, and no model
  CLI.
- **Current Docker runner**: the supervisor `ticorun` (UID 10002) owns the tools directory, registration
  and runner state; bot code runs as `bot` (UID 10003) and cannot replace those files. Bots still share
  their bot user, workspace and model logins. Start with the release's
  [runner Compose file](../docker/runner.compose.yaml), which supplies the required user and capabilities.
- **Native Mac/Linux and legacy containers without isolation**: bots share the runner's user and can
  replace a CLI or reach that user's runner state. See the isolation notes in
  [Install](install.md#add-computers-to-run-your-bots) and [Security](../SECURITY.md).

## Updating and pinning

Every day the runner asks each harness it installed for the newest release. With the default policy (`latest`) it
installs the new version **between runs**: the copy is downloaded and checked beside the old one while runs are in progress,
and switched in only at a moment no run in progress uses that harness (a run on another harness does not hold it
back). A failed install keeps the working version and is retried after 30 minutes.

A harness can be **pinned** to a version: the runner keeps that version and only reports that a newer one exists.
The manifest can ship a pin (`[update] policy = "pinned"`, `pin = "1.2.3"`), and the owner can pin or unpin per
computer.

**Settings > Computers** shows a chip per harness on each computer: name, version, `pinned`, `<version> available`,
`installing`, `updating`. The owner (and only the owner) sees the actions, for installs the runner manages:

- **Update**: install the newest release now (waits for an idle moment; moves the pin if the harness is pinned).
- **Pin to this version** / **Resume updates**.

Each request is an audit event (`runner.harness.update|pin|unpin`, then `runner.harness.done|failed`) and travels the
same way as the browser sign-in: the server keeps the request, the runner polls `GET /api/v2/runner-harness-actions`
and reports back. Nothing listens on the runner. A request the computer does not answer within six hours expires.

The readiness heartbeat carries, per harness: `installed`, `version`, `pinned` (and `pin`), `authenticated`,
`update_available` (and `latest`), `managed` (installed by the runner, not by a human), `wanted`, `state`. A runner
talking to a server from before this change drops the field instead of going offline.

## Writing a harness

A harness is a manifest plus a host adapter.

1. **Host adapter**: `runner/hosts/<host>.py`, a `Host` subclass (`runner/hosts/base.py`: `start_thread`, `start_turn`,
   `interrupt`, and events through `emit`). Register it in `Runner.make_host` (`runner/service.py`).
2. **Manifest**: `runner/harnesses/<id>.toml`. The file name is the id.

   ```toml
   id = "acme-agent"            # lowercase letters, digits, hyphens
   name = "Acme Agent"
   host = "acme"                # runner/hosts/acme.py
   executable = "acme"          # what the host runs, looked up on PATH
   providers = ["acme"]         # provider ids from backend/providers.py; one harness per provider
   # catch_all = true           # at most one harness; it serves providers with no CLI of their own

   [install]
   method = "npm"               # npm | pip | script | binary
   package = "@acme/agent"      # npm and pip
   # script: url (https), prefix_env (variable that tells the script where to install), bin (path inside it)
   # binary: url with {os} and {arch}, and [install.sha256] "linux-arm64" = "<hex>" per platform (required)

   [version]
   args = ["--version"]
   pattern = '(\d+\.\d+\.\d+)'  # one capture group

   [update]
   policy = "latest"            # latest | pinned (a pinned manifest also needs pin = "1.2.3")

   [auth]
   methods = ["device-code", "subscription", "api-key"]
   api_key_env = ["ACME_API_KEY"]

   [login]                      # only for device-code / subscription sign-in through the browser relay
   command = ["login", "--device-auth"]
   terminal = false             # true when the CLI insists on a terminal
   paste_code = false           # true when the sign-in page hands back a code to paste
   ```

3. **Provider and models**: add the provider (with `runtime` and `harness`) and its models to `backend/providers.py`.
   If the CLI signs in through the browser relay, add its runtime to `RUNTIMES` (and `PASTE_RUNTIMES`) in
   `backend/model_login.py`; a test checks that this list matches the manifests.
4. **Check**: `runner/tests/test_harness_tools.py` validates every manifest (file name, host adapter, unique
   providers, install fields) and that the provider list and manifests agree.

Loading fails loudly on a bad manifest, naming the file and the field.
