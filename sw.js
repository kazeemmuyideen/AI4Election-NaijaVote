const CACHE='naijavote-shell-v2';
const SHELL=['/','/index.html','/styles.css','/app.js','/manifest.webmanifest','/favicon.svg','/icon-192.png','/icon-512.png'];

self.addEventListener('install',event=>{
  event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(SHELL)).then(()=>self.skipWaiting()));
});

self.addEventListener('activate',event=>{
  event.waitUntil(
    caches.keys()
      .then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))
      .then(()=>self.clients.claim())
  );
});

self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET')return;
  const url=new URL(request.url);
  if(url.origin!==location.origin||url.pathname.startsWith('/api/'))return;

  // Navigations are network-first so a new deployment is picked up, with a cached shell offline.
  if(request.mode==='navigate'){
    const isShell=url.pathname==='/'||url.pathname==='/index.html';
    event.respondWith(
      fetch(request)
        .then(response=>{
          if(isShell&&response.ok){
            const copy=response.clone();
            caches.open(CACHE).then(cache=>cache.put('/index.html',copy));
          }
          return response;
        })
        .catch(()=>caches.match('/index.html').then(cached=>cached||caches.match('/')))
    );
    return;
  }

  // Static assets: serve from cache immediately, refresh in the background.
  event.respondWith(
    caches.match(request).then(cached=>{
      const network=fetch(request)
        .then(response=>{
          if(response.ok){
            const copy=response.clone();
            caches.open(CACHE).then(cache=>cache.put(request,copy));
          }
          return response;
        })
        .catch(()=>cached);
      return cached||network;
    })
  );
});
