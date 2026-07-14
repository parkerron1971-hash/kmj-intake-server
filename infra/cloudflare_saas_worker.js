/**
 * Cloudflare-for-SaaS fallback Worker — Host-header bridge to Railway.
 *
 * WHY THIS EXISTS
 * ---------------
 * Custom practitioner domains (e.g. kmjcreate.com) are fronted by Cloudflare
 * for SaaS: Cloudflare terminates TLS and proxies to our Railway backend, which
 * serves the practitioner sites. But Railway routes purely by the Host header
 * and only knows `kmj-intake-server-production.up.railway.app`. Cloudflare
 * forwards the ORIGINAL Host (`kmjcreate.com`), so Railway answers every custom
 * domain with `{"code":404,"message":"Application not found"}`.
 *
 * Cloudflare's built-in Host-header override lives in Origin Rules — which is
 * ENTERPRISE-ONLY. On any other plan the supported fix is a Worker. This is it.
 *
 * WHAT IT DOES
 * ------------
 * For custom-domain traffic it rewrites the origin Host to the Railway hostname
 * (so Railway routes the request to our service) and forwards the real customer
 * hostname in `X-Forwarded-Host`. The backend reads that via `public_host()`
 * (public_site.py) to pick which site to serve.
 *
 * Anything on our own zone (`*.mysolutionist.app` — the Vercel app, the DNS-only
 * platform subdomains, the fallback-origin record) is passed through untouched.
 * DNS-only (gray) records never reach a Worker anyway; this guard only matters
 * for proxied zone hosts and keeps the Worker a strict no-op for them.
 *
 * DEPLOY
 * ------
 * 1. Workers & Pages → Create Worker → paste this → Deploy.
 * 2. That Worker → Settings → Triggers → Add route:
 *       Zone   = mysolutionist.app
 *       Route  = *​/*            (catches SaaS custom-hostname traffic too;
 *                                 you do NOT add a route per custom domain)
 * 3. Leave the SSL/TLS → Custom Hostnames fallback origin as-is; the Worker
 *    short-circuits before origin resolution for custom hostnames.
 *
 * The X-Forwarded-Host header is trusted for SITE SELECTION only (all sites are
 * public read-only), so spoofing it just selects which public site renders — no
 * auth or data exposure. Add a shared-secret header here + a check in
 * public_host() if that ever stops being true.
 */

const RAILWAY_ORIGIN = "kmj-intake-server-production.up.railway.app";
const PLATFORM_ZONE = "mysolutionist.app";

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const host = (request.headers.get("host") || "").split(":")[0].toLowerCase();

    // Our own zone (app on Vercel, platform subdomains, fallback record):
    // never touch it — let it resolve to its configured origin.
    if (host === PLATFORM_ZONE || host.endsWith("." + PLATFORM_ZONE)) {
      return fetch(request);
    }

    // Custom domain: send to Railway with a Host it recognizes, and carry the
    // real hostname so the backend can pick the practitioner's site.
    url.hostname = RAILWAY_ORIGIN;
    const headers = new Headers(request.headers);
    headers.set("X-Forwarded-Host", host);
    headers.delete("Host"); // let fetch() derive Host from url.hostname

    return fetch(new Request(url.toString(), {
      method: request.method,
      headers,
      body: request.body,
      redirect: "manual", // pass Railway's 3xx straight back to the visitor
    }));
  },
};
