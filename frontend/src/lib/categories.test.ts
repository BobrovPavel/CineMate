import { describe, expect, it } from "vitest";

import type { CategoryMovie, CategoryPref } from "./api";
import {
  categoryCount,
  categoryId,
  categoryState,
  shouldLoadMovies,
  toggleOpen,
  withMovieValue,
  withRatingChange,
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

describe("categories helpers", () => {
  it("categoryCount", () => {
    expect(categoryCount("ru", marvel)).toBe("вы дизлайкнули 5 из 5");
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

describe("раскрытие категории", () => {
  it("список грузится только при первом раскрытии", () => {
    expect(shouldLoadMovies(false, false, false)).toBe(false);
    expect(shouldLoadMovies(true, false, false)).toBe(true);
    expect(shouldLoadMovies(true, true, false)).toBe(false);
    expect(shouldLoadMovies(true, false, true)).toBe(false);
  });

  it("toggleOpen открывает и закрывает, не мутируя набор", () => {
    const open = new Set<string>();
    const opened = toggleOpen(open, "studio:420");
    expect([...opened]).toEqual(["studio:420"]);
    expect(open.size).toBe(0);
    expect(toggleOpen(opened, "studio:420").size).toBe(0);
  });
});

describe("смена оценки в категории", () => {
  const movie = (id: number, value: 1 | -1): CategoryMovie => ({
    movie_id: id,
    title: `m${id}`,
    title_ru: null,
    year: null,
    poster_path: null,
    value,
  });

  it("withMovieValue меняет только выбранный фильм", () => {
    const list = [movie(1, -1), movie(2, -1)];
    const next = withMovieValue(list, 2, 1);
    expect(next.map((m) => m.value)).toEqual([-1, 1]);
    expect(list[1].value).toBe(-1);
  });

  it("лайк уменьшает число дизлайков, «N из N» становится «N-1 из N»", () => {
    const next = withRatingChange([marvel, animation], marvel, -1, 1);
    expect(next[0]).toMatchObject({ disliked: 4, rated: 5 });
    expect(next[1]).toEqual(animation);
  });

  it("возврат дизлайка восстанавливает числа", () => {
    const liked = withRatingChange([marvel], marvel, -1, 1);
    expect(withRatingChange(liked, marvel, 1, -1)).toEqual([marvel]);
  });

  it("та же оценка ничего не меняет, числа не выходят за границы", () => {
    const list = [marvel];
    expect(withRatingChange(list, marvel, -1, -1)).toBe(list);
    const zero = { ...marvel, disliked: 0, rated: 0 };
    expect(withRatingChange([zero], zero, 1, -1)[0].disliked).toBe(0);
  });

  it("лайк в категории снимает правило: состояние lifted", () => {
    expect(categoryState(marvel)).toBe("hidden");
    const [after] = withRatingChange([marvel], marvel, -1, 1);
    expect(categoryState(after)).toBe("lifted");
    expect(categoryState({ ...after, show: true })).toBe("shown");
    expect(categoryState(withShow([marvel], marvel, true)[0])).toBe("shown");
  });
});
