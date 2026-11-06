// Pure logic of the infinite recommendations feed: paging, dedup, saved state.

export const MIN_VISIBLE = 8;
export const FEED_TTL_MS = 30 * 60 * 1000;
export const FEED_STORAGE_KEY = "cinemate.feed";

/** At most one request at a time; nothing more to load when the feed is over. */
export function canRequestPage(state: {
  loading: boolean;
  hasMore: boolean;
  failed: boolean;
}): boolean {
  return !state.loading && state.hasMore && !state.failed;
}

/** After a reaction: load more when fewer than MIN_VISIBLE cards are left. */
export function needsRefill(visibleCount: number, min = MIN_VISIBLE): boolean {
  return visibleCount < min;
}

/** Append cards whose movie is neither shown nor reacted to; keeps the order. */
export function mergePage<T extends { movie: { id: number } }>(
  current: T[],
  incoming: T[],
  reacted: ReadonlySet<number> = new Set(),
): T[] {
  const known = new Set(current.map((c) => c.movie.id));
  const fresh: T[] = [];
  for (const card of incoming) {
    const id = card.movie.id;
    if (known.has(id) || reacted.has(id)) continue;
    known.add(id);
    fresh.push(card);
  }
  return fresh.length > 0 ? [...current, ...fresh] : current;
}

export type SavedFeed<T> = {
  savedAt: number;
  sessionId: string;
  items: T[];
  offset: number;
  hasMore: boolean;
  strategy: "collaborative" | "fallback";
  scrollY: number;
};

type Store = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function saveFeed<T>(
  store: Store,
  state: Omit<SavedFeed<T>, "savedAt">,
  now: number = Date.now(),
): void {
  try {
    store.setItem(FEED_STORAGE_KEY, JSON.stringify({ ...state, savedAt: now }));
  } catch {
    // Storage full or blocked: the feed just won't be restored.
  }
}

/** The saved feed, or null if absent, malformed or older than FEED_TTL_MS. */
export function loadFeed<T>(
  store: Store,
  now: number = Date.now(),
): SavedFeed<T> | null {
  try {
    const raw = store.getItem(FEED_STORAGE_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as Partial<SavedFeed<T>>;
    if (
      typeof data.savedAt !== "number" ||
      typeof data.sessionId !== "string" ||
      !Array.isArray(data.items) ||
      typeof data.offset !== "number" ||
      typeof data.hasMore !== "boolean" ||
      typeof data.scrollY !== "number" ||
      (data.strategy !== "collaborative" && data.strategy !== "fallback")
    ) {
      return null;
    }
    if (now - data.savedAt >= FEED_TTL_MS || now < data.savedAt) {
      store.removeItem(FEED_STORAGE_KEY);
      return null;
    }
    return data as SavedFeed<T>;
  } catch {
    return null;
  }
}

export function clearFeed(store: Store): void {
  try {
    store.removeItem(FEED_STORAGE_KEY);
  } catch {
    // ignore
  }
}
