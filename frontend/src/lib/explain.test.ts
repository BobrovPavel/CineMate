import { describe, expect, it } from "vitest";

import { explainCollaborative } from "./explain";

describe("explainCollaborative (ru)", () => {
  it("без because_of — только число людей", () => {
    expect(explainCollaborative("ru", 5, [])).toBe(
      "Понравилось 5 людям с похожим вкусом",
    );
  });

  it("склоняет «человеку» в тексте", () => {
    expect(explainCollaborative("ru", 1, [])).toBe(
      "Понравилось 1 человеку с похожим вкусом",
    );
    expect(explainCollaborative("ru", 21, [])).toBe(
      "Понравилось 21 человеку с похожим вкусом",
    );
    expect(explainCollaborative("ru", 11, [])).toBe(
      "Понравилось 11 людям с похожим вкусом",
    );
  });

  it("одно название", () => {
    expect(explainCollaborative("ru", 2, ["Матрица"])).toBe(
      "Понравилось 2 людям с похожим вкусом; они же высоко оценили «Матрица»",
    );
  });

  it("два названия соединяются через «и»", () => {
    expect(explainCollaborative("ru", 3, ["А", "Б"])).toBe(
      "Понравилось 3 людям с похожим вкусом; они же высоко оценили «А» и «Б»",
    );
  });

  it("берёт не больше трёх названий", () => {
    expect(explainCollaborative("ru", 7, ["А", "Б", "В", "Г"])).toBe(
      "Понравилось 7 людям с похожим вкусом; они же высоко оценили «А», «Б» и «В»",
    );
  });
});

describe("explainCollaborative (en)", () => {
  it("singular and plural", () => {
    expect(explainCollaborative("en", 1, [])).toBe(
      "Liked by 1 person with similar taste",
    );
    expect(explainCollaborative("en", 5, [])).toBe(
      "Liked by 5 people with similar taste",
    );
  });

  it("one title", () => {
    expect(explainCollaborative("en", 2, ["Matrix"])).toBe(
      "Liked by 2 people with similar taste; they also rated «Matrix» highly",
    );
  });

  it("joins up to three titles with 'and'", () => {
    expect(explainCollaborative("en", 7, ["A", "B", "C", "D"])).toBe(
      "Liked by 7 people with similar taste; they also rated «A», «B» and «C» highly",
    );
  });
});
