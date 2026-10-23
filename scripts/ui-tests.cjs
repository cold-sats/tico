#!/usr/bin/env node
// Runs the browser scripts in ui/tests/*.cjs a few at a time (npm run test:ui).
// Each script's output is held and printed together, so a failure reads as one block.
// Usage: node scripts/ui-tests.cjs [-j N] [--all] [name-or-path ...]   (free-core jobs, or $TICO_UI_JOBS)
// With no names it runs CORE, the main pages and the privacy boundaries; --all runs every script (the release
// check does). A name runs that script whether or not it is in CORE. Run locally, it waits for one of the box's
// heavy-job slots first (scripts/heavy.sh). A script still running after TICO_UI_SCRIPT_TIMEOUT seconds (120, times the
// slowdown) is stopped with every process it started and fails with its name and the browser calls it was waiting on,
// so one hang does not hold the job until CI cancels it.
const {execFileSync, spawn} = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

async function sampleCpu(read = os.cpus, pause = ms => new Promise(resolve => setTimeout(resolve, ms))) {
  // CPU counters measure spare capacity even when macOS load average stays high.
  const before = read();
  await pause(1000);
  const after = read();
  const idle = cpus => cpus.reduce((sum, cpu) => sum + cpu.times.idle, 0);
  const total = cpus => cpus.reduce((sum, cpu) => sum + Object.values(cpu.times).reduce((a, b) => a + b, 0), 0);
  const elapsed = total(after) - total(before);
  const idleFraction = before.length === after.length && elapsed > 0
    ? Math.max(0, Math.min(1, (idle(after) - idle(before)) / elapsed)) : 0;
  return {cores: Math.max(1, after.length), idleFraction};
}

function resources(env, cores, idleFraction) {
  const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
  const jobs = Number(env.TICO_UI_JOBS ?? clamp(Math.floor(cores * idleFraction), 1, 4));
  const slowdown = Number(env.TICO_UI_SLOWDOWN ?? clamp(1 / Math.max(idleFraction * 2, 0.25), 1, 4));
  const timeout = Number(env.TICO_UI_SCRIPT_TIMEOUT ?? 120) * slowdown;
  if (!Number.isInteger(jobs) || jobs < 1) throw new Error('TICO_UI_JOBS must be a positive integer');
  if (!Number.isFinite(slowdown) || slowdown <= 0) throw new Error('TICO_UI_SLOWDOWN must be a positive finite number');
  if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('TICO_UI_SCRIPT_TIMEOUT must be a positive number of seconds');
  return {jobs, slowdown, timeout};
}

// Lists every process as {pid, ppid, command}; a stopped script's tree is found from it by parent, never by name.
function listProcesses() {
  return execFileSync('ps', ['-A', '-o', 'pid=,ppid=,command='], {encoding: 'utf8', timeout: 5000}).split('\n')
    .map(line => /^\s*(\d+)\s+(\d+)\s?(.*)$/.exec(line)).filter(Boolean)
    .map(([, pid, ppid, command]) => ({pid: Number(pid), ppid: Number(ppid), command: command.trim()}));
}

// Stops a script and every process it started: its browser (which Playwright puts in a process group of its own),
// the browser's helpers and any server the script spawned. Each pass freezes what it finds, so nothing in the tree
// can start another process or be orphaned while the tree is read; then all of it is killed. Returns what it stopped.
function stopTree(root, {list = listProcesses, signal = (pid, name) => process.kill(pid, name)} = {}) {
  const send = (pid, name) => { try { signal(pid, name); } catch {} };
  if (process.platform === 'win32') {
    try { execFileSync('taskkill', ['/PID', String(root), '/T', '/F'], {stdio: 'ignore', timeout: 10000}); } catch {}
    return [{pid: root, command: ''}];
  }
  const found = new Map();
  for (let pass = 0; pass < 5; pass++) {
    let rows = [];
    try { rows = list(); } catch {}
    const tree = new Set([root, ...found.keys()]);
    for (let grew = true; grew;) {
      grew = false;
      for (const row of rows) if (tree.has(row.ppid) && !tree.has(row.pid)) { tree.add(row.pid); grew = true; }
    }
    const before = found.size;
    for (const pid of tree) {
      if (found.has(pid)) continue;
      found.set(pid, (rows.find(row => row.pid === pid)?.command ?? '').slice(0, 120));
      send(pid, 'SIGSTOP');
    }
    if (found.size === before) break;
  }
  for (const pid of found.keys()) send(pid, 'SIGKILL');
  return [...found].map(([pid, command]) => ({pid, command}));
}

// Runs one browser script with the support preload and holds its output. A script still running after `timeout`
// seconds is stopped with everything it started. Playwright's call log (DEBUG=pw:api) is held apart from the
// output: it names the browser calls a stopped script was still waiting on, which is the hang point.
function runScript(script, {env = process.env, timeout, preload = path.join(__dirname, '..', 'ui', 'tests', 'support', 'browser.cjs'),
                            stop = stopTree}) {
  return new Promise(resolve => {
    const t0 = Date.now();
    const trace = env.DEBUG === undefined;
    const child = spawn(process.execPath, ['--require', preload, script], {env: trace ? {...env, DEBUG: 'pw:api'} : env});
    let out = '', err = '', timedOut = false, stopped = [];
    const calls = [], pending = [];
    const take = line => {
      const api = / pw:api (.*)$/.exec(line);
      if (!api) { out += line + '\n'; return; }
      calls.push(api[1]);
      if (calls.length > 10) calls.shift();
      let call;
      if ((call = /^=> (\S+) started/.exec(api[1]))) pending.push(call[1]);
      else if ((call = /^<= (\S+) (succeeded|failed)/.exec(api[1])) && pending.includes(call[1])) {
        pending.splice(pending.lastIndexOf(call[1]), 1);
      }
    };
    child.stdout.on('data', d => { out += d; });
    child.stderr.on('data', d => {
      if (!trace) { out += d; return; }
      const lines = (err + d).split('\n');
      err = lines.pop();
      lines.forEach(take);
    });
    const timer = setTimeout(() => { timedOut = true; stopped = stop(child.pid); }, timeout * 1000);
    // Wait for the process, not for its pipes: a browser's helper processes can hold them open for a minute.
    child.on('exit', code => {
      clearTimeout(timer);
      setTimeout(() => {
        child.stdout.destroy(); child.stderr.destroy();
        if (err) take(err);
        resolve({code, out, timedOut, secs: (Date.now() - t0) / 1000, stopped, pending: [...pending], calls: [...calls]});
      }, 100);
    });
  });
}

// What a stopped script was doing: the browser calls it was waiting on, the last ones logged and what was stopped.
function stoppedReport({pending, calls, stopped}) {
  return [pending.length ? `waiting on: ${pending.join(', ')}` : 'waiting on: no browser call (the script itself)',
          ...(calls.length ? ['last browser calls:', ...calls.map(call => `  ${call}`)] : []),
          `stopped ${stopped.length} process(es) it started:`, ...stopped.map(p => `  ${p.pid} ${p.command}`)].join('\n');
}

async function main() {
  const {cores, idleFraction} = await sampleCpu();
  const selected = resources(process.env, cores, idleFraction);

  const dir = path.join(__dirname, '..', 'ui', 'tests');
  const CORE = ['bot-permissions', 'chat', 'docs', 'goals', 'inbound', 'meetings', 'people-access', 'recruit-unit',
                'settings-forms', 'sign-in-redirect', 'task-privacy', 'tasks-page', 'team-groups', 'visual-cards', 'visual-fallback', 'visual-media', 'visual-media-app'];
  const args = process.argv.slice(2);
  let jobs = selected.jobs;
  let all = false;
  const wanted = [];
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '-j') {
      jobs = Number(args[++i]);
      if (!Number.isInteger(jobs) || jobs < 1) throw new Error('-j must be a positive integer');
    }
    else if (args[i] === '--all') all = true;
    else wanted.push(path.basename(args[i]).replace(/\.cjs$/, ''));
  }
  const chosen = wanted.length ? wanted : all ? null : CORE;
  const files = fs.readdirSync(dir).filter(f => f.endsWith('.cjs')).sort()
    .filter(f => !chosen || chosen.includes(f.replace(/\.cjs$/, '')));
  if (!files.length) { console.error('no UI test scripts matched'); process.exit(1); }
  console.log(`UI tests: jobs=${jobs}, slowdown=${selected.slowdown}, timeout=${selected.timeout}s, cores=${cores}, idle=${(idleFraction * 100).toFixed(1)}%`);

  const failed = [];
  const started = Date.now();
  const env = {TICO_BROWSER: 'chromium', ...process.env, TICO_UI_SLOWDOWN: String(selected.slowdown)};
  const run = async file => {
    const result = await runScript(path.join(dir, file), {env, timeout: selected.timeout});
    const {code, out, timedOut, secs} = result;
    if (code === 0 && !timedOut) console.log(`ok    ${file} (${secs.toFixed(1)}s)`);
    else {
      failed.push(file);
      const why = timedOut ? `, stopped: still running after ${selected.timeout}s` : '';
      const text = timedOut ? `${out.trimEnd()}\n${stoppedReport(result)}` : out.trimEnd();
      console.log(`FAIL  ${file} (${secs.toFixed(1)}s${why})\n${text.replace(/^/gm, '      ')}\n`);
    }
  };

  const queue = [...files];
  await Promise.all(Array.from({length: Math.min(jobs, queue.length)}, async () => {
    while (queue.length) await run(queue.shift());
  }));
  const secs = ((Date.now() - started) / 1000).toFixed(0);
  console.log(failed.length ? `\n${failed.length} of ${files.length} UI scripts failed: ${failed.join(', ')} (${secs}s)`
                            : `\n${files.length} UI scripts passed in ${secs}s`);
  process.exit(failed.length ? 1 : 0);
}

module.exports = {resources, runScript, sampleCpu, inSlot, stopTree, stoppedReport};
// A local run first takes one of the box's heavy-job slots, at low priority (scripts/heavy.sh), before it samples
// the CPU; hosted CI, a run already in a slot, or a computer without bash goes straight on.
function inSlot(env = process.env) { return Boolean(env.CI || env.TICO_HEAVY_HELD) || process.platform === 'win32'; }

if (require.main === module) {
  const go = () => main().catch(error => { console.error(error.message); process.exitCode = 1; });
  if (inSlot()) go();
  else {
    // The wrapper's own stop ends the browser scripts, so a stop here is passed on and the exit waits for it.
    const slotted = spawn(path.join(__dirname, 'heavy.sh'), [process.execPath, __filename, ...process.argv.slice(2)],
                          {stdio: 'inherit'});
    for (const signal of ['SIGTERM', 'SIGINT', 'SIGHUP']) process.on(signal, () => slotted.kill('SIGTERM'));
    slotted.on('error', go);
    slotted.on('exit', code => process.exit(code ?? 1));
  }
}
