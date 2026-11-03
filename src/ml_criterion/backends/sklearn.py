"""Bounded-memory ordinary least squares: centered streaming QR + sklearn solve."""

import csv
import tempfile

import numpy as np
import sklearn
from psycopg import sql
from sklearn.linear_model import LinearRegression


class StreamingOLS:
    """Reduce [X,y] orthogonally; never form X.T @ X or retain the whole dataset."""

    def __init__(self, features, fit_intercept):
        self.features = features
        self.fit_intercept = fit_intercept
        self.count = 0
        self.mean = np.zeros(features + 1)
        self.r = np.empty((0, features + 1))

    def update(self, xy):
        xy = np.asarray(xy, dtype=np.float64)
        if xy.ndim != 2 or xy.shape[1] != self.features + 1 or not np.isfinite(xy).all():
            raise ValueError("null_or_nonfinite_data")
        size = len(xy)
        if not size:
            return
        pieces = [self.r]
        if self.fit_intercept:
            mean = xy.mean(axis=0)
            pieces.append(xy - mean)
            if self.count:
                # Between-block correction preserves the global centered least-squares problem.
                weight = np.sqrt(self.count * (size / (self.count + size)))
                pieces.append(((self.mean - mean) * weight)[None, :])
            self.mean += (mean - self.mean) * (size / (self.count + size))
        else:
            pieces.append(xy)
        self.r = np.linalg.qr(np.vstack(pieces), mode="r")
        self.count += size

    def finish(self):
        if self.count < 2:
            raise ValueError("training_row_count_mismatch")
        x, y = self.r[:, : self.features], self.r[:, self.features]
        u, singular, vt = np.linalg.svd(x, full_matrices=False)
        # Match the dense OLS cutoff to the ORIGINAL sample count, not the compressed shape.
        version = tuple(int(part) for part in sklearn.__version__.split(".")[:2])
        relative_cutoff = (
            LinearRegression().tol
            if version >= (1, 9)
            else max(self.count, self.features) * np.finfo(np.float64).eps
        )
        cutoff = relative_cutoff * singular[0]
        keep = singular > cutoff
        reduced_x = singular[keep, None] * vt[keep]
        reduced_y = (u.T @ y)[keep]
        if not keep.any():
            reduced_x, reduced_y = np.zeros((1, self.features)), np.zeros(1)
        model = LinearRegression(fit_intercept=False, n_jobs=1).fit(reduced_x, reduced_y)
        model.intercept_ = (
            float(self.mean[-1] - self.mean[:-1] @ model.coef_) if self.fit_intercept else 0.0
        )
        model.rank_ = int(keep.sum())
        model.singular_ = singular
        return model


class SklearnAdapter:
    def validate(self, context):
        features = len(context.spec["prepared"]["features"])
        # Budget now controls a batch, not the number of rows in the source.
        fixed = 16 * (features + 1) ** 2 * 8
        available = context.memory_mb * 1024**2 // 4 - fixed
        per_row = (features + 1) * 128 + 1024
        if available < per_row:
            raise ValueError("sklearn_memory_budget_exceeded")
        self.batch_rows = min(4096, available // per_row)
        self.features = features
        self.spool = None

    def prepare(self, context):
        self.reducer = StreamingOLS(self.features, context.spec["fit_intercept"])

    def train(self, context):
        with context.connection.cursor(name="stream_training") as cursor:
            cursor.execute(
                sql.SQL('SELECT x,y FROM {}.train ORDER BY row_id COLLATE "C"').format(
                    sql.Identifier(context.schema)
                )
            )
            while rows := cursor.fetchmany(self.batch_rows):
                self.reducer.update(np.asarray([[*x, y] for x, y in rows], dtype=np.float64))
        if self.reducer.count != context.spec["prepared"]["train_count"]:
            raise ValueError("training_row_count_mismatch")
        self.model = self.reducer.finish()
        context.connection.commit()

    def predict(self, context):
        # Disk spool keeps predict/persist timings separate and bounds RAM for test rows too.
        self.spool = tempfile.TemporaryFile(mode="w+", encoding="utf-8", newline="")
        writer = csv.writer(self.spool)
        self.test_count = 0
        with context.connection.cursor(name="stream_testing") as cursor:
            cursor.execute(
                sql.SQL('SELECT row_id,x FROM {}.test ORDER BY row_id COLLATE "C"').format(
                    sql.Identifier(context.schema)
                )
            )
            while rows := cursor.fetchmany(self.batch_rows):
                values = self.model.predict(np.asarray([r[1] for r in rows], dtype=np.float64))
                if not np.isfinite(values).all():
                    raise ValueError("invalid_predictions")
                writer.writerows((r[0], float(v)) for r, v in zip(rows, values, strict=True))
                self.test_count += len(rows)
        if self.test_count != context.spec["prepared"]["test_count"]:
            raise ValueError("invalid_predictions")
        self.spool.seek(0)
        context.connection.commit()

    def persist_results(self, context):
        namespace = sql.Identifier(context.schema)
        context.connection.execute(
            sql.SQL("CREATE TABLE {}.predictions (row_id text PRIMARY KEY, y_pred float8)").format(
                namespace
            )
        )
        with context.connection.cursor() as cursor:
            with cursor.copy(
                sql.SQL("COPY {}.predictions FROM STDIN WITH (FORMAT CSV)").format(namespace)
            ) as copy:
                while block := self.spool.read(1024**2):
                    copy.write(block)
        context.connection.commit()

    def collect_diagnostics(self, context):
        return {
            "backend": "sklearn",
            "version": sklearn.__version__,
            "solver": "streaming-centered-qr-sklearn-ols-v1",
            "execution_mode": "streaming",
            "batch_rows": self.batch_rows,
            "coefficients": self.model.coef_.tolist(),
            "intercept": float(self.model.intercept_),
            "rank": int(self.model.rank_),
            "rows_processed": self.reducer.count,
            "test_rows_processed": self.test_count,
            "model": {"type": "linear_coefficients", "format_version": 1},
        }

    def cleanup(self):
        if getattr(self, "spool", None) is not None:
            self.spool.close()
        self.__dict__.clear()
