// Switching back to a bot paints its last chat and tasks at once ("bring down
// switching to less than 1s"). Fixtures only, no network; the second visit's answers are slowed.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
(async () => {
  const browser = process.env.TICO_BROWSER === 'webkit' ? await webkit.launch({headless:true}) : await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined,headless:true});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block'});
    const errors=[],uploads=[],sends=[];let offline=true;let slow=0;
    page.on('pageerror',e=>errors.push(e.message));
    const bot=(name,display_name)=>({name,display_name,host:'keeper',status:'active',can_chat:true,schedules:[]});
    const bots=[bot('legal','Legal'),bot('seo','AI SEO'),bot('cmo','AI CMO'),bot('finance','Finance'),bot('sales-ops','Sales Ops'),bot('designer','Designer')];
    await page.context().route('**/*',route=>{
      const url=new URL(route.request().url()),p=url.pathname;
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
      if(p.endsWith('/watch'))return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
      if(p==='/api/v2/conversations'){const bot=url.searchParams.get('chat_with');
        return json({conversations:bot?[{id:'c-'+bot,kind:'chat',scope:'personal',participants:['human:ana','bot:'+bot]}]:[]});}
      if(p.startsWith('/api/v2/conversations/c-')&&p.endsWith('/snapshot')){const bot=p.split('/')[4].slice(2);
        const body=JSON.stringify({messages:[{id:'m-'+bot,from_actor:'bot:'+bot,body:'Hello from '+bot,created:new Date().toISOString()}],execution:null});
        return setTimeout(()=>route.fulfill({contentType:'application/json',body}),slow);}
      if(p==='/api/v2/tasks'){const owner=url.searchParams.get('owner');
        const body=JSON.stringify({tasks:owner?[{id:'t-'+owner,title:'Task for '+owner,owner:'bot:'+owner,requester:'human:ana',status:'doing',lane:'company',labels:[],links:[],parts:{total:0,done:0},version:1,updated:new Date().toISOString()}]:[]});
        return setTimeout(()=>route.fulfill({contentType:'application/json',body}),slow);}
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
    await page.setViewportSize({width:1200,height:800});
    await page.goto('https://tico-ui.test/#/bot/legal/chat');
    await page.getByText('Hello from legal').waitFor();
    await page.evaluate(()=>{location.hash='#/bot/seo/chat';});
    await page.getByText('Hello from seo').waitFor();
    // Back to Legal with a slow hub: its chat is on screen at once, not "Loading".
    slow=3000;
    const t0=Date.now();
    await page.evaluate(()=>{location.hash='#/bot/legal/chat';});
    await page.getByText('Hello from legal').waitFor({timeout:1000});
    assert(Date.now()-t0<1000,'chat painted from memory in '+(Date.now()-t0)+'ms');
    await page.evaluate(()=>{location.hash='#/bot/legal/tasks';});
    await page.getByText('Task for legal').waitFor({timeout:1000});
    slow=0;
    assert.deepEqual(errors,[]);
    console.log('bot-switch-cache: ok');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
