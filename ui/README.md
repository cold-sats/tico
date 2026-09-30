# ui/

The web UI: plain HTML, CSS and classic scripts, served as they are. There is no build step and no
module system. Every script shares the page's globals (`S`, `$`, `esc`, `get`, `post`, `route`, ...).

    index.html        the markup skeleton, then <link> and <script> tags in load order; no inline script
    styles/*.css      the stylesheet, one file per area, linked in cascade order
    app/*.js          the app: routing, state, sidebar and one file per page or feature
    *.js              features that mount into a page through a small `window.*` API
                      (docs-page.js, goals-kpis.js, first-run.js, support.js, ...)
    assets/, vendor/  images, the icon font, marked
    tests/*.cjs       browser tests (`npm run test:ui`)
    sw.js             the service worker; it caches nothing, so a new file needs no entry here

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
