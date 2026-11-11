import { describe, expect, it } from "vitest";

import {
  canRequestPage,
  clearFeed,
  FEED_TTL_MS,
  loadFeed,
  mergePage,
  needsRefill,
  saveFeed,
} from "./feed";

const card = (id: number) => ({ movie: { id } });

function memoryStore() {
  const data = new Map<string, string>();
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
  };
}

const state = {
  sessionId: "abc",
  items: [card(1), card(2)],
  offset: 20,
  hasMore: true,
  strategy: "collaborative" as const,
  scrollY: 420,
};

describe("canRequestPage", () => {
  it("allows only one request at a time", () => {
    expect(canRequestPage({ loading: false, hasMore: true, failed: false })).toBe(true);
    expect(canRequestPage({ loading: true, hasMore: true, failed: false })).toBe(false);
  });
  it("stops at the end of the feed and after an error", () => {
    expect(canRequestPage({ loading: false, hasMore: false, failed: false })).toBe(false);
    expect(canRequestPage({ loading: false, hasMore: true, failed: true })).toBe(false);
  });
});

describe("needsRefill", () => {
  it("loads more below 8 visible cards", () => {
    expect(needsRefill(7)).toBe(true);
    expect(needsRefill(8)).toBe(false);
    expect(needsRefill(0)).toBe(true);
  });
});

describe("mergePage", () => {
  it("skips shown and reacted movies and duplicates inside the page", () => {
    const merged = mergePage(
      [card(1), card(2)],
      [card(2), card(3), card(3), card(4)],
      new Set([4]),
    );
    expect(merged.map((c) => c.movie.id)).toEqual([1, 2, 3]);
  });
  it("returns the same array when nothing is new", () => {
    const current = [card(1)];
    expect(mergePage(current, [card(1)])).toBe(current);
  });
});

describe("saved feed state", () => {
  it("restores what was saved", () => {
    const store = memoryStore();
    saveFeed(store, state, 1000);
    expect(loadFeed(store, 2000)).toEqual({ ...state, savedAt: 1000 });
  });
  it("expires after 30 minutes", () => {
    const store = memoryStore();
    saveFeed(store, state, 1000);
    expect(loadFeed(store, 1000 + FEED_TTL_MS - 1)).not.toBeNull();
    expect(loadFeed(store, 1000 + FEED_TTL_MS)).toBeNull();
    expect(loadFeed(store, 1000 + 1)).toBeNull();
  });
  it("ignores malformed data and can be cleared", () => {
    const store = memoryStore();
    store.setItem("cinemate.feed", "{oops");
    expect(loadFeed(store)).toBeNull();
    store.setItem("cinemate.feed", JSON.stringify({ sessionId: 1 }));
    expect(loadFeed(store)).toBeNull();
    saveFeed(store, state);
    clearFeed(store);
    expect(loadFeed(store)).toBeNull();
  });
  it("survives a failing storage", () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
      removeItem: () => {
        throw new Error("blocked");
      },
    };
    expect(() => saveFeed(broken, state)).not.toThrow();
    expect(loadFeed(broken)).toBeNull();
  });
});
