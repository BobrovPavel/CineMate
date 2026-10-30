import { describe, expect, it } from "vitest";

import { translate } from "./i18n";
import {
  arrowState,
  backTarget,
  countryNames,
  factRows,
  formatMoney,
  formatRuntime,
  formatSeasons,
  nextScrollLeft,
  pillLabels,
  type FactsSource,
} from "./movie";

const en = translate("en");
const ru = translate("ru");

const person = (name: string) => ({ id: 1, name });
const base: FactsSource = {
  type: "movie",
  year: 2014,
  runtime: 140,
  number_of_seasons: null,
  number_of_episodes: null,
  budget: 4_400_000,
  revenue: 0,
  genres: ["Drama"],
  studios: ["Studio A"],
  countries: ["RU"],
  directors: [person("Dir")],
  writers: [],
  producers: [],
  composers: [],
  creators: [],
};

describe("formatMoney", () => {
  it("доллары без копеек", () => {
    expect(formatMoney(4_400_000, "en")).toBe("$4,400,000");
    expect(formatMoney(4_400_000, "ru")).toContain("4");
    expect(formatMoney(4_400_000, "ru")).toContain("$");
  });
});

describe("formatRuntime", () => {
  it.each([
    [140, "2 h 20 min"],
    [120, "2 h"],
    [45, "45 min"],
  ])("%i мин", (minutes, expected) => {
    expect(formatRuntime(minutes, en)).toBe(expected);
  });

  it("ru", () => {
    expect(formatRuntime(95, ru)).toBe("1 ч 35 мин");
  });

  it.each([null, 0, -5])("нет данных: %s", (minutes) => {
    expect(formatRuntime(minutes, en)).toBeNull();
  });
});

describe("formatSeasons", () => {
  it("ru склоняет", () => {
    expect(formatSeasons(1, 8, "ru")).toBe("1 сезон, 8 серий");
    expect(formatSeasons(3, 22, "ru")).toBe("3 сезона, 22 серии");
    expect(formatSeasons(5, 21, "ru")).toBe("5 сезонов, 21 серия");
  });

  it("en", () => {
    expect(formatSeasons(1, 1, "en")).toBe("1 season, 1 episode");
    expect(formatSeasons(2, 20, "en")).toBe("2 seasons, 20 episodes");
  });

  it("одна из частей", () => {
    expect(formatSeasons(3, null, "en")).toBe("3 seasons");
    expect(formatSeasons(null, 10, "en")).toBe("10 episodes");
  });

  it("нет данных", () => {
    expect(formatSeasons(null, null, "en")).toBeNull();
    expect(formatSeasons(0, 0, "en")).toBeNull();
  });
});

describe("countryNames", () => {
  it("название на языке интерфейса", () => {
    expect(countryNames(["RU"], "en")).toEqual(["Russia"]);
    expect(countryNames(["RU"], "ru")).toEqual(["Россия"]);
  });

  it("неизвестный код остаётся как есть", () => {
    expect(countryNames(["??"], "en")).toEqual(["??"]);
  });
});

describe("factRows", () => {
  const keys = (rows: ReturnType<typeof factRows>) => rows.map((r) => r.key);

  it("строки без данных не показываются", () => {
    expect(keys(factRows(base, "en", en))).toEqual([
      "movie.director",
      "movie.studio",
      "movie.country",
      "movie.year",
      "movie.budget",
      "movie.format",
      "movie.genres",
      "movie.duration",
    ]);
  });

  it("значения", () => {
    const rows = factRows(base, "en", en);
    expect(rows.find((r) => r.key === "movie.budget")?.value).toBe("$4,400,000");
    expect(rows.find((r) => r.key === "movie.duration")?.value).toBe("2 h 20 min");
    expect(rows.find((r) => r.key === "movie.format")?.value).toBe("Movie");
  });

  it("сериал: создатели и сезоны, без бюджета и режиссёра", () => {
    const tv: FactsSource = {
      ...base,
      type: "tv",
      creators: [person("A"), person("B")],
      directors: [person("Dir")],
      number_of_seasons: 2,
      number_of_episodes: 20,
      budget: 5,
      revenue: 6,
    };
    const rows = factRows(tv, "en", en);
    expect(rows.map((r) => r.key)).toEqual([
      "movie.creators",
      "movie.studio",
      "movie.country",
      "movie.year",
      "movie.format",
      "movie.genres",
      "movie.seasons",
    ]);
    expect(rows[0].value).toBe("A, B");
    expect(rows.at(-1)?.value).toBe("2 seasons, 20 episodes");
  });

  it("пустой фильм показывает только формат", () => {
    const empty: FactsSource = {
      ...base,
      year: null,
      runtime: null,
      budget: null,
      genres: [],
      studios: [],
      countries: [],
      directors: [],
    };
    expect(keys(factRows(empty, "ru", ru))).toEqual(["movie.format"]);
  });
});

describe("pillLabels", () => {
  it("жанры, затем теги, без повторов", () => {
    expect(pillLabels(["Drama", "Epic"], ["epic", " Dark Fantasy ", ""])).toEqual([
      "Drama",
      "Epic",
      "Dark Fantasy",
    ]);
  });
});

describe("прокрутка пилюль", () => {
  const row = { scrollLeft: 0, clientWidth: 300, scrollWidth: 1000 };

  it("стрелки по краям", () => {
    expect(arrowState(row)).toEqual({ left: false, right: true });
    expect(arrowState({ ...row, scrollLeft: 400 })).toEqual({ left: true, right: true });
    expect(arrowState({ ...row, scrollLeft: 700 })).toEqual({ left: true, right: false });
  });

  it("всё помещается: стрелок нет", () => {
    expect(arrowState({ scrollLeft: 0, clientWidth: 300, scrollWidth: 300 })).toEqual({
      left: false,
      right: false,
    });
  });

  it("шаг в 90% ширины в пределах ряда", () => {
    expect(nextScrollLeft(row, 1)).toBe(270);
    expect(nextScrollLeft({ ...row, scrollLeft: 600 }, 1)).toBe(700);
    expect(nextScrollLeft({ ...row, scrollLeft: 100 }, -1)).toBe(0);
    expect(nextScrollLeft({ ...row, scrollLeft: 500 }, -1)).toBe(230);
  });
});

describe("backTarget", () => {
  it("история есть — назад, иначе лента", () => {
    expect(backTarget(3)).toBe("history");
    expect(backTarget(1)).toBe("feed");
  });
});
