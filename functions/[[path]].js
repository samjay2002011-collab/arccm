export async function onRequest(context) {
  const url = new URL(context.request.url);
  const backend = (context.env && context.env.BACKEND_URL) || "https://arccm.fastapicloud.dev";

  // 1. Static frontend assets (CSS, JS, favicon, icons, hideout)
  if (
    url.pathname.endsWith(".css") ||
    url.pathname.endsWith(".js") ||
    url.pathname === "/favicon.png" ||
    url.pathname.startsWith("/icons/") ||
    url.pathname.startsWith("/assets/hideout/")
  ) {
    return context.next();
  }

  // 2. Direct Cloudflare CDN downloads for CMSync:
  if (
    url.pathname === "/download/CMSync.exe" ||
    url.pathname.toLowerCase() === "/download/cmsync.exe"
  ) {
    const assetUrl = new URL("/CMSync.exe", url.origin);
    const assetRes = context.env.ASSETS ? await context.env.ASSETS.fetch(assetUrl) : await context.next();
    const headers = new Headers(assetRes.headers);
    headers.set("Content-Disposition", 'attachment; filename="CMSync.exe"');
    headers.set("Content-Type", "application/octet-stream");
    return new Response(assetRes.body, { status: assetRes.status, headers });
  }

  if (
    url.pathname === "/download/cmsync" ||
    url.pathname.toLowerCase() === "/download/cmsync" ||
    url.pathname === "/download/CMSync_Setup.exe" ||
    url.pathname.toLowerCase() === "/download/cmsync_setup.exe" ||
    url.pathname.toLowerCase() === "/download/setup"
  ) {
    const assetUrl = new URL("/CMSync_Setup.exe", url.origin);
    const assetRes = context.env.ASSETS ? await context.env.ASSETS.fetch(assetUrl) : await context.next();
    const headers = new Headers(assetRes.headers);
    headers.set("Content-Disposition", 'attachment; filename="CMSync_Setup.exe"');
    headers.set("Content-Type", "application/octet-stream");
    return new Response(assetRes.body, { status: assetRes.status, headers });
  }

  // 3. Login page: /login or /login.html
  if (url.pathname === "/login" || url.pathname === "/login.html") {
    const loginUrl = new URL("/login.html", url.origin);
    const assetRes = context.env.ASSETS ? await context.env.ASSETS.fetch(loginUrl) : await context.next();
    if (assetRes.status === 200) return assetRes;
    return context.next();
  }

  // 4. Root /: single-domain unified entry
  // If not logged in, redirect directly to /login
  // If logged in (has cookie), serve index.html statically
  if (url.pathname === "/" || url.pathname === "/index.html") {
    const cookie = context.request.headers.get("cookie") || "";
    const hasAuth = cookie.includes("cm_subscriber_token") || cookie.includes("cm_admin_session");
    if (!hasAuth) {
      return Response.redirect(new URL("/login", url.origin).toString(), 302);
    }
    return context.next();
  }

  // 5. For image assets under /assets/:
  const isImage = /\.(png|webp|jpg|jpeg|svg|ico)$/i.test(url.pathname);
  if (isImage) {
    const staticRes = await context.next();
    const contentType = staticRes.headers.get("content-type") || "";
    if (staticRes.status === 200 && contentType.startsWith("image/")) {
      return staticRes;
    }
  }

  // 6. Proxy dynamic requests to backend:
  // /api/*, /auth/*, /admin, /admin/api/*, /local/*, /assets/items/*
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
    // Fallback: try static asset
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
