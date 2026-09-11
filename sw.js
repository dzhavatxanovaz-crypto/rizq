/* Ризк - офлайн-кэш. Меняйте номер версии при каждом обновлении приложения. */
var CACHE = "rizq-v86";
var ASSETS = [
  "./",
  "./index.html",
  "./fonts.css",
  "./privacy.html",
  "./manifest.webmanifest",
  "./posts.json",
  "./sadaqa.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
  "./audio/adhan.mp3"
];

/* каждый файл кладём отдельно: один недоступный адрес не должен ломать весь кэш */
self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(CACHE).then(function (c) {
      return Promise.all(ASSETS.map(function (url) {
        return c.add(url).catch(function () { return null; });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      /* rizq-audio не трогаем: это скачанное человеком аудио, а не наш кэш.
         Стирать его при каждом обновлении - значит заставлять качать заново. */
      return Promise.all(keys.filter(function (k) { return k.indexOf("rizq-v") === 0 ? k !== CACHE : false; /* общий домен с Volt: чужие кэши и rizq-audio не трогаем */ })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  if (e.request.method !== "GET") return;
  var url = new URL(e.request.url);
  /* Скачанное аудио Корана. Пользователь качает его сам, отдельной кнопкой,
     и лежит оно в своём хранилище: обновление приложения его не стирает.
     Сами ничего сюда не кладём - иначе прослушивание онлайн незаметно
     забивало бы память телефона. */
  if (url.hostname === "cdn.islamic.network") {
    e.respondWith(
      caches.open("rizq-audio").then(function (c) {
        return c.match(e.request).then(function (hit) {
          return hit || fetch(e.request);
        });
      })
    );
    return;
  }

  if (url.origin !== location.origin) return;   /* аудио и внешние сайты мимо кэша */

  /* Журнал и подборка сборов обновляются без пересборки приложения, поэтому
     для них сначала сеть, а кэш - запасной вариант. Иначе правка файла на
     хостинге не дошла бы до тех, у кого он уже лежит в кэше. */
  if (url.pathname.indexOf("posts.json") !== -1 || url.pathname.indexOf("sadaqa.json") !== -1) {
    e.respondWith(
      fetch(e.request).then(function (resp) {
        if (resp && resp.status === 200) {
          var copy = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
        }
        return resp;
      }).catch(function () {
        return caches.match(e.request).then(function (hit) {
          return hit;
        });
      })
    );
    return;
  }

  /* Сама страница приложения - сначала сеть: иначе исправление доходило бы
     до человека только со второго открытия. Без сети - из кэша, как раньше. */
  if (e.request.mode === "navigate") {
    e.respondWith(
      fetch(e.request).then(function (resp) {
        if (resp && resp.status === 200) {
          var copy = resp.clone();
          caches.open(CACHE).then(function (c) { c.put("./index.html", copy); });
        }
        return resp;
      }).catch(function () {
        return caches.match("./index.html").then(function (hit) { return hit || caches.match("./"); });
      })
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(function (hit) {
      if (hit) return hit;
      return fetch(e.request).then(function (resp) {
        if (resp && resp.status === 200 && resp.type === "basic") {
          var copy = resp.clone();
          caches.open(CACHE).then(function (c) { c.put(e.request, copy); });
        }
        return resp;
      }).catch(function () {
        return caches.match("./index.html");
      });
    })
  );
});
