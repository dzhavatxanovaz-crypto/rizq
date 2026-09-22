/* Ризк - офлайн-кэш. Меняйте номер версии при каждом обновлении приложения. */
var CACHE = "rizq-v165";
var ASSETS = [
  "./",
  "./index.html",
  "./fonts.css",
  /* основные наборы шрифтов - чтобы без интернета текст выглядел так же; остальные наборы кэшируются при первом использовании */
  "./fonts/inter-cyrillic.woff2",
  "./fonts/inter-latin.woff2",
  "./fonts/montserrat-cyrillic.woff2",
  "./fonts/montserrat-latin.woff2",
  "./fonts/marcellus-latin.woff2",
  "./fonts/noto-naskh-arabic-arabic.woff2",
  "./fonts/amiri-quran-arabic.woff2",
  "./fonts/scheherazade-new-arabic.woff2",
  "./fonts/noto-naskh-arabic-latin.woff2",
  "./privacy.html",
  "./manifest.webmanifest",
  "./posts.json",
  "./sadaqa.json",
  "./icons/icon-192.png",
  "./icons/icon-512.png"
  /* азан (1,4 МБ) сюда не кладём: на медленной связи он не давал офлайн-кэшу
     установиться при первом входе, и потом приложение не открывалось без интернета.
     Азан сохраняется в кэш при первом проигрывании (общее правило ниже). */
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

/* Уведомление при закрытом приложении. Текст приходит зашифрованным
   ключом этого телефона; браузер расшифровывает его сам. Одна метка на
   все напоминания о намазе: новое заменяет прежнее, а не копится. */
self.addEventListener("push", function (e) {
  var d = {};
  try { d = e.data ? e.data.json() : {}; } catch (x) { d = { title: "RIZQ", body: e.data ? e.data.text() : "" }; }
  e.waitUntil(self.registration.showNotification(d.title || "RIZQ", {
    body: d.body || "",
    icon: "icons/icon-192.png",
    badge: "icons/icon-192.png",
    tag: d.tag || "rizq",
    renotify: true
  }));
});

self.addEventListener("notificationclick", function (e) {
  e.notification.close();
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) { if ("focus" in list[i]) return list[i].focus(); }
    return clients.openWindow("./");
  }));
});

self.addEventListener("fetch", function (e) {
  if (e.request.method !== "GET") return;
  var url = new URL(e.request.url);
  /* Скачанное аудио Корана. Пользователь качает его сам, отдельной кнопкой,
     и лежит оно в своём хранилище: обновление приложения его не стирает.
     Сами ничего сюда не кладём - иначе прослушивание онлайн незаметно
     забивало бы память телефона. С 21.09 часть чтецов и разметка слов - с quran.com. */
  if (url.hostname === "cdn.islamic.network" || url.hostname === "verses.quran.com" || url.hostname === "mirrors.quranicaudio.com" || url.hostname === "api.quran.com") {
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
  /* Страницы мединского мусхафа и их шрифты не меняются (путь с номером издания v1):
     храним их отдельно, в rizq-mushaf, - обновление приложения их не стирает,
     и однажды открытая страница читается без интернета. */
  if (url.pathname.indexOf("/mushaf/") !== -1) {
    e.respondWith(
      caches.open("rizq-mushaf").then(function (c) {
        return c.match(e.request).then(function (hit) {
          return hit || fetch(e.request).then(function (resp) {
            if (resp && resp.status === 200) c.put(e.request, resp.clone());
            return resp;
          });
        });
      })
    );
    return;
  }
  /* отзывы «Халяль рядом» и прочие обращения к серверу - только из сети, иначе кэш покажет вчерашние */
  if (url.pathname.indexOf("/api/") === 0) return;

  /* Журнал и подборка сборов обновляются без пересборки приложения, поэтому
     для них сначала сеть, а кэш - запасной вариант. Иначе правка файла на
     хостинге не дошла бы до тех, у кого он уже лежит в кэше. */
  if (url.pathname.indexOf("posts.json") !== -1 || url.pathname.indexOf("sadaqa.json") !== -1 || url.pathname.indexOf("/halal/") !== -1 || url.pathname.indexOf("audio/ar/list.json") !== -1) {
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

  /* Главная страница - сразу из памяти телефона, если она там есть: так RIZQ
     открывается мгновенно и при плохой связи, и без неё. Раньше было «сначала
     сеть»: на медленном интернете человек ждал, пока 2,9 МБ скачаются заново,
     а при «сеть есть, но висит» приложение не открывалось совсем.
     Новая версия приходит сама: при выпуске меняется номер кэша, браузер ставит
     новый офлайн-кэш в фоне, и появляется плашка «Вышла новая версия». */
  if (e.request.mode === "navigate") {
    var isApp = url.pathname === "/" || /\/index\.html$/.test(url.pathname) || /\/$/.test(url.pathname);
    e.respondWith(
      caches.match(isApp ? "./index.html" : e.request).then(function (hit) {
        if (hit) return hit;
        return fetch(e.request).then(function (resp) {
          if (isApp && resp && resp.status === 200) {
            var copy = resp.clone();
            caches.open(CACHE).then(function (c) { c.put("./index.html", copy); });
          }
          return resp;
        }).catch(function () {
          return caches.match("./index.html").then(function (h) { return h || caches.match("./"); });
        });
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
