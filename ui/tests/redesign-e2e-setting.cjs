// Journey 1 on a real hub (redesign TESTING.md §L3): the owner turns the redesign on in Settings > General and the new
// nav appears (Automations, Library, Strategy opening on Market); turned off, today's nav is back. Phone, then desktop.
const assert = require('node:assert/strict');
const {run, open, go, ok, sideways, shot, t} = require('./support/redesign-e2e.cjs');

const navShown = page => page.$$eval('#side .side-scroll a.nav-link', els => els.filter(el => el.checkVisibility())
  .map(el => el.dataset.nav).filter(Boolean));

async function flip(page, on) {
  await go(page, '#/settings');
  const box = page.locator('#redesign-switch');
  await box.waitFor({timeout: t(15000)});
  assert.equal(await box.isChecked(), !on, 'the switch reads the other way first');
  await Promise.all([page.waitForEvent('load'), on ? box.check() : box.uncheck()]);
  await page.locator('#account .account-email').waitFor();
  await page.waitForFunction(on => document.documentElement.classList.contains('redesign') === on, on, {timeout: t(15000)});
}
async function openRail(page, phone) {
  if (!phone) return;
  await page.locator('#mobile-more').click();
  await page.locator('#side a.nav-link[data-nav="tasks"]').waitFor({state: 'visible'});
}

run('redesign-e2e-setting', ['org', 'toured'], async ({hub, browser, phone, tag}) => {
  const page = await open(browser, hub, 'dana', {phone});
  assert.deepEqual(await ok(page, 'GET', 'settings/redesign'), {enabled: false});
  await openRail(page, phone);
  const before = await navShown(page);
  assert.ok(!before.includes('automations') && before.includes('goals'), `${tag}: today's nav first: ${before}`);
  if (phone) await page.keyboard.press('Escape');

  await flip(page, true);
  assert.deepEqual(await ok(page, 'GET', 'settings/redesign'), {enabled: true}, `${tag}: the hub has it on`);
  await page.locator('#settings-redesign').scrollIntoViewIfNeeded();
  await shot(page, `${tag}-01-settings-on`);
  await openRail(page, phone);
  const on = await navShown(page);
  for (const key of ['automations', 'library', 'tools', 'strategy'])
    assert.ok(on.includes(key), `${tag}: ${key} in the new nav: ${on}`);
  assert.equal(await page.getAttribute('a[data-nav="strategy"]', 'href'), '#/strategy/market');
  await shot(page, `${tag}-02-nav-on`);
  await page.locator('#side a.nav-link[data-nav="automations"]').click();
  await page.locator('#au-root').waitFor();
  await page.locator('.au-row').first().waitFor();
  assert.ok((await page.locator('.au-row').allInnerTexts()).some(x => x.includes('What wakes bots')), `${tag}: the built-in is there`);
  assert.equal(await sideways(page), false, `${tag}: no sideways scroll`);

  await flip(page, false);
  assert.deepEqual(await ok(page, 'GET', 'settings/redesign'), {enabled: false});
  await openRail(page, phone);
  assert.deepEqual(await navShown(page), before, `${tag}: today's nav is back`);
  await shot(page, `${tag}-03-nav-off`);
  assert.deepEqual(page.errors, [], `${tag}: no page errors`);
  await page.context().close();
});
