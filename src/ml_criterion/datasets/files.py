"""Bounded, streaming CSV ingestion. Display headers never become SQL identifiers."""

import csv
import math
from pathlib import Path

from psycopg import sql


def numeric_value(value):
    """CSV cells may use a decimal point or comma; grouping separators are unsupported."""
    number = float(value.replace(",", "."))
    if not math.isfinite(number):
        raise ValueError("nonfinite number")
    return number


def csv_options(path, encoding="auto", delimiter="auto"):
    if encoding == "auto":
        encoding = "utf-8-sig"
        try:
            with path.open(encoding=encoding) as source:
                while source.read(65536):
                    pass
        except UnicodeDecodeError:
            encoding = "cp1251"
    with path.open(encoding=encoding, newline="") as source:
        sample = source.read(65536)
    if not sample.strip():
        raise ValueError("Файл пуст. Выберите CSV с заголовками и данными.")
    if delimiter == "auto":
        try:
            delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
        except csv.Error:
            delimiter = ","
    return encoding, delimiter


def inspect_csv(path, max_rows, encoding="auto", delimiter="auto", consume=None):
    encoding, delimiter = csv_options(path, encoding, delimiter)
    columns, preview, count = [], [], 0
    try:
        with path.open(encoding=encoding, newline="") as source:
            reader = csv.reader(source, delimiter=delimiter, strict=True)
            headers = next(reader)
            if not 2 <= len(headers) <= 101:
                raise ValueError("Нужно от 2 до 101 столбца. Проверьте разделитель CSV.")
            headers = [h.strip() for h in headers]
            if any(not h or len(h) > 255 for h in headers) or len(set(headers)) != len(headers):
                raise ValueError("Заголовки должны быть непустыми и уникальными (до 255 символов).")
            columns = [
                dict(key=f"c{i}", name=h, missing=0, invalid=0, examples=[])
                for i, h in enumerate(headers)
            ]
            for row in reader:
                count += 1
                if max_rows and count > max_rows:
                    raise ValueError(f"Превышен лимит: {max_rows} строк.")
                if len(row) != len(headers):
                    raise ValueError(
                        f"Строка {reader.line_num}: число ячеек отличается от заголовка."
                    )
                if any(len(v) > 4096 or "\x00" in v for v in row):
                    raise ValueError(
                        f"Строка {reader.line_num}: недопустимая или слишком длинная ячейка."
                    )
                cleaned = [v.strip() for v in row]
                for column, value in zip(columns, cleaned, strict=True):
                    problem = None
                    if not value:
                        column["missing"] += 1
                        problem = "пустое значение"
                    else:
                        try:
                            numeric_value(value)
                        except ValueError:
                            column["invalid"] += 1
                            problem = "не является конечным числом"
                    if problem and len(column["examples"]) < 3:
                        column["examples"].append(f"Строка {reader.line_num}: {problem}")
                if len(preview) < 10:
                    preview.append([v[:160] for v in cleaned])
                if consume:
                    consume(count, cleaned)
    except (UnicodeError, csv.Error) as exc:
        raise ValueError("Не удалось прочитать CSV. Проверьте кодировку и разделитель.") from exc
    if count < 4:
        raise ValueError("Для сравнения нужно не менее 4 строк данных.")
    for column in columns:
        column["usable"] = column["missing"] == 0 and column["invalid"] == 0
    return dict(
        columns=columns, preview=preview, row_count=count, encoding=encoding, delimiter=delimiter
    )


def import_csv(connection, payload, attempt_id, settings):
    path = Path(settings.upload_root) / (payload["file_id"] + ".csv")
    table = "f_" + attempt_id.hex
    connection.execute("CREATE SCHEMA IF NOT EXISTS uploads")
    # The first bounded inspection supplies the schema; a second streaming pass copies rows.
    profile = inspect_csv(
        path, settings.max_dataset_rows, payload["encoding"], payload["delimiter"]
    )
    connection.execute(
        sql.SQL("CREATE TABLE uploads.{} (row_id bigint PRIMARY KEY, {})").format(
            sql.Identifier(table),
            sql.SQL(",").join(
                sql.SQL("{} text").format(sql.Identifier(c["key"])) for c in profile["columns"]
            ),
        )
    )
    with connection.cursor() as cursor:
        with cursor.copy(
            sql.SQL("COPY uploads.{} FROM STDIN").format(sql.Identifier(table))
        ) as copy:
            inspect_csv(
                path,
                settings.max_dataset_rows,
                profile["encoding"],
                profile["delimiter"],
                lambda i, row: copy.write_row(
                    [
                        i,
                        *[
                            repr(numeric_value(v)) if c["usable"] else v
                            for c, v in zip(profile["columns"], row, strict=True)
                        ],
                    ]
                ),
            )
    return {**profile, "schema": "uploads", "table": table}
