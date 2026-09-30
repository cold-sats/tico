window.pageChangelog = async function () {
  const root = document.querySelector('#main');
  root.innerHTML = '<div class="release-page"><header class="release-header"><h1>Changelog</h1></header><div class="release-filters"><input type="search" aria-label="Search changes" autocomplete="off" placeholder="Search changes…"><select aria-label="Filter changes"><option value="product">Product updates</option><option value="">All activity</option></select><button class="ghost release-review" hidden>Review drafts</button><button class="primary round-add" type="button" aria-label="Add product update" title="Add product update" hidden data-add-update>+</button></div><div class="release-list" aria-live="polite">Loading changes…</div></div>';
  let data;
  try {data = await get('/changelog');} catch(e) {root.querySelector('.release-list').textContent=e.message;return;}
  if (!root.querySelector('.release-list')) return;
  const search=root.querySelector('input'), filter=root.querySelector('select'), list=root.querySelector('.release-list');
  const render = () => {
    const q=search.value.toLowerCase().trim();
    const rows=data.entries.filter(r=>(!filter.value || r.kind===filter.value) && (!q || (r.title+' '+r.bullets.join(' ')).toLowerCase().includes(q)));
    list.innerHTML=rows.map(r=>`<article class="release-entry"><div class="release-date"><time datetime="${esc(r.shipped_at)}">${esc(r.shipped_at ? new Date(r.shipped_at).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}) : '')}</time><span class="release-dot" aria-hidden="true"></span></div><div class="release-card"><span class="release-area">${esc(r.kind === 'activity' ? 'Bot activity' : 'Product')}</span><h2>${esc(r.title)}</h2><ul>${r.bullets.map(b=>`<li>${esc(r.kind==='activity' && typeof plainMd==='function' ? plainMd(b) : b)}</li>`).join('')}</ul>${r.task_id ? `<button class="linkish release-source" data-activity-task="${esc(r.task_id)}">View outcome</button>` : ''}</div></article>`).join('') || '<div class="empty">No changes in this view.</div>';
  };
  list.onclick=async e=>{
    const button=e.target.closest('[data-activity-task]');if(!button)return;
    try{
      const result=await get('/v2/tasks/'+encodeURIComponent(button.dataset.activityTask));
      const dialog=document.createElement('dialog');dialog.className='tmodal docs-proposals';
      dialog.innerHTML=`<div class="tmodal-head"><h2>Reported task outcome</h2><span class="spacer"></span><button aria-label="Close">✕</button></div><div class="docs-proposals-body"><h3>${esc(result.task.title)}</h3>${safeMd(result.task.note || 'No outcome recorded.')}</div>`;
      document.body.append(dialog);dialog.showModal();dialog.querySelector('button').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
    }catch(error){toast(error.message,true);}
  };
  search.oninput=render;filter.onchange=render;render();
  const add=root.querySelector('[data-add-update]');
  add.hidden=!data.can_add;
  add.onclick=()=>{
    const dialog=document.createElement('dialog');dialog.className='tmodal docs-proposals';
    dialog.innerHTML='<div class="tmodal-head"><h2>Product update</h2><span class="spacer"></span><button aria-label="Close">✕</button></div><div class="docs-proposals-body"><p class="muted">What humans will notice. One change, a few bullets. This is the default Changelog view.</p><label>Title<input class="draft-title" style="width:100%" maxlength="90"></label><label>Bullets — one per line<textarea class="draft-bullets" style="width:100%" rows="4"></textarea></label><p class="row"><button class="primary" data-publish>Publish</button></p><p class="draft-status" role="status"></p></div>';
    document.body.append(dialog);dialog.showModal();
    dialog.querySelector('[aria-label="Close"]').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
    dialog.querySelector('[data-publish]').onclick=async()=>{
      const title=dialog.querySelector('.draft-title').value.trim();
      const bullets=dialog.querySelector('.draft-bullets').value.split('\n').map(b=>b.trim()).filter(Boolean);
      const status=dialog.querySelector('.draft-status');
      try{await post('/changelog',{title,bullets});dialog.close();data=await get('/changelog');if(location.hash==='#/changelog')render();}
      catch(e){status.textContent=e.message;}
    };
  };
  const review=root.querySelector('.release-review');
  review.hidden=!data.can_review || !data.drafts.length;review.textContent=`Review drafts (${data.drafts.length})`;
  review.onclick=()=>{
    const dialog=document.createElement('dialog');dialog.className='tmodal docs-proposals';
    dialog.innerHTML='<div class="tmodal-head"><h2>Announcement drafts</h2><span class="spacer"></span><button aria-label="Close">✕</button></div><div class="docs-proposals-body"><p class="muted">Publish only meaningful changes verified live. Remove names, research, routine activity and technical details. Combine related changes.</p><div class="release-drafts"></div></div>';
    const drafts=dialog.querySelector('.release-drafts');
    for(const draft of data.drafts){
      const card=document.createElement('section');card.className='card';
      card.innerHTML=`<label>Title<input class="draft-title" style="width:100%" maxlength="90" value="${esc(draft.title)}"></label><label>Bullets — one per line<textarea class="draft-bullets" style="width:100%" rows="4">${esc(draft.bullets.join('\n'))}</textarea></label><p class="muted">${esc(draft.evidence?.observation || 'No deployment evidence supplied.')}</p><p class="proof"></p><button class="publish">Publish announcement</button> <button class="ghost dismiss">Dismiss</button><p class="draft-status" role="status"></p>`;
      const proof=draft.evidence?.url;
      if(proof && /^https?:\/\//.test(proof)){const a=document.createElement('a');a.href=proof;a.target='_blank';a.rel='noopener noreferrer';a.textContent='Inspect deployment evidence ↗';card.querySelector('.proof').append(a);}
      const send=async action=>{
        card.querySelectorAll('button').forEach(b=>b.disabled=true);
        try{await post('/changelog/'+action,{id:draft.id,title:card.querySelector('.draft-title').value,bullets:card.querySelector('.draft-bullets').value.split('\n').map(b=>b.trim()).filter(Boolean)});card.remove();data=await get('/changelog');if(location.hash==='#/changelog')render();review.textContent=`Review drafts (${data.drafts.length})`;review.hidden=!data.drafts.length;}
        catch(e){card.querySelector('.draft-status').textContent=e.message;card.querySelectorAll('button').forEach(b=>b.disabled=false);}
      };
      card.querySelector('.publish').onclick=()=>send('publish');card.querySelector('.dismiss').onclick=()=>send('dismiss');drafts.append(card);
    }
    document.body.append(dialog);dialog.showModal();dialog.querySelector('button').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();
  };
};
