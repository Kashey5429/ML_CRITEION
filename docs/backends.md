# Адаптеры и оценка качества

Реализация: `backends/base.py`, `madlib.py`, `sklearn.py`; оркестрация — `worker/benchmark.py`. Поддержана линейная регрессия без регуляризации на плотных конечных float64.

## Общий контракт

`RunContext` содержит psycopg connection, уникальную schema попытки, spec с prepared manifest и memory_mb. Protocol: validate(context), prepare(context), train(context), predict(context), persist_results(context), collect_diagnostics(context), cleanup(). Первые пять операций не возвращают ModelRef: состояние хранится внутри экземпляра адаптера, итог собирается диагностикой и исполнителем.

Для каждой попытки создаётся `attempt_<UUID>` с views train/test над общей prepared-таблицей. Последовательность: validate → начало sampler → создание views и prepare → train → predict → persist_results → завершение sampler → evaluate → collect_diagnostics → JSON. Фазы измеряются perf_counter_ns; model_wall включает создание views, подготовку адаптера и обмен данными. validate, общая подготовка, оценка качества и экспорт не входят в model_wall.

## MADlib

Validate проверяет MADlib 2.1.0. Для intercept=true вектор признаков — `ARRAY[1.0] || x`, иначе x. Train вызывает `madlib.linregr_train`, модель хранится в таблице model схемы попытки. Predict вызывает `madlib.linregr_predict` и создаёт predictions(row_id,y_pred). Persist добавляет PRIMARY KEY(row_id). Эти стадии выполняют commit.

Diagnostics содержит версию, коэффициенты, fit_intercept, число обучающих строк и SQL-ссылку на модель. При intercept=true первый коэффициент — свободный член. Cleanup не удаляет опубликованные модели и предсказания. Особенности сборки и исправление closest_columns — в [validation.md](validation.md).

## scikit-learn

Validate оценивает память как `rows * (features * 64 + 512)` байт и сравнивает с ML_SKLEARN_MEMORY_MB. Это предварительная оценка; реальная память измеряется отдельно и ограничивается контейнером.

Prepare получает train/test через fetchall в порядке row_id COLLATE C и создаёт NumPy float64-массивы. Train использует `LinearRegression(fit_intercept=..., n_jobs=1)`; BLAS ограничен общим threadpool_limits. Predict работает в Python. Persist записывает результаты через PostgreSQL COPY в predictions с PRIMARY KEY(row_id).

Diagnostics сохраняет коэффициенты, отдельный intercept, rank, версию и число обучающих строк. Модель экспортируется как коэффициенты в JSON, pickle/joblib-файл не создаётся. Cleanup освобождает состояние экземпляра; долговременные SQL-объекты сохраняются.

## Оценка качества

`worker/benchmark.py:evaluate` выполняет FULL JOIN test и predictions по row_id, проверяет число строк, пропущенные и лишние предсказания, NULL/NaN/Infinity. Затем рассчитывает RMSE и MAE в PostgreSQL; метрики должны быть конечными. Проверяется также rows_processed=train_count. Нарушения дают `invalid_predictions` или `training_row_count_mismatch`, а не успешную рекомендацию.

Оба подхода оцениваются одной функцией на одной test-таблице. Сравнение численных результатов и параметров модели проверено [реальной серией](benchmark-series-2026-10-21.md). Новый алгоритм потребует расширения spec/capabilities, обоих адаптеров, метрик и тестов эквивалентности; одной замены estimator недостаточно.
