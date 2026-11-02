#!/usr/bin/env python3
"""
Hot backup of the vibeHQ SQLite database (safe while the server is running).

  python backup.py                      # -> /data/backups/vibehq-YYYYmmdd-HHMMSS.db, keeps 14
  docker compose exec app python backup.py
"""
import argparse
import os
import sqlite3
import time


def main():
    parser = argparse.ArgumentParser(description="vibeHQ database backup")
    parser.add_argument("--db", default=os.environ.get("VIBEHQ_DB", "vibehq.db"))
    parser.add_argument("--dir", default=None, help="backup folder (default: <db folder>/backups)")
    parser.add_argument("--keep", type=int, default=14, help="number of backups to keep")
    args = parser.parse_args()

    backup_dir = args.dir or os.path.join(os.path.dirname(os.path.abspath(args.db)), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = os.path.join(backup_dir, f"vibehq-{stamp}.db")
    counter = 1
    while os.path.exists(target):
        counter += 1
        target = os.path.join(backup_dir, f"vibehq-{stamp}-{counter}.db")

    source = sqlite3.connect(args.db)
    destination = sqlite3.connect(target)
    with destination:
        source.backup(destination)
    destination.close()
    source.close()

    backups = sorted(name for name in os.listdir(backup_dir) if name.startswith("vibehq-") and name.endswith(".db"))
    for old in backups[:-args.keep]:
        os.remove(os.path.join(backup_dir, old))
    print(f"backup written: {target} ({os.path.getsize(target)} bytes); kept {min(len(backups), args.keep)}")


if __name__ == "__main__":
    main()
