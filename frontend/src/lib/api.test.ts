import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function loadApi(apiUrl?: string) {
  vi.resetModules();
  if (apiUrl === undefined) vi.unstubAllEnvs();
  else vi.stubEnv("NEXT_PUBLIC_API_URL", apiUrl);
  return import("./api");
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("apiFetch", () => {
  it("возвращает JSON при успехе", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    const { apiFetch } = await loadApi("http://api.test");
    await expect(apiFetch("/api/x")).resolves.toEqual({ ok: true });
  });

  it("шлёт запрос на NEXT_PUBLIC_API_URL с credentials: include", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    const { apiFetch } = await loadApi("http://api.test");
    await apiFetch("/api/x", { method: "POST" });
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/x");
    expect(init.credentials).toBe("include");
    expect(init.method).toBe("POST");
  });

  it("по умолчанию использует http://localhost:8000", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    const prev = process.env.NEXT_PUBLIC_API_URL;
    delete process.env.NEXT_PUBLIC_API_URL;
    try {
      const { apiFetch } = await loadApi();
      await apiFetch("/api/x");
    } finally {
      if (prev !== undefined) process.env.NEXT_PUBLIC_API_URL = prev;
    }
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/api/x");
  });

  it("ставит Content-Type только при наличии body", async () => {
    fetchMock.mockImplementation(async () => new Response("{}", { status: 200 }));
    const { apiFetch } = await loadApi("http://api.test");
    await apiFetch("/api/a");
    await apiFetch("/api/b", { method: "POST", body: "{}" });
    expect(new Headers(fetchMock.mock.calls[0][1].headers).has("Content-Type")).toBe(false);
    expect(new Headers(fetchMock.mock.calls[1][1].headers).get("Content-Type")).toBe(
      "application/json",
    );
  });

  it("не-2xx превращается в ApiError со статусом", async () => {
    fetchMock.mockResolvedValue(new Response("nope", { status: 401 }));
    const { apiFetch, ApiError } = await loadApi("http://api.test");
    const error = await apiFetch("/api/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as InstanceType<typeof ApiError>).status).toBe(401);
    expect((error as Error).name).toBe("ApiError");
  });

  it("сетевая ошибка пробрасывается как есть", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { apiFetch, ApiError } = await loadApi("http://api.test");
    const error = await apiFetch("/api/x").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(TypeError);
    expect(error).not.toBeInstanceOf(ApiError);
  });
});
