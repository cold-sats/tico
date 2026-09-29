// Offline browser regression for the bot page and the rail.
// Desktop: the bot's goal leads as plain words; chat on the left, the bot's
// tasks on the right as one flat Active list with its routines under them; old #/bot/x/tasks links
// land there; More holds the settings and Docs; a bot with no goal says so. Phone: one top line with
// back, the bot and Chat · Tasks · More, the goal folded to one line, no bottom bar, the composer on
// the bottom edge. Both: an arrow to send (no "Send as task"), a wave for Live, a status only when it
// is an alert. The rail reads Tasks, Goals, Docs, Market, Meetings, Org, Message bots; the account
// menu holds Integrations, Runs, Changelog and Settings; More on a phone opens that rail unfolded;
// and no text field is under 16px on a phone, so iOS never zooms into one. The chat (#524): short
// links, the pending line and its timeout, the jump pill, the composer cap, files dropped on the pane.
// Fixtures only, no network. TICO_SCREENSHOT_DIR=<dir> saves the review screenshots.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, '../index.html'), 'utf8');
const shots = process.env.TICO_SCREENSHOT_DIR;

const hour = 3600e3, now = Date.now(), iso = ms => new Date(now + ms).toISOString();
const bot = (name, display_name, org_parent, extra = {}) => ({name, display_name, org_parent, host: 'keeper',
  status: 'active', can_chat: true, users: [{id: 'ana', name: 'Ana'}], schedules: [], ...extra});
const bots = [
  bot('coo', 'Tico', ''), bot('doc-updater', 'Doc Updater', 'b:coo'),
  bot('cmo', 'AI CMO', '', {role: 'Grows organic signups through content and search.', schedules: [
    {id: 'r-plan', title: 'Weekday content plan', kind: 'cron', cron: '0 8 * * 1-5', on: '', timezone: 'America/Los_Angeles',
     enabled: true, active: true, next: iso(14 * hour)},
    {id: 'r-rec', title: 'Pull quotes from new recordings', kind: 'event', cron: '', on: 'recording.ready', timezone: 'America/Los_Angeles',
     enabled: true, active: true, next: null}]}),
  bot('seo', 'AI SEO', 'b:cmo'),
];
const goal = {id: 'g-signups', title: 'Double organic signups by December', owner: 'bot:cmo', status: 'green', rank: 0,
  status_note: 'Signups are up 18% month on month after the pricing page shipped.', status_at: iso(-20 * hour), status_by: 'human:ana',
  kpis: [{id: 'k-signups', name: 'Organic signups per week', unit: 'signups', target: 400, readings: 6,
    latest_measured: {value: 312, ts: iso(-26 * hour), source: 'measured'}, latest: {value: 312, ts: iso(-26 * hour), source: 'measured'}}],
  chain: [], children: [], tasks: [], events: []};
const LONG = 'Rewrite the vacation rental cleaning checklist landing page so it answers the five questions hosts ask most before booking';
const tasks = [
  {id: 't-pricing', title: 'Publish the pricing comparison page', status: 'doing', owner: 'bot:cmo', requester: 'human:ana', lane: 'company', created: iso(-30 * hour), updated: iso(-2 * hour)},
  {id: 't-brief', title: 'Approve the October content brief', status: 'waiting', owner: 'human:ana', requester: 'bot:cmo', lane: 'company', created: iso(-5 * hour), updated: iso(-hour)},
  {id: 't-audit', title: LONG, status: 'open', owner: 'bot:cmo', requester: 'human:ana', lane: 'company', created: iso(-50 * hour), updated: iso(-40 * hour)},
  {id: 't-shipped', title: 'Ship the September newsletter', status: 'done', owner: 'bot:cmo', requester: 'human:ana', lane: 'company', created: iso(-90 * hour), updated: iso(-70 * hour)},
];
const messages = [
  {id: 'm1', from_actor: 'human:ana', body: 'Where are we on the pricing page?', created: iso(-3 * hour)},
  {id: 'm2', from_actor: 'bot:cmo', body: 'The comparison table is drafted; I am checking the numbers with Finance before it ships tomorrow.', created: iso(-3 * hour + 60e3),
   refs: {task_id: 't-pricing', turn_id: 'turn-1'},
   // What the turn did (backend/turns.py): titles and names, never ids; its steps on request.
   ref_tasks: {'t-pricing': {title: 'Publish the pricing comparison page', owner: 'bot:cmo', status: 'doing'}},
   run: {steps: 4, tool_calls: 2, took_s: 185, did: [
     {kind: 'task', task_id: 't-brief', title: 'Approve the October content brief', owner: 'human:ana', at: iso(-3 * hour)},
     {kind: 'link', url: 'https://github.com/ticoteam/tico/pull/18852', title: 'Pricing comparison page', at: iso(-3 * hour)},
     {kind: 'ask', to: 'bot:seo', text: 'Which keywords should the page lead with?', at: iso(-3 * hour)},
     {kind: 'refused', rule: 'identity', text: 'Bots cannot message a person directly', at: iso(-3 * hour)}]}},
];
const turnSteps = {turn_id: 'turn-1', tool_calls: 2, took_s: 185, steps: [
  {kind: 'thinking', tool: '', text: 'Check the Finance numbers before answering.', at: iso(-3 * hour)},
  {kind: 'tool', tool: 'Bash', text: '', at: iso(-3 * hour)},
  {kind: 'tool', tool: 'Read', text: 'failed', at: iso(-3 * hour)},
  {kind: 'said', tool: '', text: 'Handing the brief to Ana.', at: iso(-3 * hour)}]};

// Offline stand-in for marked (a CDN script): paragraphs, [text](url) and GFM's bare-URL links,
// enough for the page's own sanitizing and link rewriting to be what is tested.
const markedStub = () => { window.marked = {parse: s => '<p>' + String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
  .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)|(https?:\/\/[^\s<)]+[^\s<).,;])/g, (m, t, u, bare) => bare
    ? `<a href="${bare}">${bare}</a>` : `<a href="${u}">${t}</a>`) + '</p>'}; };
async function open(browser, viewport, fixture = {}) {
  const page = await browser.newPage({viewport, serviceWorkers: 'block', hasTouch: viewport.width < 760});
  if (fixture.clock) await page.clock.install({time: now});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/*', route => {
    const url = new URL(route.request().url()), p = url.pathname, q = url.searchParams;
    const json = body => route.fulfill({contentType: 'application/json', body: JSON.stringify(body)});
    if (shots && /^fonts\.(googleapis|gstatic)\.com$/.test(url.hostname)) return route.continue();   // icons in the review screenshots
    if (/\/marked\.min\.js$/.test(p)) return route.fulfill({contentType: 'application/javascript', body: `(${markedStub})()`});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/([^/]+\.js)$/);
    if (ui) {
      const file = path.join(__dirname, '..', ui[1]);
      if (fs.existsSync(file)) return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(file, 'utf8')});
    }
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json({id: 'ana', role: 'owner', name: 'Ana', email: 'ana@example.test', cloud: true});
    if (p === '/api/people') return json({people: [{id: 'ana', name: 'Ana'}]});
    if (p === '/api/employees') return json(bots);
    if (p === '/api/issues') return json([]);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: [], schedules: []});
    if (p === '/api/v2/status') return json({bots: [fixture.status || {bot: 'cmo', state: 'idle'}, {bot: 'seo', state: 'crashed', focus: 'The search console token expired.'}]});
    if (p === '/api/v2/needs-you') return json({items: []});
    // The first goals request fails the way a deploy's restart does; the page retries quietly.
    if (p === '/api/v2/goals' && !globalThis.__goalBlip) { globalThis.__goalBlip = true; return route.fulfill({status: 503, contentType: 'application/json', body: '{"error":{"code":"unavailable"}}'}); }
    if (p === '/api/v2/goals') return json({goals: q.get('owner') === 'bot:cmo' ? [goal, {...goal, id: 'g-rank', title: 'Rank for vacation rental cleaning', status: 'yellow', rank: 1}] : [], chain: [], reports: [], company: []});
    if (p === '/api/v2/goals' && q.get('all') === '1') return json({goals: []});
    // The bot's latest update leads its page while unread; History lists them all.
    if (p === '/api/v2/updates' && q.get('bot') === 'cmo') {
      const all = [{id: 'u-cmo-2', bot: 'cmo', kind: 'daily', day: '2026-09-27', body: '- Drafted the October content plan\n- Next: the pricing comparison page',
                    created: iso(-hour), updated: iso(-hour), read: !!globalThis.__updRead?.includes('u-cmo-2'), replies: 0},
                   {id: 'u-cmo-1', bot: 'cmo', kind: 'weekly', day: '2026-09-25', body: '- Shipped four pages this week',
                    created: iso(-50 * hour), updated: iso(-50 * hour), read: true, replies: 0}];
      return json({updates: all.slice(0, Number(q.get('limit') || 40)), missed: [], unread: 0, next_before: null, today: {}});
    }
    if (p === '/api/v2/updates/read') { const b = JSON.parse(route.request().postData() || '{}'); globalThis.__updRead = [...(globalThis.__updRead || []), ...(b.ids || [])]; return json({marked: (b.ids || []).length, read: true}); }
    if (p === '/api/v2/goals/g-signups' && route.request().method() === 'POST') {
      globalThis.__goalEdit = JSON.parse(route.request().postData() || '{}');
      return json({goal: {...goal, ...globalThis.__goalEdit}});
    }
    if (p === '/api/v2/goals/g-signups') return json({goal});
    if (p === '/api/v2/turns/turn-1/steps') return json(turnSteps);
    const gone = p.match(/^\/api\/v2\/routines\/([^/]+)\/delete$/);
    if (gone) { for (const b of bots) b.schedules = (b.schedules || []).filter(r => r.id !== gone[1]); return json({routine: {id: gone[1]}}); }
    // Every file comes back the way production serves it: a sandboxed octet-stream download.
    if (p === '/api/v2/files/img-1') return route.fulfill({contentType: 'application/octet-stream', headers: {'Content-Disposition': "attachment; filename*=UTF-8''shot.png"}, body: PNG});
    const one = p.match(/^\/api\/v2\/tasks\/([^/]+)$/);
    if (one) return json({task: tasks.find(t => t.id === one[1])});
    const list = fixture.tasks || tasks;
    if (p === '/api/v2/tasks') return json({tasks: q.get('owner') === 'cmo' ? list.filter(t => t.owner === 'bot:cmo') : q.get('requester') === 'cmo' ? list.filter(t => t.requester === 'bot:cmo') : []});
    // The first chat lookup fails the way a phone on a weak signal does; the page retries, and it
    // asks for this bot's chat directly (chat_with), never scanning every conversation.
    if (p === '/api/v2/conversations' && q.get('chat_with') === 'cmo' && !globalThis.__convBlip) { globalThis.__convBlip = true; return route.fulfill({status: 503, contentType: 'application/json', body: '{"error":{"code":"unavailable"}}'}); }
    if (p === '/api/v2/conversations' && q.get('chat_with')) globalThis.__chatWith = q.get('chat_with');
    if (p === '/api/v2/conversations') return json({conversations: [{id: 'cmo-chat', kind: 'chat', scope: 'personal', participants: ['human:ana', 'bot:cmo']}]});
    if (p.endsWith('/snapshot')) return json({messages: fixture.messages || messages, execution: fixture.execution || null});
    if (p.endsWith('/watch') && fixture.messages) return;   // held open: the snapshot above is the whole story
    if (p.endsWith('/watch')) return route.fulfill({contentType: 'text/event-stream', body: ': fixture\n\n'});
    return json({});
  });
  return {page, errors};
}
// An 800x600 red PNG: what Ana pastes into the chat.
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAyAAAAJYCAIAAAAVFBUnAAAIyElEQVR42u3WMQ0AAAjAsPk3DSYIV5Mq2LWmAAA4JAEAgMECADBYAAAGCwAAgwUAYLAAAAwWAAAGCwDAYAEAGCwAAAwWAIDBAgAwWAAABgsAAIMFAGCwAAAMFgAABgsAwGABABgsAAAMFgCAwQIAMFgAABgsAACDBQBgsAAADBYAAAYLAMBgAQAYLAAADBYAgMECADBYAAAYLAAAgwUAYLAAADBYAAAGCwDAYAEAGCwAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAwWAAABgsAwGABACABAIDBAgAwWAAABgsAAIMFAGCwAAAMFgAABgsAwGABABgsAAAMFgCAwQIAMFgAAAYLAACDBQBgsAAADBYAAAYLAMBgAQAYLAAADBYAgMECADBYAAAYLAAAgwUAYLAAAAwWAAAGCwDAYAEAGCwAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAwWAAABgsAwGABABgsAAAMFgCAwQIAMFgAABgsAACDBQBgsAAAMFgAAAYLAMBgAQBgsAAADBYAgMECADBYAAAYLAAAgwUAYLAAADBYAAAGCwDAYAEAYLAAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAwWAAABgsAwGABAGCwAAAMFgCAwQIAwGABABgsAACDBQBgsAAAMFgAAAYLAMBgAQBgsAAADBYAgMECAMBgAQAYLAAAgwUAgMECADBYAAAGCwDAYAEAYLAAAAwWAIDBAgDAYAEAGCwAAIMFAIDBAgAwWAAABgsAAIMFAGCwAAAMFgCAwQIAwGABABgsAACDBQCAwQIAMFgAAAYLAACDBQBgsAAADBYAgMECAMBgAQAYLAAAgwUAgMECADBYAAAGCwAAgwUAYLAAAAwWAAAGCwDAYAEAGCwAAIMFAIDBAgAwWAAABgsAAIMFAGCwAAAMFgAABgsAwGABABgsAAAMFgCAwQIAMFgAAAYLAACDBQBgsAAADBYAAAYLAMBgAQAYLAAADBYAgMECADBYAAAYLAAAgwUAYLAAAAwWAAAGCwDAYAEAGCwAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAMlgQAAAYLAMBgAQAYLAAADBYAgMECADBYAAAYLAAAgwUAYLAAADBYAAAGCwDAYAEAGCwAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAwWAAABgsAwGABAGCwAAAMFgCAwQIAMFgAABgsAACDBQBgsAAAMFgAAAYLAMBgAQBgsAAADBYAgMECAMBgAQAYLAAAgwUAYLAAADBYAAAGCwDAYAEAYLAAAAwWAIDBAgDAYAEAGCwAAIMFAIAEAAAGCwDAYAEAGCwAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAwWAAABgsAwGABABgsAAAMFgCAwQIAMFgAABgsAACDBQBgsAAAMFgAAAYLAMBgAQBgsAAADBYAgMECADBYAAAYLAAAgwUAYLAAADBYAAAGCwDAYAEAYLAAAAwWAIDBAgDAYAEAGCwAAIMFAGCwAAAwWAAABgsAwGABAGCwAAAMFgCAwQIAwGABABgsAACDBQCABAAABgsAwGABABgsAAAMFgCAwQIAMFgAABgsAACDBQBgsAAAMFgAAAYLAMBgAQAYLAAADBYAgMECADBYAAAYLAAAgwUAYLAAADBYAAAGCwDAYAEAYLAAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAwWAAABgsAwGABAGCwAAAMFgCAwQIAwGABABgsAACDBQBgsAAAMFgAAAYLAMBgAQBgsAAADBYAgMECAMBgAQAYLAAAgwUAgMECADBYAAAGCwDAYAEAYLAAAAwWAIDBAgDAYAEAGCwAAIMFAIDBAgAwWAAABgsAwGABAGCwAAAMFgCAwQIAwGABABgsAACDBQCAwQIAMFgAAAYLAACDBQBgsAAADBYAgMECAMBgAQAYLAAAgwUAgMECADBYAAAGCwAAgwUAYLAAAAwWAAAGCwDAYAEAGCwAAIMFAIDBAgAwWAAABgsAAIMFAGCwAAAMFgAABgsAwGABABgsAAAMFgCAwQIAMFgAAAYLAACDBQBgsAAADBYAAAYLAMBgAQAYLAAADBYAgMECADBYAAAGCwAAgwUAYLAAAAwWAAAGCwDAYAEAGCwAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAMFgAABgsAwGABABgsAAAMFgCAwQIAMFgAABgsAACDBQBgsAAAMFgAAAYLAMBgAQAYLAAADBYAgMECADBYAAAYLAAAgwUAYLAAADBYAAAGCwDAYAEAYLAAAAwWAIDBAgAwWAAAGCwAAIMFAGCwAAAwWAAABgsAwGABAGCwAAAMFgCAwQIAMFgSAAAYLAAAgwUAYLAAADBYAAAGCwDAYAEAYLAAAAwWAIDBAgDAYAEAGCwAAIMFAGCwAAAwWAAABgsAwGABAGCwAAAMFgCAwQIAwGABABgsAACDBQCAwQIAMFgAAAYLAMBgAQBgsAAADBYAgMECAMBgAQAYLAAAgwUAgMECADBYAAAGCwAAgwUAYLAAAAwWAIDBAgDAYAEAGCwAAIMFAIDBAgAwWAAABgsAAIMFAGCwAAAMFgAAEgAAGCwAAIMFAGCwAAAwWAAABgsAwGABAGCwAAAMFgCAwQIAwGABABgsAACDBQBgsAAAMFgAAAYLAMBgAQBgsAAADBYAgMECAMBgAQAYLAAAgwUAgMECADBYAAAGCwDAYAEAYLAAAAwWAIDBAgDAYAEAGCwAAIMFAIDBAgAwWAAABgsAAIMFAGCwAAAMFgCAwQIAwGABABgsAACDBQCAwQIAMFgAAAYLAACDBQBgsAAADBYAABIAABgsAACDBQBgsAAAMFgAAAYLAMBgAQBgsAAADBYAgMECAMBgAQAYLAAAgwUAYLAAADBYAAAGCwDAYAEAYLAAAAwWAIDBAgDAYAEAGCwAAIMFAIDBAgAwWAAABgsAwGABAGCwAAAMFgCAwQIAwGABABgsAACDBQCAwQIAeLSLJxp1r2MNOgAAAABJRU5ErkJggg==', 'base64');
const box = locator => locator.boundingBox();
const until = async (test, ms = 5000) => { for (const end = Date.now() + ms; !test(); ) { if (Date.now() > end) throw new Error('timed out'); await new Promise(r => setTimeout(r, 50)); } };
const shot = async (page, name) => { if (!shots) return; await page.evaluate(() => document.fonts.ready); await page.screenshot({path: path.join(shots, name)}); };
const ready = page => page.waitForFunction(() => BOT?.slug === 'cmo' && V2C?.rendered && document.querySelector('#bot-goal .bot-goal-title'));

// The chat patterns from bot-desk (#524): short links, what is happening to a sent message in the
// reply's place and its 20-minute timeout, the jump-to-latest pill, the composer's height.
const LINKS = 'Shipped in https://github.com/ticoteam/tico/pull/18852 (tracked in https://github.com/ticoteam/tico/issues/524); '
  + 'guide https://example.com/guide.';
const chatter = Array.from({length: 24}, (_, i) => ({id: 'f' + i, from_actor: i % 2 ? 'bot:cmo' : 'human:ana',
  body: i % 2 ? 'Noted; the draft is in the content folder and the numbers match the September report.' : 'And the next section?', created: iso(-5 * hour + i * 60e3)}));
async function chatPatterns(browser, viewport, tag) {
  const sent = {id: 'm-sent', from_actor: 'human:ana', body: 'Can you pull this week’s reviews into the brief?', created: iso(-60e3)};
  const {page, errors} = await open(browser, viewport, {clock: true,
    messages: [...chatter, {id: 'm-links', from_actor: 'bot:cmo', body: LINKS, created: iso(-2 * hour)}, sent],
    execution: {job_id: 'j1', message_id: sent.id, bot: 'cmo', attempt_id: null, state: 'queued', label: 'Saved — queued', text: ''},
    status: {bot: 'cmo', state: 'running', focus: 'Weekly review sweep'}});
  await page.goto('https://tico-ui.test/#/bot/cmo');
  await ready(page);
  const thread = page.locator('#conv-thread');
  // Short links: a mark and the number, the URL in the tooltip; a chosen label stays; others untouched.
  const reply = thread.locator('.conv-run', {hasText: 'Shipped in'});
  assert.deepEqual(await reply.locator('a.ref').evaluateAll(as => as.map(a => [a.className, a.textContent])),
    [['ref ref-pr', '#18852'], ['ref ref-issue', '#524']]);
  assert.match(await reply.locator('a.ref-pr').getAttribute('title'), /tico pull request #18852\nhttps:\/\/github\.com\/ticoteam\/tico\/pull\/18852/);
  assert.equal(await reply.locator('a[href="https://example.com/guide"]').evaluate(a => [a.className, a.textContent].join('|')), '|https://example.com/guide');
  // The line where the reply will appear: quiet dots and one word; the sentence is the tooltip.
  const pending = thread.locator('.thinking');
  await page.waitForFunction(() => /another run/.test(document.querySelector('#conv-thread .thinking')?.title));
  assert.equal((await pending.innerText()).trim(), 'Queued');
  assert.equal(await pending.getAttribute('title'), 'AI CMO is on another run: Weekly review sweep');
  assert.equal(await pending.locator('.typing.wait i').count(), 3);
  await reply.evaluate(el => { const t = el.closest('#conv-thread'); t.scrollTop += el.getBoundingClientRect().top - t.getBoundingClientRect().top - 40; });
  await shot(page, `chat-short-links-${tag}.png`);
  await thread.evaluate(el => { el.scrollTop = el.scrollHeight; });
  await shot(page, `chat-pending-${tag}.png`);
  // The composer grows to a third of the screen (at most 300px) on a desktop, 120px on a phone.
  const box = page.locator('#chat-composer textarea');
  await box.fill(Array.from({length: 40}, (_, i) => 'line ' + i).join('\n'));
  const tall = (await box.boundingBox()).height;
  if (viewport.width > 760) assert(Math.abs(tall - Math.min(300, viewport.height / 3)) <= 2, 'desktop composer cap: ' + tall);
  else assert(Math.abs(tall - 120) <= 2, 'phone composer cap: ' + tall);
  await box.fill('');
  const stubbed = await page.evaluate(() => { const real = window.pillSend; window.SENT = [];
    window.pillSend = P => { window.SENT.push(document.querySelector('#chat-composer textarea').value); };
    window.REAL_PILL_SEND = real; return true; });
  assert(stubbed);
  if (viewport.width > 760) {
    // On a computer Return sends and Shift+Return is a new line.
    await box.fill('first line');
    await box.press('Shift+Enter');
    await box.type('second line');
    assert.equal(await box.inputValue(), 'first line\nsecond line', 'Shift+Return adds a line');
    assert.deepEqual(await page.evaluate(() => window.SENT), [], 'Shift+Return does not send');
    await box.press('Enter');
    assert.deepEqual(await page.evaluate(() => window.SENT), ['first line\nsecond line'], 'Return sends');
  } else {
    // On a phone Return is a new line; three in a row send, without the two blank lines.
    await box.fill('first line');
    await box.press('Enter');
    await box.type('second line');
    assert.equal(await box.inputValue(), 'first line\nsecond line', 'Return adds a line, it does not send');
    await box.press('Enter'); await box.press('Enter');
    assert.equal(await box.inputValue(), 'first line\nsecond line\n\n');
    assert.deepEqual(await page.evaluate(() => window.SENT), [], 'two Returns do not send');
    await box.press('Enter');
    assert.deepEqual(await page.evaluate(() => window.SENT), ['first line\nsecond line'], 'the third Return sends');
    await box.fill('a');
    await box.press('Enter'); await box.type('b'); await box.press('Enter'); await box.press('Enter');
    assert.deepEqual(await page.evaluate(() => window.SENT.length), 1, 'only Returns in a row count');
  }
  await page.evaluate(() => { window.pillSend = window.REAL_PILL_SEND; });
  await box.fill('');
  // iPhone autocorrect: the box asks for it, and typing a character does not
  // collapse and re-measure the box (that re-layout drops iOS's pending correction).
  assert.deepEqual(await box.evaluate(el => [el.getAttribute('autocorrect'), el.getAttribute('autocapitalize'), el.spellcheck]),
    ['on', 'sentences', true]);
  await box.fill('Hello');
  const collapses = await box.evaluate(el => new Promise(done => {
    let seen = false;
    new MutationObserver(list => { if (list.some(m => el.style.height === 'auto')) seen = true; })
      .observe(el, {attributes: true, attributeFilter: ['style']});
    el.value += 'o'; el.dispatchEvent(new Event('input', {bubbles: true}));
    setTimeout(() => done(seen), 50);
  }));
  assert.equal(collapses, false, 'typing does not collapse the composer');
  await box.fill('');
  // Scrolled up, nothing new: no pill. A new reply arrives: "New reply ↓", which takes you down.
  const jump = page.locator('#conv-jump');
  // Scroll up until the page agrees: the cleared composer's resize may scroll it back down once.
  await page.waitForFunction(() => { document.querySelector('#conv-thread').scrollTop = 0; return V2C.followLatest === false; }, null, {polling: 100});
  assert.equal(await jump.isVisible(), false);
  await page.evaluate(() => {
    V2C.messages.push({id: 'm-reply', from_actor: 'bot:cmo', body: 'Pulled 14 reviews into the brief.', created: new Date().toISOString()});
    V2C.live = null; V2C.execution = null;
    v2ChatRender(V2C);
  });
  assert.equal(await jump.innerText(), 'New reply ↓');
  const pill = await jump.boundingBox(), composer = await page.locator('#chat-composer').boundingBox();
  assert(pill.y + pill.height <= composer.y, 'the pill sits above the composer');
  await shot(page, `chat-jump-${tag}.png`);
  await jump.click();
  assert.equal(await jump.isVisible(), false);
  // The pill turns follow-latest on and scrolls; layout (fonts, the composer's resize) may still
  // settle a frame later, so wait for the thread to rest at the bottom rather than read it once.
  await page.waitForFunction(() => { const el = document.querySelector('#conv-thread');
    return V2C.followLatest && el.scrollTop + el.clientHeight >= el.scrollHeight - 2; }, null, {timeout: 3000, polling: 50});
  // Twenty minutes after sending with no reply, the line says so and can be dismissed.
  await page.evaluate(sent => {
    V2C.messages = V2C.messages.filter(m => m.id !== 'm-reply');
    V2C.live = {text: ''}; V2C.execution = {message_id: sent, state: 'queued', label: 'Saved — queued'};
    v2ChatRender(V2C);
  }, sent.id);
  await page.clock.fastForward('20:00');
  await page.waitForFunction(() => /No reply after 20 minutes/.test(document.querySelector('#conv-thread .thinking')?.textContent));
  assert.equal((await pending.innerText()).trim(), 'No reply after 20 minutes · dismiss');
  await shot(page, `chat-no-reply-${tag}.png`);
  await pending.getByRole('button', {name: 'dismiss'}).click();
  assert.equal(await thread.locator('.thinking').count(), 0);
  // Files dragged anywhere over the chat light up the composer and attach when dropped there.
  const drag = (sel, type) => page.locator(sel).first().evaluate((el, type) => {
    const data = new DataTransfer();
    data.items.add(new File(['Synthetic review export'], 'reviews.csv', {type: 'text/csv'}));
    const ev = new DragEvent(type, {bubbles: true, cancelable: true, dataTransfer: data});
    el.dispatchEvent(ev);
    return ev.defaultPrevented;
  }, type);
  const composerPill = page.locator('#chat-composer .p-pill');
  assert.equal(await drag('#conv-thread .conv-run', 'dragenter'), true);
  assert.equal(await composerPill.evaluate(el => el.classList.contains('over') && getComputedStyle(el, '::after').content), '"Drop to attach"');
  await shot(page, `chat-drop-${tag}.png`);
  assert.equal(await drag('#conv-thread .conv-run', 'drop'), true);
  await page.locator('#chat-composer .p-chips').getByText('reviews.csv').waitFor();
  assert.equal(await composerPill.evaluate(el => el.classList.contains('over')), false);
  assert.equal(await drag('body', 'drop'), true, 'a stray drop never opens the file in place of the page');
  assert.deepEqual(errors, []);
  await page.close();
}

// A task the bot closes leaves the Active column beside the chat without a reload (Business
// Development, 2026-09-25: two closed decisions stayed listed until the page was reopened).
async function liveTasks(browser) {
  const live = tasks.map(t => ({...t}));
  const {page, errors} = await open(browser, {width: 1440, height: 900}, {tasks: live});
  await page.goto('https://tico-ui.test/#/bot/cmo');
  await ready(page);
  await page.locator('#t-assigned .trow').first().waitFor();
  assert.equal(await page.locator('#t-open .trow').count(), 2);
  assert.equal(await page.locator('#t-assigned .trow').count(), 1);
  live.find(t => t.id === 't-brief').status = 'closed';
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => document.querySelector('#bot-assigned')?.hidden);
  assert.doesNotMatch(await page.locator('#pane-tasks').innerText(), /Approve the October content brief/);
  for (const t of live) if (t.status !== 'done') t.status = 'closed';
  await page.evaluate(() => refresh());
  await page.waitForFunction(() => !document.querySelector('#t-open .trow'));
  assert.equal(await page.locator('#t-open').innerText(), 'No active tasks.', 'no per-bot "Give … a task" line; + New is enough');
  assert.deepEqual(errors, []);
  await page.close();
}

// An image in the chat is a thumbnail that opens full size, not "image.png".
async function chatImages(browser) {
  const withImage = [...messages, {id: 'm-img', from_actor: 'human:ana', body: 'This one', created: iso(-60e3),
    refs: {attachments: [{id: 'img-1', name: 'image.png', content_type: 'image/png', size: 120},
                         {id: 'doc-1', name: 'notes.pdf', content_type: 'application/pdf', size: 900}]}}];
  const {page, errors} = await open(browser, {width: 1440, height: 900}, {messages: withImage});
  await page.goto('https://tico-ui.test/#/bot/cmo');
  await ready(page);
  const thumb = page.locator('#conv-thread .chat-thumb.ready');
  await thumb.waitFor();
  assert.equal(await thumb.locator('img').evaluate(img => img.naturalWidth), 800, 'the thumbnail shows the image itself');
  const size = await thumb.boundingBox();
  assert(size.width <= 122 && size.height <= 92, 'a small thumbnail');
  assert.equal(await page.locator('#conv-thread a.pill', {hasText: 'notes.pdf'}).count(), 1, 'other files stay links');
  assert.equal(await page.locator('#conv-thread', {hasText: 'image.png'}).locator('a.pill').filter({hasText: 'image.png'}).count(), 0);
  await thumb.click();
  // It opens in the one viewer.
  const box = page.locator('#doc-viewer[open] .viewer-img');
  await box.waitFor();
  assert((await box.boundingBox()).width > size.width, 'clicking opens it large');
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('#doc-viewer[open]').count(), 0);
  assert.deepEqual(errors, []);
  await page.close();
}

// A deleted routine leaves the bot page at once, not after a reload.
async function routineDelete(browser) {
  const {page, errors} = await open(browser, {width: 1440, height: 900});
  page.on('dialog', d => d.accept());
  await page.goto('https://tico-ui.test/#/bot/cmo/more');
  await page.locator('#bot-routines-list').waitFor();
  const card = page.locator('#bot-routines-list');
  assert.match(await card.innerText(), /Weekday content plan/);
  await card.locator('[data-expand-routine="r-plan"]').click();
  await card.locator('[data-delete-routine="r-plan"]').click();
  await page.waitForFunction(() => !/Weekday content plan/.test(document.querySelector('#bot-routines-list')?.innerText || ''));
  assert.match(await card.innerText(), /Pull quotes from new recordings/, 'the other routine stays');
  assert.deepEqual(errors, []);
  await page.close();
}

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try {
    if (shots) fs.mkdirSync(shots, {recursive: true});
    // Desktop: the goal on top, chat left, tasks right, routines under the tasks.
    const {page, errors} = await open(browser, {width: 1440, height: 900});
    await page.goto('https://tico-ui.test/#/bot/cmo');
    await ready(page);
    await page.locator('#t-open .trow').first().waitFor();
    // Its unread latest update leads the page, dismissable; History has them all.
    const latest = page.locator('#bot-update');
    await latest.locator('.upd-body').waitFor();
    assert.match(await latest.innerText(), /Latest update[\s\S]*Drafted the October content plan/);
    if (shots) await page.screenshot({path: path.join(shots, 'bot-latest-update.png')});
    await latest.locator('[data-bot-update-dismiss]').click();
    assert.equal(await latest.isVisible(), false);
    for (const end = Date.now() + 3000; !(globalThis.__updRead || []).includes('u-cmo-2') && Date.now() < end;) await new Promise(r => setTimeout(r, 50));
    assert((globalThis.__updRead || []).includes('u-cmo-2'), 'dismissing marks it read');
    await page.locator('#bot-history-btn').click();
    await page.waitForFunction(() => location.hash === '#/bot/cmo/history' && !document.querySelector('#pane-history').hidden);
    await page.locator('#bot-history .bot-history-item').nth(1).waitFor();
    assert.match(await page.locator('#bot-history').innerText(), /Drafted the October content plan[\s\S]*Week in review[\s\S]*Shipped four pages/);
    assert.equal(await page.locator('#bot-work').isVisible(), false);
    await page.evaluate(() => { location.hash = '#/bot/cmo'; });
    await page.waitForFunction(() => BOT?.split && !document.querySelector('#bot-work').hidden);
    const head = page.locator('#bot-goal');
    assert.equal(await head.getAttribute('data-status'), 'set', 'a failed first request is retried, never shown');
    assert(!/Could not load/.test(await page.locator('body').innerText()));
    assert.equal(globalThis.__convBlip, true, 'the first chat lookup failed');
    assert.equal(globalThis.__chatWith, 'cmo');
    assert.match(await page.locator('#conv-thread').innerText(), /Where are we on the pricing page\?/, 'a failed first lookup is retried, never "Nothing yet"');
    // Before it has loaded, or while it cannot, the thread says so; "Nothing yet" is only for a loaded, empty chat.
    assert.deepEqual(await page.evaluate(() => {
      const say = over => { const was = {...V2C}; Object.assign(V2C, {messages: [], live: null}, over); v2ChatRender(V2C);
        const t = document.querySelector('#conv-thread').innerText; Object.assign(V2C, was); v2ChatRender(V2C); return t; };
      return [say({loaded: false, failed: false}), say({loaded: false, failed: true}), say({loaded: true, failed: false})];
    }), ['Loading the thread…', 'Could not load the conversation yet; trying again…', 'Nothing yet. Say something below.']);
    assert.match(await head.innerText(), /Double organic signups by December/);
    assert.equal((await head.innerText()).replace(/\s+/g, ' ').trim(), 'Double organic signups by December',
      'one quiet line: the goal in plain words, no colour or reading');
    assert.equal(await head.locator('.goal-dot').count(), 0);
    assert((await box(head)).height <= 24, 'no taller than a line');
    assert.equal(await head.locator('a.bot-goal-main').getAttribute('href'), '#/goals/g-signups');
    assert.equal(await page.locator('#bot-alert').innerText(), '', 'an idle bot shows no status');
    const chat = await box(page.locator('#pane-chat')), taskCol = await box(page.locator('#pane-tasks'));
    assert(chat && taskCol, 'chat and tasks are both on screen');
    assert(taskCol.x >= chat.x + chat.width, 'tasks sit to the right of chat');
    assert((await box(page.locator('#chat-composer'))).y < 900, 'the composer is in view');
    assert.match(await page.locator('#conv-thread').innerText(), /checking the numbers with Finance/);
    // The chat is the page: no card border, no Idle/Private pills.
    assert.equal(await page.locator('#conv').evaluate(el => getComputedStyle(el).borderTopWidth), '0px');
    assert.equal(await page.locator('#conv-state').isVisible(), false);
    assert.equal(await page.locator('#conv-access').isVisible(), false);
    // What the turn did, as muted rows in words (#524): the task it was about, what it handed out,
    // filed, asked and was refused; no id anywhere. Its steps fold to one line and load on opening.
    const did = page.locator('#conv-thread .run-did');
    assert.deepEqual(await did.locator('.did').evaluateAll(rows => rows.map(r => [...r.children].map(c => c.textContent).join(' '))), [
      '↳ task · Publish the pricing comparison page', '↳ gave you a task · Approve the October content brief',
      '↳ filed #18852 Pricing comparison page', '↳ asked AI SEO · Which keywords should the page lead with?',
      '✗ refused · Bots cannot message a person directly']);
    assert.doesNotMatch(await page.locator('#conv-thread').innerText(), /t-pricing|t-brief|turn-1|88c1a455/);
    assert.equal(await page.locator('#conv-thread .fchip').count(), 0);
    assert.equal(await did.locator('a.did', {hasText: '#18852'}).getAttribute('href'), 'https://github.com/ticoteam/tico/pull/18852');
    assert.equal(await did.locator('a.did', {hasText: 'asked AI SEO'}).getAttribute('href'), '#/bot/seo');
    const stepsLine = did.locator('details.run-steps');
    assert.equal(await stepsLine.locator('summary').innerText(), '4 steps · 2 tool calls · 3m');
    await stepsLine.locator('summary').click();
    await stepsLine.locator('.step-tool', {hasText: 'Bash'}).waitFor();
    assert.deepEqual(await stepsLine.locator('.steps-list > *').evaluateAll(rows => rows.map(r => r.innerText.replace(/\s+/g, ' ').trim())),
      ['Thinking', 'Bash', 'Read failed', 'said Handing the brief to Ana.']);
    await stepsLine.locator('.think summary').click();
    assert.match(await stepsLine.locator('.think').innerText(), /Check the Finance numbers/);
    await page.evaluate(() => v2ChatRender(V2C));
    assert.equal(await stepsLine.evaluate(el => el.open), true, 'stays open across a redraw');
    assert.match(await stepsLine.locator('.steps-list').innerText(), /Read\s+failed/);
    await shot(page, 'chat-run-desktop.png');
    await did.getByRole('button', {name: /task · Publish the pricing comparison page/}).click();
    await page.locator('dialog[data-task="t-pricing"][open]').waitFor();
    await page.keyboard.press('Escape');
    // One send arrow; nothing offers "Send as task". Live voice was removed.
    const composer = page.locator('#chat-composer');
    assert.equal(await composer.locator('.p-live, .p-live-dock').count(), 0, 'Live voice was removed');
    assert.equal(await composer.getByRole('button', {name: 'Send', exact: true}).count(), 1);
    assert.equal(await composer.locator('.p-caret, .p-menu').count(), 0);
    assert.equal(await page.getByText('Send as task').count(), 0);
    // Tasks: Active is the bot's own work; what it asked of others,
    // a task it filed for you included, is its own section. Neither title carries a count. A long title wraps to two
    // lines beside the name.
    assert.equal((await page.locator('#pane-tasks .card.tasks h2').first().innerText()).replace(/\s+/g, ' ').trim(), 'Active');
    assert.equal((await page.locator('#bot-assigned h2').innerText()).replace(/\s+/g, ' ').trim(), 'Assigned to others');
    assert.equal(await page.locator('#t-assigned .trow', {hasText: 'Approve the October content brief'}).count(), 1);
    // Each task is its state icon, its title (two lines at most) and the holder's avatar only.
    const states = await page.locator('#t-open .trow summary .st-ic, #t-assigned .trow summary .st-ic').evaluateAll(els => els.map(el => el.getAttribute('aria-label')));
    // The bot is idle in this fixture: a task marked doing shows a still ring, not the spinner the
    // org rail reserves for a bot running right now.
    assert.deepEqual(states.slice().sort(), ['In progress, not running now', 'In progress, not running now', 'Needs you']);
    assert.equal(await page.evaluate(() => { S.v2.status.cmo = {bot: 'cmo', state: 'running', task_id: 't-pricing'};
      const d = document.createElement('div'); d.innerHTML = taskStateIcon({status: 'doing', owner: 'bot:cmo', id: 't-pricing'});
      const other = document.createElement('div'); other.innerHTML = taskStateIcon({status: 'doing', owner: 'bot:cmo', id: 't-audit'});
      S.v2.status.cmo = {bot: 'cmo', state: 'idle'};
      return d.firstElementChild.className + '|' + other.firstElementChild.className; }), 'st-ic st-doing|st-ic st-doing-idle');
    // Every icon name the page writes is in the font's icon_names, or it shows as letters.
    const allowed = new Set(fs.readFileSync(path.join(__dirname, '../vendor/fonts/icons.txt'), 'utf8').split('\n').filter(Boolean));
    const used = [...html.matchAll(/class="nav-icon[^"]*"[^>]*>([a-z_]+)</g)].map(m => m[1]);
    assert.deepEqual(used.filter(n => !allowed.has(n)), [], 'icons missing from ui/vendor/fonts/icons.txt (run scripts/build-icon-font.py)');
    const brief = page.locator('#t-assigned .trow', {hasText: 'Approve the October content brief'});
    assert.equal(await brief.locator('.st-ic').innerText(), '!');
    assert.equal(await brief.locator('.who-av').getAttribute('title'), 'You');
    assert.equal(await brief.locator('.tags').isVisible(), false, 'no name chip, just the avatar');
    assert.equal(await brief.locator('.tnum').isVisible(), false);
    for (const row of await page.locator('#t-open .trow summary, #t-assigned .trow summary').all()) {
      const lines = await row.locator('.ttl').evaluate(el => Math.round(el.getBoundingClientRect().height / parseFloat(getComputedStyle(el).lineHeight)));
      assert(lines <= 2, 'a task is two lines at most');
      assert((await row.boundingBox()).height <= 56, 'rows stay small');
    }
    assert.equal(await page.locator('#t-open .v2-group, #t-open h3').count(), 0);
    assert.equal(await page.locator('#t-open .trow').count(), 2);
    const longRow = page.locator('#t-open .trow', {hasText: 'Rewrite the vacation rental'});
    const title = await box(longRow.locator('.ttl')), who = await box(longRow.locator('.who-av'));
    const lineHeight = await longRow.locator('.ttl').evaluate(el => parseFloat(getComputedStyle(el).lineHeight));
    assert(title.height > lineHeight * 1.5 && title.height < lineHeight * 2.5, 'the long title wraps to two lines');
    assert(title.x + title.width <= who.x, 'the title never runs under the avatar');
    assert.equal(await page.locator('#pane-tasks .bot-done').evaluate(el => el.open), false, 'Done is folded away');
    // Routines last: a cron one in words with its zone and next run, an event one; a quiet repeat
    // icon and no count.
    const recurring = page.locator('#bot-recurring');
    assert((await box(page.locator('#bot-assigned'))).y > (await box(page.locator('#pane-tasks .card.tasks').first())).y);
    assert((await box(recurring)).y > (await box(page.locator('#pane-tasks .bot-done'))).y, 'Recurring comes last');
    assert.equal(await recurring.locator('header .cnt').count(), 0);
    assert.equal(await recurring.locator('header .bot-recurring-ic').innerText(), 'repeat');
    const routineText = await recurring.innerText();
    assert.match(routineText, /Weekday content plan\s*Weekdays at 08:00 \(America\/Los_Angeles\)\s*in 14\.0h/);
    assert.match(routineText, /Pull quotes from new recordings\s*When a meeting is imported\s*on event/);
    await shot(page, 'bot-page-desktop.png');

    // An old Tasks link lands on the same combined view; More holds the settings and Docs.
    await page.goto('https://tico-ui.test/#/bot/cmo/tasks');
    await page.waitForFunction(() => BOT?.tab === 'tasks');
    assert.equal(await page.locator('#pane-chat').isVisible(), true);
    assert.equal(await page.locator('#pane-tasks').isVisible(), true);
    await page.locator('#bot-more-btn').click();
    await page.waitForFunction(() => location.hash === '#/bot/cmo/more' && BOT?.tab === 'more');
    assert.equal(await page.locator('#bot-work').isVisible(), false);
    assert.equal(await page.locator('#pane-more').isVisible(), true);
    assert.equal(await page.locator('#pane-docs').isVisible(), true);
    // More's Goals card is the same goals as plain lines, each edited in place,
    // with a link icon for the goal it supports. No colour, description or Edit button.
    const goalsCard = page.locator('#bot-goals-card');
    await goalsCard.locator('[data-goal-ed]').first().waitFor();
    assert.equal(await goalsCard.locator('[data-goal-ed]').count(), 2);
    assert.equal(await goalsCard.locator('.goal-dot, textarea, [data-goal-edit]').count(), 0);
    await shot(page, 'bot-more-goals.png');
    const words = goalsCard.locator('[data-goal-ed="g-signups"] .goal-ed-text');
    assert.equal(await words.inputValue(), goal.title);
    await words.fill('Double weekly signups');
    await words.press('Enter');
    await until(() => globalThis.__goalEdit?.title);
    assert.deepEqual(globalThis.__goalEdit, {title: 'Double weekly signups'});
    // The link icon picks the goal it supports; never itself.
    await goalsCard.locator('[data-goal-ed="g-signups"] .goal-ed-link').click();
    const pick = goalsCard.locator('[data-goal-ed="g-signups"] .goal-ed-pick');
    assert.equal(await pick.locator('option[value="g-signups"]').count(), 0);
    await pick.selectOption('g-rank');
    await until(() => globalThis.__goalEdit?.parent_id);
    assert.deepEqual(globalThis.__goalEdit, {parent_id: 'g-rank'});
    await page.locator('#bot-back').click();
    await page.waitForFunction(() => location.hash === '#/bot/cmo' && BOT?.split);

    // A bot with no goal says so and offers to set one; a crashed bot says it is crashed.
    await page.goto('https://tico-ui.test/#/bot/seo');
    await page.waitForFunction(() => BOT?.slug === 'seo' && document.querySelector('#bot-goal')?.dataset.status === 'none');
    assert.match(await page.locator('#bot-goal').innerText(), /^No goal · Set goal$/);
    assert.match(await page.locator('#bot-alert').innerText(), /Crashed/);
    await shot(page, 'bot-page-no-goal.png');
    await page.locator('#bot-goal-set').click();
    await page.locator('#bot-goal .goal-add-text').waitFor();
    await page.keyboard.press('Escape');

    // The rail: Tasks, Goals, Docs, Market, Meetings, then Org above Message bots. No Menu.
    await page.goto('https://tico-ui.test/#/tasks');
    await page.locator('#tree .node').first().waitFor();
    assert.equal(await page.locator('#app-menu, #app-menu-btn').count(), 0, 'the top-left Menu is gone');
    const railOrder = () => page.locator('.side-scroll').evaluate(nav => [...nav.querySelectorAll('.nav-link[data-nav], .section-toggle')]
      .filter(el => !el.hidden && !el.closest('[hidden]'))
      .map(el => el.matches('.section-toggle') ? el.textContent.trim().replace(/\W+$/, '') : [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join('').trim()));
    await page.evaluate(() => { $('#nav-inboxes-section').hidden = false; });   // no message bots in these fixtures; the order still holds
    assert.deepEqual(await railOrder(), ['Updates', 'Tasks', 'Goals', 'Docs', 'Market', 'Meetings', 'Org', 'Message bots']);
    await page.evaluate(() => { $('#nav-inboxes-section').hidden = true; });
    assert.equal(await page.locator('.side-scroll #nav-docs-librarian').getAttribute('href'), '#/bot/doc-updater/more');
    assert.equal(await page.locator('.side-scroll #nav-market-librarian').count(), 1, 'the Market Analyst gear stays beside Market');
    await shot(page, 'rail-desktop.png');
    // The account menu holds Integrations, Runs, Changelog and Settings, in that order.
    await page.locator('#account').click();
    const account = page.locator('#account-menu');
    assert.equal(await account.isVisible(), true);
    assert.deepEqual((await account.locator('.nav-link:visible').allInnerTexts()).map(t => t.replace(/^\S+\s*/, '').trim()),
      ['Integrations', 'Runs', 'Changelog', 'Settings']);
    assert.equal(await account.locator('#download-app').count(), 1, 'Download for Mac lives here when a build is published');
    await shot(page, 'account-menu-open.png');
    await account.locator('[data-nav="runs"]').click();
    await page.waitForFunction(() => location.hash === '#/runs');
    assert.equal(await account.isVisible(), false);
    // Search still finds the account pages.
    assert.deepEqual(await page.evaluate(() => searchEntries().filter(e => e.kind === 'page').map(e => e.label)),
      ['Updates', 'Tasks', 'Goals', 'Docs', 'Market', 'Meetings', 'Integrations', 'Runs', 'Changelog', 'Settings']);
    assert.deepEqual(errors, []);
    await page.close();

    // Phone: one top line, the goal as one line, Chat by default, no bottom bar, composer at the bottom.
    const phone = await open(browser, {width: 390, height: 844});
    const p = phone.page;
    await p.goto('https://tico-ui.test/#/tasks');
    await p.goto('https://tico-ui.test/#/bot/cmo');
    await ready(p);
    const line = await Promise.all(['#bot-back-arrow', '.bot-ident .av', '.bot-ident h1', '#btabs [data-bt="chat"]', '#btabs [data-bt="more"]']
      .map(sel => box(p.locator(sel).first())));
    const mid = b => b.y + b.height / 2;
    assert(line.every(b => b && Math.abs(mid(b) - mid(line[0])) < 14), 'back, icon, name and the tabs share one line');
    assert(line.every((b, i) => i === 0 || b.x >= line[i - 1].x), 'in that order, left to right');
    const tabs = p.locator('#btabs [data-bt]');
    assert.deepEqual(await tabs.evaluateAll(els => els.map(e => e.getAttribute('aria-label'))), ['Chat', 'Tasks', 'History', 'More']);
    // Under the bot's name, what needs you (pinned) or its active tasks, ticker-style.
    const ticker = p.locator('#bot-ticker');
    await ticker.locator('.bot-ticker-needs').waitFor();
    assert.match(await ticker.innerText(), /Needs you: Approve the October content brief/);
    await p.evaluate(() => { BOT_TICKER.needs = []; BOT_TICKER.i = 0; botTickerPaint(); });
    assert.match(await ticker.innerText(), /1\/2/, 'the active tasks cycle, one at a time');
    await p.evaluate(() => { BOT_TICKER.i = 1; botTickerPaint(true); });
    assert.match(await ticker.innerText(), /2\/2/);
    assert.deepEqual(await tabs.evaluateAll(els => els.map(e => e.querySelector('.bt-icon').textContent)), ['chat_bubble', 'task_alt', 'history', 'menu'],
      'on a phone the tabs are icons: a chat bubble, a check, the clock for History and the menu for More');
    assert(line[4].x + line[4].width > 390 - 24, 'the icons sit on the right edge');
    assert.equal(await p.locator('#btabs [data-bt="chat"]').getAttribute('aria-selected'), 'true');
    assert.equal(await p.locator('#bot-alert').isVisible(), false);
    assert.equal(await p.locator('#mobile-nav').isVisible(), false, 'no bottom bar on a bot page');
    assert.equal(await p.locator('#bot-goal').isVisible(), false, 'no goal in the top line on a phone');
    const composerBox = await box(p.locator('#chat-composer'));
    assert(composerBox.y + composerBox.height >= 842 && composerBox.width >= 388, 'the composer sits on the bottom edge, full width');
    assert.equal(await p.locator('#pane-chat').isVisible(), true);
    assert.equal(await p.locator('#pane-tasks').isVisible(), false);
    assert.equal(await p.getByText('Send as task').count(), 0);
    // What needs you: titles only, about two lines tall, with an X that keeps it dismissed.
    const needs = p.locator('#bot-chat-tasks');
    assert.equal(await needs.isVisible(), true);
    const needsText = await needs.innerText();
    assert(!/Needs you|All tasks|ago/.test(needsText), 'no heading, link or age: ' + needsText);
    assert((await box(needs)).height <= 56, 'about two lines tall');
    await shot(p, 'bot-page-mobile.png');
    await p.locator('#conv-thread details.run-steps summary').click();
    await p.locator('#conv-thread .step-tool', {hasText: 'Bash'}).waitFor();
    const runBox = await box(p.locator('#conv-thread .run-did'));
    assert(runBox.x + runBox.width <= 390, 'the rows fit a phone');
    await shot(p, 'chat-run-phone.png');
    await p.locator('.bot-chat-tasks-x').click();
    assert.equal(await needs.isVisible(), false, 'dismissed');
    await p.reload(); await ready(p);
    assert.equal(await p.locator('#bot-chat-tasks').isVisible(), false, 'stays dismissed while the same things need you');
    // The goal lives in More on a phone.
    await p.locator('#btabs [data-bt="more"]').click();
    await p.locator('#pane-more #bot-goal').waitFor();
    assert.match(await p.locator('#pane-more #bot-goal').innerText(), /Double organic signups by December/);
    await shot(p, 'bot-page-mobile-more.png');
    // Tasks: Active, Assigned to others, then the routines.
    await p.locator('#btabs [data-bt="tasks"]').click();
    await p.waitForFunction(() => location.hash === '#/bot/cmo/tasks' && BOT?.tab === 'tasks');
    await p.locator('#t-open .trow').first().waitFor();
    assert.equal(await p.locator('#pane-chat').isVisible(), false);
    assert.equal(await p.locator('#t-open h3').count(), 0);
    assert((await box(p.locator('#bot-recurring'))).y > (await box(p.locator('#bot-assigned'))).y, 'Recurring last on a phone too');
    await shot(p, 'bot-page-mobile-tasks.png');
    // Back always goes home (Tasks), even when the bot was opened from another page.
    await p.evaluate(() => { location.hash = '#/goals'; });
    await p.waitForFunction(() => location.hash === '#/goals');
    await p.evaluate(() => { location.hash = '#/bot/cmo'; });
    await p.waitForFunction(() => BOT?.slug === 'cmo' && document.body.classList.contains('bot-page'));
    await p.locator('#bot-back-arrow').click();
    await p.waitForFunction(() => location.hash === '#/updates', null, {timeout: 5000});   // home is Updates
    await p.evaluate(() => { location.hash = '#/tasks'; });
    await p.waitForFunction(() => location.hash === '#/tasks' && TASKS_ST);
    assert.equal(await p.locator('#mobile-nav').isVisible(), true);
    // Org, left of Search, pops the bots up: the one just visited nearest the
    // thumb, then the ones that need you (AI SEO is crashed). Fast: only transform and opacity move.
    assert.deepEqual(await p.locator('#mobile-nav .mobile-nav-label').allInnerTexts(), ['Org', 'Search', 'Updates', 'More'],
      'Updates takes Tasks\' place on the phone; Tasks is in More');
    await p.locator('#mobile-org').click();
    await p.locator('#org-fan.open').waitFor();
    assert.deepEqual(await p.locator('#org-fan [data-org-bot]').evaluateAll(els => els.map(el => el.dataset.orgBot)), ['cmo', 'seo']);
    const [cmoBox, seoBox] = [await box(p.locator('[data-org-bot="cmo"]')), await box(p.locator('[data-org-bot="seo"]'))];
    assert(cmoBox.y > seoBox.y, 'the most recent bot is lowest, nearest the Org button');
    // No animation, it is simply there.
    assert.deepEqual(await p.locator('[data-org-bot="cmo"]').evaluate(el => [getComputedStyle(el).transitionDuration, getComputedStyle(el).opacity, getComputedStyle(el).transform]), ['0s', '1', 'none']);
    // Tapping Org again closes it, and so does tapping where the Org button sits under the backdrop.
    const orgAt = await box(p.locator('#mobile-org'));
    await p.mouse.click(orgAt.x + orgAt.width / 2, orgAt.y + orgAt.height / 2);
    await p.waitForFunction(() => document.querySelector('#org-fan').hidden);
    await p.locator('#mobile-org').click();
    await p.locator('#org-fan.open').waitFor();
    await p.waitForTimeout(250);
    // Easy to tap: tall rows with room between them.
    const [cmoTap, seoTap] = [await box(p.locator('[data-org-bot="cmo"]')), await box(p.locator('[data-org-bot="seo"]'))];
    assert(cmoTap.height >= 52 && seoTap.height >= 52, 'tall enough to tap: ' + cmoTap.height);
    assert(cmoTap.y - (seoTap.y + seoTap.height) >= 12, 'spread out');
    await shot(p, 'org-fan-phone.png');
    await p.locator('[data-org-bot="seo"]').click();
    await p.waitForFunction(() => location.hash === '#/bot/seo' && document.querySelector('#org-fan').hidden && BOT?.slug === 'seo');
    await p.goBack();
    await p.waitForFunction(() => location.hash === '#/tasks' && TASKS_ST);
    await p.locator('#mobile-org').click();
    await p.locator('#org-fan.open').waitFor();
    assert.deepEqual(await p.locator('#org-fan [data-org-bot]').evaluateAll(els => els.map(el => el.dataset.orgBot)), ['seo', 'cmo'],
      'the bot just visited moves to the bottom');
    await p.locator('#org-fan').click({position: {x: 300, y: 40}});
    await p.waitForFunction(() => document.querySelector('#org-fan').hidden);
    // More opens the rail as it is on a desktop, nothing folded: even a section folded earlier opens.
    await p.evaluate(() => { localStorage.setItem('hub.nav.collapsed', '["organisation"]'); });
    await p.reload();
    await p.waitForFunction(() => location.hash === '#/tasks' && TASKS_ST);
    await p.locator('#mobile-more').click();
    await p.locator('body.drawer').waitFor();
    for (const nav of ['tasks', 'goals', 'docs', 'market', 'meetings']) {
      assert.equal(await p.locator(`.side-scroll [data-nav="${nav}"]`).isVisible(), true, `${nav} shows in More`);
    }
    assert.equal(await p.locator('#nav-organisation').isVisible(), true, 'the Org section is open');
    assert.equal(await p.locator('#tree .node').first().isVisible(), true, 'the org tree shows without expanding anything');
    const ys = await Promise.all(['tasks', 'goals', 'docs', 'market', 'meetings'].map(nav => box(p.locator(`.side-scroll [data-nav="${nav}"]`)).then(b => b.y)));
    const orgY = (await box(p.locator('[data-section-toggle="organisation"]'))).y;
    assert(ys.every((y, i) => i === 0 || y > ys[i - 1]) && orgY > ys[4], 'Tasks, Goals, Docs, Market, Meetings, then Org');
    await p.waitForTimeout(350);   // the drawer's slide (.2s) has finished
    await shot(p, 'more-phone.png');
    await p.locator('#account').click();
    assert.deepEqual((await p.locator('#account-menu .nav-link:visible').allInnerTexts()).map(t => t.replace(/^\S+\s*/, '').trim()),
      ['Integrations', 'Runs', 'Changelog', 'Settings']);
    await shot(p, 'more-phone-account.png');
    await p.locator('#account').click();
    await p.locator('.side-close').click();
    // No zoom when a field is tapped: every text field is at least 16px on a phone (iOS zooms under 16px).
    const fieldSizes = async where => p.evaluate(() => [...document.querySelectorAll('input, textarea, select')]
      .filter(el => el.offsetParent && !['checkbox', 'radio', 'range', 'file', 'color', 'hidden'].includes(el.type))
      .map(el => [el.id || el.name || el.tagName, parseFloat(getComputedStyle(el).fontSize)]));
    const tasksFields = await fieldSizes();
    assert(tasksFields.some(([id]) => id === 'task-q'), 'the tasks search is on the page');
    assert(tasksFields.every(([, px]) => px >= 16), 'tasks page fields are 16px or more: ' + JSON.stringify(tasksFields));
    await p.locator('#mobile-search').click();
    await p.locator('#search-input').waitFor();
    const searchFields = await fieldSizes();
    assert(searchFields.some(([id]) => id === 'search-input') && searchFields.every(([, px]) => px >= 16), 'search fields are 16px or more: ' + JSON.stringify(searchFields));
    await p.keyboard.press('Escape');
    await p.goto('https://tico-ui.test/#/bot/cmo');
    await ready(p);
    const botFields = await fieldSizes();
    assert(parseFloat(await p.locator('#chat-composer textarea').evaluate(el => getComputedStyle(el).fontSize)) >= 16, 'the composer is 16px or more');
    assert(botFields.every(([, px]) => px >= 16), 'composer fields are 16px or more: ' + JSON.stringify(botFields));
    assert.deepEqual(phone.errors, []);
    await liveTasks(browser);
    await chatImages(browser);
    await routineDelete(browser);
    await chatPatterns(browser, {width: 1440, height: 900}, 'desktop');
    await chatPatterns(browser, {width: 390, height: 844}, 'phone');
    console.log('PASS: the unread latest update at the top (dismiss marks it read) and a History tab of every update, goal header as plain words, goals edited in place with a link icon, full-bleed chat left, Active and Assigned to others right with Recurring last, old Tasks link, More with Docs, no-goal and crashed states, phone top line with back, the bot and Chat · Tasks · More icons on the right, the goal in More, no bottom bar, composer at the bottom, arrow send and Live wave, rail order, account menu, More unfolded, 16px fields on a phone; short links, the pending line and its timeout, the jump pill, the composer cap on both.');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
