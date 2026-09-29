// A bot's live reply keeps its separate messages apart: the server joins them with a blank line
// (execution.text, execution.parts), and the chat shows them as separate paragraphs, not one run-on
// line ("keep the bot planned.I've filed the build"). Fixtures only, no network.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
(async () => {
  const browser = process.env.TICO_BROWSER === 'webkit' ? await webkit.launch({headless:true}) : await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined,headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1200,height:800},serviceWorkers:'block'});
    const errors=[];
    page.on('pageerror',e=>errors.push(e.message));
    const now=new Date().toISOString();
    const snapshot={messages:[{id:'m1',from_actor:'human:ana',body:'Plan the build',created:now,
                               run:{job_id:'j1',attempt_id:'a1',state:'started_run'}}],
      execution:{job_id:'j1',message_id:'m1',bot:'ops',attempt_id:'a1',state:'running',label:'Working',
        text:'Keep the bot planned.\n\nI filed the build.',
        parts:[{kind:'progress',text:'Keep the bot planned.',at:now},{kind:'tool',text:'Ran hub task create',at:now},
               {kind:'reply',text:'I filed the build.',at:now}]}};
    await page.context().route('**/*',route=>{
      const url=new URL(route.request().url()),p=url.pathname;
      const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      if(p==='/')return route.fulfill({contentType:'text/html',body:html});
      const ui=p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if(ui){const file=path.join(__dirname,'..',ui[1]);
        if(fs.existsSync(file))return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(file,'utf8')});}
      if(/\/marked\.min\.js$/.test(p))return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(path.join(__dirname,'../vendor/marked.min.js'),'utf8')});
      if(p==='/api/me')return json({id:'ana',name:'Ana',role:'owner',cloud:true});
      if(p==='/api/employees')return json([{name:'ops',display_name:'Ops',host:'keeper',status:'active',can_chat:true,schedules:[]}]);
      if(p==='/api/issues')return json([]);
      if(p.endsWith('/watch'))return route.fulfill({contentType:'text/event-stream',body:'event: snapshot\ndata: '+JSON.stringify(snapshot)+'\n\n'});
      if(p==='/api/v2/conversations'){const b=url.searchParams.get('chat_with');
        return json({conversations:b?[{id:'c-ops',kind:'chat',scope:'personal',participants:['human:ana','bot:ops']}]:[]});}
      if(p.startsWith('/api/v2/conversations/c-')&&p.endsWith('/snapshot'))return json(snapshot);
      return json({});
    });
    await page.goto('https://tico-ui.test/#/bot/ops/chat');
    await page.locator('#v2-live').waitFor();
    const paragraphs=await page.locator('#v2-live p').allInnerTexts();
    assert.deepEqual(paragraphs,['Keep the bot planned.','I filed the build.'],'each message is its own paragraph');
    assert.deepEqual(errors,[]);
    console.log('live-reply: ok');
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
