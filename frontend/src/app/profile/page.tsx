"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  ApiError,
  fetchProfile,
  postRating,
  TMDB_IMAGE_BASE,
  type ProfileItem,
} from "@/lib/api";
import { displayTitle } from "@/lib/titles";
import { useLocale } from "@/lib/useLocale";

type Status = "loading" | "ready" | "error";

export default function ProfilePage() {
  const router = useRouter();
  const locale = useLocale();
  const [status, setStatus] = useState<Status>("loading");
  const [items, setItems] = useState<ProfileItem[]>([]);
  const [pending, setPending] = useState<Set<number>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
  const started = useRef(false);

  const load = useCallback(async () => {
    setStatus("loading");
    try {
      setItems(await fetchProfile());
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

  function setValue(movieId: number, value: 1 | -1) {
    setItems((prev) => prev.map((it) => (it.movie_id === movieId ? { ...it, value } : it)));
  }

  async function toggle(item: ProfileItem) {
    const id = item.movie_id;
    if (pending.has(id)) return;
    const previous = item.value;
    const next: 1 | -1 = previous === 1 ? -1 : 1;
    setMessage(null);
    setPending((s) => new Set(s).add(id));
    setValue(id, next);
    try {
      await postRating(id, next);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.replace("/onboarding");
        return;
      }
      setValue(id, previous);
      setMessage("Не удалось изменить оценку. Попробуйте ещё раз.");
    } finally {
      setPending((s) => {
        const copy = new Set(s);
        copy.delete(id);
        return copy;
      });
    }
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-6">
      <h1 className="mb-4 text-2xl font-semibold">Мои оценки</h1>

      {message && (
        <div role="alert" className="mb-4 rounded-xl bg-red-100 p-3 text-sm text-red-900">
          {message}
        </div>
      )}

      {status === "loading" && (
        <ul className="flex flex-col gap-3" aria-busy="true">
          {Array.from({ length: 5 }, (_, i) => (
            <li key={i} className="flex animate-pulse gap-3">
              <div className="h-24 w-16 shrink-0 rounded-lg bg-gray-200" />
              <div className="flex flex-1 flex-col gap-2 py-2">
                <div className="h-5 w-2/3 rounded bg-gray-200" />
                <div className="h-4 w-1/3 rounded bg-gray-200" />
              </div>
            </li>
          ))}
          <li className="sr-only">Загрузка…</li>
        </ul>
      )}

      {status === "error" && (
        <div role="alert" className="flex flex-col items-center gap-4 py-10 text-center">
          <p>Не удалось загрузить оценки. Проверьте соединение и попробуйте ещё раз.</p>
          <button
            type="button"
            onClick={() => void load()}
            className="min-h-12 rounded-xl bg-black px-6 text-white"
          >
            Повторить
          </button>
        </div>
      )}

      {status === "ready" && items.length === 0 && (
        <div className="flex flex-col items-center gap-4 py-10 text-center">
          <p>Вы пока ничего не оценили.</p>
          <Link href="/onboarding" className="min-h-12 rounded-xl bg-black px-6 py-3 text-white">
            Оценить фильмы
          </Link>
        </div>
      )}

      {status === "ready" && items.length > 0 && (
        <ul className="flex flex-col gap-3">
          {items.map((item) => {
            const liked = item.value === 1;
            const { primary, secondary } = displayTitle(item, locale);
            const meta = item.year ? String(item.year) : "";
            return (
              <li key={item.movie_id} className="flex min-w-0 items-center gap-3">
                <div className="h-24 w-16 shrink-0 overflow-hidden rounded-lg bg-gray-200">
                  {item.poster_path ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={`${TMDB_IMAGE_BASE}${item.poster_path}`}
                      alt={`Постер фильма «${primary}»`}
                      className="h-full w-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <div
                      className="flex h-full w-full items-center justify-center p-1 text-center text-xs text-gray-500"
                      role="img"
                      aria-label="Постер отсутствует"
                    >
                      Нет постера
                    </div>
                  )}
                </div>
                <div className="flex min-w-0 flex-1 flex-col gap-1">
                  <h2 className="font-semibold break-words">{primary}</h2>
                  {secondary && (
                    <p className="text-sm break-words text-gray-600">({secondary})</p>
                  )}
                  {meta && <p className="text-sm text-gray-600">{meta}</p>}
                  <p
                    className={`text-sm font-medium ${liked ? "text-green-800" : "text-red-800"}`}
                  >
                    {liked ? "Нравится" : "Не нравится"}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={pending.has(item.movie_id)}
                  onClick={() => void toggle(item)}
                  aria-label={
                    liked
                      ? `Изменить оценку фильма «${primary}» на «Не нравится»`
                      : `Изменить оценку фильма «${primary}» на «Нравится»`
                  }
                  className="min-h-11 shrink-0 rounded-xl bg-gray-200 px-3 text-sm text-gray-900 disabled:opacity-50"
                >
                  {liked ? "Не нравится" : "Нравится"}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}
