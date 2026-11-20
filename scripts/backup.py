"""Create periodic, consistent SQLite backups with SQLite's online backup API."""

from __future__ import annotations

import logging
import os
import signal
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger("backup")
BACKUP_PREFIX = "database-"
BACKUP_SUFFIX = ".sqlite3"
_running = True


def _stop(signum, frame):
    """Let Docker stop the periodic loop cleanly."""
    del signum, frame
    global _running
    _running = False


def create_backup(database_path: str | Path, backup_dir: str | Path,
                  now: datetime | None = None) -> Path:
    """Write a transactionally consistent snapshot and atomically publish it."""
    source_path = Path(database_path)
    destination_dir = Path(backup_dir)
    if not source_path.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {source_path}")

    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = timestamp.strftime("%Y%m%dT%H%M%S%fZ")
    destination = destination_dir / f"{BACKUP_PREFIX}{stamp}{BACKUP_SUFFIX}"
    temporary = destination.with_name(destination.name + ".tmp")

    try:
        source_uri = source_path.resolve().as_uri() + "?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source:
            with closing(sqlite3.connect(temporary, timeout=30)) as target:
                source.backup(target)
                integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise sqlite3.DatabaseError(f"Backup integrity check failed: {integrity}")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    LOGGER.info("Створено резервну копію: %s", destination)
    return destination


def prune_backups(backup_dir: str | Path, keep: int) -> list[Path]:
    """Keep the newest `keep` backups; leave unrelated files untouched."""
    if keep < 1:
        raise ValueError("BACKUP_KEEP must be at least 1")
    directory = Path(backup_dir)
    backups = sorted(
        directory.glob(f"{BACKUP_PREFIX}*{BACKUP_SUFFIX}"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    removed = backups[keep:]
    for path in removed:
        path.unlink()
        LOGGER.info("Видалено застарілу копію: %s", path)
    return removed


def run_backup_loop(database_path: str | Path, backup_dir: str | Path,
                    keep: int, interval_seconds: int) -> None:
    """Back up immediately, then repeat; log failures and retry next interval."""
    if interval_seconds < 1:
        raise ValueError("BACKUP_INTERVAL_SECONDS must be at least 1")
    while _running:
        try:
            create_backup(database_path, backup_dir)
            prune_backups(backup_dir, keep)
        except (OSError, sqlite3.Error, ValueError):
            LOGGER.exception("Не вдалося створити резервну копію")
        # Sleep in short intervals so SIGTERM doesn't delay container shutdown.
        remaining = interval_seconds
        while _running and remaining > 0:
            pause = min(remaining, 1)
            time.sleep(pause)
            remaining -= pause


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    run_backup_loop(
        os.environ.get("DATABASE_PATH", "/app/data/database.db"),
        os.environ.get("BACKUP_PATH", "/app/backups"),
        int(os.environ.get("BACKUP_KEEP", "7")),
        int(os.environ.get("BACKUP_INTERVAL_SECONDS", "86400")),
    )


if __name__ == "__main__":
    main()
