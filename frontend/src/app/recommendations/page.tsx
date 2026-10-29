"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { ClampedText } from "@/components/ClampedText";
import { CardSkeleton } from "@/components/MovieCard";
import {
  ApiError,
  fetchRecommendations,
  postReactionRating,
  postReactionSeen,
  TMDB_IMAGE_BASE,
  type RecommendationItem,
  type SeenType,
} from "@/lib/api";
import { explainCollaborative } from "@/lib/explain";
import type { MessageKey } from "@/lib/i18n";
import { displayTitle } from "@/lib/titles";
import { useLocale, useT } from "@/lib/LocaleProvider";

const LIMIT = 20;
const LEAVE_MS = 250;

type Status = "loading" | "ready" | "error";
type Reaction = "like" | "dislike" | "watched" | "not_interested";
type Shown = RecommendationItem & { sessionId: string };

const BUTTONS: { reaction: Reaction; label: MessageKey; style: string }[] = [
  {
    reaction: "like",
    label: "reaction.like",
    style: "bg-green-100 text-green-900",
  },
  {
    reaction: "dislike",
    label: "reaction.dislike",
    style: "bg-red-100 text-red-900",
  },
  {
    reaction: "watched",
    label: "reaction.watched",
    style: "bg-gray-200 text-gray-900",
  },
  {
    reaction: "not_interested",
    label: "reaction.notInterested",
    style: "bg-gray-200 text-gray-900",
  },
];

export default function RecommendationsPage() {
  const router = useRouter();
  const locale = useLocale();
  const t = useT();
  const [status, setStatus] = useState<Status>("loading");
  const [strategy, setStrategy] = useState<"collaborative" | "fallback">(
    "collaborative",
  );
  const [items, setItems] = useState<Shown[]>([]);
  const [leaving, setLeaving] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const started = useRef(false);
  // Movies reacted to in this page lifetime; never re-added by a refetch.
  const reacted = useRef<Set<number>>(new Set());

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      const data = await fetchRecommendations(LIMIT);
      setStrategy(data.strategy);
      setItems(data.items.map((it) => ({ ...it, sessionId: data.session_id })));
      setStatus("ready");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/onboarding");
        return;
      }
      setStatus("error");
    }
  }, [router]);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void load();
  }, [load]);

  // Refetch after a reaction: keep shown cards untouched, only append new ones.
  const refill = useCallback(async () => {
    try {
      const data = await fetchRecommendations(LIMIT);
      setItems((prev) => {
        const known = new Set(prev.map((p) => p.movie.id));
        const fresh = data.items
          .filter(
            (it) =>
              !known.has(it.movie.id) && !reacted.current.has(it.movie.id),
          )
          .map((it) => ({ ...it, sessionId: data.session_id }));
        return fresh.length > 0 ? [...prev, ...fresh] : prev;
      });
    } catch {
      // Silent: the current grid stays usable.
    }
  }, []);

  async function react(item: Shown, reaction: Reaction) {
    const id = item.movie.id;
    if (leaving.has(id)) return;
    setMessage(null);
    setLeaving((s) => new Set(s).add(id));
    try {
      if (reaction === "like" || reaction === "dislike") {
        await postReactionRating(
          id,
          reaction === "like" ? 1 : -1,
          item.sessionId,
        );
      } else {
        await postReactionSeen(id, reaction as SeenType, item.sessionId);
      }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/onboarding");
        return;
      }
      setLeaving((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
      setMessage(t("recommendations.reactError"));
      return;
    }
    reacted.current.add(id);
    window.setTimeout(() => {
      setItems((prev) => prev.filter((p) => p.movie.id !== id));
      setLeaving((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      });
    }, LEAVE_MS);
    void refill();
  }

  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-semibold">
        {t("recommendations.title")}
      </h1>

      {status === "ready" && strategy === "fallback" && (
        <div className="mb-4 rounded-xl bg-amber-100 p-4 text-amber-950">
          {t("recommendations.fallback")}{" "}
          <Link href="/onboarding" className="font-semibold underline">
            {t("recommendations.rateMore")}
          </Link>
        </div>
      )}

      {message && (
        <div
          role="alert"
          className="mb-4 rounded-xl bg-red-100 p-3 text-sm text-red-900"
        >
          {message}
        </div>
      )}

      {status === "loading" && (
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      )}

      {status === "error" && (
        <div
          role="alert"
          className="flex flex-col items-center gap-4 py-10 text-center"
        >
          <p>{t("recommendations.loadError")}</p>
          <button
            type="button"
            onClick={() => void load()}
            className="min-h-12 rounded-xl bg-black px-6 text-white"
          >
            {t("common.retry")}
          </button>
        </div>
      )}

      {status === "ready" && items.length === 0 && (
        <p className="py-10 text-center">{t("recommendations.empty")}</p>
      )}

      {status === "ready" && items.length > 0 && (
        <ul className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {items.map((item) => {
            const gone = leaving.has(item.movie.id);
            const { primary, secondary } = displayTitle(item.movie, locale);
            const meta = [item.movie.year, item.movie.genres.join(", ")]
              .filter(Boolean)
              .join(" · ");
            return (
              <li
                key={item.movie.id}
                className={`flex h-full min-w-0 flex-col gap-3 transition duration-200 ${
                  gone ? "scale-95 opacity-0" : "opacity-100"
                }`}
              >
                <div className="aspect-[2/3] w-full overflow-hidden rounded-xl bg-gray-200">
                  {item.movie.poster_path ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={`${TMDB_IMAGE_BASE}${item.movie.poster_path}`}
                      alt={t("poster.alt", { title: primary })}
                      className="h-full w-full object-cover"
                      loading="lazy"
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
                </div>
                <h2
                  title={primary}
                  className="line-clamp-2 min-h-14 text-lg leading-7 font-semibold break-words"
                >
                  {primary}
                </h2>
                <p
                  title={secondary ?? undefined}
                  className="min-h-5 truncate text-sm leading-5 text-gray-600"
                >
                  {secondary ? `(${secondary})` : null}
                </p>
                <p
                  title={meta || undefined}
                  className="min-h-5 truncate text-sm leading-5 text-gray-600"
                >
                  {meta}
                </p>
                {strategy === "collaborative" && (
                  <ClampedText
                    text={explainCollaborative(
                      locale,
                      item.liked_by,
                      item.because_of.map(
                        (b) => displayTitle(b, locale).primary,
                      ),
                    )}
                  />
                )}
                <div className="mt-auto grid grid-cols-2 gap-2">
                  {BUTTONS.map((b) => (
                    <button
                      key={b.reaction}
                      type="button"
                      aria-label={t("recommendations.buttonLabel", {
                        action: t(b.label),
                        title: primary,
                      })}
                      disabled={gone}
                      onClick={() => void react(item, b.reaction)}
                      className={`min-h-11 min-w-11 rounded-xl px-2 text-sm font-semibold disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 ${b.style}`}
                    >
                      {t(b.label)}
                    </button>
                  ))}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
