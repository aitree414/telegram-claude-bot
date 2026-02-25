import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / "telegram-claude-bot" / "conversations.db"
MAX_HISTORY = 100  # Max messages sent to Claude API per request


class ConversationMemory:
    def __init__(self) -> None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_user_id ON messages(user_id)")
        self._conn.commit()

    def add_message(self, user_id: int, role: str, content: Any) -> None:
        content_str = json.dumps(content, ensure_ascii=False) if not isinstance(content, str) else content
        self._conn.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content_str),
        )
        self._conn.commit()

    def get_history(self, user_id: int) -> list[dict[str, Any]]:
        cursor = self._conn.execute(
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
        self._conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
        self._conn.commit()

    def get_stats(self, user_id: int) -> dict[str, int]:
        cursor = self._conn.execute(
            "SELECT COUNT(*) FROM messages WHERE user_id = ?", (user_id,)
        )
        total = cursor.fetchone()[0]
        return {"total_messages": total}
