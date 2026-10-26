import { describe, expect, it } from "vitest";

import { displayTitle } from "./titles";

const movie = { title: "Home Alone", title_ru: "Один дома" };

describe("displayTitle", () => {
  it("ru: русское название, оригинал ниже", () => {
    expect(displayTitle(movie, "ru")).toEqual({ primary: "Один дома", secondary: "Home Alone" });
  });

  it("ru-RU и регистр не важны", () => {
    expect(displayTitle(movie, "ru-RU").primary).toBe("Один дома");
    expect(displayTitle(movie, "RU").primary).toBe("Один дома");
  });

  it("en-US: только оригинал", () => {
    expect(displayTitle(movie, "en-US")).toEqual({ primary: "Home Alone", secondary: null });
  });

  it("нет title_ru: только оригинал", () => {
    expect(displayTitle({ title: "Alien", title_ru: null }, "ru")).toEqual({
      primary: "Alien",
      secondary: null,
    });
    expect(displayTitle({ title: "Alien", title_ru: "" }, "ru").secondary).toBeNull();
  });

  it("названия совпадают: без secondary", () => {
    expect(displayTitle({ title: "Аватар", title_ru: "Аватар" }, "ru")).toEqual({
      primary: "Аватар",
      secondary: null,
    });
  });
});
