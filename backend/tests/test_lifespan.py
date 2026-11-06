from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.main import app
from app.services.scheduler import monitoring_scheduler


def test_application_starts_and_stops_scheduler(monkeypatch):
    start = Mock()
    shutdown = Mock()

    monkeypatch.setattr(monitoring_scheduler, "start", start)
    monkeypatch.setattr(monitoring_scheduler, "shutdown", shutdown)

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

        assert response.status_code == 200
        assert response.json() == {"status": "alive"}

        start.assert_called_once()
        shutdown.assert_not_called()

    shutdown.assert_called_once()
