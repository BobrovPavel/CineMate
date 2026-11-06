import { plural, translate } from "./i18n";
import type { Lang } from "./locale";

export function explainCollaborative(
  lang: Lang,
  likedBy: number,
  becauseOf: string[],
): string {
  const t = translate(lang);
  let text = t("explain.liked", {
    n: likedBy,
    people: plural(lang, "people", likedBy),
  });
  const titles = becauseOf.slice(0, 3).map((title) => `«${title}»`);
  if (titles.length > 0) {
    const joined =
      titles.length === 1
        ? titles[0]
        : `${titles.slice(0, -1).join(", ")} ${t("explain.and")} ${titles.at(-1)}`;
    text += t("explain.also", { titles: joined });
  }
  return text;
}

export function explainTaste(lang: Lang, name: string): string {
  return translate(lang)("explain.taste", { name });
}

export function explainTwin(lang: Lang, common: number, of: number): string {
  return translate(lang)("explain.twin", { common, of });
}

/** "Next part: you rated parts 1 and 2": ``rated`` are the 1-based numbers of the seen parts. */
export function explainNextPart(lang: Lang, rated: number[]): string {
  const t = translate(lang);
  const numbers = rated.map(String);
  const parts =
    numbers.length < 2
      ? (numbers[0] ?? "")
      : `${numbers.slice(0, -1).join(", ")} ${t("explain.and")} ${numbers.at(-1)}`;
  return t(numbers.length < 2 ? "explain.nextPart.one" : "explain.nextPart.many", {
    parts,
  });
}

/** The franchise line of a card: "Harry Potter Collection · 8 films". */
export function collectionLine(lang: Lang, name: string, parts: number): string {
  const short = name
    .replace(/\s*\((?:коллекция|collection)\)\s*$/i, "")
    .replace(/\s*[-—–:]?\s*(?:collection|коллекция)\s*$/i, "")
    .trim();
  return translate(lang)("collection.line", {
    name: short || name,
    n: parts,
    films: plural(lang, "film", parts),
  });
}
