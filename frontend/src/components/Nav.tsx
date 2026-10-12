"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/recommendations", label: "Подборка" },
  { href: "/profile", label: "Мои оценки" },
];

export function Nav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Основная навигация" className="border-b border-gray-200 px-4 py-3">
      <ul className="mx-auto flex max-w-6xl flex-wrap gap-4">
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
                {link.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
