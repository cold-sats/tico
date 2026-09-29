// Offline chat send: a message the network dropped sends itself when the
// connection is back, once, with the same request id. Fixtures only, no network.
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
    const bots=[{name:'legal',display_name:'Legal',host:'keeper',status:'active',can_chat:true,schedules:[]}];
    await page.route('**/*',route=>{
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
    await page.goto('https://tico-ui.test/#/bot/legal/chat');
    await page.waitForFunction(()=>BOT?.slug==='legal' && V2C?.rendered);
    const box=page.locator('#chat-composer textarea');
    await box.fill('Hello offline');
    await page.locator('#chat-composer').getByRole('button',{name:'Send',exact:true}).click();
    await page.getByText('No connection. Your message will send by itself',{exact:false}).waitFor();
    assert.equal(sends.length,3,'three quick tries, then it waits');
    assert.equal(await box.inputValue(),'Hello offline','the message stays in the box');
    offline=false;
    await page.evaluate(()=>window.dispatchEvent(new Event('online')));
    await page.waitForFunction(()=>!document.querySelector('#chat-composer textarea').value);
    assert.equal(sends.length,4,'sent once when back online');
    assert.equal(new Set(sends).size,1,'every try carries the same request id');
    // Waiting out the backoff sends nothing more.
    await page.waitForTimeout(5500);
    assert.equal(sends.length,4);
    assert.deepEqual(errors,[]);
    console.log('chat-offline-retry: ok');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
