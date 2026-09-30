/* Market is its own room: a note, the graph of who connects to whom, and a librarian
   that reads the graph at the moment you ask. It is not the Docs library. */
let MARKET_VIEW = null;

const MARKET_TYPES = [
  ['company', 'Companies'],
  ['segment', 'Segments'],
  ['channel', 'Channels'],
  ['person', 'People'],
  ['product', 'Products'],
  ['regulation', 'Regulation'],
  ['geography', 'Places'],
  ['event', 'Events'],
];

const MARKET_BRIEF = 'brief';

// Nothing about the market is written here: the Overview is the page the Librarian writes
// (playbooks/market-setup.md), and until it exists there is only the setup card in getting-started.js.
const marketStyle = document.createElement('style');
marketStyle.textContent = '.market-blank{margin:0;color:#9a9a9a}.market-hint{display:none}'
  + 'body:has(#gs-card [data-gs-market]) .market-hint{display:inline}';
document.head.appendChild(marketStyle);

// The node for your own company sits at the centre of the graph. The hub may name it in its
// status (company_entity); otherwise the convention is company/self.
const marketSelfId = () => (typeof S !== 'undefined' && S.status && S.status.company_entity) || 'company/self';

function marketNoteId() {
  if (S.route.startsWith('#/market/')) return decodeURIComponent(S.route.slice('#/market/'.length).split('?')[0]);
  return new URLSearchParams((S.route.split('?')[1] || '')).get('note') || MARKET_BRIEF;
}

function marketHref(id) {
  return '#/market?note=' + encodeURIComponent(id);
}

window.marketStop = function marketStop() {
  if (MARKET_VIEW) MARKET_VIEW.stop();
};

// The research notice (getting-started.js) calls this when the market has new content. A question being
// typed is left alone.
window.marketReload = function marketReload() {
  if (!MARKET_VIEW || !(S.route === '#/market' || S.route.startsWith('#/market?') || S.route.startsWith('#/market/'))) return;
  const ask = $('#market-q');
  if (ask && (ask.value || document.activeElement === ask)) return;
  MARKET_VIEW.stop();
  MARKET_VIEW = null;
  void pageMarket();
};

window.pageMarket = async function pageMarket() {
  $('#main').classList.add('market-layout');
  const note = marketNoteId();
  if (!MARKET_VIEW || !document.body.contains(MARKET_VIEW.shell)) {
    $('#main').innerHTML = '<div id="market-shell" class="market-shell"><p class="market-loading">Opening the market…</p></div>';
    const shell = $('#market-shell');
    try {
      MARKET_VIEW = await mountMarket(shell);
    } catch (error) {
      shell.innerHTML = `<p class="market-loading">${esc(error.message || 'The market graph did not load.')}</p>`;
      return;
    }
  }
  await MARKET_VIEW.open(note);
};

async function mountMarket(shell) {
  const today = new Date().toISOString().slice(0, 10);
  const [entities, edges, library] = await Promise.all([
    get('/v2/market/entities'),
    get('/v2/market/edges?as_of=' + today),
    get('/company-docs?collection=market'),
  ]);
  const nodes = (entities.entities || []).filter(row => row.status !== 'retired' && row.status !== 'merged');
  const byId = new Map(nodes.map(row => [row.id, row]));
  const links = (edges.edges || []).filter(edge => byId.has(edge.src) && byId.has(edge.dst));
  // A fresh install starts with pages the seed wrote ("None in the seed."): they are not shown until the graph has rows.
  const pages = (library.documents || []).filter(doc => nodes.length || !doc.seeded).sort((a, b) => a.title.localeCompare(b.title));
  shell.innerHTML = `<aside class="market-list" aria-label="Market notes">
      <a id="market-overview" class="market-overview-btn" href="${marketHref(MARKET_BRIEF)}">Overview</a>
      <input id="market-filter" type="search" placeholder="Search the market" aria-label="Search the market" autocomplete="off">
      <div id="market-index"></div>
    </aside>
    <section class="market-note">
      <div id="market-read" class="market-read"></div>
      <form id="market-ask" class="market-ask">
        <label for="market-q">Ask the librarian</label>
        <div class="market-ask-row">
          <input id="market-q" name="q" type="text" placeholder="Who competes with us?" autocomplete="off">
          <button type="submit">Ask</button>
        </div>
        <div id="market-answer" class="market-answer" hidden></div>
      </form>
    </section>
    <div class="market-graph">
      <canvas id="market-canvas" aria-label="Graph of the market"></canvas>
    </div>`;
  const graph = mountGraph($('#market-canvas'), nodes, links);
  const index = $('#market-index');
  const filter = $('#market-filter');

  function renderIndex(query) {
    const q = query.trim().toLowerCase();
    const match = row => !q || (row.name || row.title || '').toLowerCase().includes(q) || (row.id || '').toLowerCase().includes(q);
    const groups = [['Pages', pages.filter(doc => doc.id !== 'market/overview').map(doc => ({id: doc.id, name: doc.title}))]];
    for (const [type, label] of MARKET_TYPES) {
      const rows = nodes.filter(row => row.type === type && match(row));
      if (rows.length) groups.push([label, rows]);
    }
    const shownPages = groups[0][1].filter(match);
    groups[0][1] = shownPages;
    index.innerHTML = groups.filter(([, rows]) => rows.length).map(([label, rows]) =>
      `<section><h2>${esc(label)}</h2><ul>${rows.map(row =>
        `<li><a href="${marketHref(row.id)}" data-market-note="${esc(row.id)}">${esc(row.name || row.title)}</a></li>`).join('')}</ul></section>`
    ).join('') || (q ? '<p class="market-empty">Nothing matches.</p>' : '');
  }
  renderIndex('');
  filter.oninput = () => renderIndex(filter.value);
  $('#market-ask').onsubmit = async event => {
    event.preventDefault();
    const question = $('#market-q').value.trim();
    if (!question) return;
    const box = $('#market-answer');
    box.hidden = false;
    box.innerHTML = '<p class="market-pulling">Pulling from the market graph…</p>';
    try {
      const out = await post('/v2/market/ask', {question});
      const cites = out.citations || [];
      graph.cite(cites.filter(row => row.kind === 'entity').map(row => row.id));
      const chips = cites.map(row => {
        const node = byId.get(row.id);
        const label = node ? node.name : 'evidence';
        const href = node ? marketHref(row.id) : '';
        return href ? `<a href="${href}" data-market-note="${esc(row.id)}">${esc(label)}</a>` : `<span>${esc(label)}</span>`;
      }).join(' ');
      const prose = String(out.answer || '').replace(/\s*\[[a-z]+:[^\]]+\]/gi, '');
      box.innerHTML = `<div class="md market-md">${safeMd(prose)}</div>`
        + (chips ? `<p class="market-cites">Pulled ${esc(String(cites.length))} ${cites.length === 1 ? 'row' : 'rows'}: ${chips}</p>` : '');
    } catch (error) {
      box.innerHTML = `<p class="market-pulling">${esc(error.message || 'The librarian could not answer.')}</p>`;
    }
  };

  async function open(id) {
    const overview = $('#market-overview');
    const onBrief = id === MARKET_BRIEF;
    overview.classList.toggle('cur', onBrief);
    if (onBrief) overview.setAttribute('aria-current', 'page'); else overview.removeAttribute('aria-current');
    index.querySelectorAll('a').forEach(link => {
      const on = link.dataset.marketNote === id;
      link.classList.toggle('cur', on);
      if (on) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    });
    const read = $('#market-read');
    const showDoc = async doc => {
      const full = await get('/company-docs/' + doc.id.split('/').map(encodeURIComponent).join('/'));
      read.innerHTML = `<p class="market-kicker">Market</p><div class="md market-md">${safeMd(full.content || '')}</div>`;
      graph.focus(null);
    };
    if (onBrief) {
      const overview = pages.find(row => row.id === 'market/overview');
      if (overview) { await showDoc(overview); return; }
      read.innerHTML = '<p class="market-blank">Nothing here yet.<span class="market-hint"> Start the research above.</span></p>';
      graph.focus(null);
      return;
    }
    if (byId.has(id)) {
      const shown = await get('/v2/market/entities/' + id.split('/').map(encodeURIComponent).join('/'));
      read.innerHTML = renderEntity(shown, byId);
      graph.focus(id);
      const current = index.querySelector('a.cur');
      if (current) current.scrollIntoView({block: 'nearest'});
      return;
    }
    const doc = pages.find(row => row.id === id);
    if (!doc) {
      read.innerHTML = '<p class="market-empty">That note is not in the market.</p>';
      graph.focus(null);
      return;
    }
    await showDoc(doc);
  }

  return {shell, open, stop: () => graph.stop()};
}

function renderEntity(shown, names) {
  const entity = shown.entity;
  const bits = [entity.type, entity.tier].filter(Boolean).join(' · ');
  const aliases = (entity.aliases || []).filter(name => name && name !== entity.name);
  const nameOf = id => names.get(id)?.name || id;
  const lines = [];
  for (const [rel, bucket] of Object.entries(shown.edges || {})) {
    for (const edge of [...(bucket.out || []), ...(bucket.in || [])]) {
      const other = edge.src === entity.id ? edge.dst : edge.src;
      lines.push(`<li>${esc(rel.replaceAll('_', ' '))} <a href="${marketHref(other)}" data-market-note="${esc(other)}">${esc(nameOf(other))}</a></li>`);
    }
  }
  const evidence = (shown.evidence || []).map(row =>
    `<blockquote class="market-quote">${row.our_read ? `<p>${esc(row.our_read)}</p>` : ''}${row.quote ? `<p>${esc(row.quote)}</p>` : ''}</blockquote>`
  ).join('');
  return `<p class="market-kicker">${esc(bits || 'Entity')}</p><h1>${esc(entity.name)}</h1>
    ${entity.summary ? `<p class="market-summary">${esc(entity.summary)}</p>` : ''}
    ${aliases.length ? `<p class="market-aliases">Also called ${aliases.map(esc).join(', ')}</p>` : ''}
    ${lines.length ? `<h2>Connections</h2><ul class="market-rels">${lines.join('')}</ul>` : '<p class="market-empty">No current connections.</p>'}
    ${evidence ? `<h2>Evidence</h2>${evidence}` : ''}`;
}

function mountGraph(canvas, rows, edges) {
  const degree = new Map();
  edges.forEach(edge => {
    degree.set(edge.src, (degree.get(edge.src) || 0) + 1);
    degree.set(edge.dst, (degree.get(edge.dst) || 0) + 1);
  });
  const nodes = rows.map(row => ({
    id: row.id, name: row.name, type: row.type, tier: row.tier,
    r: 2.4 + Math.min(5.5, Math.sqrt(degree.get(row.id) || 0) * 1.7),
    x: 0, y: 0, vx: 0, vy: 0,
  }));
  const byId = new Map(nodes.map(node => [node.id, node]));
  const links = edges.map(edge => ({a: byId.get(edge.src), b: byId.get(edge.dst), rel: edge.rel})).filter(link => link.a && link.b);
  const linked = new Set(links.flatMap(link => [link.a.id, link.b.id]));
  let ring = 0;
  const free = nodes.filter(node => !linked.has(node.id));
  const bound = nodes.filter(node => linked.has(node.id) && node.id !== marketSelfId());
  bound.forEach((node, index) => {
    const angle = (index / Math.max(1, bound.length)) * Math.PI * 2;
    node.x = Math.cos(angle) * 150;
    node.y = Math.sin(angle) * 110;
  });
  free.forEach((node, index) => {
    const angle = (index / Math.max(1, free.length)) * Math.PI * 2 + (index % 4) * 0.35;
    const radius = 210 + (index % 6) * 28;
    node.x = Math.cos(angle) * radius;
    node.y = Math.sin(angle) * radius * 0.72;
  });
  const self = byId.get(marketSelfId());
  if (self) { self.x = 0; self.y = 0; }
  let focus = null;
  let cited = new Set();
  let hover = null;
  let frame = 0;
  let running = true;
  const view = {x: 0, y: 0, k: 1};
  let drag = null;

  function step() {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        let dx = nodes[j].x - nodes[i].x;
        let dy = nodes[j].y - nodes[i].y;
        const dist = Math.hypot(dx, dy) || 0.01;
        const force = 420 / (dist * dist);
        dx /= dist; dy /= dist;
        nodes[i].vx -= dx * force; nodes[i].vy -= dy * force;
        nodes[j].vx += dx * force; nodes[j].vy += dy * force;
      }
    }
    for (const link of links) {
      let dx = link.b.x - link.a.x;
      let dy = link.b.y - link.a.y;
      const dist = Math.hypot(dx, dy) || 0.01;
      const force = (dist - 96) * 0.012;
      dx /= dist; dy /= dist;
      link.a.vx += dx * force; link.a.vy += dy * force;
      link.b.vx -= dx * force; link.b.vy -= dy * force;
    }
    for (const node of nodes) {
      if (node.id === marketSelfId()) { node.x = 0; node.y = 0; node.vx = 0; node.vy = 0; continue; }
      node.vx -= node.x * 0.008;
      node.vy -= node.y * 0.008;
      node.vx *= 0.72; node.vy *= 0.72;
      node.x += Math.max(-12, Math.min(12, node.vx));
      node.y += Math.max(-12, Math.min(12, node.vy));
    }
  }
  for (let n = 0; n < 160; n++) step();

  function neighbors() {
    const near = new Set();
    if (!focus) return near;
    near.add(focus);
    for (const link of links) {
      if (link.a.id === focus) near.add(link.b.id);
      if (link.b.id === focus) near.add(link.a.id);
    }
    return near;
  }

  function color(node, near) {
    if (cited.has(node.id)) return '#8fd18c';
    if (node.id === focus) return '#ffffff';
    if (near.has(node.id)) return '#f2f2f2';
    if (node.type === 'segment') return '#7dce7a';
    if (node.tier === 'core') return '#e8e8e8';
    if (node.type === 'channel') return '#8d8d8d';
    return '#bdbdbd';
  }

  function draw() {
    if (!running) return;
    const rect = canvas.getBoundingClientRect();
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width * ratio));
    const height = Math.max(1, Math.floor(rect.height * ratio));
    if (canvas.width !== width || canvas.height !== height) {
      canvas.width = width; canvas.height = height;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, rect.width, rect.height);
    ctx.fillStyle = '#191919';
    ctx.fillRect(0, 0, rect.width, rect.height);
    if (frame < 40) step();
    frame += 1;
    const near = neighbors();
    ctx.save();
    ctx.translate(rect.width / 2 + view.x, rect.height / 2 + view.y);
    ctx.scale(view.k, view.k);
    for (const link of links) {
      const hot = focus && (link.a.id === focus || link.b.id === focus);
      ctx.beginPath();
      ctx.moveTo(link.a.x, link.a.y);
      ctx.lineTo(link.b.x, link.b.y);
      ctx.strokeStyle = hot ? 'rgba(230,230,230,0.55)' : 'rgba(180,180,180,0.18)';
      ctx.lineWidth = hot ? 1.15 : 0.8;
      ctx.stroke();
    }
    for (const node of nodes) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.id === focus ? node.r + 1.6 : node.r, 0, Math.PI * 2);
      ctx.fillStyle = color(node, near);
      ctx.fill();
    }
    ctx.font = '12px system-ui, sans-serif';
    ctx.textBaseline = 'middle';
    for (const node of nodes) {
      const show = node.id === focus || node.id === hover || near.has(node.id) || node.tier === 'core' || node.id === marketSelfId();
      if (!show) continue;
      ctx.fillStyle = node.id === focus || node.id === hover ? '#f7f7f7' : 'rgba(220,220,220,0.78)';
      ctx.fillText(node.name, node.x + node.r + 4, node.y);
    }
    ctx.restore();
    if (running) requestAnimationFrame(draw);
  }
  requestAnimationFrame(draw);

  function world(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left - rect.width / 2 - view.x) / view.k,
      y: (event.clientY - rect.top - rect.height / 2 - view.y) / view.k,
    };
  }
  function hit(point) {
    let found = null;
    let best = 14 / view.k;
    for (const node of nodes) {
      const dist = Math.hypot(node.x - point.x, node.y - point.y);
      if (dist < best) { best = dist; found = node; }
    }
    return found;
  }
  canvas.onmousemove = event => {
    if (drag && drag.moved) {
      view.x = drag.vx + (event.clientX - drag.x);
      view.y = drag.vy + (event.clientY - drag.y);
      return;
    }
    if (drag) drag.moved = Math.hypot(event.clientX - drag.x, event.clientY - drag.y) > 3;
    const node = hit(world(event));
    hover = node ? node.id : null;
    canvas.style.cursor = node ? 'pointer' : 'grab';
  };
  canvas.onmousedown = event => {
    drag = {x: event.clientX, y: event.clientY, vx: view.x, vy: view.y, moved: false, node: hit(world(event))};
  };
  const release = () => {
    if (!drag) return;
    const picked = drag.node;
    const moved = drag.moved;
    drag = null;
    if (!moved && picked) location.hash = marketHref(picked.id);
  };
  window.addEventListener('mouseup', release);
  canvas.onwheel = event => {
    event.preventDefault();
    const next = Math.min(2.4, Math.max(0.45, view.k * (event.deltaY < 0 ? 1.08 : 0.92)));
    view.k = next;
  };
  canvas.addEventListener('wheel', canvas.onwheel, {passive: false});

  return {
    focus(id) { focus = byId.has(id) ? id : null; cited = new Set(); },
    cite(ids) { cited = new Set(ids); if (ids[0] && byId.has(ids[0])) focus = ids[0]; },
    stop() { running = false; window.removeEventListener('mouseup', release); },
  };
}
