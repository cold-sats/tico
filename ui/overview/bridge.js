const $ = selector => document.querySelector(selector);
const origin = location.origin;
let model = null, scene = null, topology = '', revision = 0, disposed = false, failed = false;
// The renderer starts downloading before the team arrives; the page preloads it too.
const renderer = import('./building.js'); renderer.catch(() => {});
const preferences = {layout: 'campus'};
try { if (localStorage.getItem('tico-overview-layout') === 'tower') preferences.layout = 'tower'; } catch {}
const send = data => parent.postMessage(data, origin);
function openMember(id) {
  if (model.groups.some(g => g.members.some(m => m.id === id && m.href))) send({type: 'tico-overview-open', id});
}
function fallback(message) {
  $('#loading').hidden = true; $('#fallback').hidden = false;
  $('#fallback h1').textContent = model?.company || 'Overview';
  $('#fallback p').textContent = message;
  const list = $('#fallback-team'); list.replaceChildren();
  for (const group of model?.groups || []) {
    const section = document.createElement('section'), heading = document.createElement('h2');
    heading.textContent = group.name; section.append(heading);
    for (const member of group.members) {
      const button = document.createElement('button');
      button.textContent = member.name + ' · ' + member.detail;
      button.disabled = !member.href; button.onclick = () => openMember(member.id); section.append(button);
    }
    if (!group.members.length) { const p = document.createElement('p'); p.textContent = 'No teammates assigned yet.'; section.append(p); }
    list.append(section);
  }
}
function currentData() {
  return {...model, offset: 0, groups: model.groups.map(g => ({...g, key: g.id}))};
}
function controls() {
  $('#connection-status').hidden = model.fresh;
  $('#campus-company').textContent = model.company;
  const count = model.groups.filter(g => g.kind === 'computer').length;
  $('#campus-summary').textContent = count + (count === 1 ? ' computer' : ' computers') + (preferences.layout === 'tower' ? ' · One tower' : ' · One connected campus');
  document.querySelectorAll('[data-layout]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.layout === preferences.layout)));
}
async function mount(quiet = false) {
  const seq = ++revision; scene?.dispose(); scene = null; failed = false; $('#world').replaceChildren();
  controls(); $('#fallback').hidden = true;
  if (!quiet) { $('#loading').hidden = false; $('#loading').classList.remove('gone'); }
  delete document.body.dataset.sceneReady;
  if (!model.groups.length) { fallback('Your campus will come to life when you add computers and teammates.'); return; }
  try {
    const {createBuilding} = await renderer;
    if (disposed || seq !== revision) return;
    scene = createBuilding(currentData(), preferences, openMember);
  } catch (error) {
    if (disposed || seq !== revision) return;
    failed = true; fallback('The 3D view is unavailable. Explore your team below.');
    console.warn('Overview renderer unavailable', error);
  }
}
function update(next) {
  if (!Array.isArray(next?.groups)) return;
  const shape = JSON.stringify([next.company, next.groups.map(g => [g.id, g.name, g.kind, g.members.map(m => [m.id, m.name, m.type])])]);
  model = next;
  if (shape !== topology) { topology = shape; mount(); }
  else { controls(); scene?.update(currentData()); if (failed) fallback('The 3D view is unavailable. Explore your team below.'); }
}
for (const button of document.querySelectorAll('[data-layout]')) button.onclick = () => {
  if (!model || preferences.layout === button.dataset.layout) return;
  preferences.layout = button.dataset.layout; preferences.floorId = null;
  try { localStorage.setItem('tico-overview-layout', preferences.layout); } catch {}
  mount(true);
};
function dispose() { disposed = true; revision++; scene?.dispose(); scene = null; }
window.addEventListener('message', event => {
  if (event.source !== parent || event.origin !== origin || disposed) return;
  if (event.data?.type === 'tico-overview-data') update(event.data.model);
  if (event.data?.type === 'tico-overview-dispose') dispose();
});
window.addEventListener('pagehide', dispose);
window.addEventListener('overview-context-lost', () => { failed = true; fallback('The 3D view was interrupted. Your team is still accessible below.'); });
send({type: 'tico-overview-ready'});
