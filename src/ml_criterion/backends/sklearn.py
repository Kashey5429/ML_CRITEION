import numpy as np
import sklearn
from psycopg import sql
from sklearn.linear_model import LinearRegression


class SklearnAdapter:
    def validate(self, context):
        data = context.spec["prepared"]
        # Include Python row objects, arrays and fitting copies. This is a preflight estimate.
        estimate = data["row_count"] * (len(data["features"]) * 64 + 512)
        if estimate > context.memory_mb * 1024**2:
            raise ValueError("sklearn_memory_budget_exceeded")

    def prepare(self, context):
        conn, namespace = context.connection, sql.Identifier(context.schema)
        train = conn.execute(
            sql.SQL('SELECT x,y FROM {}.train ORDER BY row_id COLLATE "C"').format(namespace)
        ).fetchall()
        test = conn.execute(
            sql.SQL('SELECT row_id,x FROM {}.test ORDER BY row_id COLLATE "C"').format(namespace)
        ).fetchall()
        self.x_train = np.asarray([r[0] for r in train], dtype=np.float64)
        self.y_train = np.asarray([r[1] for r in train], dtype=np.float64)
        self.row_ids = [r[0] for r in test]
        self.x_test = np.asarray([r[1] for r in test], dtype=np.float64)
        conn.commit()

    def train(self, context):
        self.model = LinearRegression(fit_intercept=context.spec["fit_intercept"], n_jobs=1)
        self.model.fit(self.x_train, self.y_train)

    def predict(self, context):
        self.predictions = self.model.predict(self.x_test)

    def persist_results(self, context):
        connection = context.connection
        namespace = sql.Identifier(context.schema)
        connection.execute(
            sql.SQL("CREATE TABLE {}.predictions (row_id text PRIMARY KEY, y_pred float8)").format(
                namespace
            )
        )
        with connection.cursor() as cursor:
            with cursor.copy(
                sql.SQL("COPY {}.predictions (row_id,y_pred) FROM STDIN").format(namespace)
            ) as copy:
                for row_id, value in zip(self.row_ids, self.predictions, strict=True):
                    copy.write_row((row_id, float(value)))
        connection.commit()

    def collect_diagnostics(self, context):
        return {
            "backend": "sklearn",
            "version": sklearn.__version__,
            "coefficients": self.model.coef_.tolist(),
            "intercept": float(self.model.intercept_),
            "rank": int(self.model.rank_),
            "rows_processed": len(self.y_train),
            "model": {"type": "linear_coefficients", "format_version": 1},
        }

    def cleanup(self):
        self.__dict__.clear()
