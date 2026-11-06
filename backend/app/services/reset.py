import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.database import engine


def create_database_backup() -> Path:
    """Create a consistent SQLite backup, including committed WAL data."""
    if engine.dialect.name != "sqlite":
        raise RuntimeError("Automatic reset backups currently require SQLite.")

    database_name = engine.url.database
    if not database_name or database_name == ":memory:":
        raise RuntimeError("A file-backed SQLite database is required.")

    database_path = Path(database_name).expanduser().resolve()
    if not database_path.is_file():
        raise RuntimeError(f"Database file does not exist: {database_path}")

    backup_directory = database_path.parent / "backups"
    backup_directory.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup_path = backup_directory / f"network_stats_before_reset_{timestamp}.db"

    source = sqlite3.connect(str(database_path))
    destination = sqlite3.connect(str(backup_path))

    try:
        source.backup(destination)
        destination.commit()
    except Exception:
        destination.close()
        source.close()
        backup_path.unlink(missing_ok=True)
        raise
    else:
        destination.close()
        source.close()

    return backup_path
