# Метаданные, результаты и артефакты

Реализация: `persistence/models.py`, `persistence/db.py`, `migrations/`; запись JSON — `worker/benchmark.py`, выдача — `api/app.py`. Metadata PostgreSQL и bench PostgreSQL — разные экземпляры. Между ними и файловым volume нет распределённой транзакции.

## Metadata PostgreSQL

| Таблица | Назначение |
| --- | --- |
| datasets / dataset_versions | Spec источника, состояние версии, manifest/error_code |
| experiments | Неизменяемый spec, config_hash, статус, cancel_requested_at, итоговый analysis JSONB |
| idempotency_records | Связь ключа создания с hash и experiment |
| comparison_cases | Конфигурация варианта и общий prepared manifest |
| runs | Backend, repeat_index, warmup, pair_id, sequence, статус и result JSONB |
| jobs | Payload, тип, связи с experiment/version/run, owner/token/lease |
| attempts | Техническая попытка, token, даты, статус, error_code/result |
| benchmark_slots | Единственный слот: available, busy или quarantined |

Уникальные ограничения: attempt(job_id,token), case(experiment_id,case_index), run(case_id,backend,repeat_index,warmup), job.run_id. Метрики, окружение и ссылки на артефакты хранятся внутри JSONB результатов; отдельных таблиц measurement/artifact/recommendation/event пока нет.

Миграции: 0001 — управление и очередь; 0002 — датасеты, cases/runs и payload заданий; 0003 — nullable experiments.analysis. `alembic upgrade head` выполняет Compose-сервис migrate до API и worker. Старые записи без analysis остаются доступны, но не получают рекомендации задним числом.

## Bench PostgreSQL и файлы

Исходные таблицы находятся в разрешённых схемах. Snapshots: `snapshots.v_<attempt>`. Prepared-таблицы: `prep_<attempt>.c_<case>`. Модели MADlib, views и предсказания: `attempt_<attempt>`. UUID в имени изолирует попытки; опубликованные объекты сохраняются.

Успешный run записывает `<ML_ARTIFACT_ROOT>/<attempt hex>/result.json`. Сначала пишется result.tmp, выполняется flush/fsync файла, затем replace. Manifest содержит относительный key, размер и SHA-256. Supervisor публикует manifest в metadata только при действующем lease/token. При сбое между bench commit, записью файла и metadata-публикацией могут остаться сиротские объекты; автоматического сборщика пока нет.

Worker монтирует artifacts volume для записи, API — read-only. Endpoint artifact выдаёт только файл успешной опубликованной попытки, проверяет существование и принадлежность пути корню; SHA-256 хранится в manifest, но не пересчитывается на каждом скачивании. Итоговый experiment report формируется из metadata JSON и не требует отдельного файла в volume.

Для восстановления нужны все три volumes: metadata, bench и artifacts. Согласованную резервную копию следует снимать при остановленных записях API/worker; копия одной metadata не восстановит обучающие таблицы. `docker compose down -v` удаляет данные и не является штатным способом перезапуска. Retention, удаление эксперимента и автоматическая уборка не реализованы.
