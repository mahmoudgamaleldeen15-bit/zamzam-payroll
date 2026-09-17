// ===== زمزم Payroll — Service Worker =====
// v3: الشبكة أولاً للصفحة الرئيسية دايمًا — يمنع تجميد النسخة القديمة
//     على الموبايل عند كل تحديث للبرنامج
const CACHE_NAME = 'zamzam-payroll-v3';
const STATIC_ASSETS = ['./manifest.json', './icon-192.png', './icon-512.png'];

// تثبيت: تخزين الملفات الثابتة بس (مش index.html)
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

// تفعيل: حذف أي نسخة كاش قديمة فورًا
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const req = event.request;

  // صفحة البرنامج نفسها (index.html) — الشبكة أولاً دايمًا
  // عشان أي تحديث نرفعه يوصل فورًا بدل ما يفضل محبوس في الكاش
  if(req.mode === 'navigate' || req.destination === 'document'){
    event.respondWith(
      fetch(req)
        .then(res => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(req, clone));
          return res;
        })
        .catch(() => caches.match(req).then(c => c || caches.match('./index.html')))
    );
    return;
  }

  // باقي الملفات (أيقونات/مانيفست) — كاش أولاً مع تحديث في الخلفية
  event.respondWith(
    caches.match(req).then(cached => {
      const fetchPromise = fetch(req)
        .then(res => { caches.open(CACHE_NAME).then(cache => cache.put(req, res.clone())); return res; })
        .catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
