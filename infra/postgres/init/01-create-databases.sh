#!/bin/bash
# Runs once on the first PostgreSQL startup (empty data volume only).
# Creates the three databases/users and the warehouse schema layers.
set -euo pipefail

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" <<-SQL
	CREATE USER airflow PASSWORD '${AIRFLOW_DB_PASSWORD}';
	CREATE DATABASE airflow OWNER airflow;

	CREATE USER superset PASSWORD '${SUPERSET_DB_PASSWORD}';
	CREATE DATABASE superset OWNER superset;

	CREATE USER brazil_economy PASSWORD '${BRAZIL_ECONOMY_DB_PASSWORD}';
	CREATE DATABASE brazil_economy OWNER brazil_economy;
SQL

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d brazil_economy <<-SQL
	CREATE SCHEMA raw AUTHORIZATION brazil_economy;
	CREATE SCHEMA staging AUTHORIZATION brazil_economy;
	CREATE SCHEMA marts AUTHORIZATION brazil_economy;
SQL

echo "brazil-economy-observatory databases ready: airflow, superset, brazil_economy (raw/staging/marts)"
