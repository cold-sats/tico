// The hub's service worker exists so Chrome and Edge offer "Install app". It caches nothing:
// every request goes to the network with cache: 'no-store'. The API in particular must never
// be served from a cache — the hub is a live view of what the bots are doing.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (url.pathname.startsWith('/api/')) return;     // untouched: no interception, no cache
  event.respondWith(fetch(event.request, {cache: 'no-store'}));
});
