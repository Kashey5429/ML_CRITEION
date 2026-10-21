from psycopg import sql


class MadlibAdapter:
    def validate(self, context):
        version = context.connection.execute("SELECT madlib.version()").fetchone()[0]
        if "2.1.0" not in version:
            raise ValueError("unsupported_madlib_version")
        self.version = version

    def prepare(self, context):
        self.expression = "ARRAY[1.0] || x" if context.spec["fit_intercept"] else "x"

    def train(self, context):
        context.connection.execute(
            "SELECT madlib.linregr_train(%s,%s,%s,%s)",
            (context.schema + ".train", context.schema + ".model", "y", self.expression),
        )
        context.connection.commit()

    def predict(self, context):
        context.connection.execute(
            sql.SQL("""
            CREATE TABLE {}.predictions AS SELECT row_id,
                madlib.linregr_predict(m.coef, {}) AS y_pred
            FROM {}.test CROSS JOIN {}.model m
        """).format(
                sql.Identifier(context.schema),
                sql.SQL(self.expression),
                sql.Identifier(context.schema),
                sql.Identifier(context.schema),
            )
        )
        context.connection.commit()

    def persist_results(self, context):
        context.connection.execute(
            sql.SQL("ALTER TABLE {}.predictions ADD PRIMARY KEY(row_id)").format(
                sql.Identifier(context.schema)
            )
        )
        context.connection.commit()

    def collect_diagnostics(self, context):
        coef, rows = context.connection.execute(
            sql.SQL("SELECT coef,num_rows_processed FROM {}.model").format(
                sql.Identifier(context.schema)
            )
        ).fetchone()
        return {
            "backend": "madlib",
            "version": self.version,
            "coefficients": coef,
            "fit_intercept": context.spec["fit_intercept"],
            "rows_processed": rows,
            "model": {"type": "postgres", "schema": context.schema, "table": "model"},
        }

    def cleanup(self):
        pass  # Published model and predictions are durable, not temporary objects.
