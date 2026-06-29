// 献立 オフラインキャッシュ（初回ロード後はネット無しでも動く）
const CACHE = 'kondate-v3';
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

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  e.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((resp) => {
      // Pyodide(CDN)・フォントも初回取得時にキャッシュ → 次回オフライン可
      if (resp && (resp.ok || resp.type === 'opaque') &&
        (req.url.startsWith(self.location.origin) || req.url.includes('jsdelivr.net') || req.url.includes('fonts.g'))) {
        const copy = resp.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return resp;
    }).catch(() => caches.match('index.html')))
  );
});
