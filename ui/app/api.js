/* ui/app/api.js — get/post/put/form requests, API errors, sign-in redirect, toast
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

const bytes = n => n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(0)} KB` : n < 1073741824 ? `${(n/1048576).toFixed(1)} MB` : `${(n/1073741824).toFixed(1)} GB`;
const apiErrorRaw = (j, r) => j.error?.detail || (typeof j.error === 'string' ? j.error : '') || (Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.slice(1).join('.') || 'Request'}: ${e.msg}`).join('; ') : '') || r.statusText;
const apiError = (j, r) => {
  const raw = apiErrorRaw(j, r);
  return String(raw).replace(/\. Rewrite the title\/body to fix these writing errors and retry\. Do not ask the human to waive formatting rules\./g, '. Please edit the title or details and try again.')
    .replace(/start the title with a verb \(it starts "([^"]+)"\)/g, 'Start the title with an action, such as “Email” or “Review”');
};
// The message is what a person reads; `body` is the one extra fact a refusal carries, such as the
// task a duplicate feature request already has (`backend/store.py`, Problem.extra).
const apiFailure = (j, r) => Object.assign(new Error(apiError(j, r)), {body: j, status: r.status});
// With built-in sign-in a 401 names the login page; go there and come back to this place.
const signInRedirect = (r, j) => {
  const to = r.status === 401 && j?.error?.sign_in;
  if (typeof to !== 'string' || !to.startsWith('/auth/')) return false;
  location.assign(to + '?next=' + encodeURIComponent(location.pathname + location.search + location.hash));
  return true;
};
// A list the server tags (tasks, labels, routines) is asked for again with its tag: unchanged, the answer is a 304
// with no body and the copy kept here is read again, so the server neither loads nor sends it. A few dozen at most.
const GET_TAGGED = new Map();
// Two readers of the same path at the same moment (the bot page asks for its goals twice, a poll lands while a page
// loads) share one request; each parses its own copy. A write forgets them all, so a read that follows a write never
// gets an answer from before it.
const GET_INFLIGHT = new Map();
// What startup asks for ahead of the page that will need it (getPrefetch): read once, within a few seconds.
const GET_PREFETCHED = new Map();
const getForget = () => { GET_INFLIGHT.clear(); GET_PREFETCHED.clear(); };
const getRaw = p => {
  const kept = GET_TAGGED.get(p);
  return fetch(API + p, {cache:'no-store', headers: kept ? {'If-None-Match': kept.tag} : {}}).then(async r => {
    window.TicoObservability?.response(r.status);
    const text = r.status === 304 ? '' : await r.text().catch(() => '');
    if (r.ok) {
      const tag = r.headers.get('ETag');
      if (r.status !== 304) GET_TAGGED.delete(p);
      if (tag && r.status !== 304) { GET_TAGGED.set(p, {tag, text}); if (GET_TAGGED.size > 40) GET_TAGGED.delete(GET_TAGGED.keys().next().value); }
    }
    return {r, text, kept};
  });
};
const getPrefetch = p => { if (!GET_PREFETCHED.has(p)) GET_PREFETCHED.set(p, {at: Date.now(), raw: getRaw(p).catch(() => null)}); };
const get = async p => {
  let res = null;
  const pre = GET_PREFETCHED.get(p);
  if (pre) { GET_PREFETCHED.delete(p); if (Date.now() - pre.at < 5000) res = await pre.raw; }
  if (!res) {
    let raw = GET_INFLIGHT.get(p);
    if (!raw) {
      raw = getRaw(p);
      GET_INFLIGHT.set(p, raw);
      const done = () => { if (GET_INFLIGHT.get(p) === raw) GET_INFLIGHT.delete(p); };
      raw.then(done, done);
    }
    res = await raw;
  }
  const {r, text, kept} = res;
  if (r.status === 304 && kept) return JSON.parse(kept.text);
  let j; try { j = JSON.parse(text); } catch { j = {}; }
  if (!r.ok) { signInRedirect(r, j); throw apiFailure(j, r); }
  return j;
};
const pendingWrites = new Map();
const newRequestId = () => globalThis.crypto?.randomUUID?.() || 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
  const n = globalThis.crypto?.getRandomValues?.(new Uint8Array(1))[0] ?? Math.floor(Math.random() * 256);
  return ((c === 'x' ? n : (n & 3) | 8) & 15).toString(16);
});
// Every JSON write goes through one path so a PUT carries the same Idempotency-Key and the same
// retry rules as a POST; the method is part of the signature so the two never share a request id.
const writeRequestOnce = async (method, p, body={}, operationId) => {
  getForget();
  const payload = JSON.stringify(body), signature = method + ' ' + p + '\n' + payload;
  const key = operationId || pendingWrites.get(signature) || newRequestId();
  pendingWrites.set(signature, key);
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const r = await fetch(API + p, {method, headers:{'Content-Type':'application/json', 'Idempotency-Key':key}, body:payload});
      window.TicoObservability?.response(r.status);
      const j = await r.json().catch(()=>({}));
      if ([429,502,503,504].includes(r.status)) throw new TypeError(apiError(j, r));
      pendingWrites.delete(signature);
      if (!r.ok) { signInRedirect(r, j); throw apiFailure(j, r); }
      return j;
    } catch (error) {
      if (!(error instanceof TypeError)) throw error;
      if (attempt === 2) throw Object.assign(new Error('Could not confirm whether this saved. Retry the same submission in this tab; it will use the same request ID.'), {unconfirmed: true});
      await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
    }
  }
};
// The button just pressed shows the write is under way until it settles (styles/skeleton.css), so a slow server
// never looks like an ignored click. Only a press in the last moment counts; a later background save marks nothing.
let LAST_PRESS = null;
document.addEventListener('click', e => {
  const el = e.target.closest?.('button, [role="button"], input[type="submit"]');
  LAST_PRESS = el ? {el, at: performance.now()} : null;
}, true);
document.addEventListener('submit', e => { if (e.submitter) LAST_PRESS = {el: e.submitter, at: performance.now()}; }, true);
const pressPending = () => {
  const press = LAST_PRESS;
  if (!press || performance.now() - press.at > 400 || !press.el.isConnected || press.el.classList.contains('is-pending')) return () => {};
  const el = press.el;
  el.classList.add('is-pending'); el.setAttribute('aria-busy', 'true');
  return () => { el.classList.remove('is-pending'); el.removeAttribute('aria-busy'); };
};
const writeRequest = async (...args) => { const done = pressPending(); try { return await writeRequestOnce(...args); } finally { done(); } };
const postRequest = (p, body={}, operationId) => writeRequest('POST', p, body, operationId);
const patchRequest = (p, body={}, operationId) => writeRequest('PATCH', p, body, operationId);
const putRequest = (p, body={}, operationId) => writeRequest('PUT', p, body, operationId);
const post = (p, body={}, operationId) => window.TicoObservability
  ? window.TicoObservability.run(p, () => postRequest(p, body, operationId)) : postRequest(p, body, operationId);
const patch = (p, body={}, operationId) => window.TicoObservability
  ? window.TicoObservability.run(p, () => patchRequest(p, body, operationId)) : patchRequest(p, body, operationId);
const put = (p, body={}, operationId) => window.TicoObservability
  ? window.TicoObservability.run(p, () => putRequest(p, body, operationId)) : putRequest(p, body, operationId);
// Keep multipart and binary retries stable across newly constructed bodies.
const formRequestOnce = async (url, body) => {
  getForget();
  if (!S.me?.cloud) return fetch(url, {method:'POST', body});
  const fields = [];
  for (const [name, value] of body instanceof Blob ? [['file', body]] : body.entries()) {
    if (value instanceof Blob) {
      const digest = await crypto.subtle.digest('SHA-256', await value.arrayBuffer());
      fields.push([name, value.name || '', value.type, value.size,
        Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('')]);
    } else fields.push([name, value]);
  }
  const signature = url + '\n' + JSON.stringify(fields), key = pendingWrites.get(signature) || newRequestId();
  pendingWrites.set(signature, key);
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const response = await fetch(url, {method:'POST', body, redirect:'error', headers:{'Idempotency-Key':key}});
      window.TicoObservability?.response(response.status);
      if ([429,502,503,504].includes(response.status)) throw new TypeError('Upload temporarily unavailable');
      if (response.ok) {
        const confirmation = await response.clone().json().catch(() => null);
        if (!confirmation || typeof confirmation !== 'object') throw new TypeError('Upload confirmation was not valid JSON');
      }
      pendingWrites.delete(signature);
      return response;
    } catch (error) {
      if (!(error instanceof TypeError)) throw error;
      if (attempt === 2) throw Object.assign(new Error('Could not confirm whether this upload saved. Keep the files and retry the same submission in this tab.'), {unconfirmed: true});
      await new Promise(resolve => setTimeout(resolve, 500 * (attempt + 1)));
    }
  }
};
const formRequest = async (...args) => { const done = pressPending(); try { return await formRequestOnce(...args); } finally { done(); } };
const formFetch = (url, body) => window.TicoObservability
  ? window.TicoObservability.run(url.startsWith(API) ? url.slice(API.length) : '', () => formRequest(url, body)) : formRequest(url, body);
async function cloudCompose(path, body, files = []) {
  if (!files.length) return post(path, body);
  const fd = new FormData();
  for (const [key, value] of Object.entries(body)) fd.append(key, typeof value === 'object' ? JSON.stringify(value) : value);
  files.forEach(file => fd.append('files', file, file.name));
  const response = await formFetch(API + path.replace('/v2/', '/v2/uploads/'), fd);
  const result = await response.json().catch(() => ({}));
  if (!response.ok || !result.task && !result.message) throw new Error(apiError(result, response) || 'The server did not confirm this upload.');
  return result;
}
const toast = (msg, isErr, action) => {
  const t = document.createElement('div'); t.className = 'toast' + (isErr ? ' err' : ''); t.textContent = msg;
  if (action) {
    const button = document.createElement('button'); button.className = 'linkish'; button.textContent = action.label;
    button.onclick = async () => { button.disabled = true; try { await action.run(); t.remove(); } catch (e) { toast(e.message, true); button.disabled = false; } };
    t.append(' ', button);
  }
  document.body.appendChild(t); setTimeout(() => t.remove(), action ? 8000 : isErr ? 8000 : 3500);
};
