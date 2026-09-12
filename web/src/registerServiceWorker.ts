export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  // sw.js caches every same-origin GET cache-first (see public/sw.js). In a
  // production build that's safe: Vite content-hashes each asset's
  // filename, so a stale cache entry just goes unused. In `npm run dev`
  // filenames never change (always /src/App.tsx, /src/index.css, ...), so
  // a cache-first SW serves whatever it cached last against those same
  // paths — new JS can end up paired with stale CSS (or vice versa) after
  // any edit. Skip registration entirely in dev to avoid that whole class
  // of "did my change actually apply?" confusion.
  if (import.meta.env.DEV) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((err) => {
      console.error("Service worker registration failed", err);
    });
  });
}
