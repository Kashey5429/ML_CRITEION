# Эксперименты и матрица запусков

Реализация: `domain/specs.py`, `application/experiments.py`, `application/benchmarks.py`. Сущности experiment, case, run и attempt имеют разные назначения: spec серии; вариант условий; логическое измерение; техническое выполнение задания соответственно.

## Спецификация

`BenchmarkSpec`: готовая dataset_version_id, algorithm=`linear_regression`, backends (`madlib`, `sklearn`), seed, repeats, warmups, sample_sizes, fit_intercepts, test_fraction, timeout_seconds, threads и recommendation. Значения по умолчанию: оба backend, seed 42, 5 повторов, 1 прогревочная пара, весь dataset, intercept=true, test_fraction=0,2, тайм-аут 300 с, 1 поток BLAS.

Ограничения: repeats 1–100, warmups 0–5, threads 1–16, timeout до 3600 с; размеры не меньше 4 и не больше версии. Пустые измерения матрицы и повторяющиеся значения запрещены. Общее число runs не более 200. Один backend допустим для выполнения, но парного сравнения двух подходов не даёт. Политика рекомендаций описана [отдельно](measurement-and-recommendations.md).

Spec нормализуется Pydantic и сохраняется вместе с SHA-256 канонического JSON. Изменять его после создания нельзя; новые условия требуют нового experiment. `DiagnosticSpec` используется для проверок success/fail/hang и запускается только при ML_ENABLE_DIAGNOSTIC_JOBS=true.

## Планирование

Cases — декартово произведение sample_sizes × fit_intercepts. `null` означает полный размер версии. Число runs = cases × backends × (repeats + warmups). Например, два размера, два intercept, два backend, 5 измерений и 1 прогрев дают 48 runs.

Case ID детерминирован через UUID5 от experiment ID и индекса; pair_id — от case ID, признака warmup и номера повтора. UUID run создаётся отдельно. Сначала идут прогревы, затем измерения; порядок backend чередуется на чётных/нечётных повторах. `sequence` фиксирует порядок. Prepare-job создаётся одновременно с cases/runs; run-jobs добавляются только после успешной подготовки.

## Состояния и публикация

Обычный путь: draft → queued → preparing → running → succeeded. Если часть runs завершилась ошибкой, возможен partial; если нет успешных — failed. Cancel переводит draft сразу в cancelled, активную серию — в cancelling, затем worker завершает отмену. Истечение lease даёт interrupted и карантин стенда.

Повторный start для queued/preparing/running/succeeded возвращает существующее состояние без повторного запуска. Для остальных недопустимых состояний — 409. Cancel терминального эксперимента возвращает его без изменений. Автоматического retry нет.

`complete_job` вызывается в транзакции публикации под проверкой владельца очереди. Он сохраняет manifest, результат run и итоговый статус. `finalize_analysis` собирает измеряемые пары и сохраняет `experiments.analysis`; отдельного finalize-job нет. Для отменённой/прерванной серии опубликованный вывод не должен выбирать победителя. После аварийного прерывания analysis может ещё отсутствовать; API явно сообщает это состояние.

Проверки: `tests/test_specs.py`, `tests/test_analysis.py`, `tests/integration/test_control_plane.py`; завершённая [серия из 132 запусков](benchmark-series-2026-10-21.md).
