import { describe, expect, it } from "vitest";

import { explainCollaborative, pluralPeople } from "./explain";

describe("pluralPeople", () => {
  it.each([
    [1, "человеку"],
    [21, "человеку"],
    [22, "людям"],
    [2, "людям"],
    [4, "людям"],
    [5, "людям"],
    [11, "людям"],
    [12, "людям"],
    [14, "людям"],
    [25, "людям"],
  ])("%i -> %s", (n, expected) => {
    expect(pluralPeople(n)).toBe(expected);
  });
});

describe("explainCollaborative", () => {
  it("без because_of — только счётчик", () => {
    expect(explainCollaborative(1, [])).toBe("Понравилось 1 человеку с похожим вкусом");
  });

  it("одно название", () => {
    expect(explainCollaborative(5, ["Матрица"])).toBe(
      "Понравилось 5 людям с похожим вкусом; они же высоко оценили «Матрица»",
    );
  });

  it("два названия соединяются через «и»", () => {
    expect(explainCollaborative(2, ["А", "Б"])).toContain("оценили «А» и «Б»");
  });

  it("берёт не больше трёх названий", () => {
    const text = explainCollaborative(21, ["А", "Б", "В", "Г"]);
    expect(text).toBe(
      "Понравилось 21 человеку с похожим вкусом; они же высоко оценили «А», «Б» и «В»",
    );
    expect(text).not.toContain("«Г»");
  });
});
