/* Settings > Cloud services > Meeting importers (owner). Turns Fireflies, Zoom, Google Meet and
   Granola on, picks the enrolled computer that runs each one, and shows how it is doing. Their
   credentials are never typed here: they are files on that computer (docs/meetings.md). */
window.mountMeetingImporters = async function (host) {
  if (!host) return;
  const esc = value => { const s = document.createElement('span'); s.textContent = value ?? ''; return s.innerHTML; };
  const when = value => value ? (typeof ago === 'function' ? ago(value) : new Date(value).toLocaleString()) : 'never';
  const labels = {off: 'Off', waiting: 'Waiting for the computer', syncing: 'Syncing', delayed: 'Delayed', error: 'Error'};
  let state;
  try { state = await get('/v2/meeting-importers'); }
  catch (error) { host.innerHTML = `<div class="empty">${esc(error.message)}</div>`; return; }
  if (!host.isConnected) return;
  const machines = state.computers || [];
  if (!Array.isArray(state.importers)) { host.innerHTML = '<div class="empty">Meeting importers are unavailable.</div>'; return; }
  host.innerHTML = (state.importers || []).map(i => {
    const options = ['<option value="">Choose a computer</option>'].concat(machines.map(m =>
      `<option value="${esc(m.id)}"${m.id === i.runner_id ? ' selected' : ''}>${esc(m.label)}${m.platform ? ' (' + esc(m.platform) + ')' : ''}${m.online ? '' : ' - offline'}</option>`)).join('');
    const facts = i.enabled ? `<p class="muted" data-imp-facts>Last sync ${esc(when(i.last_success))} · last import ${esc(when(i.last_import))} · ${Number(i.imported_total) || 0} imported</p>` : '';
    const error = i.error ? `<p role="alert" data-imp-error>${esc(i.error)}</p>` : '';
    return `<form class="meeting-importer" data-importer="${esc(i.source)}" style="display:grid;gap:8px;padding:12px 0;border-top:1px solid var(--line)">
      <div class="row"><strong>${esc(i.name)}</strong><span class="muted" data-imp-status>${esc(labels[i.status] || i.status)}</span></div>
      <div class="row"><label><input type="checkbox" name="enabled"${i.enabled ? ' checked' : ''} aria-label="Enable ${esc(i.name)}"> Enabled</label>
        <label>Runs on <select name="runner" aria-label="Computer that runs ${esc(i.name)}">${options}</select></label>
        <button class="primary" type="submit" aria-label="Save ${esc(i.name)}">Save</button></div>
      ${facts}${error}
      <details><summary>Set up credentials</summary>
        <p class="muted">On the computer you chose, create <code>${esc(i.setup.file)}</code> in its projects folder (mode 600) with:</p>
        <pre>${i.setup.keys.map(k => esc(k) + '=').join('\n')}</pre>
        <p class="muted">Steps and scopes: ${esc(i.setup.doc)}. Check the computer with <code>python -m runner importers-doctor</code>.</p></details>
      <p role="status" data-imp-message></p></form>`;
  }).join('') + (machines.length ? '' : '<p class="empty">No enrolled computer may run importers yet. Add one under Devices.</p>');
  host.querySelectorAll('form[data-importer]').forEach(form => {
    form.onsubmit = async event => {
      event.preventDefault();
      const message = form.querySelector('[data-imp-message]'), button = form.querySelector('button[type=submit]');
      message.textContent = '';
      button.disabled = true;
      try {
        await post('/v2/meeting-importers/' + form.dataset.importer, {enabled: form.enabled.checked, runner_id: form.runner.value});
        window.mountMeetingImporters(host);
      } catch (error) { message.textContent = error.message; button.disabled = false; }
    };
  });
};
