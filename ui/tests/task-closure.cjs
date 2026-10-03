// Explicit acceptance works from Done without reopening or waking the task.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {open} = require('./tasks-page.cjs');
(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    const {page, errors, posts, tasks} = await open(browser, {hash: '#/tasks?view=done'});
    await page.locator('#task-view [data-view="done"]').click();
    await page.locator('[data-task-key="tt-receipt"] .tl-title').click();
    const peek = page.locator('#task-peek');
    await peek.locator('[data-task-more]').click();
    assert.equal(await peek.getByRole('menuitem', {name: 'Close task', exact: true}).count(), 1);
    await peek.getByRole('menuitem', {name: 'Open full', exact: true}).click();
    const modal = page.locator('#task-modal');
    await modal.locator('[data-task-more]').click();
    await modal.getByRole('menuitem', {name: 'Close task', exact: true}).click();
    await page.waitForFunction(() => document.querySelector('#task-modal [data-prop="status"]')?.textContent.includes('Closed'));
    assert.equal(tasks.find(t => t.id === 't-receipt').status, 'closed');
    assert.deepEqual(posts.filter(p => p.p === '/api/v2/tasks/t-receipt').map(p => p.body), [{version: 3, close: true}]);
    await modal.locator('[data-task-more]').click();
    assert.equal(await modal.getByRole('menuitem', {name: 'Close task', exact: true}).count(), 0);
    await page.keyboard.press('Escape');
    await page.keyboard.press('Escape');
    // Bulk accepts Done and skips already Closed work.
    await page.locator('[data-task-key="tt-sso"] .tl-check').click();
    await page.locator('[data-task-key="tt-faq"] .tl-check').click();
    await page.locator('#task-bulk [data-bulk="close"]').click();
    await page.waitForFunction(() => /closed/.test(document.querySelector('.tl-bulk-msg')?.textContent || ''));
    assert.deepEqual(posts.filter(p => /^\/api\/v2\/tasks\/t-(sso|faq)$/.test(p.p)), [{p: '/api/v2/tasks/t-sso', body: {version: 3, close: true}}]);
    assert.deepEqual(errors, []);
    await page.close();
    const viewer = await open(browser, {hash: '#/tasks?view=done', mover: false});
    await viewer.page.locator('#task-view [data-view="done"]').click();
    await viewer.page.locator('[data-task-key="tt-receipt"] .tl-title').click();
    await viewer.page.locator('#task-peek [data-task-more]').click();
    assert.equal(await viewer.page.getByRole('menuitem', {name: 'Close task', exact: true}).count(), 1, 'a requester can accept without mover rights');
    await viewer.page.close();
    console.log('Done explicit closure: detail, peek, bulk and requester rights passed');
  } finally { await browser.close(); }
})().catch(e => {console.error(e); process.exit(1);});
