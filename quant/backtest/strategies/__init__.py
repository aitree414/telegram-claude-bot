"""量化策略模板庫。

此包提供標準化的策略模板，方便快速開發和測試新的交易策略。
"""

from .base_strategies import (
    MovingAverageCrossover,
    BollingerBandsStrategy,
    RSIStrategy,
    MACDStrategy,
    CombinedStrategy
)

__all__ = [
    "MovingAverageCrossover",
    "BollingerBandsStrategy",
    "RSIStrategy",
    "MACDStrategy",
    "CombinedStrategy",
]