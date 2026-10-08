// Overview remains useful when inventory is unavailable, on large teams and for an empty team.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {createOverviewFixture} = require('./support/overview-fixture.cjs');

(async () => {
  const browser = await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless:true,
    args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const {bots, machines, errors, state, open, enter} = createOverviewFixture(browser);
  try {
    state.inventoryUnavailable = true;
    const noInventory = await open({width:1280,height:900}); await noInventory.evaluate(() => location.hash = '#/overview');
    await noInventory.frameLocator('#overview-frame').locator('body[data-scene-ready]').waitFor();
    assert.equal((await noInventory.evaluate(() => overviewModel())).groups.filter(g => g.kind === 'computer').length, 2,
      'readable assignments survive inventory failure');
    await noInventory.close(); state.inventoryUnavailable = false;

    const machineCount = machines.length, botCount = bots.length;
    for (let i=0; i<7; i++) machines.push({id:'extra-'+i,label:'Computer '+i});
    for (let i=0; i<20; i++) bots.push({name:'extra-bot-'+i,status:'active',operator:'ana',machine:{runner_id:'alpha',label:'Garden Mac'},my_access:{see:true,read:true}});
    const large = await open({width:1440,height:1000}); await large.evaluate(() => location.hash = '#/overview');
    const frame = large.frameLocator('#overview-frame'); await frame.locator('body[data-scene-ready]').waitFor();
    assert.equal(await frame.locator('[data-floor]').count(), 11, 'every computer stays reachable in a large campus');
    await enter(large, 'computer:alpha');
    assert.equal(await frame.locator('[data-person]').count(), 26, 'every bot and human is rendered across multiple floors');
    await large.close(); machines.length = machineCount; bots.length = botCount;

    state.empty = true;
    const noTeam = await open({width:390,height:844}); await noTeam.evaluate(() => location.hash = '#/overview');
    await noTeam.frameLocator('#overview-frame').locator('#fallback p').filter({hasText:'add computers and teammates'}).waitFor();
    await noTeam.close();
    assert.deepEqual(errors, []);
    console.log('Overview resilience: unavailable inventory, large campus and empty-team states passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
