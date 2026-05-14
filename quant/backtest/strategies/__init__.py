"""量化策略模板庫。

此包提供標準化的策略模板，方便快速開發和測試新的交易策略。
"""

from .base_strategies import (
    MovingAverageCrossover,
    BollingerBandsStrategy,
    RSIStrategy,
    MACDStrategy,
    CombinedStrategy,
    create_strategy,
)
from .crypto_strategies import (
    TrendFollowingStrategy,
    GridRecoveryStrategy,
    VolatilityBreakoutStrategy,
)

__all__ = [
    "MovingAverageCrossover",
    "BollingerBandsStrategy",
    "RSIStrategy",
    "MACDStrategy",
    "CombinedStrategy",
    "TrendFollowingStrategy",
    "GridRecoveryStrategy",
    "VolatilityBreakoutStrategy",
    "create_strategy",
]