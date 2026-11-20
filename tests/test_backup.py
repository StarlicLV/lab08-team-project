"""Unit tests for the participant 3 SQLite backup service."""

import sqlite3
from datetime import datetime, timezone

import pytest

from scripts.backup import create_backup, prune_backups


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "source.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE notes (value TEXT NOT NULL)")
        connection.execute("INSERT INTO notes VALUES ('before backup')")
    return path


def test_create_backup_is_a_restorable_sqlite_snapshot(database, tmp_path):
    # Arrange
    backups = tmp_path / "backups"
    timestamp = datetime(2026, 11, 20, tzinfo=timezone.utc)

    # Act
    saved = create_backup(database, backups, now=timestamp)

    # Assert
    assert saved.name == "database-20261120T000000000000Z.sqlite3"
    with sqlite3.connect(saved) as restored:
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("SELECT value FROM notes").fetchone()[0] == "before backup"


def test_create_backup_rejects_missing_database(tmp_path):
    # Arrange / Act / Assert
    with pytest.raises(FileNotFoundError):
        create_backup(tmp_path / "missing.sqlite3", tmp_path / "backups")


def test_prune_backups_keeps_newest_and_ignores_other_files(tmp_path):
    # Arrange
    backups = tmp_path / "backups"
    backups.mkdir()
    paths = [backups / f"database-20261120T00000{index}000000Z.sqlite3" for index in range(4)]
    for index, path in enumerate(paths):
        path.write_bytes(str(index).encode())
    unrelated = backups / "keep-me.txt"
    unrelated.write_text("not a database backup", encoding="utf-8")

    # Act
    removed = prune_backups(backups, keep=2)

    # Assert
    assert len(removed) == 2
    assert len(list(backups.glob("database-*.sqlite3"))) == 2
    assert unrelated.read_text(encoding="utf-8") == "not a database backup"


def test_prune_backups_requires_positive_retention(tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        prune_backups(tmp_path, keep=0)
