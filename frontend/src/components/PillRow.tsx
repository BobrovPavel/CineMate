"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { arrowState, nextScrollLeft } from "@/lib/movie";
import { useT } from "@/lib/LocaleProvider";

/** Pills in one horizontal row: swipe on a phone, arrows on a wide screen. */
export function PillRow({ labels }: { labels: string[] }) {
  const t = useT();
  const ref = useRef<HTMLUListElement>(null);
  const [arrows, setArrows] = useState({ left: false, right: false });

  const update = useCallback(() => {
    if (ref.current) setArrows(arrowState(ref.current));
  }, []);

  useEffect(() => {
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [update, labels]);

  function scroll(direction: -1 | 1) {
    const el = ref.current;
    if (el) el.scrollTo({ left: nextScrollLeft(el, direction), behavior: "smooth" });
  }

  const arrow =
    "hidden min-h-11 min-w-11 shrink-0 items-center justify-center rounded-full bg-gray-200 text-gray-900 md:flex";
  return (
    <div className="flex items-center gap-2">
      {arrows.left && (
        <button
          type="button"
          className={arrow}
          aria-label={t("movie.scrollLeft")}
          onClick={() => scroll(-1)}
        >
          ‹
        </button>
      )}
      <ul
        ref={ref}
        onScroll={update}
        className="flex min-w-0 flex-1 gap-2 overflow-x-auto pb-1 [scrollbar-width:none]"
      >
        {labels.map((label) => (
          <li
            key={label}
            className="shrink-0 rounded-full bg-gray-100 px-3 py-1.5 text-sm whitespace-nowrap"
          >
            {label}
          </li>
        ))}
      </ul>
      {arrows.right && (
        <button
          type="button"
          className={arrow}
          aria-label={t("movie.scrollRight")}
          onClick={() => scroll(1)}
        >
          ›
        </button>
      )}
    </div>
  );
}
