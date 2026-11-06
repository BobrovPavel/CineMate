"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import Link from "next/link";

import {
  fetchCategoryMovies,
  fetchCategoryPrefs,
  postCategoryPref,
  postRating,
  TMDB_IMAGE_BASE,
  type CategoryMovie,
  type CategoryPref,
} from "@/lib/api";
import {
  categoryCount,
  categoryId,
  categoryState,
  shouldLoadMovies,
  withMovieValue,
  withRatingChange,
  withShow,
} from "@/lib/categories";
import { useLocale, useT } from "@/lib/LocaleProvider";
import { displayTitle } from "@/lib/titles";

type MoviesState = {
  status: "loading" | "ready" | "error";
  movies: CategoryMovie[];
};

/** Profile section: categories moved down by the rule or shown by the user, with a switch. */
export function HiddenCategoriesSection() {
  const locale = useLocale();
  const t = useT();
  const [prefs, setPrefs] = useState<CategoryPref[] | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const [lists, setLists] = useState<Record<string, MoviesState>>({});
  const [ratingPending, setRatingPending] = useState<Set<string>>(new Set());
  const started = useRef(false);

  const load = useCallback(async () => {
    try {
      setPrefs(await fetchCategoryPrefs());
    } catch {
      setMessage(t("categories.loadError"));
    }
  }, [t]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void load();
  }, [load]);

  async function toggle(category: CategoryPref) {
    const id = categoryId(category);
    if (pending.has(id)) return;
    const next = !category.show;
    setMessage(null);
    setPending((s) => new Set(s).add(id));
    setPrefs((prev) => (prev ? withShow(prev, category, next) : prev));
    try {
      await postCategoryPref(category.kind, category.key, next);
    } catch {
      setPrefs((prev) => (prev ? withShow(prev, category, !next) : prev));
      setMessage(t("categories.saveError"));
    } finally {
      setPending((s) => {
        const copy = new Set(s);
        copy.delete(id);
        return copy;
      });
    }
  }

  async function loadMovies(category: CategoryPref) {
    const id = categoryId(category);
    setLists((l) => ({ ...l, [id]: { status: "loading", movies: [] } }));
    try {
      const movies = await fetchCategoryMovies(category.kind, category.key);
      setLists((l) => ({ ...l, [id]: { status: "ready", movies } }));
    } catch {
      setLists((l) => {
        const copy = { ...l };
        delete copy[id]; // not loaded: the next expansion retries
        return { ...copy, [`${id}:error`]: { status: "error", movies: [] } };
      });
    }
  }

  function onToggleOpen(category: CategoryPref, open: boolean) {
    const id = categoryId(category);
    setLists((l) => {
      const copy = { ...l };
      delete copy[`${id}:error`];
      return copy;
    });
    if (shouldLoadMovies(open, id in lists, false)) void loadMovies(category);
  }

  async function changeRating(category: CategoryPref, movie: CategoryMovie) {
    const cid = categoryId(category);
    const key = `${cid}:${movie.movie_id}`;
    if (ratingPending.has(key)) return;
    const previous = movie.value;
    const next: 1 | -1 = previous === 1 ? -1 : 1;
    setMessage(null);
    setRatingPending((s) => new Set(s).add(key));
    const apply = (from: 1 | -1, to: 1 | -1) => {
      setLists((l) =>
        l[cid]
          ? {
              ...l,
              [cid]: {
                ...l[cid],
                movies: withMovieValue(l[cid].movies, movie.movie_id, to),
              },
            }
          : l,
      );
      setPrefs((p) => (p ? withRatingChange(p, category, from, to) : p));
    };
    apply(previous, next);
    try {
      await postRating(movie.movie_id, next);
    } catch {
      apply(next, previous);
      setMessage(t("categories.ratingError"));
    } finally {
      setRatingPending((s) => {
        const copy = new Set(s);
        copy.delete(key);
        return copy;
      });
    }
  }

  const stateLabel = (c: CategoryPref) => {
    const state = categoryState(c);
    if (state === "shown") return t("categories.shown");
    return state === "lifted" ? t("categories.lifted") : t("categories.hidden");
  };

  if (prefs === null && message === null) return null;

  return (
    <section
      aria-labelledby="hidden-categories-title"
      className="mb-4 flex flex-col gap-2 rounded-xl bg-gray-100 p-3 text-sm"
    >
      <h2 id="hidden-categories-title" className="text-base font-semibold">
        {t("categories.title")}
      </h2>
      <p className="text-gray-600">{t("categories.hint")}</p>
      {message && (
        <p role="alert" className="text-red-900">
          {message}
        </p>
      )}
      {prefs !== null && prefs.length === 0 && <p>{t("categories.empty")}</p>}
      {prefs !== null && prefs.length > 0 && (
        <ul className="flex flex-col gap-2">
          {prefs.map((c) => (
            <li key={categoryId(c)} className="min-w-0">
              <details
                onToggle={(e) =>
                  onToggleOpen(c, (e.currentTarget as HTMLDetailsElement).open)
                }
              >
                <summary className="flex min-h-11 min-w-0 cursor-pointer items-center justify-between gap-3">
                  <span className="min-w-0 break-words">
                    {c.name} — {categoryCount(locale, c)} ({stateLabel(c)})
                  </span>
                </summary>
                <MovieList
                  state={
                    lists[categoryId(c)] ?? lists[`${categoryId(c)}:error`]
                  }
                  category={c}
                  pending={ratingPending}
                  onChange={(m) => void changeRating(c, m)}
                />
              </details>
              <button
                type="button"
                disabled={pending.has(categoryId(c))}
                aria-label={
                  c.show
                    ? t("categories.hideLabel", { name: c.name })
                    : t("categories.showLabel", { name: c.name })
                }
                onClick={() => void toggle(c)}
                className="mt-1 min-h-11 rounded-xl bg-gray-200 px-3 text-gray-900 disabled:opacity-50"
              >
                {c.show ? t("categories.hide") : t("categories.show")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function MovieList({
  state,
  category,
  pending,
  onChange,
}: {
  state: MoviesState | undefined;
  category: CategoryPref;
  pending: Set<string>;
  onChange: (movie: CategoryMovie) => void;
}) {
  const locale = useLocale();
  const t = useT();
  if (!state || state.status === "loading") {
    return (
      <p className="py-2 text-gray-600">{t("categories.moviesLoading")}</p>
    );
  }
  if (state.status === "error") {
    return (
      <p role="alert" className="py-2 text-red-900">
        {t("categories.moviesError")}
      </p>
    );
  }
  if (state.movies.length === 0) {
    return <p className="py-2">{t("categories.moviesEmpty")}</p>;
  }
  return (
    <ul
      aria-label={t("categories.movies")}
      className="flex flex-col gap-2 py-2"
    >
      {state.movies.map((m) => {
        const { primary } = displayTitle(m, locale);
        const liked = m.value === 1;
        return (
          <li key={m.movie_id} className="flex min-w-0 items-center gap-3">
            <Link
              href={`/movies/${m.movie_id}`}
              aria-label={primary}
              tabIndex={-1}
              className="block h-16 w-11 shrink-0 overflow-hidden rounded bg-gray-200"
            >
              {m.poster_path && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={`${TMDB_IMAGE_BASE}${m.poster_path}`}
                  alt={t("poster.alt", { title: primary })}
                  className="h-full w-full object-cover"
                  loading="lazy"
                />
              )}
            </Link>
            <div className="flex min-w-0 flex-1 flex-col">
              <Link
                href={`/movies/${m.movie_id}`}
                className="font-semibold break-words"
              >
                {primary}
              </Link>
              <span className="text-gray-600">
                {m.year ? `${m.year} · ` : ""}
                <span className={liked ? "text-green-800" : "text-red-800"}>
                  {liked ? t("reaction.like") : t("reaction.dislike")}
                </span>
              </span>
            </div>
            <button
              type="button"
              disabled={pending.has(`${categoryId(category)}:${m.movie_id}`)}
              onClick={() => onChange(m)}
              aria-label={t("profile.changeTo", {
                title: primary,
                value: liked ? t("reaction.dislike") : t("reaction.like"),
              })}
              className="min-h-11 shrink-0 rounded-xl bg-gray-200 px-3 text-gray-900 disabled:opacity-50"
            >
              {liked ? t("reaction.dislike") : t("reaction.like")}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
