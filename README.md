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
Названия приводятся к читаемому виду («Blair Witch Project, The» → «The Blair Witch Project»,
альтернативное название из скобок уходит в пустое `original_title`); повторный запуск
обновляет названия уже импортированных фильмов.

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

Команда также сохраняет русское название (`Movie.title_ru`): при языке браузера `ru` сайт
показывает его крупно, а оригинальное название — ниже в скобках. Название считается русским,
если в нём есть кириллица (если перевода нет, TMDB отдаёт оригинал, он не сохраняется).
Постер и другие поля сохраняются, даже если у TMDB нет русского описания.

Порядок: `enrich-movies` для новых фильмов, затем `enrich-movies --refresh-titles` для уже
обогащённых раньше — он запрашивает фильмы с `tmdb_id` без `title_ru` и дописывает только
название (`--limit` работает в обоих режимах):

```
cinemate enrich-movies --refresh-titles --limit 100
```

## Оценка на внешнем наборе оценок

`evaluate` и `tune` умеют читать оценки не только из MovieLens, но и из своего `ratings.csv` (шкала 1–10), без БД и без сети. Файл — с заголовком, порядок колонок произвольный, лишние колонки игнорируются:

```
user_id,movie_id,title_ru,title_original,type,year,genres,kp_rating,user_rating
18481579,9353768,Холодец-молодец,,MiniSeries,2025,"комедия, драма",,9
```

Обязательны `user_id`, `movie_id` (целые) и `user_rating` (целое 1–10); остальные необязательны, `genres` — список через запятую. При повторе пары (пользователь, фильм) побеждает последняя строка.

```
cinemate evaluate --source csv --ratings-csv data/ratings.csv
cinemate tune --source csv --ratings-csv data/ratings.csv --types Film,TvSeries
```

- `--types Film,TvSeries,…` — оставить только фильмы указанных типов (без учёта регистра; строки без `type` отбрасываются); по умолчанию все.
- `--rel-threshold` (по умолчанию `0.5`, строго больше 0) — оценка, превышающая личное среднее пользователя на этот порог и больше, это лайк (`+1`), ниже среднего на порог и больше — дизлайк (`-1`), остальные отбрасываются. Пользователи с менее чем 20 оценками отбрасываются целиком.
- Допущение: среднее считается один раз на пользователя по всем оценкам файла, поэтому тестовые оценки входят в него и дают небольшое смещение.

Перед таблицей печатается сводка по набору данных (пользователи, фильмы, оценки, плотность, доли `+1`/`-1`/отброшенных) — для обоих источников, чтобы сравнение с MovieLens было честным.

## Внешний набор оценок

Оценки из `ratings.csv` (формат — в разделе выше) можно загрузить в ту же БД, что и MovieLens: фильмы, пользователей и оценки. Порядок команд:

```
cinemate migrate
cinemate import-movielens
cinemate import-ratings-csv --file data/ratings.csv [--types Film,TvSeries] [--rel-threshold 0.5]
```

В Docker: `docker compose run --rm app import-ratings-csv --file data/ratings.csv`.

- Файл кладите в `data/` — каталог не коммитится.
- Фильмы, общие с MovieLens, склеиваются в одну запись по нормализованному `title_original` и году (сравнение с `title` и `original_title`); `title` существующего фильма не меняется, ему проставляется `external_ratings_id`. Неоднозначные случаи (несколько кандидатов или конфликт) создают отдельный фильм и попадают в `movies ambiguous`.
- Пользователи хранятся как `is_synthetic=True`, только с идентификатором из файла, без имён; создаются при наличии хотя бы одной оценки (пользователи с менее чем 20 оценками остаются без оценок и не создаются). Сырые оценки 1–10 не хранятся, только `+1`/`-1`.
- Повторный запуск ничего не добавляет и не меняет; `Movie.popularity_score` пересчитывается.
- Постеры и описания для таких фильмов не подтягиваются: у них нет `tmdb_id`.

## Переменные окружения

| Переменная     | Назначение                                                        |
| -------------- | ----------------------------------------------------------------- |
| `TMDB_API_KEY` | ключ TMDB API для `enrich-movies` и поиска в API (`serve`)        |
| `DATABASE_URL` | URL БД для `import-movielens`, `import-ratings-csv`, `enrich-movies`, `metrics`, `serve` |

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
| `TMDB_API_KEY`        | `enrich-movies`, `serve` (поиск фильмов `/api/search`) | не задан (команда не работает, поиск отвечает 503) |
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

## Пулы пользователей

Пользователи делятся на два пула, `users.pool`: `ru` и `world`. Соседи, «популярное» (запасная
стратегия) и карточки онбординга считаются только по оценкам пользователей своего пула.

- **Назначение.** `POST /api/session` при создании пользователя читает `Accept-Language`: если
  язык с наибольшим приоритетом — русский (`ru`, `ru-RU`), пул `ru`, иначе (в том числе без
  заголовка) `world`. Пул сохраняется один раз и дальше не меняется; он возвращается в ответе
  `POST /api/session` (поле `pool`).
- **Данные пула `ru`** — набор оценок владельца: `cinemate import-ratings-csv` создаёт
  пользователей с `pool='ru'`.
- **Данные пула `world`** — MovieLens: `cinemate import-movielens` создаёт пользователей с
  `pool='world'`. Оценки живых пользователей пополняют матрицу только их пула.
- **Миграция `0005`** добавляет колонку: существующие пользователи с `external_ratings_id`
  получают `ru`, остальные — `world`. Примените её командой `cinemate migrate`.

## Миграции базы

Схема БД управляется Alembic (`alembic.ini`, каталог `migrations/`). URL базы берётся так же, как
у остальных команд: `--database-url`, затем `DATABASE_URL`, затем `sqlite:///cinemate.db`.

- Применить миграции: `cinemate migrate` (то же, что `alembic upgrade head`). Повторный запуск
  ничего не меняет.
- Локальная база, созданная раньше без миграций (через `create_all`): один раз выполните
  `cinemate migrate --stamp-existing` — команда проставит последнюю ревизию, не трогая таблицы и
  данные; дальше работает обычный `cinemate migrate`.
- Создать ревизию после изменения `cinemate/db/models.py`:
  `alembic revision --autogenerate -m "описание"`, проверьте файл в `migrations/versions/` и
  примените его через `cinemate migrate`.
- `cinemate serve` на in-memory SQLite создаёт схему сам; пустой файл SQLite (в том числе
  `cinemate.db` по умолчанию) инициализируется миграциями автоматически. На любой другой базе
  (например, PostgreSQL) сервер не стартует, пока схема не на актуальной ревизии: выполните
  `cinemate migrate`.

## Каталог фильмов

- `movies.id` — единственный ключ внутри системы: API, оценки и матрица работают только с ним.
- Главный внешний идентификатор — пара (`tmdb_type`, `tmdb_id`), где `tmdb_type` — `movie` или
  `tv` (у TMDB это разные пространства ID). Пара уникальна; у фильма, которого нет в TMDB, она
  пустая.
- Остальные внешние ID лежат в таблице `movie_external_ids` (`source`, `external_id`,
  `movie_id`): источники `movielens`, `imdb`, `kinopoisk`, `ratings_csv`. Один фильм может иметь
  несколько ID одного источника (дубли MovieLens), один ID принадлежит одному фильму.
- Поиск и привязка — `cinemate/db/catalog.py` (`find_movie`, `link`, `merge_movies`). Старые
  столбцы `external_*_id` и `imdb_id` пока остаются, но код читает ID из таблицы сопоставления.
- Миграция `0004` сливает фильмы с одинаковой парой TMDB: остаётся строка с минимальным `id`,
  оценки, отметки и события переносятся на неё (при оценках одного пользователя на оба дубля
  остаётся более поздняя; у отметок нет времени, берётся запись с большим `id`).

### Поиск любого фильма или сериала TMDB

Страница `/search` ищет по всему TMDB (более 1,4 млн названий), а не только по фильмам
MovieLens. Нужен `TMDB_API_KEY` в окружении `cinemate serve` (в `docker compose` он передаётся
сервису `api`); ключ остаётся на сервере и в браузер не попадает.

- `GET /api/search?q=&page=1` — `q` от 2 до 100 символов; язык запроса к TMDB `ru-RU`, если
  основной язык `Accept-Language` русский, иначе `en-US`. В ответе `movie_id` (наш ID, если
  фильм уже в каталоге) и `user_value` (оценка пользователя). Ответы TMDB кэшируются в памяти
  процесса (до 1000 запросов, 24 часа). Без ключа — 503, ошибка TMDB — 502.
- `POST /api/movies/resolve` с `{tmdb_type, tmdb_id}` создаёт фильм в каталоге (если его ещё нет)
  и возвращает карточку с нашим `id`; оценка ставится через `POST /api/ratings`.
- К TMDB не больше 20 запросов в секунду на процесс; на 429 выдерживается пауза по `Retry-After`
  и запрос повторяется один раз.

## Docker

Весь продукт (PostgreSQL, API и фронтенд) поднимается одной командой. Драйвер PostgreSQL ставится
extra `postgres`; образ API собирается с ним.

1. Создайте `.env` и задайте `POSTGRES_PASSWORD` (шаблон — `.env.example`; значений по умолчанию
   в файлах нет):

   ```
   cp .env.example .env
   ```

2. Примените миграции базы (до первого `up`: API не стартует на базе без актуальной схемы;
   команда сама поднимет `db`):

   ```
   docker compose run --rm app migrate
   ```

3. Соберите и запустите сервисы (порядок задан healthcheck'ами: `db` → `api` → `frontend`):

   ```
   docker compose up --build -d
   ```

4. Выполните первичный импорт данных (один раз):

   ```
   docker compose run --rm app import-movielens --data-dir data
   docker compose run --rm app enrich-movies    # по желанию, нужен TMDB_API_KEY в .env
   ```

5. Откройте сайт: <http://localhost:3000>. API наружу не публикуется, фронтенд проксирует `/api`.

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
