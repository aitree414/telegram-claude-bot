import json
import logging
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

from . import constants

# Constants
TASKS_FILE = Path(__file__).parent.parent / "data" / "tasks.json"
WEB_TASKS_FILE = Path(__file__).parent.parent / "web-apps" / "data" / "tasks.json"
DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Auto-repair settings
MAX_RETRIES = constants.MAX_RETRIES
RETRY_DELAY = constants.RETRY_DELAY
BACKUP_FILES = True
MAX_BACKUPS = constants.MAX_BACKUPS

class TaskStatus(Enum):
    """Status of a task."""
    PENDING = "pending"      # Task just created
    IN_PROGRESS = "in_progress"  # Task is being processed
    COMPLETED = "completed"  # Task completed successfully
    FAILED = "failed"        # Task failed

class TaskType(Enum):
    """Task types matching session manager."""
    STOCK = "stock"
    PORTFOLIO = "portfolio"
    ALERTS = "alerts"
    WATCHLIST = "watchlist"
    POLY = "poly"
    CHAT = "chat"
    GENERAL = "general"
    OTHER = "other"  # For any other types

@dataclass
class Task:
    """A tracked task."""
    task_id: str
    user_id: int
    task_type: TaskType
    status: TaskStatus
    summary: str
    full_conversation: List[Dict[str, Any]]
    created_at: float
    updated_at: float
    metadata: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "task_type": self.task_type.value,
            "status": self.status.value,
            "summary": self.summary,
            "full_conversation": self.full_conversation,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """Create Task from dictionary."""
        return cls(
            task_id=data["task_id"],
            user_id=data["user_id"],
            task_type=TaskType(data["task_type"]),
            status=TaskStatus(data["status"]),
            summary=data["summary"],
            full_conversation=data["full_conversation"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            metadata=data.get("metadata", {})
        )


class TaskTracker:
    """Tracks tasks for Telegram Claude Bot."""

    def __init__(self):
        self._lock = threading.RLock()
        self._tasks: Dict[str, Task] = {}
        self._load_tasks()

    def _load_tasks(self) -> None:
        """Load tasks from JSON file with auto-repair on failure."""
        with self._lock:
            if not TASKS_FILE.exists():
                logger.info(f"Tasks file {TASKS_FILE} does not exist, starting fresh")
                # Also check web file for consistency
                if WEB_TASKS_FILE.exists():
                    try:
                        logger.info(f"Web tasks file exists, attempting to copy to main location")
                        import shutil
                        shutil.copy2(WEB_TASKS_FILE, TASKS_FILE)
                        logger.info(f"Copied web tasks file to main location")
                    except Exception as e:
                        logger.warning(f"Failed to copy web tasks file: {e}")
                return

            # Try to load with retry and repair
            last_error = None
            loaded_successfully = False

            for attempt in range(MAX_RETRIES):
                try:
                    # Try to repair file before loading
                    if attempt > 0:
                        self._repair_json_file(TASKS_FILE)

                    with open(TASKS_FILE, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    if not isinstance(data, list):
                        logger.error(f"Tasks file {TASKS_FILE} does not contain a list")
                        # Try to recover by creating empty list
                        data = []

                    # Load tasks
                    loaded_count = 0
                    for item in data:
                        try:
                            task = Task.from_dict(item)
                            self._tasks[task.task_id] = task
                            loaded_count += 1
                        except Exception as e:
                            logger.error(f"Failed to load task {item.get('task_id', 'unknown')}: {e}")

                    logger.info(f"Loaded {loaded_count} tasks from {TASKS_FILE}")
                    loaded_successfully = True
                    break

                except json.JSONDecodeError as e:
                    last_error = e
                    logger.warning(f"JSON decode error loading tasks (attempt {attempt + 1}): {e}")

                    if attempt < MAX_RETRIES - 1:
                        # Try to repair before next attempt
                        self._repair_json_file(TASKS_FILE)
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.error(f"Failed to load tasks after {MAX_RETRIES} attempts: {e}")
                        # Try to load from web file as fallback
                        self._try_load_from_web_backup()

                except Exception as e:
                    last_error = e
                    logger.error(f"Error loading tasks (attempt {attempt + 1}): {e}")

                    if attempt < MAX_RETRIES - 1:
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.error(f"Failed to load tasks after {MAX_RETRIES} attempts: {e}")
                        # Try to load from web file as fallback
                        self._try_load_from_web_backup()

            if not loaded_successfully and last_error:
                logger.error(f"Could not load tasks from {TASKS_FILE}: {last_error}")
                # Create empty tasks file
                try:
                    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                        json.dump([], f, ensure_ascii=False, indent=2)
                    logger.info(f"Created empty tasks file at {TASKS_FILE}")
                except Exception as e:
                    logger.error(f"Failed to create empty tasks file: {e}")

    def _try_load_from_web_backup(self) -> None:
        """Try to load tasks from web backup file when main file fails."""
        try:
            if not WEB_TASKS_FILE.exists():
                logger.info(f"Web backup file {WEB_TASKS_FILE} does not exist")
                return

            logger.info(f"Attempting to load tasks from web backup {WEB_TASKS_FILE}")

            with open(WEB_TASKS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, list):
                logger.error(f"Web backup file does not contain a list")
                return

            # Load tasks from web backup
            loaded_count = 0
            for item in data:
                try:
                    task = Task.from_dict(item)
                    self._tasks[task.task_id] = task
                    loaded_count += 1
                except Exception as e:
                    logger.error(f"Failed to load task from web backup {item.get('task_id', 'unknown')}: {e}")

            if loaded_count > 0:
                logger.info(f"Loaded {loaded_count} tasks from web backup {WEB_TASKS_FILE}")
                # Try to save recovered tasks to main location
                try:
                    tasks_list = [task.to_dict() for task in self._tasks.values()]
                    with open(TASKS_FILE, 'w', encoding='utf-8') as f:
                        json.dump(tasks_list, f, ensure_ascii=False, indent=2)
                    logger.info(f"Saved recovered tasks to main file {TASKS_FILE}")
                except Exception as e:
                    logger.error(f"Failed to save recovered tasks to main file: {e}")
        except Exception as e:
            logger.error(f"Failed to load tasks from web backup {WEB_TASKS_FILE}: {e}")

    def _backup_file(self, file_path: Path) -> None:
        """Create a backup of a file before overwriting."""
        if not BACKUP_FILES or not file_path.exists():
            return

        try:
            backup_dir = file_path.parent / "backups"
            backup_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_name = f"{file_path.stem}_backup_{timestamp}{file_path.suffix}"
            backup_path = backup_dir / backup_name

            shutil.copy2(file_path, backup_path)

            # Clean up old backups
            if MAX_BACKUPS > 0:
                backups = sorted(backup_dir.glob(f"{file_path.stem}_backup_*{file_path.suffix}"))
                if len(backups) > MAX_BACKUPS:
                    for old_backup in backups[:-MAX_BACKUPS]:
                        old_backup.unlink()

        except Exception as e:
            logger.warning(f"Failed to create backup for {file_path}: {e}")

    def _repair_json_file(self, file_path: Path) -> bool:
        """Attempt to repair a corrupted JSON file."""
        try:
            if not file_path.exists():
                logger.info(f"File {file_path} does not exist, nothing to repair")
                return False

            # Try to read and parse the file
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read().strip()

            if not content:
                logger.warning(f"File {file_path} is empty, cannot repair")
                return False

            # Try to parse as JSON
            try:
                data = json.loads(content)
                # If we can parse it, it's not corrupted
                return True
            except json.JSONDecodeError as e:
                logger.warning(f"JSON parse error in {file_path}: {e}, attempting repair")

            # Attempt 1: Try to fix common JSON issues
            # Remove trailing commas
            content = re.sub(r',\s*}', '}', content)
            content = re.sub(r',\s*]', ']', content)

            # Try parsing again
            try:
                data = json.loads(content)
                # Save repaired version
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(f"Successfully repaired {file_path}")
                return True
            except json.JSONDecodeError:
                pass

            # Attempt 2: Try to extract valid JSON array
            # Look for array start and end
            start = content.find('[')
            end = content.rfind(']')
            if start != -1 and end != -1 and end > start:
                partial_content = content[start:end+1]
                try:
                    data = json.loads(partial_content)
                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                    logger.info(f"Extracted valid JSON array from {file_path}")
                    return True
                except json.JSONDecodeError:
                    pass

            # If all repair attempts fail, create empty array
            logger.error(f"Could not repair {file_path}, creating empty array")
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
            return False

        except Exception as e:
            logger.error(f"Error during JSON repair of {file_path}: {e}")
            return False

    def _save_tasks(self) -> None:
        """Save tasks to JSON file with retry and auto-repair logic."""
        with self._lock:
            tasks_list = [task.to_dict() for task in self._tasks.values()]

            # Save to both locations with retry logic
            files_to_save = [(TASKS_FILE, "primary"), (WEB_TASKS_FILE, "web")]

            for file_path, file_type in files_to_save:
                last_error = None
                success = False

                for attempt in range(MAX_RETRIES):
                    try:
                        # Create backup before writing
                        self._backup_file(file_path)

                        # Ensure directory exists
                        file_path.parent.mkdir(parents=True, exist_ok=True)

                        # Write file
                        with open(file_path, 'w', encoding='utf-8') as f:
                            json.dump(tasks_list, f, ensure_ascii=False, indent=2)

                        logger.debug(f"Successfully saved tasks to {file_type} file (attempt {attempt + 1})")
                        success = True
                        break

                    except Exception as e:
                        last_error = e
                        logger.warning(f"Failed to save tasks to {file_type} file (attempt {attempt + 1}): {e}")

                        if attempt < MAX_RETRIES - 1:
                            time.sleep(RETRY_DELAY)
                            # Try to repair file before next attempt
                            self._repair_json_file(file_path)

                if not success:
                    logger.error(f"Failed to save tasks to {file_type} file after {MAX_RETRIES} attempts: {last_error}")

                    # Try emergency recovery: write to alternative location
                    try:
                        alt_path = file_path.with_suffix('.json.bak')
                        with open(alt_path, 'w', encoding='utf-8') as f:
                            json.dump(tasks_list, f, ensure_ascii=False, indent=2)
                        logger.error(f"Emergency save to {alt_path}")
                    except Exception as e:
                        logger.error(f"Emergency save also failed: {e}")

    def _generate_task_id(self, user_id: int, task_type: TaskType) -> str:
        """Generate a unique task ID."""
        timestamp = int(time.time() * 1000)
        return f"{task_type.value}_{user_id}_{timestamp}"

    def _generate_summary(self, messages: List[Dict[str, Any]], task_type: TaskType) -> str:
        """Generate a summary from conversation messages."""
        if not messages:
            return f"{task_type.value} task"

        # Get the last user message as context
        user_messages = [msg for msg in messages if msg.get("role") == "user"]
        if user_messages:
            last_user_msg = user_messages[-1].get("content", "")
            if isinstance(last_user_msg, str):
                # Truncate if too long
                if len(last_user_msg) > 100:
                    return f"{task_type.value}: {last_user_msg[:97]}..."
                return f"{task_type.value}: {last_user_msg}"

        return f"{task_type.value} task with {len(messages)} messages"

    def record_task(self, user_id: int, task_type: TaskType,
                    messages: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Record a new task or update an existing one.

        Args:
            user_id: Telegram user ID
            task_type: Type of task
            messages: Full conversation messages
            metadata: Additional metadata (e.g., session_id, ticker, etc.)

        Returns:
            task_id: The ID of the recorded task
        """
        with self._lock:
            # Check if there's an existing pending/in-progress task of same type for this user
            existing_task_id = None
            for task in self._tasks.values():
                if (task.user_id == user_id and
                    task.task_type == task_type and
                    task.status in [TaskStatus.PENDING, TaskStatus.IN_PROGRESS]):
                    existing_task_id = task.task_id
                    break

            if existing_task_id:
                # Update existing task
                task = self._tasks[existing_task_id]
                task.full_conversation = messages
                task.summary = self._generate_summary(messages, task_type)
                task.updated_at = time.time()
                if metadata:
                    task.metadata.update(metadata)

                # If there's an assistant response, mark as completed
                assistant_messages = [msg for msg in messages if msg.get("role") == "assistant"]
                if assistant_messages:
                    task.status = TaskStatus.COMPLETED
                else:
                    task.status = TaskStatus.IN_PROGRESS

                logger.debug(f"Updated task {existing_task_id} for user {user_id}")
            else:
                # Create new task
                task_id = self._generate_task_id(user_id, task_type)
                summary = self._generate_summary(messages, task_type)

                # Determine initial status
                assistant_messages = [msg for msg in messages if msg.get("role") == "assistant"]
                if assistant_messages:
                    status = TaskStatus.COMPLETED
                else:
                    status = TaskStatus.PENDING

                metadata = metadata or {}
                metadata["user_id"] = user_id
                metadata["task_type"] = task_type.value

                task = Task(
                    task_id=task_id,
                    user_id=user_id,
                    task_type=task_type,
                    status=status,
                    summary=summary,
                    full_conversation=messages,
                    created_at=time.time(),
                    updated_at=time.time(),
                    metadata=metadata
                )

                self._tasks[task_id] = task
                logger.debug(f"Created new task {task_id} for user {user_id}")

            self._save_tasks()
            return task.task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID."""
        with self._lock:
            return self._tasks.get(task_id)

    def get_user_tasks(self, user_id: int, status_filter: Optional[TaskStatus] = None) -> List[Task]:
        """Get all tasks for a user, optionally filtered by status."""
        with self._lock:
            tasks = [task for task in self._tasks.values() if task.user_id == user_id]
            if status_filter:
                tasks = [task for task in tasks if task.status == status_filter]
            return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def get_all_tasks(self, status_filter: Optional[TaskStatus] = None) -> List[Task]:
        """Get all tasks, optionally filtered by status."""
        with self._lock:
            tasks = list(self._tasks.values())
            if status_filter:
                tasks = [task for task in tasks if task.status == status_filter]
            return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def update_task_status(self, task_id: str, status: TaskStatus) -> bool:
        """Update task status."""
        with self._lock:
            if task_id not in self._tasks:
                logger.error(f"Task {task_id} not found")
                return False

            self._tasks[task_id].status = status
            self._tasks[task_id].updated_at = time.time()
            self._save_tasks()
            logger.debug(f"Updated task {task_id} status to {status.value}")
            return True

    def delete_task(self, task_id: str) -> bool:
        """Delete a task."""
        with self._lock:
            if task_id not in self._tasks:
                return False

            del self._tasks[task_id]
            self._save_tasks()
            logger.debug(f"Deleted task {task_id}")
            return True

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about tasks."""
        with self._lock:
            total = len(self._tasks)
            by_status = {status.value: 0 for status in TaskStatus}
            by_type = {task_type.value: 0 for task_type in TaskType}

            for task in self._tasks.values():
                by_status[task.status.value] += 1
                by_type[task.task_type.value] += 1

            return {
                "total_tasks": total,
                "by_status": by_status,
                "by_type": by_type,
                "last_updated": datetime.now().isoformat()
            }


# Global task tracker instance
_task_tracker = None

def get_task_tracker() -> TaskTracker:
    """Get the global task tracker instance."""
    global _task_tracker
    if _task_tracker is None:
        _task_tracker = TaskTracker()
    return _task_tracker