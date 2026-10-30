import { describe, expect, it } from "vitest";

import type { CategoryPref } from "./api";
import {
  bannerText,
  categoryCount,
  categoryId,
  hiddenCategories,
  withShow,
} from "./categories";

const marvel: CategoryPref = {
  kind: "studio",
  key: "420",
  name: "Marvel Studios",
  disliked: 5,
  rated: 5,
  show: false,
};
const animation: CategoryPref = {
  kind: "genre",
  key: "16",
  name: "Анимация",
  disliked: 6,
  rated: 6,
  show: false,
};
const shown: CategoryPref = { ...animation, key: "35", show: true };

describe("bannerText", () => {
  it("перечисляет скрытые категории с числами «N из N»", () => {
    expect(bannerText("ru", [marvel, animation])).toBe(
      "Опустили ниже: Marvel Studios — вы дизлайкнули 5 из 5 · Анимация — вы дизлайкнули 6 из 6",
    );
  });

  it("на английском", () => {
    expect(bannerText("en", [marvel])).toBe(
      "Moved down: Marvel Studios — you disliked 5 of 5",
    );
  });

  it("не показывает категории, которые пользователь вернул", () => {
    expect(bannerText("ru", [shown])).toBeNull();
    expect(bannerText("ru", [shown, marvel])).toContain("Marvel Studios");
    expect(bannerText("ru", [shown, marvel])).not.toContain("Анимация");
  });

  it("без категорий плашки нет", () => {
    expect(bannerText("ru", [])).toBeNull();
  });
});

describe("categories helpers", () => {
  it("categoryCount", () => {
    expect(categoryCount("ru", marvel)).toBe("вы дизлайкнули 5 из 5");
  });

  it("hiddenCategories оставляет только скрытые", () => {
    expect(hiddenCategories([marvel, shown])).toEqual([marvel]);
  });

  it("categoryId различает вид и ключ", () => {
    expect(categoryId(marvel)).toBe("studio:420");
    expect(categoryId(animation)).not.toBe(categoryId(shown));
  });

  it("withShow меняет только выбранную категорию и не мутирует список", () => {
    const list = [marvel, animation];
    const next = withShow(list, marvel, true);
    expect(next.map((c) => c.show)).toEqual([true, false]);
    expect(list[0].show).toBe(false);
    expect(withShow(next, marvel, false)).toEqual(list);
  });
});
