const DEFAULT_API_INTERNAL_URL = "http://127.0.0.1:8000";

type Context = { params: Promise<{ path: string[] }> };

function badRequest(): Response {
  return Response.json({ detail: "Invalid path" }, { status: 400 });
}

async function proxy(request: Request, context: Context): Promise<Response> {
  const { path } = await context.params;
  if (path.some((segment) => segment === "" || segment === "." || segment === "..")) {
    return badRequest();
  }
  const base = (process.env.API_INTERNAL_URL || DEFAULT_API_INTERNAL_URL).replace(/\/+$/, "");
  const search = new URL(request.url).search;
  const target = `${base}/api/${path.map(encodeURIComponent).join("/")}${search}`;

  const headers = new Headers();
  for (const name of ["cookie", "content-type"]) {
    const value = request.headers.get(name);
    if (value !== null) headers.set(name, value);
  }

  let upstream: Response;
  try {
    upstream = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "POST" ? await request.arrayBuffer() : undefined,
      redirect: "manual",
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "API unavailable" }, { status: 502 });
  }

  const responseHeaders = new Headers();
  const contentType = upstream.headers.get("content-type");
  if (contentType !== null) responseHeaders.set("content-type", contentType);
  for (const cookie of upstream.headers.getSetCookie()) {
    responseHeaders.append("set-cookie", cookie);
  }
  return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
}

export const dynamic = "force-dynamic";

export const GET = proxy;
export const POST = proxy;

function methodNotAllowed(): Response {
  return new Response(null, { status: 405, headers: { allow: "GET, POST" } });
}

export const PUT = methodNotAllowed;
export const PATCH = methodNotAllowed;
export const DELETE = methodNotAllowed;
