"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchCategoryPrefs,
  postCategoryPref,
  type CategoryPref,
} from "@/lib/api";
import { categoryCount, categoryId, withShow } from "@/lib/categories";
import { useLocale, useT } from "@/lib/LocaleProvider";

/** Profile section: categories moved down by the rule or shown by the user, with a switch. */
export function HiddenCategoriesSection() {
  const locale = useLocale();
  const t = useT();
  const [prefs, setPrefs] = useState<CategoryPref[] | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [message, setMessage] = useState<string | null>(null);
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
      {prefs !== null && prefs.length === 0 && (
        <p>{t("categories.empty")}</p>
      )}
      {prefs !== null && prefs.length > 0 && (
        <ul className="flex flex-col gap-2">
          {prefs.map((c) => (
            <li
              key={categoryId(c)}
              className="flex min-w-0 items-center justify-between gap-3"
            >
              <span className="min-w-0 break-words">
                {c.name} — {categoryCount(locale, c)} (
                {c.show ? t("categories.shown") : t("categories.hidden")})
              </span>
              <button
                type="button"
                disabled={pending.has(categoryId(c))}
                aria-label={
                  c.show
                    ? t("categories.hideLabel", { name: c.name })
                    : t("categories.showLabel", { name: c.name })
                }
                onClick={() => void toggle(c)}
                className="min-h-11 shrink-0 rounded-xl bg-gray-200 px-3 text-gray-900 disabled:opacity-50"
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
