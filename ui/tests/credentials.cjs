// All requests use synthetic fixtures; no live secrets or mutations.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const page=await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block'});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    let resolveReveal;
    const credential={id:'fixture',name:'PostHog',env:'POSTHOG_API_KEY',username:'',kind:'api_key',preview:'phx…654',stored:true,grants:[],revision:1,source:''};
    await page.route('**/*',async route=>{
      const p=new URL(route.request().url()).pathname;
      const json=body=>route.fulfill({contentType:'application/json',body:JSON.stringify(body)});
      if(p==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../index.html'),'utf8')});
      const ui=p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if(ui){const file=path.join(__dirname,'..',ui[1]); if(fs.existsSync(file)) return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(file,'utf8')});}
      if(p.endsWith('.js'))return route.fulfill({contentType:'application/javascript',body:''});
      if(p==='/api/me')return json({id:'ana',name:'Ana',role:'owner',cloud:true,credential_access:true,credential_admin:true});
      if(p==='/api/v2/integrations')return json({integrations:[{service:'posthog',title:'PostHog',kind:'api',summary:'Product analytics',access:'hub',credentials:['POSTHOG_API_KEY — read-only'],writes:'never',owner:'ana',aliases:[]}]});
      if(p==='/api/v2/credentials')return json({credentials:[credential],can_manage:true,configured:true,people:[{id:'ben',name:'Ben'}],bots:[{id:'seo',name:'SEO'}]});
      if(p.endsWith('/reveal')){await new Promise(resolve=>resolveReveal=resolve);return json({id:'fixture',value:'synthetic-secret-value'});}
      if(p==='/api/employees'||p==='/api/issues')return json([]);
      if(p.endsWith('/watch'))return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
      return json({people:[],bots:[],models:[],runners:[],credentials:[]});
    });
    await page.goto('https://tico-ui.test/#/credentials');
    await page.getByRole('button',{name:'Credentials for PostHog'}).click();
    await page.getByRole('button',{name:'Reveal / copy',exact:true}).waitFor();
    assert.equal(await page.locator('body').innerText().then(s=>s.includes('synthetic-secret-value')),false);
    await page.getByRole('button',{name:'Reveal / copy',exact:true}).click();
    await page.waitForTimeout(100);
    await page.getByRole('button',{name:'Close credential',exact:true}).click();
    await page.getByRole('button',{name:'Edit',exact:true}).click();
    resolveReveal();
    await page.waitForTimeout(200);
    assert.equal(await page.getByRole('dialog').locator('textarea[readonly]').count(),0,'Late reveal must not expose a secret in a different dialog');
    await page.getByRole('button',{name:'Close credential',exact:true}).click();
    await page.getByRole('button',{name:'Reveal / copy',exact:true}).click();
    await page.waitForTimeout(100);resolveReveal();
    await page.getByLabel('Password or key',{exact:true}).waitFor();
    assert.equal(await page.getByLabel('Password or key',{exact:true}).inputValue(),'synthetic-secret-value');
    await page.getByRole('button',{name:'Close credential',exact:true}).click();
    assert.equal(await page.locator('#credential-dialog').innerHTML(),'');
    await page.getByRole('button',{name:'Manage access',exact:true}).click();
    assert.equal(await page.locator('#vault-grant-form option').count(),2);
    assert.deepEqual(errors,[]);
    console.log('Credentials mobile list, reveal cleanup, race isolation, and grant controls passed');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
