import type { Metadata } from "next";

import { MovieView } from "@/components/MovieView";
import { translate } from "@/lib/i18n";
import { fetchMovieOnServer } from "@/lib/serverApi";
import { getServerLanguage } from "@/lib/serverLocale";

type Props = { params: Promise<{ id: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const movieId = Number(id);
  const t = translate(await getServerLanguage());
  const movie = Number.isInteger(movieId) ? await fetchMovieOnServer(movieId) : null;
  return { title: movie ? movie.display_title : t("movie.tabTitle") };
}

export default async function MoviePage({ params }: Props) {
  const { id } = await params;
  return <MovieView movieId={Number(id)} />;
}
