// Service Worker dla PWA "Mieszkania — Emmerich / Kleve".
// Odpowiada za dwie rzeczy: pokazanie powiadomienia push oraz otwarcie strony po kliknięciu.

self.addEventListener('push', (event) => {
  let payload = { title: '🏠 Mieszkania', body: 'Sprawdź nowe oferty.', url: './' };
  try {
    if (event.data) payload = { ...payload, ...event.data.json() };
  } catch (e) {
    // jesli payload nie jest JSON-em, zostaw domyslny tekst
  }

  event.waitUntil(
    self.registration.showNotification(payload.title, {
      body: payload.body,
      icon: 'icon-192.png',
      badge: 'icon-192.png',
      data: { url: payload.url || './' },
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) || './';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(targetUrl);
    })
  );
});
