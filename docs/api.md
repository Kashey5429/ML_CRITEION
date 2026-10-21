# HTTP API

Реализация: `src/ml_criterion/api/app.py`. Фабрика `create_app(settings=None, sessions=None)` позволяет подменять настройки и metadata session factory в интеграционных тестах. API работает с метаданными; обучение и копирование датасетов выполняет worker.

Прямой адрес: `http://localhost:8000`; через frontend Nginx: `http://localhost:8080`. Интерактивная схема — [Swagger](http://localhost:8000/docs), машинная — `/openapi.json`. Примеры PowerShell приведены в [development.md](development.md).

## Маршруты

Все следующие пути, кроме health, имеют префикс `/api/v1`.

| Метод и путь | Результат |
| --- | --- |
| GET `/health/live` | Процесс API отвечает; БД не проверяется |
| GET `/health/ready` | Metadata доступна и существует слот стенда; не проверяет bench DB и worker |
| GET `/capabilities` | Алгоритмы, адаптеры, области измерений и версия политики |
| GET / POST `/datasets` | Список / регистрация источника (201), без копирования данных |
| GET / POST `/datasets/{id}/versions` | Список / постановка snapshot в очередь (202) |
| GET `/dataset-versions/{id}` | Статус, manifest и error_code версии |
| POST `/experiments/validate` | Проверка готовой версии и матрицы, количества cases/runs/measured_runs; ничего не сохраняет |
| GET / POST `/experiments` | История / создание draft (201) |
| GET `/experiments/{id}` | Spec, hash, статус и даты |
| POST `/experiments/{id}/start` | Постановка в очередь (202) |
| POST `/experiments/{id}/cancel` | Запрос отмены (202); остановка выполняется worker асинхронно |
| GET `/experiments/{id}/runs` | Логические запуски, конфигурация case, pair_id и результат |
| GET `/experiments/{id}/attempts` | Технические попытки, token, даты, error_code и результат |
| GET `/experiments/{id}/results` | Счётчики, медианы успешных измеряемых запусков и сохранённый analysis |
| GET `/experiments/{id}/recommendation` | Сохранённый анализ либо `unavailable/analysis_not_published` |
| GET `/experiments/{id}/report` | JSON spec + config_hash + analysis как attachment; 409 до публикации анализа |
| GET `/attempts/{id}/artifact` | JSON-файл опубликованной успешной попытки |

Списки возвращают массивы, `offset` по умолчанию 0. `limit`: experiments — 30 по умолчанию, максимум 100; datasets/versions — 100; runs/attempts — 50, максимум 200. Для полной истории нужно читать страницы до неполной страницы. `completed_runs` в results считает успешные runs, включая прогрев; summary исключает прогревы. До завершения summary может быть частичным — окончательный вывод берётся из analysis.

## Валидация и ошибки

Спецификации Pydantic запрещают неизвестные поля, содержат `schema_version=1` и сохраняются с раскрытыми значениями по умолчанию. POST создания эксперимента проверяет форму spec; наличие готовой версии и допустимость размера проверяются validate/start. Изменения существующего spec через API нет.

`Idempotency-Key` поддержан только при POST `/experiments` (1–128 символов): тот же ключ и hash возвращают прежний эксперимент, другой hash даёт 409 `idempotency_key_conflict`. Регистрация источника и создание версии при повторном POST создают новые сущности.

Прикладная ошибка: `{"error":{"code":"experiment_not_found"}}`. Основные статусы: 404 — сущность/артефакт отсутствует; 409 — недопустимый переход или конфликт; 422 — неправильный spec, неготовая версия либо запрещённая схема; 503 `metadata_unavailable` — SQLAlchemy-ошибка. Структурные ошибки Pydantic используют стандартный FastAPI `detail`, а не `error.code`.

Авторизации нет: текущий Compose публикует сервисы только на localhost. Произвольный SQL не принимается. Путь файла артефакта проверяется относительно настроенного корня. Тесты: `tests/test_specs.py`, `tests/integration/test_control_plane.py`.
