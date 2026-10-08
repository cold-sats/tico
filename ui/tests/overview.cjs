// Desktop campus layout, privacy, scene clock, keyboard navigation and status refresh.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {createOverviewFixture} = require('./support/overview-fixture.cjs');

(async () => {
  const browser = await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless:true,
    args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const {bots, errors, requests, state, open, modelOf, enter, shot, waitForCondition} = createOverviewFixture(browser);
  try {
    const page = await open({width:1440,height:1000});
    assert.equal(await page.locator('#overview-frame').count(), 0);
    assert(!requests.includes('/api/v2/computers'), 'computer inventory stays lazy');
    assert(!requests.some(p => p.includes('/vendor/three/')), 'Three.js stays lazy');
    await page.locator('.side-scroll [data-nav=overview]').click();
    const frame = page.frameLocator('#overview-frame'); await frame.locator('body[data-scene-ready]').waitFor();
    await frame.locator('[data-computer="computer:empty"]').waitFor({state:'attached'});
    const model = await modelOf(page), members = model.groups.flatMap(g => g.members);
    assert.deepEqual(model.groups.filter(g => g.kind === 'computer').map(g => g.id), ['computer:alpha','computer:beta','computer:empty']);
    for (const id of ['human:hidden','bot:invisible','bot:retired','bot:other-branch']) assert(!members.some(m => m.id === id), id);
    assert(members.some(m => m.id === 'bot:my-branch'));
    assert(!JSON.stringify(model).includes('SECRET'), 'machine and free-text work content stay private');
    const inBuilding = (key, id) => model.groups.find(g => g.id === key).members.some(m => m.id === id);
    assert.equal(members.find(m => m.id === 'bot:bot-0').href, '#/bot/bot-0');
    assert(inBuilding('computer:alpha','human:ana') && inBuilding('computer:beta','human:ana'), 'person with bots on two machines appears in both');
    assert(inBuilding('computer:alpha','human:jo') && !inBuilding('computer:beta','human:jo'), 'person with bots on one machine appears once');
    assert(inBuilding('computer:beta','human:pat') && !inBuilding('computer:alpha','human:pat'), 'visible reporting chains place the human manager');
    assert(!inBuilding('@commons','human:ana') && inBuilding('@commons','human:eli'), 'only unplaced people use the pavilion');
    assert(inBuilding('@commons','bot:restricted') && inBuilding('@commons','bot:unassigned') && inBuilding('@commons','bot:external'));
    assert.equal(members.find(m => m.id === 'bot:restricted').href, '');
    assert.equal(model.groups.find(g => g.id === 'computer:empty').members.length, 0);
    await frame.locator('#loading').waitFor({state:'hidden'}); await shot(page, 'campus-desktop');

    // Wait on the renderer's real simulation state, not an arbitrary screenshot delay.
    const sceneFrame = page.frames().find(f => f.url().includes('/overview/index.html'));
    const motionState = () => sceneFrame.evaluate(() => ({frame:window.__TICO_OVERVIEW_TEST_PROBE__.frame,
      time:window.__TICO_OVERVIEW_TEST_PROBE__.time}));
    const beforeMotion = await motionState();
    await page.emulateMedia({reducedMotion:'no-preference'});
    await waitForCondition(sceneFrame, () => !matchMedia('(prefers-reduced-motion: reduce)').matches);
    await waitForCondition(sceneFrame, ({frame,time}) => window.__TICO_OVERVIEW_TEST_PROBE__.frame > frame
      && window.__TICO_OVERVIEW_TEST_PROBE__.time > time, beforeMotion);
    const beforePause = await motionState();
    await page.emulateMedia({reducedMotion:'reduce'});
    await waitForCondition(sceneFrame, ({frame}) => matchMedia('(prefers-reduced-motion: reduce)').matches
      && window.__TICO_OVERVIEW_TEST_PROBE__.frame >= frame + 2, beforePause);
    const paused = await motionState();
    assert.equal(paused.time, beforePause.time, 'reduced motion freezes the scene clock across rendered frames');

    await enter(page, 'computer:alpha');
    assert.equal(await frame.locator('[data-person]').count(), 6, 'all occupants have an accessible character');
    assert.equal(await frame.locator('[data-person="bot:bot-0"] img').count(), 0);
    await shot(page, 'computer-desktop');
    await frame.locator('[data-person="bot:bot-0"]').focus(); await page.keyboard.press('Enter');
    const child = page.frames().find(f => f.url().includes('/overview/index.html'));
    await child.evaluate(() => window.originalCanvas = document.querySelector('canvas'));
    state.running = false; await page.evaluate(() => refresh());
    await frame.locator('#speech-message').filter({hasText:'Waiting on a human'}).waitFor();
    assert(await child.evaluate(() => window.originalCanvas === document.querySelector('canvas')), 'status refresh preserves renderer and selection');
    state.offline = true; await page.evaluate(() => refresh());
    await frame.locator('#speech-message').filter({hasText:'Status is unavailable'}).waitFor();
    assert.equal((await modelOf(page)).groups[0].members.find(m => m.type === 'bot').state, 'unknown');
    state.offline = false; await page.evaluate(() => refresh());
    await frame.locator('#speech-message').filter({hasText:'Waiting on a human'}).waitFor();
    // The speech bubble follows the camera; visibility is asserted and the button is activated directly.
    assert(await frame.locator('#speech-open').isVisible());
    await Promise.all([page.waitForURL(url => url.hash === '#/bot/bot-0'), frame.locator('#speech-open').evaluate(button => button.click())]);
    assert.equal(await page.locator('#overview-frame').count(), 0);
    await page.evaluate(() => location.hash = '#/overview'); await frame.locator('body[data-scene-ready]').waitFor();
    await enter(page, 'computer:beta'); await frame.locator('[data-person="human:ana"]').focus(); await page.keyboard.press('Enter');
    assert.match(await frame.locator('#speech-message').innerText(), /Presence is not tracked/);
    assert(await frame.locator('#speech-open').isVisible());
    await Promise.all([page.waitForURL(url => url.hash === '#/person/ana'), frame.locator('#speech-open').evaluate(button => button.click())]);
    await page.evaluate(() => location.hash = '#/overview'); await frame.locator('body[data-scene-ready]').waitFor();
    await enter(page, 'computer:alpha');
    bots[0].machine = {runner_id:'beta',label:'Solar Linux'}; await page.evaluate(() => refresh());
    const reassigned = await modelOf(page);
    assert(reassigned.groups.find(g => g.id === 'computer:beta').members.some(m => m.id === 'bot:bot-0'), 'refresh publishes the updated assignment');
    assert(!reassigned.groups.find(g => g.id === 'computer:alpha').members.some(m => m.id === 'bot:bot-0'), 'reassignment moves a bot between buildings');
    await frame.locator('[data-person="bot:bot-0"]').waitFor({state:'detached'});
    await frame.locator('body[data-scene-ready]').waitFor();
    assert.equal(await frame.locator('#floor-title').innerText(), 'Garden Mac', 'topology rebuild remembers building');
    bots[0].machine = {runner_id:'alpha',label:'Garden Mac'};
    await page.close();

    // Fallback render keeps every visible collaborator and does not expose inaccessible work.
    const fallback = await open({width:1280,height:900}, true); await fallback.evaluate(() => location.hash = '#/overview');
    const fallbackFrame = fallback.frameLocator('#overview-frame');
    await fallbackFrame.locator('#fallback-team button').first().waitFor();
    assert.equal(await fallbackFrame.locator('#fallback-team section').count(), 4);
    assert.equal(await fallbackFrame.locator('#fallback-team button').count(), members.length);
    await fallback.close();
    assert.deepEqual(errors, []);
    console.log('Overview desktop: privacy, lazy load, placement, reduced motion, keyboard status, reassignment and fallback passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
