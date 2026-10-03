// Exercise the real bundled app, iframe renderer and existing API contracts, without a live hub.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');
const groups = Array.from({length: 8}, (_, i) => ({id: 'g' + i, name: i === 0 ? 'Design <studio>' : 'Department ' + i}));
const people = [{id: 'ana', name: 'Ana', team: 'g0'}, {id: 'hidden', name: 'Hidden human', hidden: true}];
const bots = Array.from({length: 8}, (_, i) => ({name: 'bot-' + i, display_name: i === 0 ? '<img src=x onerror=alert(1)>' : 'Teammate ' + i, team: 'g0', host: 'keeper', status: 'active', my_access: {see: true, read: true}, can_chat: true}));
bots.push({name: 'restricted', team: 'g1', my_access: {see: true, read: false}},
  {name: 'invisible', my_access: {see: false}}, {name: 'retired', status: 'retired'},
  {name: 'my-branch', is_branch: true, operator: 'ana', team: 'g1'},
  {name: 'other-branch', is_branch: true, operator: 'other', team: 'g1'});
(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true,
    args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader']});
  let offline = false, running = true, empty = false;
  const errors = [];
  const open = async (viewport, noWebGL = false) => {
    const page = await browser.newPage({viewport, serviceWorkers: 'block', reducedMotion: 'reduce'});
    page.on('pageerror', e => errors.push(e.message));
    if (noWebGL) await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type, ...args) { return String(type).startsWith('webgl') ? null : original.call(this, type, ...args); };
    });
    await page.route('**/*', async route => {
      const url = new URL(route.request().url()), p = url.pathname;
      if (url.origin !== 'http://tico-ui.test') return route.abort();
      const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
      if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
      if (p.startsWith('/tico/ui/')) {
        const name = p.slice('/tico/ui/'.length), file = uiFile(name);
        if (fs.existsSync(file)) return route.fulfill({contentType: name.endsWith('.html') ? 'text/html' : name.endsWith('.css') ? 'text/css' : name.endsWith('.js') ? 'application/javascript' : 'application/octet-stream', body: fs.readFileSync(file)});
      }
      if (p === '/api/employees') return json(empty ? [] : bots);
      if (p === '/api/humans') return json({people: empty ? [] : people, org_groups: empty ? [] : groups});
      if (p === '/api/me') return json({id: 'ana', name: 'Ana', role: 'owner', cloud: true});
      if (p === '/api/status') return json({active: [], employees: []});
      if (p === '/api/issues') return json([]);
      if (p === '/api/v2/status') return json({bots: bots.map(b => ({bot: b.name, state: running ? 'running' : 'waiting_human', focus: 'SECRET WORK CONTENT'}))}, offline ? 503 : 200);
      return json({});
    });
    await page.goto('http://tico-ui.test/');
    await page.waitForFunction(() => location.hash === '#/updates');
    return page;
  };
  try {
    const page = await open({width: 1440, height: 1000});
    assert.equal(await page.locator('#overview-frame').count(), 0, 'default Updates does not load Three.js');
    assert.equal(await page.locator('.side-scroll .nav-link:visible').first().getAttribute('data-nav'), 'overview');
    await page.locator('.side-scroll [data-nav=overview]').click();
    const frame = page.frameLocator('#overview-frame');
    await frame.locator('body[data-scene-ready]').waitFor();
    const model = await page.evaluate(() => overviewModel());
    const members = model.groups.flatMap(g => g.members);
    for (const id of ['human:hidden', 'bot:invisible', 'bot:retired', 'bot:other-branch']) assert(!members.some(m => m.id === id), id);
    assert(members.some(m => m.id === 'bot:my-branch'));
    assert.equal(members.find(m => m.id === 'bot:restricted').state, 'restricted');
    assert.equal(members.find(m => m.id === 'bot:restricted').href, '');
    assert(!JSON.stringify(model).includes('SECRET'), 'free-text work content never crosses the renderer boundary');
    assert.equal(await frame.locator('[data-floor]').count(), 8, 'all departments remain reachable without paging');
    assert.equal(await frame.locator('#light, #pause, #fullscreen, #department-picker, .camera-controls, #help, #building-pages, #occupant-pages').count(), 0);
    assert.match(await frame.locator('body').getAttribute('class'), /night/);
    await frame.locator('[data-floor="7"]').focus(); await page.keyboard.press('Enter');
    await frame.locator('#floor-title').filter({hasText: 'Department 7'}).waitFor();
    await page.keyboard.press('Escape');
    await frame.locator('[data-floor="0"]').focus(); await page.keyboard.press('Enter');
    await frame.locator('#floor-title').filter({hasText: 'Design <studio>'}).waitFor();
    assert.equal(await frame.locator('[data-person]').count(), 9, 'entering a department reveals every teammate');
    assert.equal(await frame.locator('[data-person="bot:bot-0"] img').count(), 0, 'names are text, never HTML');
    await frame.locator('[data-person="bot:bot-0"]').focus(); await page.keyboard.press('Enter');
    const child = page.frames().find(f => f.url().includes('/overview/index.html'));
    await child.evaluate(() => window.originalCanvas = document.querySelector('canvas'));
    running = false; await page.evaluate(() => refresh());
    await frame.locator('#speech-message').filter({hasText: 'Waiting on a human'}).waitFor();
    assert(await child.evaluate(() => window.originalCanvas === document.querySelector('canvas')), 'status refresh preserves camera and renderer');
    assert.equal(await frame.locator('#floor-title').innerText(), 'Design <studio>');
    offline = true; await page.evaluate(() => refresh());
    await frame.locator('#speech-message').filter({hasText: 'Status is unavailable'}).waitFor();
    assert.equal((await page.evaluate(() => overviewModel())).groups[0].members[1].state, 'unknown');
    offline = false; await page.evaluate(() => refresh());
    await frame.locator('#speech-message').filter({hasText: 'Waiting on a human'}).waitFor();
    await frame.locator('#speech-open').click();
    await page.waitForFunction(() => location.hash === '#/bot/bot-0');
    assert.equal(await page.locator('#overview-frame').count(), 0, 'leaving unmounts the scene');
    await page.evaluate(() => location.hash = '#/overview');
    await frame.locator('body[data-scene-ready]').waitFor();
    await frame.locator('canvas').click({position: {x: 10, y: 10}});
    assert.equal(await frame.locator('#floors').getAttribute('hidden'), null);
    await page.close();

    const mobile = await open({width: 390, height: 844});
    await mobile.locator('#mobile-more').click();
    await mobile.locator('.side-scroll [data-nav=overview]').click();
    const phoneFrame = mobile.frameLocator('#overview-frame');
    await phoneFrame.locator('body[data-scene-ready]').waitFor();
    assert.equal(await mobile.locator('#mobile-nav [data-nav=overview]').count(), 0);
    assert.equal(await mobile.locator('#mobile-nav .mobile-nav-item').first().getAttribute('data-nav'), 'org');
    const bounds = await mobile.locator('#overview-frame').boundingBox(), nav = await mobile.locator('#mobile-nav').boundingBox();
    assert(bounds.height > 400 && bounds.y + bounds.height <= nav.y + 1, 'scene fits above mobile navigation');
    await phoneFrame.locator('[data-floor="0"]').focus(); await mobile.keyboard.press('Enter');
    assert.equal(await phoneFrame.locator('[data-person]').count(), 9);
    await mobile.keyboard.press('Escape');
    await phoneFrame.locator('[data-floor="7"]').focus(); await mobile.keyboard.press('Enter');
    await phoneFrame.locator('#floor-title').filter({hasText: 'Department 7'}).waitFor();
    await mobile.setViewportSize({width: 360, height: 740});
    await phoneFrame.locator('canvas').click({position: {x: 10, y: 10}});
    assert.equal(await phoneFrame.locator('#floors').getAttribute('hidden'), null, 'tapping outside a room returns to the building');
    await mobile.close();

    const fallback = await open({width: 1280, height: 900}, true);
    await fallback.evaluate(() => location.hash = '#/overview');
    await fallback.frameLocator('#overview-frame').locator('#fallback-team button').first().waitFor();
    assert.equal(await fallback.frameLocator('#overview-frame').locator('#fallback-team button').count(), members.length);
    await fallback.close();
    empty = true;
    const noTeam = await open({width: 390, height: 844});
    await noTeam.evaluate(() => location.hash = '#/overview');
    await noTeam.frameLocator('#overview-frame').locator('#fallback p').filter({hasText: 'add groups and teammates'}).waitFor();
    assert.deepEqual(errors, []);
    await noTeam.close();
    console.log('Overview: permissions, live status, default route, scene navigation, phone fit, lifecycle, fallback and empty state passed');
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
