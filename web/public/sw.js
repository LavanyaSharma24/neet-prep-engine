// App-shell + item_bank.json cache so retrieval works fully offline after
// the first load. Cache-first with a background revalidate for same-origin
// GET requests; anything cross-origin (the api/ backend) is left alone.
//
// The revalidation fetch is wrapped in event.waitUntil() so it's
// guaranteed to run to completion (and actually update the cache) rather
// than risking early termination once the fetch event's response has been
// sent. CACHE_NAME also gets bumped on any deploy where old entries should
// be evicted outright rather than relying on revalidation alone — activate()
// below deletes every cache that isn't the current CACHE_NAME.
const CACHE_NAME = "neet-prep-cache-v2";
const APP_SHELL = ["/", "/index.html", "/manifest.json", "/item_bank.json"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL))
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  // KNOWN ISSUE (not fixed yet, left as-is intentionally): this deletes
  // *every* cache that isn't CACHE_NAME, including "transformers-cache" —
  // the separate Cache Storage entry @xenova/transformers uses for the
  // ~250MB downloaded Tier 1 model (see src/tier1.ts). That means every
  // deploy that bumps CACHE_NAME wipes the downloaded model too, forcing a
  // full re-download on next use. Fix would be to only delete keys that
  // look like our own app-shell cache (e.g. keys.filter((key) => key.startsWith("neet-prep-cache-") && key !== CACHE_NAME)),
  // leaving unrelated caches alone.
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
      )
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // never intercept calls to the api/ backend

  event.respondWith(
    caches.match(request).then((cached) => {
      const networkFetch = fetch(request)
        .then((response) => {
          if (response && response.status === 200) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          }
          return response;
        })
        .catch(() => cached);

      // Keep the worker alive until the revalidation fetch (and its cache
      // write) actually finishes, even on a cache hit below where
      // networkFetch isn't what answers this request. Without this, the
      // browser can tear the worker down as soon as respondWith's promise
      // settles, the cache.put above never lands, and a returning visitor
      // stays stuck on stale content indefinitely instead of getting it
      // fixed after one background revalidation.
      event.waitUntil(networkFetch);

      return cached || networkFetch;
    })
  );
});
