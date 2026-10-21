# ML_CRITEION

Стенд сравнения машинного обучения в PostgreSQL + Apache MADlib и Python + scikit-learn.

Реализован сквозной сценарий линейной регрессии: регистрация источника, неизменяемая версия датасета, общее train/test-разбиение, матрица запусков, отдельные процессы обучения, метрики и JSON-артефакты. API и worker используют отдельную PostgreSQL для метаданных и очереди.

- [Запуск и примеры API](docs/development.md)
- [Результаты проверок и исправление MADlib](docs/validation.md)
- [Измерения CPU/RAM, парная статистика и рекомендации](docs/measurement-and-recommendations.md)
- [Frontend: Vue 3, TypeScript и Yarn](docs/frontend.md)
- [Целевая архитектура](docs/backend-architecture.md)
- [План реализации](docs/backend-implementation-plan.md)

```powershell
docker compose --profile bench up -d --build bench-db
docker compose up -d --build api worker frontend
```

Приложение: [ML Criterion](http://localhost:8080). Документация API: [Swagger UI](http://localhost:8000/docs). Диагностические задания включаются отдельно через `ML_ENABLE_DIAGNOSTIC_JOBS=true`.

Проверки реальных адаптеров и очереди:

```powershell
docker compose --profile bench --profile bench-test build benchmark-tests
docker compose --profile bench --profile bench-test run --rm benchmark-tests
```
