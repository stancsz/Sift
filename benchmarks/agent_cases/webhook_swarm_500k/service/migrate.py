"""Legacy delivery schema upgrade starter."""

import sqlite3


def migrate(connection: sqlite3.Connection) -> None:
    """Upgrade the legacy table while retaining all existing rows."""
    # Starter only creates a placeholder column and is not idempotent.
    connection.execute("ALTER TABLE deliveries ADD COLUMN migrated INTEGER DEFAULT 0")
