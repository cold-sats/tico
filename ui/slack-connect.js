/* Settings > Cloud services > Slack: paste the two tokens of the Slack app created from the manifest
   (docs/slack.md). They are sent once and stored encrypted; the browser is never sent them back. */
window.mountSlackConnect = async function (host) {
  if (!host) return;
  const text = value => { const s = document.createElement('span'); s.textContent = value ?? ''; return s.innerHTML; };
  let state;
  try { state = await get('/v2/slack/app'); }
  catch (error) { host.innerHTML = `<div class="empty">${text(error.message)}</div>`; return; }
  if (!host.isConnected) return;
  const labels = {connected: 'Connected.', waiting: 'Tokens saved; waiting for the Slack service to connect. Is <code>slack</code> in COMPOSE_PROFILES?',
    disconnected: 'Disconnected'};
  if (state.configured) {
    host.innerHTML = `<p data-slack-state="${text(state.state)}"><strong>${labels[state.state] || 'Tokens saved.'}</strong>
      ${state.state === 'disconnected' && state.message ? ' ' + text(state.message) : ''}</p>
      <div class="row"><button type="button" class="ghost" data-slack-disconnect>Disconnect</button></div>
      <p class="muted">Disconnect only forgets the tokens here. Delete or reinstall the app on Slack to revoke them there.</p>
      <p role="status" data-slack-status></p>`;
    host.querySelector('[data-slack-disconnect]').onclick = async event => {
      if (!confirm('Forget the Slack tokens? Bots stop answering in Slack.')) return;
      event.target.disabled = true;
      try { await post('/v2/slack/disconnect', {}); window.mountSlackConnect(host); }
      catch (error) { host.querySelector('[data-slack-status]').textContent = error.message; event.target.disabled = false; }
    };
    return;
  }
  host.innerHTML = `<form data-slack-form style="display:grid;gap:10px;max-width:460px">
      <p class="muted">1. At api.slack.com/apps choose <strong>Create New App &gt; From a manifest</strong> and paste the manifest.
      <a href="#" data-slack-manifest>Copy the manifest</a></p>
      <p class="muted">2. <strong>Install App</strong> to your workspace and copy the <strong>Bot User OAuth Token</strong> (xoxb-). Under Basic Information &gt; App-Level Tokens create one with <code>connections:write</code> (xapp-).</p>
      <label>Bot token<input name="bot_token" type="password" required autocomplete="off" spellcheck="false" placeholder="xoxb-..."></label>
      <label>App-level token<input name="app_token" type="password" required autocomplete="off" spellcheck="false" placeholder="xapp-..."></label>
      <button class="primary" type="submit">Connect Slack</button>
      <p role="status" data-slack-status></p></form>`;
  const status = host.querySelector('[data-slack-status]');
  host.querySelector('[data-slack-manifest]').onclick = async event => {
    event.preventDefault();
    try {
      await navigator.clipboard.writeText(JSON.stringify(await get('/v2/slack/manifest'), null, 2));
      status.textContent = 'Manifest copied. Choose the JSON tab on Slack and paste it.';
    } catch (error) { status.textContent = error.message; }
  };
  host.querySelector('[data-slack-form]').onsubmit = async event => {
    event.preventDefault();
    const form = event.target;
    try {
      await put('/v2/slack/tokens', {bot_token: form.bot_token.value.trim(), app_token: form.app_token.value.trim()});
      window.mountSlackConnect(host);
    } catch (error) { status.textContent = error.message; }
  };
};
