from ml_criterion.measurement.resources import ResourceSampler


class Reader:
    def __init__(self, values):
        self.values = iter(values)

    def read(self):
        value = next(self.values)
        if isinstance(value, Exception):
            raise value
        return value


def sample(cpu, memory, identity="db"):
    return {"status": "available", "cpu_seconds": cpu, "memory_bytes": memory, "identity": identity}


def test_boundary_delta_and_sampled_peak():
    sampler = ResourceSampler(
        {"bench_container": Reader([sample(10, 100), sample(12, 500), sample(13, 200)])}, 10
    )
    sampler.start()
    sampler.sample()
    result = sampler.finish()
    scope = result["scopes"]["bench_container"]
    assert scope["cpu_seconds"] == 3
    assert scope["peak_memory_bytes"] == 500
    assert scope["baseline_memory_bytes"] == 100
    assert scope["samples"] == 3


def test_unavailable_and_reset_do_not_publish_false_zero():
    for values in (
        [sample(10, 100), OSError("unreadable")],
        [sample(10, 100), sample(1, 100)],
        [sample(10, 100), sample(11, 100, "restarted")],
    ):
        sampler = ResourceSampler({"bench_container": Reader(values)}, 10)
        sampler.start()
        scope = sampler.finish()["scopes"]["bench_container"]
        assert scope["status"] == "unavailable"
        assert scope["cpu_seconds"] is None
        assert scope["peak_memory_bytes"] is None
