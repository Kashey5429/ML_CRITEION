import numpy as np
import pytest
from sklearn.linear_model import LinearRegression

from ml_criterion.backends.base import RunContext
from ml_criterion.backends.sklearn import SklearnAdapter, StreamingOLS


@pytest.mark.parametrize("intercept", [False, True])
@pytest.mark.parametrize("kind", ["regular", "collinear", "offset", "constant", "wide"])
def test_streaming_matches_dense_ols(intercept, kind):
    rng = np.random.default_rng(42)
    x = rng.normal(size=(7 if kind == "wide" else 503, 12))
    if kind == "collinear":
        x[:, 4] = x[:, 0] * 2
    if kind == "offset":
        x += 1e7
    if kind == "constant":
        x[:] = 3
    y = x @ rng.normal(size=12) + 7 + rng.normal(size=len(x)) * 0.01
    expected = LinearRegression(fit_intercept=intercept).fit(x, y)
    reducer = StreamingOLS(x.shape[1], intercept)
    for start in range(0, len(x), 17):
        reducer.update(np.column_stack((x[start : start + 17], y[start : start + 17])))
        assert reducer.r.shape[0] <= x.shape[1] + 1
    actual = reducer.finish()
    np.testing.assert_allclose(actual.predict(x), expected.predict(x), rtol=1e-7, atol=1e-6)
    assert reducer.count == len(x)
    assert actual.rank_ == expected.rank_


def test_memory_batch_independent_of_source_size():
    sizes = []
    for rows in [100, 1000000, 1000000000]:
        adapter = SklearnAdapter()
        context = RunContext(
            None,
            "unused",
            {
                "prepared": {
                    "row_count": rows,
                    "features": list(range(50)),
                }
            },
            512,
        )
        adapter.validate(context)
        sizes.append(adapter.batch_rows)
    assert sizes == [4096] * 3


def test_invalid_values_and_empty_training_rejected():
    reducer = StreamingOLS(1, True)
    with pytest.raises(ValueError, match="nonfinite"):
        reducer.update([[np.inf, 1]])
    with pytest.raises(ValueError, match="row_count"):
        reducer.finish()
