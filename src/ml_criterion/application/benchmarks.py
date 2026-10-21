from uuid import uuid4, uuid5

from sqlalchemy import select

from ml_criterion.domain.specs import BenchmarkSpec
from ml_criterion.persistence.models import ComparisonCase, DatasetVersion, Job, Run


def plan_matrix(experiment_id, spec, manifest):
    """Deterministic order and pair identities; fresh cases belong to this experiment."""
    spec = BenchmarkSpec.model_validate(spec)
    cases, runs = [], []
    sequence = 0
    for size in spec.sample_sizes:
        count = size or manifest["row_count"]
        train_count = int(count * (1 - spec.test_fraction))
        if count > manifest["row_count"] or train_count < 2 or count - train_count < 1:
            raise ValueError("Invalid sample size or split")
        for intercept in spec.fit_intercepts:
            index = len(cases)
            case_id = uuid5(experiment_id, f"case:{index}")
            config = {
                "sample_size": count,
                "fit_intercept": intercept,
                "train_count": train_count,
                "seed": spec.seed,
                "threads": spec.threads,
                "timeout_seconds": spec.timeout_seconds,
            }
            cases.append({"id": case_id, "case_index": index, "config": config})
            for warmup, repetitions in ((True, spec.warmups), (False, spec.repeats)):
                for repeat in range(repetitions):
                    backends = spec.backends if repeat % 2 == 0 else spec.backends[::-1]
                    pair = uuid5(case_id, f"{warmup}:{repeat}")
                    for backend in backends:
                        runs.append(
                            {
                                "id": uuid4(),
                                "case_id": case_id,
                                "backend": backend,
                                "repeat_index": repeat,
                                "warmup": warmup,
                                "pair_id": pair,
                                "sequence": sequence,
                            }
                        )
                        sequence += 1
    return cases, runs


def enqueue_benchmark(session, experiment):
    spec = BenchmarkSpec.model_validate(experiment.spec)
    version = session.get(DatasetVersion, spec.dataset_version_id)
    if not version or version.status != "ready":
        raise ValueError("dataset_version_not_ready")
    cases, runs = plan_matrix(experiment.id, experiment.spec, version.manifest)
    session.add_all(ComparisonCase(experiment_id=experiment.id, **case) for case in cases)
    session.flush()
    session.add_all(Run(**run) for run in runs)
    session.add(
        Job(
            experiment_id=experiment.id,
            kind="prepare",
            payload={
                "kind": "prepare",
                "snapshot": version.manifest,
                "cases": [{**case, "id": str(case["id"])} for case in cases],
                "timeout_seconds": spec.timeout_seconds,
            },
        )
    )


def complete_job(session, job, experiment, status, result, error_code):
    """Called only inside the queue's ownership-checked publication transaction."""
    if job.kind == "snapshot":
        version = session.get(DatasetVersion, job.version_id, with_for_update=True)
        version.status = "ready" if status == "succeeded" else status
        version.manifest = result if status == "succeeded" else None
        version.error_code = error_code
        return
    if job.kind == "diagnostic":
        experiment.status = status
        return
    cases = session.scalars(
        select(ComparisonCase).where(ComparisonCase.experiment_id == experiment.id)
    ).all()
    runs = session.scalars(select(Run).where(Run.case_id.in_([c.id for c in cases]))).all()
    if job.kind == "prepare":
        if status == "succeeded":
            manifests = result["prepared"]
            for case in cases:
                case.prepared = manifests[str(case.id)]
            for run in runs:
                case = next(c for c in cases if c.id == run.case_id)
                run.status = "queued"
                session.add(
                    Job(
                        experiment_id=experiment.id,
                        run_id=run.id,
                        kind="run",
                        sequence=run.sequence,
                        payload={
                            "kind": "run",
                            "backend": run.backend,
                            "prepared": case.prepared,
                            **case.config,
                        },
                    )
                )
            experiment.status = "running"
        else:
            for run in runs:
                run.status = "cancelled" if status == "cancelled" else "failed"
            experiment.status = status
            finalize_analysis(experiment, cases, runs)
        return
    run = session.get(Run, job.run_id)
    run.status, run.result = status, result if status == "succeeded" else None
    if experiment.status == "interrupted":
        return
    if any(r.status in {"pending", "queued", "running"} for r in runs):
        return
    if experiment.cancel_requested_at:
        experiment.status = "cancelled"
    elif all(r.status == "succeeded" for r in runs):
        experiment.status = "succeeded"
    elif any(r.status == "succeeded" for r in runs):
        experiment.status = "partial"
    else:
        experiment.status = "failed"
    finalize_analysis(experiment, cases, runs)


def finalize_analysis(experiment, cases, runs):
    from ml_criterion.recommendation.analysis import analyze_experiment

    records = [
        {
            "id": str(r.id),
            "case_id": str(r.case_id),
            "pair_id": str(r.pair_id),
            "backend": r.backend,
            "warmup": r.warmup,
            "status": r.status,
            "result": r.result,
        }
        for r in sorted(runs, key=lambda r: r.sequence)
    ]
    report = analyze_experiment(experiment.spec, records)
    configs = {str(case.id): case.config for case in cases}
    for item in report["cases"]:
        item["config"] = configs[item["case_id"]]
        if experiment.status in {"cancelled", "interrupted"}:
            item["verdict"] = "inconclusive"
            item["reasons"] = ["experiment_" + experiment.status]
    report["experiment_status"] = experiment.status
    experiment.analysis = report
