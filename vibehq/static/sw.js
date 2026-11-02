// vibeHQ service worker: offline app shell + push notifications.
// Pushes arrive without payload; we fetch the newest notification from the API
// so notification text never passes through third-party push servers.
const CACHE = "vibehq-v2";
const SHELL = ["/", "/manifest.webmanifest", "/static/icon-192.png", "/static/icon-512.png"];

self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener("activate", event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key !== CACHE).map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", event => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) {
    return;
  }
  // network first, cached shell when offline
  event.respondWith((async () => {
    try {
      const response = await fetch(event.request);
      const cache = await caches.open(CACHE);
      cache.put(event.request, response.clone());
      return response;
    } catch (error) {
      return (await caches.match(event.request)) || (await caches.match("/"));
    }
  })());
});

function readToken() {
  return new Promise(resolve => {
    const open = indexedDB.open("vibehq", 1);
    open.onupgradeneeded = () => open.result.createObjectStore("kv");
    open.onerror = () => resolve(null);
    open.onsuccess = () => {
      const read = open.result.transaction("kv", "readonly").objectStore("kv").get("token");
      read.onsuccess = () => resolve(read.result || null);
      read.onerror = () => resolve(null);
    };
  });
}

async function showLatestNotification() {
  let body = "You have a new notification";
  let link = "feed";
  try {
    const token = await readToken();
    if (token) {
      const response = await fetch("/api/notifications?unread=1&limit=1", {
        headers: { Authorization: "Bearer " + token },
      });
      if (response.ok) {
        const data = await response.json();
        if (data.notifications.length) {
          body = data.notifications[0].text;
          link = data.notifications[0].link || "feed";
        }
      }
    }
  } catch (error) {
    // fall back to the generic text - a push must always show something
  }
  return self.registration.showNotification("vibeHQ", {
    body,
    icon: "/static/icon-192.png",
    badge: "/static/icon-192.png",
    tag: "vibehq-" + link,
    renotify: true,
    data: { link },
  });
}

self.addEventListener("push", event => {
  event.waitUntil(showLatestNotification());
});

self.addEventListener("notificationclick", event => {
  event.notification.close();
  const target = "/#" + (event.notification.data && event.notification.data.link || "feed");
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === location.origin) {
        await client.focus();
        client.postMessage({ type: "open", link: event.notification.data.link });
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
