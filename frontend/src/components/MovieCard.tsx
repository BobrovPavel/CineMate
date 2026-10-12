import { TMDB_IMAGE_BASE, type OnboardingCard } from "@/lib/api";

export function MovieCard({ card }: { card: OnboardingCard }) {
  const meta = [card.year, card.genres.join(", ")].filter(Boolean).join(" · ");
  return (
    <article className="flex flex-col items-center gap-3">
      <div className="aspect-[2/3] w-full max-w-60 overflow-hidden rounded-xl bg-gray-200">
        {card.poster_path ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={`${TMDB_IMAGE_BASE}${card.poster_path}`}
            alt={`Постер фильма «${card.title}»`}
            className="h-full w-full object-cover"
            draggable={false}
          />
        ) : (
          <div
            className="flex h-full w-full items-center justify-center p-4 text-center text-gray-500"
            role="img"
            aria-label="Постер отсутствует"
          >
            Постер отсутствует
          </div>
        )}
      </div>
      <h2 className="text-center text-xl font-semibold">{card.title}</h2>
      {meta && <p className="text-center text-sm text-gray-600">{meta}</p>}
    </article>
  );
}

export function CardSkeleton() {
  return (
    <div className="flex animate-pulse flex-col items-center gap-3" aria-busy="true">
      <div className="aspect-[2/3] w-full max-w-60 rounded-xl bg-gray-200" />
      <div className="h-6 w-48 rounded bg-gray-200" />
      <div className="h-4 w-32 rounded bg-gray-200" />
      <span className="sr-only">Загрузка…</span>
    </div>
  );
}
