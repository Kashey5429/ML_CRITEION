"""Independent audit of completed real runs and the published paired recommendation."""

import argparse
import json
from collections import defaultdict
from pathlib import Path
from statistics import median
from urllib.request import urlopen

import numpy as np


def get(base, path):
    with urlopen(base + "/api/v1" + path, timeout=15) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("state")
    parser.add_argument("--base", default="http://frontend")
    args = parser.parse_args()
    state = json.loads(Path(args.state).read_text(encoding="utf-8-sig"))
    checks, summary = [], []
    for dataset in state["datasets"]:
        identifier = dataset["experiment_id"]
        base = f"/experiments/{identifier}"
        version = get(args.base, f"/dataset-versions/{dataset['version_id']}")
        assert version["status"] == "ready"
        assert version["manifest"]["row_count"] == dataset["rows"]
        assert version["manifest"]["features"] == dataset["features"]
        experiment, results = get(args.base, base), get(args.base, base + "/results")
        runs = get(args.base, base + "/runs?limit=200")
        attempts = get(args.base, base + "/attempts?limit=200")
        report = get(args.base, base + "/report")
        assert experiment["status"] == results["status"] == "succeeded"
        assert len(runs) == results["total_runs"] == results["completed_runs"] == 22
        assert sum(r["warmup"] for r in runs) == 2
        assert len(attempts) == 23 and all(a["status"] == "succeeded" for a in attempts)
        assert report["analysis"] == results["analysis"]
        pairs = defaultdict(dict)
        max_gap, scopes_available, coefficient_delta = 0, 0, 0
        for run in runs:
            result = run["result"]
            assert run["status"] == "succeeded"
            assert result["diagnostics"]["rows_processed"] == dataset["rows"] * 0.8
            assert result["quality"]["test_rows"] == dataset["rows"] * 0.2
            assert 0.07 < result["quality"]["rmse"] < 0.13
            resources = result["resources"]
            assert resources["window_seconds"] >= result["timings"]["model_wall_ns"] / 1e9
            max_gap = max(max_gap, resources["max_sample_gap_seconds"])
            for scope in resources["scopes"].values():
                assert scope["status"] == "available" and scope["missed_samples"] == 0
                assert scope["cpu_seconds"] >= 0 and scope["peak_memory_bytes"] > 0
                scopes_available += 1
            if not run["warmup"]:
                pairs[run["pair_id"]][run["backend"]] = run
        assert len(pairs) == 10 and all(
            set(pair) == {"madlib", "sklearn"} for pair in pairs.values()
        )
        madlib_times, sklearn_times = [], []
        for _, pair in sorted(pairs.items()):
            madlib, sklearn = pair["madlib"]["result"], pair["sklearn"]["result"]
            assert madlib["prepared"] == sklearn["prepared"]
            assert madlib["prepared"]["source_checksum"] == version["manifest"]["checksum"]
            assert abs(madlib["quality"]["rmse"] - sklearn["quality"]["rmse"]) < 1e-8
            madlib_coef = np.asarray(madlib["diagnostics"]["coefficients"])
            sklearn_coef = np.asarray(
                [sklearn["diagnostics"]["intercept"], *sklearn["diagnostics"]["coefficients"]]
            )
            delta = float(np.max(np.abs(madlib_coef - sklearn_coef)))
            assert delta < 1e-7
            coefficient_delta = max(coefficient_delta, delta)
            madlib_times.append(madlib["timings"]["model_wall_ns"])
            sklearn_times.append(sklearn["timings"]["model_wall_ns"])
        case = report["analysis"]["cases"][0]
        assert not case["excluded_pairs"] and case["statistics"]["pairs"] == 10
        assert all(v["status"] == "feasible" for v in case["constraints"].values())
        ratios = np.asarray(madlib_times) / np.asarray(sklearn_times)
        rng = np.random.default_rng(case["statistics"]["seed"])
        bootstrap = np.median(ratios[rng.integers(0, 10, size=(4000, 10))], axis=1)
        low, high = np.quantile(bootstrap, [0.025, 0.975])
        np.testing.assert_allclose(case["statistics"]["ci95"], [low, high], rtol=1e-12)
        assert abs(case["statistics"]["median_ratio"] - np.median(ratios)) < 1e-12
        threshold = 1 + experiment["spec"]["recommendation"]["practical_speedup"]
        expected = (
            "sklearn"
            if low > threshold
            else "madlib"
            if high < 1 / threshold
            else "comparable"
            if low >= 1 / threshold and high <= threshold
            else "inconclusive"
        )
        assert case["verdict"] == expected
        row = {
            "experiment_id": identifier,
            "dataset_id": dataset["dataset_id"],
            "version_id": dataset["version_id"],
            "rows": dataset["rows"],
            "features": len(dataset["features"]),
            "verdict": expected,
            "ratio": float(np.median(ratios)),
            "ci95": [float(low), float(high)],
            "max_coefficient_difference": coefficient_delta,
            "max_sample_gap_seconds": max_gap,
            "available_resource_scopes": scopes_available,
            "backends": {},
        }
        for backend, times in [("madlib", madlib_times), ("sklearn", sklearn_times)]:
            data = [r["result"] for r in runs if not r["warmup"] and r["backend"] == backend]
            row["backends"][backend] = {
                "model_seconds": median(times) / 1e9,
                "train_seconds": median(r["timings"]["train_ns"] for r in data) / 1e9,
                "prepare_seconds": median(r["timings"]["backend_prepare_ns"] for r in data) / 1e9,
                "persist_seconds": median(r["timings"]["persist_results_ns"] for r in data) / 1e9,
                "rmse": median(r["quality"]["rmse"] for r in data),
                "cpu_python": median(
                    r["resources"]["scopes"]["python_process"]["cpu_seconds"] for r in data
                ),
                "cpu_db": median(
                    r["resources"]["scopes"]["bench_container"]["cpu_seconds"] for r in data
                ),
                "ram_python_mib": median(
                    r["resources"]["scopes"]["python_process"]["peak_memory_bytes"] for r in data
                )
                / 1024**2,
                "ram_db_mib": median(
                    r["resources"]["scopes"]["bench_container"]["peak_memory_bytes"] for r in data
                )
                / 1024**2,
            }
        summary.append(row)
        checks.append({"id": identifier, "passed": True})
    print(
        json.dumps(
            {"series": state["series"], "checks": checks, "summary": summary},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
