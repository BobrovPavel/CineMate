const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    throw new ApiError(
      response.status,
      `Запрос ${path} завершился ошибкой ${response.status}`,
    );
  }
  return (await response.json()) as T;
}

export type OnboardingCard = {
  movie_id: number;
  title: string;
  title_ru: string | null;
  year: number | null;
  poster_path: string | null;
  genres: string[];
};

export type WriteResult = { ok: boolean; rated_count: number };

export const TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500";

export function openSession(): Promise<{ user_id: number }> {
  return apiFetch("/api/session", { method: "POST" });
}

export function fetchOnboarding(limit = 20): Promise<OnboardingCard[]> {
  return apiFetch(`/api/onboarding?limit=${limit}`);
}

export function postRating(
  movieId: number,
  value: 1 | -1,
): Promise<WriteResult> {
  return apiFetch("/api/ratings", {
    method: "POST",
    body: JSON.stringify({ movie_id: movieId, value }),
  });
}

export function postNotSeen(movieId: number): Promise<WriteResult> {
  return apiFetch("/api/seen", {
    method: "POST",
    body: JSON.stringify({ movie_id: movieId, type: "not_seen" }),
  });
}

export type RecommendationItem = {
  movie: {
    id: number;
    title: string;
    title_ru: string | null;
    year: number | null;
    poster_path: string | null;
    genres: string[];
  };
  score: number;
  liked_by: number;
  because_of: { movie_id: number; title: string; title_ru: string | null }[];
  because_taste: { kind: string; id: string; name: string } | null;
};

export type RecommendationsResponse = {
  strategy: "collaborative" | "fallback";
  session_id: string;
  items: RecommendationItem[];
};

export type SeenType = "not_seen" | "watched" | "not_interested";

export function fetchRecommendations(
  limit = 20,
): Promise<RecommendationsResponse> {
  return apiFetch(`/api/recommendations?limit=${limit}`);
}

export function postReactionRating(
  movieId: number,
  value: 1 | -1,
  sessionId: string,
): Promise<WriteResult> {
  return apiFetch("/api/ratings", {
    method: "POST",
    body: JSON.stringify({ movie_id: movieId, value, session_id: sessionId }),
  });
}

export function postReactionSeen(
  movieId: number,
  type: SeenType,
  sessionId: string,
): Promise<WriteResult> {
  return apiFetch("/api/seen", {
    method: "POST",
    body: JSON.stringify({ movie_id: movieId, type, session_id: sessionId }),
  });
}

export type ProfileItem = {
  movie_id: number;
  title: string;
  title_ru: string | null;
  year: number | null;
  poster_path: string | null;
  value: 1 | -1;
};

export type Me = { user_id: number; pool: "ru" | "world"; rated_count: number };

export function fetchMe(): Promise<Me> {
  return apiFetch("/api/me");
}

export function resetSession(): Promise<{
  user_id: number;
  pool: "ru" | "world";
}> {
  return apiFetch("/api/session/reset", { method: "POST" });
}

export function fetchProfile(): Promise<ProfileItem[]> {
  return apiFetch("/api/profile");
}

export type SearchResult = {
  tmdb_type: "movie" | "tv";
  tmdb_id: number;
  title: string;
  original_title: string | null;
  year: number | null;
  poster_path: string | null;
  movie_id: number | null;
  user_value: 1 | -1 | null;
};

export function searchMovies(
  query: string,
  signal?: AbortSignal,
): Promise<SearchResult[]> {
  return apiFetch(`/api/search?q=${encodeURIComponent(query)}`, { signal });
}

export function resolveMovie(
  tmdbType: "movie" | "tv",
  tmdbId: number,
): Promise<{ id: number }> {
  return apiFetch("/api/movies/resolve", {
    method: "POST",
    body: JSON.stringify({ tmdb_type: tmdbType, tmdb_id: tmdbId }),
  });
}

export function postWatched(movieId: number): Promise<WriteResult> {
  return apiFetch("/api/seen", {
    method: "POST",
    body: JSON.stringify({ movie_id: movieId, type: "watched" }),
  });
}

export type CategoryKind = "collection" | "studio" | "genre" | "anime";

/** A category the rule moved down (`show` false) or the user chose to show. */
export type CategoryPref = {
  kind: CategoryKind;
  key: string;
  name: string;
  disliked: number;
  rated: number;
  show: boolean;
};

export function fetchCategoryPrefs(): Promise<CategoryPref[]> {
  return apiFetch("/api/category-prefs");
}

export function postCategoryPref(
  kind: CategoryKind,
  key: string,
  show: boolean,
): Promise<WriteResult> {
  return apiFetch("/api/category-prefs", {
    method: "POST",
    body: JSON.stringify({ kind, key, show }),
  });
}

export type RatingSource = {
  source: string;
  label: string;
  value: number;
  scale: "10" | "%";
  votes: number | null;
  url: string | null;
};

export type CastMember = {
  id: number;
  name: string;
  character: string | null;
  profile_path: string | null;
};

export type MovieDetail = {
  id: number;
  title: string;
  title_ru: string | null;
  original_title: string | null;
  year: number | null;
  overview: string | null;
  poster_path: string | null;
  genres: string[];
  runtime: number | null;
  display_title: string;
  second_title: string | null;
  type: "movie" | "tv";
  number_of_seasons: number | null;
  number_of_episodes: number | null;
  tagline: string | null;
  certification: string | null;
  keywords: string[];
  studios: string[];
  countries: string[];
  collection: string | null;
  budget: number | null;
  revenue: number | null;
  directors: { id: number; name: string }[];
  writers: { id: number; name: string }[];
  producers: { id: number; name: string }[];
  composers: { id: number; name: string }[];
  creators: { id: number; name: string }[];
  cast: CastMember[];
  ratings: RatingSource[];
  user_value: 1 | -1 | null;
  user_mark: SeenType | null;
};

export const TMDB_PROFILE_BASE = "https://image.tmdb.org/t/p/w185";

export function fetchMovie(id: number): Promise<MovieDetail> {
  return apiFetch(`/api/movies/${id}`);
}
