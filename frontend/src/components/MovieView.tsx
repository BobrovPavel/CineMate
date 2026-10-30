"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { PillRow } from "@/components/PillRow";
import {
  ApiError,
  fetchMovie,
  postReactionRating,
  postReactionSeen,
  TMDB_IMAGE_BASE,
  TMDB_PROFILE_BASE,
  type MovieDetail,
  type SeenType,
} from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/LocaleProvider";
import { backTarget, factRows, pillLabels } from "@/lib/movie";

type Status = "loading" | "ready" | "error" | "notFound";
type Reaction = "like" | "dislike" | "watched" | "not_interested";

const BUTTONS: { reaction: Reaction; label: MessageKey }[] = [
  { reaction: "like", label: "reaction.like" },
  { reaction: "dislike", label: "reaction.dislike" },
  { reaction: "watched", label: "reaction.watched" },
  { reaction: "not_interested", label: "reaction.notInterested" },
];

const ACTIVE: Record<Reaction, string> = {
  like: "bg-green-700 text-white",
  dislike: "bg-red-700 text-white",
  watched: "bg-gray-800 text-white",
  not_interested: "bg-gray-800 text-white",
};

function isActive(movie: MovieDetail, reaction: Reaction): boolean {
  if (reaction === "like") return movie.user_value === 1;
  if (reaction === "dislike") return movie.user_value === -1;
  return movie.user_mark === reaction;
}

export function MovieView({ movieId }: { movieId: number }) {
  const router = useRouter();
  const lang = useLocale();
  const t = useT();
  const [status, setStatus] = useState<Status>("loading");
  const [movie, setMovie] = useState<MovieDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const sessionId = useRef<string>("");

  useEffect(() => {
    sessionId.current = crypto.randomUUID();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    fetchMovie(movieId)
      .then((data) => {
        if (cancelled) return;
        setMovie(data);
        setStatus("ready");
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof ApiError && e.status === 401) {
          router.replace("/onboarding");
        } else {
          setStatus(e instanceof ApiError && e.status === 404 ? "notFound" : "error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [movieId, attempt, router]);

  function goBack() {
    if (backTarget(window.history.length) === "history") router.back();
    else router.push("/recommendations");
  }

  async function react(reaction: Reaction) {
    if (!movie || busy) return;
    const previous = movie;
    setBusy(true);
    setMessage(null);
    const next: MovieDetail =
      reaction === "like" || reaction === "dislike"
        ? { ...movie, user_value: reaction === "like" ? 1 : -1 }
        : { ...movie, user_mark: reaction as SeenType };
    setMovie(next);
    try {
      if (reaction === "like" || reaction === "dislike") {
        await postReactionRating(movie.id, reaction === "like" ? 1 : -1, sessionId.current);
      } else {
        await postReactionSeen(movie.id, reaction as SeenType, sessionId.current);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/onboarding");
        return;
      }
      setMovie(previous);
      setMessage(t("movie.saveError"));
    } finally {
      setBusy(false);
    }
  }

  const backButton = (
    <button
      type="button"
      onClick={goBack}
      className="mb-4 min-h-11 rounded-xl bg-gray-200 px-4 text-sm text-gray-900"
    >
      ← {t("movie.back")}
    </button>
  );

  if (status === "loading") {
    return (
      <main className="mx-auto w-full max-w-4xl px-4 py-6" aria-busy="true">
        {backButton}
        <div className="flex animate-pulse flex-col gap-4 md:flex-row">
          <div className="aspect-[2/3] w-full max-w-60 rounded-xl bg-gray-200" />
          <div className="h-8 w-2/3 rounded bg-gray-200" />
        </div>
        <p className="sr-only">{t("common.loading")}</p>
      </main>
    );
  }

  if (status !== "ready" || !movie) {
    return (
      <main className="mx-auto w-full max-w-4xl px-4 py-6">
        {backButton}
        <div role="alert" className="flex flex-col items-center gap-4 py-10 text-center">
          <p>{status === "notFound" ? t("movie.notFound") : t("movie.loadError")}</p>
          {status === "notFound" ? (
            <Link
              href="/recommendations"
              className="min-h-12 rounded-xl bg-black px-6 py-3 text-white"
            >
              {t("movie.toFeed")}
            </Link>
          ) : (
            <button
              type="button"
              onClick={() => setAttempt((n) => n + 1)}
              className="min-h-12 rounded-xl bg-black px-6 text-white"
            >
              {t("common.retry")}
            </button>
          )}
        </div>
      </main>
    );
  }

  const facts = factRows(movie, lang, t);
  const pills = pillLabels(movie.genres, movie.keywords);
  const cast = movie.cast.slice(0, 15);
  return (
    <main className="mx-auto w-full max-w-4xl px-4 py-6">
      {backButton}
      <article className="flex flex-col gap-6">
        <div className="flex flex-col gap-6 md:flex-row md:justify-between">
          <div className="flex min-w-0 flex-col gap-4 md:flex-1">
            <header>
              <h1 className="text-2xl font-semibold break-words">{movie.display_title}</h1>
              {movie.second_title && (
                <p className="text-gray-600 break-words">{movie.second_title}</p>
              )}
              {movie.tagline && <p className="mt-1 text-sm text-gray-600 italic">{movie.tagline}</p>}
            </header>
            {movie.ratings.length > 0 && (
              <section aria-label={t("movie.ratings")}>
                <ul className="flex flex-wrap gap-3">
                  {movie.ratings.map((r) => (
                    <li key={r.source} className="min-w-32 rounded-xl bg-gray-100 p-3">
                      <p className="text-sm text-gray-600">{r.label}</p>
                      <p className="text-xl font-semibold">
                        {r.scale === "%" ? `${Math.round(r.value)}%` : r.value.toFixed(1)}
                        {r.scale === "10" && (
                          <span className="text-sm font-normal text-gray-600"> / 10</span>
                        )}
                      </p>
                      <div
                        className="my-1 h-1.5 overflow-hidden rounded bg-gray-300"
                        role="meter"
                        aria-label={r.label}
                        aria-valuemin={0}
                        aria-valuemax={r.scale === "%" ? 100 : 10}
                        aria-valuenow={r.value}
                      >
                        <div
                          className="h-full bg-black"
                          style={{
                            width: `${Math.max(0, Math.min(100, r.scale === "%" ? r.value : r.value * 10))}%`,
                          }}
                        />
                      </div>
                      {r.votes !== null && (
                        <p className="text-xs text-gray-600">
                          {t("movie.votes", { n: r.votes.toLocaleString(lang) })}
                        </p>
                      )}
                      {r.url && (
                        <a
                          href={r.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          aria-label={t("movie.ratingLink", { source: r.label })}
                          className="text-xs underline"
                        >
                          {r.label} ↗
                        </a>
                      )}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {facts.length > 0 && (
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
                {facts.map((f) => (
                  <div key={f.key} className="contents">
                    <dt className="text-gray-600">{t(f.key)}</dt>
                    <dd className="break-words">{f.value}</dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
          <div className="relative aspect-[2/3] w-full max-w-60 shrink-0 self-center overflow-hidden rounded-xl bg-gray-200 md:self-start">
            {movie.poster_path ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={`${TMDB_IMAGE_BASE}${movie.poster_path}`}
                alt={t("poster.alt", { title: movie.display_title })}
                className="h-full w-full object-cover"
              />
            ) : (
              <div
                className="flex h-full w-full items-center justify-center p-4 text-center text-gray-500"
                role="img"
                aria-label={t("poster.missing")}
              >
                {t("poster.missing")}
              </div>
            )}
            {movie.certification && (
              <span
                aria-label={t("movie.ageRating", { value: movie.certification })}
                className="absolute top-2 right-2 rounded-md bg-black/80 px-2 py-1 text-sm font-semibold text-white"
              >
                {movie.certification}
              </span>
            )}
          </div>
        </div>

        {movie.overview && (
          <section>
            <h2 className="mb-1 text-lg font-semibold">{t("movie.overview")}</h2>
            <p className="whitespace-pre-line">{movie.overview}</p>
          </section>
        )}

        {pills.length > 0 && (
          <section aria-label={t("movie.tags")}>
            <PillRow labels={pills} />
          </section>
        )}

        {cast.length > 0 && (
          <section>
            <h2 className="mb-2 text-lg font-semibold">{t("movie.cast")}</h2>
            <ul className="flex gap-3 overflow-x-auto pb-2">
              {cast.map((p) => (
                <li key={p.id} className="w-24 shrink-0">
                  <div className="aspect-[2/3] overflow-hidden rounded-lg bg-gray-200">
                    {p.profile_path ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={`${TMDB_PROFILE_BASE}${p.profile_path}`}
                        alt={t("movie.photoAlt", { name: p.name })}
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
                  <p className="mt-1 text-sm font-medium break-words">{p.name}</p>
                  {p.character && (
                    <p className="text-xs break-words text-gray-600">{p.character}</p>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        <section aria-label={t("movie.reactions")}>
          {message && (
            <div role="alert" className="mb-3 rounded-xl bg-red-100 p-3 text-sm text-red-900">
              {message}
            </div>
          )}
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {BUTTONS.map((b) => {
              const active = isActive(movie, b.reaction);
              return (
                <button
                  key={b.reaction}
                  type="button"
                  disabled={busy}
                  aria-pressed={active}
                  onClick={() => void react(b.reaction)}
                  className={`min-h-11 rounded-xl px-2 text-sm font-semibold disabled:opacity-50 ${
                    active ? ACTIVE[b.reaction] : "bg-gray-200 text-gray-900"
                  }`}
                >
                  {t(b.label)}
                </button>
              );
            })}
          </div>
        </section>
      </article>
    </main>
  );
}
