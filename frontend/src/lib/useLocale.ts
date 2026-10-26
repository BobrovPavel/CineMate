import { useEffect, useState } from "react";

/** Browser language; "en" on the server and the first client render to avoid hydration errors. */
export function useLocale(): string {
  const [locale, setLocale] = useState("en");
  useEffect(() => {
    setLocale(navigator.language || "en");
  }, []);
  return locale;
}
