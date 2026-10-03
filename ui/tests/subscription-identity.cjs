// Real subscription component with isolated fixture data: rename never changes routing keys.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless: true,
    channel: process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    const errors = []; page.on('pageerror', e => errors.push(e.message));
    await page.setContent('<section id="settings-subs"><div id="set-subs"></div></section><div id="rows"><div data-bot-sub-line></div><div data-bot-sub-row><select></select></div></div>');
    await page.evaluate(() => {
      window.$ = s => document.querySelector(s);
      window.esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
      window.formBusy = el => [...el.querySelectorAll('input')].some(f => f === document.activeElement || f.value !== f.defaultValue); window.toast = () => {};
      window.settingsIsAdmin = () => true;
      window.S = {me: {id: 'ana', cloud: true}, orgGroups: [], emps: [{name: 'builder', machine: {runner_id: 'r1', operator: 'ana'}}]};
      window.SETTINGS_DATA = {machines: [{id: 'r1', label: 'North', operator: 'ana'}, {id: 'r2', label: 'South', operator: 'ana'}]};
      window.fixture = {profiles_by_computer: ['r1','r2'].map((runner_id, i) => ({runner_id, label: ['North', 'South'][i], profiles: [
        {name: 'engineering', id: 'subscription:' + JSON.stringify([runner_id, 'engineering']), display_name: 'Engineering', runtimes: {codex: {signed_in: true}}}]})),
        assignments: [{scope: 'bot', target: 'builder', profile: 'engineering'}]};
      window.writes = [];
      window.get = async () => structuredClone(fixture);
      window.put = async (url, body) => {
        writes.push({url, body});
        if (url === '/v2/subscriptions/name') {
          const p = fixture.profiles_by_computer.find(c => c.runner_id === body.runner_id).profiles.find(p => p.name === body.profile);
          p.display_name = body.display_name.trim(); return {id:p.id, display_name:p.display_name};
        }
      };
    });
    await page.addScriptTag({content: fs.readFileSync(path.join(__dirname, '../app/subscriptions.js'), 'utf8')});
    await page.evaluate(() => renderSettingsSubs(true));
    const north = page.locator('.subs-pc').first();
    await north.locator('summary').filter({hasText: /^Rename$/}).click();
    await page.evaluate(() => renderSettingsSubs());
    assert.equal(await north.locator('details').first().getAttribute('open'), '', 'polling preserves open rename');
    await north.locator('[name=display_name]').fill('Research <img src=x onerror=alert(1)>');
    await page.evaluate(() => renderSettingsSubs());
    assert.equal(await north.locator('[name=display_name]').inputValue(), 'Research <img src=x onerror=alert(1)>', 'polling preserves typing');
    await north.locator('button').filter({hasText: /^Save name$/}).click();
    await page.waitForFunction(() => document.querySelector('.subs-name')?.textContent.startsWith('Research <img'));
    assert.equal(await north.locator('.subs-name').textContent(), 'Research <img src=x onerror=alert(1)>');
    assert.equal(await page.locator('#set-subs img').count(), 0, 'display names are escaped');
    const [write] = await page.evaluate(() => writes);
    assert.deepEqual(write, {url:'/v2/subscriptions/name', body:{runner_id:'r1', profile:'engineering', display_name:'Research <img src=x onerror=alert(1)>'}});
    assert.equal(await page.locator('.subs-pc').nth(1).locator('.subs-name').textContent(), 'Engineering', 'another computer keeps its own label');
    await page.evaluate(() => subsBotPaint(document.querySelector('#rows'), 'builder'));
    assert.equal(await page.locator('#rows select').inputValue(), 'engineering', 'routing uses immutable key');
    assert.equal(await page.locator('#rows option:checked').textContent(), 'Research <img src=x onerror=alert(1)>');
    await page.evaluate(() => { settingsIsAdmin = () => false; S.me.id = 'viewer'; return renderSettingsSubs(true); });
    assert.equal(await page.locator('[data-subs-rename]').count(), 0, 'nonoperators cannot rename');
    assert.deepEqual(errors, []);
    console.log('subscription identity and rename: ok');
    await page.close();
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
