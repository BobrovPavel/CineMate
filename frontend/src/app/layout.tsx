import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import { translate } from "@/lib/i18n";
import { LocaleProvider } from "@/lib/LocaleProvider";
import { getServerLanguage } from "@/lib/serverLocale";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = translate(await getServerLanguage());
  return { title: t("meta.title"), description: t("meta.description") };
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const lang = await getServerLanguage();
  const t = translate(lang);
  return (
    <html lang={lang}>
      <body className="flex min-h-screen flex-col antialiased">
        <LocaleProvider lang={lang}>
          <Nav />
          <div className="flex-1">{children}</div>
        </LocaleProvider>
        <footer className="border-t border-gray-200 px-4 py-6 text-sm text-gray-600">
          <p className="mx-auto max-w-2xl">
            {t("footer.data")}{" "}
            <a
              className="underline"
              href="https://grouplens.org/datasets/movielens/"
              target="_blank"
              rel="noopener noreferrer"
            >
              MovieLens (GroupLens)
            </a>
            . {t("footer.tmdbIntro")} This product uses the{" "}
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
          <p className="mx-auto mt-2 max-w-2xl">
            {t("footer.imdb")}{" "}
            <a
              className="underline"
              href="https://www.imdb.com/"
              target="_blank"
              rel="noopener noreferrer"
            >
              IMDb
            </a>
            .
          </p>
          <a
            className="mx-auto mt-3 block max-w-2xl"
            href="https://www.themoviedb.org/"
            target="_blank"
            rel="noopener noreferrer"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/tmdb-logo.svg" alt="TMDB" className="h-3.5 w-auto" />
          </a>
        </footer>
      </body>
    </html>
  );
}
