import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

WATCHLIST_FILE = Path.home() / "telegram-claude-bot" / "watchlist.json"


class WatchlistManager:
    def __init__(self) -> None:
        self._symbols: list[str] = []
        self._load()

    def _load(self) -> None:
        if WATCHLIST_FILE.exists():
            try:
                data = json.loads(WATCHLIST_FILE.read_text())
                self._symbols = data.get("symbols", [])
            except Exception:
                logger.exception("載入 watchlist 失敗")

    def _save(self) -> None:
        try:
            WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            WATCHLIST_FILE.write_text(
                json.dumps({"symbols": self._symbols}, ensure_ascii=False, indent=2)
            )
        except Exception:
            logger.exception("儲存 watchlist 失敗")

    def add(self, symbol: str) -> bool:
        """Add symbol. Returns False if already in list."""
        if symbol in self._symbols:
            return False
        self._symbols = [*self._symbols, symbol]
        self._save()
        return True

    def remove(self, symbol: str) -> bool:
        """Remove symbol. Returns False if not found."""
        new_list = [s for s in self._symbols if s != symbol]
        if len(new_list) == len(self._symbols):
            return False
        self._symbols = new_list
        self._save()
        return True

    def list_symbols(self) -> list[str]:
        return list(self._symbols)
