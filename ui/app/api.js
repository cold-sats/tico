/* ui/app/api.js — get/post/put/form requests, API errors, sign-in redirect, toast
   Classic script: its globals are shared with the other files under ui/app/, loaded in the order index.html lists them. */
'use strict';

const bytes = n => n < 1024 ? `${n} B` : n < 1048576 ? `${(n/1024).toFixed(0)} KB` : `${(n/1048576).toFixed(1)} MB`;
const apiError = (j, r) => j.error?.detail || (typeof j.error === 'string' ? j.error : '') || (Array.isArray(j.detail) ? j.detail.map(e => `${e.loc?.slice(1).join('.') || 'Request'}: ${e.msg}`).join('; ') : '') || r.statusText;
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
const get = async p => { const r = await fetch(API + p, {cache:'no-store'}); window.TicoObservability?.response(r.status); const j = await r.json().catch(()=>({})); if (!r.ok) { signInRedirect(r, j); throw apiFailure(j, r); } return j; };
const pendingWrites = new Map();
const newRequestId = () => globalThis.crypto?.randomUUID?.() || 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
  const n = globalThis.crypto?.getRandomValues?.(new Uint8Array(1))[0] ?? Math.floor(Math.random() * 256);
  return ((c === 'x' ? n : (n & 3) | 8) & 15).toString(16);
});
// Every JSON write goes through one path so a PUT carries the same Idempotency-Key and the same
// retry rules as a POST; the method is part of the signature so the two never share a request id.
const writeRequest = async (method, p, body={}, operationId) => {
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
const postRequest = (p, body={}, operationId) => writeRequest('POST', p, body, operationId);
const patchRequest = (p, body={}, operationId) => writeRequest('PATCH', p, body, operationId);
const putRequest = (p, body={}, operationId) => writeRequest('PUT', p, body, operationId);
const post = (p, body={}, operationId) => window.TicoObservability
  ? window.TicoObservability.run(p, () => postRequest(p, body, operationId)) : postRequest(p, body, operationId);
const patch = (p, body={}, operationId) => window.TicoObservability
  ? window.TicoObservability.run(p, () => patchRequest(p, body, operationId)) : patchRequest(p, body, operationId);
const put = (p, body={}, operationId) => window.TicoObservability
  ? window.TicoObservability.run(p, () => putRequest(p, body, operationId)) : putRequest(p, body, operationId);
// Keep multipart retries stable across newly constructed FormData boundaries.
const formRequest = async (url, body) => {
  if (!S.me?.cloud) return fetch(url, {method:'POST', body});
  const fields = [];
  for (const [name, value] of body.entries()) {
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
const formFetch = (url, body) => window.TicoObservability
  ? window.TicoObservability.run(url.startsWith(API) ? url.slice(API.length) : '', () => formRequest(url, body)) : formRequest(url, body);
async function cloudCompose(path, body, files = []) {
  if (!files.length) return post(path, body);
  if (!S.me?.cloud) throw new Error('This composer cannot send files on the local backend. Keep the files and use Meetings to send them.');
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
