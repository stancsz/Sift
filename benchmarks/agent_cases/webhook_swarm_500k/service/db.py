"""SQLite persistence starter for the webhook delivery service."""

from pathlib import Path
import sqlite3


ROOT = Path(__file__).resolve().parents[1]


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path, timeout=5.0, isolation_level=None,
                                 check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def initialize(connection: sqlite3.Connection) -> None:
    """Create a new database at the legacy schema, then apply the migration."""
    exists = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='deliveries'"
    ).fetchone()
    if not exists:
        connection.executescript((ROOT / "migrations" / "001_legacy.sql").read_text())
    from service.migrate import migrate

    migrate(connection)


def metrics_snapshot(connection: sqlite3.Connection, now: int) -> dict:
    """Return the operational counters required by docs/operations.md."""
    # Starter intentionally reports an incomplete view.
    row = connection.execute("SELECT COUNT(*) AS count FROM deliveries").fetchone()
    return {"total": row["count"], "queued": 0, "leased": 0,
            "delivered": 0, "permanent_failure": 0, "dead_letter": 0,
            "due_now": 0, "oldest_due_age_seconds": None}
