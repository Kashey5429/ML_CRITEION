CREATE TABLE IF NOT EXISTS public.criterion_demo (
    id integer PRIMARY KEY, x1 double precision NOT NULL,
    x2 double precision NOT NULL, y double precision NOT NULL
);
INSERT INTO public.criterion_demo
SELECT i, i::float8, (i%7)::float8, (3+2*i-4*(i%7))::float8
FROM generate_series(1,100) i
ON CONFLICT (id) DO NOTHING;
