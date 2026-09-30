# ui/

The web UI: plain HTML, CSS and classic scripts, served as they are. There is no build step and no
module system. Every script shares the page's globals (`S`, `$`, `esc`, `get`, `post`, `route`, ...).

    index.html        the markup skeleton, then <link> and <script> tags in load order; no inline script.
                      The tags between the `<!-- bundle:css:start/end -->` and `<!-- bundle:js:start/end -->`
                      markers are the styles and app scripts; the server bundles them (below)
    styles/*.css      the stylesheet, one file per area, linked in cascade order
    app/*.js          the app: routing, state, sidebar and one file per page or feature
    *.js              features that mount into a page through a small `window.*` API
                      (docs-page.js, goals-kpis.js, first-run.js, support.js, ...)
    assets/, vendor/  images, the icon font, marked
    tests/*.cjs       browser tests (`npm run test:ui`)
    sw.js             the service worker; it caches nothing (it lets the hashed bundle through to the browser cache)

## One request each: the bundle

The many files are for editing. The server (`backend/ui_bundle.py`) concatenates the files listed between the
markers, in that order, into `/tico/ui/app.bundle.js` and `/tico/ui/app.bundle.css` (each file after a
`// file: app/name.js` comment), and serves index.html with each region replaced by one tag,
`?v=<content hash>`. The bundles are immutable for that URL (`Cache-Control: public, max-age=31536000,
immutable`, strong ETag, gzip when the browser accepts it); index.html is revalidated on every load. It
rebuilds when a listed file changes, so editing needs no step. index.html is the only list: adding a file to it
adds it to the bundle.

A file that is not strict cannot share the bundle's one script (the bundle opens with `'use strict'` once), so
start every `app/` file with it. `TICO_UI_BUNDLE=off` serves the files separately, as listed. The browser
tests run the real bundler and serve the bundle by default; `TICO_UI_BUNDLE=off npm run test:ui` runs them on
the separate files. Files outside the markers (`ui/*.js`, `vendor/`) load on their own.

An open tab does not pick up a new release by itself. The config carries the release (`version`) and the served build
(`ui_build`, the `?v=` of the two bundle tags joined by a dot); `app/notices.js` compares both with what the page loaded with, on the
config poll and when a hidden tab is shown, and shows "New version · Reload" (`#stale-banner`). It is empty when the files are served
unbundled, so only the release is compared then.

## The rule

**One feature per file; load order is in index.html.** Add a page or feature as its own file and add its
`<script>` (or `<link>`) tag where it belongs. Nothing else lists files: the server serves the folder, the
icon-font scan (`scripts/build-icon-font.py`) reads `app/` and `styles/`, and the tests load whatever
`index.html` asks for.

Load order matters in two ways:

- **Scripts.** Function declarations are global once their file has loaded, so functions may call each other
  across files. A top-level statement that runs at load (`const x = f()`, `el.onclick = ...`,
  `addEventListener(...)`) may use only what earlier files define. Keep those statements in the order
  index.html lists the files: listeners on the same event fire in the order they were registered. `boot.js`
  is last; it starts the app.
- **Styles.** Later rules win at equal specificity, so `styles/*.css` keep the order they were cut in.
  `tokens.css` first, then base, then the areas.

Every file in `app/` starts with `'use strict'`, as the old inline script did. Use absolute URLs
(`/assets/...`) inside CSS: a stylesheet resolves relative URLs against its own path.

## Where things are

| File(s) in `app/` | What |
| --- | --- |
| core, markdown, viewer, format, api, state, notices | routes, `$`/`esc`/`md`, `safeMd`, the file viewer, formatting, `get`/`post`, the state `S` and company names, the new-version and usage notices |
| avatars, sidebar, heartbeat, tooltip | bot avatars and blobs, the org tree, heartbeat and account menu, hover status |
| issues, hub-v2, needs-you, bot-tasks | shared request rows and tables, hub v2 helpers, Needs you, a bot's tasks |
| chat, pill, bot-page, bot-conversation, person-page | bot chat and its live reply, the composer, the bot and person pages |
| tasks, task-modal, tasks-page, recurring | Tasks: rows and cards, the modal and its comments, the page, routines |
| meetings, mail, messaging, credentials, sql, integrations, help | one page each |
| settings, settings-*, vault, catalog | Settings: shell, one file per tab, the bot editor, access editor, credential vault, catalog cards |
| welcome, updates, goals | first run, Updates, Goals |
| router, drawer, search, org-fan, nav-events, viewport, refresh, native, boot | `route()`, account menu and phone drawer, search, mobile org switcher, keyboard viewport, the refresh loop, the desktop bridge, startup |

Files under about 1,500 lines; split a file along its section comments when it grows past that.
