// Video and audio cards in chat and task conversations (Visual replies 3/4). The bodies are the task-files players
// (controls, playsinline, preload="metadata", the poster) inside the shared card frame (visual-cards.js); this file
// adds the video and audio bodies, one clip at a time, and a player that recovers from an expired address.
// Media loads only from the attachment's isolated `src` (no app sign-in, range requests), never through a blob URL,
// so seeking a large file asks for that part only. Nothing here ever calls play(): a clip starts when a person
// presses play. Classic script, loaded after visual-cards.js.
'use strict';
const VM_TYPE = {'video/mp4': 'MP4', 'video/webm': 'WebM', 'video/quicktime': 'MOV', 'video/x-m4v': 'M4V',
  'audio/mpeg': 'MP3', 'audio/mp4': 'M4A', 'audio/x-m4a': 'M4A', 'audio/wav': 'WAV', 'audio/x-wav': 'WAV',
  'audio/wave': 'WAV', 'audio/ogg': 'OGG', 'audio/aac': 'AAC'};
const vmWord = kind => kind === 'video' ? 'video' : 'audio';
// Whether this device says it can't play the type at all ('' from canPlayType); 'maybe' and 'probably' get a try.
function vmUnplayable(kind, type) {
  if (!type) return false;
  return document.createElement(kind === 'video' ? 'video' : 'audio').canPlayType(type) === '';
}
// The card body when the device can't play the clip: the reason and the signed-in download (a click, like a chip).
const vmDownload = f => f.url || `${API}/v2/files/${encodeURIComponent(f.file_id || f.id)}${f.version ? `?v=${Number(f.version)}` : ''}`;
const vmCantPlayHTML = (href, name, reason) =>
  `<div class="vm-cant"><p class="vm-reason">${esc(reason)}</p><a class="pill" href="${esc(href)}" download="${esc(name || '')}">Download</a></div>`;
function vmReason(kind, type, code) {
  const word = VM_TYPE[type] || '';
  if (code === 2) return `Couldn't load this ${vmWord(kind)}. Check the connection, or download it.`;
  return `This device can't play ${word ? word + ' ' : 'this '}${vmWord(kind)}.`;
}
function vmBodyHTML(f) {
  const kind = f.kind === 'audio' ? 'audio' : 'video';
  const src = visualSrc(f);
  if (vmUnplayable(kind, f.content_type)) return vmCantPlayHTML(vmDownload(f), f.name, vmReason(kind, f.content_type, 4));
  const at = ` data-vm-src="${esc(src)}" data-vm-type="${esc(f.content_type || '')}" data-vm-dl="${esc(vmDownload(f))}" data-vm-name="${esc(f.name || '')}"`;
  if (kind === 'audio') return `<div class="tf-media audio media-skel vm"><audio src="${esc(src)}"${at} controls preload="metadata"></audio></div>`;
  const ratio = f.width && f.height ? ` style="aspect-ratio:${Number(f.width)}/${Number(f.height)}"` : '';
  const poster = f.poster_url ? ` poster="${esc(f.poster_url)}"` : '';
  return `<div class="tf-media video media-skel vm${f.poster_url ? ' ready' : ''}"${ratio}><video src="${esc(src)}"${at}${poster} controls playsinline preload="metadata"></video></div>`;
}
// After the card is in the page: ready on metadata; on an error, first try the newest address the thread handed
// the card (visualKeep keeps a playing card and writes the new tree's src to data-fresh-src) at the same position
// and play state; only then show the reason and Download.
function vmWire(card) {
  const m = card.querySelector('video[data-vm-src], audio[data-vm-src]');
  if (!m || m.dataset.vmWired) return;
  m.dataset.vmWired = '1';
  const wrap = m.closest('.tf-media');
  m.addEventListener('loadedmetadata', () => wrap.classList.add('ready'));
  // Whether the person has it playing. A failed load pauses the element just before its error event, so a pause
  // only counts once the turn has passed without an error.
  m.addEventListener('play', () => { m.dataset.vmPlaying = '1'; });
  m.addEventListener('pause', () => setTimeout(() => { if (!m.error) delete m.dataset.vmPlaying; }));
  m.addEventListener('error', () => {
    if (vmRecover(m, card)) return;
    const kind = m.tagName === 'AUDIO' ? 'audio' : 'video', d = m.dataset;
    wrap.outerHTML = vmCantPlayHTML(d.vmDl, d.vmName, vmReason(kind, d.vmType, m.error && m.error.code));
  });
}
function vmRecover(m, card) {
  const fresh = card.dataset.freshSrc;
  if (!fresh || fresh === m.dataset.vmSrc || m.dataset.vmTried === fresh) return false;
  const at = m.currentTime, playing = !m.ended && (!m.paused || m.dataset.vmPlaying === '1');
  m.dataset.vmTried = fresh;
  m.dataset.vmSrc = fresh;
  m.addEventListener('loadedmetadata', () => {
    if (at) m.currentTime = at;
    if (playing) m.play().catch(() => {});                // it was playing when the address ran out: keep playing
  }, {once: true});
  m.src = fresh;
  return true;
}
// One clip at a time: starting any video or audio on the page pauses the one already playing.
document.addEventListener('play', e => {
  for (const m of document.querySelectorAll('video, audio')) if (m !== e.target && !m.paused) m.pause();
}, true);
if (typeof VISUAL_BODY === 'object') VISUAL_BODY.video = VISUAL_BODY.audio = vmBodyHTML;
if (typeof VISUAL_WIRE === 'object') VISUAL_WIRE.video = VISUAL_WIRE.audio = vmWire;
