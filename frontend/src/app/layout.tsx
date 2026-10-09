import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CineMate — что посмотреть сегодня",
  description: "Рекомендации фильмов по вашему вкусу: пара минут онбординга — и список с объяснением.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru">
      <body className="flex min-h-screen flex-col antialiased">
        <div className="flex-1">{children}</div>
        <footer className="border-t border-gray-200 px-4 py-6 text-sm text-gray-600">
          <p className="mx-auto max-w-2xl">
            Данные о фильмах и оценках —{" "}
            <a
              className="underline"
              href="https://grouplens.org/datasets/movielens/"
              target="_blank"
              rel="noopener noreferrer"
            >
              MovieLens (GroupLens)
            </a>
            . This product uses the{" "}
            <a
              className="underline"
              href="https://www.themoviedb.org/"
              target="_blank"
              rel="noopener noreferrer"
            >
              TMDB
            </a>{" "}
            API but is not endorsed or certified by TMDB.
          </p>
        </footer>
      </body>
    </html>
  );
}
