import type { CategoryMovie, CategoryPref } from "./api";
import { translate } from "./i18n";
import type { Lang } from "./locale";

type CategoryId = Pick<CategoryPref, "kind" | "key">;

export function categoryId(c: CategoryId): string {
  return `${c.kind}:${c.key}`;
}

/** «вы дизлайкнули 5 из 5» */
export function categoryCount(lang: Lang, c: CategoryPref): string {
  return translate(lang)("categories.count", { n: c.disliked, total: c.rated });
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

/**
 * What the user sees for a category: `shown` (override on), `hidden` (the rule lowers it) or
 * `lifted` (a like appeared, so the rule no longer applies; the override is not needed).
 */
export type CategoryState = "shown" | "hidden" | "lifted";

export function categoryState(c: CategoryPref): CategoryState {
  if (c.show) return "shown";
  return c.disliked < c.rated ? "lifted" : "hidden";
}

/** The movie list is fetched on the first expansion only, never while loading or loaded. */
export function shouldLoadMovies(
  expanded: boolean,
  loaded: boolean,
  loading: boolean,
): boolean {
  return expanded && !loaded && !loading;
}

/** `[...open]` with `id` toggled; does not mutate. */
export function toggleOpen(open: ReadonlySet<string>, id: string): Set<string> {
  const next = new Set(open);
  if (!next.delete(id)) next.add(id);
  return next;
}

/** The movie list after the user changed one rating (no mutation). */
export function withMovieValue(
  movies: CategoryMovie[],
  movieId: number,
  value: 1 | -1,
): CategoryMovie[] {
  return movies.map((m) => (m.movie_id === movieId ? { ...m, value } : m));
}

/** Counts «N из N» after a rating moved from `from` to `to`; unchanged when equal. */
export function withRatingChange(
  prefs: CategoryPref[],
  id: CategoryId,
  from: 1 | -1,
  to: 1 | -1,
): CategoryPref[] {
  if (from === to) return prefs;
  const delta = to === -1 ? 1 : -1;
  return prefs.map((c) =>
    categoryId(c) === categoryId(id)
      ? { ...c, disliked: Math.max(0, Math.min(c.rated, c.disliked + delta)) }
      : c,
  );
}
