import { describe, expect, it } from "vitest";

import { explainCollaborative, pluralPeople } from "./explain";

describe("pluralPeople", () => {
  it.each([
    [1, "человеку"],
    [21, "человеку"],
    [101, "человеку"],
    [2, "людям"],
    [4, "людям"],
    [5, "людям"],
    [11, "людям"],
    [12, "людям"],
    [14, "людям"],
    [22, "людям"],
    [25, "людям"],
    [111, "людям"],
  ])("%i -> %s", (n, expected) => {
    expect(pluralPeople(n)).toBe(expected);
  });
});

describe("explainCollaborative", () => {
  it("без because_of — только число людей", () => {
    expect(explainCollaborative(5, [])).toBe("Понравилось 5 людям с похожим вкусом");
  });

  it("склоняет «человеку» в тексте", () => {
    expect(explainCollaborative(1, [])).toBe("Понравилось 1 человеку с похожим вкусом");
  });

  it("одно название", () => {
    expect(explainCollaborative(2, ["Матрица"])).toBe(
      "Понравилось 2 людям с похожим вкусом; они же высоко оценили «Матрица»",
    );
  });

  it("два названия соединяются через «и»", () => {
    expect(explainCollaborative(3, ["А", "Б"])).toBe(
      "Понравилось 3 людям с похожим вкусом; они же высоко оценили «А» и «Б»",
    );
  });

  it("берёт не больше трёх названий", () => {
    expect(explainCollaborative(7, ["А", "Б", "В", "Г"])).toBe(
      "Понравилось 7 людям с похожим вкусом; они же высоко оценили «А», «Б» и «В»",
    );
  });
});
