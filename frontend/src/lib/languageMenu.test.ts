import { describe, expect, it } from "vitest";

import { initialMenu, menuReducer, selectedLang } from "./languageMenu";

const open = { open: true, active: 0 };

describe("menuReducer", () => {
  it("toggle открывает на текущем языке и закрывает", () => {
    const opened = menuReducer(initialMenu(), { type: "toggle", current: "en" });
    expect(opened).toEqual({ open: true, active: 1 });
    expect(menuReducer(opened, { type: "toggle", current: "en" }).open).toBe(false);
  });

  it("стрелки двигают выбор в пределах списка", () => {
    const k = (state: typeof open, key: string) => menuReducer(state, { type: "key", key, current: "ru" });
    expect(k(open, "ArrowDown").active).toBe(1);
    expect(k({ open: true, active: 1 }, "ArrowDown").active).toBe(1);
    expect(k({ open: true, active: 1 }, "ArrowUp").active).toBe(0);
    expect(k(open, "ArrowUp").active).toBe(0);
    expect(k(open, "End").active).toBe(1);
    expect(k({ open: true, active: 1 }, "Home").active).toBe(0);
  });

  it("стрелка и Enter открывают закрытый список", () => {
    for (const key of ["ArrowDown", "ArrowUp", "Enter", " "]) {
      expect(menuReducer(initialMenu(), { type: "key", key, current: "en" })).toEqual({
        open: true,
        active: 1,
      });
    }
  });

  it("Escape, Tab и close закрывают, прочие клавиши ничего не меняют", () => {
    expect(menuReducer(open, { type: "key", key: "Escape", current: "ru" }).open).toBe(false);
    expect(menuReducer(open, { type: "key", key: "Tab", current: "ru" }).open).toBe(false);
    expect(menuReducer(open, { type: "close" }).open).toBe(false);
    expect(menuReducer(open, { type: "key", key: "a", current: "ru" })).toBe(open);
    expect(menuReducer(initialMenu(), { type: "key", key: "Escape", current: "ru" })).toEqual(
      initialMenu(),
    );
  });
});

describe("selectedLang", () => {
  it("Enter/Space выбирают активный язык, если он не текущий", () => {
    expect(selectedLang({ open: true, active: 1 }, "Enter", "ru")).toBe("en");
    expect(selectedLang({ open: true, active: 1 }, " ", "ru")).toBe("en");
    expect(selectedLang({ open: true, active: 1 }, "Enter", "en")).toBeNull();
    expect(selectedLang({ open: true, active: 1 }, "ArrowDown", "ru")).toBeNull();
    expect(selectedLang({ open: false, active: 1 }, "Enter", "ru")).toBeNull();
  });
});
