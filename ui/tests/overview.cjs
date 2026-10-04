// Exercise the bundled app, computer placement, iframe renderer and existing API contracts.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
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
(async()=>{
  const browser=await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL??'chrome',headless:true,
    args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  let offline=false,running=true,empty=false,inventoryUnavailable=false;
  const errors=[], requests=[];
  const artifacts=process.env.TICO_OVERVIEW_ARTIFACTS;
  if(artifacts)fs.mkdirSync(artifacts,{recursive:true});
  const shot=async(page,name)=>{if(artifacts)await page.screenshot({path:path.join(artifacts,name+'.png')});};
  const open=async(viewport,noWebGL=false)=>{
    const page=await browser.newPage({viewport,serviceWorkers:'block',reducedMotion:'reduce'});
    page.on('pageerror',e=>errors.push(e.message));
    if(noWebGL)await page.addInitScript(()=>{
      const original=HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext=function(type,...args){return String(type).startsWith('webgl')?null:original.call(this,type,...args);};
    });
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url()),p=url.pathname;requests.push(p);
      if(url.origin!=='http://tico-ui.test')return route.abort();
      const json=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
      if(p==='/')return route.fulfill({contentType:'text/html',body:html});
      if(p.startsWith('/tico/ui/')){
        const name=p.slice('/tico/ui/'.length),file=uiFile(name);
        if(fs.existsSync(file))return route.fulfill({contentType:name.endsWith('.html')?'text/html':name.endsWith('.css')?'text/css':name.endsWith('.js')?'application/javascript':'application/octet-stream',body:fs.readFileSync(file)});
      }
      if(p==='/api/employees')return json(empty?[]:bots);
      if(p==='/api/humans')return json({people:empty?[]:people,org_groups:[]});
      if(p==='/api/me')return json({id:'ana',name:'Ana',role:'owner',cloud:true,config:{company_name:'Acme Studio'}});
      if(p==='/api/status')return json({active:[],employees:[]});
      if(p==='/api/issues')return json([]);
      if(p==='/api/v2/computers')return json({computers:empty?[]:machines},inventoryUnavailable?503:200);
      if(p==='/api/v2/status')return json({bots:bots.map(b=>({bot:b.name,state:running?'running':'waiting_human',focus:'SECRET WORK CONTENT'}))},offline?503:200);
      return json({});
    });
    await page.goto('http://tico-ui.test/');await page.waitForFunction(()=>location.hash==='#/updates');return page;
  };
  const modelOf=page=>page.evaluate(()=>overviewModel());
  const enter=async(page,key)=>{
    const frame=page.frameLocator('#overview-frame');
    await frame.locator(`[data-computer="${key}"]`).focus();await page.keyboard.press('Enter');return frame;
  };
  try{
    const page=await open({width:1440,height:1000});
    assert.equal(await page.locator('#overview-frame').count(),0);
    assert(!requests.includes('/api/v2/computers'),'computer inventory stays lazy');
    assert(!requests.some(p=>p.includes('/vendor/three/')),'Three.js stays lazy');
    await page.locator('.side-scroll [data-nav=overview]').click();
    const frame=page.frameLocator('#overview-frame');await frame.locator('body[data-scene-ready]').waitFor();
    await frame.locator('[data-computer="computer:empty"]').waitFor({state:'attached'});
    const model=await modelOf(page),members=model.groups.flatMap(g=>g.members);
    assert.deepEqual(model.groups.filter(g=>g.kind==='computer').map(g=>g.id),['computer:alpha','computer:beta','computer:empty']);
    for(const id of ['human:hidden','bot:invisible','bot:retired','bot:other-branch'])assert(!members.some(m=>m.id===id),id);
    assert(members.some(m=>m.id==='bot:my-branch'));
    assert(!JSON.stringify(model).includes('SECRET'),'machine and free-text work content stay private');
    const inBuilding=(key,id)=>model.groups.find(g=>g.id===key).members.some(m=>m.id===id);
    assert(inBuilding('computer:alpha','human:ana')&&inBuilding('computer:beta','human:ana'),'person with bots on two machines appears in both');
    assert(inBuilding('computer:alpha','human:jo')&&!inBuilding('computer:beta','human:jo'),'person with bots on one machine appears once');
    assert(inBuilding('computer:beta','human:pat')&&!inBuilding('computer:alpha','human:pat'),'visible reporting chains place the human manager');
    assert(!inBuilding('@commons','human:ana')&&inBuilding('@commons','human:eli'),'only unplaced people use the pavilion');
    assert(inBuilding('@commons','bot:restricted')&&inBuilding('@commons','bot:unassigned')&&inBuilding('@commons','bot:external'));
    assert.equal(members.find(m=>m.id==='bot:restricted').href,'');
    assert.equal(model.groups.find(g=>g.id==='computer:empty').members.length,0);
    await frame.locator('#loading').waitFor({state:'hidden'});await shot(page,'campus-desktop');
    // An iframe's media query can update without dispatching its change event. Observe the rendered result.
    const sceneFrame=page.frames().find(f=>f.url().includes('/overview/index.html'));
    const drawn=()=>sceneFrame.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
    await page.emulateMedia({reducedMotion:'no-preference'});await drawn();
    const movingA=await frame.locator('canvas').screenshot();await page.waitForTimeout(700);const movingB=await frame.locator('canvas').screenshot();
    assert(!movingA.equals(movingB),'decorative motion advances');
    await page.emulateMedia({reducedMotion:'reduce'});await drawn();
    const stillA=await frame.locator('canvas').screenshot();await page.waitForTimeout(700);const stillB=await frame.locator('canvas').screenshot();
    assert(stillA.equals(stillB),'changing reduced-motion preference freezes the canvas');
    await enter(page,'computer:alpha');
    assert.equal(await frame.locator('[data-person]').count(),6,'all occupants have an accessible character, without sampling');
    assert.equal(await frame.locator('[data-person="bot:bot-0"] img').count(),0);
    await shot(page,'computer-desktop');
    await frame.locator('[data-person="bot:bot-0"]').focus();await page.keyboard.press('Enter');
    const child=page.frames().find(f=>f.url().includes('/overview/index.html'));
    await child.evaluate(()=>window.originalCanvas=document.querySelector('canvas'));
    running=false;await page.evaluate(()=>refresh());
    await frame.locator('#speech-message').filter({hasText:'Waiting on a human'}).waitFor();
    assert(await child.evaluate(()=>window.originalCanvas===document.querySelector('canvas')),'status refresh preserves renderer and selection');
    offline=true;await page.evaluate(()=>refresh());
    await frame.locator('#speech-message').filter({hasText:'Status is unavailable'}).waitFor();
    assert.equal((await modelOf(page)).groups[0].members.find(m=>m.type==='bot').state,'unknown');
    offline=false;await page.evaluate(()=>refresh());
    await frame.locator('#speech-message').filter({hasText:'Waiting on a human'}).waitFor();
    // Observe navigation directly because software WebGL can suspend animation-frame polling on exit.
    await Promise.all([page.waitForURL(url=>url.hash==='#/bot/bot-0'),frame.locator('#speech-open').click()]);
    assert.equal(await page.locator('#overview-frame').count(),0);
    await page.evaluate(()=>location.hash='#/overview');await frame.locator('body[data-scene-ready]').waitFor();
    await enter(page,'computer:beta');await frame.locator('[data-person="human:ana"]').focus();await page.keyboard.press('Enter');
    assert.match(await frame.locator('#speech-message').innerText(),/Presence is not tracked/);
    await Promise.all([page.waitForURL(url=>url.hash==='#/person/ana'),frame.locator('#speech-open').click()]);
    await page.evaluate(()=>location.hash='#/overview');await frame.locator('body[data-scene-ready]').waitFor();
    await enter(page,'computer:alpha');
    bots[0].machine={runner_id:'beta',label:'Solar Linux'};await page.evaluate(()=>refresh());
    await frame.locator('[data-person]').first().waitFor({state:'attached'});
    await page.waitForFunction(()=>overviewModel().groups.find(g=>g.id==='computer:beta').members.some(m=>m.id==='bot:bot-0'));
    assert(!(await modelOf(page)).groups.find(g=>g.id==='computer:alpha').members.some(m=>m.id==='bot:bot-0'),'reassignment moves a bot between buildings');
    await frame.locator('body[data-scene-ready]').waitFor();
    assert.equal(await frame.locator('#floor-title').innerText(),'Garden Mac','topology rebuild remembers building');
    bots[0].machine={runner_id:'alpha',label:'Garden Mac'};
    await page.close();

    const mobile=await open({width:390,height:844});await mobile.locator('#mobile-more').click();
    await mobile.locator('.side-scroll [data-nav=overview]').click();
    assert.equal(await mobile.locator('#mobile-nav [data-nav=overview]').count(),0);
    assert.equal(await mobile.locator('#mobile-nav .mobile-nav-item').first().getAttribute('data-nav'),'org');
    const phoneFrame=mobile.frameLocator('#overview-frame');await phoneFrame.locator('body[data-scene-ready]').waitFor();
    const bounds=await mobile.locator('#overview-frame').boundingBox(),nav=await mobile.locator('#mobile-nav').boundingBox();
    assert(bounds.height>400&&bounds.y+bounds.height<=nav.y+1,'campus fits above mobile navigation');
    await phoneFrame.locator('#loading').waitFor({state:'hidden'});await shot(mobile,'campus-mobile');
    await enter(mobile,'computer:beta');assert.equal(await phoneFrame.locator('[data-person]').count(),7);
    await shot(mobile,'computer-mobile');
    await mobile.keyboard.press('Escape');await enter(mobile,'computer:empty');
    assert.equal(await phoneFrame.locator('[data-person]').count(),0);await phoneFrame.locator('#back').click();
    await mobile.setViewportSize({width:360,height:740});await enter(mobile,'computer:alpha');
    await phoneFrame.locator('canvas').click({position:{x:10,y:10}});
    assert.equal(await phoneFrame.locator('#floors').getAttribute('hidden'),null,'outside tap returns to campus');
    await mobile.close();

    inventoryUnavailable=true;
    const noInventory=await open({width:1280,height:900});await noInventory.evaluate(()=>location.hash='#/overview');
    await noInventory.frameLocator('#overview-frame').locator('body[data-scene-ready]').waitFor();
    assert.equal((await modelOf(noInventory)).groups.filter(g=>g.kind==='computer').length,2,'readable assignments survive inventory failure');await noInventory.close();inventoryUnavailable=false;
    const fallback=await open({width:1280,height:900},true);await fallback.evaluate(()=>location.hash='#/overview');
    await fallback.frameLocator('#overview-frame').locator('#fallback-team button').first().waitFor();
    assert.equal(await fallback.frameLocator('#overview-frame').locator('#fallback-team section').count(),4);
    assert.equal(await fallback.frameLocator('#overview-frame').locator('#fallback-team button').count(),members.length);
    await fallback.close();
    const machineCount=machines.length,botCount=bots.length;
    for(let i=0;i<7;i++)machines.push({id:'extra-'+i,label:'Computer '+i});
    for(let i=0;i<20;i++)bots.push({name:'extra-bot-'+i,status:'active',operator:'ana',machine:{runner_id:'alpha',label:'Garden Mac'},my_access:{see:true,read:true}});
    const large=await open({width:1440,height:1000});await large.evaluate(()=>location.hash='#/overview');
    const largeFrame=large.frameLocator('#overview-frame');await largeFrame.locator('body[data-scene-ready]').waitFor();
    assert.equal(await largeFrame.locator('[data-floor]').count(),11,'every computer stays reachable in a large campus');
    await enter(large,'computer:alpha');assert.equal(await largeFrame.locator('[data-person]').count(),26,'every bot and human is rendered across multiple floors');
    await large.close();machines.length=machineCount;bots.length=botCount;
    empty=true;const noTeam=await open({width:390,height:844});await noTeam.evaluate(()=>location.hash='#/overview');
    await noTeam.frameLocator('#overview-frame').locator('#fallback p').filter({hasText:'add computers and teammates'}).waitFor();
    await noTeam.close();assert.deepEqual(errors,[]);
    console.log('Overview: computer campus, collaborator duplication, permissions, reassignment, status, keyboard navigation, mobile, lifecycle, fallback and empty state passed');
  }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
