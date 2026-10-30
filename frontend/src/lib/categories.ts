import type { CategoryPref } from "./api";
import { translate } from "./i18n";
import type { Lang } from "./locale";

type CategoryId = Pick<CategoryPref, "kind" | "key">;

export function categoryId(c: CategoryId): string {
  return `${c.kind}:${c.key}`;
}

/** Categories the rule moved down in the feed right now. */
export function hiddenCategories(prefs: CategoryPref[]): CategoryPref[] {
  return prefs.filter((c) => !c.show);
}

/** «вы дизлайкнули 5 из 5» */
export function categoryCount(lang: Lang, c: CategoryPref): string {
  return translate(lang)("categories.count", { n: c.disliked, total: c.rated });
}

/** One banner entry: «Marvel Studios — вы дизлайкнули 5 из 5». */
export function categoryLine(lang: Lang, c: CategoryPref): string {
  return `${c.name} — ${categoryCount(lang, c)}`;
}

/**
 * The whole banner text: «Опустили ниже: Marvel Studios — вы дизлайкнули 5 из 5 · Анимация —
 * 6 из 6». `null` when the rule hides nothing.
 */
export function bannerText(lang: Lang, prefs: CategoryPref[]): string | null {
  const hidden = hiddenCategories(prefs);
  if (hidden.length === 0) return null;
  const lines = hidden.map((c) => categoryLine(lang, c)).join(" · ");
  return `${translate(lang)("categories.banner")} ${lines}`;
}

/** The list after the user chose `show` for a category (the optimistic update). */
export function withShow(
  prefs: CategoryPref[],
  id: CategoryId,
  show: boolean,
): CategoryPref[] {
  return prefs.map((c) =>
    categoryId(c) === categoryId(id) ? { ...c, show } : c,
  );
}
