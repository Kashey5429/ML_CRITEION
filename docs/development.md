# Запуск Python-бэкенда и экспериментального стенда

Команды выполняются из корня ML_CRITEION. Требуется Docker с Linux-контейнерами. MADlib 2.1.0 собирается из исходников для PostgreSQL 15; приложение использует Python 3.12 и зависимости из uv.lock. PL/Python MADlib использует отдельный Python 3.11.

## Запуск и обновление

При необходимости скопируйте .env.example в .env. Пароли по умолчанию предназначены для локального стенда; порты доступны только на loopback. Изменение .env не меняет пароль уже созданной БД.

```powershell
docker compose --profile bench up -d --build bench-db
docker compose up -d --build api worker
docker compose ps -a
```

При обновлении существующего приложения сначала остановите API и worker (`docker compose stop api worker`), затем выполните команды выше. Сервис migrate применяет Alembic до запуска приложения. Миграция 0002 добавляет datasets, dataset_versions, comparison_cases и runs; сохраняет прежние диагностические задания. Downgrade с реальными benchmark-заданиями намеренно запрещён.

Swagger: http://localhost:8000/docs. `/health/live` проверяет процесс, `/health/ready` — управляющую БД. `/api/v1/capabilities` сообщает поддерживаемые алгоритмы. История доступна и при недоступной bench DB.

## Проверка MADlib

```powershell
docker compose exec -T bench-db psql -v ON_ERROR_STOP=1 -U bench -d bench -f /opt/checks/closest_columns.sql
docker compose --profile bench run --build --rm preflight
docker compose exec -T bench-db bash -c 'export PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD" PGDATABASE="$POSTGRES_DB" PGHOST=localhost; /usr/local/madlib/bin/madpack -s madlib -p postgres install-check'
```

Init-скрипт устанавливает MADlib только при создании пустого volume. Исправление C++ находится в библиотеке образа; пересоздание контейнера с обновлённым образом заменяет библиотеку без удаления данных. Проверки выполняйте без параллельной экспериментальной нагрузки. Описание совместимости и результатов — в [отчёте](validation.md).

## Датасет и версия

Первый сценарий работает с существующей таблицей bench DB. Источник должен содержать уникальный непустой ID, числовые признаки и числовую целевую переменную. Поддерживаются плотные конечные float64 без NULL, NaN и Infinity. Строковые категории, импутация и масштабирование пока не реализованы. По умолчанию разрешены таблицы схемы public, до 1 млн строк и 100 признаков.

Создать демонстрационный источник (команда не перезаписывает существующие данные):

```powershell
Get-Content deploy/bench/demo.sql -Raw | docker compose exec -T bench-db psql -v ON_ERROR_STOP=1 -U bench -d bench
```

Зарегистрировать источник и заказать snapshot:

```powershell
$base = 'http://localhost:8000/api/v1'
$body = @{name='demo'; source_table='criterion_demo'; id_column='id'; features=@('x1','x2'); target='y'} | ConvertTo-Json
$dataset = Invoke-RestMethod -Method Post -Uri "$base/datasets" -ContentType application/json -Body $body
$version = Invoke-RestMethod -Method Post -Uri "$base/datasets/$($dataset.id)/versions"
Invoke-RestMethod "$base/dataset-versions/$($version.id)"
```

Дождитесь `status=ready`; при `failed` смотрите error_code. Worker копирует данные в отдельную таблицу `snapshots.v_<attempt>` в согласованной транзакции и сохраняет SHA-256, количество строк, порядок признаков и источник. Изменение исходной таблицы не меняет готовую версию. Новая версия создаётся новым POST. Неизменяемость обеспечена приложением; администратор bench DB технически может изменить таблицы.

## Матрица запусков

После готовности версии:

```powershell
$spec = @{
  kind='benchmark'; dataset_version_id=$version.id
  algorithm='linear_regression'; backends=@('madlib','sklearn')
  sample_sizes=@(50,100); fit_intercepts=@($true)
  test_fraction=0.2; seed=42; repeats=2; warmups=1
  threads=1; timeout_seconds=300
} | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/experiments/validate" -ContentType application/json -Body $spec
$experiment = Invoke-RestMethod -Method Post -Uri "$base/experiments" -ContentType application/json -Body $spec
$id = $experiment.id
Invoke-RestMethod -Method Post -Uri "$base/experiments/$id/start"
Invoke-RestMethod "$base/experiments/$id"
Invoke-RestMethod "$base/experiments/$id/runs?limit=200"
Invoke-RestMethod "$base/experiments/$id/results"
```

Пример создаёт 2 comparison cases и 12 runs: 2 размера × (1 прогрев + 2 измеряемых повтора) × 2 адаптера. `sample_sizes=[null]` означает всю версию. `fit_intercepts=[true,false]` добавляет вторую ось матрицы. Лимит — 200 runs с учётом прогревов.

Подготовка сохраняет строковый состав и train/test-флаг один раз для каждого case. Отбор использует seed и стабильную сортировку ID. Оба адаптера читают одну подготовленную таблицу. Повторы имеют pair_id; порядок адаптеров чередуется. Прогревы сохраняются, но исключаются из сводки. Параллельное обучение отключено одним benchmark slot.

MADlib вызывает linregr_train/linregr_predict. sklearn загружает NumPy float64, обучает LinearRegression и возвращает предсказания через COPY в ту же bench DB. У sklearn есть предварительная оценка памяти (512 MiB по умолчанию); это оценка, а не точная граница RSS. threadpoolctl ограничивает Python BLAS; число потоков PostgreSQL/MADlib этим параметром не задаётся. Compose отдельно ограничивает CPU и RAM контейнеров.

Времена: backend_prepare, train, predict, persist_results, model_wall и evaluate в наносекундах. model_wall включает создание представлений, получение данных и возврат предсказаний в БД; snapshot, общее разбиение, запуск процесса и экспорт JSON в него не входят. Границы predict/persist у адаптеров различаются из-за материализации SQL, поэтому сравнение отдельных фаз требует учёта этих различий. Sampler CPU/RAM и парные рекомендации реализованы; определения и ограничения описаны в [отдельной инструкции](measurement-and-recommendations.md).

Evaluator проверяет точное соответствие ID тестовой выборке, полноту и конечность предсказаний, рассчитывает RMSE и MAE. `/results` возвращает описательные медианы успешных измеряемых повторов; поле analysis содержит парную статистику и рекомендации отдельно по каждому case.

## Артефакты, очередь и отмена

`GET /api/v1/experiments/{id}/attempts` показывает ошибки и результаты попыток. `GET /api/v1/attempts/{attempt_id}/artifact` скачивает JSON с конфигурацией, коэффициентами модели, метриками и окружением. Файлы записываются атомарно в постоянный volume; metadata хранит размер и SHA-256. MADlib дополнительно сохраняет таблицу модели; sklearn сохраняет коэффициенты и intercept, без pickle.

Создание эксперимента поддерживает Idempotency-Key. Повторный start для queued/preparing/running/succeeded не создаёт новые задания. Для новой серии создавайте новый эксперимент. Отмена: `POST /api/v1/experiments/{id}/cancel`. Supervisor останавливает дочерний процесс, затем SQL-сессии с уникальным application_name попытки; публикация дополнительно проверяет lease/token и запрос отмены.

Истёкшая аренда переводит слот в quarantined и эксперимент в interrupted. Автоматический retry пока отсутствует. После подтверждения остановки старого worker и его SQL-сессий оператор может освободить слот:

```powershell
docker compose stop worker
docker compose run --rm worker ml-criterion release-quarantine --confirmed-stopped
docker compose up -d worker
```

Сначала установите, что прежнее выполнение действительно остановлено: флаг не выполняет эту проверку. Для повторного запуска создайте новый эксперимент. Таблицы и файлы незавершённых попыток могут оставаться; автоматическая уборка и retention пока не реализованы. Удалять volume с нужными данными не требуется.

## Проверки и текущие границы

```powershell
docker compose --profile bench --profile bench-test build benchmark-tests
docker compose --profile bench --profile bench-test run --rm benchmark-tests
```

Интеграционные тесты создают отдельные metadata-схемы и уникальные bench-объекты; удаляют только свои объекты. Проверяются миграции, гонки очереди, fencing, cancellation, timeout, реальный subprocess, версии данных и оба адаптера. Тесты только управляющей БД: `docker compose --profile test run --build --rm tests`.

Локальная разработка: `uv sync --frozen --python 3.12`, `uv run ruff check src tests migrations`, `uv run pytest`. Без TEST_METADATA_URL и TEST_BENCH_DSN интеграционные проверки пропускаются. Для запуска вне Docker задайте ML_METADATA_URL, ML_BENCH_DSN и доступный ML_ARTIFACT_ROOT. API и worker должны видеть одинаковые настройки источников и путь артефактов.

Следующие этапы: контрольные серии для оценки влияния мониторинга, расширенные манифесты окружения, очистка/retention, автоматическое восстановление, новые алгоритмы и preprocessing. Авторизация, роли БД и внешний многопользовательский доступ пока не реализованы; текущая конфигурация предназначена для локального исследовательского стенда.

Для существующего bench volume установите функцию мониторинга по [инструкции](measurement-and-recommendations.md). Миграция 0003 сохраняет итоговый анализ; прежние результаты не удаляются.
