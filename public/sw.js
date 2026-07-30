// Minimal service worker: show a system notification on push, focus/open the
// app when it's tapped. No caching/offline support — not the point here.

self.addEventListener('push', (event) => {
  let data = { title: 'Robin', body: 'You have a reminder.' };
  try {
    data = event.data.json();
  } catch (e) {
    // ignore, use default
  }
  event.waitUntil(
    self.registration.showNotification(data.title || 'Robin', {
      body: data.body || '',
      icon: '/icon.svg',
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  event.waitUntil(
    clients.matchAll({ type: 'window' }).then((clientList) => {
      for (const client of clientList) {
        if ('focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow('/');
    })
  );
});
