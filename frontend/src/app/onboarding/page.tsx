"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { CardSkeleton, MovieCard } from "@/components/MovieCard";
import {
  fetchOnboarding,
  openSession,
  postNotSeen,
  postRating,
  type OnboardingCard,
} from "@/lib/api";

const MIN_RATED = 5;
const CARDS_LIMIT = 20;
const SWIPE_THRESHOLD = 60;

type Status = "loading" | "ready" | "error";

export default function OnboardingPage() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>("loading");
  const [cards, setCards] = useState<OnboardingCard[]>([]);
  const [index, setIndex] = useState(0);
  const [ratedCount, setRatedCount] = useState(0);
  const [actionError, setActionError] = useState(false);
  const [busy, setBusy] = useState(false);
  const started = useRef(false);
  const touchStart = useRef<{ x: number; y: number } | null>(null);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      await openSession();
      const loaded = await fetchOnboarding(CARDS_LIMIT);
      setCards(loaded);
      setIndex(0);
      setStatus("ready");
    } catch {
      setStatus("error");
    }
  }, []);

  useEffect(() => {
    // Guard against the double effect run in dev (StrictMode) creating two sessions.
    if (started.current) return;
    started.current = true;
    void load();
  }, [load]);

  const finished = status === "ready" && index >= cards.length;

  useEffect(() => {
    if (finished) router.push("/recommendations");
  }, [finished, router]);

  const current = status === "ready" ? cards[index] : undefined;

  const answer = useCallback(
    async (kind: "like" | "dislike" | "not_seen") => {
      if (!current || busy) return;
      setBusy(true);
      setActionError(false);
      try {
        const result =
          kind === "not_seen"
            ? await postNotSeen(current.movie_id)
            : await postRating(current.movie_id, kind === "like" ? 1 : -1);
        setRatedCount(result.rated_count);
        setIndex((i) => i + 1);
      } catch {
        setActionError(true);
      } finally {
        setBusy(false);
      }
    },
    [current, busy],
  );

  function onTouchStart(e: React.TouchEvent) {
    const t = e.touches[0];
    touchStart.current = { x: t.clientX, y: t.clientY };
  }

  function onTouchEnd(e: React.TouchEvent) {
    const start = touchStart.current;
    touchStart.current = null;
    if (!start) return;
    const t = e.changedTouches[0];
    const dx = t.clientX - start.x;
    const dy = t.clientY - start.y;
    if (Math.abs(dx) < SWIPE_THRESHOLD || Math.abs(dx) < Math.abs(dy) * 1.5) return;
    void answer(dx > 0 ? "like" : "dislike");
  }

  const buttonBase =
    "min-h-14 flex-1 rounded-xl px-3 text-base font-semibold disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2";

  return (
    <main className="mx-auto flex w-full max-w-md flex-col gap-5 px-4 py-6">
      <header className="flex items-center justify-between text-sm text-gray-600">
        <span aria-live="polite">
          {status === "ready" && !finished ? `${Math.min(index + 1, cards.length)} из ${cards.length}` : " "}
        </span>
        <Link href="/recommendations" className="min-h-11 content-center underline">
          Пропустить
        </Link>
      </header>

      {status === "loading" && <CardSkeleton />}

      {status === "error" && (
        <div role="alert" className="flex flex-col items-center gap-4 py-10 text-center">
          <p>Не удалось загрузить карточки. Проверьте соединение и попробуйте ещё раз.</p>
          <button
            type="button"
            onClick={() => void load()}
            className="min-h-12 rounded-xl bg-black px-6 text-white"
          >
            Повторить
          </button>
        </div>
      )}

      {status === "ready" && cards.length === 0 && (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <p>Карточки закончились.</p>
          <Link
            href="/recommendations"
            className="inline-flex min-h-12 items-center rounded-xl bg-black px-6 text-white"
          >
            Перейти к рекомендациям
          </Link>
        </div>
      )}

      {current && (
        <>
          <div onTouchStart={onTouchStart} onTouchEnd={onTouchEnd} className="touch-pan-y">
            <MovieCard card={current} />
          </div>

          {actionError && (
            <div role="alert" className="text-center text-sm text-red-700">
              Не удалось сохранить ответ. Нажмите кнопку ещё раз.
            </div>
          )}

          <div className="flex gap-3">
            <button
              type="button"
              aria-label="Не нравится"
              disabled={busy}
              onClick={() => void answer("dislike")}
              className={`${buttonBase} bg-red-100 text-red-900`}
            >
              Не нравится
            </button>
            <button
              type="button"
              aria-label="Не смотрел"
              disabled={busy}
              onClick={() => void answer("not_seen")}
              className={`${buttonBase} bg-gray-200 text-gray-900`}
            >
              Не смотрел
            </button>
            <button
              type="button"
              aria-label="Нравится"
              disabled={busy}
              onClick={() => void answer("like")}
              className={`${buttonBase} bg-green-100 text-green-900`}
            >
              Нравится
            </button>
          </div>

          {ratedCount >= MIN_RATED && (
            <Link
              href="/recommendations"
              className="inline-flex min-h-12 items-center justify-center rounded-xl bg-black px-6 text-white"
            >
              Хватит, покажи рекомендации
            </Link>
          )}
        </>
      )}
    </main>
  );
}
