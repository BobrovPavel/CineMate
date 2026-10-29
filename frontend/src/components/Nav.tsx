"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { useLocale, useT } from "@/lib/LocaleProvider";
import { setLanguage, type Lang } from "@/lib/locale";
import type { MessageKey } from "@/lib/i18n";

const LINKS: { href: string; label: MessageKey }[] = [
  { href: "/recommendations", label: "nav.recommendations" },
  { href: "/search", label: "nav.search" },
  { href: "/profile", label: "nav.profile" },
];

const LANGS: Lang[] = ["ru", "en"];

export function Nav() {
  const pathname = usePathname();
  const t = useT();
  const lang = useLocale();
  return (
    <nav
      aria-label={t("nav.label")}
      className="flex items-center justify-between gap-4 border-b border-gray-200 px-4 py-3"
    >
      <ul className="mx-auto flex max-w-6xl flex-1 flex-wrap gap-4">
        {LINKS.map((link) => {
          const current = pathname === link.href;
          return (
            <li key={link.href}>
              <Link
                href={link.href}
                aria-current={current ? "page" : undefined}
                className={`inline-flex min-h-11 items-center px-1 ${
                  current ? "font-semibold underline" : "text-gray-700"
                }`}
              >
                {t(link.label)}
              </Link>
            </li>
          );
        })}
      </ul>
      <div
        role="group"
        aria-label={t("nav.language")}
        className="flex shrink-0 gap-1"
      >
        {LANGS.map((code) => (
          <button
            key={code}
            type="button"
            lang={code}
            aria-pressed={code === lang}
            onClick={() => {
              if (code !== lang) setLanguage(code);
            }}
            className={`min-h-11 min-w-11 rounded-lg px-2 text-sm ${
              code === lang
                ? "bg-black font-semibold text-white"
                : "text-gray-700"
            }`}
          >
            {code.toUpperCase()}
          </button>
        ))}
      </div>
    </nav>
  );
}
