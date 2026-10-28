// Journey 7 on a real hub (redesign TESTING.md §L3): Strategy › Org on a phone (then a desktop). Dana, the top of the
// org, taps Builder (Claude) and moves it from Engineering to Release: the hub's groups have it there at once. Then a
// bot's proposal to move Builder (OpenAI) should show Dana one row with Approve. Filing an org approval needs wave 2
// (budgets: approval kind `org`); until that lands the hub refuses it (422) and that step prints SKIPPED, never a
// silent pass.
const assert = require('node:assert/strict');
const {run, open, go, ok, sideways, shot, t} = require('./support/redesign-e2e.cjs');

const card = ref => `.rdo-card[data-rdo-ref="${ref}"]`;
const groupsOf = async page => { const g = await ok(page, 'GET', 'groups'); return g.groups || g; };
const groupNamed = (groups, name) => groups.find(g => g.name === name);
const holds = (group, slug) => JSON.stringify(group).includes(`"${slug}"`) || JSON.stringify(group).includes(`bot:${slug}"`);

run('redesign-e2e-org', ['org', 'toured', 'redesign_on', 'groups'], async ({hub, browser, phone, tag}) => {
  const page = await open(browser, hub, 'dana', {phone, hash: '#/strategy/org'});
  await page.locator(card('bot:builder-claude')).waitFor({timeout: t(15000)});
  let groups = await groupsOf(page);
  const eng = groupNamed(groups, 'Engineering'), release = groupNamed(groups, 'Release');
  assert.ok(eng && release, `${tag}: both groups: ${JSON.stringify(groups).slice(0, 300)}`);
  assert.ok(holds(eng, 'builder-claude'));
  assert.equal(await page.locator(`[data-rdo-group="${eng.id}"] ${card('bot:builder-claude')}`).count(), 1);
  assert.equal(await sideways(page), false, `${tag}: the chart pans inside its pane`);
  await shot(page, `${tag}-01-chart`);

  // Dana moves Builder (Claude) at once.
  await page.locator(card('bot:builder-claude')).click();
  const sheet = page.locator('dialog.rd-sheet[open]');
  await sheet.waitFor();
  assert.equal(await sheet.locator('[data-rdo-home]').innerText(), 'Engineering');
  await sheet.locator('select[name="to"]').selectOption({label: 'Release'});
  assert.equal(await sheet.locator('[type=submit]').innerText(), 'Move', `${tag}: the top of the org moves`);
  await shot(page, `${tag}-02-move-sheet`);
  await sheet.locator('[type=submit]').click();
  await sheet.waitFor({state: 'detached'});
  await page.locator(`[data-rdo-group="${release.id}"] ${card('bot:builder-claude')}`).waitFor({timeout: t(10000)});
  groups = await groupsOf(page);
  assert.ok(holds(groupNamed(groups, 'Release'), 'builder-claude'), `${tag}: the hub has it in Release`);
  assert.ok(!holds(groupNamed(groups, 'Engineering'), 'builder-claude'), `${tag}: and out of Engineering`);
  await shot(page, `${tag}-03-moved`);

  // A bot proposes a move; Dana should see one row with Approve.
  const filed = await fetch(hub.url + '/api/v2/approvals', {method: 'POST', headers: {'Content-Type': 'application/json',
    Authorization: 'Bearer ' + hub.tokens['engineering-lead'], 'Idempotency-Key': `org-${tag}-${Date.now()}`},
    body: JSON.stringify({kind: 'org', payload: {bot: 'bot:builder-openai', from: eng.id, to: release.id}})});
  if (filed.status === 422) {
    // TODO(wave 2 · budgets): approval kind `org` is not in ApprovalCreate yet. Once it is, this branch stops running
    // and the Approve row below is checked.
    console.log(`${tag}: SKIPPED the Approve row: the hub refuses an org approval (422) until wave 2 (budgets) lands`);
  } else {
    assert.ok(filed.status < 300, `${tag}: the proposal is filed: ${filed.status} ${await filed.text()}`);
    await go(page, '#/strategy');
    await go(page, '#/strategy/org');
    const row = page.locator('.rdo-props');
    await row.waitFor({timeout: t(10000)});
    assert.match(await row.innerText(), /Builder \(OpenAI\)|builder-openai/);
    assert.equal(await page.locator(`.rdo-card.pv${card('bot:builder-openai').slice('.rdo-card'.length)}`).count(), 1);
    await shot(page, `${tag}-04-proposal`);
    await page.locator('[data-rdo-decide="approved"]').click();
    await row.waitFor({state: 'detached'});
    await page.locator(`[data-rdo-group="${release.id}"] ${card('bot:builder-openai')}`).waitFor();
    assert.ok(holds(groupNamed(await groupsOf(page), 'Release'), 'builder-openai'), `${tag}: approved, the hub moved it`);
  }
  assert.deepEqual(page.errors, [], `${tag}: no page errors`);
  await page.context().close();
});
