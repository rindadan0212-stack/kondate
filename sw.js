// 献立 オフラインキャッシュ（初回ロード後はネット無しでも動く）
const CACHE = 'kondate-v9';
const CORE = ['./', 'index.html', 'app.js', 'style.css', 'kondate_bundle.py',
  'recipes.json', 'profile.json', 'week.json', 'manifest.json', 'icon-192.png', 'icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(CORE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// stale-while-revalidate: キャッシュを即返しつつ裏で更新（次回アクセスで最新に）
self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  e.respondWith(caches.open(CACHE).then((cache) =>
    cache.match(req).then((cached) => {
      const fetched = fetch(req).then((resp) => {
        if (resp && (resp.ok || resp.type === 'opaque') &&
          (req.url.startsWith(self.location.origin) || req.url.includes('jsdelivr.net') || req.url.includes('fonts.g'))) {
          cache.put(req, resp.clone());
        }
        return resp;
      }).catch(() => cached || caches.match('index.html'));
      return cached || fetched;
    })
  ));
});
