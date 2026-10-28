// Journey 8 on a real hub (redesign TESTING.md §L3): Library › Connections lists the tool a computer reported (the
// Engineering Lead's Acme Billing, read and refund, from the runner's heartbeat) under In use, and its row opens the
// tool's own page, read only. Phone, then desktop.
const assert = require('node:assert/strict');
const {run, open, ok, sideways, shot, t} = require('./support/redesign-e2e.cjs');

run('redesign-e2e-connections', ['org', 'toured', 'redesign_on', 'connection'], async ({hub, browser, phone, tag}) => {
  const page = await open(browser, hub, 'dana', {phone, hash: '#/library/connections'});
  const tools = await ok(page, 'GET', 'tools');
  assert.ok(JSON.stringify(tools).includes('acme-billing'), `${tag}: the hub lists it`);
  const row = page.locator('.lc-row[data-service="acme-billing"]');
  await row.waitFor({timeout: t(15000)});
  assert.match(await row.innerText(), /acme|billing/i);
  assert.match((await page.locator('.lc-gh').allInnerTexts())[0], /IN USE/);
  assert.equal(await page.locator('#side a[data-nav="connections"].cur').count(), 1, `${tag}: Connections is current`);
  const h = await row.evaluate(el => el.getBoundingClientRect().height);
  assert.ok(h < 64, `${tag}: one dense row (${h}px)`);
  assert.equal(await sideways(page), false);
  await shot(page, `${tag}-01-list`);

  await row.click();
  await page.waitForFunction(() => location.hash === '#/library/connections/acme-billing', null, {timeout: t(5000)});
  await page.locator('#int-detail h1').waitFor();
  assert.equal(await page.locator('#int-detail .int-key, #int-learn-text, #int-learn-add, [data-delete-learning]').count(), 0,
    `${tag}: read only`);
  assert.equal(await sideways(page), false);
  await shot(page, `${tag}-02-tool`);
  assert.deepEqual(page.errors, [], `${tag}: no page errors`);
  await page.context().close();
});
