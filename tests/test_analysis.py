from copy import deepcopy

import pytest

from ml_criterion.domain.specs import RecommendationPolicy
from ml_criterion.recommendation.analysis import analyze_case


def paired_runs(ratios=(2, 2, 2, 2, 2)):
    runs = []
    for i, ratio in enumerate(ratios):
        for backend, duration in [("madlib", ratio * 100), ("sklearn", 100)]:
            runs.append(
                {
                    "id": f"{i}-{backend}",
                    "pair_id": str(i),
                    "backend": backend,
                    "warmup": False,
                    "status": "succeeded",
                    "result": {
                        "attempt_id": f"attempt-{i}-{backend}",
                        "prepared": {"table": "same"},
                        "timings": {"model_wall_ns": duration},
                        "quality": {"rmse": 1.0},
                    },
                }
            )
    return runs


@pytest.mark.parametrize(("ratio", "verdict"), [(2, "sklearn"), (0.5, "madlib"), (1, "comparable")])
def test_paired_decision_and_reproducible_bootstrap(ratio, verdict):
    runs = paired_runs([ratio] * 5)
    report = analyze_case(runs, RecommendationPolicy(), 42)
    assert report["verdict"] == verdict
    assert report == analyze_case(runs[::-1], RecommendationPolicy(), 42)
    assert report["statistics"]["ci95"] == [ratio, ratio]
    assert len(report["input_attempts"]) == 10


def test_warmup_excluded_and_incomplete_pair_prevents_selection():
    runs = paired_runs()
    warmup = deepcopy(runs[0])
    warmup.update(warmup=True, pair_id="warmup")
    warmup["result"]["timings"]["model_wall_ns"] = 1e12
    runs.append(warmup)
    assert analyze_case(runs, RecommendationPolicy(), 1)["statistics"]["median_ratio"] == 2
    runs[0]["status"] = "failed"
    report = analyze_case(runs, RecommendationPolicy(), 1)
    assert report["verdict"] == "inconclusive"
    assert report["excluded_reasons"] == {"unsuccessful_run": 1}
    assert report["statistics"]["pairs"] == 4


def test_quality_guard_overrides_faster_backend():
    runs = paired_runs()
    for run in runs:
        if run["backend"] == "sklearn":
            run["result"]["quality"]["rmse"] = 10
    report = analyze_case(runs, RecommendationPolicy(), 1)
    assert report["verdict"] == "madlib"
    assert report["reasons"] == ["only_backend_meeting_constraints"]
    assert (
        analyze_case(runs, RecommendationPolicy(max_rmse=0.5), 1)["verdict"]
        == "no_feasible_backend"
    )


def test_missing_resources_are_not_zero_and_block_required_constraint():
    report = analyze_case(paired_runs(), RecommendationPolicy(max_cpu_seconds=1), 1)
    assert report["verdict"] == "inconclusive"
    metric = report["resources"]["madlib"]["bench_container"]["cpu_seconds"]
    assert metric == {"median": None, "available_pairs": 0, "unavailable_pairs": 5}
    assert report["reasons"] == ["required_resources_unavailable"]


def test_resource_constraint_uses_database_and_python_separately():
    runs = paired_runs()
    for run in runs:
        run["result"]["resources"] = {
            "scopes": {
                "python_process": {
                    "status": "available",
                    "cpu_seconds": 1,
                    "peak_memory_bytes": 10,
                },
                "bench_container": {
                    "status": "available",
                    "cpu_seconds": 2,
                    "peak_memory_bytes": 100 if run["backend"] == "madlib" else 20,
                },
            }
        }
    policy = RecommendationPolicy(max_bench_memory_bytes=50)
    assert analyze_case(runs, policy, 1)["verdict"] == "sklearn"
    assert (
        analyze_case(runs, RecommendationPolicy(max_cpu_seconds=2), 1)["verdict"]
        == "no_feasible_backend"
    )


def test_variable_pairs_and_mismatched_split_are_inconclusive():
    runs = paired_runs([0.1, 0.5, 1, 2, 10])
    assert analyze_case(runs, RecommendationPolicy(), 1)["verdict"] == "inconclusive"
    runs[0]["result"]["prepared"] = {"table": "different"}
    assert analyze_case(runs, RecommendationPolicy(), 1)["excluded_reasons"] == {
        "different_prepared_data": 1
    }


def test_bootstrap_preserves_pairs_instead_of_comparing_independent_medians():
    runs = paired_runs([2, 2, 2, 2, 2])
    for i, run in enumerate(runs):
        run["result"]["timings"]["model_wall_ns"] *= 10 ** (i // 2)
    report = analyze_case(runs, RecommendationPolicy(), 1)
    assert report["statistics"]["ratios_madlib_over_sklearn"] == [2] * 5
    assert report["statistics"]["ci95"] == [2, 2]
