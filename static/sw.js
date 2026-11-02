// shiphub service worker: phone push for HQ notifications.
// Pushes arrive without a payload; the worker fetches the newest notification
// (with the normal login cookie) so message text never passes through push servers.
const CACHE = "shiphub-v1";

self.addEventListener("install", () => self.skipWaiting());

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

async function latestNotification() {
  try {
    const response = await fetch("/api/notifications", { credentials: "same-origin" });
    if (!response.ok) return null;
    const data = await response.json();
    const item = (data.items || []).find((entry) => !entry.is_read) || (data.items || [])[0];
    if (!item) return null;
    if (item.kind === "hq") return { body: item.text, link: item.link || "hq" };
    return { body: `New activity on ${item.idea_title || "your idea"}`, link: `i/${item.idea_id}` };
  } catch (error) {
    return null;
  }
}

self.addEventListener("push", (event) => {
  event.waitUntil((async () => {
    const latest = (await latestNotification()) || { body: "You have a new notification", link: "hq" };
    await self.registration.showNotification("shiphub", {
      body: latest.body,
      icon: "/static/icon-192.png",
      badge: "/static/icon-192.png",
      tag: "shiphub-" + latest.link,
      renotify: true,
      data: { link: latest.link },
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = "/#/" + ((event.notification.data && event.notification.data.link) || "hq");
  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const client of windows) {
      if (new URL(client.url).origin === self.location.origin) {
        await client.focus();
        client.navigate(target).catch(() => {});
        return;
      }
    }
    await self.clients.openWindow(target);
  })());
});
