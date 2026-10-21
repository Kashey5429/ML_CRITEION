"""Create deterministic numeric sources; never replace an existing table.

Run with the worker's Python/environment before starting measured experiments.
The only stdout is a JSON manifest that the UI driver can consume.
"""

import argparse
import json
import re

import numpy as np
import psycopg
from psycopg import sql

from ml_criterion.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--series", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_]{1,24}", args.series):
        parser.error("series must contain 1–24 lowercase letters, digits or underscores")
    seed = 20261021
    manifest = {
        "series": args.series,
        "seed": seed,
        "noise_std": 0.1,
        "generator": "numpy-PCG64-standard-normal-v1",
        "numpy": np.__version__,
        "datasets": [],
    }
    with psycopg.connect(Settings().bench_dsn, connect_timeout=5) as connection:
        for features in (5, 20):
            x = np.random.default_rng(seed + features).standard_normal((100000, features))
            coefficients = np.array([(-1) ** j * (j + 1) / features for j in range(features)])
            y = 3 + x @ coefficients + np.random.default_rng(seed).normal(0, 0.1, len(x))
            columns = [f"x{i + 1}" for i in range(features)]
            for size in (1000, 10000, 100000):
                name = f"bench_{args.series}_n{size}_p{features}"
                connection.execute(
                    sql.SQL(
                        "CREATE TABLE public.{} (id bigint PRIMARY KEY, {}, y float8 NOT NULL)"
                    ).format(
                        sql.Identifier(name),
                        sql.SQL(", ").join(
                            sql.SQL("{} float8 NOT NULL").format(sql.Identifier(c)) for c in columns
                        ),
                    )
                )
                with connection.cursor() as cursor:
                    with cursor.copy(
                        sql.SQL("COPY public.{} FROM STDIN").format(sql.Identifier(name))
                    ) as copy:
                        for i in range(size):
                            copy.write_row((i + 1, *x[i].tolist(), float(y[i])))
                connection.execute(sql.SQL("ANALYZE public.{}").format(sql.Identifier(name)))
                count = connection.execute(
                    sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(name))
                ).fetchone()[0]
                assert count == size
                manifest["datasets"].append(
                    {
                        "name": f"Линейная · {size:,} строк · {features} признаков".replace(
                            ",", " "
                        ),
                        "table": name,
                        "rows": size,
                        "features": columns,
                        "coefficients": coefficients.tolist(),
                        "intercept": 3,
                    }
                )
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
