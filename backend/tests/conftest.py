import pytest


@pytest.fixture(autouse=True)
def isolate_application_startup_database(monkeypatch):
    """Keep API test lifespan recovery away from the real application database."""
    monkeypatch.setattr(
        "app.main.recover_interrupted_discovery_scans",
        lambda db: 0,
    )
