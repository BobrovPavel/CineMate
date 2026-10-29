"use client";

import { createContext, useContext, useMemo } from "react";

import { translate, type Translate } from "./i18n";
import type { Lang } from "./locale";

const LocaleContext = createContext<Lang>("en");

/** Gives client components the language chosen on the server. */
export function LocaleProvider({
  lang,
  children,
}: {
  lang: Lang;
  children: React.ReactNode;
}) {
  return (
    <LocaleContext.Provider value={lang}>{children}</LocaleContext.Provider>
  );
}

export function useLocale(): Lang {
  return useContext(LocaleContext);
}

export function useT(): Translate {
  const lang = useLocale();
  return useMemo(() => translate(lang), [lang]);
}
