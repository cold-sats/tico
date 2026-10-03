const $ = selector => document.querySelector(selector);
const origin = location.origin;
let model = null, scene = null, page = 0, topology = '', revision = 0, disposed = false, failed = false;
const preferences = {};
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
  return {...model, offset: page * 5, groups: model.groups.slice(page * 5, page * 5 + 5).map(g => ({...g, key: g.id}))};
}
function controls() {
  $('#connection-status').hidden = model.fresh;
  $('#scene-about').hidden = !model.demo;
  const picker = $('#department-picker'); picker.replaceChildren(new Option('All floors', ''));
  for (const g of model.groups) picker.add(new Option(g.name, g.id));
  picker.value = preferences.floorId || '';
  $('#building-pages').hidden = model.groups.length <= 5;
  $('#building-range').textContent = `Floors ${page * 5 + 1}–${Math.min(model.groups.length, page * 5 + 5)} of ${model.groups.length}`;
  $('#building-prev').disabled = page === 0;
  $('#building-next').disabled = (page + 1) * 5 >= model.groups.length;
}
async function mount() {
  const seq = ++revision; scene?.dispose(); scene = null; failed = false; $('#world').replaceChildren();
  controls(); $('#fallback').hidden = true; $('#loading').hidden = false; $('#loading').classList.remove('gone');
  delete document.body.dataset.sceneReady;
  if (!model.groups.length) { fallback('Your building will come to life when you add groups and teammates.'); return; }
  try {
    const {createBuilding} = await import('./building.js');
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
  const shape = JSON.stringify([next.company, next.groups.map(g => [g.id, g.name, g.parent, g.members.map(m => [m.id, m.name, m.type])])]);
  model = next;
  if (preferences.night === undefined) preferences.night = false;
  page = Math.min(page, Math.max(0, Math.ceil(model.groups.length / 5) - 1));
  if (shape !== topology) { topology = shape; mount(); }
  else { controls(); scene?.update(currentData()); if (failed) fallback('The 3D view is unavailable. Explore your team below.'); }
}
$('#department-picker').onchange = event => {
  const key = event.target.value; preferences.floorId = key || null;
  if (!key) { scene?.select(null); return; }
  const index = model.groups.findIndex(g => g.id === key), nextPage = Math.floor(index / 5);
  if (nextPage !== page) { page = nextPage; mount(); } else scene?.select(key);
};
for (const [id, delta] of [['building-prev', -1], ['building-next', 1]]) $( '#' + id).onclick = () => {
  page = Math.max(0, Math.min(Math.ceil(model.groups.length / 5) - 1, page + delta)); preferences.floorId = null; mount();
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
