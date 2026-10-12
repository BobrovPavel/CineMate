import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function loadApi(apiUrl?: string) {
  vi.resetModules();
  if (apiUrl === undefined) vi.stubEnv("NEXT_PUBLIC_API_URL", "");
  else vi.stubEnv("NEXT_PUBLIC_API_URL", apiUrl);
  if (apiUrl === undefined) delete process.env.NEXT_PUBLIC_API_URL;
  return import("./api");
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

describe("apiFetch", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("возвращает JSON при успехе", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ user_id: 7 }));
    const { apiFetch } = await loadApi("http://api.test");
    await expect(apiFetch("/api/session")).resolves.toEqual({ user_id: 7 });
  });

  it("шлёт credentials: include на базовый URL из NEXT_PUBLIC_API_URL", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const { apiFetch } = await loadApi("http://api.test");
    await apiFetch("/api/profile");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/profile");
    expect(init.credentials).toBe("include");
  });

  it("по умолчанию использует http://localhost:8000", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const { apiFetch } = await loadApi();
    await apiFetch("/api/health");
    expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/api/health");
  });

  it("ставит Content-Type для запроса с телом", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    const { apiFetch } = await loadApi("http://api.test");
    await apiFetch("/api/ratings", { method: "POST", body: "{}" });
    const headers = fetchMock.mock.calls[0][1].headers as Headers;
    expect(headers.get("Content-Type")).toBe("application/json");
  });

  it("не-2xx превращается в ApiError со статусом", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "no" }, 401));
    const { apiFetch, ApiError } = await loadApi("http://api.test");
    const error = await apiFetch("/api/profile").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as InstanceType<typeof ApiError>).status).toBe(401);
  });

  it("сетевая ошибка пробрасывается как есть", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));
    const { apiFetch } = await loadApi("http://api.test");
    await expect(apiFetch("/api/profile")).rejects.toThrow("Failed to fetch");
  });
});
