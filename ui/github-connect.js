/* Tools > GitHub: connect the team's GitHub organization through a GitHub App the
   owner creates there (docs/github-app.md). The private key never reaches the browser. */
window.mountGithubConnect = async function (host) {
  if (!host) return;
  const text = value => { const s = document.createElement('span'); s.textContent = value ?? ''; return s.innerHTML; };
  let state;
  try { state = await get('/v2/github/app'); }
  catch (error) { host.innerHTML = `<div class="empty">${text(error.message)}</div>`; return; }
  if (!host.isConnected) return;
  if (state.connected) {
    host.innerHTML = `<p>Connected to <strong>${text(state.org)}</strong> through the app <strong>${text(state.slug)}</strong>.
      <span data-gh-install>${state.installed ? 'Installed on the organization.' : 'Not installed yet.'}</span></p>
      <p class="muted">${state.administration ? 'Tico may create bot repositories.' : 'Tico may not create repositories; create them yourself.'}</p>
      ${state.installed ? '' : `<p class="muted">Choose <strong>All repositories</strong> when GitHub asks. Each bot's token still covers only its own repository.</p>`}
      <div class="row">${state.installed ? '' : `<a class="primary" role="button" href="${text(state.install_url)}" target="_blank" rel="noopener">Install on ${text(state.org)}</a>`}
      <button type="button" class="ghost" data-gh-disconnect>Disconnect</button>
      <a href="${text(state.uninstall_url)}" target="_blank" rel="noopener">Uninstall on GitHub</a></div>
      <p class="muted">Disconnect forgets the app here; delete it on GitHub to revoke access.</p>
      <p role="status" data-gh-status></p>`;
    host.querySelector('[data-gh-disconnect]').onclick = async event => {
      if (!confirm('Forget the GitHub app?')) return;
      event.target.disabled = true;
      try { await post('/v2/github/app/disconnect', {}); window.mountGithubConnect(host); }
      catch (error) { host.querySelector('[data-gh-status]').textContent = error.message; event.target.disabled = false; }
    };
    return;
  }
  host.innerHTML = `<form data-gh-form style="display:grid;gap:10px;max-width:460px">
      <p class="muted">When GitHub asks where to install, choose <strong>All repositories</strong>. Each bot's token still covers only its own repository. For sensitive code, use a separate organization.</p>
      <label>Organization<input name="org" type="text" required maxlength="39" autocomplete="off" spellcheck="false" pattern="[A-Za-z0-9][A-Za-z0-9-]*" placeholder="your-org"></label>
      <label>App name<input name="name" type="text" maxlength="34" autocomplete="off" placeholder="Acme Tico"></label>
      <label><input type="checkbox" name="administration"> Let Tico create bot repositories</label>
      <button class="primary" type="submit">Connect GitHub</button>
      <p role="status" data-gh-status></p></form>`;
  host.querySelector('[data-gh-form]').onsubmit = async event => {
    event.preventDefault();
    const form = event.target, status = host.querySelector('[data-gh-status]');
    const query = new URLSearchParams({org: form.org.value.trim(), administration: String(form.administration.checked)});
    if (form.name.value.trim()) query.set('name', form.name.value.trim());
    try {
      const setup = await get('/v2/github/app/manifest?' + query);
      const post_form = document.createElement('form');
      post_form.method = 'post'; post_form.action = setup.action;
      const field = document.createElement('input');
      field.type = 'hidden'; field.name = 'manifest'; field.value = JSON.stringify(setup.manifest);
      post_form.append(field); document.body.append(post_form); post_form.submit();
    } catch (error) { status.textContent = error.message; }
  };
};
