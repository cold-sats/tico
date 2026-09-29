// A 401 that names the built-in login page sends the browser there and back to the same place.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const page=await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block'});
    let login=null;
    await page.route('**/*',async route=>{
      const url=new URL(route.request().url()), p=url.pathname;
      if(p==='/auth/login'){login=url.search;return route.fulfill({contentType:'text/html',body:'<title>login</title>'});}
      if(p==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../index.html'),'utf8')});
      if(p.endsWith('.js'))return route.fulfill({contentType:'application/javascript',body:''});
      if(p.startsWith('/api/'))return route.fulfill({status:401,contentType:'application/json',body:JSON.stringify({error:{code:'identity',detail:'Sign in',sign_in:'/auth/login'}})});
      return route.fulfill({contentType:'application/json',body:'{}'});
    });
    await page.goto('https://tico-ui.test/?a=1#/tasks');
    await page.waitForURL('**/auth/login**');
    assert.equal(new URLSearchParams(login).get('next'),'/?a=1#/tasks');
    console.log('401 with sign_in goes to the login page and asks to return to the same place');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exit(1);});
