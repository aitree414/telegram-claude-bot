import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

WATCHLIST_FILE = Path.home() / "telegram-claude-bot" / "watchlist.json"

# 同步寫入回測自選清單（供夜間回測引擎讀取）
_BACKTEST_CSV = Path.home() / "Documents/investment/airdrop_hunter/backtest/watchlist.csv"


class WatchlistManager:
    def __init__(self) -> None:
        self._symbols: list[str] = []
        self._names: dict[str, str] = {}   # code → name
        self._load()

    def _load(self) -> None:
        if WATCHLIST_FILE.exists():
            try:
                data = json.loads(WATCHLIST_FILE.read_text())
                self._symbols = data.get("symbols", [])
                self._names = data.get("names", {})
            except Exception:
                logger.exception("載入 watchlist 失敗")

    def _save(self) -> None:
        try:
            WATCHLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
            WATCHLIST_FILE.write_text(
                json.dumps(
                    {"symbols": self._symbols, "names": self._names},
                    ensure_ascii=False,
                    indent=2,
                )
            )
        except Exception:
            logger.exception("儲存 watchlist 失敗")
        # 同步到回測 CSV
        self._sync_backtest_csv()

    def _sync_backtest_csv(self) -> None:
        """同步自選清單至 backtest/watchlist.csv（供夜間回測引擎使用）"""
        try:
            _BACKTEST_CSV.parent.mkdir(parents=True, exist_ok=True)
            with open(_BACKTEST_CSV, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["code", "name", "note"])
                writer.writeheader()
                for code in self._symbols:
                    writer.writerow({
                        "code": code,
                        "name": self._names.get(code, ""),
                        "note": "Telegram",
                    })
            logger.info("backtest watchlist.csv 已同步（%d 檔）", len(self._symbols))
        except Exception as e:
            logger.warning("同步 backtest CSV 失敗: %s", e)

    def add(self, symbol: str, name: str = "") -> bool:
        """Add symbol. Returns False if already in list."""
        symbol = symbol.upper().strip()
        if symbol in self._symbols:
            return False
        self._symbols = [*self._symbols, symbol]
        if name:
            self._names[symbol] = name.strip()
        self._save()
        return True

    def remove(self, symbol: str) -> bool:
        """Remove symbol. Returns False if not found."""
        symbol = symbol.upper().strip()
        new_list = [s for s in self._symbols if s != symbol]
        if len(new_list) == len(self._symbols):
            return False
        self._symbols = new_list
        self._names.pop(symbol, None)
        self._save()
        return True

    def list_symbols(self) -> list[str]:
        return list(self._symbols)

    def get_name(self, symbol: str) -> str:
        return self._names.get(symbol.upper(), "")
