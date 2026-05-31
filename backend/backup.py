import datetime
import shutil

from db import DB_PATH

MAX_BACKUPS = 7


def run_startup_backup() -> None:
    """Copy the database to a timestamped file in backups/, keeping the 7 newest.

    Silently does nothing if the database file does not exist yet (first launch).
    """
    if not DB_PATH.exists():
        return

    backups_dir = DB_PATH.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_path = backups_dir / f"trades_{timestamp}.db"
    shutil.copy2(DB_PATH, backup_path)

    backups = sorted(backups_dir.glob("trades_*.db"))
    while len(backups) > MAX_BACKUPS:
        backups.pop(0).unlink()

    print(f"Backup created: {backup_path.name} ({len(backups)} backups retained)")
