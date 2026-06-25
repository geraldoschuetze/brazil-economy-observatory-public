# Airflow image for brazil-economy-observatory: stock Airflow + dbt-postgres.
#
# dbt is installed in an ISOLATED virtualenv (/opt/dbt-venv) so its dependency
# tree never collides with Airflow's heavily-pinned constraints — the DAG calls
# dbt through that venv's binary. This is the recommended way to run dbt and
# Airflow in one image.
ARG AIRFLOW_IMAGE_NAME=apache/airflow:3.2.2
FROM ${AIRFLOW_IMAGE_NAME}

# pinned for reproducibility; dbt-postgres 1.9.x pulls a compatible dbt-core
ARG DBT_POSTGRES_VERSION=1.9.0

USER root
RUN python -m venv /opt/dbt-venv \
    && /opt/dbt-venv/bin/pip install --no-cache-dir \
        "dbt-postgres==${DBT_POSTGRES_VERSION}" \
    && chown -R airflow: /opt/dbt-venv
USER airflow

# discoverable on PATH for ad-hoc `docker compose exec` debugging
ENV PATH="/opt/dbt-venv/bin:${PATH}"
