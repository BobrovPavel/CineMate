import type { SearchResult } from "./api";

export const SEARCH_DEBOUNCE_MS = 300;
export const MIN_QUERY_LENGTH = 2;
export const MAX_QUERY_LENGTH = 100;

/** Query sent to the API: trimmed, inner whitespace collapsed, capped at the API limit. */
export function normalizeQuery(raw: string): string {
  return raw.trim().replace(/\s+/g, " ").slice(0, MAX_QUERY_LENGTH);
}

export function isSearchable(raw: string): boolean {
  return normalizeQuery(raw).length >= MIN_QUERY_LENGTH;
}

/** Stable key of a result: TMDB movie and tv ids live in different spaces. */
export function resultKey(item: Pick<SearchResult, "tmdb_type" | "tmdb_id">): string {
  return `${item.tmdb_type}:${item.tmdb_id}`;
}

/** Copy of ``results`` with the item ``key`` linked to our movie and/or given a new rating. */
export function updateResult(
  results: SearchResult[],
  key: string,
  patch: Partial<Pick<SearchResult, "movie_id" | "user_value">>,
): SearchResult[] {
  return results.map((r) => (resultKey(r) === key ? { ...r, ...patch } : r));
}

export function ratingLabel(value: 1 | -1 | null): string | null {
  if (value === 1) return "Нравится";
  if (value === -1) return "Не нравится";
  return null;
}
