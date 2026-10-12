/** Russian plural form for "человек": 1 человеку (21, 31…), иначе людям (2–4, 5+, 11). */
export function pluralPeople(n: number): string {
  const mod100 = n % 100;
  const mod10 = n % 10;
  if (mod10 === 1 && mod100 !== 11) return "человеку";
  return "людям";
}

export function explainCollaborative(likedBy: number, becauseOf: string[]): string {
  let text = `Понравилось ${likedBy} ${pluralPeople(likedBy)} с похожим вкусом`;
  const titles = becauseOf.slice(0, 3).map((t) => `«${t}»`);
  if (titles.length > 0) {
    const joined =
      titles.length === 1 ? titles[0] : `${titles.slice(0, -1).join(", ")} и ${titles.at(-1)}`;
    text += `; они же высоко оценили ${joined}`;
  }
  return text;
}
