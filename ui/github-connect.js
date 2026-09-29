/* Settings > Cloud services: connect the company's GitHub organization through a GitHub App the
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
      ${state.installed ? '' : `<p class="muted">When GitHub asks where to install the app, choose <strong>All repositories</strong>: bots get new repositories automatically. Each bot's token is still limited to its own repository plus any extra repositories you allow on its settings. If this organization also holds sensitive code, create a separate GitHub organization for bot repositories and connect that one.</p>`}
      <div class="row">${state.installed ? '' : `<a class="primary" role="button" href="${text(state.install_url)}" target="_blank" rel="noopener">Install on ${text(state.org)}</a>`}
      <button type="button" class="ghost" data-gh-disconnect>Disconnect</button>
      <a href="${text(state.uninstall_url)}" target="_blank" rel="noopener">Uninstall on GitHub</a></div>
      <p class="muted">Disconnect only forgets the app here. Uninstall or delete it on GitHub to revoke its access.</p>
      <p role="status" data-gh-status></p>`;
    host.querySelector('[data-gh-disconnect]').onclick = async event => {
      if (!confirm('Forget this GitHub connection? Bots fall back to the git access on their computer.')) return;
      event.target.disabled = true;
      try { await post('/v2/github/app/disconnect', {}); window.mountGithubConnect(host); }
      catch (error) { host.querySelector('[data-gh-status]').textContent = error.message; event.target.disabled = false; }
    };
    return;
  }
  host.innerHTML = `<form data-gh-form style="display:grid;gap:10px;max-width:460px">
      <p class="muted">Bots get GitHub access through an app you create in your own organization, so no personal token is shared. GitHub asks you to confirm it.</p>
      <p class="muted">When GitHub asks where to install the app, choose <strong>All repositories</strong>: bots get new repositories automatically. Each bot's token is still limited to its own repository plus any extra repositories you allow on its settings. If this organization also holds sensitive code, create a separate GitHub organization for bot repositories and connect that one.</p>
      <label>GitHub organization<input name="org" required maxlength="39" pattern="[A-Za-z0-9][A-Za-z0-9-]*" placeholder="your-org"></label>
      <label>App name<input name="name" maxlength="34" placeholder="Your Company Tico"></label>
      <label><input type="checkbox" name="administration"> Allow Tico to create bot repositories</label>
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
