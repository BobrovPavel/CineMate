import { describe, expect, it } from "vitest";

import { isClamped } from "./clamp";

describe("isClamped", () => {
  it("true, когда содержимое выше видимой области", () => {
    expect(isClamped(80, 60)).toBe(true);
  });

  it("false, когда текст помещается", () => {
    expect(isClamped(60, 60)).toBe(false);
    expect(isClamped(40, 60)).toBe(false);
  });
});
