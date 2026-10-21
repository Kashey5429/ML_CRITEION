"""Real training smoke test. All database objects are rolled back on exit."""

import platform
from pathlib import Path
from uuid import uuid4

import numpy as np
import psycopg
import sklearn
from psycopg import sql
from sklearn.linear_model import LinearRegression
from threadpoolctl import threadpool_limits


def check_stand(dsn: str) -> dict:
    schema = "smoke_" + uuid4().hex
    with psycopg.connect(dsn, connect_timeout=5) as connection:
        try:
            connection.execute("SET LOCAL statement_timeout = '60s'")
            pg_version = connection.execute("SHOW server_version_num").fetchone()[0]
            madlib_version = connection.execute("SELECT madlib.version()").fetchone()[0]
            if int(pg_version) // 10000 != 15 or "2.1.0" not in madlib_version:
                raise RuntimeError("Expected PostgreSQL 15 and MADlib 2.1.0")
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
            connection.execute(
                sql.SQL("""
                CREATE TABLE {}.data AS
                SELECT i AS row_id, i::float8 AS x1, (i % 7)::float8 AS x2,
                       (3 + 2*i - 4*(i % 7))::float8 AS y
                FROM generate_series(1, 100) AS i
            """).format(sql.Identifier(schema))
            )
            connection.execute(
                sql.SQL("CREATE VIEW {}.train AS SELECT * FROM {}.data WHERE row_id <= 80").format(
                    sql.Identifier(schema), sql.Identifier(schema)
                )
            )
            connection.execute(
                "SELECT madlib.linregr_train(%s, %s, %s, %s)",
                (schema + ".train", schema + ".model", "y", "ARRAY[1.0,x1,x2]"),
            )
            train = np.array(
                connection.execute(
                    sql.SQL("SELECT x1,x2,y FROM {}.train ORDER BY row_id").format(
                        sql.Identifier(schema)
                    )
                ).fetchall(),
                dtype=np.float64,
            )
            test = np.array(
                connection.execute(
                    sql.SQL("""
                SELECT d.row_id, d.x1, d.x2, d.y,
                       madlib.linregr_predict(m.coef, ARRAY[1.0,d.x1,d.x2])
                FROM {}.data d CROSS JOIN {}.model m
                WHERE d.row_id > 80 ORDER BY d.row_id
            """).format(sql.Identifier(schema), sql.Identifier(schema))
                ).fetchall(),
                dtype=np.float64,
            )
            if train.shape != (80, 3) or test.shape != (20, 5):
                raise RuntimeError("Unexpected prediction count")
            with threadpool_limits(limits=1):
                model = LinearRegression().fit(train[:, :2], train[:, 2])
                predictions = model.predict(test[:, 1:3])
            if not np.isfinite(test).all() or not np.isfinite(predictions).all():
                raise RuntimeError("Non-finite predictions")
            np.testing.assert_allclose(test[:, 4], test[:, 3], atol=1e-7, rtol=0)
            np.testing.assert_allclose(predictions, test[:, 4], atol=1e-7, rtol=0)
            return {
                "status": "passed",
                "postgres_version_num": pg_version,
                "madlib": madlib_version,
                "python": platform.python_version(),
                "sklearn": sklearn.__version__,
                "numpy": np.__version__,
                "algorithm": "linear_regression",
                "train_rows": 80,
                "test_rows": 20,
                "madlib_rmse": float(np.sqrt(np.mean((test[:, 4] - test[:, 3]) ** 2))),
                "sklearn_rmse": float(np.sqrt(np.mean((predictions - test[:, 3]) ** 2))),
                "executor_cgroup_v2": Path("/sys/fs/cgroup/cpu.stat").is_file(),
                "scope": "synthetic smoke test; not a performance benchmark",
            }
        finally:
            connection.rollback()
