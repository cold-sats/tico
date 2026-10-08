// Shared synthetic team and browser routes for the independently scheduled overview checks.
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./page.cjs');

function createOverviewFixture(browser) {
  const people = [{id:'ana',name:'Ana'}, {id:'jo',name:'Jo'}, {id:'eli',name:'Eli'}, {id:'pat',name:'Pat'}, {id:'hidden',name:'Hidden human',hidden:true}];
  const machines = [
    {id:'alpha',label:'Garden Mac',bots:['restricted']},
    {id:'beta',label:'Solar Linux'},
    {id:'empty',label:'Spare computer'},
    {id:'revoked',label:'Revoked machine',revoked_at:'2026-01-01'}
  ];
  const bots = Array.from({length:8},(_,i)=>({name:'bot-'+i,display_name:i===0?'<img src=x onerror=alert(1)>':'Teammate '+i,
    host:'keeper',status:'active',operator:i<4?'jo':'ana',users:[{id:'ana'},{id:'hidden'}],
    machine:{runner_id:i<4?'alpha':'beta',label:i<4?'Garden Mac':'Solar Linux'},my_access:{see:true,read:true},can_chat:true}));
  bots[4].reports_to='bot-5'; bots[5].reports_to='human:pat';
  bots[6].reports_to='bot-7'; bots[7].reports_to='bot-6'; // Cycles cannot stall the model.
  bots.push({name:'restricted',machine:{runner_id:'secret',label:'SECRET MACHINE'},my_access:{see:true,read:false}},
    {name:'invisible',my_access:{see:false}}, {name:'retired',status:'retired'},
    {name:'my-branch',is_branch:true,operator:'ana',machine:{runner_id:'beta',label:'Solar Linux'}},
    {name:'other-branch',is_branch:true,operator:'other'},
    {name:'unassigned',status:'planned'},
    {name:'external',agent:{platform:'external'},status:'active'});
  const state = {offline:false, running:true, empty:false, inventoryUnavailable:false};
  const errors = [], requests = [];
  const artifacts = process.env.TICO_OVERVIEW_ARTIFACTS;
  if (artifacts) fs.mkdirSync(artifacts, {recursive:true});
  const shot = async (page, name) => { if (artifacts) await page.screenshot({path:path.join(artifacts,name+'.png')}); };
  // Software WebGL can monopolize requestAnimationFrame polling under parallel release load.
  const waitForCondition = (context, predicate, arg) => context.waitForFunction(predicate, arg, {polling:100});
  const open = async (viewport, noWebGL = false) => {
    const page = await browser.newPage({viewport, serviceWorkers:'block', reducedMotion:'reduce'});
    await page.addInitScript(() => { window.__TICO_OVERVIEW_TEST_PROBE__ = {}; });
    page.on('pageerror', e => errors.push(e.message));
    if (noWebGL) await page.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type, ...args) {
        return String(type).startsWith('webgl') ? null : original.call(this, type, ...args);
      };
    });
    await page.route('**/*', async route => {
      const url = new URL(route.request().url()), p = url.pathname; requests.push(p);
      if (url.origin !== 'http://tico-ui.test') return route.abort();
      const json = (body, status = 200) => route.fulfill({status, contentType:'application/json', body:JSON.stringify(body)});
      if (p === '/') return route.fulfill({contentType:'text/html', body:html});
      if (p.startsWith('/tico/ui/')) {
        const name = p.slice('/tico/ui/'.length), file = uiFile(name);
        if (fs.existsSync(file)) return route.fulfill({contentType:name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.js')?'application/javascript':'application/octet-stream', body:fs.readFileSync(file)});
      }
      if (p === '/api/employees') return json(state.empty ? [] : bots);
      if (p === '/api/humans') return json({people:state.empty ? [] : people, org_groups:[]});
      if (p === '/api/me') return json({id:'ana', name:'Ana', role:'owner', cloud:true, config:{company_name:'Acme Studio'}});
      if (p === '/api/status') return json({active:[], employees:[]});
      if (p === '/api/issues') return json([]);
      if (p === '/api/v2/computers') return json({computers:state.empty ? [] : machines}, state.inventoryUnavailable ? 503 : 200);
      if (p === '/api/v2/status') return json({bots:bots.map(b=>({bot:b.name,state:state.running?'running':'waiting_human',focus:'SECRET WORK CONTENT'}))}, state.offline ? 503 : 200);
      return json({});
    });
    await page.goto('http://tico-ui.test/');
    await waitForCondition(page, () => location.hash === '#/updates');
    return page;
  };
  const modelOf = page => page.evaluate(() => overviewModel());
  const enter = async (page, key) => {
    const frame = page.frameLocator('#overview-frame');
    await frame.locator(`[data-computer="${key}"]`).focus(); await page.keyboard.press('Enter'); return frame;
  };
  return {people, machines, bots, state, errors, requests, shot, waitForCondition, open, modelOf, enter};
}

module.exports = {createOverviewFixture};
