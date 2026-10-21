# Датасеты, версии и подготовка

Реализация: `domain/specs.py:DatasetSpec`, `datasets/execution.py`; постановка snapshot — `api/app.py`, публикация — `application/benchmarks.py:complete_job`.

## Источник и snapshot

Источник — существующая обычная или partitioned-таблица bench PostgreSQL. Spec содержит `name`, `source_schema`, `source_table`, `id_column`, упорядоченный список `features` и `target`. По умолчанию разрешена схема public. CSV-upload и произвольные SELECT не поддерживаются.

Признаки и target: int2/int4/int8/float4/float8/numeric, при копировании преобразуются в float64. ID: целые, text/varchar/uuid; в snapshot приводится к text. Все имена столбцов должны различаться. Разрешено 1–100 признаков; размер версии — от 4 до `ML_MAX_DATASET_ROWS` (по умолчанию 1 000 000). NULL, NaN, Infinity и неуникальный/пустой SQL NULL ID отклоняются. Идентификаторы SQL экранируются через psycopg.sql.Identifier.

POST версии создаёт metadata-запись `queued` и job `snapshot` с тайм-аутом 300 с. Статусы: queued → running → ready либо failed/cancelled/interrupted. Исполнитель копирует таблицу в `snapshots.v_<attempt UUID без дефисов>` в транзакции REPEATABLE READ. `LIMIT max_rows+1` позволяет обнаружить превышение, а не публикует усечённую версию. PRIMARY KEY защищает row_id.

Manifest готовой версии содержит schema/table, row_count, SHA-256 checksum, features, target, dtype и version_id. Checksum вычисляется по JSON-строкам `[row_id,x,y]`, упорядоченным `row_id COLLATE "C"`. Это fingerprint данных после преобразования, не исходного SQL-текста.

Изменение источника не меняет snapshot. Неизменяемость обеспечена приложением, а не запретом SQL для администратора. Для новых данных создаётся новая версия. Ошибки `source_must_be_a_table`, `features_and_target_must_be_numeric`, `unsupported_row_id_type`, `null_or_nonfinite_data`, `dataset_row_limit` доступны через error_code; ошибки PostgreSQL представлены как `bench_sql_<SQLSTATE>`, прочие неизвестные ошибки — `executor_failed`.

## Общая подготовка

Prepare создаёт схему `prep_<attempt>` и таблицу `c_<case UUID>` для каждого case. Строки упорядочиваются по `md5(row_id || ':' || seed)`, затем по row_id с COLLATE C. Берутся первые sample_size строк; первые `int(sample_size*(1-test_fraction))` помечаются `is_train=true`, остальные — test. Train содержит минимум две строки, test — минимум одну.

Оба адаптера и все повторы case используют одну таблицу. Manifest фиксирует число строк, признаки, исходный checksum, seed и рецепт `md5-rowid-seed-v1`. Повторы не создают новые разбиения. Один seed даёт детерминированные подвыборки; при разных размерах граница train/test меняется.

Импутации, стандартизации, категориального кодирования и отдельного пакета preprocessing пока нет. Для добавления преобразований потребуется версионированный рецепт с обучением параметров только на train и общей выдачей обоим адаптерам.

Проверки: интеграционный тест меняет источник после snapshot и запускает модели на старой версии; проверяются checksum, split и парность. [Генератор шести наборов и результаты](benchmark-series-2026-10-21.md).
