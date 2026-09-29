// Attachment interactions only; every request is intercepted, including Legal uploads.
const {chromium, webkit} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
(async () => {
  const browser = process.env.TICO_BROWSER === 'webkit' ? await webkit.launch({headless:true}) : await chromium.launch({channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined,headless:true});
  try {
    const page = await browser.newPage({viewport:{width:390,height:844},serviceWorkers:'block'});
    const errors=[],uploads=[];let rejectUpload=false;
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
      if(p==='/api/v2/uploads/chat/legal'){
        uploads.push({path:p,body:route.request().postDataBuffer().toString()});
        if(rejectUpload)return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:{detail:'Fixture upload unavailable'}})});
        return json({conversation:{id:'legal-upload'},message:{id:'m1',from_actor:'human:ana',body:'Review this fixture',created:new Date().toISOString()}});
      }
      return json({});
    });
    await page.goto('https://tico-ui.test/#/bot/legal/chat');
    await page.waitForFunction(()=>BOT?.slug==='legal' && V2C?.rendered);
    const composer=page.locator('#chat-composer');
    const box=composer.locator('textarea');
    async function choose() {
      const [chooser]=await Promise.all([page.waitForEvent('filechooser',{timeout:15000}),composer.getByRole('button',{name:'Attach files',exact:true}).click({timeout:10000})]);
      assert(chooser.isMultiple());
      return chooser;
    }
    // Reproduce the first tap after typing: do not blur or click a second time.
    await box.fill('Review this fixture');
    let chooser=await choose();
    await chooser.setFiles({name:'legal-fixture.txt',mimeType:'text/plain',buffer:Buffer.from('Synthetic attachment; no private legal material.')});
    await composer.getByText('legal-fixture.txt',{exact:false}).waitFor();
    await composer.getByRole('button',{name:'Send',exact:true}).click();
    await page.waitForFunction(()=>!document.querySelector('#chat-composer textarea').value);
    assert.equal(uploads.length,1);
    assert(uploads[0].body.includes('filename="legal-fixture.txt"'));
    assert(uploads[0].body.includes('Review this fixture'));
    assert.equal(await composer.locator('.p-chips [data-rm]').count(),0);
    // Cancel leaves the draft intact, and reopening/selecting/removing remains usable.
    await box.fill('Keep this draft');
    chooser=await choose();await chooser.setFiles([]);
    assert.equal(await box.inputValue(),'Keep this draft');
    chooser=await choose();await chooser.setFiles({name:'second.txt',mimeType:'text/plain',buffer:Buffer.from('Second fixture')});
    await composer.getByRole('link',{name:'remove second.txt'}).click();
    assert.equal(await composer.locator('.p-chips [data-rm]').count(),0);
    // Desktop and keyboard activation still open the native picker.
    await page.setViewportSize({width:1100,height:900});
    await box.focus();chooser=await choose();await chooser.setFiles([]);
    // Target the control directly; picker cancellation may still restore focus asynchronously.
    const [keyboardChooser]=await Promise.all([page.waitForEvent('filechooser',{timeout:15000}),composer.getByRole('button',{name:'Attach files',exact:true}).press('Enter')]);
    await keyboardChooser.setFiles([]);
    // Clipboard image data follows the same durable attachment route, without a picker.
    async function paste(target, names, text='') {
      return target.evaluate((box, {names,text}) => {
        const data=new DataTransfer();
        for(const name of names)data.items.add(new File([new Uint8Array([137,80,78,71])],name,{type:'image/png'}));
        if(text)data.setData('text/plain',text);
        const event=new Event('paste',{bubbles:true,cancelable:true});
        Object.defineProperty(event,'clipboardData',{value:data});
        box.dispatchEvent(event);
        return event.defaultPrevented;
      },{names,text});
    }
    await box.fill('Before after');
    await box.evaluate(el=>el.setSelectionRange(7,7));
    assert.equal(await paste(box,['screenshot.png','diagram.png'],'pasted '),true);
    assert.equal(await box.inputValue(),'Before pasted after');
    assert.equal(await composer.locator('.p-chips [data-rm]').count(),2);
    // A pasted image shows a preview; a tap opens it full size.
    assert.equal(await composer.locator('.p-chips .p-thumb img').count(),2);
    assert.match(await composer.locator('.p-chips .p-thumb img').first().getAttribute('src'),/^blob:/);
    await composer.getByRole('button',{name:'Open screenshot.png'}).click();
    await page.waitForFunction(()=>document.querySelector('#img-lightbox')?.open && document.querySelector('#img-lightbox img')?.src.startsWith('blob:'));
    assert.match(await page.locator('#img-lightbox').innerText(),/screenshot\.png/);
    await page.locator('#img-lightbox img').click();
    await page.waitForFunction(()=>!document.querySelector('#img-lightbox').open);
    await composer.getByRole('link',{name:'remove diagram.png'}).click();
    assert.equal(await composer.locator('.p-chips .p-thumb').count(),1);
    await box.fill('');
    assert.equal(await composer.getByRole('button',{name:'Send',exact:true}).isEnabled(),true);
    rejectUpload=true;
    await composer.getByRole('button',{name:'Send',exact:true}).click();
    await page.waitForFunction(()=>!BOT_PILL.sending);
    assert.equal(await composer.locator('.p-chips [data-rm]').count(),1);
    rejectUpload=false;
    await composer.getByRole('button',{name:'Send',exact:true}).click();
    await page.waitForFunction(()=>BOT_PILL.files.length===0);
    assert(uploads.at(-1).body.includes('filename="screenshot.png"'));
    assert(uploads.at(-1).body.includes('Attached files.'));
    assert.equal(await box.inputValue(),'');
    assert.equal(await composer.getByRole('button',{name:'Send',exact:true}).isDisabled(),true);
    assert.equal(await paste(box,[],'ordinary text'),false);
    assert.deepEqual(errors,[]);
    console.log('PASS: Legal first-tap picker, multipart attachment send, cancellation, reselect/remove, desktop and keyboard activation; image paste, mixed text, image-only send, retry and removal.');
  } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
