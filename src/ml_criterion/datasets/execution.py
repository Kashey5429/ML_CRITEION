import hashlib
import json
import math

from psycopg import sql

from ml_criterion.domain.specs import DatasetSpec


def snapshot(connection, payload, attempt_id, settings):
    spec = DatasetSpec.model_validate(payload["source"])
    if spec.source_schema not in settings.source_schemas:
        raise ValueError("source_schema_not_allowed")
    relation = connection.execute(
        """
        SELECT c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname=%s AND c.relname=%s
    """,
        (spec.source_schema, spec.source_table),
    ).fetchone()
    if not relation or relation[0] not in ("r", "p"):
        raise ValueError("source_must_be_a_table")
    columns = dict(
        connection.execute(
            """
        SELECT a.attname, t.typname FROM pg_attribute a
        JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_type t ON t.oid=a.atttypid
        WHERE n.nspname=%s AND c.relname=%s AND a.attnum>0 AND NOT a.attisdropped
    """,
            (spec.source_schema, spec.source_table),
        ).fetchall()
    )
    numeric = {"int2", "int4", "int8", "float4", "float8", "numeric"}
    if any(columns.get(c) not in numeric for c in (*spec.features, spec.target)):
        raise ValueError("features_and_target_must_be_numeric")
    if columns.get(spec.id_column) not in {"int2", "int4", "int8", "text", "varchar", "uuid"}:
        raise ValueError("unsupported_row_id_type")
    name = "v_" + attempt_id.hex
    connection.execute("CREATE SCHEMA IF NOT EXISTS snapshots")
    connection.execute(
        sql.SQL("""
        CREATE TABLE snapshots.{} AS SELECT {}::text AS row_id,
            ARRAY[{}]::float8[] AS x, {}::float8 AS y FROM {}.{} LIMIT %s
    """).format(
            sql.Identifier(name),
            sql.Identifier(spec.id_column),
            sql.SQL(",").join(sql.Identifier(c) for c in spec.features),
            sql.Identifier(spec.target),
            sql.Identifier(spec.source_schema),
            sql.Identifier(spec.source_table),
        ),
        (settings.max_dataset_rows + 1,),
    )
    connection.execute(
        sql.SQL("ALTER TABLE snapshots.{} ADD PRIMARY KEY (row_id)").format(sql.Identifier(name))
    )
    digest, count = hashlib.sha256(), 0
    with connection.cursor(name="snapshot_fingerprint") as cursor:
        cursor.execute(
            sql.SQL('SELECT row_id,x,y FROM snapshots.{} ORDER BY row_id COLLATE "C"').format(
                sql.Identifier(name)
            )
        )
        for row_id, x, y in cursor:
            if y is None or any(v is None or not math.isfinite(v) for v in [*x, y]):
                raise ValueError("null_or_nonfinite_data")
            digest.update(
                json.dumps(
                    [row_id, x, y], separators=(",", ":"), ensure_ascii=True, allow_nan=False
                ).encode()
                + b"\n"
            )
            count += 1
    if not 4 <= count <= settings.max_dataset_rows:
        raise ValueError("dataset_row_limit")
    return {
        "schema": "snapshots",
        "table": name,
        "row_count": count,
        "checksum": digest.hexdigest(),
        "features": list(spec.features),
        "target": spec.target,
        "dtype": "float64",
        "version_id": payload["version_id"],
    }


def prepare(connection, payload, attempt_id):
    source = payload["snapshot"]
    namespace = "prep_" + attempt_id.hex
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(namespace)))
    prepared = {}
    for case in payload["cases"]:
        config = case["config"]
        table = "c_" + case["id"].replace("-", "")
        connection.execute(
            sql.SQL("""
            CREATE TABLE {}.{} AS
            SELECT row_id,x,y, position <= %s AS is_train FROM (
                SELECT row_id,x,y, row_number() OVER (
                    ORDER BY md5(row_id || ':' || %s), row_id COLLATE "C") AS position
                FROM {}.{}
            ) ranked WHERE position <= %s
        """).format(
                sql.Identifier(namespace),
                sql.Identifier(table),
                sql.Identifier(source["schema"]),
                sql.Identifier(source["table"]),
            ),
            (config["train_count"], str(config["seed"]), config["sample_size"]),
        )
        connection.execute(
            sql.SQL("ALTER TABLE {}.{} ADD PRIMARY KEY(row_id)").format(
                sql.Identifier(namespace), sql.Identifier(table)
            )
        )
        prepared[case["id"]] = {
            "schema": namespace,
            "table": table,
            "row_count": config["sample_size"],
            "train_count": config["train_count"],
            "test_count": config["sample_size"] - config["train_count"],
            "features": source["features"],
            "source_checksum": source["checksum"],
            "split_recipe": "md5-rowid-seed-v1",
            "seed": config["seed"],
        }
    return {"prepared": prepared}
