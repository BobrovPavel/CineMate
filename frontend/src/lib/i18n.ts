import type { Lang } from "./locale";

const ru = {
  "meta.title": "CineMate — что посмотреть сегодня",
  "meta.description":
    "Рекомендации фильмов по вашему вкусу: пара минут онбординга — и список с объяснением.",

  "nav.label": "Основная навигация",
  "nav.recommendations": "Подборка",
  "nav.search": "Поиск",
  "nav.profile": "Мои оценки",
  "nav.language": "Язык интерфейса",

  "footer.data": "Данные о фильмах и оценках —",
  "footer.tmdbIntro": "Уведомление TMDB:",

  "home.lead":
    "Ответим на вопрос, что посмотреть сегодня: пара минут онбординга — и список из 10–20 фильмов с объяснением.",
  "home.start": "Начать",

  "common.loading": "Загрузка…",
  "common.retry": "Повторить",
  "poster.alt": "Постер фильма «{title}»",
  "poster.missing": "Постер отсутствует",
  "poster.none": "Нет постера",

  "reaction.like": "Нравится",
  "reaction.dislike": "Не нравится",
  "reaction.notSeen": "Не смотрел",
  "reaction.watched": "Уже смотрел",
  "reaction.notInterested": "Не интересует",

  "onboarding.progress": "{current} из {total}",
  "onboarding.skip": "Пропустить",
  "onboarding.loadError":
    "Не удалось загрузить карточки. Проверьте соединение и попробуйте ещё раз.",
  "onboarding.done": "Карточки закончились.",
  "onboarding.toRecommendations": "Перейти к рекомендациям",
  "onboarding.saveError": "Не удалось сохранить ответ. Нажмите кнопку ещё раз.",
  "onboarding.enough": "Хватит, покажи рекомендации",

  "recommendations.title": "Рекомендации",
  "recommendations.fallback":
    "Пока это просто популярное — оцените ещё несколько фильмов, и подборка станет точнее.",
  "recommendations.rateMore": "Оценить фильмы",
  "recommendations.reactError":
    "Не удалось сохранить реакцию. Попробуйте ещё раз.",
  "recommendations.loadError":
    "Не удалось загрузить рекомендации. Проверьте соединение и попробуйте ещё раз.",
  "recommendations.empty": "Фильмы закончились — загляните позже.",
  "recommendations.buttonLabel": "{action}: {title}",

  "explain.liked": "Понравилось {n} {people} с похожим вкусом",
  "explain.also": "; они же высоко оценили {titles}",
  "explain.and": "и",

  "profile.title": "Мои оценки",
  "profile.saveError": "Не удалось изменить оценку. Попробуйте ещё раз.",
  "profile.loadError":
    "Не удалось загрузить оценки. Проверьте соединение и попробуйте ещё раз.",
  "profile.empty": "Вы пока ничего не оценили.",
  "profile.rate": "Оценить фильмы",
  "profile.changeTo": "Изменить оценку фильма «{title}» на «{value}»",
  "profile.pool.ru": "Рекомендации на основе оценок русскоязычных зрителей",
  "profile.pool.world": "Рекомендации на основе оценок MovieLens",
  "profile.restart": "Начать заново",
  "profile.restartConfirm":
    "Ваши оценки на этом устройстве будут потеряны. Новый профиль получит набор оценок по текущему языку сайта.",
  "profile.restartCancel": "Отмена",
  "profile.restartError": "Не удалось начать заново. Попробуйте ещё раз.",
  "profile.restartHint.ru":
    "Чтобы получать рекомендации по русскоязычным зрителям, начните заново.",
  "profile.restartHint.world":
    "Чтобы получать рекомендации по оценкам MovieLens, начните заново.",

  "search.title": "Поиск",
  "search.label": "Название фильма или сериала",
  "search.hint": "Введите хотя бы два символа, чтобы найти фильм или сериал.",
  "search.searching": "Ищем…",
  "search.unavailable": "Поиск недоступен: на сервере не задан ключ TMDB.",
  "search.error": "Не удалось выполнить поиск. Попробуйте ещё раз чуть позже.",
  "search.empty": "Ничего не найдено.",
  "search.saveError": "Не удалось сохранить. Попробуйте ещё раз.",
  "search.tv": "Сериал",
  "search.watched": "Смотрел",
} as const;

export type MessageKey = keyof typeof ru;

const en: Record<MessageKey, string> = {
  "meta.title": "CineMate — what to watch today",
  "meta.description":
    "Movie recommendations for your taste: a couple of minutes of onboarding, then a list with explanations.",

  "nav.label": "Main navigation",
  "nav.recommendations": "For you",
  "nav.search": "Search",
  "nav.profile": "My ratings",
  "nav.language": "Interface language",

  "footer.data": "Movie data and ratings —",
  "footer.tmdbIntro": "TMDB notice:",

  "home.lead":
    "We answer what to watch today: a couple of minutes of onboarding, then a list of 10–20 movies with explanations.",
  "home.start": "Start",

  "common.loading": "Loading…",
  "common.retry": "Retry",
  "poster.alt": "Poster of “{title}”",
  "poster.missing": "No poster",
  "poster.none": "No poster",

  "reaction.like": "Like",
  "reaction.dislike": "Dislike",
  "reaction.notSeen": "Haven't seen",
  "reaction.watched": "Already seen",
  "reaction.notInterested": "Not interested",

  "onboarding.progress": "{current} of {total}",
  "onboarding.skip": "Skip",
  "onboarding.loadError":
    "Could not load the cards. Check your connection and try again.",
  "onboarding.done": "No more cards.",
  "onboarding.toRecommendations": "Go to recommendations",
  "onboarding.saveError": "Could not save your answer. Press the button again.",
  "onboarding.enough": "Enough, show recommendations",

  "recommendations.title": "Recommendations",
  "recommendations.fallback":
    "For now these are just popular movies — rate a few more and the list will get more accurate.",
  "recommendations.rateMore": "Rate movies",
  "recommendations.reactError":
    "Could not save your reaction. Please try again.",
  "recommendations.loadError":
    "Could not load recommendations. Check your connection and try again.",
  "recommendations.empty": "No more movies — check back later.",
  "recommendations.buttonLabel": "{action}: {title}",

  "explain.liked": "Liked by {n} {people} with similar taste",
  "explain.also": "; they also rated {titles} highly",
  "explain.and": "and",

  "profile.title": "My ratings",
  "profile.saveError": "Could not change the rating. Please try again.",
  "profile.loadError":
    "Could not load your ratings. Check your connection and try again.",
  "profile.empty": "You haven't rated anything yet.",
  "profile.rate": "Rate movies",
  "profile.changeTo": "Change the rating of “{title}” to “{value}”",
  "profile.pool.ru": "Recommendations based on Russian-speaking viewers",
  "profile.pool.world": "Recommendations based on MovieLens ratings",
  "profile.restart": "Start over",
  "profile.restartConfirm":
    "Your ratings on this device will be lost. The new profile will get a set of ratings for the current site language.",
  "profile.restartCancel": "Cancel",
  "profile.restartError": "Could not start over. Please try again.",
  "profile.restartHint.ru":
    "To get recommendations based on Russian-speaking viewers, start over.",
  "profile.restartHint.world":
    "To get recommendations based on MovieLens ratings, start over.",

  "search.title": "Search",
  "search.label": "Movie or TV show title",
  "search.hint": "Type at least two characters to find a movie or TV show.",
  "search.searching": "Searching…",
  "search.unavailable": "Search is unavailable: the server has no TMDB key.",
  "search.error": "Search failed. Please try again a bit later.",
  "search.empty": "Nothing found.",
  "search.saveError": "Could not save. Please try again.",
  "search.tv": "TV show",
  "search.watched": "Seen",
};

export const MESSAGES: Record<Lang, Record<MessageKey, string>> = { ru, en };

export type PluralForms = Partial<Record<Intl.LDMLPluralRule, string>> & {
  other: string;
};

/** Noun forms by plural category; Russian needs one/few/many, English one/other. */
export const PLURALS = {
  movie: {
    ru: { one: "фильм", few: "фильма", many: "фильмов", other: "фильма" },
    en: { one: "movie", other: "movies" },
  },
  people: {
    ru: { one: "человеку", other: "людям" },
    en: { one: "person", other: "people" },
  },
} satisfies Record<string, Record<Lang, PluralForms>>;

export type PluralKey = keyof typeof PLURALS;

/** The form of noun ``key`` that agrees with the integer ``n`` ("1 фильм", "2 фильма", "5 фильмов"). */
export function plural(lang: Lang, key: PluralKey, n: number): string {
  const forms: PluralForms = PLURALS[key][lang];
  return forms[new Intl.PluralRules(lang).select(n)] ?? forms.other;
}

export type Vars = Record<string, string | number>;
export type Translate = (key: MessageKey, vars?: Vars) => string;

export function format(template: string, vars: Vars = {}): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    name in vars ? String(vars[name]) : match,
  );
}

export function translate(lang: Lang): Translate {
  return (key, vars) => format(MESSAGES[lang][key], vars);
}
