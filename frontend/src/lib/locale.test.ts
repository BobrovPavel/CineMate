import { describe, expect, it } from "vitest";

import { pickLanguage, poolMismatchesLang } from "./locale";

describe("pickLanguage", () => {
  it.each([
    ["ru", "en-US", "ru"],
    ["en", "ru-RU,ru;q=0.9", "en"],
    [undefined, "ru", "ru"],
    [undefined, "ru-RU,ru;q=0.9,en;q=0.8", "ru"],
    [undefined, "RU-ru", "ru"],
    [undefined, "en-US,ru;q=0.5", "en"],
    [undefined, "ru;q=0", "en"],
    [undefined, "ru;q=abc", "en"],
    [undefined, "rus", "en"],
    [undefined, "*", "en"],
    [undefined, "de", "en"],
    [undefined, undefined, "en"],
    [null, null, "en"],
  ])("cookie %j + header %j -> %s", (cookie, header, expected) => {
    expect(pickLanguage(cookie, header)).toBe(expected);
  });

  it("неверное значение cookie игнорируется", () => {
    expect(pickLanguage("de", "ru")).toBe("ru");
    expect(pickLanguage("", "en")).toBe("en");
    expect(pickLanguage("RU", "en")).toBe("en");
  });
});

describe("poolMismatchesLang", () => {
  it.each([
    ["ru", "ru", false],
    ["world", "en", false],
    ["world", "ru", true],
    ["ru", "en", true],
  ] as const)("pool %s + lang %s -> %s", (pool, lang, expected) => {
    expect(poolMismatchesLang(pool, lang)).toBe(expected);
  });
});
