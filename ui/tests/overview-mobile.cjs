// Phone navigation, layout, computer selection and outside-tap behavior for the overview campus.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const {createOverviewFixture} = require('./support/overview-fixture.cjs');

(async () => {
  const browser = await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless:true,
    args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const {errors, open, enter, shot} = createOverviewFixture(browser);
  try {
    const mobile = await open({width:390,height:844}); await mobile.locator('#mobile-more').click();
    await mobile.locator('.side-scroll [data-nav=overview]').click();
    assert.equal(await mobile.locator('#mobile-nav [data-nav=overview]').count(), 0);
    assert.equal(await mobile.locator('#mobile-nav .mobile-nav-item').first().getAttribute('data-nav'), 'org');
    const frame = mobile.frameLocator('#overview-frame'); await frame.locator('body[data-scene-ready]').waitFor();
    const bounds = await mobile.locator('#overview-frame').boundingBox(), nav = await mobile.locator('#mobile-nav').boundingBox();
    assert(bounds.height > 400 && bounds.y + bounds.height <= nav.y + 1, 'campus fits above mobile navigation');
    await frame.locator('#loading').waitFor({state:'hidden'}); await shot(mobile, 'campus-mobile');
    await enter(mobile, 'computer:beta'); assert.equal(await frame.locator('[data-person]').count(), 7);
    await shot(mobile, 'computer-mobile');
    await mobile.keyboard.press('Escape'); await enter(mobile, 'computer:empty');
    assert.equal(await frame.locator('[data-person]').count(), 0);
    // The scene camera keeps moving under load, so use the control's actual DOM action instead of
    // pointer hit-testing and wait for the scene to return to the campus state.
    await frame.locator('#back').evaluate(button => button.click());
    await frame.locator('#back').waitFor({state:'hidden'});
    await frame.locator('#floors').waitFor({state:'visible'});
    await mobile.setViewportSize({width:360,height:740}); await enter(mobile, 'computer:alpha');
    await frame.locator('canvas').click({position:{x:10,y:10}});
    assert.equal(await frame.locator('#floors').getAttribute('hidden'), null, 'outside tap returns to campus');
    await mobile.close();
    assert.deepEqual(errors, []);
    console.log('Overview mobile: navigation, campus fit, selection, empty computer and outside tap passed');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exit(1); });
