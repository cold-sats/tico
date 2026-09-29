// Test that the session card in a bot's More tab displays the session ID
// and terminal resume command with working tap-to-copy interactions.
const {chromium} = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const html = fs.readFileSync(path.join(__dirname, "../index.html"), "utf8");

const hour = 3600e3, now = Date.now(), iso = ms => new Date(now + ms).toISOString();
const bot = (name, display_name, org_parent, extra = {}) => ({name, display_name, org_parent, host: "keeper",
  status: "active", can_chat: true, users: [{id: "ana", name: "Ana"}], schedules: [], ...extra});
const bots = [
  bot("coo", "Tico", ""),
  bot("cmo", "AI CMO", "", {runtime: "claude", model: "claude-opus-5-5"}),
];
const sid = "test-session-uuid-9876";

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? "chrome", headless: true});
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 900}, serviceWorkers: "block"});
    await context.grantPermissions(["clipboard-read", "clipboard-write"], {origin: "https://tico-ui.test"});
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    await page.route("**/*", route => {
      const url = new URL(route.request().url()), p = url.pathname, q = url.searchParams;
      const json = body => route.fulfill({contentType: "application/json", body: JSON.stringify(body)});
      if (url.origin !== "https://tico-ui.test") return route.abort();
      const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if (ui) {
        const file = path.join(__dirname, "..", ui[1]);
        if (fs.existsSync(file)) return route.fulfill({contentType: "application/javascript", body: fs.readFileSync(file, "utf8")});
      }
      if (p === "/") return route.fulfill({contentType: "text/html", body: html});
      if (p === "/api/me") return json({id: "ana", role: "owner", name: "Ana", email: "ana@example.test", cloud: true});
      if (p === "/api/people") return json({people: [{id: "ana", name: "Ana"}]});
      if (p === "/api/employees") return json(bots);
      if (p === "/api/issues") return json([]);
      if (p === "/api/status") return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
      if (p === "/api/v2/status") return json({bots: [{bot: "cmo", state: "idle"}]});
      if (p === "/api/v2/needs-you") return json({items: []});
      if (p === "/api/v2/goals") return json({goals: [], chain: [], reports: [], company: []});
      if (p === "/api/v2/tasks") return json({tasks: []});
      if (p === "/api/v2/conversations") return json({conversations: [{id: "cmo-chat", kind: "chat", scope: "personal", participants: ["human:ana", "bot:cmo"]}]});
      if (p.endsWith("/snapshot")) return json({messages: [], execution: null});
      if (p.endsWith("/watch")) return route.fulfill({contentType: "text/event-stream", body: ": fixture\n\n"});
      if (p === "/api/employees/cmo/session") return json({
        cloud: true,
        current: true,
        runtime: "claude",
        model: "claude-opus-5-5",
        session_id: sid,
        provider_session: {
          bot: "cmo",
          runtime: "claude",
          model: "claude-opus-5-5",
          thread_id: sid,
          runner_id: "runner-ana-mac",
          tokens_in: 1250,
          updated: iso(-hour)
        },
        turns: [
          {role: "user", text: "Draft campaign", ts: iso(-hour)},
          {role: "assistant", text: "Campaign drafted.", ts: iso(-hour + 60e3)}
        ],
        runs: [],
        first_ts: iso(-hour),
        last_ts: iso(-hour + 60e3),
        turn_count: 2,
        shown: 2,
        skipped: 0
      });
      return json({});
    });

    await page.goto("https://tico-ui.test/#/bot/cmo");
    await page.waitForFunction(() => BOT?.slug === "cmo" && V2C?.rendered);

    // Navigate to More tab
    await page.goto("https://tico-ui.test/#/bot/cmo/more");

    // Wait for the session resume block to appear in #sess-head
    await page.waitForSelector("#sess-head .sess-resume", {timeout: 5000});

    // Verify session ID is rendered
    const idEl = await page.$("[data-copy-sess-id]");
    assert(idEl, "data-copy-sess-id element should exist");
    const idAttr = await idEl.getAttribute("data-copy-sess-id");
    assert.equal(idAttr, sid, "Session ID attribute should match");

    // Verify resume command is rendered
    const expectedCmd = `cd ~/tico-work/emp-cmo && claude --resume ${sid}`;
    const cmdEl = await page.$("[data-copy-sess-cmd]");
    assert(cmdEl, "data-copy-sess-cmd element should exist");
    const cmdAttr = await cmdEl.getAttribute("data-copy-sess-cmd");
    assert.equal(cmdAttr, expectedCmd, "Resume command attribute should match");

    // Each copy creates a new .toast that lives 3.5s, so toasts stack. Clear any
    // earlier toast before each click and wait for the exact new text; checking
    // document.querySelector(".toast") only saw the oldest (stale) toast.
    const copyAndExpect = async (selector, value, message) => {
      await page.evaluate(() => {
        document.querySelectorAll(".toast").forEach(t => t.remove());
        return navigator.clipboard.writeText("");
      });
      await page.click(selector);
      await page.locator(".toast", {hasText: message}).waitFor({timeout: 5000});
      assert.equal(await page.evaluate(() => navigator.clipboard.readText()), value, `${selector} should copy ${value}`);
    };
    await copyAndExpect("button[data-copy-sess-id]", sid, "Session ID copied");
    await copyAndExpect("button[data-copy-sess-cmd]", expectedCmd, "Resume command copied");
    await copyAndExpect("code[data-copy-sess-id]", sid, "Session ID copied");
    await copyAndExpect("code[data-copy-sess-cmd]", expectedCmd, "Resume command copied");

    assert.equal(errors.length, 0, `Unexpected page errors: ${errors.join("; ")}`);
    console.log("PASS: session resume box renders session ID and command with working copy interactions.");
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
