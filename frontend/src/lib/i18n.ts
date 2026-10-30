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
  "footer.imdb": "Информация об оценках IMDb предоставлена IMDb (для личного и некоммерческого использования):",

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
  "recommendations.showMore": "Показать больше",
  "recommendations.showLess": "Свернуть",

  "explain.liked": "Понравилось {n} {people} с похожим вкусом",
  "explain.also": "; они же высоко оценили {titles}",
  "explain.and": "и",
  "explain.taste": "Вы часто лайкаете {name}",

  "profile.title": "Мои оценки",
  "profile.saveError": "Не удалось изменить оценку. Попробуйте ещё раз.",
  "profile.loadError":
    "Не удалось загрузить оценки. Проверьте соединение и попробуйте ещё раз.",
  "profile.empty": "Вы пока ничего не оценили.",
  "profile.rate": "Оценить фильмы",
  "profile.changeTo": "Изменить оценку фильма «{title}» на «{value}»",
  "profile.restart": "Начать заново",
  "profile.restartConfirm":
    "Ваши оценки на этом устройстве будут потеряны.",
  "profile.restartCancel": "Отмена",
  "profile.restartError": "Не удалось начать заново. Попробуйте ещё раз.",

  "categories.banner": "Опустили ниже:",
  "categories.count": "вы дизлайкнули {n} из {total}",
  "categories.show": "Показывать",
  "categories.hide": "Скрывать",
  "categories.showLabel": "Показывать категорию «{name}» в ленте",
  "categories.hideLabel": "Снова опускать категорию «{name}» в ленте",
  "categories.title": "Скрытые категории",
  "categories.hint":
    "Если вы дизлайкнули категорию целиком, её фильмы опускаются ниже в ленте. Вы можете вернуть их.",
  "categories.empty": "Пока ничего не скрыто.",
  "categories.shown": "показываем",
  "categories.hidden": "опущена ниже",
  "categories.saveError": "Не удалось сохранить выбор. Попробуйте ещё раз.",
  "categories.loadError": "Не удалось загрузить скрытые категории.",

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
  "footer.imdb": "IMDb ratings: information courtesy of IMDb, for personal and non-commercial use:",

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
  "recommendations.showMore": "Show more",
  "recommendations.showLess": "Show less",

  "explain.liked": "Liked by {n} {people} with similar taste",
  "explain.also": "; they also rated {titles} highly",
  "explain.and": "and",
  "explain.taste": "You often like {name}",

  "profile.title": "My ratings",
  "profile.saveError": "Could not change the rating. Please try again.",
  "profile.loadError":
    "Could not load your ratings. Check your connection and try again.",
  "profile.empty": "You haven't rated anything yet.",
  "profile.rate": "Rate movies",
  "profile.changeTo": "Change the rating of “{title}” to “{value}”",
  "profile.restart": "Start over",
  "profile.restartConfirm":
    "Your ratings on this device will be lost.",
  "profile.restartCancel": "Cancel",
  "profile.restartError": "Could not start over. Please try again.",

  "categories.banner": "Moved down:",
  "categories.count": "you disliked {n} of {total}",
  "categories.show": "Show",
  "categories.hide": "Hide",
  "categories.showLabel": "Show the category “{name}” in the feed",
  "categories.hideLabel": "Move the category “{name}” down in the feed again",
  "categories.title": "Hidden categories",
  "categories.hint":
    "If you disliked a whole category, its movies are moved lower in the feed. You can bring them back.",
  "categories.empty": "Nothing is hidden yet.",
  "categories.shown": "shown",
  "categories.hidden": "moved down",
  "categories.saveError": "Could not save your choice. Please try again.",
  "categories.loadError": "Could not load hidden categories.",

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
