# The official Superset image ships no database drivers — extend it with the
# Postgres one (used both for Superset metadata and the brazil_economy warehouse).
ARG SUPERSET_IMAGE_TAG=6.1.0
FROM apache/superset:${SUPERSET_IMAGE_TAG}

USER root
# Superset 6 runs from a uv-managed virtualenv at /app/.venv that has no `pip`;
# the system pip would install outside it. Install the driver INTO the venv with
# uv, otherwise Superset fails at boot with ModuleNotFoundError: psycopg2.
RUN uv pip install --no-cache --python /app/.venv/bin/python psycopg2-binary==2.9.10
USER superset
