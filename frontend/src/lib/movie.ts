import type { Lang } from "./locale";
import type { MessageKey, Translate } from "./i18n";
import { plural } from "./i18n";

export type PersonRef = { id: number; name: string };

/** The fields of the movie page that feed the facts list. */
export type FactsSource = {
  type: "movie" | "tv";
  year: number | null;
  runtime: number | null;
  number_of_seasons: number | null;
  number_of_episodes: number | null;
  budget: number | null;
  revenue: number | null;
  genres: string[];
  studios: string[];
  countries: string[];
  directors: PersonRef[];
  writers: PersonRef[];
  producers: PersonRef[];
  composers: PersonRef[];
  creators: PersonRef[];
};

export type Fact = { key: MessageKey; value: string };

/** Money in US dollars (the currency TMDB reports), no fraction digits. */
export function formatMoney(amount: number, lang: Lang): string {
  return new Intl.NumberFormat(lang, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(amount);
}

/** "2 h 5 min" / "2 ч 5 мин"; ``null`` for an unknown or non-positive runtime. */
export function formatRuntime(minutes: number | null, t: Translate): string | null {
  if (!minutes || minutes <= 0) return null;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (hours === 0) return t("movie.minutes", { n: rest });
  if (rest === 0) return t("movie.hours", { n: hours });
  return `${t("movie.hours", { n: hours })} ${t("movie.minutes", { n: rest })}`;
}

/** "3 seasons, 30 episodes"; either part may be missing; ``null`` when both are. */
export function formatSeasons(
  seasons: number | null,
  episodes: number | null,
  lang: Lang,
): string | null {
  const parts: string[] = [];
  if (seasons && seasons > 0) parts.push(`${seasons} ${plural(lang, "season", seasons)}`);
  if (episodes && episodes > 0) parts.push(`${episodes} ${plural(lang, "episode", episodes)}`);
  return parts.length > 0 ? parts.join(", ") : null;
}

/** Country names in the interface language; an unknown code stays as it is. */
export function countryNames(codes: string[], lang: Lang): string[] {
  let names: Intl.DisplayNames | null = null;
  try {
    names = new Intl.DisplayNames([lang], { type: "region" });
  } catch {
    // Unsupported environment: show the codes.
  }
  return codes.map((code) => {
    try {
      return names?.of(code) ?? code;
    } catch {
      return code;
    }
  });
}

const joinNames = (people: PersonRef[]) => people.map((p) => p.name).join(", ");

/** The facts rows in the order of the design; rows without data are left out. */
export function factRows(movie: FactsSource, lang: Lang, t: Translate): Fact[] {
  const isTv = movie.type === "tv";
  const duration = isTv
    ? formatSeasons(movie.number_of_seasons, movie.number_of_episodes, lang)
    : formatRuntime(movie.runtime, t);
  const rows: [MessageKey, string | null][] = isTv
    ? [["movie.creators", joinNames(movie.creators)]]
    : [
        ["movie.director", joinNames(movie.directors)],
        ["movie.writer", joinNames(movie.writers)],
        ["movie.producer", joinNames(movie.producers)],
        ["movie.composer", joinNames(movie.composers)],
      ];
  rows.push(
    ["movie.studio", movie.studios.join(", ")],
    ["movie.country", countryNames(movie.countries, lang).join(", ")],
    ["movie.year", movie.year ? String(movie.year) : null],
    ["movie.budget", !isTv && movie.budget ? formatMoney(movie.budget, lang) : null],
    ["movie.revenue", !isTv && movie.revenue ? formatMoney(movie.revenue, lang) : null],
    ["movie.format", t(isTv ? "movie.formatTv" : "movie.formatMovie")],
    ["movie.genres", movie.genres.join(", ")],
    [isTv ? "movie.seasons" : "movie.duration", duration],
  );
  return rows.filter((r): r is [MessageKey, string] => Boolean(r[1])).map(([key, value]) => ({ key, value }));
}

/** Genres first, then keywords, without repeats (case-insensitive). */
export function pillLabels(genres: string[], keywords: string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const label of [...genres, ...keywords]) {
    const key = label.trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(label.trim());
  }
  return result;
}

export type ScrollState = { scrollLeft: number; clientWidth: number; scrollWidth: number };

/** Which arrows of a horizontally scrolling row are useful (1px tolerance for rounding). */
export function arrowState(s: ScrollState): { left: boolean; right: boolean } {
  return {
    left: s.scrollLeft > 1,
    right: s.scrollLeft + s.clientWidth < s.scrollWidth - 1,
  };
}

/** The scrollLeft to move one page (90% of the visible width) left or right, kept in range. */
export function nextScrollLeft(s: ScrollState, direction: -1 | 1): number {
  const target = s.scrollLeft + direction * s.clientWidth * 0.9;
  return Math.max(0, Math.min(target, Math.max(0, s.scrollWidth - s.clientWidth)));
}

/** Where "Back" goes: the browser history when there is any, else the feed. */
export function backTarget(historyLength: number): "history" | "feed" {
  return historyLength > 1 ? "history" : "feed";
}
