"""系統錯誤處理與自動重啟機制。

此模組提供全局錯誤處理、Telegram 錯誤通知和自動重啟功能，
增強系統健壯性與可維護性。
"""

import sys
import logging
import traceback
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import atexit
import threading

# 嘗試導入 Telegram bot 配置
try:
    from bot.config import get_config
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    logging.warning("bot.config 不可用，Telegram 錯誤通知將被禁用")

# 日誌配置
ERROR_LOG_DIR = Path(__file__).parent.parent / "logs"
ERROR_LOG_DIR.mkdir(parents=True, exist_ok=True)
ERROR_LOG_FILE = ERROR_LOG_DIR / "error_history.log"

# 配置日誌記錄器
logging.basicConfig(
    level=logging.ERROR,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(ERROR_LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)


class ErrorHandler:
    """全局錯誤處理器與系統監控"""

    def __init__(self, restart_on_critical: bool = True, max_restarts: int = 3):
        """初始化錯誤處理器。

        Args:
            restart_on_critical: 是否在嚴重錯誤時自動重啟
            max_restarts: 最大重啟次數（防止重啟循環）
        """
        self.restart_on_critical = restart_on_critical
        self.max_restarts = max_restarts
        self.restart_count = 0
        self.last_restart_time = 0
        self.restart_cooldown = 300  # 重啟冷卻時間（秒）

        # 錯誤統計
        self.error_stats = {
            "total_errors": 0,
            "critical_errors": 0,
            "last_error_time": None,
            "errors_by_type": {}
        }

        # Telegram 通知配置
        self.telegram_enabled = TELEGRAM_AVAILABLE
        self.notification_cooldown = 600  # 通知冷卻時間（秒）
        self.last_notification_time = 0

        # 註冊全局異常鉤子
        self._original_excepthook = sys.excepthook
        sys.excepthook = self.global_exception_handler

        # 註冊退出處理器
        atexit.register(self.cleanup)

        logger.info("全局錯誤處理器已初始化")

    def global_exception_handler(self, exc_type, exc_value, exc_traceback):
        """全局異常處理器，捕獲所有未處理的異常。"""
        # 更新錯誤統計
        self.error_stats["total_errors"] += 1
        self.error_stats["last_error_time"] = datetime.now().isoformat()

        error_name = exc_type.__name__
        self.error_stats["errors_by_type"][error_name] = \
            self.error_stats["errors_by_type"].get(error_name, 0) + 1

        # 判斷是否為嚴重錯誤
        is_critical = self._is_critical_error(exc_type, exc_value)
        if is_critical:
            self.error_stats["critical_errors"] += 1

        # 記錄錯誤
        error_msg = self._format_error(exc_type, exc_value, exc_traceback)
        logger.error(f"未處理的異常: {error_msg}")

        # 發送 Telegram 通知
        if self.telegram_enabled:
            self._send_telegram_notification(error_msg, is_critical)

        # 如果是嚴重錯誤且啟用重啟，則嘗試重啟
        if is_critical and self.restart_on_critical:
            self._attempt_restart()

        # 調用原始異常鉤子（通常會終止程序）
        self._original_excepthook(exc_type, exc_value, exc_traceback)

    def handle_error(self, error: Exception, context: str = "") -> Dict[str, Any]:
        """手動處理錯誤（用於捕獲的異常）。

        Args:
            error: 異常實例
            context: 錯誤上下文描述

        Returns:
            處理結果字典
        """
        error_name = error.__class__.__name__
        error_msg = str(error)

        # 更新統計
        self.error_stats["total_errors"] += 1
        self.error_stats["errors_by_type"][error_name] = \
            self.error_stats["errors_by_type"].get(error_name, 0) + 1
        self.error_stats["last_error_time"] = datetime.now().isoformat()

        # 記錄錯誤
        full_context = f"{context}: " if context else ""
        logger.error(f"{full_context}{error_name}: {error_msg}")

        # 檢查是否需要通知
        if self.telegram_enabled and self._should_notify():
            self._send_telegram_notification(
                f"{full_context}{error_name}: {error_msg}",
                is_critical=False
            )

        return {
            "handled": True,
            "error_type": error_name,
            "error_message": error_msg,
            "context": context,
            "timestamp": datetime.now().isoformat()
        }

    def wrap_function(self, func: Callable, func_name: str = "") -> Callable:
        """包裝函數以自動捕獲和處理錯誤。

        Args:
            func: 要包裝的函數
            func_name: 函數名稱（用於錯誤報告）

        Returns:
            包裝後的函數
        """
        if not func_name:
            func_name = func.__name__

        def wrapped(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                self.handle_error(e, f"函數 {func_name} 執行失敗")
                raise  # 重新拋出異常

        return wrapped

    def _is_critical_error(self, exc_type, exc_value) -> bool:
        """判斷是否為嚴重錯誤（需要重啟）。"""
        critical_errors = [
            "MemoryError",
            "SystemExit",
            "KeyboardInterrupt",  # 雖然是用户中斷，但視為嚴重
            "OSError",
            "IOError",
            "ConnectionError",
            "TimeoutError",
        ]

        error_name = exc_type.__name__
        return error_name in critical_errors

    def _format_error(self, exc_type, exc_value, exc_traceback) -> str:
        """格式化錯誤信息。"""
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_traceback)
        tb_text = "".join(tb_lines[-5:])  # 只取最後 5 行堆棧跟踪

        error_msg = f"{exc_type.__name__}: {exc_value}\n\n堆棧跟踪:\n{tb_text}"
        return error_msg[:2000]  # 限制長度

    def _send_telegram_notification(self, error_msg: str, is_critical: bool) -> None:
        """發送 Telegram 錯誤通知。"""
        try:
            # 檢查冷卻時間
            current_time = time.time()
            if current_time - self.last_notification_time < self.notification_cooldown:
                return

            from telegram import Bot
            from telegram.error import TelegramError

            config = get_config()
            if not config.telegram_bot_token:
                logger.warning("Telegram bot token 未配置")
                return

            bot = Bot(token=config.telegram_bot_token)
            chat_id = config.authorized_user_id

            if chat_id == 0:
                logger.warning("未配置授權用戶 ID，無法發送通知")
                return

            # 格式化消息
            prefix = "🚨 嚴重錯誤" if is_critical else "⚠️ 系統錯誤"
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            message = (
                f"{prefix}\n"
                f"時間: {timestamp}\n"
                f"錯誤: {error_msg[:1000]}..." if len(error_msg) > 1000 else error_msg
            )

            # 發送消息
            bot.send_message(chat_id=chat_id, text=message)
            self.last_notification_time = current_time

            logger.info("Telegram 錯誤通知已發送")

        except ImportError:
            logger.warning("python-telegram-bot 不可用，無法發送 Telegram 通知")
            self.telegram_enabled = False
        except TelegramError as e:
            logger.error(f"發送 Telegram 通知失敗: {e}")
        except Exception as e:
            logger.error(f"發送通知時發生未預期錯誤: {e}")

    def _attempt_restart(self) -> None:
        """嘗試重啟系統。"""
        current_time = time.time()

        # 檢查冷卻時間
        if current_time - self.last_restart_time < self.restart_cooldown:
            logger.warning(f"重啟冷卻中，請等待 {self.restart_cooldown} 秒")
            return

        # 檢查最大重啟次數
        if self.restart_count >= self.max_restarts:
            logger.error(f"已達到最大重啟次數 ({self.max_restarts})，停止重啟")
            return

        self.restart_count += 1
        self.last_restart_time = current_time

        logger.warning(f"嘗試重啟系統 (第 {self.restart_count} 次)")

        # 發送重啟通知
        if self.telegram_enabled:
            self._send_restart_notification()

        # 實際重啟邏輯（需要根據具體部署調整）
        self._perform_restart()

    def _send_restart_notification(self) -> None:
        """發送重啟通知。"""
        try:
            from telegram import Bot

            config = get_config()
            bot = Bot(token=config.telegram_bot_token)
            chat_id = config.authorized_user_id

            message = (
                "🔄 系統重啟中\n"
                f"時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"重啟次數: {self.restart_count}/{self.max_restarts}\n"
                f"最後錯誤: {self.error_stats['last_error_time']}"
            )

            bot.send_message(chat_id=chat_id, text=message)
        except Exception as e:
            logger.error(f"發送重啟通知失敗: {e}")

    def _perform_restart(self) -> None:
        """執行實際的重啟操作。"""
        # 這裡需要根據你的部署方式調整
        # 範例：使用 PM2 重啟
        try:
            # 方法 1: 使用 PM2（如果使用 PM2 管理）
            subprocess.run(["pm2", "restart", "airdrop-hunter"], check=True)
            logger.info("PM2 重啟命令已執行")
        except (subprocess.SubprocessError, FileNotFoundError):
            # 方法 2: 使用 Python 重啟當前進程
            logger.warning("PM2 不可用，嘗試 Python 重啟")
            self._restart_python_process()

    def _restart_python_process(self) -> None:
        """重啟當前 Python 進程。"""
        # 這是一個簡單的重啟方法，可能不是最穩健的
        python = sys.executable
        script = sys.argv[0]

        # 在子線程中執行重啟，避免阻塞
        def restart():
            time.sleep(2)  # 給清理操作一點時間
            subprocess.Popen([python, script] + sys.argv[1:])
            sys.exit(0)

        thread = threading.Thread(target=restart)
        thread.daemon = True
        thread.start()

    def _should_notify(self) -> bool:
        """檢查是否應該發送通知。"""
        current_time = time.time()
        return current_time - self.last_notification_time >= self.notification_cooldown

    def get_error_stats(self) -> Dict[str, Any]:
        """獲取錯誤統計信息。"""
        return self.error_stats.copy()

    def reset_stats(self) -> None:
        """重置錯誤統計。"""
        self.error_stats = {
            "total_errors": 0,
            "critical_errors": 0,
            "last_error_time": None,
            "errors_by_type": {}
        }
        self.restart_count = 0
        logger.info("錯誤統計已重置")

    def cleanup(self) -> None:
        """清理資源。"""
        logger.info("錯誤處理器正在清理...")
        # 恢復原始異常鉤子
        sys.excepthook = self._original_excepthook


# 全局錯誤處理器實例
_error_handler_instance = None

def get_error_handler() -> ErrorHandler:
    """獲取全局錯誤處理器實例。"""
    global _error_handler_instance
    if _error_handler_instance is None:
        _error_handler_instance = ErrorHandler()
    return _error_handler_instance

def init_error_handler() -> ErrorHandler:
    """初始化並返回錯誤處理器（用於主程序入口）。"""
    return get_error_handler()

def handle_error(error: Exception, context: str = "") -> Dict[str, Any]:
    """便捷函數：處理錯誤。"""
    return get_error_handler().handle_error(error, context)

def wrap_function(func: Callable, func_name: str = "") -> Callable:
    """便捷函數：包裝函數以捕獲錯誤。"""
    return get_error_handler().wrap_function(func, func_name)