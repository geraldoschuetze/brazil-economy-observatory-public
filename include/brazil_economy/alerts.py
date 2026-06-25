"""Failure alerting for the brazil_economy DAGs.

`notify_failure` is wired into every DAG's `on_failure_callback`. It posts a
compact message to a generic JSON webhook (Slack-compatible: ``{"text": ...}``)
when ``BRAZIL_ECONOMY_ALERT_WEBHOOK`` is set, and otherwise just logs — so the pipeline
behaves identically with or without an alerting channel configured, and a
broken webhook can never fail a task (the callback swallows its own errors).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

WEBHOOK_ENV = "BRAZIL_ECONOMY_ALERT_WEBHOOK"


def build_message(context: dict) -> str:
    """Render a one-line alert from an Airflow callback context."""
    dag = getattr(context.get("dag"), "dag_id", "?")
    ti = context.get("task_instance")
    task = getattr(ti, "task_id", "?")
    run_id = context.get("run_id", "?")
    exc = context.get("exception")
    # Truncate the exception text so internal detail (paths, SQL, secrets that may
    # surface in messages) is not shipped wholesale to an off-host webhook.
    reason = f" — {type(exc).__name__}: {str(exc)[:200]}" if exc else ""
    return f"🔴 brazil_economy: {dag}.{task} failed (run {run_id}){reason}"


def notify_failure(context: dict) -> None:
    """Airflow on_failure_callback: alert via webhook if configured, else log."""
    message = build_message(context)
    log.error(message)

    url = os.environ.get(WEBHOOK_ENV)
    if not url:
        return
    try:
        import requests

        requests.post(url, json={"text": message}, timeout=10)
    except Exception:  # never let alerting break the run
        log.exception("failed to post failure alert to webhook")
