// Imported history is a snapshot, with no runtime credential actions; real agents retain them.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {html, uiFile} = require('./support/page.cjs');

(async () => {
  const browser = await chromium.launch({headless: true});
  const page = await browser.newPage({serviceWorkers: 'block'});
  const last = new Date(Date.now() - 27 * 3600e3).toISOString();
  let fresh = false;
  const errors = [], writes = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => { window.EventSource = undefined; });
  const bots = () => [
    {name:'history-copy',display_name:'Imported Designer',status:'active',host:'keeper',can_chat:true,operator:'ana',
      online:fresh,agent:{harness:'grokbot',credential:true,synced:true,last_seen:last}},
    {name:'live-agent',display_name:'Live Agent',status:'active',host:'keeper',can_chat:true,operator:'ana',
      online:false,agent:{harness:'hermes',credential:true,last_seen:last}}
  ];
  await page.route('**/*', route => {
    const request = route.request(), p = new URL(request.url()).pathname;
    const json = body => route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
    if (request.method() !== 'GET') writes.push(p);
    if (p === '/') return route.fulfill({contentType:'text/html',body:html});
    if (p.startsWith('/tico/ui/')) {
      const file = uiFile(p.slice('/tico/ui/'.length));
      if (fs.existsSync(file)) return route.fulfill({path:file});
    }
    if (p === '/api/me') return json({id:'ana',role:'owner',email:'ana@acme.example',cloud:true,bot_admin:true});
    if (p === '/api/humans') return json({people:[{id:'ana',name:'Ana'}]});
    if (p === '/api/employees') return json(bots());
    if (p === '/api/status') return json({cloud:true,keeper_alive:true,active:[],queued:[],health_issues:[]});
    if (p === '/api/v2/status') return json({bots:bots().map(b=>({bot:b.name,state:'idle',open_tasks:1}))});
    if (p === '/api/v2/tasks') return json({tasks:[],next_offset:null});
    if (p === '/api/v2/conversations') return json({conversations:[{id:'thread',scope:'personal',participants:['human:ana','bot:history-copy']}]});
    if (p.endsWith('/snapshot')) return json({messages:[]});
    if (p.endsWith('/files')) return json({files:[],total:0,can_manage:true});
    if (p.endsWith('/tools')) return json({tools:[]});
    return json({});
  });
  try {
    await page.goto('https://tico-ui.test/#/bot/history-copy/more');
    await page.locator('#pane-more:not([hidden])').waitFor();
    assert.equal(await page.locator('#pane-more [data-agent-credential], #pane-more [data-agent-revoke]').count(),0,
      'an import has no runtime credential to rotate or revoke');
    assert.doesNotMatch(await page.locator('#bot-alert').innerText(),/Offline/);
    assert.match(await page.locator('#bot-alert').innerText(),/History.*sync/i);
    await page.locator('#bot-top [data-tip-bot]').focus();
    await page.locator('#bot-tip:not([hidden])').waitFor();
    assert.match(await page.locator('#bot-tip').innerText(),/Last sync/);
    assert.doesNotMatch(await page.locator('#bot-tip').innerText(),/Not reporting|Last seen/);
    assert.equal(await page.evaluate(()=>S.emps.find(e=>e.name==='history-copy').agent.last_seen),last);
    assert.equal(await page.evaluate(()=>settingsBotProblem(S.emps.find(e=>e.name==='history-copy'))),'history not synced');
    if (process.env.TICO_SCREENSHOT_DIR) await page.screenshot({path:process.env.TICO_SCREENSHOT_DIR+'/imported-history.png'});

    fresh = true;
    await page.reload();
    await page.locator('#pane-more:not([hidden])').waitFor();
    assert.equal(await page.locator('#bot-alert').innerText(),'');
    assert.equal(await page.locator('#pane-more [data-agent-credential], #pane-more [data-agent-revoke]').count(),0);
    assert.equal(await page.evaluate(()=>settingsBotProblem(S.emps.find(e=>e.name==='history-copy'))),'');

    await page.goto('https://tico-ui.test/#/bot/live-agent/more');
    await page.locator('#pane-more:not([hidden])').waitFor();
    assert.match(await page.locator('#bot-alert').innerText(),/Offline with work waiting/);
    assert.equal(await page.locator('#pane-more [data-agent-credential], #pane-more [data-agent-revoke]').count(),2,
      'a real external agent retains its credential controls');
    await page.locator('#bot-top [data-tip-bot]').focus();
    await page.locator('#bot-tip:not([hidden])').waitFor();
    assert.match(await page.locator('#bot-tip').innerText(),/Not reporting|Last seen/);
    assert.deepEqual(errors,[]);
    assert.deepEqual(writes,[],'reading snapshots creates no credential or sends a message');
    console.log('imported-history: ok');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exit(1);});
