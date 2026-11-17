export async function onRequest(context) {
  const url = new URL(context.request.url);
  const backend = (context.env && context.env.BACKEND_URL) || "https://hours-lay-referrals-sense.trycloudflare.com";

  // 1. Static asset file extensions: serve directly from Cloudflare CDN
  const isStatic = /\.(css|js|png|jpg|jpeg|webp|svg|ico|woff|woff2|ttf|map)$/i.test(url.pathname);
  if (isStatic) {
    return context.next();
  }

  // 2. Explicit login HTML page
  if (url.pathname === "/login" || url.pathname === "/login.html") {
    const res = await context.next();
    if (res.status === 200) return res;
  }

  // 3. Dynamic requests: /api/*, /auth/*, /admin/*, /local/*, /
  const targetUrl = new URL(url.pathname + url.search, backend);

  const reqHeaders = new Headers(context.request.headers);
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
    init.body = context.request.body;
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
