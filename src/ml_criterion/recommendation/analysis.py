import hashlib
import json
import math
from collections import Counter, defaultdict
from statistics import median

import numpy as np

from ml_criterion.domain.specs import RecommendationPolicy


def paired_statistics(madlib, sklearn, seed):
    """Resample whole pairs; report pointwise percentile CI of median time ratio."""
    ratios = np.asarray(madlib, dtype=float) / np.asarray(sklearn, dtype=float)
    rng = np.random.default_rng(seed)
    resampled = ratios[rng.integers(0, len(ratios), size=(4000, len(ratios)))]
    interval = np.quantile(np.median(resampled, axis=1), [0.025, 0.975])
    return {
        "pairs": len(ratios),
        "ratios_madlib_over_sklearn": ratios.tolist(),
        "median_ratio": float(np.median(ratios)),
        "ci95": interval.tolist(),
        "median_difference_ns": float(np.median(np.asarray(madlib) - np.asarray(sklearn))),
        "median_madlib_ns": median(madlib),
        "median_sklearn_ns": median(sklearn),
        "ratio_iqr": float(np.quantile(ratios, 0.75) - np.quantile(ratios, 0.25)),
        "method": "paired-percentile-bootstrap-median-ratio-v1",
        "resamples": 4000,
        "seed": seed,
    }


def resource_value(result, scope, metric):
    data = result.get("resources", {}).get("scopes", {}).get(scope, {})
    value = data.get(metric)
    if data.get("status") != "available" or value is None or not math.isfinite(value):
        return None
    return value


def feasibility(pairs, backend, policy):
    violations, unknown = set(), set()
    other = "sklearn" if backend == "madlib" else "madlib"
    for pair in pairs:
        result, peer = pair[backend]["result"], pair[other]["result"]
        rmse, reference = result["quality"]["rmse"], peer["quality"]["rmse"]
        if (
            rmse
            > reference + policy.quality_abs_tolerance + policy.quality_rel_tolerance * reference
        ):
            violations.add("quality_loss_exceeds_tolerance")
        if policy.max_rmse is not None and rmse > policy.max_rmse:
            violations.add("max_rmse_exceeded")
        if (
            policy.max_model_seconds is not None
            and result["timings"]["model_wall_ns"] / 1e9 > policy.max_model_seconds
        ):
            violations.add("max_model_seconds_exceeded")
        for scope, limit in (
            ("python_process", policy.max_python_rss_bytes),
            ("bench_container", policy.max_bench_memory_bytes),
        ):
            if limit is None:
                continue
            peak = resource_value(result, scope, "peak_memory_bytes")
            if peak is None:
                unknown.add(scope + "_memory_unavailable")
            elif peak > limit:
                violations.add(scope + "_observed_memory_limit_exceeded")
        if policy.max_cpu_seconds is not None:
            values = [
                resource_value(result, s, "cpu_seconds")
                for s in ("python_process", "bench_container")
            ]
            if any(v is None for v in values):
                unknown.add("cpu_unavailable")
            elif sum(values) > policy.max_cpu_seconds:
                violations.add("max_cpu_seconds_exceeded")
    return {
        "status": "infeasible" if violations else "unknown" if unknown else "feasible",
        "violations": sorted(violations),
        "unknown": sorted(unknown),
    }


def analyze_case(runs, policy, seed):
    grouped = defaultdict(list)
    for run in runs:
        if not run["warmup"]:
            grouped[run["pair_id"]].append(run)
    pairs, excluded = [], []
    for pair_id, entries in sorted(grouped.items()):
        by_backend = {r["backend"]: r for r in entries}
        reason = None
        if len(entries) != 2 or set(by_backend) != {"madlib", "sklearn"}:
            reason = "missing_or_duplicate_backend"
        elif any(r["status"] != "succeeded" or not r["result"] for r in entries):
            reason = "unsuccessful_run"
        else:
            results = [r["result"] for r in entries]
            if results[0].get("prepared") != results[1].get("prepared"):
                reason = "different_prepared_data"
            elif any(
                not math.isfinite(r["timings"]["model_wall_ns"])
                or r["timings"]["model_wall_ns"] <= 0
                or not math.isfinite(r["quality"]["rmse"])
                or r["quality"]["rmse"] < 0
                for r in results
            ):
                reason = "invalid_metric"
        if reason:
            excluded.append({"pair_id": pair_id, "reason": reason})
        else:
            pairs.append(by_backend)
    stats = None
    if pairs:
        stats = paired_statistics(
            [p["madlib"]["result"]["timings"]["model_wall_ns"] for p in pairs],
            [p["sklearn"]["result"]["timings"]["model_wall_ns"] for p in pairs],
            seed,
        )
    constraints = {b: feasibility(pairs, b, policy) for b in ("madlib", "sklearn")}
    verdict, reasons = "inconclusive", []
    if excluded:
        reasons.append("incomplete_pairs")
    if len(pairs) < policy.min_pairs:
        reasons.append("insufficient_pairs")
    if not reasons:
        feasible = [b for b, c in constraints.items() if c["status"] == "feasible"]
        if any(c["status"] == "unknown" for c in constraints.values()):
            reasons.append("required_resources_unavailable")
        elif not feasible:
            verdict, reasons = "no_feasible_backend", ["constraints_violated"]
        elif len(feasible) == 1:
            verdict, reasons = feasible[0], ["only_backend_meeting_constraints"]
        else:
            low, high = stats["ci95"]
            upper, lower = 1 + policy.practical_speedup, 1 / (1 + policy.practical_speedup)
            if low > upper:
                verdict, reasons = "sklearn", ["paired_speedup_above_threshold"]
            elif high < lower:
                verdict, reasons = "madlib", ["paired_speedup_above_threshold"]
            elif low >= lower and high <= upper:
                verdict, reasons = "comparable", ["interval_within_practical_equivalence_band"]
            else:
                reasons.append("uncertainty_overlaps_decision_threshold")
    resource_summary = {}
    for backend in ("madlib", "sklearn"):
        resource_summary[backend] = {}
        for scope in ("python_process", "bench_container"):
            metrics = {}
            for metric in ("cpu_seconds", "peak_memory_bytes"):
                values = [resource_value(p[backend]["result"], scope, metric) for p in pairs]
                available = [v for v in values if v is not None]
                metrics[metric] = {
                    "median": median(available) if available else None,
                    "available_pairs": len(available),
                    "unavailable_pairs": len(values) - len(available),
                }
            resource_summary[backend][scope] = metrics
    return {
        "verdict": verdict,
        "reasons": reasons,
        "expected_pairs": len(grouped),
        "excluded_pairs": excluded,
        "excluded_reasons": dict(Counter(e["reason"] for e in excluded)),
        "statistics": stats,
        "constraints": constraints,
        "resources": resource_summary,
        "input_runs": [p[b]["id"] for p in pairs for b in ("madlib", "sklearn")],
        "input_attempts": [
            p[b]["result"].get("attempt_id") for p in pairs for b in ("madlib", "sklearn")
        ],
        "warnings": [
            "Pointwise CI; no adjustment across cases. Sequential repeats may be correlated.",
            "Sampled memory limits concern observed peaks only, not guaranteed maxima.",
            "DB counters include background activity; memory scopes are not additive.",
        ],
    }


def analyze_experiment(spec, runs):
    policy = RecommendationPolicy.model_validate(spec.get("recommendation", {}))
    cases = defaultdict(list)
    for run in runs:
        cases[run["case_id"]].append(run)
    results = []
    for case_id, entries in sorted(cases.items()):
        seed = int(hashlib.sha256(f"{spec.get('seed', 42)}:{case_id}".encode()).hexdigest()[:8], 16)
        results.append({"case_id": case_id, **analyze_case(entries, policy, seed)})
    return {
        "analysis_version": 1,
        "policy": policy.model_dump(mode="json"),
        "cases": results,
        "scope": "Per comparison case; observed dataset, split, machine and cache policy only.",
        "input_sha256": hashlib.sha256(
            json.dumps(runs, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
    }
