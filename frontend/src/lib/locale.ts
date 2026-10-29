export type Lang = "ru" | "en";

export const LANG_COOKIE = "cinemate_lang";
export const LANG_COOKIE_MAX_AGE = 365 * 24 * 3600;

export function isLang(value: string | null | undefined): value is Lang {
  return value === "ru" || value === "en";
}

/** "ru" if the most preferred language of an Accept-Language header is Russian (as in the API). */
function acceptsRussian(header: string | null | undefined): boolean {
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
  return best === "ru" || (best?.startsWith("ru-") ?? false);
}

/** The one language rule: a valid cookie, else the browser language (ru), else en. */
export function pickLanguage(
  cookieLang: string | null | undefined,
  acceptLanguage: string | null | undefined,
): Lang {
  if (isLang(cookieLang)) return cookieLang;
  return acceptsRussian(acceptLanguage) ? "ru" : "en";
}

/** Remember the choice for a year and reload so the server renders in the new language. */
export function setLanguage(lang: Lang): void {
  document.cookie = `${LANG_COOKIE}=${lang}; path=/; max-age=${LANG_COOKIE_MAX_AGE}; SameSite=Lax`;
  window.location.reload();
}
