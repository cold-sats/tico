window.attachDocReview = function (container, proposal) {
  const box = document.createElement('div');
  box.innerHTML = '<button type="button">Chat / review with Doc Updater</button><div hidden><p class="revision"></p><div class="fresh-diffs"></div><div class="thread" aria-live="polite"></div><form><textarea aria-label="Feedback for Doc Updater" rows="3" maxlength="12000" required placeholder="Ask about this change or describe a revision…" style="width:100%"></textarea><button type="submit">Send feedback</button><button type="button" class="merge" disabled>Merge reviewed revision</button></form><p class="status" role="status"></p></div>';
  container.append(box);
  let review, timer;
  const status = box.querySelector('.status'), form = box.querySelector('form'), field = box.querySelector('textarea');
  const context = {page:'doc-pr', repo:proposal.repo, number:proposal.number};
  const show = messages => {
    box.querySelector('.thread').innerHTML = messages.map(m => '<p><strong>' + (m.from_actor === 'bot:doc-updater' ? 'Doc Updater' : 'You') + '</strong></p>' + safeMd(m.refs?.comment || m.body)).join('');
  };
  const load = async () => {
    review = await post('/v2/page-chat', {...context,action:'load'});
    show(review.messages);
    box.querySelector('.revision').textContent = 'Reviewing ' + review.pr.head_sha.slice(0,12) + ' · ' + review.pr.state + (review.pr.merge_eligible ? '' : ' · Merge unavailable: requires an open, non-draft, docs-only PR from this repository.');
    const diffs = box.querySelector('.fresh-diffs'); diffs.replaceChildren();
    for (const file of review.pr.files) {
      const details = document.createElement('details'), summary = document.createElement('summary'), pre = document.createElement('pre');
      summary.textContent = 'Current revision: ' + file.path + ' · ' + file.status;
      pre.textContent = file.patch || 'No inline diff available. Review the complete change on GitHub.';
      details.append(summary,pre); diffs.append(details);
    }
    box.querySelector('.merge').disabled = !review.pr.merge_eligible;
    clearInterval(timer);
    if (review.conversation) timer = setInterval(async () => {
      if (!box.isConnected) {clearInterval(timer); return;}
      try {const result = await get('/v2/conversations/' + review.conversation.id + '/messages'); show(result.messages || []);} catch {status.textContent = 'Could not refresh replies. Reopen this review to retry.';}
    },3000);
  };
  box.querySelector('button').onclick = async () => {
    box.querySelector('div').hidden = false;
    try {await load();} catch(e) {status.textContent = e.message;}
  };
  const send = async action => {
    const text = action === 'merge' ? 'Merge the reviewed revision ' + review.pr.head_sha + '.' : field.value.trim();
    if (!text) return;
    form.querySelectorAll('button').forEach(b => b.disabled = true);
    try {
      const result = await post('/v2/page-chat', {...context,action,text,head_sha:review?.pr.head_sha});
      show(result.messages); field.value = '';
      status.textContent = action === 'merge' ? 'Merge review requested for this exact revision. Doc Updater will verify scope and checks, then ask for explicit approval before any merge.' : 'Sent to Doc Updater. This conversation is saved with the PR.';
      await load();
    } catch(e) {status.textContent = e.message;}
    finally {form.querySelector('[type=submit]').disabled = false;}
  };
  form.onsubmit = e => {e.preventDefault(); send('feedback');};
  box.querySelector('.merge').onclick = () => send('merge');
};
