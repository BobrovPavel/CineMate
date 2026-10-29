import { describe, expect, it } from "vitest";

import type { SearchResult } from "./api";
import {
  isSearchable,
  normalizeQuery,
  ratingKey,
  resultKey,
  updateResult,
} from "./search";

const base: SearchResult = {
  tmdb_type: "movie",
  tmdb_id: 10,
  title: "A",
  original_title: null,
  year: 2014,
  poster_path: null,
  movie_id: null,
  user_value: null,
};

describe("normalizeQuery", () => {
  it("обрезает и схлопывает пробелы", () => {
    expect(normalizeQuery("  Игра   престолов ")).toBe("Игра престолов");
  });

  it("ограничивает длину 100 символами", () => {
    expect(normalizeQuery("x".repeat(150))).toHaveLength(100);
  });
});

describe("isSearchable", () => {
  it("нужно минимум 2 символа без учёта пробелов по краям", () => {
    expect(isSearchable("")).toBe(false);
    expect(isSearchable(" a ")).toBe(false);
    expect(isSearchable("ab")).toBe(true);
  });
});

describe("resultKey", () => {
  it("различает фильм и сериал с одним id", () => {
    expect(resultKey({ tmdb_type: "movie", tmdb_id: 1 })).not.toBe(
      resultKey({ tmdb_type: "tv", tmdb_id: 1 }),
    );
  });
});

describe("updateResult", () => {
  it("меняет только нужный элемент и не мутирует исходный массив", () => {
    const tv = { ...base, tmdb_type: "tv" as const };
    const input = [base, tv];
    const out = updateResult(input, resultKey(tv), {
      movie_id: 5,
      user_value: 1,
    });
    expect(out[0]).toBe(base);
    expect(out[1]).toMatchObject({ movie_id: 5, user_value: 1 });
    expect(input[1].movie_id).toBeNull();
  });
});

describe("ratingKey", () => {
  it("ключи подписей оценок", () => {
    expect(ratingKey(1)).toBe("reaction.like");
    expect(ratingKey(-1)).toBe("reaction.dislike");
    expect(ratingKey(null)).toBeNull();
  });
});
