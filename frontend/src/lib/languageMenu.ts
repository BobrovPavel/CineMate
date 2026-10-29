import { LANGUAGES, type Lang } from "./locale";

export type MenuKey = "ArrowDown" | "ArrowUp" | "Home" | "End" | "Enter" | " " | "Escape" | "Tab";

export type MenuState = { open: boolean; active: number };

export type MenuAction =
  | { type: "toggle"; current: Lang }
  | { type: "close" }
  | { type: "key"; key: string; current: Lang };

export function indexOfLang(code: Lang): number {
  return Math.max(
    0,
    LANGUAGES.findIndex((l) => l.code === code),
  );
}

export function initialMenu(): MenuState {
  return { open: false, active: 0 };
}

/** Open/close and arrow-key logic of the language list; selection is `selectedLang`. */
export function menuReducer(state: MenuState, action: MenuAction): MenuState {
  const last = LANGUAGES.length - 1;
  switch (action.type) {
    case "toggle":
      return state.open
        ? { ...state, open: false }
        : { open: true, active: indexOfLang(action.current) };
    case "close":
      return state.open ? { ...state, open: false } : state;
    case "key": {
      const open = (active: number) => ({ open: true, active });
      switch (action.key) {
        case "ArrowDown":
          return state.open
            ? open(Math.min(state.active + 1, last))
            : open(indexOfLang(action.current));
        case "ArrowUp":
          return state.open
            ? open(Math.max(state.active - 1, 0))
            : open(indexOfLang(action.current));
        case "Home":
          return state.open ? open(0) : state;
        case "End":
          return state.open ? open(last) : state;
        case "Enter":
        case " ":
          return state.open ? state : open(indexOfLang(action.current));
        case "Escape":
        case "Tab":
          return state.open ? { ...state, open: false } : state;
        default:
          return state;
      }
    }
  }
}

/** The language chosen by Enter/Space on the active item, or null if nothing to choose. */
export function selectedLang(state: MenuState, key: string, current: Lang): Lang | null {
  if (!state.open || (key !== "Enter" && key !== " ")) return null;
  const code = LANGUAGES[state.active]?.code;
  return code && code !== current ? code : null;
}
