import { cookies, headers } from "next/headers";

import { LANG_COOKIE, pickLanguage, type Lang } from "./locale";

/** Language of the current request on the server (layout, metadata). */
export async function getServerLanguage(): Promise<Lang> {
  const [cookieStore, headerStore] = await Promise.all([cookies(), headers()]);
  return pickLanguage(
    cookieStore.get(LANG_COOKIE)?.value,
    headerStore.get("accept-language"),
  );
}
