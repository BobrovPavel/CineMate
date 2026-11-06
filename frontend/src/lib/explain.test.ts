import { describe, expect, it } from "vitest";

import {
  collectionLine,
  explainCollaborative,
  explainNextPart,
  explainTaste,
  explainTwin,
} from "./explain";

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

describe("explainTaste", () => {
  it("говорит о вкусе на двух языках", () => {
    expect(explainTaste("ru", "фэнтези")).toBe("Вы часто лайкаете фэнтези");
    expect(explainTaste("en", "fantasy")).toBe("You often like fantasy");
  });
});

describe("explainTwin", () => {
  it("называет только числа на двух языках", () => {
    expect(explainTwin("ru", 8, 10)).toBe(
      "Понравилось зрителю, у которого совпало 8 из 10 ваших лайков",
    );
    expect(explainTwin("en", 8, 10)).toBe(
      "Liked by a viewer who shares 8 of your 10 likes",
    );
  });
});

describe("explainNextPart", () => {
  it("перечисляет оценённые части на двух языках", () => {
    expect(explainNextPart("ru", [1, 2])).toBe(
      "Следующая часть: вы оценили части 1 и 2",
    );
    expect(explainNextPart("en", [1, 2, 3])).toBe(
      "Next part: you rated parts 1, 2 and 3",
    );
  });

  it("одна часть — в единственном числе", () => {
    expect(explainNextPart("ru", [1])).toBe(
      "Следующая часть: вы оценили часть 1",
    );
    expect(explainNextPart("en", [2])).toBe("Next part: you rated part 2");
  });
});

describe("collectionLine", () => {
  it("строка франшизы на двух языках", () => {
    expect(collectionLine("ru", "Гарри Поттер", 8)).toBe(
      "Серия «Гарри Поттер» · 8 фильмов",
    );
    expect(collectionLine("en", "Harry Potter Collection", 8)).toBe(
      "Harry Potter Collection · 8 films",
    );
  });

  it("убирает слово «коллекция» из названия TMDB", () => {
    expect(collectionLine("ru", "Гарри Поттер (коллекция)", 2)).toBe(
      "Серия «Гарри Поттер» · 2 фильма",
    );
    expect(collectionLine("en", "Saga", 1)).toBe("Saga Collection · 1 film");
  });
});
