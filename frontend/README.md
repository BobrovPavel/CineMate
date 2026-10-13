# CineMate frontend

Next.js (App Router), TypeScript (`strict`), Tailwind. Интерфейс на русском.

## Установка

```
npm install
cp .env.example .env.local   # API_INTERNAL_URL — адрес API (`cinemate serve`)
```

Браузер ходит на `/api/*` того же origin, а Next.js (`src/app/api/[...path]/route.ts`) проксирует
запросы на `API_INTERNAL_URL` (читается при каждом запросе), поэтому cookie сессии first-party и
CORS не нужен. `NEXT_PUBLIC_API_URL` задавайте только для прямых запросов к другому origin (тогда на
API нужен `CORS_ORIGINS`).

## Docker

```
docker build -t cinemate-frontend .
docker run -p 3000:3000 -e API_INTERNAL_URL=http://host.docker.internal:8000 cinemate-frontend
```

## Команды

```
npm run dev        # dev-сервер на http://localhost:3000
npm run build      # production-сборка
npm run lint       # ESLint
npm run typecheck  # tsc --noEmit
npm test           # Vitest (юнит-тесты src/lib)
```
