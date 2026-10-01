// The chat, offline. Fixtures only, no network.
//  - offline retry: a message the network dropped sends itself when the connection is back, once, with the
//    same request id.
//  - live reply: a bot's separate messages stay apart (the server joins them with a blank line,
//    execution.text and execution.parts) and show as separate paragraphs, not one run-on line
//    ("keep the bot planned.I've filed the build").
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');

async function offlineRetry(browser) {
  const page = await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block'});
  const errors=[],uploads=[],sends=[];let offline=true;
  page.on('pageerror',e=>errors.push(e.message));
  const bots=[{name:'legal',display_name:'Legal',host:'keeper',status:'active',can_chat:true,schedules:[]}];
  await page.route('**/*',route=>{
    const p=new URL(route.request().url()).pathname;
    const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    if(p==='/')return route.fulfill({contentType:'text/html',body:html});
    const ui=p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if(ui){
      const file=uiFile(ui[1]);
      if(fs.existsSync(file))return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript',body:fs.readFileSync(file,'utf8')});
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
  console.log('chat offline retry: ok');
}

async function liveReply(browser) {
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
    const ui=p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if(ui){const file=uiFile(ui[1]);
      if(fs.existsSync(file))return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript',body:fs.readFileSync(file,'utf8')});}
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
  // Avatars: a bot is an SVG blob that morphs while it answers; a person stays a circle; motion stops under reduced motion.
  const av=await page.evaluate(()=>{
    const el=document.querySelector('#bot-top .av'),path=el?.querySelector('svg.av-shape path');
    const probe=document.createElement('div');
    probe.innerHTML=personCircle('Ana Reyes',22)+botAvatar({name:'ops',icon:'rocket_launch'},22);
    document.body.append(probe);
    const [person,glyph]=probe.children;
    return {blob:!!el?.classList.contains('blob'),d:/^M[\d.]+ [\d.]+(C[-\d. ]+){6,8}Z$/.test(path?.getAttribute('d')||''),
      morph:!!el?.classList.contains('morph'),moving:getComputedStyle(path).animationName==='av-morph'||!!path.querySelector('animate'),
      person:!person.querySelector('svg')&&getComputedStyle(person).borderRadius==='50%',
      glyph:glyph.querySelector('.av-glyph')?.textContent,same:botAvatar('ops',22)===botAvatar('ops',22)};
  });
  assert.deepEqual(av,{blob:true,d:true,morph:true,moving:true,person:true,glyph:'rocket_launch',same:true},'bot blob, person circle');
  await page.emulateMedia({reducedMotion:'reduce'});
  assert.equal(await page.evaluate(()=>{const p=document.querySelector('#bot-top .av-shape path');
    return getComputedStyle(p).animationName==='none'&&!botAvatar('ops',36).includes('<animate');}),true,'reduced motion: no morph');
  assert.deepEqual(errors,[]);
  const pending = await page.evaluate(() => {
    const state = {slug:'ops', messages:[{id:'queued',created:new Date(Date.now()-30*60000).toISOString()}],
      execution:{message_id:'queued',state:'queued',label:'Saved — no AI provider is chosen',readiness_reason:'missing_provider'}};
    const el = document.createElement('div');
    el.innerHTML = v2PendingHTML(state);
    const link = el.querySelector('a');
    const result = {text:el.textContent,href:link?.getAttribute('href'),tab:link?.dataset.gsTab};
    delete state.execution.readiness_reason;
    const legacy = v2PendingHTML(state);
    clearTimeout(state.waitTimer);
    return {...result,legacy};
  });
  assert.match(pending.text,/no AI provider is chosen/);
  assert.match(pending.text,/Add an AI provider/);
  assert.equal(pending.href,'#/settings');
  assert.equal(pending.tab,'providers');
  assert.match(pending.legacy,/No reply after 20 minutes/);
  console.log('chat live reply: ok');
}

(async () => {
  const browser = process.env.TICO_BROWSER === 'webkit' ? await webkit.launch({headless:true}) : await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined,headless:true});
  try {
    await offlineRetry(browser);
    await liveReply(browser);
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
