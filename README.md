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
cinemate tune --k 20,40,80 --lambda 2,5,10 --min-overlap 1,2,3
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

   При работе по HTTPS добавьте `--cookie-secure` (или `COOKIE_SECURE=1`), чтобы cookie сессии
   ставилась с флагом `Secure`.

   Проверка: <http://127.0.0.1:8000/api/health> и документация <http://127.0.0.1:8000/docs>.

4. **Фронтенд** (в другом терминале):

   ```
   cd frontend
   npm install
   cp .env.example .env.local   # API_INTERNAL_URL — адрес API; настройка CORS не нужна
   npm run dev
   ```

   Сайт: <http://localhost:3000>.

### Переменные окружения

| Переменная            | Где используется                                   | По умолчанию                |
| --------------------- | -------------------------------------------------- | --------------------------- |
| `DATABASE_URL`        | `import-movielens`, `enrich-movies`, `metrics`, `serve` (если нет `--database-url`) | `sqlite:///cinemate.db` |
| `TMDB_API_KEY`        | `enrich-movies`                                    | не задан (команда не работает) |
| `CORS_ORIGINS`        | API: источники для прямых запросов из браузера (через запятую, без `*`); нужен только если `NEXT_PUBLIC_API_URL` указывает на другой origin | `http://localhost:3000` |
| `COOKIE_SECURE`       | `serve`: флаг `Secure` у cookie сессии (`1/true/yes/on` — включить, `0/false/no/off` — выключить; `--cookie-secure` важнее) | выключено |
| `REC_K`               | API: число соседей рекомендателя (>= 1)            | `150`                       |
| `REC_LAMBDA`          | API: сила shrinkage (>= 0)                         | `40`                        |
| `REC_MIN_OVERLAP`     | API: минимум общих оценок у соседа (>= 1)          | `1`                         |
| `REC_POP_PENALTY`     | API: показатель штрафа за популярность (>= 0)      | `0.75`                      |
| `REC_SIGNIFICANCE`    | API: порог взвешивания сходства по числу общих оценок, `0` — выключено (>= 0) | `0`      |
| `REC_MIN_USER_RATINGS` | API: число оценок, с которого вместо запасной стратегии включается CF (>= 1) | `5`       |
| `REC_FALLBACK_POOL_FACTOR` | API: запасная стратегия выбирает из первых `pool_factor * n` по числу лайков; `1` — точный топ (>= 1) | `1` |
| `API_INTERNAL_URL`    | фронтенд (сервер Next.js): куда проксируются запросы `/api/*`; читается при каждом запросе | `http://127.0.0.1:8000` |
| `NEXT_PUBLIC_API_URL` | фронтенд: прямой адрес API в обход прокси (тогда нужен `CORS_ORIGINS`); после смены перезапустите `npm run dev` | пусто (тот же origin, `/api/...`) |
| `POSTGRES_PASSWORD`   | `docker-compose.yml`: пароль пользователя PostgreSQL | нет, обязателен для Docker |

### Типичные проблемы

- **Пустая лента или онбординг без карточек** — не выполнен `cinemate import-movielens`, либо
  API запущен с другой базой (проверьте `--database-url` / `DATABASE_URL` в обоих командах).
- **Запросы отвечают 502 `API unavailable`** — фронтенд не достучался до API: запустите
  `cinemate serve` и проверьте `API_INTERNAL_URL`.
- **Cookie сессии не ставится, запросы отвечают 401** — оставьте `NEXT_PUBLIC_API_URL` пустым:
  браузер ходит на `/api/*` фронтенда, и cookie остаётся first-party. Если вы указали прямой адрес
  API, открывайте сайт на `localhost:3000`, держите API на `localhost:8000` (не `127.0.0.1`), а
  `CORS_ORIGINS` должен точно совпадать с адресом сайта.
- **Нет постеров и описаний** — не выполнен `cinemate enrich-movies` (нужен `TMDB_API_KEY`).

## Docker

Весь продукт (PostgreSQL, API и фронтенд) поднимается одной командой. Драйвер PostgreSQL ставится
extra `postgres`; образ API собирается с ним.

1. Создайте `.env` и задайте `POSTGRES_PASSWORD` (шаблон — `.env.example`; значений по умолчанию
   в файлах нет):

   ```
   cp .env.example .env
   ```

2. Соберите и запустите сервисы (порядок задан healthcheck'ами: `db` → `api` → `frontend`):

   ```
   docker compose up --build -d
   ```

3. Выполните первичный импорт данных (один раз):

   ```
   docker compose run --rm app import-movielens --data-dir data
   docker compose run --rm app enrich-movies    # по желанию, нужен TMDB_API_KEY в .env
   ```

4. Откройте сайт: <http://localhost:3000>. API наружу не публикуется, фронтенд проксирует `/api`.

Другие разовые команды: `docker compose run --rm app metrics`. Сервис `app` относится к профилю
`tools`, поэтому `docker compose up` его не запускает.

Остановка: `docker compose down`; с удалением данных базы (том `pgdata`): `docker compose down -v`.

Данные MovieLens монтируются томом `./data`. Пароль подставляется в URL без кодирования —
используйте только URL-безопасные символы (без `@ / : #`). Контейнер работает от пользователя
uid 10001: каталог `./data` должен быть ему доступен на запись.

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
