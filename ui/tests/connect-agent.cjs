// Offline browser regression: "Connect an agent" beside the account menu. The owner and bot
// administrators see it (also in the phone drawer), everyone else does not; the dialog makes a
// personal token labelled after the agent and shows one block to paste: the runner MCP address,
// the bearer and the skill the server hands out. No provider or Hub requests leave here.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const SKILL = 'SKILL: "Who needs me" — working Ana\'s Acme bots through the tico-hub MCP\n\nCall hub_batch_start.\n' +
  '1. When the person asks "who needs me", call hub_batch_start and read every item before answering; never guess.\n' +
  '2. A long unbroken reference must wrap too: https://runner.tico-ui.test/api/v2/conversations/0f6e56aa-2b1e-4f7a-9f00-000000000000/snapshot?include=refs\n';
const MCP_URL = 'https://runner.tico-ui.test/api/v2/mcp';
const shots = process.env.TICO_SCREENSHOT_DIR;   // TICO_SCREENSHOT_DIR=<dir> saves the review screenshots
const shoot = async (page, name) => { if (!shots) return; fs.mkdirSync(shots, {recursive: true}); await page.evaluate(() => document.fonts.ready); await page.waitForTimeout(350); await page.screenshot({path: path.join(shots, name)}); };
(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const run = async (me, expectButton, viewport = {width: 1440, height: 900}) => {
      const page = await browser.newPage({viewport, serviceWorkers: 'block', colorScheme: me.dark ? 'dark' : 'light'});
      await page.addInitScript(() => { window.__copied = []; navigator.clipboard.writeText = async text => { window.__copied.push(text); }; });
      const errors = [];
      page.on('pageerror', e => errors.push(e.message));
      const posted = [];
      await page.route('**/*', route => {
        const p = new URL(route.request().url()).pathname, method = route.request().method();
        const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
        if (shots && /^fonts\.(googleapis|gstatic)\.com$/.test(new URL(route.request().url()).hostname)) return route.continue();   // icons in the review screenshots
        const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
        if (ui) { const file = path.join(__dirname, '..', ui[1]); if (fs.existsSync(file)) return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(file,'utf8')}); }
        if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
        if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
        if (p === '/api/me') return json({id: me.id, role: me.role, name: me.name, email: me.id + '@acme.example', cloud: true, bot_admin: me.bot_admin, registered: true});
        if (p === '/api/employees') return json([]);
        if (p === '/api/people') return json({people: [], teams: {}});
        if (p === '/api/issues') return json([]);
        if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
        if (p === '/api/v2/status') return json({bots: []});
        if (p === '/api/v2/needs-you') return json({items: []});
        if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
        if (p === '/api/v2/agent-skill') return json({mcp_url: MCP_URL, text: SKILL});
        if (p === '/api/v2/me/tokens' && method === 'POST') {
          const body = route.request().postDataJSON(); posted.push(body);
          return json({id: 't9', token: 'tico_pt_SHOWN-ONCE', label: body.label, expires_at: new Date(Date.now() + 90 * 86400000).toISOString()});
        }
        return json({});
      });
      await page.goto('https://tico-ui.test/#/help');
      await page.waitForFunction(() => !document.querySelector('#account .account-email')?.textContent.includes('Signing in'));
      const button = page.locator('#connect-agent');
      if (viewport.width < 760) await page.locator('#mobile-more').click();
      if (!expectButton) {
        assert.equal(await button.isVisible(), false, `${me.id} must not see Connect an agent`);
        assert.deepEqual(errors, []);
        await page.close();
        return posted;
      }
      assert.equal(await button.isVisible(), true, `${me.id} sees Connect an agent`);
      assert.equal(await button.getAttribute('aria-label'), 'Connect an agent');
      await button.click();
      const dialog = page.locator('dialog.connect-agent[open]');
      await dialog.waitFor();
      // A title, one intro line, the agent as a segmented control and one primary button.
      assert.equal(await dialog.locator('h2').innerText(), 'Connect an agent');
      assert.deepEqual(await dialog.locator('.ca-seg label').allInnerTexts(), ['Grok Bot', 'Meta Muse', 'Other']);
      assert.equal(await dialog.locator('input[name=agent]:checked').getAttribute('value'), 'grok-bot');
      assert.equal(await dialog.locator('button.primary').count(), 1);
      assert.equal(await dialog.locator('[data-other]').isVisible(), false, 'the name field waits for Other');
      if (!me.other) await shoot(page, `connect-agent-${viewport.width}-before${me.dark ? '-dark' : ''}.png`);
      if (me.other) {
        await dialog.locator('.ca-seg label', {hasText: 'Other'}).click();
        const seg = await dialog.locator('.ca-seg').boundingBox(), field = await dialog.locator('input[name=other]').boundingBox();
        assert(field && field.y < seg.y + seg.height + 60, 'the name field appears inline, beside or right under the choice');
        await dialog.locator('input[name=other]').fill(me.other);
        await shoot(page, `connect-agent-${viewport.width}-before-other.png`);
      }
      await dialog.locator('button[type=submit]').click();
      await dialog.locator('[data-setup]').waitFor();
      const block = await dialog.locator('[data-setup]').textContent();
      assert.match(block, /Name: tico-hub/);
      assert.ok(block.includes('URL: ' + MCP_URL), 'the runner MCP address');
      assert.ok(block.includes('Authorization: Bearer tico_pt_SHOWN-ONCE'), 'the bearer');
      assert.ok(block.endsWith(SKILL), 'the skill the server hands out');
      assert.match(await dialog.locator('.ca-note').textContent(), /shown once and will not be shown again.*Settings → Devices → API tokens/s);
      assert.deepEqual((await dialog.locator('.ca-steps li').allInnerTexts()).length, 3, 'three numbered steps');
      assert.match(await dialog.locator('.ca-steps').innerText(), new RegExp(`Copy the block[\\s\\S]*Paste it into ${me.other ? 'Claude Desktop' : 'Grok Bot'}\\.[\\s\\S]*who needs me`));
      // The block wraps inside the dialog: no sideways scroll, and the dialog fits the screen.
      const pre = await dialog.locator('[data-setup]').evaluate(el => ({sw: el.scrollWidth, cw: el.clientWidth, ws: getComputedStyle(el).whiteSpace}));
      assert(pre.sw <= pre.cw + 1 && pre.ws === 'pre-wrap', 'the block wraps: ' + JSON.stringify(pre));
      const d = await dialog.boundingBox();
      assert(d.x >= 0 && d.x + d.width <= viewport.width && d.y >= 0 && d.y + d.height <= viewport.height, 'the dialog fits the screen');
      const copyBox = await dialog.locator('[data-copy-setup]').boundingBox(), blockBox = await dialog.locator('.ca-block').boundingBox();
      assert(copyBox.y - blockBox.y < 40 && blockBox.x + blockBox.width - (copyBox.x + copyBox.width) < 40, 'Copy sits in the top-right corner of the block');
      await dialog.locator('[data-copy-setup]').click();
      await page.waitForFunction(() => window.__copied.length === 1);
      assert.equal(await page.evaluate(() => window.__copied[0]), block);
      assert.match(await dialog.locator('[data-copy-setup]').innerText(), /Copied/);
      await shoot(page, `connect-agent-${viewport.width}-after${me.other ? '-other' : ''}${me.dark ? '-dark' : ''}.png`);
      await dialog.locator('[data-close]').click();
      await page.waitForFunction(() => !document.querySelector('dialog.connect-agent'));
      assert.deepEqual(errors, []);
      await page.close();
      return posted;
    };
    assert.deepEqual(await run({id: 'ana', role: 'owner', name: 'Ana', bot_admin: true}, true),
                     [{label: 'grok-bot', expires_in_days: 90}]);
    assert.deepEqual(await run({id: 'ben', role: 'viewer', name: 'Ben', bot_admin: true, other: 'Claude Desktop!'}, true),
                     [{label: 'claude-desktop', expires_in_days: 90}]);
    assert.deepEqual(await run({id: 'ana', role: 'owner', name: 'Ana', bot_admin: true, dark: true}, true, {width: 390, height: 844}),
                     [{label: 'grok-bot', expires_in_days: 90}]);
    assert.deepEqual(await run({id: 'cara', role: 'viewer', name: 'Cara Mendes', bot_admin: false}, false), []);
    console.log('Connect an agent: owner and bot admin see it (phone too), token labelled after the agent, one block with MCP URL, bearer and skill, hidden for others passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
