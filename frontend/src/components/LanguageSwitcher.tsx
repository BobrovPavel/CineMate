"use client";

import { useEffect, useId, useReducer, useRef } from "react";

import { useLocale, useT } from "@/lib/LocaleProvider";
import { initialMenu, menuReducer, selectedLang } from "@/lib/languageMenu";
import { LANGUAGES, languageByCode, setLanguage, type Lang } from "@/lib/locale";

function GlobeIcon() {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z" />
    </svg>
  );
}

export function LanguageSwitcher() {
  const t = useT();
  const lang = useLocale();
  const [state, dispatch] = useReducer(menuReducer, undefined, initialMenu);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const listRef = useRef<HTMLUListElement>(null);
  const listId = useId();

  useEffect(() => {
    if (state.open) listRef.current?.focus();
  }, [state.open]);

  useEffect(() => {
    if (!state.open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) dispatch({ type: "close" });
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [state.open]);

  function choose(code: Lang) {
    dispatch({ type: "close" });
    buttonRef.current?.focus();
    if (code !== lang) setLanguage(code);
  }

  function onKeyDown(event: React.KeyboardEvent) {
    const chosen = selectedLang(state, event.key, lang);
    if (state.open && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      if (chosen) choose(chosen);
      else dispatch({ type: "close" });
      return;
    }
    // Enter/Space on the closed button are left to its native click.
    if (!state.open && (event.key === "Enter" || event.key === " ")) return;
    if (["ArrowDown", "ArrowUp", "Home", "End", "Escape"].includes(event.key)) {
      event.preventDefault();
    }
    dispatch({ type: "key", key: event.key, current: lang });
    if (event.key === "Escape" && state.open) buttonRef.current?.focus();
  }

  const current = languageByCode(lang);
  return (
    <div ref={rootRef} className="relative shrink-0" onKeyDown={onKeyDown}>
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="listbox"
        aria-expanded={state.open}
        aria-controls={state.open ? listId : undefined}
        aria-label={`${t("nav.language")}: ${current.name}`}
        onClick={() => dispatch({ type: "toggle", current: lang })}
        className="inline-flex min-h-11 min-w-11 items-center gap-1.5 rounded-lg px-2 text-sm text-gray-800"
      >
        <GlobeIcon />
        <span>{current.label}</span>
        <svg
          aria-hidden="true"
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className={`transition-transform ${state.open ? "rotate-180" : ""}`}
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {state.open && (
        <ul
          id={listId}
          role="listbox"
          aria-label={t("nav.language")}
          aria-activedescendant={`${listId}-${LANGUAGES[state.active].code}`}
          tabIndex={-1}
          ref={listRef}
          className="absolute right-0 z-10 mt-1 max-w-[calc(100vw-2rem)] min-w-32 rounded-lg border border-gray-200 bg-white py-1 shadow-lg outline-none"
        >
          {LANGUAGES.map((language, index) => (
            <li
              key={language.code}
              id={`${listId}-${language.code}`}
              role="option"
              lang={language.code}
              aria-selected={language.code === lang}
              onClick={() => choose(language.code)}
              className={`flex min-h-11 cursor-pointer items-center gap-2 px-3 text-sm ${
                language.code === lang ? "bg-black font-semibold text-white" : "text-gray-800"
              } ${
                index === state.active
                  ? language.code === lang
                    ? "ring-2 ring-inset ring-gray-400"
                    : "bg-gray-100"
                  : ""
              }`}
            >
              <span aria-hidden="true">{language.flag}</span>
              <span>{language.label}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
