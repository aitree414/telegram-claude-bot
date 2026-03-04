"""Automatic repair mechanisms for the Telegram Claude Bot.

This module provides tools for detecting and repairing common issues
such as corrupted databases, malformed JSON files, and other system
problems that can occur during bot operation.
"""

import json
import logging
import sqlite3
import shutil
import time
import os
from pathlib import Path
from typing import Optional, Any, Dict, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Database schemas for repair operations
CONVERSATIONS_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_id ON messages(user_id);
"""

# Mapping of database files to their schemas
DATABASE_SCHEMAS = {
    "conversations.db": CONVERSATIONS_DB_SCHEMA,
}


class DatabaseRepair:
    """Repair utilities for SQLite databases."""

    @staticmethod
    def check_database_integrity(db_path: Path) -> bool:
        """Check SQLite database integrity using PRAGMA integrity_check.

        Returns:
            True if database is intact, False if corrupted.
        """
        if not db_path.exists():
            logger.warning(f"Database file does not exist: {db_path}")
            return False

        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()

            # Run integrity check
            cursor.execute("PRAGMA integrity_check")
            result = cursor.fetchone()

            conn.close()

            if result and result[0] == "ok":
                logger.debug(f"Database integrity check passed: {db_path}")
                return True
            else:
                logger.error(f"Database integrity check failed: {db_path}, result: {result}")
                return False

        except sqlite3.Error as e:
            logger.error(f"Database integrity check error for {db_path}: {e}")
            return False

    @staticmethod
    def backup_database(db_path: Path, max_backups: int = 5) -> Optional[Path]:
        """Create a backup of the database.

        Args:
            db_path: Path to the database file
            max_backups: Maximum number of backup files to keep

        Returns:
            Path to the backup file, or None if backup failed
        """
        if not db_path.exists():
            logger.warning(f"Cannot backup non-existent database: {db_path}")
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = db_path.parent / f"{db_path.name}.backup.{timestamp}"

        try:
            # Use SQLite backup API for proper backup
            source_conn = sqlite3.connect(str(db_path))
            backup_conn = sqlite3.connect(str(backup_path))

            source_conn.backup(backup_conn)

            backup_conn.close()
            source_conn.close()

            logger.info(f"Database backup created: {backup_path}")

            # Clean up old backups
            DatabaseRepair._cleanup_old_backups(db_path, max_backups)

            return backup_path

        except sqlite3.Error as e:
            logger.error(f"Database backup failed for {db_path}: {e}")
            # Fallback to file copy
            try:
                shutil.copy2(db_path, backup_path)
                logger.info(f"Database backup created (fallback): {backup_path}")
                return backup_path
            except Exception as e2:
                logger.error(f"Database backup fallback also failed: {e2}")
                return None

    @staticmethod
    def _cleanup_old_backups(db_path: Path, max_backups: int):
        """Remove old backup files, keeping only the most recent ones."""
        backup_pattern = f"{db_path.name}.backup.*"
        backups = list(db_path.parent.glob(backup_pattern))

        if len(backups) > max_backups:
            # Sort by modification time (oldest first)
            backups.sort(key=lambda x: x.stat().st_mtime)

            # Remove oldest backups
            for backup in backups[:-max_backups]:
                try:
                    backup.unlink()
                    logger.debug(f"Removed old backup: {backup}")
                except Exception as e:
                    logger.warning(f"Failed to remove old backup {backup}: {e}")

    @staticmethod
    def get_schema_for_db(db_path: Path) -> Optional[str]:
        """Get schema SQL for a database file based on its name.

        Args:
            db_path: Path to the database file

        Returns:
            Schema SQL string, or None if schema not known
        """
        db_name = db_path.name
        return DATABASE_SCHEMAS.get(db_name)

    @staticmethod
    def repair_database(db_path: Path, schema_sql: Optional[str] = None) -> bool:
        """Attempt to repair a corrupted database.

        Args:
            db_path: Path to the database file
            schema_sql: Optional SQL to recreate schema if needed

        Returns:
            True if repair was successful, False otherwise
        """
        logger.info(f"Attempting to repair database: {db_path}")

        # Try to get schema if not provided
        if schema_sql is None:
            schema_sql = DatabaseRepair.get_schema_for_db(db_path)
            if schema_sql:
                logger.debug(f"Found schema for {db_path.name}")
            else:
                logger.warning(f"No schema available for {db_path.name}, repair may be limited")

        # First, create a backup
        backup_path = DatabaseRepair.backup_database(db_path)
        if not backup_path:
            logger.warning("Failed to create backup before repair")

        try:
            # Try to dump and reload the database
            temp_path = db_path.parent / f"{db_path.name}.temp.{int(time.time())}"

            # Connect to source database
            source_conn = sqlite3.connect(str(db_path))
            source_conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

            # Create new database
            dest_conn = sqlite3.connect(str(temp_path))

            # Copy data
            source_conn.backup(dest_conn)

            dest_conn.close()
            source_conn.close()

            # Replace old database with new one
            db_path.unlink(missing_ok=True)
            temp_path.rename(db_path)

            logger.info(f"Database repair successful: {db_path}")
            return True

        except sqlite3.Error as e:
            logger.error(f"Database repair failed: {e}")

            # If repair failed and we have schema SQL, try to recreate
            if schema_sql:
                logger.info("Attempting to recreate database from schema")
                try:
                    db_path.unlink(missing_ok=True)
                    conn = sqlite3.connect(str(db_path))
                    conn.executescript(schema_sql)
                    conn.close()
                    logger.info("Database recreated from schema")
                    return True
                except Exception as e2:
                    logger.error(f"Database recreation failed: {e2}")

            return False


class FileRepair:
    """Repair utilities for JSON and other configuration files."""

    @staticmethod
    def repair_json_file(file_path: Path, default_content: Any = None, max_attempts: int = 3) -> bool:
        """Repair a corrupted JSON file.

        Args:
            file_path: Path to the JSON file
            default_content: Default content to use if file cannot be repaired
            max_attempts: Maximum number of repair attempts

        Returns:
            True if file was repaired or is valid, False otherwise
        """
        for attempt in range(max_attempts):
            try:
                # Try to read the file
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = json.load(f)

                # File is valid
                logger.debug(f"JSON file is valid: {file_path}")
                return True

            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.warning(f"JSON file corrupted (attempt {attempt + 1}/{max_attempts}): {file_path}, error: {e}")

                # Create backup of corrupted file
                if attempt == 0:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_path = file_path.parent / f"{file_path.name}.corrupted.{timestamp}"
                    try:
                        shutil.copy2(file_path, backup_path)
                        logger.info(f"Backup of corrupted file created: {backup_path}")
                    except Exception as backup_error:
                        logger.warning(f"Failed to backup corrupted file: {backup_error}")

                # Try to fix common issues
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        raw_content = f.read()

                    # Try to find JSON object/array
                    json_start = raw_content.find('{')
                    json_end = raw_content.rfind('}') + 1

                    if json_start >= 0 and json_end > json_start:
                        json_str = raw_content[json_start:json_end]
                        json.loads(json_str)  # Validate

                        # Write repaired content
                        with open(file_path, 'w', encoding='utf-8') as f:
                            f.write(json_str)

                        logger.info(f"JSON file repaired by extracting JSON from corrupted file: {file_path}")
                        return True

                except Exception:
                    pass

                # If we're on the last attempt and have default content, use it
                if attempt == max_attempts - 1 and default_content is not None:
                    try:
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(default_content, f, indent=2, ensure_ascii=False)

                        logger.info(f"JSON file recreated with default content: {file_path}")
                        return True
                    except Exception as write_error:
                        logger.error(f"Failed to write default content to {file_path}: {write_error}")

            except Exception as e:
                logger.error(f"Unexpected error reading JSON file {file_path}: {e}")

        return False

    @staticmethod
    def ensure_directory_structure(base_dir: Path, subdirs: List[str]) -> bool:
        """Ensure that required directory structure exists.

        Args:
            base_dir: Base directory
            subdirs: List of subdirectory paths relative to base_dir

        Returns:
            True if all directories exist or were created, False otherwise
        """
        try:
            base_dir.mkdir(parents=True, exist_ok=True)

            for subdir in subdirs:
                dir_path = base_dir / subdir
                dir_path.mkdir(parents=True, exist_ok=True)

            logger.debug(f"Directory structure verified: {base_dir}")
            return True

        except Exception as e:
            logger.error(f"Failed to create directory structure {base_dir}: {e}")
            return False


class AutoRepairManager:
    """Manager for automatic repair operations."""

    def __init__(self):
        self.db_repair = DatabaseRepair()
        self.file_repair = FileRepair()

    def run_startup_checks(self) -> bool:
        """Run all startup checks and repairs.

        Returns:
            True if all checks passed or repairs were successful
        """
        logger.info("Running startup checks and repairs...")

        all_ok = True

        # Check data directory
        data_dir = Path(__file__).parent.parent / "data"
        if self.file_repair.ensure_directory_structure(
            data_dir,
            ["sessions", "sessions/archive"]
        ):
            logger.info("✓ Data directory structure OK")
        else:
            logger.error("✗ Data directory structure check failed")
            all_ok = False

        # Check conversations database (if it exists)
        db_path = Path.home() / "telegram-claude-bot" / "conversations.db"
        if db_path.exists():
            if self.db_repair.check_database_integrity(db_path):
                logger.info("✓ Conversations database integrity OK")
            else:
                logger.warning("⚠ Conversations database may be corrupted, attempting repair...")
                if self.db_repair.repair_database(db_path):
                    logger.info("✓ Database repair successful")
                else:
                    logger.error("✗ Database repair failed")
                    all_ok = False
        else:
            logger.info("✓ Conversations database does not exist (this is OK for new installations)")

        # Check tasks file
        tasks_file = data_dir / "tasks.json"
        if tasks_file.exists():
            if self.file_repair.repair_json_file(tasks_file, default_content={"tasks": []}):
                logger.info("✓ Tasks file OK")
            else:
                logger.error("✗ Tasks file repair failed")
                all_ok = False
        else:
            logger.info("✓ Tasks file does not exist (will be created when needed)")

        logger.info("Startup checks completed")
        return all_ok

    def schedule_periodic_checks(self, interval_hours: int = 24):
        """Schedule periodic checks (to be called from a scheduler).

        Args:
            interval_hours: How often to run checks (in hours)
        """
        logger.info(f"Scheduling periodic checks every {interval_hours} hours")
        # This would typically be integrated with apscheduler or similar
        # For now, just log the intention

    def emergency_repair(self) -> Dict[str, bool]:
        """Run emergency repair procedures.

        Returns:
            Dictionary of repair operations and their success status
        """
        logger.warning("Running emergency repair procedures...")

        results = {}

        # Repair conversations database
        db_path = Path.home() / "telegram-claude-bot" / "conversations.db"
        if db_path.exists():
            # We would need schema SQL for proper repair
            # For now, just check integrity
            results["database_integrity"] = self.db_repair.check_database_integrity(db_path)

        # Repair tasks file
        data_dir = Path(__file__).parent.parent / "data"
        tasks_file = data_dir / "tasks.json"
        if tasks_file.exists():
            results["tasks_file"] = self.file_repair.repair_json_file(
                tasks_file,
                default_content={"tasks": []}
            )

        # Ensure directory structure
        results["directory_structure"] = self.file_repair.ensure_directory_structure(
            data_dir,
            ["sessions", "sessions/archive"]
        )

        logger.warning(f"Emergency repair completed: {results}")
        return results


# Global instance
_repair_manager = None

def get_repair_manager() -> AutoRepairManager:
    """Get the global repair manager instance."""
    global _repair_manager
    if _repair_manager is None:
        _repair_manager = AutoRepairManager()
    return _repair_manager