"""Standalone entry point for the legacy personal-info/language backfill.

The backfill also runs automatically on every API boot (see api/main.py's
lifespan), so this script exists only for manual/CI reruns -- e.g. to check
progress or force a rerun without restarting the API process. It's safe to
run any number of times; already-migrated rows are skipped.

Usage:
    python -m scripts.backfill_legacy_personal_info
"""

import logging
import sys

sys.path.insert(0, ".")

from utils.logging_utils import setup_logging
from utils.db_storage import DBStorage, init_db_pool
from utils.legacy_migration import backfill_personal_info_and_languages


def main():
    setup_logging()
    logger = logging.getLogger("betterresume.scripts.backfill_legacy_personal_info")
    init_db_pool()
    db = DBStorage()
    db.init_schema()
    stats = backfill_personal_info_and_languages(db)
    logger.info("Backfill finished: %s", stats)
    print(stats)


if __name__ == "__main__":
    main()
