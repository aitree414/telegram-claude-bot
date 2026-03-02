import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ALERTS_FILE = Path.home() / "telegram-claude-bot" / "alerts.json"


class AlertManager:
    def __init__(self) -> None:
        self._alerts: list[dict[str, Any]] = []
        self._next_id = 1
        self._lock = threading.RLock()
        self._load()

    def _load(self) -> None:
        with self._lock:
            if ALERTS_FILE.exists():
                try:
                    data = json.loads(ALERTS_FILE.read_text())
                    self._alerts = data.get("alerts", [])
                    self._next_id = data.get("next_id", 1)
                except Exception:
                    logger.exception("載入提醒失敗")

    def _save(self) -> None:
        with self._lock:
            try:
                ALERTS_FILE.write_text(
                    json.dumps({"alerts": self._alerts, "next_id": self._next_id}, ensure_ascii=False, indent=2)
                )
            except Exception:
                logger.exception("儲存提醒失敗")

    def add(self, user_id: int, symbol: str, condition: str, target: float) -> int:
        with self._lock:
            alert_id = self._next_id
            self._alerts.append({
                "id": alert_id,
                "user_id": user_id,
                "symbol": symbol,
                "condition": condition,  # "above" or "below"
                "target": target,
                "triggered": False,
            })
            self._next_id += 1
            self._save()
            return alert_id

    def remove(self, user_id: int, alert_id: int) -> bool:
        with self._lock:
            before = len(self._alerts)
            self._alerts = [
                a for a in self._alerts
                if not (a["id"] == alert_id and a["user_id"] == user_id)
            ]
            if len(self._alerts) < before:
                self._save()
                return True
            return False

    def list_alerts(self, user_id: int) -> list[dict[str, Any]]:
        with self._lock:
            return [a for a in self._alerts if a["user_id"] == user_id and not a["triggered"]]

    def get_pending(self) -> list[dict[str, Any]]:
        with self._lock:
            return [a for a in self._alerts if not a["triggered"]]

    def mark_triggered(self, alert_id: int) -> None:
        with self._lock:
            for a in self._alerts:
                if a["id"] == alert_id:
                    a["triggered"] = True
            self._save()
