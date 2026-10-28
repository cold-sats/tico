// Strategy › Org (ui/app/redesign-org.js) against the fake hub in support/strategy-fake.cjs (the
// Acme example): the chart top down with the owner on top, groups as outlines that fold (and stay folded), helpers off
// it, pinch and the zoom buttons; a teammate's sheet with its group and Move to…; the owner, and a lead inside the
// groups it leads, move at once (PATCH /api/v2/groups), anyone else files an org approval; a proposal waiting on the
// owner is one row with Approve and Decline. A phone first, then a computer.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {openStrategy, PHONE, DESKTOP, sideways, shot} = require('./support/strategy-fake.cjs');

const card = ref => `.rdo-card[data-rdo-ref="${ref}"]`;
const inGroup = (page, ref, gid) => page.locator(`[data-rdo-group="${gid}"] ${card(ref)}`).count().then(n => n === 1);
const zoomOf = page => page.locator('#rdo-cv').evaluate(el => Number(el.style.zoom) || 1);

async function chart(page, tag) {
  await page.locator(card('bot:builder')).waitFor();
  assert.equal(await page.locator('.rdo-card.top').innerText().then(t => t.split('\n')[0]), 'Ana Silva', tag + ': the owner on top');
  for (const helper of ['bot:botops', 'bot:librarian', 'bot:coo', 'bot:mail-sorter'])
    assert.equal(await page.locator(card(helper)).count(), 0, `${tag}: ${helper} is off the chart`);
  assert.equal(await page.locator(card('bot:goal-manager')).count(), 1, tag + ': the Strategy Bot is on it');
  assert.ok(await inGroup(page, 'bot:builder', 'eng'), tag + ': Builder in Engineering');
  assert.equal(await page.locator('[data-rdo-group="eng"] [data-rdo-group="web"]').count(), 1, tag + ': Web nests in Engineering');
  assert.equal(await page.locator('[data-rdo-group="eng"] .rdo-card').first().getAttribute('data-rdo-ref'), 'bot:eng-lead', tag + ': the lead first');
  assert.equal(await sideways(page), false, tag + ': no sideways scroll');
}

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    // A phone, the owner: the chart, folding, pinch, a move, a proposal approved.
    {
      const tag = 'phone owner';
      const {page, errors, writes} = await openStrategy(browser);
      await chart(page, tag);
      // One row per move, whole on a phone: who and where to, with its own Approve and Decline.
      const prop = page.locator('.rdo-prop[data-rdo-prop="ap_org1"]');
      assert.match(await prop.innerText(), /Reviewer → Web/, tag + ': the proposal row');
      assert.equal(await prop.locator('.rdo-props-t').evaluate(el => el.scrollWidth <= el.clientWidth), true, tag + ': the row is not cut');
      assert.equal(await prop.getByRole('button', {name: 'Approve'}).isVisible(), true, tag + ': Approve');
      assert.equal(await prop.getByRole('button', {name: 'Decline'}).isVisible(), true, tag + ': Decline');
      assert.equal(await page.locator('.rdo-card.pv' + `[data-rdo-ref="bot:reviewer"]`).count(), 1, tag + ': the teammate it moves is marked');
      // Opens readable (names 12px or more), centred on the owner, the frame down to the tab bar, the page still.
      const look = await page.evaluate(() => {
        const pane = document.querySelector('#rdo-pane'), cv = document.querySelector('#rdo-cv');
        const name = parseFloat(getComputedStyle(cv.querySelector('.rdo-card b')).fontSize) * Number(cv.style.zoom);
        const top = document.querySelector('.rdo-card.top').getBoundingClientRect(), box = pane.getBoundingClientRect();
        const bar = document.querySelector('#mobile-nav').getBoundingClientRect().top;
        return {name, off: Math.abs(top.left + top.width / 2 - (box.left + box.width / 2)), gap: bar - box.bottom,
          wider: pane.scrollWidth > pane.clientWidth, still: document.querySelector('#main').scrollHeight <= document.querySelector('#main').clientHeight + 1};
      });
      assert.ok(look.name >= 12, `${tag}: names read at ${look.name}px`);
      assert.ok(look.off < 4, `${tag}: centred on the owner (${look.off}px off)`);
      assert.ok(look.gap >= 0 && look.gap <= 24, `${tag}: the frame runs to the tab bar (${look.gap}px short)`);
      assert.ok(look.wider, tag + ': the chart runs wider than the screen and pans');
      assert.ok(look.still, tag + ': the page itself does not scroll');
      await shot(page, 'phone-org');

      // Fold Engineering: its teammates leave, the tab counts them, and it stays folded on the next visit.
      await page.locator('[data-rdo-fold="eng"]').click();
      assert.equal(await page.locator(card('bot:builder')).isVisible(), false, tag + ': folded');
      assert.equal(await page.locator('[data-rdo-fold="eng"] .rdo-n').innerText(), '5', tag + ': the tab counts who is inside');
      assert.equal(await page.locator('[data-rdo-fold="eng"]').getAttribute('aria-expanded'), 'false');
      await shot(page, 'phone-org-folded');
      await page.reload();
      await page.locator('[data-rdo-fold="eng"]').waitFor();
      assert.equal(await page.locator(card('bot:builder')).isVisible(), false, tag + ': still folded after a reload');
      await page.locator('[data-rdo-fold="eng"]').click();
      await page.locator(card('bot:builder')).waitFor();

      // Pinch out with two fingers, then the buttons.
      const before = await zoomOf(page), box = await page.locator('#rdo-pane').boundingBox();
      const cdp = await page.context().newCDPSession(page);
      const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
      const touch = d => [{x: cx - d, y: cy, id: 1}, {x: cx + d, y: cy, id: 2}];
      await cdp.send('Input.dispatchTouchEvent', {type: 'touchStart', touchPoints: touch(40)});
      for (const d of [60, 80, 100]) await cdp.send('Input.dispatchTouchEvent', {type: 'touchMove', touchPoints: touch(d)});
      await cdp.send('Input.dispatchTouchEvent', {type: 'touchEnd', touchPoints: []});
      const pinched = await zoomOf(page);
      assert.ok(pinched > before * 1.5, `${tag}: a pinch zooms in (${before} → ${pinched})`);
      await page.locator('[data-rdo-zoom="out"]').click();
      assert.ok(await zoomOf(page) < pinched, tag + ': − zooms out');
      assert.equal(await sideways(page), false, tag + ': zoomed, the chart pans inside its pane');

      // The owner moves Builder into Web at once.
      await page.locator(card('bot:builder')).click();
      const sheet = page.locator('dialog.rd-sheet[open]');
      await sheet.waitFor();
      assert.equal(await sheet.locator('[data-rdo-home]').innerText(), 'Engineering', tag + ': the sheet names its group');
      await sheet.locator('select[name="to"]').selectOption('web');
      assert.equal(await sheet.locator('[type=submit]').innerText(), 'Move', tag + ': the owner moves');
      await shot(page, 'phone-org-sheet');
      await sheet.locator('[type=submit]').click();
      await sheet.waitFor({state: 'detached'});
      await page.waitForFunction(() => document.querySelector('[data-rdo-group="web"] [data-rdo-ref="bot:builder"]'));

      // Approve the proposal: one decision per proposal, the row leaves and Reviewer is in Web.
      await page.locator('[data-rdo-decide="approved"]').click();
      await page.locator('.rdo-props').waitFor({state: 'detached'});
      await page.waitForFunction(() => document.querySelector('[data-rdo-group="web"] [data-rdo-ref="bot:reviewer"]'));
      assert.deepEqual(writes.filter(w => w.path.startsWith('/api/v2/groups') || w.path.startsWith('/api/v2/approvals')), [
        {method: 'PATCH', path: '/api/v2/groups/web', body: {add: {bots: ['builder']}}},
        {method: 'POST', path: '/api/v2/approvals/ap_org1', body: {decision: 'approved'}},
      ], tag + ': the requests');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // A phone, a teammate who leads nothing: the same chart, no proposal row, and a move is a proposal.
    {
      const tag = 'phone member';
      const {page, errors, writes} = await openStrategy(browser, {viewer: 'cara'});
      await chart(page, tag);
      assert.equal(await page.locator('.rdo-props').count(), 0, tag + ': nothing waits on her');
      await page.locator(card('bot:sdr')).click();
      const sheet = page.locator('dialog.rd-sheet[open]');
      await sheet.locator('select[name="to"]').selectOption('eng');
      assert.equal(await sheet.locator('[type=submit]').innerText(), 'Ask to move', tag + ': she asks');
      await sheet.locator('[type=submit]').click();
      await sheet.waitFor({state: 'detached'});
      assert.deepEqual(writes.filter(w => w.path.startsWith('/api/v2/groups') || w.path.startsWith('/api/v2/approvals')), [
        {method: 'POST', path: '/api/v2/approvals', body: {kind: 'org', payload: {bot: 'bot:sdr', from: 'sales', to: 'eng'}}},
      ], tag + ': an org approval, no group change');
      assert.ok(await inGroup(page, 'bot:sdr', 'sales'), tag + ': SDR stays in Sales until approved');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // A phone, a lead who is not an admin: inside the groups he leads a move happens at once (PATCH, audited by the
    // hub); out of them it is an org approval.
    {
      const tag = 'phone lead';
      const {page, errors, writes} = await openStrategy(browser, {viewer: 'ben'});
      await chart(page, tag);
      const ask = async (ref, to, label) => {
        await page.locator(card(ref)).click();
        const sheet = page.locator('dialog.rd-sheet[open]');
        await sheet.locator('select[name="to"]').selectOption(to);
        assert.equal(await sheet.locator('[type=submit]').innerText(), label, `${tag}: ${ref} to ${to} is ${label}`);
        await sheet.locator('[type=submit]').click();
        await sheet.waitFor({state: 'detached'});
      };
      await ask('bot:sdr', 'outbound', 'Move');
      await page.waitForFunction(() => document.querySelector('[data-rdo-group="outbound"] [data-rdo-ref="bot:sdr"]'));
      await ask('bot:sales-lead', 'eng', 'Ask to move');
      assert.deepEqual(writes.filter(w => w.path.startsWith('/api/v2/groups') || w.path.startsWith('/api/v2/approvals')), [
        {method: 'PATCH', path: '/api/v2/groups/outbound', body: {add: {bots: ['sdr']}}},
        {method: 'POST', path: '/api/v2/approvals', body: {kind: 'org', payload: {bot: 'bot:sales-lead', from: 'sales', to: 'eng'}}},
      ], tag + ': a direct move inside Sales, an org approval out of it');
      assert.ok(await inGroup(page, 'bot:sales-lead', 'sales'), tag + ': Sales Lead stays in Sales until approved');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    // A computer, the owner: the same chart, wider; the proposal row on top.
    {
      const tag = 'desktop owner';
      const {page, errors} = await openStrategy(browser, {viewport: DESKTOP});
      await chart(page, tag);
      assert.equal(await page.locator('.rdo-props').count(), 1, tag + ': the proposal row');
      const pane = await page.locator('#rdo-pane').boundingBox(), cv = await page.locator('#rdo-cv').boundingBox();
      assert.ok(cv.width <= pane.width + 1, tag + ': the whole chart fits the pane');
      await page.locator(card('person:cara')).click();
      await page.locator('dialog[open] [data-rdo-home]').waitFor();
      assert.equal(await page.locator('dialog[open] [data-rdo-home]').innerText(), 'Engineering', tag + ': a person has a home group too');
      await page.locator('dialog[open] [data-close]').first().click();
      await shot(page, 'desktop-org');
      assert.deepEqual(errors, [], tag + ': no page errors');
      await page.close();
    }

    console.log('strategy org ok');
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exit(1); });
