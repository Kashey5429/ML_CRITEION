\set ON_ERROR_STOP on
BEGIN;
SET LOCAL statement_timeout = '60s';
CREATE SCHEMA madlib_smoke;
CREATE TABLE madlib_smoke.train AS
SELECT i AS row_id, i::double precision AS x,
       (3 + 2*i)::double precision AS y FROM generate_series(1, 30) AS i;
SELECT madlib.linregr_train('madlib_smoke.train', 'madlib_smoke.model',
                           'y', 'ARRAY[1.0, x]');
DO $$
DECLARE error double precision;
BEGIN
    IF current_setting('server_version_num')::integer / 10000 <> 15 THEN
        RAISE EXCEPTION 'Expected PostgreSQL 15';
    END IF;
    IF madlib.version() NOT LIKE '%2.1.0%' THEN
        RAISE EXCEPTION 'Expected MADlib 2.1.0';
    END IF;
    SELECT max(abs(madlib.linregr_predict(m.coef, ARRAY[1.0, i::double precision])
                   - (3+2*i))) INTO error
    FROM madlib_smoke.model AS m CROSS JOIN generate_series(31, 40) AS i;
    IF error IS NULL OR NOT (error < 1e-8) THEN
        RAISE EXCEPTION 'MADlib regression smoke failed: %', error;
    END IF;
END $$;
SELECT version(), madlib.version();
-- No smoke objects survive, so the check is safely repeatable.
ROLLBACK;
