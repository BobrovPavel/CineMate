export type DisplayTitle = { primary: string; secondary: string | null };

/** Russian title first (original below) when the browser language is Russian. */
export function displayTitle(
  movie: { title: string; title_ru: string | null },
  locale: string,
): DisplayTitle {
  if (locale.toLowerCase().startsWith("ru") && movie.title_ru) {
    return {
      primary: movie.title_ru,
      secondary: movie.title_ru === movie.title ? null : movie.title,
    };
  }
  return { primary: movie.title, secondary: null };
}
