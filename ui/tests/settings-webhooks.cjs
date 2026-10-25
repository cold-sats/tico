// Settings > Webhooks (ui/app/settings-webhooks.js) against a fake server. Guards: #/triggers and the old Triggers tab
// land on Webhooks; a new incoming webhook (name, preset, keep days) is made in its three calls and its address and
// signing secret show once, gone after Back; a webhook's detail lists its routine and rules and warns when a rule
// wakes a bot a routine already gives a task; its call log opens a payload (redacted headers, body) and runs one
// again; Tico Team's built-in webhook is read-only but for Edit; an outgoing endpoint is made with the catalog's
// event picker (a whole group is `group.*`) and shows its secret once; its sends retry; the Gateway tab asks for the
// Gateway first, then makes an address shown once. No sideways scroll on a phone. TICO_SHOTS=<dir> saves screenshots.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const {html, uiFile} = require('./support/page.cjs');
const {unrouted} = require('./support/routes.cjs');
const shots = process.env.TICO_SHOTS || '';
const CATALOG = JSON.parse(execFileSync(process.env.TICO_PYTHON || 'python3', ['-c', 'import json; from backend.event_catalog import listing; print(json.dumps(listing()))'],
  {cwd: path.join(__dirname, '../..')}).toString());
const BASE = 'https://tico.acme.example/hooks';
const AGO = m => new Date(Date.now() - m * 60000).toISOString();

function trigger(id, name, more = {}) {
  return {id, name, kind: 'webhook', event: 'webhook.' + id, url: `${BASE}/${id}`, builtin: false, created_by: 'human:ana', created_at: AGO(900),
    last_received: null, received_24h: 0, refused_24h: 0, signed: false, preset: 'none', type_from: '', hourly: 60, keep_days: 7, unheard: 'log',
    routines: [], relay: null, ...more};
}
function server() {
  return {
    triggers: [
      trigger('shop', 'Shop', {last_received: AGO(4), received_24h: 12, refused_24h: 2, signed: true, preset: 'github', type_from: 'X-GitHub-Event',
        routines: [{id: 'r1', bot: 'eng', title: 'Handle new orders'}]}),
      trigger('_tico', 'Tico Team', {builtin: true, url: '', created_by: 'keeper', type_from: '/kind', keep_days: 30}),
    ],
    deliveries: {shop: [
      {delivery: 'd2', sent_id: 'gh-2', received_at: AGO(4), bytes: 2300, tasks: 1, outcome: 'accepted', reason: '', type: 'push', via: 'direct', rules: 1, stored: true},
      {delivery: 'd1', sent_id: '', received_at: AGO(70), bytes: 120, tasks: 0, outcome: 'refused', reason: 'bad signature', type: '', via: 'gateway', rules: 0, stored: false}],
    _tico: [], orders: []},
    rules: [{id: 'rw', scope_kind: 'team', scope_id: '', event: 'webhook.received', when: {trigger: 'shop', type: 'push'}, then: 'wake',
      params: {bot: 'eng', text: 'Look'}, enabled: true, built_in: false},
    {id: 'rx', scope_kind: 'team', scope_id: '', event: 'webhook.received', when: {trigger: 'other'}, then: 'wake', params: {bot: 'ops'}, enabled: true}],
    hooks: [{id: 'wh1', name: 'Zapier', url: 'https://hooks.zapier.com/a/b', host: 'hooks.zapier.com', events: ['task.*', 'approval.decided'], enabled: false,
      paused_reason: 'Failing for 3 days', rate_per_hour: 600, allow_http: false, created_by: 'human:ana', revision: 2, can_change: true, old_secret_until: null,
      last_7_days: {delivered: 40, failed: 3, pending: 0}}],
    sends: {wh1: [{id: 's2', webhook_id: 'wh1', type: 'task.done', subject: 't-9', state: 'failed', attempts: 5, last_status: 500, last_error: 'HTTP 500', created: AGO(30)},
      {id: 's1', webhook_id: 'wh1', type: 'approval.decided', subject: 'a-1', state: 'delivered', attempts: 1, last_status: 200, last_error: '', created: AGO(90)}]},
    relay: {key: 'none', relays: 0, cursor: 0, last_pull: null, last_error: '', pending: 0, oldest: null, deleting: 0, active: false},
    posts: [],
  };
}

async function open(browser, hash, viewport = {width: 1280, height: 860}, state = server(), store = {}) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block'});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('dialog', d => d.accept());
  if (store.tab) await page.addInitScript(tab => sessionStorage.setItem('tico.settings.tab', tab), store.tab);
  await page.route('**/*', route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname;
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1])))
      return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p.startsWith('/vendor/') && fs.existsSync(uiFile(p.slice(1)))) return route.fulfill({body: fs.readFileSync(uiFile(p.slice(1))),
      contentType: p.endsWith('.woff2') ? 'font/woff2' : 'application/javascript'});
    if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    const config = {version: '0.4.9', app_name: 'Tico'};
    const post = req.method() === 'POST' ? (req.postDataJSON() || {}) : null;
    if (post) state.posts.push({path: p, body: post});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@acme.example', cloud: true, registered: true, config});
    if (p === '/api/v2/config') return json(config);
    if (p === '/api/employees') return json([{name: 'eng', display_name: 'Engineer', status: 'active', can_manage: true},
      {name: 'ops', display_name: 'Ops', status: 'active', can_manage: true}]);
    if (p === '/api/issues') return json([]);
    if (p === '/api/humans' || p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}], teams: {}});
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/needs-you') return json({items: []});
    if (p === '/api/v2/operations') return json({machines: [], services: []});
    if (p === '/api/v2/event-types') return json({items: CATALOG});
    if (p === '/api/v2/rules') return json({rules: state.rules, events: ['comment'], sourceless_events: ['webhook.received'], more: false});
    if (p === '/api/v2/triggers' && !post) return json({triggers: state.triggers});
    if (p === '/api/v2/triggers') {
      const id = post.name.toLowerCase();
      state.triggers.push(trigger(id, post.name));
      return json({trigger: {id, event: 'webhook.' + id, url: `${BASE}/${id}/sek-ret-123`, replayed: false}});
    }
    let m = p.match(/^\/api\/v2\/triggers\/([^/]+)(?:\/(.*))?$/);
    if (m) {
      const t = state.triggers.find(x => x.id === m[1]), rest = m[2] || '';
      if (rest === '' && post) { Object.assign(t, post); return json(t); }
      if (rest === 'signing') { Object.assign(t, {signed: true, preset: post.preset, type_from: t.type_from || {github: 'X-GitHub-Event', standard: '/type', stripe: '/type'}[post.preset] || ''}); return json({trigger: {id: t.id, signed: true, preset: post.preset, signing_secret: 'whsec_c2VjcmV0', replayed: false}}); }
      if (rest === 'deliveries') return json({deliveries: state.deliveries[t.id] || []});
      if (rest === 'relay') { t.relay = {address_prefix: 'https://gw.tico.dev/v1/hooks/rl_1', created: AGO(0)}; return json({relay: {trigger: t.id, relay_id: 'rl_1', address_prefix: t.relay.address_prefix, address: t.relay.address_prefix + '/gw-secret', replayed: false}}); }
      const d = rest.match(/^deliveries\/([^/]+)(\/replay)?$/);
      if (d && d[2]) return json({replay: {delivery: d[1] + ':replay:1', of: d[1], tasks: 1, rules: 1}});
      if (d) return json({delivery: {id: d[1], received_at: AGO(4), type: 'push', via: 'direct', outcome: 'accepted', tasks: 1, rules: 1, reason: '', bytes: 2300,
        expires_at: AGO(-6000), expired: false, content_type: 'application/json',
        headers: {'content-type': 'application/json', 'x-github-event': 'push', 'x-hub-signature-256': '[hidden]'}, body: '{"id":7,"ref":"refs/heads/main"}'}});
    }
    if (p === '/api/v2/webhooks' && !post) return json({items: state.hooks, more: false});
    if (p === '/api/v2/webhooks') {
      const h = {...state.hooks[0], id: 'wh2', name: post.name, url: post.url, host: new URL(post.url).host, events: post.events, enabled: true, paused_reason: '', revision: 1,
        last_7_days: {delivered: 0, failed: 0, pending: 0}};
      state.hooks.push(h); state.sends.wh2 = [];
      return json({webhook: {...h, secret: 'whsec_b3V0Z29pbmc=', replayed: false}});
    }
    m = p.match(/^\/api\/v2\/webhooks\/([^/]+)(?:\/(.*))?$/);
    if (m) {
      const h = state.hooks.find(x => x.id === m[1]), rest = m[2] || '';
      if (rest === '') return json({webhook: h, recent_attempts: []});
      if (rest === 'sends') return json({items: state.sends[h.id] || [], more: false});
      if (rest === 'resume') { h.enabled = true; return json({webhook: h}); }
      return json({ok: true});
    }
    if (p === '/api/v2/relay') return json({relay: state.relay});
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json(unrouted(p));
  });
  await page.goto('https://tico-ui.test/' + hash);
  return {page, errors, state};
}
const settled = page => page.evaluate(() => Promise.all(document.getAnimations().map(a => a.finished.catch(() => {}))));
const noSideways = page => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1);

(async () => {
  const browser = await chromium.launch({headless: true, channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  const shot = async (page, name, el = '#settings-webhooks') => { if (shots) await page.locator(el).screenshot({path: path.join(shots, name + '.png')}); };
  try {
    {
      // #/triggers lands on Settings > Webhooks, Incoming; the list has the built-in Tico Team row.
      const {page, errors, state} = await open(browser, '#/triggers');
      const pane = page.locator('#settings-webhooks');
      await pane.locator('[data-wh-open="shop"]').waitFor();
      assert.equal(new URL(page.url()).hash, '#/settings');
      assert.equal(await page.locator('[data-settings-tab="webhooks"]').innerText(), 'Webhooks');
      assert.equal(await pane.locator('[data-wh-tab="incoming"]').getAttribute('aria-checked'), 'true');
      assert.match(await pane.locator('[data-wh-open="shop"]').innerText(), /12 in 24h · 2 refused/);
      assert.match(await pane.locator('[data-wh-open="_tico"]').innerText(), /Built-in/);
      await shot(page, 'incoming-list-desktop');

      // New webhook: create, then signing, then the settings that differ; the secrets show once.
      await pane.locator('[data-wh-new]').click();
      const dialog = page.locator('.wh-dialog');
      await dialog.locator('[name=name]').fill('Orders');
      await dialog.locator('[name=preset]').selectOption('standard');
      assert.equal(await dialog.locator('[name=type_from]').inputValue(), '/type', 'the preset fills where the type comes from');
      await dialog.locator('[name=keep_days]').fill('14');
      await dialog.locator('[name=unheard]').selectOption('note');
      if (shots) { await settled(page); await dialog.screenshot({path: path.join(shots, 'incoming-new-desktop.png')}); }
      await dialog.locator('button[type=submit]').click();
      await dialog.waitFor({state: 'detached'});
      await pane.locator('[data-wh-secret="url"]').waitFor();
      assert.deepEqual(state.posts.map(x => x.path), ['/api/v2/triggers', '/api/v2/triggers/orders/signing', '/api/v2/triggers/orders']);
      assert.deepEqual(state.posts[1].body, {preset: 'standard'});
      assert.deepEqual(state.posts[2].body, {keep_days: 14, unheard: 'note'});
      assert.equal(await pane.locator('[data-wh-secret="url"] code').innerText(), `${BASE}/orders/sek-ret-123`);
      assert.equal(await pane.locator('[data-wh-secret="signing"] code').innerText(), 'whsec_c2VjcmV0');
      await shot(page, 'incoming-created-desktop');
      await pane.locator('[data-wh-back]').click();
      await pane.locator('[data-wh-open="orders"]').click();
      await pane.locator('.wh-facts').waitFor();
      assert.equal(await pane.locator('[data-wh-secret]').count(), 0, 'shown once');
      assert.match(await pane.locator('.wh-facts').innerText(), /\/hooks\/orders\/…/);
      assert.match(await pane.locator('.wh-facts').innerText(), /Type from\s+\/type/);
      await pane.locator('[data-wh-back]').click();

      // Shop: listeners, the double-wake warning, the call log, View payload and Run again.
      await pane.locator('[data-wh-open="shop"]').click();
      await pane.locator('[data-wh-calls]').waitFor();
      assert.match(await pane.locator('[data-wh-listeners]').innerText(), /Handle new orders[\s\S]*WHEN type push THEN wake Engineer/);
      assert.doesNotMatch(await pane.locator('[data-wh-listeners]').innerText(), /Ops/, 'a rule on another webhook is not listed');
      assert.match(await pane.locator('[data-wh-twice]').innerText(), /^Engineer:/);
      assert.equal(await pane.locator('[data-wh-call]').count(), 2);
      assert.equal(await pane.locator('[data-wh-call="d1"] [data-wh-payload]').count(), 0, 'nothing to view once the body is gone');
      assert.match(await pane.locator('[data-wh-call="d1"]').innerText(), /Refused bad signature/);
      await shot(page, 'incoming-detail-desktop');
      await pane.locator('[data-wh-call="d2"] [data-wh-payload]').click();
      const payload = page.locator('.wh-dialog');
      await payload.locator('[data-wh-body]').waitFor();
      assert.match(await payload.locator('[data-wh-headers]').innerText(), /x-hub-signature-256: \[hidden\]/);
      assert.equal(await payload.locator('[data-wh-body]').innerText(), '{\n  "id": 7,\n  "ref": "refs/heads/main"\n}');
      if (shots) { await settled(page); await payload.screenshot({path: path.join(shots, 'payload-desktop.png')}); }
      await payload.locator('[data-close]').click();
      const replayed = page.waitForResponse(r => r.url().endsWith('/deliveries/d2/replay'));
      await pane.locator('[data-wh-call="d2"] [data-wh-replay]').click();
      await replayed;
      assert.ok(state.posts.some(x => x.path === '/api/v2/triggers/shop/deliveries/d2/replay'));
      await pane.locator('[data-wh-back]').click();

      // Tico Team's built-in: Edit only, keep days only.
      await pane.locator('[data-wh-open="_tico"]').click();
      await pane.locator('.wh-facts').waitFor();
      assert.equal(await pane.locator('[data-wh-edit]').count(), 1);
      assert.equal(await pane.locator('[data-wh-rotate], [data-wh-sign], [data-wh-delete]').count(), 0);
      assert.doesNotMatch(await pane.locator('.wh-facts').innerText(), /Address/);
      await pane.locator('[data-wh-edit]').click();
      assert.deepEqual(await page.locator('.wh-dialog form').evaluate(f => [...f.elements].filter(e => e.name).map(e => e.name)), ['keep_days']);
      await page.locator('.wh-dialog [name=keep_days]').fill('10');
      await page.locator('.wh-dialog button[type=submit]').click();
      await page.locator('.wh-dialog').waitFor({state: 'detached'});
      assert.deepEqual(state.posts.at(-1), {path: '/api/v2/triggers/_tico', body: {keep_days: 10}});
      await pane.locator('[data-wh-back]').click();

      // Outgoing: the picker sends a whole group as group.* and single events by name; the secret shows once.
      await pane.locator('[data-wh-tab="outgoing"]').click();
      await pane.locator('[data-wh-hook="wh1"]').waitFor();
      assert.match(await pane.locator('[data-wh-hook="wh1"]').innerText(), /Paused[\s\S]*40 sent · 3 failed/);
      await shot(page, 'outgoing-list-desktop');
      await pane.locator('[data-wh-hook-new]').click();
      const make = page.locator('.wh-dialog');
      await make.locator('[name=name]').fill('Make.com');
      await make.locator('[name=url]').fill('https://hook.make.com/abc');
      await make.locator('[data-ev-all]').uncheck();
      assert.equal(await make.locator('.wh-ev-groups input:checked').count(), 0, 'unchecking All clears the boxes');
      await make.locator('[data-ev-group="task"] [data-ev-head]').check();
      await make.locator('[data-ev-name="approval.decided"]').check();
      assert.equal(await make.locator('[data-ev-group="task"] [data-ev-name]:checked').count(), CATALOG.filter(e => e.group === 'task').length);
      if (shots) { await settled(page); await make.screenshot({path: path.join(shots, 'outgoing-new-desktop.png')}); }
      await make.locator('button[type=submit]').click();
      await make.waitFor({state: 'detached'});
      await pane.locator('[data-wh-secret="secret"]').waitFor();
      const created = state.posts.find(x => x.path === '/api/v2/webhooks');
      assert.deepEqual(created.body.events, ['task.*', 'approval.decided']);
      assert.equal(await pane.locator('[data-wh-secret="secret"] code').innerText(), 'whsec_b3V0Z29pbmc=');
      await pane.locator('[data-wh-back]').click();
      await pane.locator('[data-wh-hook="wh1"]').click();
      await pane.locator('[data-wh-sends]').waitFor();
      assert.equal(await pane.locator('[data-wh-send="s2"] [data-wh-retry]').count(), 1);
      assert.equal(await pane.locator('[data-wh-send="s1"] [data-wh-retry]').count(), 0, 'no retry on a delivered send');
      await shot(page, 'outgoing-detail-desktop');
      const retried = page.waitForResponse(r => r.url().endsWith('/sends/s2/retry'));
      await pane.locator('[data-wh-send="s2"] [data-wh-retry]').click();
      await retried;
      const example = page.waitForResponse(r => r.url().endsWith('/wh1/example'));
      await pane.locator('[data-wh-example]').click();
      await example;
      await pane.locator('[data-wh-hook-pause]').click();
      await page.waitForFunction(() => document.querySelector('[data-wh-hook-pause]')?.textContent === 'Pause');
      const paths = state.posts.map(x => x.path);
      assert.ok(paths.includes('/api/v2/webhooks/wh1/sends/s2/retry') && paths.includes('/api/v2/webhooks/wh1/example') && paths.includes('/api/v2/webhooks/wh1/resume'), paths.join(' '));

      // Through Tico Gateway: no key yet.
      await pane.locator('[data-wh-tab="gateway"]').click();
      await pane.locator('[data-wh-no-key]').waitFor();
      assert.match(await pane.locator('[data-wh-no-key]').innerText(), /Connect the Gateway first/);
      await shot(page, 'gateway-no-key-desktop');
      // With a key: make an address, shown once.
      state.relay = {...state.relay, key: 'connected', last_pull: AGO(1), pending: 3, active: true};
      await pane.locator('[data-wh-tab="incoming"]').click();
      await pane.locator('[data-wh-tab="gateway"]').click();
      await pane.locator('[data-wh-relay="shop"] [data-wh-relay-do="make"]').click();
      await pane.locator('[data-wh-secret="relay"]').waitFor();
      assert.equal(await pane.locator('[data-wh-secret="relay"] code').innerText(), 'https://gw.tico.dev/v1/hooks/rl_1/gw-secret');
      assert.match(await pane.locator('[data-wh-relay-status]').innerText(), /3 waiting/);
      assert.equal(await pane.locator('[data-wh-relay="_tico"]').count(), 0, 'the built-in has no address to make');
      await shot(page, 'gateway-desktop');
      assert.deepEqual(errors, []);
      await page.close();
    }
    {
      // The old Triggers tab saved in this browser opens Webhooks too.
      const {page, errors} = await open(browser, '#/settings', undefined, undefined, {tab: 'triggers'});
      await page.locator('#settings-webhooks [data-wh-open="shop"]').waitFor();
      assert.equal(await page.locator('#settings-webhooks').isVisible(), true);
      assert.deepEqual(errors, []);
      await page.close();
    }
    {
      // Phone: list, detail, outgoing and Gateway with nothing sideways.
      const state = server();
      state.relay = {...state.relay, key: 'connected', last_pull: AGO(1), pending: 0};
      state.triggers[0].relay = {address_prefix: 'https://gw.tico.dev/v1/hooks/rl_1', created: AGO(60)};
      const {page, errors} = await open(browser, '#/settings/webhooks', {width: 390, height: 844}, state);
      const pane = page.locator('#settings-webhooks');
      await pane.locator('[data-wh-open="shop"]').waitFor();
      assert.equal(await pane.locator('[data-wh-tab="gateway"]').innerText(), 'Gateway', 'the short label on a phone');
      assert.ok(await noSideways(page), 'list');
      await shot(page, 'incoming-list-phone');
      await pane.locator('[data-wh-open="shop"]').click();
      await pane.locator('[data-wh-calls]').waitFor();
      assert.ok(await noSideways(page), 'detail');
      await shot(page, 'incoming-detail-phone');
      await pane.locator('[data-wh-call="d2"] [data-wh-payload]').click();
      await page.locator('.wh-dialog [data-wh-body]').waitFor();
      if (shots) { await settled(page); await page.screenshot({path: path.join(shots, 'payload-phone.png')}); }
      await page.locator('.wh-dialog [data-close]').click();
      await pane.locator('[data-wh-back]').click();
      await pane.locator('[data-wh-new]').click();
      await page.locator('.wh-dialog [name=name]').waitFor();
      if (shots) { await settled(page); await page.screenshot({path: path.join(shots, 'incoming-new-phone.png')}); }
      await page.locator('.wh-dialog [data-close]').click();
      await pane.locator('[data-wh-tab="outgoing"]').click();
      await pane.locator('[data-wh-hook="wh1"]').waitFor();
      assert.ok(await noSideways(page), 'outgoing list');
      await shot(page, 'outgoing-list-phone');
      await pane.locator('[data-wh-hook-new]').click();
      await page.locator('.wh-dialog [data-wh-events]').waitFor();
      assert.ok(await page.locator('.wh-dialog').evaluate(d => d.scrollWidth <= d.clientWidth + 1), 'the picker fits');
      if (shots) { await settled(page); await page.screenshot({path: path.join(shots, 'outgoing-new-phone.png')}); }
      await page.locator('.wh-dialog [data-close]').click();
      await pane.locator('[data-wh-hook="wh1"]').click();
      await pane.locator('[data-wh-sends]').waitFor();
      assert.ok(await noSideways(page), 'outgoing detail');
      await shot(page, 'outgoing-detail-phone');
      await pane.locator('[data-wh-tab="gateway"]').click();
      await pane.locator('[data-wh-relays]').waitFor();
      assert.ok(await noSideways(page), 'gateway');
      await shot(page, 'gateway-phone');
      assert.deepEqual(errors, []);
      await page.close();
    }
  } finally { await browser.close(); }
  console.log('settings-webhooks ok');
})().catch(error => { console.error(error); process.exit(1); });
