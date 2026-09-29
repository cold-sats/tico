// Phone chat switcher: the bot's icon left of the chat bar opens a fan of the
// four bots most recently opened, with Search on top of the stack. Fixtures only, no network.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
(async () => {
  const browser = process.env.TICO_BROWSER === 'webkit' ? await webkit.launch({headless:true}) : await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined,headless:true});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block'});
    const errors=[],uploads=[],sends=[];let offline=true;
    page.on('pageerror',e=>errors.push(e.message));
    const bot=(name,display_name)=>({name,display_name,host:'keeper',status:'active',can_chat:true,schedules:[]});
    const bots=[bot('legal','Legal'),bot('seo','AI SEO'),bot('cmo','AI CMO'),bot('finance','Finance'),bot('sales-ops','Sales Ops'),bot('designer','Designer')];
    await page.context().route('**/*',route=>{
      const p=new URL(route.request().url()).pathname;
      const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      if(p==='/')return route.fulfill({contentType:'text/html',body:html});
      const ui=p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if(ui){
        const file=path.join(__dirname,'..',ui[1]);
        if(fs.existsSync(file))return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(file,'utf8')});
      }
      if(p==='/api/me')return json({id:'ana',name:'Ana',role:'owner',cloud:true});
      if(p==='/api/employees')return json(bots);
      if(p==='/api/issues')return json([]);
      if(p==='/api/v2/conversations')return json({conversations:[]});
      if(p.endsWith('/watch'))return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
      if(p==='/api/v2/chat/legal'){
        sends.push(route.request().headers()['idempotency-key']);
        if(offline)return route.abort('internetdisconnected');
        return json({conversation:{id:'legal-chat'},message:{id:'m1',from_actor:'human:ana',body:'Hello offline',created:new Date().toISOString()}});
      }
      if(p==='/api/v2/uploads/chat/legal'){
        uploads.push({path:p,body:route.request().postDataBuffer().toString()});
        if(false)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{detail:'Fixture upload unavailable'}})});
        return json({conversation:{id:'legal-upload'},message:{id:'m1',from_actor:'human:ana',body:'Review this fixture',created:new Date().toISOString()}});
      }
      return json({});
    });
    await page.addInitScript(()=>{ if(!localStorage.getItem('tico.org.history')) localStorage.setItem('tico.org.history',JSON.stringify(['b:legal','b:seo','b:cmo','b:finance','b:sales-ops','b:designer'])); });
    await page.goto('https://tico-ui.test/#/bot/legal/chat');
    await page.waitForFunction(()=>BOT?.slug==='legal' && V2C?.rendered);
    const icon=page.locator('#chat-composer .p-bot');
    assert.equal(await icon.isVisible(),true,'the bot icon sits in the chat bar on a phone');
    const [iconBox,textBox]=[await icon.boundingBox(),await page.locator('#chat-composer .p-text').boundingBox()];
    assert(iconBox.x+iconBox.width<=textBox.x,'left of where you type');
    await icon.click();
    await page.locator('#org-fan.open').waitFor();
    const order=await page.locator('#org-fan .org-fan-item').evaluateAll(els=>els.map(el=>el.dataset.orgBot||'search'));
    assert.deepEqual(order,['seo','cmo','finance','sales-ops','search'],'four most recent, not this bot, Search last in the list');
    const [top,first]=[await page.locator('[data-org-search]').boundingBox(),await page.locator('[data-org-bot="seo"]').boundingBox()];
    assert(top.y<first.y,'Search is on top of the stack');
    assert(first.y+first.height<=iconBox.y,'the fan rises from the chat bar');
    assert.equal(await icon.getAttribute('aria-expanded'),'true');
    // Tapping the bot icon again dismisses it, at once.
    await page.mouse.click(iconBox.x+iconBox.width/2,iconBox.y+iconBox.height/2);
    assert.equal(await page.evaluate(()=>document.querySelector('#org-fan').hidden),true);
    assert.equal(await icon.getAttribute('aria-expanded'),'false');
    await icon.click();
    assert.equal(await page.evaluate(()=>document.querySelector('#org-fan').hidden),false,'opens at once');
    await page.locator('[data-org-bot="cmo"]').click();
    await page.waitForFunction(()=>location.hash==='#/bot/cmo' && document.querySelector('#org-fan').hidden);
    await page.waitForFunction(()=>BOT?.slug==='cmo');
    await page.locator('#chat-composer .p-bot').click();
    await page.locator('#org-fan.open').waitFor();
    await page.locator('[data-org-search]').click();
    await page.waitForFunction(()=>document.querySelector('#search-modal').open);
    // On a computer the icon is not there.
    await page.keyboard.press('Escape');
    await page.setViewportSize({width:1200,height:800});
    assert.equal(await page.locator('#chat-composer .p-bot').isVisible(),false);
    assert.deepEqual(errors,[]);
    console.log('chat-switcher: ok');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
