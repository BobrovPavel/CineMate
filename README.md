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
| `DATABASE_URL` | URL БД для `import-movielens`, `enrich-movies`, `metrics`, `serve` |

URL базы данных выбирается так: аргумент `--database-url` → переменная `DATABASE_URL` →
`sqlite:///cinemate.db`. Шаблон переменных — в `.env.example`; настоящий `.env` не
коммитьте (он в `.gitignore`). CLI сам `.env` не читает: экспортируйте переменные в
окружение.

## Запуск приложения локально

Путь от пустого репозитория до сайта на `localhost`. Нужны Python 3.12+ и Node.js.

1. **Python-часть** (см. «Установка» выше):

   ```
   python -m venv .venv && source .venv/bin/activate
   pip install -e ".[dev]"
   ```

2. **Данные.** Импорт MovieLens в SQLite (`cinemate.db` в текущем каталоге; MovieLens
   скачивается в `data/`):

   ```
   cinemate import-movielens --data-dir data
   ```

   Необязательно — постеры и описания из TMDB (нужен ключ):

   ```
   export TMDB_API_KEY=...
   cinemate enrich-movies --limit 200
   ```

3. **API:**

   ```
   cinemate serve --host 127.0.0.1 --port 8000
   ```

   Проверка: <http://127.0.0.1:8000/api/health> и документация <http://127.0.0.1:8000/docs>.

4. **Фронтенд** (в другом терминале):

   ```
   cd frontend
   npm install
   cp .env.example .env.local
   npm run dev
   ```

   Сайт: <http://localhost:3000>.

### Переменные окружения

| Переменная            | Где используется                                   | По умолчанию                |
| --------------------- | -------------------------------------------------- | --------------------------- |
| `DATABASE_URL`        | `import-movielens`, `enrich-movies`, `metrics`, `serve` (если нет `--database-url`) | `sqlite:///cinemate.db` |
| `TMDB_API_KEY`        | `enrich-movies`                                    | не задан (команда не работает) |
| `CORS_ORIGINS`        | API: источники, которым разрешены запросы из браузера (через запятую, без `*`) | `http://localhost:3000` |
| `REC_K`               | API: число соседей рекомендателя (>= 1)            | `40`                        |
| `REC_LAMBDA`          | API: сила shrinkage (>= 0)                         | `40`                        |
| `REC_MIN_OVERLAP`     | API: минимум общих оценок у соседа (>= 1)          | `3`                         |
| `REC_POP_PENALTY`     | API: показатель штрафа за популярность (>= 0)      | `1.0`                       |
| `NEXT_PUBLIC_API_URL` | фронтенд (`frontend/.env.local`): адрес API; после смены перезапустите `npm run dev` | `http://localhost:8000`     |
| `POSTGRES_PASSWORD`   | `docker-compose.yml`: пароль пользователя PostgreSQL | нет, обязателен для Docker |

### Типичные проблемы

- **Пустая лента или онбординг без карточек** — не выполнен `cinemate import-movielens`, либо
  API запущен с другой базой (проверьте `--database-url` / `DATABASE_URL` в обоих командах).
- **Cookie сессии не ставится, запросы отвечают 401** — хосты не совпадают: открывайте сайт
  на `localhost:3000`, а `NEXT_PUBLIC_API_URL` держите на `localhost:8000` (не
  `127.0.0.1`), и `CORS_ORIGINS` должен точно совпадать с адресом сайта.
- **Нет постеров и описаний** — не выполнен `cinemate enrich-movies` (нужен `TMDB_API_KEY`).

## Docker

Для запуска CLI в контейнере с PostgreSQL нужен `.env` с `POSTGRES_PASSWORD` (шаблон —
`.env.example`; значения по умолчанию в файлах нет). Драйвер PostgreSQL ставится extra
`postgres` (`pip install ".[postgres]"`); образ собирается с ним.

```
docker compose run --rm app import-movielens
docker compose run --rm app enrich-movies    # нужен TMDB_API_KEY в .env
docker compose run --rm app metrics
```

Данные MovieLens монтируются томом `./data`, база — в томе `pgdata`. Пароль подставляется в URL
без кодирования — используйте только URL-безопасные символы (без `@ / : #`). Контейнер работает
от пользователя uid 10001: каталог `./data` должен быть ему доступен на запись.

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
