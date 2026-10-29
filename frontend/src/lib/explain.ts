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
