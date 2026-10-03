// Pure rendering checks: no credentials, network or provider calls.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const context = vm.createContext({Date, Object, JSON, Number, Map, Set,
  esc: value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;'),
  settingsIsAdmin: () => true, SETTINGS_DATA: {}, SETTINGS_ME: {actor: 'human:demo'}});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../app/subscriptions.js'), 'utf8'), context);
function html(state, runtime = 'codex') {
  context.fixture = {name: 'demo', runtimes: {[runtime]: state}};
  return vm.runInContext('subsWeeklyHTML({runner_id: "computer"}, fixture)', context);
}
assert.match(html({signed_in: false}), /Sign-in needed/);
assert.match(html({signed_in: false}), /data-subs-refresh[^>]*disabled/);
assert.match(html({signed_in: null}), /usage unknown/);
assert.doesNotMatch(html({signed_in: null}), /0% used/);
assert.doesNotMatch(html({signed_in: true}, 'claude'), /data-subs-refresh/);
assert.match(html({signed_in: true}, 'claude'), /no background model turn/);
const weekly = {used_percent: 100, status: 'rejected', source: 'provider',
  reported_at: '2020-01-01T00:00:00Z', resets_at: '2020-01-05T00:00:00Z'};
const failed = html({signed_in: false, weekly, refresh: {state: 'failed', updated_at: '2020-01-02T00:00:00Z'}});
assert.match(failed, /Sign-in needed/);
assert.match(failed, /previous week; refresh needed/);
assert.match(failed, /Refresh failed; last reading kept/);
assert.match(failed, /100% used/);
assert.match(failed, /limit reached/);
console.log('Weekly subscription rendering checks passed');
