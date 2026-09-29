// The Meetings page: Import posts one transcript to /api/v2/meetings/import, then lists and opens
// the meeting. All requests use synthetic fixtures; nothing leaves the browser.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
(async()=>{
  const browser=await chromium.launch({headless:true,channel:process.env.TICO_BROWSER_CHANNEL === undefined ? 'chrome' : process.env.TICO_BROWSER_CHANNEL || undefined});
  try {
    const page=await browser.newPage({viewport:{width:1280,height:900},serviceWorkers:'block'});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const meetings=[];
    const posts=[];
    const detail=m=>({...m,notes:'',transcript_readable:'',meeting_context:'',delivery:null,version:1,can_edit:true,outbox:{doc:[],task:[],feature:[]},outcome:null,attachments:[]});
    await page.route('**/*',async route=>{
      const req=route.request(), p=new URL(req.url()).pathname;
      const json=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
      if(p==='/')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(__dirname,'../index.html'),'utf8')});
      const ui=p.match(/\/tico\/ui\/([^/]+\.js)$/);
      if(ui){const file=path.join(__dirname,'..',ui[1]); if(fs.existsSync(file)) return route.fulfill({contentType:'application/javascript',body:fs.readFileSync(file,'utf8')});}
      if(p.endsWith('.js'))return route.fulfill({contentType:'application/javascript',body:''});
      if(p==='/api/me')return json({id:'ana',name:'Ana',email:'ana@example.com',role:'owner',cloud:true});
      if(p==='/api/employees'||p==='/api/issues'||p==='/api/people')return json([]);
      if(p==='/api/meetings/sources')return json({sources:[{id:'import',name:'Import',status:'available'},{id:'close',name:'Close',status:'needs_setup'}]});
      if(p==='/api/meetings')return json(meetings);
      if(p==='/api/v2/meetings/import'){
        const body=JSON.parse(req.postData()||'{}'); posts.push(body);
        const turns=[{speaker:'Dana',start_ms:5000,end_ms:9000,text:'Can you send pricing?'}];
        meetings.unshift({id:'m1',kind:'meeting',title:body.title,status:'done',started:body.started_at,source:body.source,owner:'ana@example.com',
          participants:[{name:'Dana',email:'dana@example.com',person_id:null},{name:'Sam',email:null,person_id:null}],turns,speakers:['Dana'],media_url:body.media_url||'',can_edit:true,outbox:{doc:[],task:[],feature:[]}});
        return json({id:'m1',title:body.title,turns:1,existing:false,changed:true,link:'#/meetings?meeting=m1'});
      }
      const one=p.match(/^\/api\/meetings\/([^/]+)$/);
      if(one)return json(detail(meetings.find(m=>m.id===one[1])||{}));
      if(/^\/api\/meetings\/[^/]+\/items$/.test(p))return json({id:'m1',can_push:true,sections:{doc:[],task:[],feature:[]},counts:{proposed:0}});
      if(/^\/api\/meetings\/[^/]+\/comments$/.test(p))return json({id:'m1',comments:[]});
      if(p.endsWith('/watch'))return route.fulfill({contentType:'text/event-stream',body:': fixture\n\n'});
      return json({people:[],bots:[],models:[],runners:[],config:{}});
    });
    await page.goto('https://tico-ui.test/#/meetings');
    await page.getByRole('heading',{name:'Meetings',exact:true}).waitFor();
    assert.match(await page.locator('.side-scroll [data-nav="meetings"]').innerText(),/Meetings\s*$/);
    await page.locator('.notes-empty').waitFor();
    assert.match(await page.locator('.notes-empty').innerText(),/No meetings yet/);

    await page.getByRole('button',{name:'Import a meeting',exact:true}).first().click();
    const dialog=page.locator('#import-modal');
    await dialog.waitFor();
    // Nothing to import yet: the form asks for a transcript instead of posting.
    await dialog.getByRole('button',{name:'Import',exact:true}).click();
    assert.match(await dialog.locator('#import-msg').innerText(),/Paste or choose a transcript/);
    assert.equal(posts.length,0);

    // A chosen file fills the paste box and, with no title yet, the title.
    await dialog.locator('#import-file').setInputFiles({name:'pricing-call.vtt',mimeType:'text/vtt',buffer:Buffer.from('WEBVTT\n\n00:00:05.000 --> 00:00:09.000\nDana: Can you send pricing?\n')});
    await page.waitForFunction(()=>document.querySelector('#import-text').value.startsWith('WEBVTT'));
    assert.equal(await dialog.locator('#import-title').inputValue(),'pricing call');

    await dialog.locator('#import-title').fill('Pricing call with Acme');
    await dialog.locator('#import-when').fill('2026-09-28T16:00');
    await dialog.locator('#import-people').fill('dana@example.com, Sam\nLee');
    await dialog.locator('#import-source').selectOption('google-meet');
    await dialog.locator('#import-media').fill('https://example.com/recording/1');
    await dialog.locator('#import-private').check();
    await dialog.getByRole('button',{name:'Import',exact:true}).click();

    await page.locator('#notes-modal[open] #meet-heading').waitFor();
    assert.equal(posts.length,1);
    const body=posts[0];
    assert.equal(body.title,'Pricing call with Acme');
    assert.equal(body.source,'google-meet');
    assert.deepEqual(body.participants,['dana@example.com','Sam','Lee']);
    assert.match(body.transcript,/^WEBVTT/);
    assert.match(body.started_at,/^2026-09-28T16:00:00[+-]\d\d:\d\d$/,'a local time goes up with its offset');
    assert.equal(body.media_url,'https://example.com/recording/1');
    assert.equal(body.private,true);

    // The meeting opens with its participants and a link to the media; the list behind it refreshed.
    const detailText=await page.locator('#notes-detail').innerText();
    assert.match(detailText,/Participants: Dana, Sam/);
    assert.match(detailText,/Google Meet/);
    assert.equal(await page.locator('#notes-detail a[href="https://example.com/recording/1"]').getAttribute('rel'),'noopener noreferrer');
    assert.match(await page.locator('#notes-detail .note-transcript').textContent(),/Can you send pricing\?/);
    await page.getByRole('button',{name:'Close meeting'}).click();
    assert.equal(await page.locator('.notes-table tbody tr').count(),1);
    assert.match(await page.locator('.notes-table').innerText(),/Pricing call with Acme/);

    // Old deep links still land on the meeting.
    await page.goto('https://tico-ui.test/#/recordings?recording=m1');
    await page.locator('#notes-modal[open] #meet-heading').waitFor();
    assert.match(page.url(),/#\/meetings\?meeting=m1/);
    assert.deepEqual(errors,[]);
    console.log('meetings-import: ok');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
