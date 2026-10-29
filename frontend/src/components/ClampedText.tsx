"use client";

import { useEffect, useRef, useState } from "react";

import { isClamped } from "@/lib/clamp";
import { useT } from "@/lib/LocaleProvider";

/** Текст в 3 строки с «Показать больше», если он не помещается. */
export function ClampedText({ text }: { text: string }) {
  const t = useT();
  const ref = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [clamped, setClamped] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () => {
      if (expanded) return;
      setClamped(isClamped(el.scrollHeight, el.clientHeight));
    };
    check();
    const observer = new ResizeObserver(check);
    observer.observe(el);
    return () => observer.disconnect();
  }, [text, expanded]);

  return (
    <div>
      <p
        ref={ref}
        className={`text-sm leading-5 break-words ${
          expanded ? "" : "line-clamp-3 min-h-15"
        }`}
      >
        {text}
      </p>
      {(clamped || expanded) && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 min-h-11 text-sm font-semibold underline focus-visible:outline-2 focus-visible:outline-offset-2"
        >
          {t(
            expanded ? "recommendations.showLess" : "recommendations.showMore",
          )}
        </button>
      )}
    </div>
  );
}
