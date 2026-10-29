"use client";

import type { CategoryPref } from "@/lib/api";
import {
  categoryCount,
  categoryId,
  hiddenCategories,
} from "@/lib/categories";
import { useLocale, useT } from "@/lib/LocaleProvider";

type Props = {
  prefs: CategoryPref[];
  busy: boolean;
  onShow: (category: CategoryPref) => void;
};

/** Compact notice above the feed: which categories were moved down, with a «Show» button. */
export function HiddenCategoriesBanner({ prefs, busy, onShow }: Props) {
  const locale = useLocale();
  const t = useT();
  const hidden = hiddenCategories(prefs);
  if (hidden.length === 0) return null;

  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl bg-gray-100 p-3 text-sm">
      <span className="font-semibold">{t("categories.banner")}</span>
      {hidden.map((c) => (
        <span key={categoryId(c)} className="flex items-center gap-2">
          <span>
            {c.name} — {categoryCount(locale, c)}
          </span>
          <button
            type="button"
            disabled={busy}
            aria-label={t("categories.showLabel", { name: c.name })}
            onClick={() => onShow(c)}
            className="min-h-11 min-w-11 rounded-xl bg-gray-200 px-3 font-semibold text-gray-900 disabled:opacity-50"
          >
            {t("categories.show")}
          </button>
        </span>
      ))}
    </div>
  );
}
