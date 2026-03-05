"""跨市場決策聯動模組 (Market Linker)

此模組監控 Polymarket 預測市場情緒，並將其轉化為 Hyperliquid 網格交易的風險調整信號。
實現 Polymarket 情緒分析與 Hyperliquid 實盤交易的跨市場聯動。
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
import sqlite3
from pathlib import Path

# Import existing Polymarket analysis modules
try:
    from bot.poly_analyzer import _fetch_markets, _parse_market
    POLY_ANALYZER_AVAILABLE = True
except ImportError:
    POLY_ANALYZER_AVAILABLE = False
    logging.warning("bot.poly_analyzer not available, falling back to direct API calls")

logger = logging.getLogger(__name__)


class MarketLinker:
    """跨市場決策聯動引擎"""

    def __init__(self, db_path: Optional[str] = None):
        """初始化 Market Linker。

        Args:
            db_path: SQLite 數據庫路徑，用於存儲市場狀態歷史。
        """
        if db_path is None:
            db_path = Path(__file__).parent.parent.parent / "data" / "market_linker.db"
            db_path.parent.mkdir(parents=True, exist_ok=True)

        self.db_path = Path(db_path)
        self._init_database()

        # 關鍵詞映射：Polymarket 事件到交易標的
        self.keyword_mapping = {
            "SOL": ["SOL", "Solana", "SOL price", "Solana price"],
            "BTC": ["BTC", "Bitcoin", "Bitcoin price"],
            "ETH": ["ETH", "Ethereum", "Ethereum price"],
            "NASDAQ": ["NASDAQ", "stock market", "S&P 500", "stock"],
            "FED": ["Fed", "Federal Reserve", "interest rate", "FOMC"],
        }

        # 信號配置
        self.signal_config = {
            "volatility_threshold": 0.15,  # 價格變化超過 15% 觸發波動率預警
            "confidence_threshold": 0.75,  # 信心門檻 75%
            "cooldown_hours": 6,  # 相同市場冷卻時間（小時）
            "max_signals_per_day": 10,  # 每日最大信號數量
        }

    def _init_database(self) -> None:
        """初始化數據庫表格"""
        with sqlite3.connect(self.db_path) as conn:
            # 市場狀態歷史
            conn.execute("""
                CREATE TABLE IF NOT EXISTS market_states (
                    market_id TEXT NOT NULL,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    outcome_prices TEXT NOT NULL,  -- JSON array of prices
                    volume REAL,
                    PRIMARY KEY (market_id, timestamp)
                )
            """)

            # 生成的信號
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source_market_id TEXT,
                    source_question TEXT,
                    signal_type TEXT NOT NULL,
                    signal_data TEXT NOT NULL,  -- JSON
                    processed BOOLEAN DEFAULT FALSE,
                    processed_at TIMESTAMP,
                    target_module TEXT NOT NULL
                )
            """)

            # 創建索引
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_market_states_market
                ON market_states (market_id, timestamp DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_unprocessed
                ON signals (processed, timestamp)
            """)

    def scan_polymarket_for_sol_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        """掃描 Polymarket 中與 SOL 相關的事件。

        Args:
            limit: 最大市場數量

        Returns:
            與 SOL 相關的市場列表
        """
        try:
            if POLY_ANALYZER_AVAILABLE:
                markets_raw = _fetch_markets(limit=limit)
                markets = [_parse_market(r) for r in markets_raw]
                markets = [m for m in markets if m is not None]
            else:
                # Fallback: 直接調用 polymarket.py 的函數
                from bot.polymarket import get_trending_markets
                # 注意：需要解析返回的字符串，這裡簡化處理
                markets = []
                logger.warning("使用簡化版的 Polymarket 掃描（需要完整實現）")
        except Exception as e:
            logger.error(f"掃描 Polymarket 失敗: {e}")
            return []

        # 過濾出與 SOL 相關的市場
        sol_keywords = self.keyword_mapping["SOL"]
        sol_markets = []

        for market in markets:
            question = market.get("question", "").lower()
            # 檢查是否包含 SOL 相關關鍵詞
            if any(keyword.lower() in question for keyword in sol_keywords):
                sol_markets.append(market)

        logger.info(f"找到 {len(sol_markets)} 個 SOL 相關市場")
        return sol_markets

    def analyze_market_volatility(self, market: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """分析市場波動率並檢測顯著變化。

        Args:
            market: 市場數據字典

        Returns:
            波動率分析結果，或 None 如果無顯著變化
        """
        market_id = market.get("id", "")
        if not market_id:
            return None

        # 獲取當前價格
        outcomes = market.get("outcomes", [])  # 格式: [(outcome, price), ...]
        if not outcomes:
            return None

        # 獲取歷史狀態（最近 24 小時）
        historical_states = self._get_market_states(market_id, hours=24)

        if len(historical_states) < 2:
            # 沒有足夠歷史數據，存儲當前狀態
            self._store_market_state(market)
            return None

        # 計算主要結果的價格變化
        primary_outcome = outcomes[0][0] if outcomes else None
        current_price = outcomes[0][1] if outcomes else 0

        # 查找歷史價格
        historical_prices = []
        for state in historical_states:
            try:
                prices_json = state[2]  # outcome_prices 列
                prices = json.loads(prices_json)
                if prices and len(prices) > 0:
                    historical_prices.append(prices[0])  # 假設第一個結果是主要的
            except (json.JSONDecodeError, IndexError):
                continue

        if not historical_prices:
            return None

        # 計算價格變化
        avg_historical_price = sum(historical_prices) / len(historical_prices)
        price_change = abs(current_price - avg_historical_price) / avg_historical_price

        # 檢查是否超過波動率閾值
        if price_change >= self.signal_config["volatility_threshold"]:
            # 檢查冷卻時間
            if self._is_in_cooldown(market_id):
                logger.info(f"市場 {market_id} 在冷卻期內，跳過信號生成")
                return None

            # 檢查每日信號限制
            if not self._can_generate_signal():
                logger.warning("達到每日信號生成限制")
                return None

            analysis = {
                "market_id": market_id,
                "question": market.get("question", ""),
                "primary_outcome": primary_outcome,
                "current_price": current_price,
                "historical_avg_price": avg_historical_price,
                "price_change": price_change,
                "volume": market.get("volume", 0),
                "is_volatile": True,
                "confidence": min(0.9, price_change * 2),  # 簡單信心計算
            }

            # 存儲當前狀態
            self._store_market_state(market)

            return analysis

        # 存儲當前狀態（即使沒有信號）
        self._store_market_state(market)
        return None

    def generate_hyperliquid_signal(self, volatility_analysis: Dict[str, Any]) -> Dict[str, Any]:
        """根據波動率分析生成 Hyperliquid 交易信號。

        Args:
            volatility_analysis: 波動率分析結果

        Returns:
            Hyperliquid 信號字典
        """
        price_change = volatility_analysis["price_change"]
        confidence = volatility_analysis["confidence"]
        volume = volatility_analysis["volume"]

        # 決策邏輯
        if price_change > 0.25 and confidence > 0.8:
            # 極端波動：暫停交易
            signal_type = "pause_trading"
            signal_data = {
                "reason": f"Polymarket SOL 事件波動率極高: {price_change:.1%}",
                "duration_minutes": 120,  # 暫停 2 小時
                "resume_condition": "volatility_decreases",
                "confidence": confidence,
                "source_market": volatility_analysis["question"],
            }
        elif price_change > 0.15 and confidence > 0.7:
            # 高波動：調整網格區間
            signal_type = "adjust_grid_range"
            # 根據波動率調整網格大小（波動率越高，區間越大）
            base_range = 0.02  # 2% 基礎網格
            adjusted_range = base_range * (1 + price_change * 2)  # 放大網格
            signal_data = {
                "reason": f"Polymarket SOL 事件波動率增加: {price_change:.1%}",
                "new_range_size": min(adjusted_range, 0.10),  # 最大 10%
                "adjustment_factor": 1 + price_change,
                "confidence": confidence,
                "volume_indicator": "high" if volume > 50000 else "medium",
                "source_market": volatility_analysis["question"],
            }
        else:
            # 中等波動：調整網格密度
            signal_type = "adjust_grid_density"
            signal_data = {
                "reason": f"Polymarket SOL 事件波動率變化: {price_change:.1%}",
                "action": "reduce_density" if price_change > 0.1 else "maintain",
                "confidence": confidence,
                "source_market": volatility_analysis["question"],
            }

        signal = {
            "signal_id": f"hyperliquid_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now().isoformat(),
            "signal_type": signal_type,
            "signal_data": signal_data,
            "target_module": "hyperliquid_grid_sol",
            "source": {
                "module": "market_linker",
                "analysis_type": "polymarket_volatility",
                "market_id": volatility_analysis["market_id"],
            },
        }

        # 存儲信號到數據庫
        self._store_signal(signal)

        return signal

    def monitor_and_generate_signals(self) -> List[Dict[str, Any]]:
        """主監控循環：掃描市場並生成信號。

        Returns:
            生成的信號列表
        """
        signals = []

        # 掃描 SOL 相關市場
        sol_markets = self.scan_polymarket_for_sol_events(limit=30)

        for market in sol_markets:
            try:
                analysis = self.analyze_market_volatility(market)
                if analysis and analysis.get("is_volatile"):
                    signal = self.generate_hyperliquid_signal(analysis)
                    signals.append(signal)
                    logger.info(f"生成信號: {signal['signal_type']} for {market.get('question', 'unknown')}")
            except Exception as e:
                logger.error(f"處理市場時出錯: {e}")
                continue

        return signals

    def _get_market_states(self, market_id: str, hours: int = 24) -> List[tuple]:
        """獲取市場歷史狀態"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT market_id, timestamp, outcome_prices, volume
                FROM market_states
                WHERE market_id = ?
                AND timestamp > datetime('now', ?)
                ORDER BY timestamp DESC
            """, (market_id, f"-{hours} hours"))
            return cursor.fetchall()

    def _store_market_state(self, market: Dict[str, Any]) -> None:
        """存儲市場狀態到數據庫"""
        market_id = market.get("id", "")
        if not market_id:
            return

        outcomes = market.get("outcomes", [])
        prices = [price for _, price in outcomes]
        volume = market.get("volume", 0)

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO market_states (market_id, outcome_prices, volume)
                    VALUES (?, ?, ?)
                """, (market_id, json.dumps(prices), volume))
        except Exception as e:
            logger.error(f"存儲市場狀態失敗: {e}")

    def _store_signal(self, signal: Dict[str, Any]) -> None:
        """存儲信號到數據庫"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO signals (
                        source_market_id, source_question,
                        signal_type, signal_data, target_module
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    signal["source"]["market_id"],
                    signal["source"]["module"],
                    signal["signal_type"],
                    json.dumps(signal["signal_data"]),
                    signal["target_module"],
                ))
        except Exception as e:
            logger.error(f"存儲信號失敗: {e}")

    def _is_in_cooldown(self, market_id: str) -> bool:
        """檢查市場是否在冷卻期內"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM signals
                WHERE source_market_id = ?
                AND timestamp > datetime('now', ?)
                AND processed = FALSE
            """, (market_id, f"-{self.signal_config['cooldown_hours']} hours"))
            count = cursor.fetchone()[0]
            return count > 0

    def _can_generate_signal(self) -> bool:
        """檢查是否可以生成新信號（每日限制）"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT COUNT(*) FROM signals
                WHERE DATE(timestamp) = DATE('now')
            """)
            count = cursor.fetchone()[0]
            return count < self.signal_config["max_signals_per_day"]

    def get_pending_signals(self, target_module: Optional[str] = None) -> List[Dict[str, Any]]:
        """獲取待處理的信號。

        Args:
            target_module: 過濾目標模塊（如 "hyperliquid_grid_sol"）

        Returns:
            待處理信號列表
        """
        query = """
            SELECT signal_id, timestamp, source_market_id, source_question,
                   signal_type, signal_data, target_module
            FROM signals
            WHERE processed = FALSE
        """
        params = []

        if target_module:
            query += " AND target_module = ?"
            params.append(target_module)

        query += " ORDER BY timestamp ASC"

        signals = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query, params)
            for row in cursor.fetchall():
                signal_id, timestamp, market_id, question, signal_type, signal_data_json, target = row
                try:
                    signal_data = json.loads(signal_data_json)
                    signals.append({
                        "signal_id": signal_id,
                        "timestamp": timestamp,
                        "source_market_id": market_id,
                        "source_question": question,
                        "signal_type": signal_type,
                        "signal_data": signal_data,
                        "target_module": target,
                    })
                except json.JSONDecodeError:
                    continue

        return signals

    def mark_signal_processed(self, signal_id: int) -> bool:
        """標記信號為已處理。

        Args:
            signal_id: 信號 ID

        Returns:
            成功返回 True，否則 False
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE signals
                    SET processed = TRUE, processed_at = CURRENT_TIMESTAMP
                    WHERE signal_id = ?
                """, (signal_id,))
                return True
        except Exception as e:
            logger.error(f"標記信號為已處理失敗: {e}")
            return False


# 單例實例
_linker_instance = None

def get_market_linker() -> MarketLinker:
    """獲取 MarketLinker 單例實例。"""
    global _linker_instance
    if _linker_instance is None:
        _linker_instance = MarketLinker()
    return _linker_instance