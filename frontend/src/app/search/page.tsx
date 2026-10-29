"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import {
  ApiError,
  postRating,
  postWatched,
  resolveMovie,
  searchMovies,
  TMDB_IMAGE_BASE,
  type SearchResult,
} from "@/lib/api";
import {
  isSearchable,
  normalizeQuery,
  ratingKey,
  resultKey,
  SEARCH_DEBOUNCE_MS,
  updateResult,
} from "@/lib/search";
import { displayTitle } from "@/lib/titles";
import { useLocale, useT } from "@/lib/LocaleProvider";

type Status = "idle" | "loading" | "ready" | "unavailable" | "error";
type Action = "like" | "dislike" | "watched";

export default function SearchPage() {
  const router = useRouter();
  const locale = useLocale();
  const t = useT();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [watched, setWatched] = useState<Set<string>>(new Set());
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!isSearchable(query)) {
      setStatus("idle");
      setResults([]);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setStatus("loading");
      try {
        const found = await searchMovies(
          normalizeQuery(query),
          controller.signal,
        );
        setResults(found);
        setStatus("ready");
      } catch (e) {
        if (controller.signal.aborted) return;
        if (e instanceof ApiError && e.status === 401) {
          router.replace("/onboarding");
        } else if (e instanceof ApiError && e.status === 503) {
          setStatus("unavailable");
        } else {
          setStatus("error");
        }
      }
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [query, router]);

  async function act(item: SearchResult, action: Action) {
    const key = resultKey(item);
    if (pending.has(key)) return;
    setMessage(null);
    setPending((s) => new Set(s).add(key));
    try {
      let movieId = item.movie_id;
      if (movieId === null) {
        movieId = (await resolveMovie(item.tmdb_type, item.tmdb_id)).id;
        setResults((prev) => updateResult(prev, key, { movie_id: movieId }));
      }
      if (action === "watched") {
        await postWatched(movieId);
        setWatched((s) => new Set(s).add(key));
      } else {
        const value = action === "like" ? 1 : -1;
        await postRating(movieId, value);
        setResults((prev) => updateResult(prev, key, { user_value: value }));
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/onboarding");
        return;
      }
      setMessage(t("search.saveError"));
    } finally {
      setPending((s) => {
        const copy = new Set(s);
        copy.delete(key);
        return copy;
      });
    }
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-semibold">{t("search.title")}</h1>
      <label htmlFor="search-input" className="sr-only">
        {t("search.label")}
      </label>
      <input
        id="search-input"
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        maxLength={100}
        autoComplete="off"
        placeholder={t("search.label")}
        className="mb-4 min-h-12 w-full rounded-xl border border-gray-300 px-4"
      />

      {message && (
        <div
          role="alert"
          className="mb-4 rounded-xl bg-red-100 p-3 text-sm text-red-900"
        >
          {message}
        </div>
      )}

      {status === "idle" && <p className="text-gray-600">{t("search.hint")}</p>}
      {status === "loading" && (
        <p role="status" aria-busy="true" className="text-gray-600">
          {t("search.searching")}
        </p>
      )}
      {status === "unavailable" && (
        <div
          role="alert"
          className="rounded-xl bg-yellow-100 p-3 text-yellow-900"
        >
          {t("search.unavailable")}
        </div>
      )}
      {status === "error" && (
        <div role="alert" className="rounded-xl bg-red-100 p-3 text-red-900">
          {t("search.error")}
        </div>
      )}
      {status === "ready" && results.length === 0 && <p>{t("search.empty")}</p>}

      {status === "ready" && results.length > 0 && (
        <ul className="flex flex-col gap-4">
          {results.map((item) => {
            const key = resultKey(item);
            const { primary, secondary } = displayTitle(
              { title: item.title, title_ru: null },
              locale,
            );
            const busy = pending.has(key);
            const ratingMessage = ratingKey(item.user_value);
            const current = ratingMessage ? t(ratingMessage) : null;
            const original =
              item.original_title && item.original_title !== item.title
                ? item.original_title
                : secondary;
            return (
              <li key={key} className="flex min-w-0 gap-3">
                <div className="h-24 w-16 shrink-0 overflow-hidden rounded-lg bg-gray-200">
                  {item.poster_path ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={`${TMDB_IMAGE_BASE}${item.poster_path}`}
                      alt={t("poster.alt", { title: primary })}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <div
                      className="flex h-full w-full items-center justify-center p-1 text-center text-xs text-gray-500"
                      role="img"
                      aria-label={t("poster.missing")}
                    >
                      {t("poster.none")}
                    </div>
                  )}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <h2 className="font-semibold break-words">{primary}</h2>
                  {original && (
                    <p className="text-sm break-words text-gray-600">
                      ({original})
                    </p>
                  )}
                  <p className="text-sm text-gray-600">
                    {[
                      item.year,
                      item.tmdb_type === "tv" ? t("search.tv") : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </p>
                  {(current || watched.has(key)) && (
                    <p className="text-sm font-medium text-gray-900">
                      {[current, watched.has(key) ? t("search.watched") : null]
                        .filter(Boolean)
                        .join(" · ")}
                    </p>
                  )}
                  <div className="mt-1 flex flex-wrap gap-2">
                    {(
                      [
                        ["like", "reaction.like"],
                        ["dislike", "reaction.dislike"],
                        ["watched", "search.watched"],
                      ] as const
                    ).map(([action, labelKey]) => (
                      <button
                        key={action}
                        type="button"
                        disabled={busy}
                        onClick={() => void act(item, action)}
                        aria-label={`${t(labelKey)}: «${primary}»`}
                        className="min-h-11 rounded-xl bg-gray-200 px-3 text-sm text-gray-900 disabled:opacity-50"
                      >
                        {t(labelKey)}
                      </button>
                    ))}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
