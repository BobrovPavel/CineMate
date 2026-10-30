import { cookies, headers } from "next/headers";

import type { MovieDetail } from "./api";

const DEFAULT_API_INTERNAL_URL = "http://127.0.0.1:8000";

/** The movie for the tab title, fetched on the server with the visitor's cookie and language.
 *  ``null`` on any failure: the title then falls back to a generic one. */
export async function fetchMovieOnServer(id: number): Promise<MovieDetail | null> {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  const base = (process.env.API_INTERNAL_URL || DEFAULT_API_INTERNAL_URL).replace(/\/+$/, "");
  const forwarded = new Headers();
  const cookie = cookieStore.toString();
  if (cookie) forwarded.set("cookie", cookie);
  const language = headerStore.get("accept-language");
  if (language) forwarded.set("accept-language", language);
  try {
    const response = await fetch(`${base}/api/movies/${id}`, {
      headers: forwarded,
      cache: "no-store",
    });
    return response.ok ? ((await response.json()) as MovieDetail) : null;
  } catch {
    return null;
  }
}
