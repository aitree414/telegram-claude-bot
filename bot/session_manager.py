import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Any
from dataclasses import dataclass, asdict
import hashlib

logger = logging.getLogger(__name__)

from . import constants

# Constants
SESSIONS_DIR = Path(__file__).parent.parent / "data" / "sessions"
ARCHIVE_DIR = SESSIONS_DIR / "archive"
DEFAULT_MAX_MESSAGES = constants.DEFAULT_MAX_HISTORY_MESSAGES
DEFAULT_MAX_TOKENS = constants.MAX_CONTEXT_WINDOW
ARCHIVE_DAYS = constants.ARCHIVE_DAYS
GENERAL_SESSION_TIMEOUT = constants.GENERAL_SESSION_TIMEOUT

# Ensure directories exist
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


class TaskType(Enum):
    """Task types for session isolation."""
    STOCK = "stock"          # /stock, /analysis, /scan
    PORTFOLIO = "portfolio"  # /buy, /sell, /portfolio
    ALERTS = "alerts"        # /alert, /alerts
    WATCHLIST = "watchlist"  # /watchlist
    POLY = "poly"            # /poly, /poly_pick
    CHAT = "chat"            # General conversation
    GENERAL = "general"      # General task (fallback)


@dataclass
class Message:
    """A single message in a conversation."""
    role: str  # "user", "assistant", "system"
    content: Union[str, List[Dict[str, Any]]]
    timestamp: float  # Unix timestamp

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        return cls(
            role=data["role"],
            content=data["content"],
            timestamp=data["timestamp"]
        )


@dataclass
class Session:
    """A conversation session for a specific task."""
    session_id: str
    task_type: TaskType
    user_id: int
    created_at: float
    last_activity: float
    messages: List[Message]
    metadata: Dict[str, Any]  # e.g., ticker symbol, date, etc.

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "task_type": self.task_type.value,
            "user_id": self.user_id,
            "created_at": self.created_at,
            "last_activity": self.last_activity,
            "messages": [msg.to_dict() for msg in self.messages],
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        return cls(
            session_id=data["session_id"],
            task_type=TaskType(data["task_type"]),
            user_id=data["user_id"],
            created_at=data["created_at"],
            last_activity=data["last_activity"],
            messages=[Message.from_dict(msg) for msg in data["messages"]],
            metadata=data.get("metadata", {})
        )

    def add_message(self, role: str, content: Union[str, List[Dict[str, Any]]]) -> None:
        """Add a message and update last activity."""
        self.messages.append(Message(role, content, time.time()))
        self.last_activity = time.time()

    def get_recent_messages(self, max_messages: int = DEFAULT_MAX_MESSAGES) -> List[Dict[str, Any]]:
        """Get recent messages formatted for API."""
        recent = self.messages[-max_messages:]
        return [{"role": msg.role, "content": msg.content} for msg in recent]


class SessionManager:
    """Manages task-isolated conversation sessions."""

    def __init__(self):
        self._lock = threading.RLock()
        self._active_sessions: Dict[str, Session] = {}
        self._user_general_session: Dict[int, Tuple[str, float]] = {}  # user_id -> (session_id, last_activity)
        self._load_existing_sessions()

    def _load_existing_sessions(self) -> None:
        """Load existing session files from disk."""
        with self._lock:
            for file_path in SESSIONS_DIR.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    session = Session.from_dict(data)
                    self._active_sessions[session.session_id] = session
                except Exception as e:
                    logger.error(f"Failed to load session file {file_path}: {e}")
                    # Rename corrupted file
                    corrupted_path = file_path.with_suffix('.json.corrupted')
                    file_path.rename(corrupted_path)

    def _generate_session_id(self, task_type: TaskType, user_id: int,
                           metadata: Dict[str, Any]) -> str:
        """Generate a unique session ID based on task type and metadata."""
        # Create a deterministic hash
        hash_input = f"{task_type.value}_{user_id}_{json.dumps(metadata, sort_keys=True)}"
        hash_digest = hashlib.md5(hash_input.encode()).hexdigest()[:12]

        # Include readable parts
        date_str = datetime.now().strftime("%Y%m%d")
        ticker = metadata.get("ticker", "")
        if ticker:
            return f"{task_type.value}_{ticker}_{date_str}_{hash_digest}"
        else:
            return f"{task_type.value}_{date_str}_{hash_digest}"

    def _get_task_type_from_text(self, text: str) -> TaskType:
        """Determine task type from message text."""
        text_lower = text.lower().strip()

        # Check for commands
        if text_lower.startswith('/'):
            if text_lower.startswith(('/stock', '/analysis', '/scan')):
                return TaskType.STOCK
            elif text_lower.startswith(('/buy', '/sell', '/portfolio')):
                return TaskType.PORTFOLIO
            elif text_lower.startswith(('/alert', '/alerts', '/delalert')):
                return TaskType.ALERTS
            elif text_lower.startswith('/watch'):
                return TaskType.WATCHLIST
            elif text_lower.startswith(('/poly', '/poly_pick')):
                return TaskType.POLY
            elif text_lower.startswith(('/new', '/sessions', '/history')):
                return TaskType.CHAT

        # Check for stock ticker patterns (e.g., numbers, 4-letter codes)
        if re.search(r'\b([0-9]{4}|[A-Z]{1,5})\b', text_lower):
            # Could be stock-related, but default to general
            return TaskType.GENERAL

        return TaskType.CHAT

    def _extract_metadata(self, task_type: TaskType, text: str, user_id: int) -> Dict[str, Any]:
        """Extract metadata from message text for session identification."""
        metadata = {"user_id": user_id}

        if task_type == TaskType.STOCK:
            # Extract stock ticker - skip the command itself
            # For "/stock AAPL", we want "AAPL" not "STOCK"
            words = text.upper().split()
            ticker_candidates = []

            for word in words:
                # Skip command words
                if word in ['/STOCK', '/ANALYSIS', '/SCAN', 'STOCK', 'ANALYSIS', 'SCAN']:
                    continue
                # Check if it looks like a ticker
                if re.fullmatch(r'[0-9]{4}|[A-Z]{1,5}', word):
                    ticker_candidates.append(word)

            # Use the first valid ticker candidate
            if ticker_candidates:
                metadata["ticker"] = ticker_candidates[0]
            else:
                # Fallback: try the original regex but exclude obvious command words
                match = re.search(r'\b(?!STOCK|ANALYSIS|SCAN)([0-9]{4}|[A-Z]{1,5})\b', text.upper())
                if match:
                    metadata["ticker"] = match.group(1)

        elif task_type == TaskType.PORTFOLIO:
            metadata["context"] = "portfolio_management"

        elif task_type == TaskType.ALERTS:
            metadata["context"] = "price_alerts"

        elif task_type == TaskType.WATCHLIST:
            metadata["context"] = "watchlist"

        elif task_type == TaskType.POLY:
            metadata["context"] = "polymarket"

        # Add date for general organization
        metadata["date"] = datetime.now().strftime("%Y-%m-%d")

        return metadata

    def get_or_create_session(self, user_id: int, text: str) -> str:
        """
        Get or create a session for the given user and message.
        Returns session_id.
        """
        with self._lock:
            task_type = self._get_task_type_from_text(text)
            metadata = self._extract_metadata(task_type, text, user_id)

            # For general chat, check if we should create a new session
            if task_type in (TaskType.CHAT, TaskType.GENERAL):
                current_time = time.time()
                if user_id in self._user_general_session:
                    session_id, last_activity = self._user_general_session[user_id]
                    if current_time - last_activity > GENERAL_SESSION_TIMEOUT:
                        # Timeout reached, create new general session
                        task_type = TaskType.CHAT
                        metadata["chat_instance"] = int(current_time)
                        session_id = self._generate_session_id(task_type, user_id, metadata)
                        self._user_general_session[user_id] = (session_id, current_time)
                    else:
                        # Update activity time for existing session
                        self._user_general_session[user_id] = (session_id, current_time)
                        if session_id in self._active_sessions:
                            self._active_sessions[session_id].last_activity = current_time
                        return session_id
                else:
                    # First general message for this user
                    task_type = TaskType.CHAT
                    metadata["chat_instance"] = int(time.time())
                    session_id = self._generate_session_id(task_type, user_id, metadata)
                    self._user_general_session[user_id] = (session_id, time.time())

            else:
                # Task-specific session
                session_id = self._generate_session_id(task_type, user_id, metadata)

            # Check if session already exists
            if session_id in self._active_sessions:
                session = self._active_sessions[session_id]
                session.last_activity = time.time()
                return session_id

            # Create new session
            session = Session(
                session_id=session_id,
                task_type=task_type,
                user_id=user_id,
                created_at=time.time(),
                last_activity=time.time(),
                messages=[],
                metadata=metadata
            )

            self._active_sessions[session_id] = session
            self._save_session(session)

            return session_id

    def add_message(self, session_id: str, role: str, content: Union[str, List[Dict[str, Any]]]) -> None:
        """Add a message to a session."""
        with self._lock:
            if session_id not in self._active_sessions:
                logger.error(f"Session {session_id} not found")
                return

            session = self._active_sessions[session_id]
            session.add_message(role, content)

            # Update general session activity if applicable
            if session.task_type in (TaskType.CHAT, TaskType.GENERAL):
                self._user_general_session[session.user_id] = (session_id, session.last_activity)

            self._save_session(session)

    def get_messages_for_api(self, session_id: str,
                           max_messages: int = DEFAULT_MAX_MESSAGES,
                           max_tokens: int = DEFAULT_MAX_TOKENS) -> List[Dict[str, Any]]:
        """
        Get messages for API call, respecting token limits.
        Returns recent messages, possibly reduced if token limit would be exceeded.
        """
        with self._lock:
            if session_id not in self._active_sessions:
                return []

            session = self._active_sessions[session_id]
            messages = session.get_recent_messages(max_messages)

            # Estimate tokens and reduce if needed
            estimated_tokens = self._estimate_tokens(messages)
            if estimated_tokens <= max_tokens:
                return messages

            # Reduce messages from oldest to newest until under limit
            for i in range(1, len(messages)):
                reduced = messages[i:]  # Remove oldest messages
                if self._estimate_tokens(reduced) <= max_tokens:
                    return reduced

            # If still over limit, return just the last message
            return messages[-1:] if messages else []

    def _estimate_tokens(self, messages: List[Dict[str, Any]]) -> int:
        """Estimate token count for messages."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                # Rough estimation: Chinese chars ~2 tokens, English words ~1.5 tokens
                chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', content))
                english_text = re.sub(r'[\u4e00-\u9fff]', '', content)
                english_words = len(re.findall(r'\b\w+\b', english_text))
                total += chinese_chars * 2 + english_words * 1.5
            elif isinstance(content, list):
                # For content blocks, extract text
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "")
                        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
                        english_text = re.sub(r'[\u4e00-\u9fff]', '', text)
                        english_words = len(re.findall(r'\b\w+\b', english_text))
                        total += chinese_chars * 2 + english_words * 1.5

        return int(total)

    def _save_session(self, session: Session) -> None:
        """Save session to disk."""
        try:
            file_path = SESSIONS_DIR / f"{session.session_id}.json"
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save session {session.session_id}: {e}")

    def get_session(self, session_id: str) -> Optional[Session]:
        """Get session by ID."""
        with self._lock:
            return self._active_sessions.get(session_id)

    def get_user_sessions(self, user_id: int, include_archived: bool = False) -> List[Session]:
        """Get all sessions for a user."""
        with self._lock:
            sessions = []
            for session in self._active_sessions.values():
                if session.user_id == user_id:
                    sessions.append(session)

            if include_archived:
                # Also check archive directory
                for file_path in ARCHIVE_DIR.glob(f"*_{user_id}_*.json"):
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        sessions.append(Session.from_dict(data))
                    except Exception as e:
                        logger.error(f"Failed to load archived session {file_path}: {e}")

            return sorted(sessions, key=lambda s: s.last_activity, reverse=True)

    def create_new_session(self, user_id: int, task_type: Optional[TaskType] = None,
                          metadata: Optional[Dict[str, Any]] = None) -> str:
        """Manually create a new session."""
        with self._lock:
            if task_type is None:
                task_type = TaskType.CHAT

            if metadata is None:
                metadata = {}

            metadata["user_id"] = user_id
            metadata["date"] = datetime.now().strftime("%Y-%m-%d")
            metadata["manual_create"] = True

            session_id = self._generate_session_id(task_type, user_id, metadata)

            # Close any existing general session
            if task_type in (TaskType.CHAT, TaskType.GENERAL):
                self._user_general_session[user_id] = (session_id, time.time())

            # Create new session
            session = Session(
                session_id=session_id,
                task_type=task_type,
                user_id=user_id,
                created_at=time.time(),
                last_activity=time.time(),
                messages=[],
                metadata=metadata
            )

            self._active_sessions[session_id] = session
            self._save_session(session)

            return session_id

    def archive_old_sessions(self) -> int:
        """
        Archive sessions older than ARCHIVE_DAYS days.
        Returns number of sessions archived.
        """
        with self._lock:
            cutoff_time = time.time() - (ARCHIVE_DAYS * 24 * 60 * 60)
            archived_count = 0

            for session_id, session in list(self._active_sessions.items()):
                if session.last_activity < cutoff_time:
                    # Move to archive
                    source_path = SESSIONS_DIR / f"{session_id}.json"
                    archive_path = ARCHIVE_DIR / f"{session_id}.json"

                    if source_path.exists():
                        source_path.rename(archive_path)

                    # Remove from active sessions
                    del self._active_sessions[session_id]

                    # Remove from general session tracking if applicable
                    if session.task_type in (TaskType.CHAT, TaskType.GENERAL):
                        if session.user_id in self._user_general_session:
                            stored_id, _ = self._user_general_session[session.user_id]
                            if stored_id == session_id:
                                del self._user_general_session[session.user_id]

                    archived_count += 1

            return archived_count

    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get a summary of a session."""
        with self._lock:
            session = self._active_sessions.get(session_id)
            if not session:
                return {"error": "Session not found"}

            return {
                "session_id": session_id,
                "task_type": session.task_type.value,
                "created_at": datetime.fromtimestamp(session.created_at).strftime("%Y-%m-%d %H:%M:%S"),
                "last_activity": datetime.fromtimestamp(session.last_activity).strftime("%Y-%m-%d %H:%M:%S"),
                "message_count": len(session.messages),
                "metadata": session.metadata
            }


# Global session manager instance
_session_manager = None

def get_session_manager() -> SessionManager:
    """Get the global session manager instance."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager