"""Shared, dependency-light helpers for the brazil_economy DAGs.

Everything here is pure Python (no Airflow imports) so it can be unit-tested in
isolation with plain pytest — the DAGs import these functions instead of
embedding the fiddly logic inline.
"""
