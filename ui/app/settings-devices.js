/* ui/app/settings-devices.js — Settings > Devices: computers, enrollment, API tokens, agent credentials, setup prompts
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// An external agent (a Hermes profile) has no computer: the cell holds its credential instead.
// The token is shown once, when it is minted; after that only rotate and revoke remain.
const agentKind = a => `${settingsHarnessName(a.harness) || a.harness} agent`;
function settingsAgentCell(e) {
  const a = e.agent, name = agentKind(a);
  const manage = settingsCanManageBot(e);
  if (a.synced) return `<div class="settings-agent-cell"><strong>${esc(name)}</strong>${a.profile ? ` · <span class="muted">${esc(a.profile)}</span>` : ''}
    <span class="settings-cell-note">${esc(a.last_seen ? `synced ${ago(a.last_seen)}${a.detail ? ` by ${a.detail}` : ''}` : 'not synced yet')}</span></div>`;
  const seen = a.last_seen ? `last seen ${ago(a.last_seen)}` : a.credential ? 'credential issued · no heartbeat yet' : 'no credential yet';
  return `<div class="settings-agent-cell"><strong>${esc(name)}</strong>${a.profile ? ` · <span class="muted">${esc(a.profile)}</span>` : ''}
    <span class="settings-cell-note">${esc(seen)}</span>
    ${manage ? `<span class="settings-agent-actions"><button class="ghost" type="button" data-agent-credential="${esc(e.name)}">${a.credential ? 'Rotate credential' : 'Create credential'}</button>${a.credential ? `<button class="ghost" type="button" data-agent-revoke="${esc(e.name)}">Revoke</button>` : ''}</span>` : ''}</div>`;
}
async function settingsAgentCredential(slug) {
  const e = S.emps.find(row => row.name === slug); if (!e) return;
  const rotating = !!e.agent?.credential;
  if (rotating && !confirm(`Rotate the agent credential for ${e.display_name}? The current token stops working at once; install the new one on its box.`)) return;
  let issued;
  try { issued = await post(`/v2/bots/${encodeURIComponent(slug)}/agent-credential`, {}); }
  catch (error) { toast(error.message, true); return; }
  const setup = issued.setup, yaml = agentConfigYaml(setup);
  const dialog = document.createElement('dialog'); dialog.className = 'tmodal agent-credential';
  dialog.innerHTML = `<header><h2>${rotating ? 'New agent credential' : 'Agent credential'} for ${esc(e.display_name)}</h2><button class="ghost" type="button" data-close>Close</button></header>
    <div class="agent-credential-body">
      <p>Shown once. It is this bot's identity; revoking it stops the bot at once.</p>
      <label>Token<div class="row"><code class="agent-token" data-token>${esc(issued.token)}</code><button class="ghost" type="button" data-copy-token>Copy</button></div></label>
      <label>On the box that runs the Hermes profile, one command installs the hub as an MCP server in the profile and a heartbeat timer:
        <div class="row"><code data-command>curl -fsSL -H "Authorization: Bearer ${esc(issued.token)}" ${esc(setup.url)}/api/v2/agents/setup-script -o hermes_agent.py &amp;&amp; python3 hermes_agent.py install --profile ${esc(e.agent?.profile || slug)} --url ${esc(setup.url)} --bot ${esc(slug)} --token ${esc(issued.token)}</code><button class="ghost" type="button" data-copy-command>Copy</button></div></label>
      <details><summary>Or by hand: the profile's config.yaml and the heartbeat</summary>
        <pre data-yaml>${esc(yaml)}</pre>
        <p class="muted">Heartbeat: <code>POST ${esc(setup.url)}${esc(setup.heartbeat.path)}</code> with <code>Authorization: Bearer &lt;token&gt;</code> every ${setup.heartbeat.every_seconds} s; the bot shows offline after ${setup.heartbeat.offline_after_seconds} s without one.</p>
      </details>
    </div>`;
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  dialog.querySelector('[data-copy-token]').onclick = () => void copyText(issued.token).then(() => toast('Token copied'));
  dialog.querySelector('[data-copy-command]').onclick = () => void copyText(dialog.querySelector('[data-command]').textContent).then(() => toast('Command copied'));
  dialog.onclose = () => { dialog.remove(); void loadSettings(); };
  document.body.appendChild(dialog); dialog.showModal();
}
// Personal API tokens (backend/personal_tokens.py): listed, made and revoked only from a signed-in
// browser; the secret is shown once, in the same dialog the agent credential uses.
async function renderSettingsTokens() {
  const el = $('#set-tokens'); if (!el) return;
  let rows;
  try { rows = (await get('/v2/me/tokens')).tokens || []; }
  catch (error) { el.innerHTML = `<div class="err">${esc(error.message || 'Tokens could not be loaded')}</div>`; return; }
  const now = Date.now();
  const state = row => row.revoked_at ? '<span class="pill fail">revoked</span>'
    : row.expires_at && new Date(row.expires_at) < now ? '<span class="pill fail">expired</span>' : '<span class="pill ok">active</span>';
  const live = rows.filter(row => !row.revoked_at);
  const table = live.length ? `<div class="scroll"><table class="settings-table"><thead><tr><th>Label</th><th>Created</th><th>Last used</th><th>Expires</th><th>Status</th><th></th></tr></thead><tbody>${live.map(row =>
    `<tr data-token-row="${esc(row.id)}"><td><strong>${esc(row.label)}</strong></td><td>${esc(ago(row.created))}</td><td>${row.last_used ? esc(ago(row.last_used)) : '<span class="muted">never</span>'}</td><td>${row.expires_at ? esc(new Date(row.expires_at).toLocaleDateString()) : '<span class="muted">never</span>'}</td><td>${state(row)}</td><td><button class="ghost" type="button" data-token-revoke="${esc(row.id)}" data-token-label="${esc(row.label)}">Revoke</button></td></tr>`).join('')}</tbody></table></div>`
    : '<div class="empty">No tokens yet.</div>';
  el.innerHTML = `${table}
    <form class="row settings-token-form" id="settings-token-form">
      <label>Label <input name="label" type="text" required maxlength="80" autocomplete="off" placeholder="CI script" aria-label="Token label"></label>
      <label>Expires in <input name="days" type="number" inputmode="numeric" min="1" max="365" value="90" required aria-label="Days until the token expires"> days</label>
      <button class="primary" type="submit">New token</button>
    </form>`;
  el.querySelectorAll('[data-token-revoke]').forEach(button => { button.onclick = () => void settingsTokenRevoke(button.dataset.tokenRevoke, button.dataset.tokenLabel); });
  const form = el.querySelector('#settings-token-form');
  form.onsubmit = async event => {
    event.preventDefault();
    const label = form.label.value.trim(), days = Number(form.days.value);
    if (!label) { form.label.focus(); return; }
    const button = form.querySelector('button[type=submit]'); button.disabled = true;
    try {
      const issued = await post('/v2/me/tokens', {label, expires_in_days: days});
      settingsTokenShow(issued);
    } catch (error) { toast(error.message, true); button.disabled = false; }
  };
}
function settingsTokenShow(issued) {
  const dialog = document.createElement('dialog'); dialog.className = 'tmodal agent-credential';
  dialog.innerHTML = `<header><h2>Token ${esc(issued.label)}</h2><button class="ghost" type="button" data-close>Close</button></header>
    <div class="agent-credential-body">
      <p>Shown once. It acts as you, and expires ${esc(new Date(issued.expires_at).toLocaleDateString())}.</p>
      <label>Token<div class="row"><code class="agent-token" data-token>${esc(issued.token)}</code><button class="ghost" type="button" data-copy-token>Copy</button></div></label>
      <label>In a shell, for the <code>hub</code> command line and scripts:<div class="row"><code data-command>export HUB_API_URL=${esc(location.origin)} HUB_TOKEN=${esc(issued.token)}</code><button class="ghost" type="button" data-copy-command>Copy</button></div></label>
    </div>`;
  dialog.querySelector('[data-close]').onclick = () => dialog.close();
  dialog.querySelector('[data-copy-token]').onclick = () => void copyText(issued.token).then(() => toast('Token copied'));
  dialog.querySelector('[data-copy-command]').onclick = () => void copyText(dialog.querySelector('[data-command]').textContent).then(() => toast('Command copied'));
  dialog.onclose = () => { dialog.remove(); void renderSettingsTokens(); };
  document.body.appendChild(dialog); dialog.showModal();
}
// Connect an agent: ui/connect-agent.js.
$('#connect-agent').onclick = () => window.connectAgent?.();
async function settingsTokenRevoke(id, label) {
  if (!confirm(`Revoke the token ${label}? Anything using it stops at once.`)) return;
  try { await post(`/v2/me/tokens/${encodeURIComponent(id)}/revoke`, {}); toast(`Token ${label} revoked`); }
  catch (error) { toast(error.message, true); }
  await renderSettingsTokens();
}
function agentConfigYaml(setup) {
  return `mcp_servers:\n  tico:\n    url: "${setup.mcp_servers.tico.url}"\n    headers:\n      Authorization: "Bearer \${TICO_AGENT_TOKEN}"\n# .env in the profile directory:\nTICO_AGENT_TOKEN=${setup.token}`;
}
async function settingsAgentRevoke(slug) {
  const e = S.emps.find(row => row.name === slug); if (!e) return;
  if (!confirm(`Revoke the agent credential for ${e.display_name}? Its box loses access at once; the bot record stays.`)) return;
  try { await post(`/v2/bots/${encodeURIComponent(slug)}/agent-credential/revoke`, {}); toast(`${e.display_name} credential revoked`); await loadSettings(); }
  catch (error) { toast(error.message, true); }
}
// The Add computer flow, shared by Settings and the first-run wizard: one private short-lived
// setup file, downloaded by the browser. The commands that consume it are shown by the caller.
// A Linux or cloud server needs no file: the one-time code goes on the docker run line.
async function enrollmentCode(operator) { return post('/v2/enrollments', {operator}); }
const shellSafe = value => String(value).replace(/["$`\\\n]/g, '');
// The release the server runs, as the tag its installer and images carry; '' for a build with none.
const serverReleaseTag = () => {
  const version = String(S.config?.runner_compat?.version || '').replace(/^v/, '');
  return /^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$/.test(version) ? 'v' + version : '';
};
// The installer sets the runner up with its updater sidecar, so it follows the server's releases;
// a bare `docker run` has no sidecar and stays where it is.
function dockerRunnerCommands(code, label, runtime) {
  const tag = serverReleaseTag(), quoted = `"${shellSafe(label)}"`;
  const installer = tag ? `https://github.com/ticoteam/tico/releases/download/${tag}/install.sh`
                        : 'https://github.com/ticoteam/tico/releases/latest/download/install.sh';
  return [
    ['Set up the runner on the server (installs Docker if it is missing; keeps itself on this server\'s release)',
     `curl -fsSL ${installer} | sh -s -- --runner --url ${runnerUrl()} --code ${code} --label ${quoted}`],
    ['Sign the bots in to a model, once (the runner installs the model CLI first; give it a minute)',
     `docker exec -it tico-runner ${runtime === 'claude' ? 'claude setup-token' : 'codex login --device-auth'}`],
    ['Or with plain Docker instead of the line above. It has no updater, so it will not follow the server\'s releases',
     `docker run -d --name tico-runner --restart unless-stopped -v tico-runner:/home/runner ghcr.io/ticoteam/tico-runner:${tag || 'latest'} join --url ${runnerUrl()} --code ${code} --label ${quoted}`],
  ];
}
async function enrollmentDownload(operator, label) {
  const filename = `tico-enrollment-${operator}-${Date.now().toString(36)}.json`;
  const enrollment = await enrollmentCode(operator);
  const setup = {...enrollment, operator, label, url: runnerUrl()};
  const url = URL.createObjectURL(new Blob([JSON.stringify(setup)], {type:'application/json'}));
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return filename;
}
function renderSettingsMachines() {
  const el = $('#set-machines'); if (!el) return;
  const cards = SETTINGS_DATA.machines.map(machine => {
    const online = !machine.revoked_at && machine.last_seen && Date.now() - new Date(machine.last_seen) < 60000;
    // Only what the company's providers or an assigned bot use, plus anything installed anyway: a
    // model nobody enabled being absent is not a problem. An older server sends no list; all show then.
    const needed = Array.isArray(machine.needed_runtimes) ? new Set(machine.needed_runtimes) : null;
    const isNeeded = name => !needed || needed.has(name);
    const runtimes = Object.entries(machine.readiness?.runtimes || {}).filter(([name, value]) => isNeeded(name) || value.installed);
    // Codex and Claude sign in from here; the computer prints the link and code, this page shows them.
    const signIn = (name, value) => S.me?.role === 'owner' && online && value.installed && value.authenticated !== 'ready' && ['codex', 'claude'].includes(name)
      ? ` <button class="ghost machine-signin" type="button" data-model-login data-runner="${esc(machine.id)}" data-runtime="${esc(name)}" data-machine="${esc(machine.label)}">Sign in</button>` : '';
    const runtime = runtimes.map(([name, value]) => `<span class="machine-runtime-item"><span class="pill ${value.authenticated === 'ready' ? 'ok' : value.authenticated === 'rejected' ? 'fail' : value.authenticated === 'unknown' || !isNeeded(name) ? 'waiting' : 'fail'}" title="${esc(value.detail || '')}">${esc(name)} · ${esc(value.authenticated === 'rejected' ? 'sign-in rejected' : value.authenticated)}</span>${signIn(name, value)}${value.authenticated === 'rejected'
      ? `<span class="err machine-rejected" data-rejected="${esc(name)}">${value.rejected_at ? esc(ago(value.rejected_at)) + '. ' : ''}${value.rejected_reason ? esc(value.rejected_reason) + '. ' : ''}Replace the key in the runner's secrets, or sign in again. It takes no work that needs ${esc(name)} until then.</span>` : ''}</span>`).join('');
    // The model CLIs the computer runs: version, pin, and the owner's Update / Pin actions. The
    // computer applies them between turns (backend/harness_actions.py, runner/harness_tools.py).
    const asked = new Set((machine.harness_actions || []).filter(row => ['requested', 'running'].includes(row.state)).map(row => `${row.harness}:${row.action}`));
    const harnessAction = (id, action, label, value) => {
      const waiting = asked.has(`${id}:${action}`);
      return ` <button class="ghost" type="button" data-harness-action="${esc(action)}" data-runner="${esc(machine.id)}" data-harness="${esc(id)}"${waiting ? ' disabled' : ''}>${waiting ? 'Requested' : esc(label)}</button>`;
    };
    const harnessChip = ([id, value]) => {
      const owner = S.me?.role === 'owner' && online && value.managed;
      const busy = value.state !== 'idle';
      const text = `${value.name || id} ${value.installed ? (value.version || 'installed') : 'not installed'}${value.pinned ? ' · pinned' : ''}${value.update_available ? ` · ${value.latest || 'update'} available` : ''}${busy ? ` · ${value.state}` : ''}`;
      const tone = value.state === 'failed' ? 'fail' : !value.installed || busy ? 'waiting' : value.update_available ? 'waiting' : 'ok';
      const buttons = owner && value.installed && !busy ? [
        value.update_available ? harnessAction(id, 'update', 'Update') : '',
        value.pinned ? harnessAction(id, 'unpin', 'Resume updates') : (value.version ? harnessAction(id, 'pin', 'Pin to this version') : '')].join('') : '';
      const title = [value.detail, value.managed ? '' : (value.installed ? 'Installed outside Tico; update it where it was installed' : '')].filter(Boolean).join(' · ');
      return `<span class="machine-harness-item" data-harness-chip="${esc(id)}"><span class="pill ${tone}" title="${esc(title)}">${esc(text)}</span>${buttons}</span>`;
    };
    const harnesses = Object.entries(machine.readiness?.harnesses || {}).filter(([, value]) => value.installed || value.wanted || value.state !== 'idle').map(harnessChip).join('');
    const failures = Object.values(machine.readiness?.bots || {}).filter(value => !value.ready).length;
    return `<tr class="machine-card"><td><strong>${esc(machine.label)}</strong><span class="settings-cell-note">${esc(machine.version || 'version not reported')}${machine.platform ? ` · ${esc(machine.platform)}` : ''}</span>${window.runnerUpdateHtml?.(machine.update) || ''}</td>
      <td>${esc(settingsPersonName(machine.operator))}${machine.revoked_at ? '' : settingsIsAdmin()
        ? `<label class="settings-cell-note machine-members"><input type="checkbox" data-member-bots="${esc(machine.id)}" ${machine.accepts_member_bots ? 'checked' : ''}> Accepts members' bots</label>`
        : machine.accepts_member_bots ? '<span class="settings-cell-note">Accepts members\' bots</span>' : ''}</td>
      <td>${machine.bots.length}${failures ? ` <span class="err">· ${failures} not ready</span>` : ''}</td>
      <td><div class="machine-runtime">${runtime || '<span class="muted">—</span>'}</div>${harnesses ? `<div class="machine-harnesses" aria-label="Tools on ${esc(machine.label)}">${harnesses}</div>` : ''}</td>
      <td>${machine.revoked_at ? '<span class="pill fail">revoked</span>' : online ? '<span class="pill ok">online</span>' : '<span class="pill">offline</span>'}${machine.last_seen ? `<span class="settings-cell-note">${esc(ago(machine.last_seen))}</span>` : ''}</td></tr>`;
  }).join('');
  el.onchange = async event => {
    const box = event.target.closest('[data-member-bots]');
    if (!box) return;
    box.disabled = true;
    try {
      await post(`/v2/runners/${encodeURIComponent(box.dataset.memberBots)}/member-bots`, {accepts: box.checked});
      toast(box.checked ? 'Members\' bots may now go on this computer' : 'Members\' bots no longer go on this computer');
      await loadSettings();
    } catch (error) { toast(error.message, true); box.checked = !box.checked; box.disabled = false; }
  };
  el.onclick = async event => {
    const button = event.target.closest('[data-harness-action]');
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      await post(`/v2/runners/${encodeURIComponent(button.dataset.runner)}/harness-actions`, {harness: button.dataset.harness, action: button.dataset.harnessAction});
      toast(button.dataset.harnessAction === 'update' ? 'Update requested; the computer applies it when no turn is using it' : 'Saved');
      await loadSettings();
    } catch (error) { toast(error.message, true); button.disabled = false; }
  };
  const people = S.me?.role === 'owner' ? SETTINGS_DATA.people : SETTINGS_DATA.people.filter(person => person.id === S.me?.id);
  const agents = (SETTINGS_DATA.agents || []).map(agent => `<tr class="machine-card" data-agent-row="${esc(agent.bot)}"><td><strong><a href="#/bot/${esc(agent.bot)}">${esc(agent.display_name || agent.bot)}</a></strong><span class="settings-cell-note">${esc(agentKind(agent))}${agent.profile ? ` · profile ${esc(agent.profile)}` : ''}${agent.version ? ` · ${esc(agent.version)}` : ''}${agent.platform ? ` · ${esc(agent.platform)}` : ''}</span></td>
      <td>${esc(settingsPersonName(S.emps.find(row => row.name === agent.bot)?.operator))}</td>
      <td>${agent.model ? `${esc(agent.model)}${agent.provider ? `<span class="settings-cell-note">${esc(agent.provider)}</span>` : ''}` : '<span class="muted">—</span>'}</td>
      <td>${agent.revoked_at ? '<span class="pill fail">revoked</span>' : agent.online ? '<span class="pill ok">reporting in</span>' : '<span class="pill">not reporting</span>'}${agent.last_seen ? `<span class="settings-cell-note">${esc(ago(agent.last_seen))}</span>` : ''}</td></tr>`).join('');
  el.innerHTML = `${cards ? `<div class="scroll"><table class="settings-table settings-machines"><thead><tr><th>Computer</th><th>Operator</th><th>Bots</th><th>Runtimes</th><th>Status</th></tr></thead><tbody>${cards}</tbody></table></div>` : '<div class="empty">No machines registered yet.</div>'}
    ${agents ? `<h3 class="settings-agents-title">External agents</h3><div class="scroll"><table class="settings-table"><thead><tr><th>Agent</th><th>Operator</th><th>Model</th><th>Status</th></tr></thead><tbody>${agents}</tbody></table></div>` : ''}
    <div class="machine-enroll"><select class="settings-inline-select" id="machine-operator" aria-label="Machine operator">
      ${people.map(person => `<option value="${esc(person.id)}" ${person.id === S.me?.id ? 'selected' : ''}>${esc(person.name || person.id)}</option>`).join('')}</select>
      <select class="settings-inline-select" id="machine-kind" aria-label="Kind of computer"><option value="mac">Mac</option><option value="linux">Linux or cloud server</option></select>
      <input id="machine-label" type="text" autocomplete="off" aria-label="Computer name" placeholder="Computer name" value="${esc(settingsPersonName(people.find(person => person.id === S.me?.id)?.id || people[0]?.id) + "'s Mac")}">
      <button class="primary" type="button" id="register-machine">Add computer</button>
      <p class="machine-enroll-status" id="machine-enroll-status"></p></div>`;
  const machineDefaultLabel = () => `${settingsPersonName($('#machine-operator').value)}'s ${$('#machine-kind').value === 'linux' ? 'server' : 'Mac'}`;
  $('#machine-operator').onchange = () => { $('#machine-label').value = machineDefaultLabel(); };
  $('#machine-kind').onchange = () => { $('#machine-label').value = machineDefaultLabel(); };
  $('#register-machine').onclick = async event => {
    const operator = $('#machine-operator').value, label = $('#machine-label').value.trim();
    if (!label) { toast('Give this computer a recognizable name', true); return; }
    event.target.disabled = true;
    try {
      const status = $('#machine-enroll-status');
      if ($('#machine-kind').value === 'linux') {
        const {code} = await enrollmentCode(operator);
        const commands = dockerRunnerCommands(code, label, S.config?.default_runtime);
        status.innerHTML = `Code for <strong>${esc(label)}</strong>, good 15 minutes. Run on that server:${commands.map(([note, command], i) => `<br><span class="muted">${esc(note)}</span><br><code>${esc(command)}</code> <button class="ghost" type="button" data-machine-copy="${i}">Copy</button>`).join('')}`;
        status.querySelectorAll('[data-machine-copy]').forEach(button => button.onclick = () =>
          void copyText(commands[Number(button.dataset.machineCopy)][1]).then(() => toast('Command copied')));
        return;
      }
      const filename = await enrollmentDownload(operator, label);
      status.innerHTML = `Setup file downloaded. Run on that Mac:<br><code>scripts/setup-runner.sh "$HOME/Downloads/${esc(filename)}"</code> <button class="ghost" type="button" id="copy-enrollment-command">Copy command</button> <button class="ghost" type="button" id="copy-enrollment-prompt">Copy AI setup prompt</button>`;
      $('#copy-enrollment-command').onclick = () => void copyText(`scripts/setup-runner.sh "$HOME/Downloads/${filename}"`).then(() => toast('Setup command copied'));
      $('#copy-enrollment-prompt').onclick = () => void copyText(settingsEnrollmentPrompt(operator, filename)).then(() => toast('Machine setup prompt copied'));
    } catch (error) { toast(error.message, true); }
    finally { event.target.disabled = false; }
  };
}
function settingsSetupPrompt(slug) {
  const rows = (slug ? S.emps.filter(e => e.name === slug) : S.emps).map(e => {
    const owners = (e.users || []).map(person => person.name || person.id).join(', ') || 'nobody';
    const machine = e.machine?.label || `not assigned (reserved for ${settingsPersonName(e.operator)})`;
    return `- ${e.display_name} [${e.name}]: people=${owners}; model=${e.model || 'not set'}; effort=${e.reasoning_effort || e.effort || 'not set'}; machine=${machine}`;
  });
  return `Help me update the ${appName()} bot setup.\n\nCurrent cloud state:\n${rows.join('\n')}\n\nAsk me what I want to change, then use the formal owner-admin API. Do not edit the production SQLite database directly. Bot definitions in the ${appName()} backend are authoritative after the one-time bootstrap: create a bot with POST /api/v2/bots and update its name, description, hierarchy, status, repository, or room type with POST /api/v2/bots/{bot}/definition. No ${appName()} application deploy or registry publish is required. Provision the bot's repository on any computer that will run it, and verify runner readiness. Preserve tasks and conversation history. Change a bot's model, reasoning effort, or registered computer through POST /api/v2/bots/{bot}/transitions so ${appName()} checkpoints every current session before applying it. If the transition is blocked because the old runner is unavailable, explain what continuity will be lost and ask me before calling apply-without-checkpoint. Use revision and assignment-generation checks. People are still managed separately from bot definitions.`;
}
function settingsEnrollmentPrompt(operator, filename) {
  return `Set up a ${appName()} local runner for ${settingsPersonName(operator)} using the downloaded ${filename} enrollment file. Work from the Tico checkout on the target Mac. Locate the person's bot repositories, run scripts/setup-runner.sh "$HOME/Downloads/${filename}", then run runtime/runner-venv/bin/python -m runner doctor and resolve every repository, runtime login (Codex or Claude), model, or configuration-readiness problem. Never print or commit the enrollment code or runner token and never open an inbound port. Do not install the private processing or connector workers. Registration must not assign bots; when the machine is ready, tell me to return to ${appName()} Settings and choose it for each intended bot so existing sessions are checkpointed before the move.`;
}
function settingsCopyPrompt(slug) {
  void copyText(settingsSetupPrompt(slug)).then(() => toast(`${slug ? settingsBotName(slug) + ' ' : ''}setup prompt copied`)).catch(() => toast('Could not copy the setup prompt', true));
}
