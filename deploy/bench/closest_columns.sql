\set ON_ERROR_STOP on
BEGIN;
CREATE SCHEMA closest_regression;
CREATE FUNCTION closest_regression.metric(float8[], float8[]) RETURNS float8
LANGUAGE SQL IMMUTABLE STRICT AS 'SELECT madlib.squared_dist_norm2($1,$2)';
DO $$
DECLARE result madlib.closest_columns_result;
BEGIN
    -- Original crash, including deterministic tie order.
    FOR i IN 1..100 LOOP
        result := madlib.closest_columns(
            ARRAY[ARRAY[0,0],ARRAY[0,1],ARRAY[1,0],ARRAY[0,1]]::float8[][],
            ARRAY[0.5,0.5]::float8[],2);
        IF result.column_ids IS DISTINCT FROM ARRAY[0,1]
           OR result.distances IS DISTINCT FROM ARRAY[0.5,0.5]::float8[] THEN
            RAISE EXCEPTION 'Incorrect nearest columns: %', result;
        END IF;
    END LOOP;
    result := madlib.closest_columns(
        ARRAY[ARRAY[0,0],ARRAY[3,4]]::float8[][], ARRAY[0,0]::float8[],
        1, 'closest_regression.metric'::regproc);
    IF result.column_ids IS DISTINCT FROM ARRAY[0]
       OR result.distances IS DISTINCT FROM ARRAY[0]::float8[] THEN
        RAISE EXCEPTION 'Custom distance failed: %', result;
    END IF;
END $$;
ROLLBACK;
