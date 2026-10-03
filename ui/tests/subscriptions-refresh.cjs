// The real weekly component and its refresh handler, using a fixture API at phone width.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 390, height: 844}});
    await page.setContent('<main style="padding:16px"><div id="weekly"></div></main>');
    for (const name of ['tokens', 'base', 'components', 'settings']) {
      await page.addStyleTag({content: fs.readFileSync(path.join(__dirname, `../styles/${name}.css`), 'utf8')});
    }
    await page.evaluate(() => {
      window.esc = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
      window.settingsIsAdmin = () => true;
      window.SETTINGS_DATA = {};
      window.calls = [];
      window.post = async (url, body) => { window.calls.push({url, body}); };
      window.toast = () => {};
    });
    await page.addScriptTag({content: fs.readFileSync(path.join(__dirname, '../app/subscriptions.js'), 'utf8')});
    await page.evaluate(() => {
      renderSettingsSubs = async () => { window.refreshed = true; };
      document.querySelector('#weekly').innerHTML = subsWeeklyHTML({runner_id: 'computer'}, {name: 'sample', runtimes: {
        codex: {signed_in: true, weekly: {used_percent: 72, reported_at: new Date().toISOString(),
          resets_at: new Date(Date.now() + 86400000).toISOString(), source: 'provider'}},
        claude: {signed_in: false}}});
      document.querySelector('[data-subs-refresh]').onclick = event => subsRefreshWeekly(event.currentTarget);
    });
    await page.getByRole('button', {name: 'Refresh weekly usage'}).focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => window.refreshed);
    assert.deepEqual(await page.evaluate(() => window.calls), [{url: '/v2/subscriptions/refresh', body: {
      runner_id: 'computer', profile: 'sample', runtime: 'codex'}}]);
    assert.match(await page.locator('#weekly').innerText(), /72% used/);
    assert.match(await page.locator('#weekly').innerText(), /Sign-in needed/);
    assert.match(await page.locator('#weekly').innerText(), /no background model turn/);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    console.log('Weekly refresh component: keyboard activation and 390px rendering passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
