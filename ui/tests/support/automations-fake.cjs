// A stand-in hub for the Automations page scripts (ui/tests/automations-*.cjs): every /api/v2/automations route in
// redesign CONTRACT §2 over ui/tests/fixtures/redesign-automations.json (the Acme example), the Automations Bot's chat,
// and the boot stubs. Writes change the copy a page reads back and are recorded in `writes`.
// A flow save (steps or trigger) is a new version; a viewer without edit rights gets 403; a built-in's delete gets 409.
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./page.cjs');
const {unrouted} = require('./routes.cjs');
const uiDir = path.join(__dirname, '../..');
const FIXTURE = path.join(__dirname, '../fixtures/redesign-automations.json');

const PHONE = {width: 390, height: 844}, DESKTOP = {width: 1440, height: 900};
const clone = x => JSON.parse(JSON.stringify(x));

// 30 runs of the inbox automation, newest first: most reply, a few fail at the LLM, a few hit the spend limit.
function inboxRuns(now = Date.now()) {
  return Array.from({length: 30}, (_, i) => {
    const failed = i % 9 === 4, capped = i % 7 === 3 && !failed;
    const steps = [
      {id: 'f1', type: 'filter', status: 'ok', outputs: {rule: null}, cost: 0},
      {id: 'dc1', type: 'decide', status: 'ok', cost: 0.004, outputs: {
        bucket: {choice: 'reply', confidence: 0.82, probabilities: {reply: 0.82, archive: 0.1, route: 0.08}},
        is_ask: {noul: 0.64}, money: {noul: 0.12}, legal: {noul: 0.03}}},
      {id: 'p1', type: 'paths', status: 'ok', outputs: {path: 0}, cost: 0},
      {id: 'l1s', type: 'llm', status: failed ? 'failed' : capped ? 'spend_cap' : 'ok', cost: failed || capped ? 0 : 0.03,
        outputs: failed ? {error: 'model timed out'} : capped ? {} : {text: 'Thanks Sam, Thursday at 3 works.'}},
    ];
    if (!failed && !capped) steps.push({id: 'a1', type: 'action', status: 'ok', outputs: {result: 'draft saved'}, cost: 0});
    return {id: 'run_' + (100 - i), automation_id: 'au_inbox', version: i < 12 ? 7 : 6, trigger_ref: 'mail:m' + i,
      started: new Date(now - i * 17 * 60000).toISOString(), finished: new Date(now - i * 17 * 60000 + 9000).toISOString(),
      status: failed ? 'failed' : 'ok', cost: steps.reduce((t, s) => t + s.cost, 0), steps};
  });
}

// One page on the fake hub. viewer: the person signed in (any but the fixture's owner sees nothing editable).
async function openAutomations(browser, {viewport = PHONE, hash = '#/automations', redesign = true, viewer = 'dana'} = {}) {
  const fx = clone(JSON.parse(fs.readFileSync(FIXTURE, 'utf8')));
  const owner = viewer === fx.me.id;
  const me = owner ? fx.me : {id: viewer, name: fx.people.find(p => p.id === viewer)?.name || viewer, email: viewer + '@acme.example',
    role: 'member', company_role: 'member', cloud: true};
  const config = redesign ? {redesign: true} : {};
  const db = {
    list: fx.automations.map(a => ({...a, can_edit: owner && a.can_edit !== false})),
    versions: {}, runs: {au_inbox: inboxRuns()}, conv: null, messages: [],
  };
  for (const a of db.list) {
    const old = fx.versions[a.id] || [{n: a.version, actor: a.owner, at: '2026-10-27T15:00:00Z'}];
    db.versions[a.id] = old.map(v => ({...v, status: 'active', flow: {trigger: clone(a.trigger), steps: clone(a.steps)}}));
  }
  const writes = [];
  const find = id => db.list.find(a => a.id === id);
  // A Decide step on a saved set comes back with the set's questions alongside, read-only (CONTRACT §2).
  const withSets = steps => (steps || []).map(s => {
    const out = {...s};
    if (s.type === 'decide' && s.set) out.questions = clone(fx.question_sets.find(q => q.id === s.set)?.questions || {});
    if (s.type === 'paths') {
      out.paths = (s.paths || []).map(p => ({...p, steps: withSets(p.steps)}));
      out.otherwise = {steps: withSets(s.otherwise?.steps)};
    }
    return out;
  });
  const full = a => ({...clone(a), steps: withSets(a.steps)});
  const row = a => { const {steps, ...rest} = clone(a); return rest; };
  const nextN = id => Math.max(...db.versions[id].map(v => v.n)) + 1;
  const newVersion = (a, actor = 'person:' + me.id) => {
    a.version = nextN(a.id);
    db.versions[a.id].push({n: a.version, actor, at: new Date().toISOString(), status: 'active', flow: {trigger: clone(a.trigger), steps: clone(a.steps)}});
  };

  const page = await browser.newPage({viewport, serviceWorkers: 'block'});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname, method = req.method();
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    const refuse = (status, code, detail) => json({error: {code, detail}}, status);
    if (url.origin !== 'http://tico-ui.test') return route.abort();
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    const file = p.startsWith('/tico/ui/') ? uiFile(p.slice(9)) : p.startsWith('/vendor/') ? path.join(uiDir, p) : '';
    if (file && fs.existsSync(file)) return route.fulfill({contentType: file.endsWith('.js') ? 'application/javascript' : file.endsWith('.css') ? 'text/css' : file.endsWith('.woff2') ? 'font/woff2' : 'application/octet-stream', body: fs.readFileSync(file)});
    if (p === '/api/v2/events') return;
    if (p === '/api/v2/config') return json(config);
    if (p === '/api/me') return json({...me, config});
    if (p === '/api/employees') return json(fx.employees);
    if (p === '/api/humans') return json({people: fx.people.map(x => ({...x, org_parent: ''})), org_groups: []});
    if (p === '/api/status') return json({active: [], employees: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/groups') return json({groups: fx.groups});
    const body = method === 'GET' ? null : req.postDataJSON?.() ?? null;
    if (method !== 'GET') writes.push({method, path: p, body});

    if (p === '/api/v2/automations/question-sets') return json({sets: fx.question_sets});
    if (p === '/api/v2/automations') return json({automations: db.list.map(row), next: null});
    let m = p.match(/^\/api\/v2\/automations\/([^/]+)(?:\/(.*))?$/);
    if (m) {
      const a = find(decodeURIComponent(m[1])), rest = m[2] || '';
      if (!a) return refuse(404, 'not_found', 'No such automation');
      if (method !== 'GET' && !a.can_edit) return refuse(403, 'forbidden', 'You can’t change this automation');
      if (!rest && method === 'GET') return json(full(a));
      if (!rest && method === 'PATCH') {
        for (const k of ['enabled', 'spend_cap', 'name']) if (k in body) { if (body[k] === null) delete a[k]; else a[k] = body[k]; }
        if (body.steps || body.trigger) {
          if (body.steps) a.steps = body.steps;
          if (body.trigger) a.trigger = body.trigger;
          newVersion(a);
        }
        return json(full(a));
      }
      if (!rest && method === 'DELETE') {
        if (a.builtin) return refuse(409, 'builtin', 'Built-in automations can’t be deleted');
        db.list = db.list.filter(x => x !== a);
        return json({ok: true});
      }
      if (rest === 'runs') {
        const all = db.runs[a.id] || [], limit = Number(url.searchParams.get('limit') || 25), before = url.searchParams.get('before');
        const from = before ? all.findIndex(r => r.id === before) + 1 : 0, rows = all.slice(from, from + limit);
        return json({runs: rows, next: from + limit < all.length ? rows.at(-1).id : null});
      }
      if (rest === 'versions') {
        const status = url.searchParams.get('status');
        return json({versions: db.versions[a.id].filter(v => !status || v.status === status)});
      }
      if ((m = rest.match(/^versions\/(\d+)\/restore$/)) && method === 'POST') {
        const v = db.versions[a.id].find(x => x.n === +m[1]);
        if (!v) return refuse(404, 'not_found', 'No such version');
        a.trigger = clone(v.flow.trigger); a.steps = clone(v.flow.steps);
        // A pending version turned on becomes the current one; an older one comes back as a new version.
        if (v.status === 'pending') { v.status = 'active'; a.version = v.n; } else newVersion(a);
        return json(full(a));
      }
      if ((m = rest.match(/^versions\/(\d+)$/)) && method === 'DELETE') {
        const v = db.versions[a.id].find(x => x.n === +m[1] && x.status === 'pending');
        if (!v) return refuse(409, 'not_pending', 'Only a proposal can be discarded');
        db.versions[a.id] = db.versions[a.id].filter(x => x !== v);
        return json({ok: true});
      }
    }

    // The Automations Bot: a message about an automation comes back with a reply and a proposal (a pending version).
    if (p === '/api/v2/conversations') return json({conversations: db.conv && url.searchParams.get('chat_with') === 'automations-bot' ? [db.conv] : []});
    if (db.conv && p === `/api/v2/conversations/${db.conv.id}/snapshot`) return json({messages: db.messages, execution: null, has_more: false, next_before: null});
    if (p === '/api/v2/chat/automations-bot' && method === 'POST') {
      db.conv ||= {id: 'conv_au', kind: 'chat', title: 'Automations Bot'};
      const n = db.messages.length, at = new Date().toISOString();
      const mine = {id: 'msg' + n, from_actor: 'human:' + me.id, body: body.text, refs: body.refs || {}, created: at, kind: 'say'};
      db.messages.push(mine);
      const a = find(body.refs?.automation);
      if (a) {
        const steps = clone(a.steps), filter = steps.find(s => s.type === 'filter');
        filter?.rules.unshift(clone(fx.proposal.rule));
        db.versions[a.id].push({n: nextN(a.id), actor: 'bot:automations-bot', at, status: 'pending', summary: fx.proposal.summary,
          flow: {trigger: clone(a.trigger), steps}});
      }
      db.messages.push({id: 'msg' + (n + 1), from_actor: 'bot:automations-bot', body: a ? 'Here is a new version: receipts are archived first.' : 'What should it watch?', refs: {}, created: at, kind: 'say'});
      return json({conversation: db.conv, message: mine});
    }
    return json(unrouted(p));
  });
  await page.goto('http://tico-ui.test/' + hash);
  return {page, errors, writes, db, me};
}

// No sideways scroll on the page itself (a path strip scrolls inside its own box).
const sideways = page => page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
// A screenshot for the build notes, when TICO_UI_SHOTS names a folder.
async function shot(page, name) {
  const dir = process.env.TICO_UI_SHOTS;
  if (!dir) return;
  fs.mkdirSync(dir, {recursive: true});
  await page.evaluate(() => Promise.all(document.getAnimations().map(a => a.finished.catch(() => {}))));   // the route's fade
  await page.screenshot({path: path.join(dir, name + '.png')});
}

module.exports = {openAutomations, PHONE, DESKTOP, sideways, shot};
