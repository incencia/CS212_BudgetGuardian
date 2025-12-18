/* Minimal service worker for PWA installability.
   NOTE: This is intentionally conservative (network-first for HTML).
*/

const CACHE_NAME = 'budget-guardian-v1';
const ASSETS = [
  '/',
  '/how-it-works',
  '/login',
  '/register',
  '/static/style.css?v=3',
  '/manifest.webmanifest',
  '/sw.js',
  '/static/icons/apple-touch-icon.png',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/pet_images/neutral-car.gif',
  '/static/pet_images/slight_overspend.gif',
  '/static/pet_images/major_overspend.gif',
  '/static/pet_images/happy-happy-happy-cat.gif',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    Promise.all([
      self.clients.claim(),
      caches.keys().then((keys) =>
        Promise.all(keys.map((k) => (k === CACHE_NAME ? null : caches.delete(k))))
      ),
    ])
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle same-origin
  if (url.origin !== self.location.origin) return;

  // Network-first for navigations (HTML)
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy));
          return res;
        })
        .catch(() => caches.match(req).then((r) => r || caches.match('/')))
    );
    return;
  }

  // Cache-first for static
  event.respondWith(
    caches.match(req).then((cached) =>
      cached ||
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((c) => c.put(req, copy));
        return res;
      })
    )
  );
});
