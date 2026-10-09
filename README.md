# CineMate

CineMate — рекомендательный сервис фильмов: пользователь ставит лайки и дизлайки, а
user-based коллаборативная фильтрация подбирает, что посмотреть дальше. Когда данных мало,
используется запасной вариант — популярные и хорошо оценённые фильмы. Сначала отлаживается
алгоритм на MovieLens (метрики precision/recall), потом строится сайт. Подробнее — в
[docs/VISION.md](docs/VISION.md).

## Установка

Нужен Python 3.12+.

```
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Команды

```
cinemate --version
```

### `cinemate evaluate`

Скачивает MovieLens (`ml-latest-small`) при первом запуске и печатает таблицу метрик
«коллаборативная фильтрация против популярного».

```
cinemate evaluate --k 40 --lambda 5 --min-overlap 5 --top-n 10 --seed 0
```

Аргументы: `--data-dir` (по умолчанию `data`), `--k`, `--lambda`, `--min-overlap`,
`--top-n`, `--seed`.

### `cinemate tune`

Перебирает значения параметров и выводит таблицу, отсортированную по precision. Параметры
принимают списки через запятую.

```
cinemate tune --k 20,40,80 --lambda 2,5,10 --min-overlap 3,5,8
```

Аргументы: `--data-dir`, `--k`, `--lambda`, `--min-overlap`, `--top-n`, `--seed`.

### `cinemate import-movielens`

Идемпотентно импортирует фильмы, пользователей и оценки MovieLens в базу данных. Поле
`Movie.popularity_score` пересчитывается как число лайков (`+1`) фильма; без лайков — `0.0`.

```
cinemate import-movielens --database-url sqlite:///cinemate.db --data-dir data
```

### `cinemate enrich-movies`

Дополняет фильмы с `tmdb_id` описанием, постером и длительностью через TMDB. Требуется
переменная окружения `TMDB_API_KEY`.

```
export TMDB_API_KEY=...
cinemate enrich-movies --database-url sqlite:///cinemate.db --limit 100
```

## Переменные окружения

| Переменная     | Назначение                                                        |
| -------------- | ----------------------------------------------------------------- |
| `TMDB_API_KEY` | ключ TMDB API для `enrich-movies`                                 |
| `DATABASE_URL` | URL БД для `import-movielens`, `enrich-movies`, `metrics`         |

URL базы данных выбирается так: аргумент `--database-url` → переменная `DATABASE_URL` →
`sqlite:///cinemate.db`. Шаблон переменных — в `.env.example`; настоящий `.env` не
коммитьте (он в `.gitignore`). CLI сам `.env` не читает: экспортируйте переменные в
окружение.

## Docker

Для запуска CLI в контейнере с PostgreSQL нужен `.env` с `POSTGRES_PASSWORD` (шаблон —
`.env.example`; значения по умолчанию в файлах нет). Драйвер PostgreSQL ставится extra
`postgres` (`pip install ".[postgres]"`); образ собирается с ним.

```
docker compose run --rm app import-movielens
docker compose run --rm app enrich-movies    # нужен TMDB_API_KEY в .env
docker compose run --rm app metrics
```

Данные MovieLens монтируются томом `./data`, база — в томе `pgdata`.

## Разработка

```
ruff check .
ruff format --check .
pytest
```

## Данные и лицензии

Проект некоммерческий.

- **MovieLens** — набор данных GroupLens Research (<https://grouplens.org/datasets/movielens/>);
  при использовании требуется атрибуция.
- **TMDB** — данные и изображения предоставлены TMDB; требуется атрибуция и логотип.
  This product uses the TMDB API but is not endorsed or certified by TMDB.

Открытые вопросы про лицензии данных — в [docs/VISION.md](docs/VISION.md).
