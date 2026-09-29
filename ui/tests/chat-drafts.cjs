// Text typed to one bot is still there after visiting another bot and coming back (Ana,
// 2026-09-28: "I type some stuff [in BotOps], I go back to Legal, and then I go back to Bot Ops,
// that stuff that I typed in Bot Ops would still be there"). A reload keeps it; sending clears it.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
(async () => {
  const browser = process.env.TICO_BROWSER === 'webkit' ? await webkit.launch({headless:true}) : await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined,headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1200,height:800},serviceWorkers:'block'});
    const errors=[],sent=[];
    page.on('pageerror',e=>errors.push(e.message));
    const bot=(name,display_name)=>({name,display_name,host:'keeper',status:'active',can_chat:true,schedules:[]});
    await page.context().route('**/*',route=>{
      const url=new URL(route.request().url()),p=url.pathname;
      const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      if(p==='/')return route.fulfill({contentType:'text/html',body:html});
      const ui=p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if(ui){const file=path.join(__dirname,'..',ui[1]);
        if(fs.existsSync(file))return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(file,'utf8')});}
      if(p==='/api/me')return json({id:'ana',name:'Ana',role:'owner',cloud:true});
      if(p==='/api/employees')return json([bot('botops','BotOps'),bot('legal','Legal')]);
      if(p==='/api/issues')return json([]);
      if(p.endsWith('/watch'))return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
      if(p==='/api/v2/conversations'){const b=url.searchParams.get('chat_with');
        return json({conversations:b?[{id:'c-'+b,kind:'chat',scope:'personal',participants:['human:ana','bot:'+b]}]:[]});}
      if(p.startsWith('/api/v2/conversations/c-')&&p.endsWith('/snapshot')){const b=p.split('/')[4].slice(2);
        return json({messages:[{id:'m-'+b,from_actor:'bot:'+b,body:'Hello from '+b,created:new Date().toISOString()}],execution:null});}
      if(p==='/api/v2/chat/botops'&&route.request().method()==='POST'){const body=route.request().postDataJSON();sent.push(body.body||body.text);
        return json({conversation:{id:'c-botops'},message:{id:'m-sent',from_actor:'human:ana',body:body.body||body.text,created:new Date().toISOString()}});}
      return json({});
    });
    const box=()=>page.locator('#chat-composer .p-text');
    const visit=async b=>{await page.evaluate(h=>{location.hash=h;},'#/bot/'+b+'/chat');await page.getByText('Hello from '+b).waitFor();};
    await page.goto('https://tico-ui.test/#/bot/botops/chat');
    await page.getByText('Hello from botops').waitFor();
    await box().fill('Half a thought for BotOps');
    await visit('legal');
    assert.equal(await box().inputValue(),'','Legal starts empty');
    await box().fill('Something for Legal');
    await visit('botops');
    assert.equal(await box().inputValue(),'Half a thought for BotOps');
    await visit('legal');
    assert.equal(await box().inputValue(),'Something for Legal');
    // A reload keeps both.
    await page.reload(); await page.getByText('Hello from legal').waitFor();
    assert.equal(await box().inputValue(),'Something for Legal');
    await visit('botops');
    assert.equal(await box().inputValue(),'Half a thought for BotOps');
    // Sending clears the draft for good.
    await box().press('Enter');
    await page.waitForFunction(()=>document.querySelector('#chat-composer .p-text').value==='');
    assert.deepEqual(sent,['Half a thought for BotOps']);
    await visit('legal'); await visit('botops');
    assert.equal(await box().inputValue(),'','a sent message does not come back');
    assert.deepEqual(errors,[]);
    console.log('chat-drafts: ok');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
