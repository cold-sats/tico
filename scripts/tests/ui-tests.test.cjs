const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {spawnSync} = require('node:child_process');
const {resources, sampleCpu} = require('../ui-tests.cjs');

test('one CPU-idle policy, explicit overrides and shared context/page timeouts', async () => {
  const counters = (user, idle) => Array.from({length: 12}, () => ({times: {user, nice: 0, sys: 0, idle, irq: 0}}));
  const snapshots = [counters(10000, 50000), counters(10070, 50030)];
  const sampled = await sampleCpu(() => snapshots.shift(), async ms => assert.equal(ms, 1000));
  assert.deepEqual(sampled, {cores: 12, idleFraction: 0.3});
  assert.equal(snapshots.length, 0);
  const spare = resources({}, sampled.cores, sampled.idleFraction);
  assert.equal(spare.jobs, 3);
  assert.ok(Math.abs(spare.slowdown - 5 / 3) < 1e-12);
  assert.deepEqual(resources({}, 12, 1), {jobs: 4, slowdown: 1});
  assert.deepEqual(resources({}, 12, 0.1), {jobs: 1, slowdown: 4});
  assert.deepEqual(resources({}, 12, 0), {jobs: 1, slowdown: 4});
  assert.deepEqual(resources({TICO_UI_JOBS: '3', TICO_UI_SLOWDOWN: '2.5'}, 12, 0.1), {jobs: 3, slowdown: 2.5});

  const support = path.resolve(__dirname, '../../ui/tests/support');
  for (const [value, expected] of [[undefined, 1], ['2.5', 2.5]]) {
    const env = {...process.env};
    delete env.TICO_UI_SLOWDOWN;
    if (value !== undefined) env.TICO_UI_SLOWDOWN = value;
    const result = spawnSync(process.execPath, ['-e', `
      const {SLOWDOWN,t,applyTimeouts}=require(${JSON.stringify(path.join(support, 'load.cjs'))});
      const calls=[]; applyTimeouts({setDefaultTimeout:n=>calls.push(n),setDefaultNavigationTimeout:n=>calls.push(n)});
      console.log(JSON.stringify({SLOWDOWN,rounded:t(101),calls}));`], {env, encoding: 'utf8'});
    assert.equal(result.status, 0, result.stderr);
    assert.deepEqual(JSON.parse(result.stdout), {SLOWDOWN: expected, rounded: Math.round(101 * expected),
                                               calls: [30000 * expected, 30000 * expected]});
  }

  const calls = [];
  const page = () => ({setDefaultTimeout: n => calls.push(['page', n]),
                      setDefaultNavigationTimeout: n => calls.push(['navigation', n])});
  const context = () => {
    let onPage;
    return {setDefaultTimeout: n => calls.push(['context', n]),
            setDefaultNavigationTimeout: n => calls.push(['context-navigation', n]),
            on: (event, callback) => { assert.equal(event, 'page'); onPage = callback; },
            newPage: async () => { const p = page(); onPage(p); return p; }};
  };
  const engine = () => ({launch: async () => ({newContext: async () => context(),
                                            newPage: async function () { return (await this.newContext()).newPage(); }}),
                        launchPersistentContext: async () => context()});
  const playwright = {chromium: engine(), firefox: engine(), webkit: engine()};
  vm.runInNewContext(fs.readFileSync(path.join(support, 'browser.cjs'), 'utf8'), {
    require: name => name === 'playwright' ? playwright : {
      applyTimeouts: p => { p.setDefaultTimeout(60000); p.setDefaultNavigationTimeout(60000); }}
  });
  const browser = await playwright.chromium.launch();
  await browser.newPage();
  assert.deepEqual(calls, [['context', 60000], ['context-navigation', 60000], ['page', 60000], ['navigation', 60000]]);
  calls.length = 0;
  const ctx = await browser.newContext();
  await ctx.newPage();
  await ctx.newPage(); // includes popups/other pages: each gets its defaults before the script uses it
  assert.equal(calls.length, 6);
  calls.length = 0;
  await playwright.chromium.launchPersistentContext('synthetic-profile');
  assert.deepEqual(calls, [['context', 60000], ['context-navigation', 60000]]);
});
