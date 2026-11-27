const CACHE='naijavote-shell-v12';
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

const SHELL_PATHS=new Set(SHELL);
function isStaticAsset(pathname){
  return SHELL_PATHS.has(pathname);
}

self.addEventListener('fetch',event=>{
  const request=event.request;
  if(request.method!=='GET')return;
  let url;
  try{url=new URL(request.url);}catch{return;}
  if(url.origin!==location.origin)return;
  if(url.pathname.startsWith('/api/'))return;
  if(request.cache==='no-store')return;

  // Navigations are network-first so a new deployment is picked up, with a cached shell offline.
  if(request.mode==='navigate'){
    event.respondWith((async()=>{
      try{
        const response=await fetch(request);
        if(response&&response.ok&&response.type==='basic'){
          const cache=await caches.open(CACHE);
          await cache.put('/index.html',response.clone());
        }
        return response;
      }catch{
        const cached=await caches.match('/index.html',{ignoreSearch:true});
        return cached||caches.match('/',{ignoreSearch:true})||Response.error();
      }
    })());
    return;
  }

  // Only cache known same-origin static shell assets; never cache docs/API/admin or arbitrary responses.
  if(!isStaticAsset(url.pathname))return;
  event.respondWith((async()=>{
    const cache=await caches.open(CACHE);
    const cached=await cache.match(request,{ignoreSearch:true});
    try{
      const response=await fetch(request);
      if(response&&response.ok&&response.type==='basic'){
        await cache.put(request,response.clone());
      }
      return response;
    }catch{
      return cached||Response.error();
    }
  })());
});
