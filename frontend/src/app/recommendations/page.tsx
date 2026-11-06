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
import {
  collectionLine,
  explainCollaborative,
  explainTaste,
  explainNextPart,
  explainTwin,
} from "@/lib/explain";
import {
  canRequestPage,
  clearFeed,
  loadFeed,
  mergePage,
  needsRefill,
  saveFeed,
} from "@/lib/feed";
import type { MessageKey } from "@/lib/i18n";
import { displayTitle } from "@/lib/titles";
import { useLocale, useT } from "@/lib/LocaleProvider";

const LIMIT = 20;
const LEAVE_MS = 250;
const PRELOAD_MARGIN = "600px 0px";

type Status = "loading" | "ready" | "error";
type MoreState = "idle" | "loading" | "error";
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
  const [more, setMore] = useState<MoreState>("idle");
  const [hasMore, setHasMore] = useState(true);
  const started = useRef(false);
  const inflight = useRef(false);
  const sessionId = useRef<string | null>(null);
  const offset = useRef(0);
  const sentinel = useRef<HTMLDivElement | null>(null);
  // Movies reacted to in this page lifetime; never re-added by a later page.
  const reacted = useRef<Set<number>>(new Set());
  const latest = useRef({ items, hasMore, strategy, ready: false });
  latest.current = { items, hasMore, strategy, ready: status === "ready" };

  // One request at a time. ``reset`` starts a new feed session.
  const fetchPage = useCallback(
    async (reset: boolean) => {
      if (inflight.current) return;
      inflight.current = true;
      const first = reset || sessionId.current === null;
      if (reset) {
        clearFeed(window.sessionStorage);
        sessionId.current = null;
        offset.current = 0;
        reacted.current = new Set();
        setItems([]);
        setHasMore(true);
      }
      if (first) setStatus("loading");
      else setMore("loading");
      try {
        const page =
          first || sessionId.current === null
            ? undefined
            : { sessionId: sessionId.current, offset: offset.current };
        const data = await fetchRecommendations(LIMIT, page);
        const sid = data.session_id;
        sessionId.current = sid;
        offset.current = data.next_offset;
        setStrategy(data.strategy);
        setHasMore(data.has_more);
        setItems((prev) =>
          mergePage(
            first ? [] : prev,
            data.items.map((it) => ({ ...it, sessionId: sid })),
            reacted.current,
          ),
        );
        setStatus("ready");
        setMore("idle");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          router.replace("/onboarding");
          return;
        }
        if (first) setStatus("error");
        else setMore("error");
      } finally {
        inflight.current = false;
      }
    },
    [router],
  );

  const loadMore = useCallback(() => {
    void fetchPage(false);
  }, [fetchPage]);

  // First load: restore the saved feed (back from a movie page) or start a new one.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const saved = loadFeed<Shown>(window.sessionStorage);
    if (saved) {
      sessionId.current = saved.sessionId;
      offset.current = saved.offset;
      setStrategy(saved.strategy);
      setItems(saved.items);
      setHasMore(saved.hasMore);
      setStatus("ready");
      window.requestAnimationFrame(() => window.scrollTo(0, saved.scrollY));
      return;
    }
    void fetchPage(true);
  }, [fetchPage]);

  // Keep the feed state in sessionStorage (cards, offset and scroll position).
  useEffect(() => {
    function save() {
      const cur = latest.current;
      if (!cur.ready || sessionId.current === null) return;
      saveFeed<Shown>(window.sessionStorage, {
        sessionId: sessionId.current,
        items: cur.items,
        offset: offset.current,
        hasMore: cur.hasMore,
        strategy: cur.strategy,
        scrollY: window.scrollY,
      });
    }
    let timer: number | undefined;
    function onScroll() {
      window.clearTimeout(timer);
      timer = window.setTimeout(save, 150);
    }
    save();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("pagehide", save);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("pagehide", save);
      save();
    };
  }, [items, hasMore, status, strategy]);

  const canLoad = canRequestPage({
    loading: status !== "ready" || more === "loading",
    hasMore,
    failed: more === "error",
  });

  // Next page when the sentinel (~600 px before the end of the list) scrolls into view.
  useEffect(() => {
    const node = sentinel.current;
    if (!node || !canLoad || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) loadMore();
      },
      { rootMargin: PRELOAD_MARGIN },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [canLoad, loadMore, items.length]);

  // Too few cards left after reactions: load the next page.
  useEffect(() => {
    if (canLoad && needsRefill(items.length)) loadMore();
  }, [canLoad, items.length, loadMore]);

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
            onClick={() => void fetchPage(true)}
            className="min-h-12 rounded-xl bg-black px-6 text-white"
          >
            {t("common.retry")}
          </button>
        </div>
      )}

      {status === "ready" && items.length === 0 && !hasMore && (
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
                <Link
                  href={`/movies/${item.movie.id}`}
                  aria-label={primary}
                  tabIndex={-1}
                  className="block"
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
                </Link>
                <h2
                  title={primary}
                  className="line-clamp-2 min-h-14 text-lg leading-7 font-semibold break-words"
                >
                  <Link href={`/movies/${item.movie.id}`}>{primary}</Link>
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
                {item.collection && (
                  <p className="min-h-5 truncate text-sm leading-5 text-gray-600">
                    <Link
                      href={`/movies/${item.movie.id}`}
                      className="underline"
                      title={collectionLine(
                        locale,
                        item.collection.name,
                        item.collection.parts,
                      )}
                    >
                      {collectionLine(
                        locale,
                        item.collection.name,
                        item.collection.parts,
                      )}
                    </Link>
                  </p>
                )}
                {item.collection?.mode === "next" &&
                  item.collection.rated_parts.length > 0 && (
                    <ClampedText
                      text={explainNextPart(
                        locale,
                        item.collection.rated_parts,
                      )}
                    />
                  )}
                {strategy === "collaborative" && item.twin && (
                  <ClampedText
                    text={explainTwin(locale, item.twin.common, item.twin.of)}
                  />
                )}
                {strategy === "collaborative" && !item.twin && (
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
                {strategy === "collaborative" && item.because_taste && (
                  <ClampedText
                    text={explainTaste(locale, item.because_taste.name)}
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

      {status === "ready" && more === "loading" && (
        <div className="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <CardSkeleton key={i} />
          ))}
        </div>
      )}

      {status === "ready" && more === "error" && (
        <div
          role="alert"
          className="flex flex-col items-center gap-4 py-10 text-center"
        >
          <p>{t("recommendations.moreError")}</p>
          <button
            type="button"
            onClick={loadMore}
            className="min-h-12 rounded-xl bg-black px-6 text-white"
          >
            {t("common.retry")}
          </button>
        </div>
      )}

      {status === "ready" && hasMore && <div ref={sentinel} aria-hidden="true" />}

      {status === "ready" && !hasMore && items.length > 0 && (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <p>{t("recommendations.end")}</p>
          <button
            type="button"
            onClick={() => void fetchPage(true)}
            className="min-h-12 rounded-xl bg-black px-6 text-white"
          >
            {t("recommendations.refresh")}
          </button>
        </div>
      )}
    </main>
  );
}
