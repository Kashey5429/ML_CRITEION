# Документация реализованных блоков

Состояние на 21 октября 2026. Это справочник текущей реализации; [целевая архитектура](backend-architecture.md) и [план](backend-implementation-plan.md) также содержат будущие возможности.

| Блок | Реализация | Документация |
| --- | --- | --- |
| API | `src/ml_criterion/api/app.py` | [HTTP-контракт](api.md) |
| Конфигурация и CLI | `config.py`, `cli.py` | [Эксплуатация](operations.md), [запуск и примеры](development.md) |
| Датасеты и preprocessing | `datasets/execution.py`, `domain/specs.py` | [Версии и подготовка](datasets.md) |
| Эксперименты и матрица | `application/experiments.py`, `application/benchmarks.py` | [Планирование и состояния](experiments.md) |
| Worker и очередь | `worker/queue.py`, `supervisor.py`, `executor.py`, `cancellation.py` | [Выполнение и восстановление](worker.md) |
| MADlib и scikit-learn | `backends/base.py`, `madlib.py`, `sklearn.py` | [Контракт адаптеров](backends.md) |
| Измерения | `measurement/resources.py`, `worker/benchmark.py` | [CPU, RAM и время](measurement-and-recommendations.md) |
| Оценка качества | `worker/benchmark.py:evaluate` | [Предсказания и качество](backends.md#оценка-качества) |
| Рекомендации | `recommendation/analysis.py` | [Статистика и политика выбора](measurement-and-recommendations.md) |
| Метаданные, модели и артефакты | `persistence/`, `migrations/`, `worker/benchmark.py` | [Хранение](storage.md) |
| Frontend | `frontend/src/`, Vue 3 + Yarn | [Интерфейс и разработка](frontend.md) |
| Стенд PostgreSQL/MADlib | `compose.yaml`, `deploy/`, `preflight.py` | [Эксплуатация](operations.md), [исправление MADlib и проверки](validation.md) |
| Проверочные серии | `deploy/bench/generate_series.py`, `verify_series.py`, `frontend/scripts/run-series.mjs` | [Результаты и повторение серии](benchmark-series-2026-10-21.md) |

## Поток одного эксперимента

1. API регистрирует существующую таблицу bench DB; worker создаёт snapshot версии.
2. API сохраняет неизменяемый spec. Команда start создаёт cases, runs и задание prepare одной metadata-транзакцией.
3. Worker резервирует единственный слот стенда и запускает отдельный процесс подготовки.
4. После подготовки очередь получает задания run. Каждый run выполняется отдельным процессом через один адаптер.
5. Исполнитель сохраняет предсказания, метрики, окружение и JSON. Supervisor публикует результат только при действующем lease/token.
6. Завершение серии формирует сохранённый парный анализ. Frontend получает результаты через polling и скачивает отчёты через API.

Отдельных пакетов `preprocessing`, `evaluation`, `artifacts` и таблиц для каждой метрики пока нет: соответствующая логика находится в перечисленных файлах. Поддержана только плотная числовая линейная регрессия. Авторизация, автоматический retry, удаление по сроку хранения и новые алгоритмы остаются за пределами текущей реализации.
