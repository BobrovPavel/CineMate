/** Текст обрезан, если его полная высота больше видимой. */
export function isClamped(scrollHeight: number, clientHeight: number): boolean {
  return scrollHeight > clientHeight;
}
