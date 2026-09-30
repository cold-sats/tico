/* Settings > People > Directory sync: pull people from Google Workspace or Microsoft Entra ID, or
   accept them over SCIM (docs/people.md). Every sync is previewed first; the credentials never
   reach the browser after they are saved. */
window.mountDirectorySync = async function (host, onChange) {
  if (!host) return;
  const text = value => { const s = document.createElement('span'); s.textContent = value ?? ''; return s.innerHTML; };
  const lines = value => value.split('\n').map(x => x.trim()).filter(Boolean);
  let view;
  try {
    const got = await get('/v2/directory');
    view = {source: '', interval_minutes: 360, mass_leave_limit: 10, revision: 0, last: {}, ...got,
      filter: {groups: [], org_units: [], domains: [], ...got.filter}, credentials: {...got.credentials}, scim: {...got.scim}};
  } catch (error) { host.innerHTML = `<div class="empty">${text(error.message)}</div>`; return; }
  if (!host.isConnected) return;
  const HELP = {
    google: 'Create a service account with domain-wide delegation for the read-only scope <code>admin.directory.user.readonly</code> (add <code>admin.directory.group.member.readonly</code> to filter by group), then paste its JSON key and the admin it acts as. Steps are in docs/people.md.',
    entra: 'Register an app in Microsoft Entra with the application permissions <code>User.Read.All</code> (and <code>GroupMember.Read.All</code> to filter by group), grant admin consent, and create a client secret. Steps are in docs/people.md.',
    scim: 'Create a token, then give your identity provider the base URL and the token. Turn group provisioning off. Steps for Okta and Entra are in docs/people.md.'};
  const last = view.last?.at
    ? `Last sync ${text(new Date(view.last.at).toLocaleString())}: ${view.last.ok === false ? `failed, ${text(view.last.error)}` : view.last.held ? 'held for your confirmation' : 'ok'}`
    : 'Never synced';
  const saved = view.credentials[view.source];
  host.innerHTML = `
    <header><h2>Directory sync</h2><span class="sub">add and remove people from your company directory</span></header>
    <form data-ds-form style="display:grid;gap:10px;max-width:560px">
      <label>Source <select name="source">
        <option value="">None: add people by hand</option><option value="google">Google Workspace</option>
        <option value="entra">Microsoft Entra ID</option><option value="scim">SCIM (Okta, Entra provisioning, JumpCloud)</option></select></label>
      <p class="muted" data-ds-help></p>
      <div data-ds-creds="google" hidden>
        <label>Service account JSON key <textarea name="service_account_json" rows="3" autocomplete="off" spellcheck="false" placeholder="${saved?.configured ? 'Saved. Paste a new key to replace it.' : '{ &quot;type&quot;: &quot;service_account&quot;, ... }'}"></textarea></label>
        <label>Admin to act as <input name="admin_email" type="email" autocomplete="email" spellcheck="false" placeholder="admin@company.com"></label>
      </div>
      <div data-ds-creds="entra" hidden>
        <label>Tenant ID or domain <input name="tenant" type="text" autocomplete="off" spellcheck="false"></label>
        <label>Application (client) ID <input name="client_id" type="text" autocomplete="off" spellcheck="false"></label>
        <label>Client secret value <input name="client_secret" type="password" autocomplete="new-password" placeholder="${saved?.configured ? 'Saved. Enter a new secret to replace it.' : ''}"></label>
      </div>
      <p class="muted" data-ds-saved></p>
      <div data-ds-filters hidden>
        <label><span data-ds-groups-label>Only these groups</span> <textarea name="groups" rows="2" spellcheck="false" placeholder="one per line; empty means everyone">${text(view.filter.groups.join('\n'))}</textarea></label>
        <label data-ds-ou>Only these organizational units <textarea name="org_units" rows="2" spellcheck="false" placeholder="/Sales">${text(view.filter.org_units.join('\n'))}</textarea></label>
        <label>Only these email domains <textarea name="domains" rows="2" spellcheck="false" placeholder="company.com">${text(view.filter.domains.join('\n'))}</textarea></label>
        <label>Sync every <select name="interval_minutes"><option value="0">Only when I press Sync now</option><option value="60">hour</option><option value="360">6 hours</option><option value="1440">day</option></select></label>
      </div>
      <label>Ask me first when a sync would mark more than <input name="mass_leave_limit" type="number" inputmode="numeric" min="0" max="10000" style="width:80px" value="${text(view.mass_leave_limit)}"> people as left</label>
      <p class="muted">Everyone synced can sign in, so keep the filter to the people who should use this app. People you added by hand are never removed by a sync, and the owner is never marked left.</p>
      <div class="row"><button class="primary" type="submit">Save</button>
        <button class="ghost" type="button" data-ds-now>Sync now</button></div>
    </form>
    <div data-ds-scim hidden style="margin-top:10px">
      <p>Base URL <code>${text(view.scim.url)}</code></p>
      <p class="muted">${view.scim.enabled ? `Token created ${text(new Date(view.scim.created).toLocaleString())}. It is shown once; make a new one to replace it.` : 'No token yet.'}</p>
      <button class="ghost" type="button" data-ds-token>${view.scim.enabled ? 'Replace token' : 'Create token'}</button>
      <p data-ds-token-out></p>
    </div>
    <p class="muted" data-ds-last>${last}</p>
    <div data-ds-preview></div>
    <p role="status" data-ds-status></p>`;
  const form = host.querySelector('[data-ds-form]'), status = host.querySelector('[data-ds-status]');
  form.source.value = view.source;
  form.interval_minutes.value = String(view.interval_minutes);
  const show = () => {
    const source = form.source.value, pull = source === 'google' || source === 'entra';
    host.querySelector('[data-ds-help]').innerHTML = HELP[source] || '';
    host.querySelectorAll('[data-ds-creds]').forEach(el => { el.hidden = el.dataset.dsCreds !== source; });
    host.querySelector('[data-ds-filters]').hidden = !pull;
    host.querySelector('[data-ds-ou]').hidden = source !== 'google';
    host.querySelector('[data-ds-groups-label]').textContent = source === 'entra' ? 'Only these groups (object IDs)' : 'Only these groups (email addresses)';
    host.querySelector('[data-ds-scim]').hidden = source !== 'scim';
    host.querySelector('[data-ds-now]').hidden = !pull || view.source !== source;
    const c = view.credentials[source];
    host.querySelector('[data-ds-saved]').textContent = pull && c?.configured ? `Credentials saved: ${c.hint}` : '';
  };
  form.source.onchange = show;
  show();
  const body = () => {
    const source = form.source.value, f = new FormData(form), fields = Object.fromEntries(f);
    const out = {source, expected_revision: view.revision, interval_minutes: Number(fields.interval_minutes),
      mass_leave_limit: Number(fields.mass_leave_limit) || 0,
      filter: {groups: lines(fields.groups || ''), org_units: lines(fields.org_units || ''), domains: lines(fields.domains || '')}};
    const typed = source === 'google' ? fields.service_account_json?.trim() || fields.admin_email?.trim()
      : source === 'entra' ? fields.tenant?.trim() || fields.client_id?.trim() || fields.client_secret?.trim() : '';
    if (typed) out.credentials = Object.fromEntries(['service_account_json', 'admin_email', 'tenant', 'client_id', 'client_secret']
      .filter(k => fields[k] !== undefined).map(k => [k, fields[k]]));
    return out;
  };
  form.onsubmit = async event => {
    event.preventDefault();
    status.textContent = '';
    try { await put('/v2/directory', body()); onChange ? onChange() : window.mountDirectorySync(host); }
    catch (error) { status.textContent = error.message; }
  };
  host.querySelector('[data-ds-token]').onclick = async () => {
    if (view.scim.enabled && !confirm('Replace the SCIM token? The identity provider stops working until you give it the new one.')) return;
    try {
      const {token} = await post('/v2/directory/scim-token', {});
      host.querySelector('[data-ds-token-out]').innerHTML = `Token (copy it now): <code data-ds-token-value>${text(token)}</code>`;
    } catch (error) { status.textContent = error.message; }
  };
  const list = (title, rows, describe) => rows.length
    ? `<details ${rows.length <= 8 ? 'open' : ''}><summary>${text(title)} (${rows.length})</summary><ul>${rows.slice(0, 200).map(r => `<li>${describe(r)}</li>`).join('')}</ul></details>` : '';
  host.querySelector('[data-ds-now]').onclick = async event => {
    const button = event.target;
    button.disabled = true; status.textContent = 'Reading the directory…';
    const slot = host.querySelector('[data-ds-preview]');
    try {
      const preview = await post('/v2/directory/preview', {});
      const p = preview.plan, need = preview.needs_confirmation, needs = need.first || need.mass_leave;
      const any = ['adds', 'updates', 'restores', 'leaves'].some(k => p[k].length);
      slot.innerHTML = `<div data-ds-plan><h3>Preview: nothing is changed until you apply</h3>
        <p><b>${p.adds.length}</b> to add, <b>${p.updates.length}</b> to update, <b>${p.restores.length}</b> to restore, <b>${p.leaves.length}</b> to mark as left.</p>
        ${list('Add', p.adds, r => `${text(r.name || r.email)} <span class="muted">${text(r.email)}</span>`)}
        ${list('Update', p.updates, r => `${text(r.email)} <span class="muted">${text(Object.keys(r.changes).join(', '))}</span>`)}
        ${list('Restore', p.restores, r => text(r.email))}
        ${list('Mark as left', p.leaves, r => `${text(r.name || r.email)} <span class="muted">${text(r.email)}: ${text(r.reason)}</span>`)}
        ${list('Protected', p.protected, r => `${text(r.email)} <span class="muted">${text(r.reason)}</span>`)}
        ${list('Skipped', p.skipped, r => `${text(r.email)} <span class="muted">${text(r.reason)}</span>`)}
        ${need.first ? '<p class="muted">This is the first sync, so it needs your confirmation.</p>' : ''}
        ${need.mass_leave ? `<p class="err">This would mark more than ${text(preview.mass_leave_limit)} people as left. Check the list before you confirm.</p>` : ''}
        ${needs ? '<label><input type="checkbox" data-ds-confirm> I have reviewed this list and want to apply it</label>' : ''}
        <div class="row"><button class="primary" type="button" data-ds-apply ${any ? '' : 'disabled'}>${any ? 'Apply' : 'Nothing to apply'}</button></div></div>`;
      const apply = slot.querySelector('[data-ds-apply]'), box = slot.querySelector('[data-ds-confirm]');
      if (box) { apply.disabled = true; box.onchange = () => { apply.disabled = !box.checked; }; }
      apply.onclick = async () => {
        apply.disabled = true;
        try {
          const out = await post('/v2/directory/sync', {confirm: !!box?.checked, plan_hash: p.hash});
          if (!out.applied) { status.textContent = 'The directory changed since the preview; review it again.'; apply.disabled = false; return; }
          toast?.('Directory synced');
          onChange ? onChange() : window.mountDirectorySync(host);
        } catch (error) { status.textContent = error.message; apply.disabled = false; }
      };
      status.textContent = '';
    } catch (error) { status.textContent = error.message; }
    button.disabled = false;
  };
};
