/* ui/app/settings-bot-editor.js — The bot editor dialog, owners, and model/computer transitions
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

// What the bot editor shows for an existing bot beyond its definition: who may use it, who it works for and who
// owns it (each opens its own dialog), and its model, fallback and computer (each applies as soon as it is picked).
function settingsBotEditorRows(e) {
  const chips = list => (list || []).map(o => `<span class="pchip">${personCircle(o.name || o.id, 16)}<span>${esc(firstName(o.name) || o.id)}</span></span>`).join('');
  const manage = settingsCanManageBot(e);
  const change = (attr, what) => manage ? `<button class="ghost" type="button" ${attr}="${esc(e.name)}" aria-label="Change ${what} for ${esc(e.display_name)}">Change</button>` : '<span></span>';
  return `<div class="sb-row"><span>Access</span><span data-access-summary>${esc(accessSummary(e.access_policy))}</span>${change('data-edit-access', 'access')}</div>
    <div class="sb-row"><span>Works for</span><div class="settings-owner-list">${chips(e.users) || '<span class="muted">Nobody</span>'}</div>${change('data-edit-owners', 'who it works for')}</div>
    <div class="sb-row"><span>Owners</span><div class="settings-owner-list" data-bot-owners>${chips(e.bot_owners) || '<span class="muted">Its owner</span>'}</div>${change('data-edit-bot-owners', 'owners')}</div>
    ${e.agent ? `<div class="sb-row"><span>Computer</span>${settingsAgentCell(e)}</div>`
      : `<div class="sb-row"><span>Model</span>${settingsChoiceCombo(e, 'model')}<span></span></div>
    <div class="sb-row"><span>Fallback</span>${settingsChoiceCombo(e, 'fallback')}<span></span></div>
    <div class="sb-row"><span>Computer</span>${settingsMachineSelect(e)}<span></span></div>`}`;
}
function settingsEditBot(slug = '') {
  const editing = !!slug, e = editing ? S.emps.find(row => row.name === slug) : null;
  const dialog = $('#bot-editor');
  if (!dialog || editing && !e) return;
  SETTINGS_KEEP_MODEL = e?.model || '';
  // A new bot starts on the team default; nothing here names a vendor.
  const enabledModels = SETTINGS_DATA.models.filter(model => !model.deprecated && model.provider &&
    (SETTINGS_DATA.enabledProviders || []).includes(model.provider));
  const fallbackModel = SETTINGS_DATA.models.find(model => model.id === SETTINGS_DATA.defaultModel)
    || enabledModels[0] || SETTINGS_DATA.models[0] || {};
  const effort = e?.reasoning_effort || e?.effort || fallbackModel.default_effort || 'high';
  const defaultHarness = e?.harness || fallbackModel.harnesses?.[0] || fallbackModel.runtime || '';
  const currentModel = settingsChoiceValue(defaultHarness, e?.model || fallbackModel.id, effort);
  const modelOptions = settingsAllChoices().map(choice =>
    `<button type="button" role="option" data-value="${esc(choice.value)}" ${choice.value === currentModel ? 'aria-selected="true"' : ''}>${esc(choice.label)}</button>`).join('');
  const parentOptions = S.emps.filter(row => row.name !== slug &&
    (S.me?.role === 'owner' || settingsCanManageBot(row))).map(row =>
    `<option value="${esc(row.name)}" ${e?.reports_to === row.name ? 'selected' : ''}>${esc(row.display_name || row.name)}</option>`).join('');
  const operator = e?.operator || S.me?.id || SETTINGS_DATA.people[0]?.id || '';
  // A member's bot goes on a computer an admin has opened to members' bots (the server refuses the rest).
  const machineOptions = SETTINGS_DATA.machines.filter(machine => !machine.revoked_at &&
    (settingsIsAdmin() || machine.accepts_member_bots)).map(machine =>
    `<option value="${esc(machine.id)}" data-operator="${esc(machine.operator)}">${esc(machine.label)} · ${esc(settingsPersonName(machine.operator))}</option>`).join('');
  dialog.innerHTML = `<form><div class="tmodal-head"><h2 id="bot-editor-title">${editing ? `Edit ${esc(e.display_name)}` : 'Add bot'}</h2><span class="spacer"></span><button class="ghost" type="button" data-bot-close aria-label="Close">✕</button></div>
    <div class="bot-editor-body">
      <div class="bot-editor-grid">
        <label>Bot slug<input name="slug" type="text" autocomplete="off" spellcheck="false" value="${esc(slug)}" placeholder="release-captain" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" maxlength="80" ${editing ? 'readonly' : 'required'}></label>
        <label>Display name<input name="display_name" type="text" autocomplete="off" value="${esc(e?.display_name || '')}" placeholder="Release Captain" maxlength="100" required></label>
        <label class="bot-editor-wide">Description<textarea name="description" maxlength="2000" placeholder="What this bot owns and does">${esc(e?.description || '')}</textarea></label>
        <label>Reports to<select name="reports_to"><option value="">Top level</option>${parentOptions}</select></label>
        <label>Other bots<select name="bot_contact"><option value="open" ${(e?.bot_contact || 'open') === 'open' ? 'selected' : ''}>May chat and assign</option><option value="replies" ${e?.bot_contact === 'replies' ? 'selected' : ''}>Replies only</option><option value="tasks" ${e?.bot_contact === 'tasks' ? 'selected' : ''}>Tasks only</option></select><small>Applies to bots only. Humans are never affected.</small></label>
        <label>Status<select name="status">${['planned','active','paused'].map(value => `<option value="${value}" ${(e?.status || 'planned') === value ? 'selected' : ''}>${value === 'planned' ? 'Setting up' : value[0].toUpperCase() + value.slice(1)}</option>`).join('')}</select></label>
        <label>Repository<input name="repo" type="text" autocomplete="off" spellcheck="false" value="${esc(e?.repo || (slug ? `emp-${slug}` : ''))}" placeholder="emp-release-captain" maxlength="200" required></label>
        ${editing && S.me?.role === 'owner' ? `<label class="bot-editor-wide" data-extra-repos hidden>Extra GitHub repositories<textarea name="extra_repos" rows="3" maxlength="2000" placeholder="shared-docs&#10;design-system" spellcheck="false"></textarea><small>One per line, in the connected GitHub organization. The bot's GitHub token covers its own repository and these, with the same permissions.</small></label>` : ''}
        <label class="bot-editor-check"><input type="checkbox" name="temp" ${e?.temp ? 'checked' : ''}> Temp bot</label>
        ${editing && e?.shared_from ? `<p class="muted bot-editor-wide">A copy of the shared bot ${esc(e.shared_from)}: it follows that bot's definition, model and repository, so only its status changes here.</p>`
          : editing ? `<label class="bot-editor-check"><input type="checkbox" name="shared" ${e?.shared ? 'checked' : ''}> Shared bot<small>Anyone who may read it can add their own copy, which runs on their own computer from this bot's repository and behaves the same.</small></label>` : ''}
        <label>Conversation<select name="thread_mode"><option value="personal" ${(e?.thread_mode || 'personal') === 'personal' ? 'selected' : ''}>Private per human</option><option value="shared" ${e?.thread_mode === 'shared' ? 'selected' : ''}>Shared room</option></select></label>
        ${editing ? '<div class="bot-editor-wide sb-rows" data-bot-people></div>' : ''}
        ${editing ? '' : `<label class="bot-editor-wide">Model and effort
          <div class="settings-combo" data-add-choice data-current="${esc(currentModel)}">
            <input type="search" name="model_search" autocomplete="off" spellcheck="false"
              aria-label="Model and effort" placeholder="Search harness or model"
              value="${esc(settingsChoiceLabel(defaultHarness, e?.model || fallbackModel.id, effort))}">
            <input type="hidden" name="model_effort" value="${esc(currentModel)}" required>
            <div class="settings-combo-list" role="listbox">${modelOptions}</div>
          </div></label>
        <label>Computer owner<select name="operator" ${S.me?.role === 'owner' ? '' : 'disabled'}>${SETTINGS_DATA.people.map(person => `<option value="${esc(person.id)}" ${person.id === operator ? 'selected' : ''}>${esc(person.name || person.id)}</option>`).join('')}</select></label>
        <label class="bot-editor-wide">Registered computer<select name="runner_id"><option value="">Assign later</option>${machineOptions}</select><small data-computer-note></small></label>
        <p class="bot-editor-wide muted">Everyone can use it. Change that under Access once it is added.</p>`}
      </div>
      <div class="row" style="margin-top:16px"><button class="primary" type="submit">${editing ? 'Save bot' : 'Add bot'}</button><button class="ghost" type="button" data-bot-close>Cancel</button><span class="muted" data-bot-status></span>${editing && !isBuiltInBot(e.name) ? `<span class="spacer"></span><select name="successor" aria-label="Hand its work to"><option value="">Hand its work to ${esc(settingsPersonName(e.operator))}</option>${S.emps.filter(row => row.name !== slug).map(row => `<option value="${esc(row.name)}">Hand its work to ${esc(row.display_name || row.name)}</option>`).join('')}</select><button class="ghost danger" type="button" data-bot-remove>Remove bot</button>` : ''}</div></div></form>`;
  const form = dialog.querySelector('form'), status = dialog.querySelector('[data-bot-status]');
  dialog.querySelectorAll('[data-bot-close]').forEach(button => button.onclick = () => dialog.close());
  // The rows for who owns it, its model and its computer: they save on their own, so keep them fresh, and
  // once one has changed the bot use the newer revision for Save.
  let rev = e?.revision, touched = false;
  const rows = dialog.querySelector('[data-bot-people]');
  if (rows) {
    const paint = () => { rows.innerHTML = settingsBotEditorRows(S.emps.find(row => row.name === slug) || e); settingsWireCombos(rows); };
    const refresh = () => { if (!dialog.open) return; if (touched) rev = (S.emps.find(row => row.name === slug) || e).revision; paint(); };
    paint();
    document.addEventListener('tico:settings-loaded', refresh);
    dialog.addEventListener('close', () => document.removeEventListener('tico:settings-loaded', refresh), {once: true});
    rows.addEventListener('click', event => {
      touched = true;
      const access = event.target.closest('[data-edit-access]'), owners = event.target.closest('[data-edit-owners]'), botOwners = event.target.closest('[data-edit-bot-owners]');
      if (access) void settingsEditAccess(access.dataset.editAccess);
      if (owners) settingsEditOwners(owners.dataset.editOwners);
      if (botOwners) void settingsEditBotOwners(botOwners.dataset.editBotOwners);
      const credential = event.target.closest('[data-agent-credential]'), revoke = event.target.closest('[data-agent-revoke]');
      if (credential) void settingsAgentCredential(credential.dataset.agentCredential);
      if (revoke) void settingsAgentRevoke(revoke.dataset.agentRevoke);
    });
    rows.addEventListener('change', event => {
      const machine = event.target.closest('[data-bot-machine]');
      if (machine) { touched = true; void settingsMoveBot(machine); }
    });
  }
  let extraLoaded = null;   // the saved list as text once the server has answered, else null
  const extraBox = dialog.querySelector('[data-extra-repos]');
  const extraLines = value => value.split(/[\s,]+/).map(x => x.trim()).filter(Boolean);
  if (extraBox) get(`/v2/bots/${encodeURIComponent(slug)}/github-repos`).then(r => {
    if (!r.connected || !dialog.isConnected) return;
    extraLoaded = (r.repositories || []).map(x => x.replace(/^[^/]+\//, '')).join('\n');
    form.elements.extra_repos.value = extraLoaded;
    extraBox.hidden = false;
  }).catch(() => {});
  const remove = dialog.querySelector('[data-bot-remove]');
  if (remove) remove.onclick = async () => {
    // Remove = archive (#535): off the chart, no routines or new work; open tasks go to the picked heir.
    const successor = form.elements.successor.value;
    if (!confirm(`Remove ${e.display_name}? It leaves the team chart and stops running; its open tasks go to ${form.elements.successor.selectedOptions[0].textContent.replace('Hand its work to ', '')}.`)) return;
    remove.disabled = true; status.textContent = 'Removing…';
    try {
      await post(`/v2/bots/${encodeURIComponent(slug)}/archive`, {successor: successor || null, expected_revision: e.revision});
      dialog.close(); await loadSettings(); settingsShow('bots');
      toast(`Removed ${e.display_name}`);
    } catch (error) { status.innerHTML = `<span class="err">${esc(error.message)}</span>`; remove.disabled = false; }
  };
  if (!editing) {
    const slugInput = form.elements.slug, repo = form.elements.repo;
    let repoEdited = false, operatorEdited = false;
    repo.addEventListener('input', () => { repoEdited = true; });
    slugInput.addEventListener('input', () => { if (!repoEdited) repo.value = slugInput.value ? `emp-${slugInput.value}` : ''; });
    form.elements.operator.addEventListener('change', () => { operatorEdited = true; });
    form.elements.reports_to.addEventListener('change', event => {
      const parent = S.emps.find(row => row.name === event.target.value);
      if (!operatorEdited && !form.elements.runner_id.value && parent?.operator) form.elements.operator.value = parent.operator;
    });
    form.elements.runner_id.addEventListener('change', event => {
      const selected = event.target.selectedOptions[0]?.dataset.operator;
      if (selected) form.elements.operator.value = selected;
    });
    const combo = dialog.querySelector('[data-add-choice]');
    if (combo) {
      const search = combo.querySelector('input[type=search]');
      const hidden = combo.querySelector('input[name=model_effort]');
      const list = combo.querySelector('.settings-combo-list');
      const paint = query => {
        const choices = settingsFilterChoices(query);
        list.innerHTML = choices.length
          ? choices.map(choice => `<button type="button" role="option" data-value="${esc(choice.value)}" ${choice.value === hidden.value ? 'aria-selected="true"' : ''}>${esc(choice.label)}</button>`).join('')
          : '<div class="settings-combo-empty">No matching harness or model</div>';
        list.querySelectorAll('[data-value]').forEach(button => {
          button.onmousedown = event => event.preventDefault();
          button.onclick = () => {
            hidden.value = button.dataset.value;
            const choice = settingsChoiceFromValue(button.dataset.value);
            search.value = settingsChoiceLabel(choice.harness, choice.model, choice.effort);
            combo.classList.remove('open');
          };
        });
      };
      search.onfocus = () => { combo.classList.add('open'); search.select(); paint(''); };
      search.oninput = () => { combo.classList.add('open'); paint(search.value); };
      search.onblur = () => { combo.classList.remove('open'); };
      // An external harness (a Hermes profile) runs nowhere Tico manages: no computer to pick,
      // and the note says what happens after saving instead.
      const computer = form.elements.runner_id, computerNote = dialog.querySelector('[data-computer-note]');
      const syncComputer = () => {
        const external = !!settingsHarness(settingsChoiceFromValue(hidden.value).harness)?.external;
        computer.disabled = external; if (external) computer.value = '';
        if (computerNote) computerNote.textContent = external ? 'Run by an external agent: no computer. After saving, create its credential in the Computer column.' : '';
      };
      hidden.addEventListener('change', syncComputer);
      const observer = new MutationObserver(syncComputer); observer.observe(hidden, {attributes: true, attributeFilter: ['value']});
      list.addEventListener('click', () => setTimeout(syncComputer, 0));
      syncComputer();
      paint('');
    }
  }
  form.onsubmit = async event => {
    event.preventDefault();
    const submit = form.querySelector('[type=submit]'); submit.disabled = true; status.textContent = 'Saving…';
    let added = null;
    try {
      if (editing && e?.shared_from) {
        await post(`/v2/bots/${encodeURIComponent(slug)}/definition`, {
          status: form.elements.status.value, expected_revision: rev});
      } else if (editing) {
        await post(`/v2/bots/${encodeURIComponent(slug)}/definition`, {
          display_name: form.elements.display_name.value, description: form.elements.description.value,
          reports_to: form.elements.reports_to.value || null, status: form.elements.status.value,
          bot_contact: form.elements.bot_contact.value,
          repo: form.elements.repo.value, thread_mode: form.elements.thread_mode.value,
          temp: form.elements.temp.checked, shared: form.elements.shared.checked, expected_revision: rev});
        if (extraLoaded !== null && extraLines(form.elements.extra_repos.value).join('\n') !== extraLines(extraLoaded).join('\n'))
          await put(`/v2/bots/${encodeURIComponent(slug)}/github-repos`, {repositories: extraLines(form.elements.extra_repos.value)});
      } else {
        const choice = settingsChoiceFromValue(form.elements.model_effort.value);
        added = await post('/v2/bots', {slug: form.elements.slug.value, display_name: form.elements.display_name.value,
          description: form.elements.description.value, reports_to: form.elements.reports_to.value || null,
          status: form.elements.status.value, repo: form.elements.repo.value,
          thread_mode: form.elements.thread_mode.value, model: choice.model, effort: choice.effort,
          harness: choice.harness, operator: form.elements.operator.value || S.me?.id,
          runner_id: form.elements.runner_id.value || null});
      }
      dialog.close(); await loadSettings(); settingsShow('bots');
      toast(editing ? `Updated ${form.elements.display_name.value}` : added?.note || `Added ${form.elements.display_name.value}`);
    } catch (error) { status.innerHTML = `<span class="err">${esc(error.message)}</span>`; submit.disabled = false; }
  };
  dialog.onclose = () => { dialog.innerHTML = ''; };
  dialog.showModal();
}
function settingsEditOwners(slug) {
  const e = S.emps.find(row => row.name === slug), dialog = $('#owner-picker');
  if (!e || !dialog) return;
  const selected = new Set((e.users || []).map(person => person.id));
  dialog.innerHTML = `<form><div class="tmodal-head"><h2 id="owner-picker-title">Who ${esc(e.display_name)} works for</h2><span class="spacer"></span><button class="ghost" type="button" data-owner-close aria-label="Close">✕</button></div>
    <div class="owner-picker-body">
      <div class="owner-options">${SETTINGS_DATA.people.map(person => `<label class="owner-option"><input type="checkbox" name="owner" value="${esc(person.id)}" ${selected.has(person.id) ? 'checked' : ''}>${personAvatar(person, 22)}<span>${esc(person.name || person.id)}</span></label>`).join('')}</div>
      <div class="row"><button class="primary" type="submit">Save</button><button class="ghost" type="button" data-owner-close>Cancel</button><span id="owner-picker-status" class="muted"></span></div></div></form>`;
  dialog.querySelectorAll('[data-owner-close]').forEach(button => button.onclick = () => dialog.close());
  dialog.querySelector('form').onsubmit = async event => {
    event.preventDefault();
    const owners = [...dialog.querySelectorAll('input[name=owner]:checked')].map(input => input.value);
    const status = $('#owner-picker-status', dialog);
    if (!owners.length) { status.innerHTML = '<span class="err">Choose at least one human.</span>'; return; }
    dialog.querySelectorAll('button,input').forEach(control => control.disabled = true); status.textContent = 'Saving…';
    try {
      await post(`/v2/bots/${encodeURIComponent(slug)}/owners`, {owners, expected_revision: e.revision});
      dialog.close(); await loadSettings(); toast(`Updated who ${e.display_name} works for`);
    } catch (error) {
      status.innerHTML = `<span class="err">${esc(error.message)}</span>`;
      dialog.querySelectorAll('button,input').forEach(control => control.disabled = false);
    }
  };
  dialog.onclose = () => { dialog.innerHTML = ''; };
  dialog.showModal();
}
async function settingsMoveBot(select) {
  const slug = select.dataset.botMachine, e = S.emps.find(row => row.name === slug);
  const current = select.dataset.current || '', machine = SETTINGS_DATA.machines.find(row => row.id === select.value);
  if (!e || !machine || machine.id === current) return;
  if (!await settingsConfirmTransition(e, 'machine', machine.label)) { select.value = current; return; }
  await settingsBeginTransition(select, e, {kind:'machine', runner_id:machine.id,
    expected_generation:e.machine?.generation || 0, expected_revision:e.revision});
}
function settingsControlInput(control) {
  return control?.matches?.('input,select') ? control : control?.querySelector?.('input,select');
}
function settingsConfirmTransition(e, kind, target) {
  const dialog = $('#transition-dialog');
  if (!dialog) return Promise.resolve(false);
  clearInterval(SETTINGS_TRANSITION_TIMER);
  const label = kind === 'model' ? 'Change model settings' : 'Move bot';
  return new Promise(resolve => {
    let settled = false;
    const finish = accepted => {
      if (settled) return;
      settled = true;
      dialog.onclose = null;
      if (dialog.open) dialog.close();
      dialog.innerHTML = '';
      resolve(accepted);
    };
    dialog.innerHTML = `<div class="tmodal-head"><h2 id="transition-title">${label} · ${esc(e.display_name)}</h2><span class="spacer"></span><button class="ghost" type="button" data-confirm-cancel aria-label="Close">✕</button></div>
      <div class="transition-body"><p>Destination: <strong>${esc(target)}</strong></p>
        <div class="transition-progress"><strong>This starts a fresh provider session.</strong>
          <p>The bot saves a checkpoint first. History is kept; session-only context is lost.</p></div>
        <div class="transition-actions"><button class="primary" type="button" data-confirm-prepare>Prepare change</button><button class="ghost" type="button" data-confirm-cancel>Cancel</button></div></div>`;
    dialog.querySelector('[data-confirm-prepare]').onclick = () => finish(true);
    dialog.querySelectorAll('[data-confirm-cancel]').forEach(button => button.onclick = () => finish(false));
    dialog.oncancel = event => { event.preventDefault(); finish(false); };
    // A dialog close event can arrive after an immediately-following picker has
    // already reused this element. Do not let that stale event cancel the new modal.
    dialog.onclose = () => { if (!dialog.open) finish(false); };
    dialog.showModal();
  });
}
async function settingsBeginTransition(control, e, body) {
  const input = settingsControlInput(control);
  const current = control.dataset.current || '';
  if (input) input.disabled = true;
  try {
    const transition = await post(`/v2/bots/${encodeURIComponent(e.name)}/transitions`, body);
    settingsWatchTransition(transition.id, {control, current});
  } catch (error) {
    if (input) { input.value = input.defaultValue || current; input.disabled = false; }
    toast(error.message, true);
  }
}
function settingsTransitionTarget(t) {
  return t.kind === 'model' ? settingsChoiceLabel(t.target?.harness || t.target?.runtime, t.target?.model, t.target?.effort)
    : t.target?.label || 'another computer';
}
function settingsTransitionHTML(t) {
  const name = settingsBotName(t.bot), progress = t.progress || {prepared:0,total:0};
  const status = t.state === 'preparing' ? `Checkpointing ${progress.prepared} of ${progress.total} current conversation${progress.total === 1 ? '' : 's'}…`
    : t.state === 'blocked' ? `Current-session checkpoint blocked: ${t.error || 'The current computer is unavailable.'}`
    : t.state === 'failed' ? t.error || 'The checkpoint could not be completed.'
    : t.state === 'applied' ? `${name} now uses ${settingsTransitionTarget(t)}.${t.without_checkpoint ? ' No prepared checkpoint was created.' : t.progress.total ? ' Its conversation checkpoint is saved.' : ' It had no active session to checkpoint.'}`
    : t.state === 'cancelled' ? 'This change was cancelled.' : 'Preparing the change…';
  const pending = ['preparing','blocked','failed','prepared'].includes(t.state);
  const force = ['blocked','failed'].includes(t.state);
  return `<div class="tmodal-head"><h2 id="transition-title">${t.kind === 'model' ? 'Change model settings' : 'Move bot'} · ${esc(name)}</h2><span class="spacer"></span><button class="ghost" type="button" data-transition-close aria-label="Close">✕</button></div>
    <div class="transition-body"><p>Destination: <strong>${esc(settingsTransitionTarget(t))}</strong></p>
      <div class="transition-progress"><strong>${esc(status)}</strong>${t.state === 'preparing' ? '<p class="muted">It applies when checkpoints are saved. You can close this.</p>' : ''}</div>
      ${force ? `<p class="err">Without a checkpoint the new session starts with no handoff. History is kept.</p>` : ''}
      <div class="transition-actions">${force ? '<button class="fail" type="button" data-transition-force>Change without checkpoint</button>' : ''}
        ${pending ? '<button class="ghost" type="button" data-transition-cancel>Cancel change</button>' : ''}
        ${t.state === 'applied' ? '<button class="primary" type="button" data-transition-done>Done</button>' : ''}</div></div>`;
}
function settingsWatchTransition(id, origin = {}) {
  const dialog = $('#transition-dialog'); if (!dialog) return;
  clearInterval(SETTINGS_TRANSITION_TIMER);
  const paint = async () => {
    let t;
    try { t = await get(`/v2/settings/transitions/${encodeURIComponent(id)}`); }
    catch (error) { if (dialog.open) dialog.innerHTML = `<div class="transition-body"><p class="err">${esc(error.message)}</p></div>`; return; }
    if (!dialog.open) dialog.showModal();
    dialog.innerHTML = settingsTransitionHTML(t);
    dialog.querySelector('[data-transition-close]')?.addEventListener('click', () => dialog.close());
    dialog.querySelector('[data-transition-done]')?.addEventListener('click', () => dialog.close());
    dialog.querySelector('[data-transition-force]')?.addEventListener('click', async button => {
      if (!confirm(`Change without a prepared checkpoint? Raw conversation history stays in ${appName()}, but persistent session context will be lost.`)) return;
      button.currentTarget.disabled = true;
      try { await post(`/v2/settings/transitions/${encodeURIComponent(id)}/apply-without-checkpoint`, {change_without_checkpoint:true}); await paint(); }
      catch (error) {toast(error.message, true); button.currentTarget.disabled = false;}
    });
    dialog.querySelector('[data-transition-cancel]')?.addEventListener('click', async button => {
      button.currentTarget.disabled = true;
      try { await post(`/v2/settings/transitions/${encodeURIComponent(id)}/cancel`, {}); await paint(); }
      catch (error) {toast(error.message, true); button.currentTarget.disabled = false;}
    });
    if (['applied','cancelled'].includes(t.state)) {
      clearInterval(SETTINGS_TRANSITION_TIMER);
      await loadSettings();
      if (t.state === 'applied') {
        const suffix = t.without_checkpoint ? ' · changed without checkpoint' : t.progress.total ? ' · checkpoint saved' : '';
        toast(`${settingsBotName(t.bot)} ${t.kind === 'model' ? 'now uses' : 'now runs on'} ${settingsTransitionTarget(t)}${suffix}`);
      }
    }
  };
  dialog.onclose = () => {
    if (dialog.open) return;
    clearInterval(SETTINGS_TRANSITION_TIMER);
    const input = settingsControlInput(origin.control);
    if (input && !input.disabled) input.value = input.defaultValue || origin.current;
  };
  void paint(); SETTINGS_TRANSITION_TIMER = setInterval(paint, 2000);
}
