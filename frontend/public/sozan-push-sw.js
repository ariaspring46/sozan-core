/* Sozan's only service worker: it shows the seller's notifications and opens the panel on a tap.
   It has no fetch handler, so it never caches or answers a page request. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch (_) {
    data = { body: event.data ? event.data.text() : "" };
  }
  const title = data.title || "سوزان";
  event.waitUntil(
    self.registration.showNotification(title, {
      body: data.body || "پیام تازه در سوزان",
      icon: "/icons/sozan-192.png",
      badge: "/icons/sozan-192.png",
      tag: data.tag || "sozan",
      renotify: true,
      dir: "rtl",
      lang: "fa",
      data: { url: data.url || "/chat" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL((event.notification.data && event.notification.data.url) || "/chat", self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.startsWith(self.location.origin)) {
          return client.focus().then((focused) => (focused && "navigate" in focused ? focused.navigate(target) : focused));
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});
