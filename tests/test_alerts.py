"""Unit tests for the failure-alert helper (no Airflow, no real webhook)."""

from __future__ import annotations

from brazil_economy import alerts


class _Dag:
    dag_id = "ingest_sgs"


class _TI:
    task_id = "ingest_series"


def _context(exception=None):
    return {
        "dag": _Dag(),
        "task_instance": _TI(),
        "run_id": "manual__2026-06-14",
        "exception": exception,
    }


def test_build_message_includes_dag_task_and_run():
    msg = alerts.build_message(_context())
    assert "ingest_sgs.ingest_series" in msg
    assert "manual__2026-06-14" in msg


def test_build_message_appends_exception_detail():
    msg = alerts.build_message(_context(ValueError("boom")))
    assert "ValueError: boom" in msg


def test_notify_failure_without_webhook_is_silent(monkeypatch):
    monkeypatch.delenv(alerts.WEBHOOK_ENV, raising=False)
    # must not raise even though no channel is configured
    alerts.notify_failure(_context())


def test_notify_failure_posts_to_webhook(monkeypatch):
    monkeypatch.setenv(alerts.WEBHOOK_ENV, "https://hooks.example/test")
    posted = {}

    class _FakeRequests:
        @staticmethod
        def post(url, json, timeout):
            posted["url"] = url
            posted["json"] = json

    monkeypatch.setitem(__import__("sys").modules, "requests", _FakeRequests)
    alerts.notify_failure(_context(RuntimeError("nope")))
    assert posted["url"] == "https://hooks.example/test"
    assert "text" in posted["json"]


def test_notify_failure_swallows_webhook_errors(monkeypatch):
    monkeypatch.setenv(alerts.WEBHOOK_ENV, "https://hooks.example/test")

    class _BoomRequests:
        @staticmethod
        def post(*args, **kwargs):
            raise OSError("network down")

    monkeypatch.setitem(__import__("sys").modules, "requests", _BoomRequests)
    # a broken webhook must never propagate out of the callback
    alerts.notify_failure(_context())
