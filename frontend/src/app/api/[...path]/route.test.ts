import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DELETE, GET, POST } from "./route";

const fetchMock = vi.fn();

function ctx(...path: string[]) {
  return { params: Promise.resolve({ path }) };
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  vi.stubEnv("API_INTERNAL_URL", "http://api.test");
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("API proxy", () => {
  it("передаёт cookie и тело POST, возвращает статус и тело", async () => {
    fetchMock.mockResolvedValue(
      new Response('{"ok":true}', { status: 201, headers: { "content-type": "application/json" } }),
    );
    const request = new Request("http://site.test/api/ratings", {
      method: "POST",
      headers: { cookie: "cinemate_session=abc", "content-type": "application/json", "accept-language": "ru-RU,ru;q=0.9", "x-evil": "1" },
      body: '{"movie_id":1}',
    });
    const response = await POST(request, ctx("ratings"));
    expect(response.status).toBe(201);
    expect(await response.text()).toBe('{"ok":true}');
    expect(response.headers.get("content-type")).toBe("application/json");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("http://api.test/api/ratings");
    expect(init.method).toBe("POST");
    const sent = new Headers(init.headers);
    expect(sent.get("cookie")).toBe("cinemate_session=abc");
    expect(sent.get("content-type")).toBe("application/json");
    expect(sent.get("accept-language")).toBe("ru-RU,ru;q=0.9");
    expect(sent.get("x-evil")).toBeNull();
    expect(new TextDecoder().decode(init.body)).toBe('{"movie_id":1}');
  });

  it("возвращает несколько set-cookie раздельно", async () => {
    const upstream = new Headers({ "content-type": "application/json", "x-other": "1" });
    upstream.append("set-cookie", "a=1; Path=/; HttpOnly");
    upstream.append("set-cookie", "b=2; Path=/");
    fetchMock.mockResolvedValue(new Response("{}", { headers: upstream }));
    const response = await POST(new Request("http://site.test/api/session", { method: "POST" }), ctx("session"));
    expect(response.headers.getSetCookie()).toEqual(["a=1; Path=/; HttpOnly", "b=2; Path=/"]);
    expect(response.headers.get("x-other")).toBeNull();
  });

  it("сохраняет query-строку", async () => {
    fetchMock.mockResolvedValue(new Response("[]"));
    await GET(new Request("http://site.test/api/recommendations?limit=5"), ctx("recommendations"));
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/recommendations?limit=5");
  });

  it("строит путь из нескольких сегментов", async () => {
    fetchMock.mockResolvedValue(new Response("{}"));
    await GET(new Request("http://site.test/api/movies/42"), ctx("movies", "42"));
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/movies/42");
  });

  it("отвечает 502 при ошибке fetch", async () => {
    fetchMock.mockRejectedValue(new TypeError("fetch failed"));
    const response = await GET(new Request("http://site.test/api/health"), ctx("health"));
    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ detail: "API unavailable" });
  });

  it.each([["..", "x"], ["a", ".."], ["a", ""]])("отклоняет сегменты %j ответом 400", async (...path) => {
    const response = await GET(new Request("http://site.test/api/x"), ctx(...path));
    expect(response.status).toBe(400);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("кодирует сегменты, хост назначения не меняется", async () => {
    fetchMock.mockResolvedValue(new Response("{}"));
    await GET(new Request("http://site.test/api/x"), ctx("@evil.test", "a/b"));
    const url: string = fetchMock.mock.calls[0][0];
    expect(url.startsWith("http://api.test/api/")).toBe(true);
    expect(new URL(url).host).toBe("api.test");
  });

  it("читает API_INTERNAL_URL во время запроса", async () => {
    fetchMock.mockResolvedValue(new Response("{}"));
    await GET(new Request("http://site.test/api/health"), ctx("health"));
    vi.stubEnv("API_INTERNAL_URL", "http://other.test/");
    await GET(new Request("http://site.test/api/health"), ctx("health"));
    expect(fetchMock.mock.calls[0][0]).toBe("http://api.test/api/health");
    expect(fetchMock.mock.calls[1][0]).toBe("http://other.test/api/health");
  });

  it("по умолчанию ходит на http://127.0.0.1:8000", async () => {
    vi.stubEnv("API_INTERNAL_URL", "");
    fetchMock.mockResolvedValue(new Response("{}"));
    await GET(new Request("http://site.test/api/health"), ctx("health"));
    expect(fetchMock.mock.calls[0][0]).toBe("http://127.0.0.1:8000/api/health");
  });

  it("остальные методы → 405", () => {
    expect(DELETE().status).toBe(405);
  });
});
