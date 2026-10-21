# Worker, очередь и восстановление

Реализация: `worker/queue.py`, `supervisor.py`, `executor.py`, `cancellation.py`, `benchmark.py`. Запуск: `ml-criterion worker`; `--once` выполняет одну итерацию, а не всю очередь. В Docker worker запускается отдельным сервисом. FastAPI BackgroundTasks не используется.

## Очередь

Типы job: snapshot, prepare, run, diagnostic. Общий слот `benchmark_slots.id=1` сериализует все задания, включая копирование данных. Несколько supervisor не увеличивают параллелизм измерений. Порядок блокировок: slot → job → experiment; захват использует FOR UPDATE SKIP LOCKED. Выбор queued-job упорядочен по created_at, sequence, id.

Claim в короткой metadata-транзакции переводит job в leased, назначает owner UUID, увеличивает token, создаёт attempt и занимает слот. Длительная работа начинается после commit. Heartbeat и finish проверяют owner, token, lease_until и связь со слотом; время аренды берётся из clock_timestamp() metadata PostgreSQL. Устаревший исполнитель не может опубликовать результат.

Настройки по умолчанию: poll 1 с, heartbeat 5 с, lease 30 с. Lease должен быть не короче трёх heartbeat-интервалов. Параметры и эксплуатационные команды — в [operations.md](operations.md).

## Дочерний процесс

Supervisor запускает `python -m ml_criterion.worker.executor` на каждую попытку. JSON payload/attempt_id передаются через stdin, итоговый JSON — через временный файл stdout, чтобы большой manifest не заблокировал pipe. Соединения создаются дочерним процессом. Постоянного IPC-потока фаз пока нет; stderr исполнителя не публикуется, диагностика идёт через error_code.

Для bench-сессии задаются application_name=`mlc:<attempt hex>`, connect_timeout 5 с, lock_timeout 5 с и statement_timeout из задания. Sampler использует отдельное соединение. Supervisor следит за общим тайм-аутом попытки, отменой и завершением процесса. `threadpool_limits` ограничивает потоки библиотек внутри model run; это отличается от квоты CPU контейнера.

## Отмена и аварии

После запроса cancel supervisor останавливает дерево процессов и собственные bench-сессии попытки. На Linux используются отдельная process group, SIGTERM и затем SIGKILL при необходимости; Windows-ветка использует psutil. Соседние SQL-сессии не должны завершаться. Терминальная публикация освобождает слот только после подтверждения остановки.

При истёкшем lease `recover_expired` помечает attempt/job interrupted, эксперимент — interrupted, слот — quarantined. Автоматического повторного захвата нет: старый процесс или SQL ещё могут работать. Если остановку SQL подтвердить не удалось, lease также остаётся для последующего карантина.

Оператор сначала проверяет и останавливает прежний executor/контейнер и его SQL-сессии, затем запускает `ml-criterion release-quarantine --confirmed-stopped`. Команда лишь освобождает слот; не возобновляет прерванный эксперимент. Для повторения создаётся новый experiment с прежним spec.

Проверки на настоящем PostgreSQL: конкурирующий захват, stale token, истёкший lease, карантин, отмена, тайм-аут и адресная остановка SQL — `tests/integration/test_control_plane.py`. Долговременный журнал фаз, automatic retry и cleanup-job пока не реализованы.
