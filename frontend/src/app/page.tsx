import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-12">
      <h1 className="text-3xl font-bold">CineMate</h1>
      <p className="text-lg">
        Ответим на вопрос, что посмотреть сегодня: пара минут онбординга — и список из 10–20
        фильмов с объяснением.
      </p>
      <Link
        href="/onboarding"
        className="inline-flex min-h-12 items-center justify-center rounded-lg bg-black px-6 text-white"
      >
        Начать
      </Link>
    </main>
  );
}
