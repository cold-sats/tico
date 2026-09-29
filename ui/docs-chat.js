/* Documentation agent chat, with streamed answers on legacy installations. */
window.openDocsChat = function ({docId = '', collection = 'docs', title = ''} = {}) {
  const dialog = document.createElement('dialog');
  dialog.className = 'tmodal docs-proposals';
  dialog.innerHTML = '<div class="tmodal-head"><h2>Ask Docs</h2><span class="spacer"></span><button aria-label="Close chat">✕</button></div>' +
    '<div class="docs-proposals-body"><p class="scope"></p><div class="answers" aria-live="polite"></div>' +
    '<form><label for="docs-question">Ask a question or follow up</label><textarea id="docs-question" rows="3" maxlength="4000" required style="width:100%" placeholder="How do we handle a refund request?"></textarea>' +
    '<button type="submit">Ask Docs</button><span class="chat-status" role="status"></span></form></div>';
  if (window.ticoIsCloud?.()) {
    dialog.querySelector('h2').textContent = 'Ask AI about docs';
    dialog.querySelector('label').textContent = 'Ask Doc Updater a question or request a documentation edit';
    dialog.querySelector('textarea').placeholder = 'Find our onboarding steps, or update the setup guide…';
    dialog.querySelector('[type=submit]').textContent = 'Send';
  }
  dialog.querySelector('.scope').textContent = title || (collection === 'notes' ? 'Bot Notes — reference only, not current policy' : 'Current documentation · PMs, Pros, Developers and authorized internal docs');
  document.body.append(dialog); dialog.showModal();
  const history = [], controller = new AbortController();
  // The bot the hub routed the first question to answers the follow-ups too: Doc Updater (older hubs said coo). The page-chat response names it.
  let cloudConversation = '', cloudSources = [], cloudBot = '';
  const botName = slug => (typeof botDisplayName === 'function' ? botDisplayName(slug) : '') || slug || 'the bot';
  dialog.querySelector('button').onclick = () => dialog.close();
  dialog.onclose = () => {controller.abort(); dialog.remove();};
  const field = dialog.querySelector('textarea'), status = dialog.querySelector('.chat-status');
  field.focus();
  dialog.querySelector('form').onsubmit = async e => {
    e.preventDefault();
    const question = field.value.trim(); if (!question) return;
    const button = dialog.querySelector('[type=submit]'); button.disabled = true;
    const turn = document.createElement('section'), heading = document.createElement('h3'), answer = document.createElement('div'), sourceList = document.createElement('ol');
    heading.textContent = question; turn.append(heading, answer, sourceList); dialog.querySelector('.answers').append(turn);
    let text = '', done = false, sources = [];
    status.textContent = ' Searching documentation…';
    const render = () => {
      answer.innerHTML = safeMd(text.replace(/\[(\d+(?:,\s*\d+)+)\]/g, (_, numbers) => numbers.split(',').map(n => '[' + n.trim() + ']').join(' ')));
      // Convert only plain citation text, never HTML attributes or code blocks.
      const walker = document.createTreeWalker(answer, NodeFilter.SHOW_TEXT), nodes = [];
      while (walker.nextNode()) if (!walker.currentNode.parentElement.closest('a,code,pre')) nodes.push(walker.currentNode);
      for (const node of nodes) {
        const value = node.textContent, pattern = /\[(\d+)\]/g; let match, start = 0;
        const fragment = document.createDocumentFragment();
        while ((match = pattern.exec(value))) {
          fragment.append(value.slice(start, match.index));
          const source = sources[Number(match[1])-1];
          if (source) {const a = document.createElement('a'); a.textContent = match[0]; a.href = '#/docs/' + encodeURIComponent(source.id) + (collection === 'notes' ? '?collection=notes' : ''); a.title = source.title; a.onclick = () => dialog.close(); fragment.append(a);}
          else fragment.append('[source unavailable]');
          start = pattern.lastIndex;
        }
        if (start) {fragment.append(value.slice(start)); node.replaceWith(fragment);}
      }
    };
    try {
      if (window.ticoIsCloud?.()) {
        const result = cloudConversation
          ? await post('/v2/conversations/' + encodeURIComponent(cloudConversation) + '/messages', {text:question,refs:{comment:question}})
          : await post('/v2/page-chat', {page:'docs',text:question,doc_id:docId || null,collection});
        cloudConversation = result.conversation?.id || cloudConversation;
        cloudBot = result.bot || cloudBot;
        const sent = result.message;
        if (!cloudConversation || !sent?.id) throw new Error('The cloud did not confirm this saved question.');
        const context = sent.refs?.page_context || {};
        const rows = context.document ? [context.document] : (context.documents || []);
        if (rows.length) cloudSources = rows.map(item => ({id:item.id,title:item.title || item.id,category:item.category || '',
          excerpt:String(item.search || item.content || '').slice(0,500)}));
        sources = cloudSources;
        sourceList.replaceChildren();
        for (const s of sources) {
          const li = document.createElement('li'), a = document.createElement('a');
          a.textContent = s.title; a.href = '#/docs/' + encodeURIComponent(s.id) + (collection === 'notes' ? '?collection=notes' : ''); a.onclick = () => dialog.close();
          li.append(a, document.createTextNode(s.category ? ' · ' + s.category : ''));
          if (s.excerpt) {const details=document.createElement('details'),summary=document.createElement('summary'),excerpt=document.createElement('p');summary.textContent='Source excerpt';excerpt.textContent=s.excerpt;details.append(summary,excerpt);li.append(details);}
          sourceList.append(li);
        }
        status.textContent = ` Saved — waiting for ${botName(cloudBot || 'doc-updater')}…`;
        while (dialog.open && !controller.signal.aborted) {
          const snapshot = await get('/v2/conversations/' + encodeURIComponent(cloudConversation) + '/snapshot');
          const reply = (snapshot.messages || []).find(message => message.in_reply_to === sent.id &&
            (cloudBot ? message.from_actor === 'bot:' + cloudBot : String(message.from_actor || '').startsWith('bot:')));
          if (reply) {
            text = reply.body || ''; render(); done = true;
            status.textContent = ` Answered by ${botName(reply.from_actor.slice(4))}`;
            history.push({question,answer:text}); field.value = '';
            break;
          }
          if (snapshot.execution?.label) status.textContent = ' ' + snapshot.execution.label;
          if (snapshot.execution?.message_id === sent.id && ['cancelled', 'uncertain', 'completed'].includes(snapshot.execution.state)) {
            throw new Error(snapshot.execution.state === 'completed' ? 'The worker finished without an answer. Your message is saved.' : snapshot.execution.label);
          }
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
        return;
      }
      const response = await fetch('/api/company-docs/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({question,history,doc_id:docId,collection}), signal:controller.signal});
      if (!response.ok) throw new Error('Unable to open Docs chat. Reload and try again.');
      const reader = response.body.getReader(), decoder = new TextDecoder(); let pending = '';
      const event = item => {
        if (item.type === 'error') throw new Error(item.message);
        if (item.type === 'sources') {
          sources = item.sources; status.textContent = ' Writing answer…';
          for (const s of sources) {
            const li = document.createElement('li'), a = document.createElement('a');
            a.textContent = s.title; a.href = '#/docs/' + encodeURIComponent(s.id) + (collection === 'notes' ? '?collection=notes' : ''); a.onclick = () => dialog.close();
            li.append(a, document.createTextNode(' · ' + s.category));
            const details = document.createElement('details'), summary = document.createElement('summary'), excerpt = document.createElement('p');
            summary.textContent = 'Source excerpt'; excerpt.textContent = s.excerpt; details.append(summary,excerpt); li.append(details); sourceList.append(li);
          }
        }
        if (item.type === 'text') {text += item.text; render();}
        if (item.type === 'done') {done = true; status.textContent = item.elapsed_ms ? ' Answered in ' + (item.elapsed_ms/1000).toFixed(1) + 's' : '';}
      };
      while (true) {
        const chunk = await reader.read(); if (chunk.done) break;
        pending += decoder.decode(chunk.value,{stream:true});
        const lines = pending.split('\n'); pending = lines.pop();
        for (const line of lines) if (line.trim()) event(JSON.parse(line));
      }
      if (!done) throw new Error('Answer interrupted. Please retry.');
      history.push({question,answer:text}); field.value = '';
    } catch (error) {if (error.name !== 'AbortError') status.textContent = error.message;}
    finally {button.disabled = false; field.focus();}
  };
};
