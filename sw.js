// ===== زمزم Payroll — Service Worker =====
// v4: إصلاح جذر مشكلة "البرنامج ما فتحش وانت أوفلاين" —
//     index.html (وكمان './' لأنها start_url في manifest.json، وهي طلب
//     شبكة مختلف تمامًا عن './index.html' من وجهة نظر الكاش) كانا
//     مُستبعدين عمدًا من قائمة التثبيت (STATIC_ASSETS) بتعليق "مش
//     index.html" — يعني الصفحة الرئيسية نفسها كانت بتتخزن في الكاش
//     بس "بالصدفة" أول مرة تفتح فيها البرنامج أونلاين بنجاح (من جوه
//     معالج fetch تحت)، ومفيش أي ضمان إنها فعلاً محفوظة. وأخطر من كده:
//     كل تحديث للبرنامج (رفع نسخة جديدة بتغيّر CACHE_NAME) بيشغّل
//     activate اللي بيمسح كل نسخ الكاش القديمة فورًا (تحت) — يعني أي
//     نسخة قديمة من index.html كانت محفوظة اتمسحت، والنسخة الجديدة لسه
//     معندهاش أي نسخة محفوظة خالص لحد أول فتح أونلاين ناجح. فلو حصل إن
//     النت اتقطع بالظبط في الفترة دي (بعد تحديث، قبل أول فتح أونلاين)،
//     فتح البرنامج أوفلاين كان بيفشل تمامًا (مفيش أي fallback في الكاش
//     خالص) — وده بالظبط السلوك اللي وصفه المستخدم.
//
//     الإصلاح: نضيف './' و'./index.html' لقائمة التثبيت، عشان يتخزنوا
//     فورًا وقت تثبيت أي نسخة جديدة من الـ Service Worker — قبل ما
//     المستخدم يحتاج يفتح البرنامج أونلاين أصلاً. سلوك "الشبكة أولاً"
//     في معالج fetch تحت فضل زي ما هو بالظبط بدون أي تغيير — التحديثات
//     لسه بتوصل فورًا لما يكون فيه نت، والكاش ده بس شبكة أمان لما مفيش
const CACHE_NAME = 'zamzam-payroll-v4';
const STATIC_ASSETS = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png'];

// تثبيت: تخزين الملفات الثابتة + الصفحة الرئيسية نفسها (index.html) —
// عشان يكون فيه دايمًا نسخة أوفلاين جاهزة من أول لحظة، حتى لو المستخدم
// لسه مفتحش البرنامج أونلاين بعد هذه النسخة من الـ Service Worker
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
