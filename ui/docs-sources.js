/* Repository configuration is saved in the cloud; fetching runs on the worker. */
window.openDocsSources = async function () {
  const dialog = document.createElement('dialog');
  dialog.className = 'tmodal docs-proposals';
  dialog.innerHTML = `<div class="tmodal-head"><h2>Documentation sources</h2><span class="spacer"></span><button type="button" aria-label="Close sources">✕</button></div>
    <div class="docs-proposals-body"><p>Link a Git repository and choose its documentation folder. Private repositories use the worker’s Git access. Linked documents are visible to the owner.</p>
    <ul class="source-list"></ul><form style="display:grid;gap:12px">
    <label>Repository URL<input name="repo" required maxlength="1000" placeholder="https://github.com/your-org/repo.git" style="width:100%"></label>
    <label>Documentation folder<input name="folder" value="docs" maxlength="500" placeholder="docs or . for the repository root" style="width:100%"></label>
    <label>Branch (optional)<input name="branch" maxlength="200" placeholder="Default branch" style="width:100%"></label>
    <p class="muted">Imports Markdown, MDX, text and reStructuredText files. Source files stay in their repository.</p>
    <button type="submit">Link and import</button></form><p class="source-status" role="status"></p></div>`;
  document.body.append(dialog); dialog.showModal();
  dialog.querySelector('button').onclick = () => dialog.close();
  dialog.onclose = () => { dialog.remove(); if (typeof pageCompanyDocs === 'function') pageCompanyDocs(); };
  const status = dialog.querySelector('.source-status');
  async function list() {
    const result = await get('/v2/document-sources');
    const ul = dialog.querySelector('.source-list'); ul.replaceChildren();
    for (const source of result.sources) {
      const li = document.createElement('li'), button = document.createElement('button');
      li.append(document.createTextNode(source.repo + ' / ' + source.folder + ' (' + (source.branch || 'default branch') + ') '));
      button.textContent = 'Unlink'; button.type = 'button';
      button.onclick = async () => {
        button.disabled = true;
        try {
          await post('/v2/document-sources/' + encodeURIComponent(source.id) + '/unlink', {});
          await list(); status.textContent = 'Unlinked. Repository files were preserved.';
        } catch (error) { status.textContent = error.message; button.disabled = false; }
      };
      li.append(button); ul.append(li);
    }
    if (!result.sources.length) ul.textContent = 'No additional repositories linked.';
  }
  dialog.querySelector('form').onsubmit = async event => {
    event.preventDefault(); const form = event.target, button = form.querySelector('button');
    button.disabled = true; status.textContent = 'Saving source…';
    try {
      await post('/v2/document-sources', Object.fromEntries(new FormData(form)));
      await list(); status.textContent = 'Source linked. Requesting import…';
      try {
        await post('/company-docs/refresh', {});
        status.textContent = 'Source linked. Import queued; documents appear after the worker finishes. Check the library status for import errors.';
      } catch (error) { status.textContent = 'Source linked, but import could not start: ' + error.message + ' Use Refresh sources to retry.'; }
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  };
  try { await list(); } catch (error) { status.textContent = error.message; }
};
