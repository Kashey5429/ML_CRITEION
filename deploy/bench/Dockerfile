FROM postgres:15-bookworm
ARG MADLIB_VERSION=2.1.0
ARG BUILD_JOBS=2
# PL/Python uses the distribution Python; the application has its own Python 3.12 image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake m4 curl ca-certificates libboost-dev \
    postgresql-server-dev-15 postgresql-plpython3-15 python3-dev python3-venv \
    && rm -rf /var/lib/apt/lists/*
RUN python3 -m venv /opt/madlib-python && \
    /opt/madlib-python/bin/pip install --no-cache-dir \
    PyYAML==6.0.1 pyxb-x==1.2.6.1 numpy==1.25.2
ENV PATH="/opt/madlib-python/bin:${PATH}" \
    PYTHONPATH="/opt/madlib-python/lib/python3.11/site-packages"
WORKDIR /opt/madlib-src
RUN curl --fail --location --retry 3 \
    "https://archive.apache.org/dist/madlib/${MADLIB_VERSION}/apache-madlib-${MADLIB_VERSION}-src.tar.gz" \
    -o /tmp/apache-madlib-${MADLIB_VERSION}-src.tar.gz && \
    curl --fail --location --retry 3 \
    "https://archive.apache.org/dist/madlib/${MADLIB_VERSION}/apache-madlib-${MADLIB_VERSION}-src.tar.gz.sha512" \
    -o /tmp/madlib.sha512 && \
    cd /tmp && sha512sum --check madlib.sha512 && \
    tar -xzf apache-madlib-${MADLIB_VERSION}-src.tar.gz -C /opt/madlib-src --strip-components=1
# GCC 12 no longer supplies <array> transitively through Boost headers.
# Explicit include only; no changes to MADlib algorithms.
RUN sed -i '1i#include <array>' src/ports/postgres/dbconnector/Allocator_impl.hpp
COPY deploy/bench/patch_madlib.py /opt/patch_madlib.py
RUN python3 /opt/patch_madlib.py
RUN cmake -S . -B build -DPYTHON_EXECUTABLE=/opt/madlib-python/bin/python3 \
    -DPOSTGRESQL_15_PG_CONFIG=/usr/lib/postgresql/15/bin/pg_config && \
    cmake --build build --parallel ${BUILD_JOBS} && cmake --install build
COPY deploy/bench/init.sh /docker-entrypoint-initdb.d/20-madlib.sh
COPY deploy/bench/smoke.sql /opt/checks/smoke.sql
COPY deploy/bench/closest_columns.sql /opt/checks/closest_columns.sql
COPY deploy/bench/resources.sql /opt/checks/resources.sql
WORKDIR /var/lib/postgresql
