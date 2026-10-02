# Tico desktop app

Download **Tico** from your server's **Download for Mac**, **Download for Windows** or
**Download for Linux** link, or from the [latest GitHub release](https://github.com/ticoteam/tico/releases/latest).
The same app connects to any Tico server.

On macOS, open the universal `.dmg` and drag Tico to Applications. On Windows, run the
`-setup.exe` installer. On Linux, make the `.AppImage` executable and open it, or install the
`.deb` package. A Mac build without Apple signing and notarization may need **Open Anyway**
in System Settings > Privacy & Security on its first launch.

The first launch asks for the **Server** address, for example `https://tico.example.com`. Enter
your team's address and click **Connect**. Tico checks that the server is reachable and answers
its `/healthz` check as Tico, saves the address in the app's config folder, then opens your Team.
Sign in as you would in a browser. HTTPS is required; `http://localhost` and `http://127.0.0.1`
are allowed for a server on your Computer. A failed check shows an error below the field.

Use **Change server…** in the generic app's menu or tray menu to connect to another server.
The app saves the address and restarts automatically to replace its native permissions.
Only the selected server's origin can use native IPC; Access and external sign-in pages that
remain in the window receive no native permissions. Tico keeps
its tray icon when you close the main window. Click it to show or hide the window.

The app checks for signed updates automatically, installs them and relaunches. Generic builds
use the public GitHub release manifest; your server's web interface updates with the server.
No company build is needed.

## Optional per-environment builds

`scripts/app.sh --env <slug>` still builds an app with that environment's name, icon, bundle
identifier, server address and hub updater endpoint. See [Environments](environments.md).
`TICO_HUB_URL` can also bake in a server address at build time. An address supplied in the
process environment as `HUB_URL` wins over the baked address, which wins over the saved address.
Without any of those addresses, the local first-launch page opens. Environment builds hide
**Change server…** and ignore attempts to change the saved address; their built-in server
retains priority. Built-in, process and saved addresses may use HTTP for existing deployments;
only a newly entered first-launch or **Change server…** address requires HTTPS or loopback HTTP.

Servers offer the desktop assets from their running GitHub release when no bucket build exists
or that build is older. A bucket build of the same or a newer version remains available. If
GitHub cannot be reached, the download link waits until the next successful check; failures are
cached for ten minutes. Source checkouts reporting `dev` need a bucket build or a download from
GitHub directly.

A built-in server address is saved to `server.txt` when no saved address exists, so a later
generic build retains it if the bundle identifier is unchanged. CI uses `team.tico.app` for
both generic and hub builds. `scripts/app.sh --env` uses `team.tico.env.<environment id>`:
its config folder differs from the generic app, so installing the generic app separately
does not inherit that environment's settings. Environment updater feeds never offer generic
GitHub builds.
