/** The one list of interface languages. To add one: an entry here and translations in i18n.ts. */
export const LANGUAGES = [
  { code: "ru", label: "RU", name: "Русский", flag: "🇷🇺" },
  { code: "en", label: "EN", name: "English", flag: "🇬🇧" },
] as const;

export type Language = (typeof LANGUAGES)[number];
export type Lang = Language["code"];

export const FALLBACK_LANG: Lang = "en";

export function languageByCode(code: Lang): Language {
  return LANGUAGES.find((l) => l.code === code) ?? LANGUAGES[0];
}

export const LANG_COOKIE = "cinemate_lang";
export const LANG_COOKIE_MAX_AGE = 365 * 24 * 3600;

export function isLang(value: string | null | undefined): value is Lang {
  return LANGUAGES.some((l) => l.code === value);
}

/** The most preferred tag of an Accept-Language header (lowercase), as in the API. */
function preferredTag(header: string | null | undefined): string | null {
  let best: string | null = null;
  let bestQ = 0;
  for (const part of (header ?? "").split(",")) {
    const [rawLang, ...params] = part.split(";").map((p) => p.trim());
    if (!rawLang) continue;
    let q = 1;
    for (const param of params) {
      const [key, value = ""] = param.split("=");
      if (key.trim().toLowerCase() === "q") {
        const parsed = Number(value);
        q = value.trim() !== "" && Number.isFinite(parsed) ? parsed : 0;
      }
    }
    if (q > bestQ) {
      best = rawLang.toLowerCase();
      bestQ = q;
    }
  }
  return best;
}

/** The one language rule: a valid cookie, else the browser's main language if listed, else en. */
export function pickLanguage(
  cookieLang: string | null | undefined,
  acceptLanguage: string | null | undefined,
): Lang {
  if (isLang(cookieLang)) return cookieLang;
  const primary = preferredTag(acceptLanguage)?.split("-")[0];
  return isLang(primary) ? primary : FALLBACK_LANG;
}

/** Remember the choice for a year and reload so the server renders in the new language. */
export function setLanguage(lang: Lang): void {
  document.cookie = `${LANG_COOKIE}=${lang}; path=/; max-age=${LANG_COOKIE_MAX_AGE}; SameSite=Lax`;
  window.location.reload();
}

export type Pool = "ru" | "world";

/** True when the site language would put a new user in a different pool than the current one. */
export function poolMismatchesLang(pool: string, lang: Lang): boolean {
  return pool !== (lang === "ru" ? "ru" : "world");
}
