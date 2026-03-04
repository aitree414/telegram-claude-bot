import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

DB_PATH = Path.home() / "telegram-claude-bot" / "conversations.db"
MAX_HISTORY = 20   # was 100 — reduces token cost significantly

logger = logging.getLogger(__name__)


class ConversationMemory:
    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        # Initialize database schema if not exists
        with self._get_conn() as conn:
            self._init_db(conn)

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a thread-local SQLite connection with WAL mode enabled."""
        if not hasattr(self._local, 'conn'):
            with self._init_lock:
                if not hasattr(self._local, 'conn'):
                    # Create new connection for this thread
                    conn = sqlite3.connect(
                        str(DB_PATH),
                        check_same_thread=False,
                    )
                    # Enable WAL mode for better concurrency
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")  # Good balance between safety and performance
                    conn.execute("PRAGMA foreign_keys=ON")
                    self._local.conn = conn
                    logger.debug(f"Created new SQLite connection for thread {threading.current_thread().name}")

        conn = self._local.conn
        try:
            yield conn
        except sqlite3.Error as e:
            logger.error(f"SQLite error: {e}")
            # Close and remove the broken connection
            try:
                conn.close()
            except:
                pass
            delattr(self._local, 'conn')
            raise

    def _init_db(self, conn: sqlite3.Connection) -> None:
        """Initialize database schema."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON messages(user_id)")
        conn.commit()

    def add_message(self, user_id: int, role: str, content: Any) -> None:
        content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content_str),
            )
            conn.commit()

    def get_history(self, user_id: int) -> list[dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT role, content FROM messages WHERE user_id = ? ORDER BY id DESC LIMIT ?",
                (user_id, MAX_HISTORY),
            )
            rows = cursor.fetchall()

        messages = []
        for role, content_str in reversed(rows):
            try:
                content = json.loads(content_str)
            except (json.JSONDecodeError, ValueError):
                content = content_str
            messages.append({"role": role, "content": content})
        return messages

    def clear(self, user_id: int) -> None:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            conn.commit()

    def get_stats(self, user_id: int) -> dict[str, int]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)
            )
            total = cursor.fetchone()[0]
        return {"total_messages": total}
