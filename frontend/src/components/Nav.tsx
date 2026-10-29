"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { LanguageSwitcher } from "@/components/LanguageSwitcher";
import { useT } from "@/lib/LocaleProvider";
import type { MessageKey } from "@/lib/i18n";

const LINKS: { href: string; label: MessageKey }[] = [
  { href: "/recommendations", label: "nav.recommendations" },
  { href: "/search", label: "nav.search" },
  { href: "/profile", label: "nav.profile" },
];

export function Nav() {
  const pathname = usePathname();
  const t = useT();
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
      <LanguageSwitcher />
    </nav>
  );
}
