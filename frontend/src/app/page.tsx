import Link from "next/link";

import { translate } from "@/lib/i18n";
import { getServerLanguage } from "@/lib/serverLocale";

export default async function Home() {
  const t = translate(await getServerLanguage());
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-12">
      <h1 className="text-3xl font-bold">CineMate</h1>
      <p className="text-lg">{t("home.lead")}</p>
      <Link
        href="/onboarding"
        className="inline-flex min-h-12 items-center justify-center rounded-lg bg-black px-6 text-white"
      >
        {t("home.start")}
      </Link>
    </main>
  );
}
