/* ui/app/settings-webhooks.js — Settings > Webhooks: incoming, outgoing, through Tico Gateway
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// Incoming (backend/triggers.py): an address a sender calls. Routines on `webhook.<id>` and rules on `webhook.received`
// listen to it. Outgoing (backend/webhooks.py): endpoints Tico posts its events to. Through Tico Gateway
// (backend/hook_relay.py): a second address for an incoming webhook, held by Tico Gateway, for a server the internet
// cannot reach. A secret is shown once, right after it is made, and is gone from the next screen.
const WH_PRESETS = [['none', 'None'], ['hmac', 'HMAC'], ['github', 'GitHub'], ['standard', 'Standard Webhooks'], ['stripe', 'Stripe']];
// Where a preset reads the event type (backend/trigger_presets.py TYPE_FROM): the API has no list of presets to read.
const WH_TYPE_FROM = {github: 'X-GitHub-Event', stripe: '/type', standard: '/type'};
const WH_UNHEARD = [['log', 'Log it'], ['note', 'Tell the owner']];
const WH_OUTCOMES = {accepted: ['ok', 'Accepted'], refused: ['fail', 'Refused'], replayed: ['', 'Rerun']};
const WH_SEND_STATES = {delivered: 'ok', failed: 'fail', ready: 'waiting', sending: 'waiting', cancelled: '', withheld: ''};
const WH_TABS = [['incoming', 'Incoming'], ['outgoing', 'Outgoing'], ['gateway', 'Through Tico Gateway', 'Gateway']];
// The open tab and item, and the one set of secrets on screen: {id, url?, signing?, relay?} for an incoming webhook,
// {id, secret} for an endpoint.
const WH = {tab: 'incoming', trigger: '', hook: '', shown: null, hookShown: null};
let WH_RUN = 0, WH_HOOKS = null;
// The event catalog (backend/event_catalog.py): the rules editor, the routine editor and the endpoint picker read it.
let EVENT_TYPES = [], EVENT_TYPES_P = null;
function eventTypesLoad() {
  EVENT_TYPES_P ||= get('/v2/event-types').then(d => (EVENT_TYPES = d.items || [])).catch(e => { EVENT_TYPES_P = null; throw e; });
  return EVENT_TYPES_P;
}
const catalogWords = name => (EVENT_TYPES.find(t => t.name === name || (t.aliases || []).includes(name))?.description || '').replace(/\.$/, '');
async function whHooksLoad() {
  try { WH_HOOKS = (await get('/v2/webhooks?limit=200')).items || []; } catch { WH_HOOKS = WH_HOOKS || []; }
  return WH_HOOKS;
}
const whPresetName = p => (WH_PRESETS.find(([k]) => k === p) || [p, p])[1];
const whPlural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const whMine = t => !t.builtin && (S.me?.role === 'owner' || t.created_by === 'human:' + (S.me?.id || ''));
const whOpt = (v, label, cur) => `<option value="${esc(v)}"${String(v) === String(cur) ? ' selected' : ''}>${esc(label)}</option>`;

async function renderSettingsWebhooks() {
  const el = $('#set-webhooks'); if (!el) return;
  const seg = $('#settings-webhooks-view');
  if (seg) {
    seg.querySelectorAll('[data-wh-tab]').forEach(b => b.setAttribute('aria-checked', String(b.dataset.whTab === WH.tab)));
    seg.onclick = ev => {
      const b = ev.target.closest('[data-wh-tab]');
      if (!b || b.dataset.whTab === WH.tab) return;
      Object.assign(WH, {tab: b.dataset.whTab, trigger: '', hook: '', shown: null, hookShown: null});
      void renderSettingsWebhooks();
    };
  }
  el.onclick = whClick;
  const run = ++WH_RUN;
  try {
    if (WH.tab === 'outgoing') await (WH.hook ? whHookDetail(el, run) : whHooks(el, run));
    else if (WH.tab === 'gateway') await whGateway(el, run);
    else await (WH.trigger ? whTriggerDetail(el, run) : whTriggers(el, run));
  } catch (e) { if (run === WH_RUN) el.innerHTML = `<div class="err">${esc(e.message)}</div>`; }
}
function whSecretHTML(label, value, key) {
  return `<div class="trigger-secret" role="status" data-wh-secret="${key}"><p><strong>${esc(label)}</strong> <span class="muted">Shown once</span></p>
    <div class="row"><code class="trigger-url">${esc(value)}</code><button class="ghost" type="button" data-wh-copy="${key}">Copy</button></div></div>`;
}
function whShownHTML(id) {
  const s = WH.shown;
  if (!s || s.id !== id) return '';
  return (s.url ? whSecretHTML('Address', s.url, 'url') : '') + (s.signing ? whSecretHTML('Signing secret', s.signing, 'signing') : '')
    + (s.relay ? whSecretHTML('Gateway address', s.relay, 'relay') : '');
}
function whHeadHTML(title, pills, actions) {
  return `<div class="wh-head"><button class="ghost" type="button" data-wh-back aria-label="Back">‹ Back</button>
    <h3>${esc(title)}</h3>${pills}<span class="spacer"></span><div class="wh-actions">${actions}</div></div>`;
}
async function whClick(ev) {
  const copy = ev.target.closest('[data-wh-copy]');
  if (copy) {
    const key = copy.dataset.whCopy, value = key === 'secret' ? WH.hookShown?.secret : WH.shown?.[key];
    if (value) { await copyText(value); toast('Copied'); }
    return;
  }
  if (ev.target.closest('[data-wh-gateway-link]')) { ev.preventDefault(); settingsShow('gateway'); return; }
  if (ev.target.closest('[data-wh-back]')) {
    Object.assign(WH, {trigger: '', hook: '', shown: null, hookShown: null});
    void renderSettingsWebhooks();
  }
}
// A dialog in the house form style; Cancel and Escape close it, and closing removes it.
function whDialog(title, body, footer = '') {
  const dialog = document.createElement('dialog');
  dialog.className = 'tmodal task-rule-dialog wh-dialog';
  dialog.setAttribute('aria-label', title);
  dialog.innerHTML = `<form class="task-rule-form" novalidate><header><h2>${esc(title)}</h2><button type="button" class="ghost" data-close>Cancel</button></header>
    ${body}<p class="err" role="status" data-wh-error></p>${footer ? `<footer>${footer}</footer>` : ''}</form>`;
  dialog.addEventListener('close', () => dialog.remove());
  dialog.querySelectorAll('[data-close]').forEach(b => { b.onclick = () => dialog.close(); });
  document.body.appendChild(dialog); dialog.showModal();
  return dialog;
}
// A form's submit with its button held and any refusal shown in the dialog.
function whSubmit(dialog, fn) {
  const form = dialog.querySelector('form'), error = dialog.querySelector('[data-wh-error]');
  form.onsubmit = async ev => {
    ev.preventDefault();
    if (!form.reportValidity()) return;
    const button = form.querySelector('[type="submit"]'); if (button) button.disabled = true; error.textContent = '';
    try { await fn(new FormData(form), form); } catch (e) { error.textContent = e.message || 'Try again'; } finally { if (button) button.disabled = false; }
  };
}

// ---------------------------------------------------------------------------------------------------------- Incoming
async function whTriggersFresh() {
  ROUTINE_TRIGGERS = (await get('/v2/triggers', {fresh: true})).triggers || [];
  return ROUTINE_TRIGGERS;
}
function whCountsHTML(t) {
  return `<span class="tnum">${t.received_24h} in 24h</span>${t.refused_24h ? ` · <span class="wh-bad tnum">${t.refused_24h} refused</span>` : ''}`;
}
function whTriggerPills(t) {
  return (t.builtin ? '<span class="pill">Built-in</span>' : '') + (t.preset && t.preset !== 'none' ? `<span class="pill">${esc(whPresetName(t.preset))}</span>` : '')
    + (t.relay ? '<span class="pill">Gateway</span>' : '');
}
async function whTriggers(el, run) {
  const list = await whTriggersFresh();
  if (run !== WH_RUN) return;
  el.innerHTML = `<div class="settings-bots-filters"><button type="button" class="primary" data-wh-new>New webhook</button></div>
    ${list.length ? `<div class="wh-list" data-wh-triggers>${list.map(t => `<button type="button" class="wh-row" data-wh-open="${esc(t.id)}">
        <span class="wh-name"><strong>${esc(t.name)}</strong>${whTriggerPills(t)}</span>
        <span class="wh-meta">${whCountsHTML(t)}</span>
        <span class="wh-meta muted">${t.last_received ? esc(ago(t.last_received)) : 'Never called'}</span></button>`).join('')}</div>`
      : '<div class="empty">No webhooks yet.</div>'}`;
  el.querySelector('[data-wh-new]').onclick = () => whTriggerDialog(null);
  el.querySelectorAll('[data-wh-open]').forEach(b => { b.onclick = () => { WH.trigger = b.dataset.whOpen; WH.shown = null; void renderSettingsWebhooks(); }; });
}
// Who a rule wakes: its own bot on a bot row, else the bot it names. A note does not wake.
function whRuleWakes(r) {
  if (r.then === 'wake') return r.scope_kind === 'bot' ? r.scope_id : r.params?.bot || '';
  return r.then === 'action' && r.params?.action === 'wake_bot' ? r.params.bot || '' : '';
}
function whRuleWords(r) {
  const types = ruleList(r.when?.type);
  return `<b>WHEN</b> ${types.length ? 'type ' + esc(types.join(' or ')) : 'any call'} <b>THEN</b> ${esc(ruleThenWords(r))}`;
}
async function whTriggerDetail(el, run) {
  const id = WH.trigger, path = `/v2/triggers/${encodeURIComponent(id)}`;
  const [list, log, rules] = await Promise.all([whTriggersFresh(), get(path + '/deliveries', {fresh: true}),
    get('/v2/rules?event=webhook.received&limit=200', {fresh: true}).catch(() => ({rules: []}))]);
  if (run !== WH_RUN) return;
  const t = list.find(x => x.id === id);
  if (!t) { WH.trigger = ''; return whTriggers(el, run); }
  const mine = whMine(t), may = mine || (t.builtin && S.me?.role === 'owner');
  const heard = (rules.rules || []).filter(r => !r.built_in && r.event === 'webhook.received' && (!r.when?.trigger || ruleList(r.when.trigger).includes(id)));
  const routineBots = new Set(t.routines.map(r => r.bot));
  const twice = [...new Set(heard.filter(r => r.enabled !== false).map(whRuleWakes).filter(b => b && routineBots.has(b)))];
  const rows = log.deliveries || [];
  const actions = mine ? `<button class="ghost" type="button" data-wh-edit>Edit</button><button class="ghost" type="button" data-wh-rotate>New secret</button>
      <button class="ghost" type="button" data-wh-sign>Signing</button><button class="ghost" type="button" data-wh-delete>Delete</button>`
    : may ? '<button class="ghost" type="button" data-wh-edit>Edit</button>' : '';
  el.innerHTML = `${whHeadHTML(t.name, whTriggerPills(t), actions)}
    ${whShownHTML(id)}
    <dl class="wh-facts">
      ${t.builtin ? '' : `<dt>Address</dt><dd><code>${esc(t.url)}/…</code></dd>
      <dt>Gateway</dt><dd>${t.relay ? `<code>${esc(t.relay.address_prefix)}/…</code>` : '<span class="muted">None</span>'}</dd>
      <dt>Signing</dt><dd>${esc(whPresetName(t.preset || 'none'))}</dd>
      <dt>Type from</dt><dd>${t.type_from ? `<code>${esc(t.type_from)}</code>` : '<span class="muted">None</span>'}</dd>
      <dt>Per hour</dt><dd class="tnum">${t.hourly}</dd>`}
      <dt>Keep</dt><dd>${whPlural(t.keep_days, 'day')}</dd>
      ${t.builtin ? '' : `<dt>If nothing listens</dt><dd>${esc((WH_UNHEARD.find(([k]) => k === t.unheard) || ['', 'Log it'])[1])}</dd>`}
      <dt>24h</dt><dd>${whCountsHTML(t)}</dd>
    </dl>
    <h4 class="wr-sub">Listeners</h4>
    ${twice.length ? `<p class="wh-warn" role="note" data-wh-twice>${esc(twice.map(empName).join(', '))}: a routine gives a task and a rule wakes the bot on every call.</p>` : ''}
    <div class="wh-listeners" data-wh-listeners>${t.routines.map(r => `<div class="wh-li"><span class="pill">Routine</span>
        <a href="#" data-wh-routine="${esc(r.id)}" data-bot="${esc(r.bot)}">${esc(r.title)}</a><span class="muted">${esc(empName(r.bot))}</span></div>`).join('')}
      ${heard.map(r => `<div class="wh-li${r.enabled === false ? ' wr-off' : ''}"><span class="pill">Rule</span>
        <span class="wr-text">${whRuleWords(r)}</span><span class="muted">${esc(ruleScopeWords(r))}</span></div>`).join('')}
      ${t.routines.length || heard.length ? '' : '<span class="muted">None</span>'}</div>
    ${rulesMayAdd() ? '<div class="row wh-li-add"><button class="ghost" type="button" data-wh-add-rule>Add rule</button></div>' : ''}
    <h4 class="wr-sub">Calls</h4>
    ${rows.length ? `<div class="wh-calls" data-wh-calls>${rows.map(r => {
      const [tone, word] = WH_OUTCOMES[r.outcome] || ['', r.outcome];
      const what = r.outcome === 'refused' ? esc(r.reason) : `${whPlural(r.tasks, 'task')} · ${whPlural(r.rules || 0, 'rule')}`;
      return `<div class="wh-call" data-wh-call="${esc(r.delivery)}">
        <span class="wh-time" title="${esc(r.received_at)}">${esc(ago(r.received_at))}</span>
        <span class="wh-type">${r.type ? `<code>${esc(r.type)}</code>` : '<span class="muted">No type</span>'}</span>
        <span class="wh-outcome"><span class="pill ${tone}">${esc(word)}</span> <span class="muted">${what}</span></span>
        <span class="tnum muted">${esc(bytes(r.bytes || 0))}</span>
        <span class="muted">${esc(r.via === 'gateway' ? 'Gateway' : r.via === 'direct' ? 'Direct' : r.via || '')}</span>
        <span class="wh-call-ctl">${r.stored && may ? `<button class="ghost" type="button" data-wh-payload>View payload</button>` : ''}
          ${r.stored && mine ? '<button class="ghost" type="button" data-wh-replay>Run again</button>' : ''}</span></div>`;
    }).join('')}</div>` : '<div class="empty">No calls yet.</div>'}`;
  const on = (sel, fn) => { const b = el.querySelector(sel); if (b) b.onclick = fn; };
  on('[data-wh-edit]', () => whTriggerDialog(t));
  on('[data-wh-sign]', () => whSigningDialog(t));
  on('[data-wh-rotate]', () => void whRotate(t));
  on('[data-wh-delete]', () => void whTriggerDelete(t));
  on('[data-wh-add-rule]', async () => {
    const dialog = await ruleEditor(null, {event: 'webhook.received', when: {trigger: id}});
    dialog?.addEventListener('close', () => void renderSettingsWebhooks());
  });
  el.querySelectorAll('[data-wh-routine]').forEach(a => { a.onclick = async ev => {
    ev.preventDefault();
    const r = routineById(a.dataset.whRoutine) || ((await get(`/v2/bots/${encodeURIComponent(a.dataset.bot)}/routines`).catch(() => ({}))).routines || []).find(x => x.id === a.dataset.whRoutine);
    if (r) routineEditorOpen({...r, employee: a.dataset.bot});
  }; });
  el.querySelectorAll('[data-wh-call]').forEach(row => {
    const delivery = row.dataset.whCall;
    const view = row.querySelector('[data-wh-payload]'), again = row.querySelector('[data-wh-replay]');
    if (view) view.onclick = () => void whPayload(id, delivery);
    if (again) again.onclick = async () => {
      again.disabled = true;
      try {
        const r = (await post(`${path}/deliveries/${encodeURIComponent(delivery)}/replay`, {})).replay;
        toast(`Ran again: ${whPlural(r.tasks, 'task')}, ${whPlural(r.rules || 0, 'rule')}`);
        void renderSettingsWebhooks();
      } catch (e) { toast(e.message, true); again.disabled = false; }
    };
  });
}
async function whPayload(id, delivery) {
  let d;
  try { d = (await get(`/v2/triggers/${encodeURIComponent(id)}/deliveries/${encodeURIComponent(delivery)}`, {fresh: true})).delivery; }
  catch (e) { toast(e.message, true); return; }
  let body = d.body ?? '';
  try { body = JSON.stringify(JSON.parse(body), null, 2); } catch { /* not JSON: shown as sent */ }
  const headers = Object.entries(d.headers || {}).map(([k, v]) => `${k}: ${v}`).join('\n');
  whDialog('Payload', `<p class="muted wh-payload-meta">${esc(ago(d.received_at))}${d.type ? ` · <code>${esc(d.type)}</code>` : ''} · ${esc(bytes(d.bytes || 0))}</p>
    ${d.expired ? '<p class="muted">No longer kept.</p>' : `<h4 class="wr-sub">Headers</h4><pre class="wh-pre" data-wh-headers>${esc(headers)}</pre>
    <h4 class="wr-sub">Body</h4><pre class="wh-pre" data-wh-body>${esc(body)}</pre>`}`);
}
function whTriggerDialog(t) {
  const builtin = !!t?.builtin;
  const fields = builtin ? `<label>Keep days<input name="keep_days" type="number" min="1" max="30" required value="${esc(t.keep_days)}"></label>`
    : `<label>Name<input name="name" maxlength="100" required autocomplete="off" value="${esc(t?.name || '')}"></label>
    ${t ? '' : `<label>Signing<select name="preset" data-wh-preset>${WH_PRESETS.map(([k, v]) => whOpt(k, v, 'none')).join('')}</select></label>
    <label data-wh-secret-field hidden>Signing secret<input name="secret" maxlength="300" autocomplete="off" spellcheck="false" placeholder="Leave empty to make one"></label>`}
    <label>Type from<input name="type_from" maxlength="120" autocomplete="off" spellcheck="false" value="${esc(t?.type_from || '')}" placeholder="Header or /json/path"></label>
    <label>Per hour<input name="hourly" type="number" min="1" max="600" required value="${esc(t?.hourly || 60)}"></label>
    <label>Keep days<input name="keep_days" type="number" min="1" max="30" required value="${esc(t?.keep_days || 7)}"></label>
    <label>If nothing listens<select name="unheard">${WH_UNHEARD.map(([k, v]) => whOpt(k, v, t?.unheard || 'log')).join('')}</select></label>`;
  const dialog = whDialog(t ? (builtin ? t.name : 'Edit webhook') : 'New webhook', fields, `<button type="submit" class="primary">${t ? 'Save' : 'Create'}</button>`);
  const form = dialog.querySelector('form'), preset = form.elements.preset;
  if (preset) preset.onchange = () => {
    dialog.querySelector('[data-wh-secret-field]').hidden = preset.value === 'none';
    const was = form.elements.type_from.value;
    if (!was || Object.values(WH_TYPE_FROM).includes(was)) form.elements.type_from.value = WH_TYPE_FROM[preset.value] || '';
  };
  whSubmit(dialog, async v => {
    const num = k => Number(v.get(k));
    if (builtin) {
      await post(`/v2/triggers/${encodeURIComponent(t.id)}`, {keep_days: num('keep_days')});
      dialog.close(); void renderSettingsWebhooks(); return;
    }
    const settings = {type_from: String(v.get('type_from') || '').trim(), hourly: num('hourly'), keep_days: num('keep_days'), unheard: String(v.get('unheard'))};
    if (t) {
      await post(`/v2/triggers/${encodeURIComponent(t.id)}`, {name: String(v.get('name')).trim(), ...settings});
      dialog.close(); void renderSettingsWebhooks(); return;
    }
    // Making one is three calls (create, signing, settings): the create answer carries only the address.
    const made = (await post('/v2/triggers', {name: String(v.get('name')).trim()})).trigger;
    Object.assign(WH, {tab: 'incoming', trigger: made.id, shown: {id: made.id, url: made.replayed ? '' : made.url}});
    if (made.replayed) toast('Made, but the address was lost on the way. Use New secret to get one.', true);
    const kind = String(v.get('preset') || 'none');
    try {
      if (kind !== 'none') {
        const secret = String(v.get('secret') || '').trim();
        const signed = (await post(`/v2/triggers/${encodeURIComponent(made.id)}/signing`, {preset: kind, ...(secret ? {secret} : {})})).trigger;
        if (!secret && !signed.replayed) WH.shown.signing = signed.signing_secret;
      }
      const changed = {};
      if (settings.type_from && settings.type_from !== (WH_TYPE_FROM[kind] || '')) changed.type_from = settings.type_from;
      if (settings.hourly !== 60) changed.hourly = settings.hourly;
      if (settings.keep_days !== 7) changed.keep_days = settings.keep_days;
      if (settings.unheard !== 'log') changed.unheard = settings.unheard;
      if (Object.keys(changed).length) await post(`/v2/triggers/${encodeURIComponent(made.id)}`, changed);
    } catch (e) { toast(e.message, true); }
    dialog.close(); void renderSettingsWebhooks();
  });
  form.elements[0].focus();
}
function whSigningDialog(t) {
  const dialog = whDialog('Signing', `<label>Preset<select name="preset">${WH_PRESETS.filter(([k]) => k !== 'none').map(([k, v]) => whOpt(k, v, t.signed ? t.preset : 'hmac')).join('')}</select></label>
    <label>Signing secret<input name="secret" maxlength="300" autocomplete="off" spellcheck="false" placeholder="Leave empty to make one"></label>`,
  `${t.signed ? '<button type="button" class="ghost danger" data-wh-sign-off>Turn off</button>' : ''}<button type="submit" class="primary">Save</button>`);
  const path = `/v2/triggers/${encodeURIComponent(t.id)}/signing`;
  whSubmit(dialog, async v => {
    if (t.signed && !confirm('Replace the signing secret? Calls signed with the current one are refused at once.')) return;
    const secret = String(v.get('secret') || '').trim();
    const made = (await post(path, {preset: String(v.get('preset')), ...(secret ? {secret} : {})})).trigger;
    WH.shown = {...(WH.shown?.id === t.id ? WH.shown : {}), id: t.id};
    if (!secret) { if (made.replayed) toast('Saved, but the secret was lost on the way. Save again for a new one.', true); else WH.shown.signing = made.signing_secret; }
    dialog.close(); void renderSettingsWebhooks();
  });
  const off = dialog.querySelector('[data-wh-sign-off]');
  if (off) off.onclick = async () => {
    if (!confirm('Turn signing off? Anyone with the address can call it.')) return;
    try { await post(path, {off: true}); if (WH.shown?.id === t.id) delete WH.shown.signing; dialog.close(); void renderSettingsWebhooks(); }
    catch (e) { dialog.querySelector('[data-wh-error]').textContent = e.message; }
  };
}
async function whRotate(t) {
  if (!confirm('Make a new address? The current one stops working at once.')) return;
  try {
    const made = (await post(`/v2/triggers/${encodeURIComponent(t.id)}/rotate`, {})).trigger;
    WH.shown = {...(WH.shown?.id === t.id ? WH.shown : {}), id: t.id, url: made.replayed ? '' : made.url};
    if (made.replayed) toast('A new address was made, but it was lost on the way. Try New secret again.', true);
    void renderSettingsWebhooks();
  } catch (e) { toast(e.message, true); }
}
async function whTriggerDelete(t) {
  const using = t.routines.length ? ` ${whPlural(t.routines.length, 'routine')} will stop running on it.` : '';
  if (!confirm(`Delete “${t.name}”?${using}`)) return;
  try {
    await post(`/v2/triggers/${encodeURIComponent(t.id)}/delete`, {});
    Object.assign(WH, {trigger: '', shown: null});
    void renderSettingsWebhooks();
  } catch (e) { toast(e.message, true); }
}

// ---------------------------------------------------------------------------------------------------------- Outgoing
function whEventsSummary(events) {
  if (!events?.length || events.includes('*')) return 'All events';
  return events.length <= 2 ? events.join(', ') : `${events.slice(0, 2).join(', ')} +${events.length - 2}`;
}
function whHookPills(h) { return h.enabled ? '' : `<span class="pill waiting" title="${esc(h.paused_reason || '')}">Paused</span>`; }
async function whHooks(el, run) {
  const list = (await get('/v2/webhooks?limit=200', {fresh: true})).items || [];
  WH_HOOKS = list;
  if (run !== WH_RUN) return;
  el.innerHTML = `<div class="settings-bots-filters"><button type="button" class="primary" data-wh-hook-new>New endpoint</button></div>
    ${list.length ? `<div class="wh-list" data-wh-hooks>${list.map(h => `<button type="button" class="wh-row" data-wh-hook="${esc(h.id)}">
        <span class="wh-name"><strong>${esc(h.name)}</strong>${whHookPills(h)}</span>
        <span class="wh-meta muted">${esc(h.host)} · ${esc(whEventsSummary(h.events))}</span>
        <span class="wh-meta"><span class="tnum">${h.last_7_days.delivered} sent</span>${h.last_7_days.failed ? ` · <span class="wh-bad tnum">${h.last_7_days.failed} failed</span>` : ''} <span class="muted">7d</span></span></button>`).join('')}</div>`
      : '<div class="empty">No endpoints yet.</div>'}`;
  el.querySelector('[data-wh-hook-new]').onclick = () => void whHookDialog(null);
  el.querySelectorAll('[data-wh-hook]').forEach(b => { b.onclick = () => { WH.hook = b.dataset.whHook; WH.hookShown = null; void renderSettingsWebhooks(); }; });
}
// The event picker: All, then each catalog group (its box means `group.*`) and its events. A pattern the catalog
// does not know is kept, checked, at the end.
function whEventGroups(types) {
  const groups = new Map();
  for (const t of types) { if (!groups.has(t.group)) groups.set(t.group, []); groups.get(t.group).push(t); }
  return [...groups];
}
function whEventsHTML(types, events) {
  const set = new Set(events), all = set.has('*'), groups = whEventGroups(types);
  const known = new Set(types.map(t => t.name).concat(groups.map(([g]) => g + '.*')));
  const extra = events.filter(e => e !== '*' && !known.has(e));
  const on = (g, n) => all || set.has(n) || set.has(g + '.*');
  const box = (attrs, checked, label, title = '') => `<label${title ? ` title="${esc(title)}"` : ''}><input type="checkbox" ${attrs}${checked ? ' checked' : ''}> ${label}</label>`;
  return `<fieldset class="wh-events" data-wh-events><legend>Events</legend>
    ${box('data-ev-all', all, 'All events')}
    <div class="wh-ev-groups">${groups.map(([g, items]) => `<div class="wh-ev-group" data-ev-group="${esc(g)}">
      ${items.length > 1 ? box('data-ev-head', items.every(i => on(g, i.name)), `<code>${esc(g)}.*</code>`) : ''}
      ${items.map(i => box(`data-ev-name="${esc(i.name)}"`, on(g, i.name), items.length > 1 ? esc(i.name.slice(g.length + 1)) : `<code>${esc(i.name).replace('.', '.<wbr>')}</code>`, i.description)).join('')}</div>`).join('')}
      ${extra.length ? `<div class="wh-ev-group">${extra.map(n => box(`data-ev-name="${esc(n)}"`, true, `<code>${esc(n)}</code>`)).join('')}</div>` : ''}</div></fieldset>`;
}
function whEventsBind(box) {
  const sync = () => {
    const all = box.querySelector('[data-ev-all]').checked;
    box.querySelectorAll('.wh-ev-groups input').forEach(i => { i.disabled = all; if (all) i.checked = true; });
    if (!all) box.querySelectorAll('[data-ev-group]').forEach(g => {
      const head = g.querySelector('[data-ev-head]');
      if (head) head.checked = [...g.querySelectorAll('[data-ev-name]')].every(i => i.checked);
    });
  };
  box.addEventListener('change', ev => {
    if (ev.target.matches('[data-ev-all]') && !ev.target.checked) box.querySelectorAll('.wh-ev-groups input').forEach(i => { i.checked = false; });
    const head = ev.target.closest('[data-ev-head]');
    if (head) head.closest('[data-ev-group]').querySelectorAll('[data-ev-name]').forEach(i => { i.checked = head.checked; });
    sync();
  });
  sync();
}
function whEventsValue(box) {
  if (box.querySelector('[data-ev-all]').checked) return ['*'];
  const out = [];
  box.querySelectorAll('.wh-ev-group').forEach(g => {
    const head = g.querySelector('[data-ev-head]');
    if (head?.checked) out.push(g.dataset.evGroup + '.*');
    else g.querySelectorAll('[data-ev-name]:checked').forEach(i => out.push(i.dataset.evName));
  });
  return out;
}
async function whHookDialog(h) {
  const types = await eventTypesLoad().catch(() => []);
  const dialog = whDialog(h ? 'Edit endpoint' : 'New endpoint', `<label>Name<input name="name" maxlength="100" required autocomplete="off" value="${esc(h?.name || '')}"></label>
    <label>URL<input name="url" type="url" maxlength="2000" required autocomplete="off" spellcheck="false" placeholder="https://" value="${esc(h?.url || '')}"></label>
    <label data-wh-http hidden><input type="checkbox" name="allow_http"${h?.allow_http ? ' checked' : ''}> Allow http</label>
    ${whEventsHTML(types, h?.events || ['*'])}`, `<button type="submit" class="primary">${h ? 'Save' : 'Create'}</button>`);
  const form = dialog.querySelector('form'), events = dialog.querySelector('[data-wh-events]');
  whEventsBind(events);
  const http = () => { dialog.querySelector('[data-wh-http]').hidden = !/^http:/i.test(form.elements.url.value.trim()); };
  form.elements.url.oninput = http; http();
  whSubmit(dialog, async v => {
    const chosen = whEventsValue(events);
    if (!chosen.length) throw new Error('Pick at least one event');
    const url = String(v.get('url')).trim();
    const body = {name: String(v.get('name')).trim(), url, events: chosen, allow_http: /^http:/i.test(url) && v.has('allow_http')};
    if (h) {
      await post(`/v2/webhooks/${encodeURIComponent(h.id)}/update`, {...body, expected_revision: h.revision});
      dialog.close(); void renderSettingsWebhooks(); return;
    }
    const made = await post('/v2/webhooks', body);
    dialog.close();
    if (!made.webhook) { toast('Sent for approval'); void renderSettingsWebhooks(); return; }
    Object.assign(WH, {tab: 'outgoing', hook: made.webhook.id, hookShown: made.webhook.replayed ? null : {id: made.webhook.id, secret: made.webhook.secret}});
    if (made.webhook.replayed) toast('Made, but the secret was lost on the way. Use New secret to get one.', true);
    void renderSettingsWebhooks();
  });
  form.elements.name.focus();
}
async function whHookDetail(el, run) {
  const id = WH.hook, path = `/v2/webhooks/${encodeURIComponent(id)}`;
  const [d, sends, types] = await Promise.all([get(path, {fresh: true}), get(path + '/sends?limit=50', {fresh: true}), eventTypesLoad().catch(() => [])]);
  if (run !== WH_RUN) return;
  const h = d.webhook, items = sends.items || [], may = h.can_change;
  const actions = may ? `<button class="ghost" type="button" data-wh-hook-edit>Edit</button>
    <button class="ghost" type="button" data-wh-hook-pause>${h.enabled ? 'Pause' : 'Resume'}</button>
    <button class="ghost" type="button" data-wh-hook-rotate>New secret</button><button class="ghost" type="button" data-wh-hook-delete>Delete</button>` : '';
  const names = types.filter(t => !t.name.includes('*')).map(t => t.name);
  el.innerHTML = `${whHeadHTML(h.name, whHookPills(h), actions)}
    ${WH.hookShown?.id === id ? whSecretHTML('Signing secret', WH.hookShown.secret, 'secret') : ''}
    <dl class="wh-facts">
      <dt>URL</dt><dd><code>${esc(h.url)}</code></dd>
      <dt>Events</dt><dd>${h.events.includes('*') ? 'All events' : h.events.map(e => `<code>${esc(e)}</code>`).join(' ')}</dd>
      <dt>7 days</dt><dd><span class="tnum">${h.last_7_days.delivered} sent</span> · <span class="tnum${h.last_7_days.failed ? ' wh-bad' : ''}">${h.last_7_days.failed} failed</span>${h.last_7_days.pending ? ` · <span class="tnum">${h.last_7_days.pending} waiting</span>` : ''}</dd>
      ${h.enabled ? '' : `<dt>Paused</dt><dd>${esc(h.paused_reason || 'Yes')}</dd>`}
      ${h.old_secret_until ? `<dt>Old secret</dt><dd>Works until ${esc(fmt(h.old_secret_until))}</dd>` : ''}
    </dl>
    <h4 class="wr-sub">Sends</h4>
    ${may && names.length ? `<div class="settings-bots-filters"><select class="settings-inline-select" data-wh-example-type aria-label="Event type">${names.map(n => whOpt(n, n, '')).join('')}</select>
      <button class="ghost" type="button" data-wh-example>Send example</button></div>` : ''}
    ${items.length ? `<div class="wh-calls wh-sends" data-wh-sends>${items.map(s => `<div class="wh-call" data-wh-send="${esc(s.id)}">
        <span class="wh-time" title="${esc(s.created)}">${esc(ago(s.created))}</span>
        <span class="wh-type"><code>${esc(s.type)}</code></span>
        <span class="wh-outcome"><span class="pill ${WH_SEND_STATES[s.state] ?? ''}">${esc(s.state[0].toUpperCase() + s.state.slice(1))}</span>${s.subject ? ` <span class="muted">${esc(s.subject)}</span>` : ''}</span>
        <span class="tnum muted">${(s.attempts === 1 ? '1 try' : `${s.attempts} tries`)}</span>
        <span class="tnum muted" title="${esc(s.last_error || '')}">${s.last_status ? esc(s.last_status) : s.last_error ? 'Error' : ''}</span>
        <span class="wh-call-ctl">${may && ['failed', 'cancelled'].includes(s.state) ? '<button class="ghost" type="button" data-wh-retry>Retry</button>' : ''}</span></div>`).join('')}</div>`
      : '<div class="empty">Nothing sent yet.</div>'}`;
  const on = (sel, fn) => { const b = el.querySelector(sel); if (b) b.onclick = fn; };
  const act = async (fn, after) => { try { await fn(); after?.(); void renderSettingsWebhooks(); } catch (e) { toast(e.message, true); } };
  on('[data-wh-hook-edit]', () => void whHookDialog(h));
  on('[data-wh-hook-pause]', () => act(() => post(`${path}/${h.enabled ? 'pause' : 'resume'}`, {})));
  on('[data-wh-hook-rotate]', () => {
    if (!confirm('Make a new signing secret? The old one keeps working for a while.')) return;
    void act(async () => {
      const made = (await post(path + '/rotate', {})).webhook;
      WH.hookShown = made.replayed ? null : {id, secret: made.secret};
      if (made.replayed) toast('A new secret was made, but it was lost on the way. Try again.', true);
    });
  });
  on('[data-wh-hook-delete]', () => {
    if (!confirm(`Delete “${h.name}”? Nothing more is sent to it.`)) return;
    void act(() => post(path + '/delete', {}), () => { WH.hook = ''; WH.hookShown = null; });
  });
  on('[data-wh-example]', () => act(async () => {
    await post(path + '/example', {type: el.querySelector('[data-wh-example-type]').value});
    toast('Example queued');
  }));
  el.querySelectorAll('[data-wh-retry]').forEach(b => { b.onclick = () => act(() => post(`${path}/sends/${encodeURIComponent(b.closest('[data-wh-send]').dataset.whSend)}/retry`, {})); });
}

// ---------------------------------------------------------------------------------------------- Through Tico Gateway
async function whGateway(el, run) {
  const [relay, list] = await Promise.all([get('/v2/relay', {fresh: true}).then(d => d.relay), whTriggersFresh()]);
  if (run !== WH_RUN) return;
  const link = settingsIsAdmin() ? ' <a href="#/settings" data-wh-gateway-link>Gateway</a>' : '';
  if (relay.key === 'none') { el.innerHTML = `<div class="empty" data-wh-no-key>Connect the Gateway first.${link}</div>`; return; }
  const rows = list.filter(t => !t.builtin);
  const status = [relay.last_pull ? `Last pull ${esc(ago(relay.last_pull))}` : 'Not pulled yet',
    Number.isFinite(relay.pending) ? `<span class="tnum">${relay.pending}</span> waiting` : ''].filter(Boolean).join(' · ');
  el.innerHTML = `${relay.key === 'revoked' ? `<p class="err">The Gateway refused this server's key.${link}</p>` : ''}
    <p class="settings-cell-note" data-wh-relay-status>${status}${relay.last_error ? ` · <span class="wh-bad">${esc(relay.last_error)}</span>` : ''}</p>
    ${WH.shown?.relay ? whSecretHTML(`Gateway address · ${(list.find(t => t.id === WH.shown.id) || {}).name || ''}`, WH.shown.relay, 'relay') : ''}
    ${rows.length ? `<div class="wh-list" data-wh-relays>${rows.map(t => `<div class="wh-row wh-gw" data-wh-relay="${esc(t.id)}">
        <span class="wh-name"><strong>${esc(t.name)}</strong></span>
        <span class="wh-meta">${t.relay ? `<code>${esc(t.relay.address_prefix)}/…</code>` : '<span class="muted">No address</span>'}</span>
        <span class="wh-call-ctl">${whMine(t) ? (t.relay ? `<button class="ghost" type="button" data-wh-relay-do="rotate">New secret</button><button class="ghost" type="button" data-wh-relay-do="delete">Remove</button>`
          : `<button class="ghost" type="button" data-wh-relay-do="make">Make address</button>`) : ''}</span></div>`).join('')}</div>`
      : '<div class="empty">No incoming webhooks yet.</div>'}`;
  el.querySelectorAll('[data-wh-relay-do]').forEach(b => { b.onclick = async () => {
    const id = b.closest('[data-wh-relay]').dataset.whRelay, what = b.dataset.whRelayDo, path = `/v2/triggers/${encodeURIComponent(id)}/relay`;
    if (what === 'delete' && !confirm('Remove the Gateway address? Calls to it stop at once.')) return;
    if (what === 'rotate' && !confirm('Make a new Gateway address? The current one stops working at once.')) return;
    b.disabled = true;
    try {
      const r = (await post(what === 'make' ? path : `${path}/${what}`, {})).relay;
      WH.shown = what === 'delete' ? null : r.replayed ? null : {id, relay: r.address};
      if (what !== 'delete' && r.replayed) toast('Made, but the address was lost on the way. Use New secret.', true);
      void renderSettingsWebhooks();
    } catch (e) { toast(e.message, true); b.disabled = false; }
  }; });
}
