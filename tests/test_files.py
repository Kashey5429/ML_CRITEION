import pytest

from ml_criterion.datasets.files import inspect_csv, numeric_value


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0,3047171", 0.3047171),
        ("-1,0399841", -1.0399841),
        ("1,25e-3", 0.00125),
        ("0.3047171", 0.3047171),
        ("42", 42),
    ],
)
def test_decimal_comma_and_point(value, expected):
    assert numeric_value(value) == expected


@pytest.mark.parametrize("value", ["1,234.56", "1.234,56", "1,2,3", "NaN", "inf", "text"])
def test_ambiguous_or_nonfinite_numbers_rejected(value):
    with pytest.raises(ValueError):
        numeric_value(value)


@pytest.mark.parametrize("delimiter", [";", ","])
def test_decimal_comma_csv(tmp_path, delimiter):
    import csv

    path = tmp_path / "decimal.csv"
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, delimiter=delimiter)
        writer.writerow(["id", "f0", "f1"])
        for i in range(4):
            writer.writerow([i, "0,3047171", "-1,0399841"])
    result = inspect_csv(path, 0)
    assert result["delimiter"] == delimiter
    assert all(c["usable"] for c in result["columns"])


def test_zero_row_cap_means_unlimited(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("x,y\n" + "1,2\n" * 20, encoding="utf-8")
    assert inspect_csv(path, 0)["row_count"] == 20
    with pytest.raises(ValueError, match="лимит"):
        inspect_csv(path, 10)


@pytest.mark.parametrize(
    "encoding,delimiter", [("utf-8-sig", ","), ("cp1251", ";"), ("utf-8", "\t")]
)
def test_russian_headers_and_full_file_validation(tmp_path, encoding, delimiter):
    path = tmp_path / "source.csv"
    lines = [delimiter.join(["Площадь", "Цена", "Описание"])]
    lines += [delimiter.join([str(i), str(i * 2), "дом"]) for i in range(15)]
    lines.append(delimiter.join(["", "NaN", "квартира"]))
    path.write_bytes("\n".join(lines).encode(encoding))
    result = inspect_csv(path, 100)
    assert result["row_count"] == 16
    assert len(result["preview"]) == 10
    assert result["columns"][0]["missing"] == 1
    assert result["columns"][1]["invalid"] == 1
    assert result["columns"][2]["invalid"] == 16
    assert not any(c["usable"] for c in result["columns"])
    assert "17" in result["columns"][0]["examples"][0]


@pytest.mark.parametrize(
    "body,limit",
    [
        ("", 100),
        ("x,x\n1,2\n2,3\n3,4\n4,5", 100),
        ("x,y\n1,2,3", 100),
        ("x,y\n1,2", 100),
        ("x,y\n1,2\n2,3\n3,4\n4,5\n5,6", 4),
    ],
)
def test_reject_invalid_csv(tmp_path, body, limit):
    path = tmp_path / "source.csv"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_csv(path, limit)


def test_quoted_cells_manual_options_and_bounded_preview(tmp_path):
    path = tmp_path / "source.csv"
    path.write_text("x;y;note\n" + '1;2;"a;b"\n' * 4, encoding="utf-8")
    result = inspect_csv(path, 10, "utf-8-sig", ";")
    assert result["preview"][0] == ["1", "2", "a;b"]
    assert [c["usable"] for c in result["columns"]] == [True, True, False]
