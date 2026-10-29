import { describe, expect, it } from "vitest";

import { format, MESSAGES, plural, translate } from "./i18n";

describe("MESSAGES", () => {
  it("наборы ключей ru и en совпадают", () => {
    expect(Object.keys(MESSAGES.en).sort()).toEqual(
      Object.keys(MESSAGES.ru).sort(),
    );
  });

  it("нет пустых значений", () => {
    for (const lang of ["ru", "en"] as const) {
      for (const [key, value] of Object.entries(MESSAGES[lang])) {
        expect(value, `${lang}:${key}`).not.toBe("");
      }
    }
  });

  it("плейсхолдеры совпадают в ru и en", () => {
    const names = (s: string) =>
      [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();
    for (const key of Object.keys(
      MESSAGES.ru,
    ) as (keyof typeof MESSAGES.ru)[]) {
      expect(names(MESSAGES.en[key]), key).toEqual(names(MESSAGES.ru[key]));
    }
  });
});

describe("plural", () => {
  it.each([
    [1, "фильм"],
    [2, "фильма"],
    [4, "фильма"],
    [5, "фильмов"],
    [11, "фильмов"],
    [12, "фильмов"],
    [21, "фильм"],
    [22, "фильма"],
    [25, "фильмов"],
    [101, "фильм"],
    [111, "фильмов"],
  ])("ru %i -> %s", (n, expected) => {
    expect(plural("ru", "movie", n)).toBe(expected);
  });

  it.each([
    [1, "movie"],
    [2, "movies"],
    [5, "movies"],
    [21, "movies"],
  ])("en %i -> %s", (n, expected) => {
    expect(plural("en", "movie", n)).toBe(expected);
  });

  it("человеку / людям", () => {
    expect(plural("ru", "people", 1)).toBe("человеку");
    expect(plural("ru", "people", 21)).toBe("человеку");
    expect(plural("ru", "people", 2)).toBe("людям");
    expect(plural("ru", "people", 11)).toBe("людям");
  });
});

describe("translate", () => {
  it("подставляет значения", () => {
    expect(
      translate("en")("onboarding.progress", { current: 2, total: 20 }),
    ).toBe("2 of 20");
    expect(
      translate("ru")("onboarding.progress", { current: 2, total: 20 }),
    ).toBe("2 из 20");
  });

  it("неизвестный плейсхолдер остаётся как есть", () => {
    expect(format("a {x} {y}", { x: 1 })).toBe("a 1 {y}");
  });
});
