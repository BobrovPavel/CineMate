import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

describe("страница рекомендаций", () => {
  const page = readFileSync(
    join(__dirname, "../app/recommendations/page.tsx"),
    "utf8",
  );

  it("больше не запрашивает category-prefs и не показывает плашку", () => {
    expect(page).not.toContain("category-prefs");
    expect(page).not.toContain("fetchCategoryPrefs");
    expect(page).not.toContain("postCategoryPref");
    expect(page).not.toContain("HiddenCategoriesBanner");
  });
});
