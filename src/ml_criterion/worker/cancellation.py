import time

import psycopg


def stop_bench_sessions(dsn, attempt_id):
    """Call after child exit, so it cannot open another connection."""
    name = "mlc:" + attempt_id.hex
    with psycopg.connect(
        dsn, connect_timeout=3, autocommit=True, options="-cstatement_timeout=2000"
    ) as connection:
        deadline = time.monotonic() + 5
        while True:
            sessions = connection.execute(
                """
                SELECT pid,backend_start FROM pg_stat_activity WHERE application_name=%s
            """,
                (name,),
            ).fetchall()
            if not sessions:
                return
            for pid, started in sessions:
                connection.execute(
                    """
                    SELECT pg_terminate_backend(pid) FROM pg_stat_activity
                    WHERE pid=%s AND backend_start=%s AND application_name=%s
                """,
                    (pid, started, name),
                )
            if time.monotonic() >= deadline:
                raise RuntimeError("bench_stop_unconfirmed")
            time.sleep(0.1)
