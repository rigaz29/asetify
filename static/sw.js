/* Asetify Service Worker — offline app shell */
const CACHE = 'asetify-shell-v1';

// Aset same-origin (app shell) — di-cache saat install.
const LOCAL_SHELL = [
  '/',
  '/manifest.webmanifest',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/icon-maskable-512.png',
];
// Aset cross-origin (CDN) — di-cache no-cors (opaque).
const CDN = [
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/@phosphor-icons/web',
];

self.addEventListener('install', (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CACHE);
    await c.addAll(LOCAL_SHELL);
    await Promise.all(CDN.map(async (u) => {
      try { await c.put(u, await fetch(u, { mode: 'no-cors' })); } catch (_) {}
    }));
    self.skipWaiting();
  })());
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Konten dinamis / besar / kedaluwarsa -> JANGAN cache: audio, API, stream YouTube.
  if (url.pathname.startsWith('/api/') ||
      url.pathname.startsWith('/audio/') ||
      /googlevideo\.com|scdn\.co/.test(url.hostname)) {
    return; // biarkan network default
  }

  // Navigasi (buka app): coba jaringan, fallback ke shell '/' saat offline.
  if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(() => caches.match('/')));
    return;
  }

  // Aset shell/statik: cache-first, lalu network (dan simpan salinannya).
  e.respondWith(
    caches.match(req).then((cached) => cached || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
      return res;
    }).catch(() => cached))
  );
});
