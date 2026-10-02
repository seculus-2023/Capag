{% load static %}// Service worker do Sistema CAPAG.
// As telas têm dados sigilosos e exigem login, então NÃO ficam em cache: só os arquivos
// estáticos (CSS, JS, ícones) e a página "sem conexão".
const CACHE = 'capag-v1';
const OFFLINE = '{% url "pwa_offline" %}';
const ESTATICOS = [
  OFFLINE,
  '{% static "vendor/bootstrap/bootstrap.min.css" %}',
  '{% static "vendor/bootstrap/bootstrap.bundle.min.js" %}',
  '{% static "vendor/bootstrap-icons/bootstrap-icons.min.css" %}',
  '{% static "pwa/icon-192.png" %}',
];

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(ESTATICOS); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (nomes) {
    return Promise.all(nomes.filter(function (n) { return n !== CACHE; }).map(function (n) { return caches.delete(n); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (req.mode === 'navigate') {  // telas: sempre da rede; sem conexão, mostra o aviso
    e.respondWith(fetch(req).catch(function () { return caches.match(OFFLINE); }));
    return;
  }
  if (url.pathname.startsWith('/{{ static_prefix }}')) {  // estáticos: cache primeiro
    e.respondWith(caches.match(req).then(function (r) {
      return r || fetch(req).then(function (resp) {
        if (resp.ok) { const copia = resp.clone(); caches.open(CACHE).then(function (c) { c.put(req, copia); }); }
        return resp;
      });
    }));
  }
});
