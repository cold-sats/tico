// Offline regression for code work on tasks (docs: PLAN sections 4, 5 and 9). Fixtures only.
//  - the task modal's right rail: Code has one line per worktree (repo · branch · ↑ahead ↓behind · N files, a missing
//    or removed one says so) and per pull request (#212 title and its checks, conflict, review and comment chips), each
//    a GitHub link; a mover removes one with its ✕ (DELETE .../links/{id});
//  - Subtasks: the roll-up line from children_summary, one level of children from GET /tasks/{id}/tree (the list's status
//    icon, PR badge, owner), a child's own children on expand, and "Add subtask" posting a task with parent_id;
//  - a worktree with no repo names it from its folder, else says "unknown repo" (muted);
//  - a task with no code links and no children has no rail at all; on a phone the rail sits under the details;
//  - the bot page's Active rows carry one small PR badge each, from the task's pr_state, and none without PRs.
// TASK_CODE_SHOTS=<dir> saves the screenshots for the owner.
const {chromium} = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {html, uiFile} = require('./support/page.cjs');
const SHOTS = process.env.TASK_CODE_SHOTS || '';

const now = new Date().toISOString();
const task = (id, over = {}) => ({id, title: id, body: 'Details.', owner: 'bot:eng', requester: 'human:ana', status: 'doing',
  lane: 'company', rank: 1, labels: [], links: [], parts: {total: 0, done: 0}, version: 2, created: now, updated: now, ...over});
const pr = (id, number, title, over = {}) => ({id, kind: 'pr', repo: 'acme/web', number, url: `https://github.com/acme/web/pull/${number}`,
  title, state: 'open', checks: 'passing', mergeable: 'clean', review_state: null, pending_comments: 0, ...over});
function fixtures() {
  const parent = task('t-checkout', {title: 'Ship the new checkout', pr_state: 'failing',
    // As backend/hubdb.py children_summaries sends it: total/done over the whole tree, direct_* over the children.
    children_summary: {total: 10, open: 6, done: 4, prs_total: 9, prs_merged: 7, direct_total: 4, direct_done: 1},
    // Worktree rows as backend/worktrees.py writes them: url worktree:<hex>, the heartbeat's report in detail_json.
    links: [
      {id: 'w1', kind: 'worktree', url: 'worktree:9f2c1a', title: 'acme/web worktree', repo: 'acme/web', branch: 'tico/t-check-checkout',
       state: 'present', path: 'tasks/t-check/eng__web', computer_id: 'r1', number: null, checks: null,
       detail_json: JSON.stringify({link_id: 'w1', state: 'present', branch: 'tico/t-check-checkout', ahead: 2, behind: 1, dirty_files: 3, last_commit: 'Add the summary step', size_mb: 41})},
      // No repo on the row: the folder (<bot>__<repo>) still names it.
      {id: 'w2', kind: 'worktree', url: 'worktree:77ab03', title: 'worktree', repo: null, branch: 'tico/t-check-api', state: 'unknown', path: 'tasks/t-check/api__payments-api',
       detail_json: JSON.stringify({error: 'This bot needs write access to the attached repository'})},
      {id: 'w3', kind: 'worktree', url: 'worktree:0c11de', title: 'acme/docs worktree', repo: 'acme/docs', branch: 'tico/t-check-docs', state: 'removed',
       detail_json: JSON.stringify({state: 'removed', ahead: 0, behind: 0, dirty_files: 0})},
      pr('p1', 212, 'Checkout summary step', {checks: 'failing', pending_comments: 2, review_state: 'changes_requested'}),
      pr('p2', 214, 'Price rounding', {checks: 'pending', mergeable: 'conflict'}),
      pr('p3', 198, 'Cart badge', {state: 'merged'}),
      {id: 'd1', kind: 'doc', url: 'https://docs.example.com/checkout', title: 'Checkout spec', state: 'open'},
    ]});
  const kid = (id, title, status, owner, pr_state = null, children = []) => ({id, title, status, owner, pr_state, children});
  const tree = [kid('k1', 'Summary step on web', 'review', 'bot:eng', 'failing', [kid('k1a', 'Copy for the summary', 'done', 'human:sam', 'merged')]),
    kid('k2', 'Rounding in the API', 'doing', 'bot:api', 'conflict'),
    kid('k3', 'Cart badge', 'done', 'bot:eng', 'merged'),
    kid('k4', 'Check the receipts email', 'open', 'human:sam')];
  const plain = task('t-plain', {title: 'Book the team offsite', owner: 'human:ana'});
  const others = [task('t-review', {title: 'Review the pricing copy', pr_state: 'changes_requested'}),
    task('t-open', {title: 'Upgrade the image library', pr_state: 'open'}),
    task('t-none', {title: 'Write the release notes', pr_state: null})];
  return {tasks: [parent, plain, ...others], tree};
}

async function open(browser, {viewport = {width: 1440, height: 900}, theme = 'dark', at = '#/task/t-checkout', mover = true} = {}) {
  const data = fixtures();
  const page = await browser.newPage({viewport, serviceWorkers: 'block'});
  const errors = [], writes = [];
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(t => { try { localStorage.setItem('tico.theme', t); } catch {} }, theme);
  const me = {id: 'ana', name: 'Ana', email: 'ana@example.com', role: 'owner', mover, cloud: true, registered: true};
  const bots = [['eng', 'Engineer'], ['api', 'API Engineer']].map(([name, display_name]) =>
    ({name, display_name, host: 'keeper', status: 'active', state: 'active', can_chat: true, operator: 'ana', can_manage: true,
      users: [{id: 'ana', name: 'Ana'}], my_access: {see: true, read: true, write: true}}));
  await page.route('**/*', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname, method = req.method();
    const json = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body)});
    if (url.origin !== 'https://tico-ui.test') return route.abort();
    const ui = p.match(/\/tico\/ui\/((?:app\/|styles\/)?[^/]+\.(?:js|css))$/);
    if (ui && fs.existsSync(uiFile(ui[1])))
      return route.fulfill({contentType: ui[1].endsWith('.css') ? 'text/css' : 'application/javascript', body: fs.readFileSync(uiFile(ui[1]), 'utf8')});
    if (p.startsWith('/vendor/fonts/') && fs.existsSync(uiFile(p.slice(1)))) return route.fulfill({contentType: 'font/woff2', body: fs.readFileSync(uiFile(p.slice(1)))});
    if (p === '/vendor/marked.min.js') return route.fulfill({contentType: 'application/javascript', body: fs.readFileSync(uiFile('vendor/marked.min.js'), 'utf8')});
    if (p.endsWith('.js')) return route.fulfill({contentType: 'application/javascript', body: ''});
    if (p === '/') return route.fulfill({contentType: 'text/html', body: html});
    if (p === '/api/me') return json(me);
    if (p === '/api/employees') return json(bots);
    if (p === '/api/humans') return json({people: [{id: 'ana', name: 'Ana'}, {id: 'sam', name: 'Sam'}], teams: {}});
    if (p === '/api/issues') return json([]);
    if (p === '/api/status') return json({cloud: true, active: [], queued: [], recent_runs: [], keeper_alive: true, health_issues: []});
    if (p === '/api/v2/status') return json({bots: []});
    if (p === '/api/v2/tasks/labels') return json({labels: [], tags: []});
    if (p === '/api/v2/tasks' && method === 'GET') {
      const owner = url.searchParams.get('owner');
      // List rows leave out the links' detail_json (and pr_sha), as backend/app.py lists do; the detail has them.
      const rows = (owner ? data.tasks.filter(t => t.owner === 'bot:' + owner) : url.searchParams.get('requester') ? [] : data.tasks)
        .map(t => ({...t, links: (t.links || []).map(({detail_json, pr_sha, ...l}) => l)}));
      return json({tasks: rows, next_offset: null});
    }
    if (p === '/api/v2/tasks' && method === 'POST') {
      const body = req.postDataJSON(); writes.push({method, p, body});
      const owner = body.owner.includes(':') ? body.owner : 'bot:' + body.owner;
      const made = task('k5', {title: body.title, owner, parent_id: body.parent_id, status: 'open'});
      data.tree.push({id: 'k5', title: body.title, status: 'open', owner, pr_state: null, children: []});
      data.tasks[0].children_summary = {...data.tasks[0].children_summary, total: 11, open: 7, direct_total: 5};
      return json({task: made});
    }
    const tree = p.match(/^\/api\/v2\/tasks\/([^/]+)\/tree$/);
    // As backend/hubdb.py task_tree answers: the direct children, each with its own nested children.
    if (tree) return json(tree[1] === 't-checkout' ? data.tree : []);
    const link = p.match(/^\/api\/v2\/tasks\/([^/]+)\/links\/([^/]+)$/);
    if (link && method === 'DELETE') {
      writes.push({method, p});
      const t = data.tasks.find(x => x.id === link[1]); t.links = t.links.filter(l => l.id !== link[2]);
      return json({links: t.links});
    }
    const one = p.match(/^\/api\/v2\/tasks\/([^/]+)$/);
    if (one && method === 'GET') {
      const t = data.tasks.find(x => x.id === decodeURIComponent(one[1]));
      if (!t) return json({error: {detail: 'Not found'}}, 404);
      return json({task: t, children: t.id === 't-checkout' ? data.tree.map(({children, ...k}) => k) : [], comments: [], events: []});
    }
    return json({});
  });
  await page.goto('https://tico-ui.test/' + at);
  return {page, errors, writes, data};
}

async function desktop(browser) {
  const {page, errors, writes} = await open(browser);
  const modal = page.locator('#task-modal');
  const rail = modal.locator('[data-task-rail]');
  await rail.locator('.task-subs .sub-row').first().waitFor();
  // Code: worktrees first, then pull requests; other links stay under Links & files.
  const lines = await rail.locator('.code-line').allInnerTexts();
  assert.equal(lines.length, 6);
  assert.match(lines[0], /^web\s*·\s*tico\/t-check-checkout\s*·\s*↑2 ↓1\s*·\s*3 files/);
  assert.match(lines[1], /^payments-api\s*·\s*tico\/t-check-api\s*unknown/);
  // With neither a repo, a folder nor a branch that names one: "unknown repo", muted; never the word "worktree".
  const bare = await page.evaluate(() => {
    const host = document.createElement('ul'); host.className = 'code-list';
    host.innerHTML = taskCodeLineHTML({id: 'w9', kind: 'worktree', url: 'worktree:1', repo: null, branch: 'tico/t-check-misc', state: 'present'}, true, [{kind: 'pr', repo: 'acme/web'}]);
    document.querySelector('#task-modal [data-task-rail]').append(host);
    const repo = host.querySelector('.code-repo');
    const out = {text: host.innerText, cls: repo.className, color: getComputedStyle(repo).color, muted: getComputedStyle(document.querySelector('#task-modal .tmeta')).color};
    host.remove();
    return out;
  });
  assert.match(bare.text, /^unknown repo\s*·\s*tico\/t-check-misc/);
  assert.equal(bare.cls, 'code-repo unknown');
  assert.equal(bare.color, bare.muted, 'unknown repo is muted');
  // A branch name is never taken for a repo (fix-api in the web repo is not "api"); only the folder says.
  assert.equal(await page.evaluate(() => taskWorktreeRepo({kind: 'worktree', branch: 'tico/fix-web'}, [{kind: 'pr', repo: 'acme/web'}])), '');
  assert.equal(await page.evaluate(() => taskWorktreeRepo({kind: 'worktree', path: 'tasks/t1/eng__web'}, [])), 'web');
  assert.match(lines[2], /^docs\s*·\s*tico\/t-check-docs\s*removed/);
  assert.match(lines[3], /#212\s*Checkout summary step\s*✕\s*changes requested\s*2 comments/);
  assert.match(lines[4], /#214\s*Price rounding\s*checks running\s*conflict/, 'a chip says what it means');
  assert.match(lines[5], /#198\s*Cart badge\s*merged/);
  assert.equal(await rail.locator('.code-line.wt a').first().getAttribute('href'), 'https://github.com/acme/web/tree/tico/t-check-checkout');
  // No repo, no GitHub link; the computer's error is the state's tooltip.
  assert.equal(await rail.locator('.code-line[data-code-link="w2"] a').count(), 0);
  assert.equal(await rail.locator('.code-line[data-code-link="w2"] .code-state').getAttribute('title'), 'This bot needs write access to the attached repository');
  // A live worktree cannot be taken off here (its computer cleans it up when the task closes); a removed one can.
  assert.equal(await rail.locator('.code-line[data-code-link="w1"] [data-code-drop]').count(), 0);
  assert.equal(await rail.locator('.code-line[data-code-link="w2"] [data-code-drop]').count(), 0);
  assert.equal(await rail.locator('.code-line[data-code-link="w3"] [data-code-drop]').getAttribute('aria-label'), 'Remove docs · tico/t-check-docs');
  assert.equal(await rail.locator('.code-line[data-code-link="p1"] [data-code-drop]').getAttribute('aria-label'), 'Remove #212');
  assert.equal(await rail.locator('.code-line[data-code-link="p1"] .code-chip[aria-label="Checks failing"]').count(), 1, 'a glyph chip has words');
  assert.equal(await rail.locator('.code-line.pr a').first().getAttribute('href'), 'https://github.com/acme/web/pull/212');
  assert.equal(await rail.locator('.code-line.pr a').first().getAttribute('target'), '_blank');
  assert.equal(await modal.locator('.tlinks a', {hasText: 'Checkout spec'}).count(), 1, 'a doc link stays in Links & files');
  assert.equal(await modal.locator('.tlinks a', {hasText: 'Checkout summary step'}).count(), 0, 'a PR is not listed twice');
  // Subtasks: the roll-up, one level, PR badges, expand a child.
  assert.equal(await rail.locator('.sub-sum').innerText(), '4 of 10 done · 7 PRs merged');
  assert.equal(await rail.locator('.sub-sum .sub-bar > i').evaluate(i => i.style.width), '40%', 'a thin bar beside it');
  assert.equal(await rail.locator('#task-subs-h .cnt').innerText(), '4', 'the heading counts the direct children');
  // One "Add subtask": the rail's field, and no second button in the controls.
  assert.equal(await modal.getByRole('button', {name: 'Add subtask'}).count(), 0);
  assert.equal(await rail.locator('.task-subs > .sub-list > .sub-row').count(), 4);
  const first = rail.locator('.sub-row[data-sub="k1"]');
  assert.match(await first.locator('> .sub-line').innerText(), /Summary step on web\s*PR ✕/);
  // The same status icon as the Tasks list, with its words for screen readers.
  assert.equal(await first.locator('> .sub-line > .si').getAttribute('data-status-kind'), 'review');
  assert.equal(await first.locator('> .sub-line > .si').getAttribute('aria-label'), 'In review');
  assert.equal(await rail.locator('.sub-row[data-sub="k3"] > .sub-line > .si').getAttribute('data-status-kind'), 'done');
  assert.equal(await rail.locator('.sub-row[data-sub="k4"] .pr-badge').count(), 0, 'no PRs, no badge');
  assert.equal(await rail.locator('[data-sub="k1a"]').count(), 0, 'one level shown');
  await first.locator('[data-sub-toggle]').click();
  await rail.locator('[data-sub="k1a"]').waitFor();
  assert.equal(await first.locator('[data-sub-toggle]').getAttribute('aria-expanded'), 'true');
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.subToggle), 'k1', 'focus stays on the toggle');
  // The rail sits to the right of the details on a desktop.
  const main = await modal.locator('.tmodal-main').boundingBox(), side = await rail.boundingBox();
  assert.ok(side.x > main.x + main.width - 1, 'the rail is to the right');
  if (SHOTS) { fs.mkdirSync(SHOTS, {recursive: true}); await modal.screenshot({path: path.join(SHOTS, 'task-code-desktop-dark.png')}); }

  // Add subtask: a task with parent_id, for whoever is picked (the parent's owner to start with).
  const form = rail.locator('[data-sub-add]');
  // For whom: an avatar picker, not a native select.
  assert.equal(await form.locator('select').count(), 0);
  assert.equal(await form.locator('input[name=owner]').inputValue(), 'eng');
  await form.locator('[data-sub-owner]').click();
  await modal.locator('.prop-pop [data-prop-pick="api"]').click();
  await page.waitForFunction(() => document.querySelector('#task-modal [data-sub-add] input[name=owner]')?.value === 'api');
  assert.match(await form.locator('[data-sub-owner]').getAttribute('aria-label'), /^For API Engineer/);
  const add = form.locator('input[name=title]');
  await add.fill('Check the receipts in the app'); await add.press('Enter');
  await rail.locator('.sub-row[data-sub="k5"]').waitFor();
  assert.deepEqual(writes.at(-1), {method: 'POST', p: '/api/v2/tasks', body: {title: 'Check the receipts in the app', body: 'Check the receipts in the app', owner: 'api', parent_id: 't-checkout'}});
  assert.equal(await rail.locator('#task-subs-h .cnt').innerText(), '5');
  assert.equal(await form.locator('input[name=owner]').inputValue(), 'api', 'the pick stays for the next one');
  assert.equal(await page.evaluate(() => document.activeElement?.name), 'title', 'ready for the next subtask');
  // Remove a link with its ✕ (shown on hover).
  const line = rail.locator('.code-line[data-code-link="p2"]');
  await line.hover();
  await line.locator('[data-code-drop]').click();
  await rail.locator('.code-line[data-code-link="p2"]').waitFor({state: 'detached'});
  assert.deepEqual(writes.at(-1), {method: 'DELETE', p: '/api/v2/tasks/t-checkout/links/p2'});

  // A task with nothing in the rail has no rail and no empty headings.
  await page.evaluate(() => { location.hash = '#/task/t-plain'; });
  await modal.locator('.tmodal-title', {hasText: 'Book the team offsite'}).waitFor();
  await page.waitForTimeout(200);
  assert.equal(await modal.locator('[data-task-rail]').isHidden(), true);
  assert.equal(await modal.evaluate(d => d.classList.contains('has-rail')), false);
  assert.equal(await modal.locator('text=Subtasks').count(), 0);
  // "Add subtask" in the task's "…" menu opens the rail's field, which then is the only one.
  await modal.locator('[data-task-more]').click();
  await modal.locator('.prop-pop .tl-mi', {hasText: 'Add subtask'}).click();
  await modal.locator('[data-sub-add] input[name=title]').waitFor();
  assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-label')), 'Add subtask');
  assert.equal(await modal.getByRole('button', {name: 'Add subtask'}).count(), 0);
  assert.equal(await modal.locator('[data-sub-add] input[name=owner]').inputValue(), 'human:ana');
  assert.deepEqual(errors, []);
  console.log('task rail desktop: ok');
  await page.close();
}

async function phone(browser) {
  const {page, errors} = await open(browser, {viewport: {width: 390, height: 844}});
  const modal = page.locator('#task-modal'), rail = modal.locator('[data-task-rail]');
  await rail.locator('.task-subs .sub-row').first().waitFor();
  const main = await modal.locator('.tmodal-main').boundingBox(), side = await rail.boundingBox(), chat = await modal.locator('.task-chat').boundingBox();
  assert.ok(side.y >= main.y + main.height - 1 && chat.y >= side.y + side.height - 1, 'details, then the rail, then comments');
  assert.ok(side.x >= 0 && side.x + side.width <= 390, 'inside the screen');
  const overflow = await modal.evaluate(d => d.querySelector('.tmodal-body').scrollWidth - d.querySelector('.tmodal-body').clientWidth);
  assert.ok(overflow <= 1, 'no sideways scroll');
  if (SHOTS) {
    await rail.scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(SHOTS, 'task-code-phone-dark.png')});
  }
  assert.deepEqual(errors, []);
  console.log('task rail phone: ok');
  await page.close();
}

async function member(browser) {
  // Someone who may not move tasks sees the links but no ✕ and no Add subtask.
  const {page, errors} = await open(browser, {mover: false});
  const rail = page.locator('#task-modal [data-task-rail]');
  await rail.locator('.task-subs .sub-row').first().waitFor();
  assert.equal(await rail.locator('[data-code-drop]').count(), 0);
  assert.equal(await rail.locator('[data-sub-add]').count(), 0);
  assert.deepEqual(errors, []);
  console.log('task rail member: ok');
  await page.close();
}

async function botPage(browser) {
  const {page, errors} = await open(browser, {at: '#/bot/eng'});
  const rows = page.locator('#t-open .trow');
  await rows.first().waitFor();
  const badge = title => page.locator('#t-open .trow', {hasText: title}).locator('.pr-badge');
  assert.equal(await badge('Ship the new checkout').innerText(), 'PR ✕');
  assert.equal(await badge('Ship the new checkout').getAttribute('aria-label'), 'Checks failing');
  assert.equal(await badge('Review the pricing copy').innerText(), 'PR changes');
  assert.equal(await badge('Upgrade the image library').innerText(), 'PR');
  assert.equal(await badge('Write the release notes').count(), 0, 'no PRs, no badge');
  for (const title of ['Ship the new checkout', 'Write the release notes']) {
    const box = await page.locator('#t-open .trow', {hasText: title}).locator('summary').boundingBox();
    assert.ok(box.height <= 44, `${title}: still a compact row`);
  }
  if (SHOTS) await page.locator('#pane-tasks .bot-active').screenshot({path: path.join(SHOTS, 'bot-active-pr-badges-dark.png')});
  assert.deepEqual(errors, []);
  console.log('bot page badges: ok');
  await page.close();
}

(async () => {
  const browser = await chromium.launch({channel: process.env.TICO_BROWSER_CHANNEL ?? 'chrome', headless: true});
  try { await desktop(browser); await phone(browser); await member(browser); await botPage(browser); }
  finally { await browser.close(); }
})().catch(e => { console.error(e); process.exit(1); });
