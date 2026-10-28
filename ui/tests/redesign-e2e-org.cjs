// Journey 7 on a real hub (redesign TESTING.md §L3): Strategy › Org on a phone (then a desktop). Dana, the top of the
// org, taps Builder (Claude) and moves it from Engineering to Release: the hub's groups have it there at once. Omar
// leads Engineering only, so moving Builder (OpenAI) to Release is "Ask to move": an `org` approval (CONTRACT §5) and
// nothing moves. Dana sees it in Needs you and as one row on Org; Approve moves it.
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

  // Omar (lead of Engineering, not Release) asks to move Builder (OpenAI).
  const omar = await open(browser, hub, 'omar', {phone, hash: '#/strategy/org'});
  await omar.locator(card('bot:builder-openai')).click();
  const ask = omar.locator('dialog.rd-sheet[open]');
  await ask.waitFor();
  await ask.locator('select[name="to"]').selectOption({label: 'Release'});
  assert.equal(await ask.locator('[type=submit]').innerText(), 'Ask to move', `${tag}: a lead outside its groups asks`);
  await shot(omar, `${tag}-04-ask-sheet`);
  await ask.locator('[type=submit]').click();
  await ask.waitFor({state: 'detached'});
  await omar.locator('.toast:has-text("Sent for approval")').waitFor();
  assert.equal(await omar.locator('.rdo-props').count(), 0, `${tag}: Omar does not decide`);
  groups = await groupsOf(omar);
  assert.ok(holds(groupNamed(groups, 'Engineering'), 'builder-openai'), `${tag}: nothing moves before Dana approves`);
  assert.deepEqual(omar.errors, [], `${tag}: no page errors for Omar`);
  await omar.context().close();

  // Dana: in Needs you, and one row on Org.
  const needs = await ok(page, 'GET', 'needs-you');
  const asked = (needs.items || needs.needs || needs).filter(it => it.kind === 'approval' && it.what === 'org');
  assert.equal(asked.length, 1, `${tag}: one org approval for Dana: ${JSON.stringify(needs).slice(0, 300)}`);
  assert.deepEqual(asked[0].payload, {bot: 'bot:builder-openai', from: eng.id, to: release.id});
  assert.equal(asked[0].requested_by, 'human:omar');
  await go(page, '#/strategy');
  await go(page, '#/strategy/org');
  const row = page.locator('.rdo-props');
  await row.waitFor({timeout: t(10000)});
  assert.match(await row.innerText(), /Builder \(OpenAI\)|builder-openai/);
  assert.equal(await page.locator(`.rdo-card.pv[data-rdo-ref="bot:builder-openai"]`).count(), 1);
  assert.equal(await sideways(page), false);
  await shot(page, `${tag}-05-proposal`);
  await page.locator('[data-rdo-decide="approved"]').click();
  await row.waitFor({state: 'detached'});
  await page.locator(`[data-rdo-group="${release.id}"] ${card('bot:builder-openai')}`).waitFor({timeout: t(10000)});
  groups = await groupsOf(page);
  assert.ok(holds(groupNamed(groups, 'Release'), 'builder-openai'), `${tag}: approved, the hub moved it`);
  assert.ok(!holds(groupNamed(groups, 'Engineering'), 'builder-openai'), `${tag}: and out of Engineering`);
  await shot(page, `${tag}-06-approved`);
  assert.deepEqual(page.errors, [], `${tag}: no page errors`);
  await page.context().close();
});
