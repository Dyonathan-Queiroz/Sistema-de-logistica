var CACHE = 'gaviao-v1';
var ASSETS = [
  '/static/manifest.json',
  '/static/icons/icon.svg',
  'https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800;900&family=Barlow:wght@400;500;600;700&display=swap',
  'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css'
];

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(c) { return c.addAll(ASSETS); })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(keys.filter(function(k) { return k !== CACHE; }).map(function(k) { return caches.delete(k); }));
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  var url = new URL(e.request.url);

  // Sempre busca do servidor para rotas da app (dados dinâmicos)
  if (url.pathname.startsWith('/entregador') || url.pathname.startsWith('/gestor') || url.pathname === '/login') {
    e.respondWith(
      fetch(e.request).catch(function() {
        return caches.match('/offline.html') || new Response(
          '<html><body style="background:#070A10;color:#f1f5f9;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;">' +
          '<div><div style="font-size:48px;margin-bottom:16px;">📡</div>' +
          '<h2>Sem conexão</h2><p style="color:#64748b">Verifique sua internet e tente novamente.</p>' +
          '<button onclick="location.reload()" style="margin-top:16px;padding:12px 24px;background:#f59e0b;color:#000;border:none;border-radius:10px;font-weight:700;font-size:15px;cursor:pointer;">Tentar Novamente</button>' +
          '</div></body></html>',
          { headers: { 'Content-Type': 'text/html' } }
        );
      })
    );
    return;
  }

  // Assets estáticos: cache first
  e.respondWith(
    caches.match(e.request).then(function(cached) {
      return cached || fetch(e.request).then(function(res) {
        if (res.ok) {
          var clone = res.clone();
          caches.open(CACHE).then(function(c) { c.put(e.request, clone); });
        }
        return res;
      });
    })
  );
});
