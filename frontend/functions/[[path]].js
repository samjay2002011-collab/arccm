export async function onRequest(context) {
  const url = new URL(context.request.url);
  const backend = (context.env && context.env.BACKEND_URL) || "https://hours-lay-referrals-sense.trycloudflare.com";

  // 1. Files that definitely belong to frontend static build:
  // /, /index.html, .css, .js, favicon.png, /icons/*, and /assets/hideout/*
  if (
    url.pathname === "/" ||
    url.pathname === "/index.html" ||
    url.pathname.endsWith(".css") ||
    url.pathname.endsWith(".js") ||
    url.pathname === "/favicon.png" ||
    url.pathname.startsWith("/icons/") ||
    url.pathname.startsWith("/assets/hideout/")
  ) {
    return context.next();
  }

  // 2. Explicit login HTML page
  if (url.pathname === "/login" || url.pathname === "/login.html") {
    const res = await context.next();
    if (res.status === 200) return res;
  }

  // 3. For image assets under /assets/:
  // First try static asset from Cloudflare CDN; if present and is a real image (not HTML SPA fallback), serve it!
  const isImage = /\.(png|webp|jpg|jpeg|svg|ico)$/i.test(url.pathname);
  if (isImage) {
    const staticRes = await context.next();
    const contentType = staticRes.headers.get("content-type") || "";
    if (staticRes.status === 200 && contentType.startsWith("image/")) {
      return staticRes;
    }
    // If not found statically or returned HTML, proceed to proxy from backend below!
  }

  // 4. Proxy dynamic requests and missing assets to backend:
  // /api/*, /auth/*, /admin/*, /local/*, /assets/items/*, /
  const targetUrl = new URL(url.pathname + url.search, backend);

  const reqHeaders = new Headers();
  for (const [key, val] of context.request.headers.entries()) {
    const k = key.toLowerCase();
    if (k !== "host" && k !== "content-length") {
      reqHeaders.set(key, val);
    }
  }
  reqHeaders.set("Host", new URL(backend).host);
  reqHeaders.set("X-Forwarded-Host", url.host);
  reqHeaders.set("X-Forwarded-Proto", "https");

  const method = context.request.method.toUpperCase();
  const init = {
    method,
    headers: reqHeaders,
    redirect: "manual"
  };

  if (method !== "GET" && method !== "HEAD") {
    init.body = await context.request.arrayBuffer();
  }

  try {
    const backendRes = await fetch(targetUrl.toString(), init);
    const resHeaders = new Headers(backendRes.headers);

    // Rewrite Location header on redirects so visitor stays on this domain
    const loc = resHeaders.get("Location");
    if (loc) {
      try {
        const locUrl = new URL(loc, backend);
        if (locUrl.host === new URL(backend).host) {
          resHeaders.set("Location", locUrl.pathname + locUrl.search + locUrl.hash);
        }
      } catch (e) {}
    }

    resHeaders.set("Access-Control-Allow-Origin", url.origin);
    resHeaders.set("Access-Control-Allow-Credentials", "true");

    return new Response(backendRes.body, {
      status: backendRes.status,
      statusText: backendRes.statusText,
      headers: resHeaders
    });
  } catch (err) {
    // If backend proxy fails, try serving static asset (e.g. index.html) as fallback
    const fallback = await context.next();
    if (fallback.status === 200) return fallback;

    return new Response(JSON.stringify({
      error: "Backend temporarily unreachable",
      detail: err.message
    }), {
      status: 502,
      headers: { "Content-Type": "application/json" }
    });
  }
}
