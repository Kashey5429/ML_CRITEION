# Конфигурация и эксплуатация стенда

Сервисы описаны в `compose.yaml`, образы — в `deploy/app`, `deploy/bench`, `frontend/Dockerfile`. Пошаговый старт и API-примеры — [development.md](development.md), интерфейс — [frontend.md](frontend.md).

| Сервис | Назначение и доступ |
| --- | --- |
| metadata-db | PostgreSQL приложения, localhost:55432, volume metadata |
| bench-db | PostgreSQL 15 + MADlib 2.1.0, профиль bench, localhost:55433, volume bench, 2 CPU / 2 GiB |
| migrate | Однократный alembic upgrade head после готовности metadata |
| api | FastAPI, localhost:8000, artifacts read-only |
| worker | Supervisor и дочерние процессы, 2 CPU / 1 GiB, artifacts read-write |
| frontend | Vue-статика и Nginx reverse proxy, localhost:8080 |
| preflight | Профиль bench, синтетическая проверка обучения двух подходов |
| tests / benchmark-tests | Профили test / bench-test, pytest против настоящих БД |

API ready не проверяет bench DB. Worker не зависит от bench health в Compose: перед серией отдельно проверьте стенд. Preflight запускается явно, не автоматически перед каждым run. Он проверяет PostgreSQL 15/MADlib 2.1.0, обучает модели на 80 строках и сравнивает 20 предсказаний; временные SQL-объекты откатываются. Это smoke test, не измерение производительности.

```powershell
docker compose --profile bench up -d --build bench-db
docker compose up -d --build api worker frontend
docker compose --profile bench run --rm preflight
docker compose ps
docker compose logs --tail 100 worker api
```

## Настройки Python

`Settings` читает ML_-переменные процесса и `.env`, игнорирует посторонние поля. Ниже значения по умолчанию; Compose переопределяет DSN внутренними именами сервисов.

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| ML_METADATA_URL | localhost:55432/criterion, dialect postgresql+psycopg | SQLAlchemy metadata |
| ML_BENCH_DSN | localhost:55433/bench | psycopg bench |
| ML_POLL_SECONDS | 1 | Пауза цикла очереди |
| ML_HEARTBEAT_SECONDS | 5 | Продление аренды |
| ML_LEASE_SECONDS | 30 | Аренда; минимум 3 heartbeat-интервала |
| ML_ENABLE_DIAGNOSTIC_JOBS | false | Разрешение искусственных diagnostic jobs |
| ML_SOURCE_SCHEMAS | ["public"] | JSON-массив разрешённых схем источников |
| ML_MAX_DATASET_ROWS | 1000000 | Максимум строк snapshot |
| ML_SKLEARN_MEMORY_MB | 512 | Бюджет предварительной оценки памяти |
| ML_ARTIFACT_ROOT | /artifacts | Корень файлов результатов |
| ML_RESOURCE_SAMPLE_SECONDS | 0.1 | Интервал sampling, диапазон 0.05–2 с |

Compose явно передаёт DSN, ML_ENABLE_DIAGNOSTIC_JOBS и ML_RESOURCE_SAMPLE_SECONDS. Для изменения других Python-настроек в контейнерах добавьте их в environment сервиса или Compose override: одно наличие переменной в хостовом `.env` не передаёт её контейнеру. Пароли Compose задаются METADATA_PASSWORD и BENCH_PASSWORD; смена значения не меняет пароль уже инициализированного PostgreSQL volume автоматически.

## Диагностика и восстановление

При failed сначала смотрите dataset_version.error_code либо `/experiments/{id}/attempts`. Для недоступных ресурсов проверьте cgroup v2 и функцию criterion_monitor.snapshot по [инструкции измерений](measurement-and-recommendations.md). При quarantined применяйте процедуру [worker.md](worker.md); CLI `release-quarantine --confirmed-stopped` допустима только после фактической проверки остановки старой нагрузки.

CLI реализует только worker, preflight и release-quarantine. Создание, отмена и экспорт экспериментов выполняются через API/UI, а не через несуществующие submit/export CLI-команды. Init SQL bench выполняется только при создании volume; изменения init-скриптов к существующей БД применяются отдельно. Данные не удаляются при обычном перезапуске сервисов.

Зависимости Python закреплены uv.lock, frontend — yarn.lock. Docker-теги и внешние apt-источники пока не закреплены по digest. Полные проверки и известные ограничения сборки — [validation.md](validation.md); воспроизводимая нагрузочная серия — [benchmark-series-2026-10-21.md](benchmark-series-2026-10-21.md).
